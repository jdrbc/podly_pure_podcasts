"""Helpers for managing the singleton JobsManagerRun row."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional, cast

from sqlalchemy import func

from app.models import JobsManagerRun, ProcessingJob

logger = logging.getLogger("writer")

SINGLETON_RUN_ID = "jobs-manager-singleton"


def _session_get(session: Any, ident: str) -> Optional[JobsManagerRun]:
    """Get a JobsManagerRun by id from a session-like object.

    Accepts both modern Session objects that implement .get(model, id)
    and older SQLAlchemy session objects where .query(...).get(id) is used.
    Returns None if not found.
    """
    getter = getattr(session, "get", None)
    if callable(getter):
        return cast(Optional[JobsManagerRun], getter(JobsManagerRun, ident))
    # Fallback for older SQLAlchemy versions
    return cast(Optional[JobsManagerRun], session.query(JobsManagerRun).get(ident))


def _build_context_payload(
    trigger: str, context: Optional[Dict[str, object]], updated_at: datetime
) -> Dict[str, object]:
    payload: Dict[str, object] = {}
    if context:
        payload.update(context)
    payload["last_trigger"] = trigger
    payload["last_trigger_at"] = updated_at.isoformat()
    return payload


def get_or_create_singleton_run(
    session: Any, trigger: str, context: Optional[Dict[str, object]] = None
) -> JobsManagerRun:
    """Return the singleton run, creating it if necessary."""
    now = datetime.utcnow()
    run = _session_get(session, SINGLETON_RUN_ID)
    if run:
        run.trigger = trigger
        run.context_json = _build_context_payload(trigger, context, now)
        run.updated_at = now
        if not run.started_at:
            run.started_at = now
        if not run.counters_reset_at:
            run.counters_reset_at = run.started_at or now
        session.flush()
        return run

    run = JobsManagerRun(
        id=SINGLETON_RUN_ID,
        status="running",
        trigger=trigger,
        started_at=now,
        counters_reset_at=now,
        created_at=now,
        updated_at=now,
        context_json=_build_context_payload(trigger, context, now),
    )
    session.add(run)
    session.flush()
    return run


def ensure_active_run(
    session: Any, trigger: str, context: Optional[Dict[str, object]] = None
) -> JobsManagerRun:
    """Return the singleton run, ensuring it exists and is up to date."""
    return get_or_create_singleton_run(session, trigger, context)


def get_active_run(session: Any) -> Optional[JobsManagerRun]:
    """Return the singleton run if it exists."""
    return _session_get(session, SINGLETON_RUN_ID)


def recalculate_run_counts(session: Any) -> Optional[JobsManagerRun]:
    """
    Recompute aggregate counters for the singleton run.

    When no jobs remain in the system the counters are reset to zero so the UI
    reflects an idle manager.
    """
    run = get_active_run(session)
    if not run:
        return None

    cutoff = run.counters_reset_at
    # The linter incorrectly flags func.count as not callable.
    query = session.query(
        ProcessingJob.status,
        func.count(ProcessingJob.id),  # pylint: disable=not-callable
    ).filter(ProcessingJob.jobs_manager_run_id == run.id)
    if cutoff:
        query = query.filter(ProcessingJob.created_at >= cutoff)
    counts = dict(query.group_by(ProcessingJob.status).all())

    logger.debug(
        "[WRITER] recalculate_run_counts: run_id=%s counts=%s",
        getattr(run, "id", None),
        counts,
    )

    now = datetime.utcnow()
    queued = counts.get("pending", 0) + counts.get("queued", 0)
    running = counts.get("running", 0)
    completed = counts.get("completed", 0)
    failed = counts.get("failed", 0) + counts.get("cancelled", 0)
    skipped = counts.get("skipped", 0)
    total_jobs = sum(counts.values())

    has_active_work = (queued + running) > 0

    if has_active_work:
        run.total_jobs = total_jobs
        run.queued_jobs = queued
        run.running_jobs = running
        run.completed_jobs = completed
        run.failed_jobs = failed
        if hasattr(run, "skipped_jobs"):
            run.skipped_jobs = skipped
        run.updated_at = now
        if run.running_jobs > 0:
            run.status = "running"
        else:
            run.status = "pending"
        if not run.started_at:
            run.started_at = now
        if not run.counters_reset_at:
            run.counters_reset_at = run.started_at or now
        run.completed_at = None
    else:
        run.status = "pending"
        run.completed_at = now
        run.started_at = None
        run.total_jobs = 0
        run.queued_jobs = 0
        run.running_jobs = 0
        run.completed_jobs = 0
        run.failed_jobs = 0
        if hasattr(run, "skipped_jobs"):
            run.skipped_jobs = 0
        run.updated_at = now
        run.counters_reset_at = now

    session.flush()
    return run


def serialize_run(run: JobsManagerRun) -> Dict[str, object]:
    """Return a JSON-serialisable representation of a run."""
    progress_denom = max(run.total_jobs or 0, 1)
    progress_percentage = (
        ((run.completed_jobs + getattr(run, "skipped_jobs", 0)) / progress_denom)
        * 100.0
        if run.total_jobs
        else 0.0
    )

    return {
        "id": run.id,
        "status": run.status,
        "trigger": run.trigger,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "total_jobs": run.total_jobs,
        "queued_jobs": run.queued_jobs,
        "running_jobs": run.running_jobs,
        "completed_jobs": run.completed_jobs,
        "failed_jobs": run.failed_jobs,
        "skipped_jobs": getattr(run, "skipped_jobs", 0),
        "context": run.context_json,
        "counters_reset_at": (
            run.counters_reset_at.isoformat() if run.counters_reset_at else None
        ),
        "progress_percentage": round(progress_percentage, 2),
    }


def build_run_status_snapshot(session: Any) -> Optional[Dict[str, object]]:
    """
    Return a fresh, non-persisted snapshot of the current run counters.

    This mirrors recalculate_run_counts but does not mutate or flush the
    JobsManagerRun row, making it safe for high-frequency polling without
    competing for SQLite write locks.
    """
    run = get_active_run(session)
    if not run:
        return None

    cutoff = run.counters_reset_at
    query = session.query(
        ProcessingJob.status,
        func.count(ProcessingJob.id),  # pylint: disable=not-callable
    ).filter(ProcessingJob.jobs_manager_run_id == run.id)
    if cutoff:
        query = query.filter(ProcessingJob.created_at >= cutoff)
    counts = dict(query.group_by(ProcessingJob.status).all())

    queued = counts.get("pending", 0) + counts.get("queued", 0)
    running = counts.get("running", 0)
    completed = counts.get("completed", 0)
    failed = counts.get("failed", 0) + counts.get("cancelled", 0)
    skipped = counts.get("skipped", 0)
    total_jobs = sum(counts.values())

    has_active_work = (queued + running) > 0
    status = run.status
    if has_active_work:
        status = "running" if running > 0 else "pending"
    else:
        status = "pending"

    progress_denom = max(total_jobs or 0, 1)
    progress_percentage = (
        ((completed + skipped) / progress_denom) * 100.0 if total_jobs else 0.0
    )

    return {
        "id": run.id,
        "status": status,
        "trigger": run.trigger,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "total_jobs": total_jobs,
        "queued_jobs": queued,
        "running_jobs": running,
        "completed_jobs": completed,
        "failed_jobs": failed,
        "skipped_jobs": skipped,
        "context": run.context_json,
        "counters_reset_at": (
            run.counters_reset_at.isoformat() if run.counters_reset_at else None
        ),
        "progress_percentage": round(progress_percentage, 2),
    }
