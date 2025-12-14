from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from app.extensions import db
from app.jobs_manager_run_service import recalculate_run_counts
from app.models import ProcessingJob


def dequeue_job_action(params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    run_id = params.get("run_id")

    # Check for running jobs
    running_job = (
        ProcessingJob.query.filter(ProcessingJob.status == "running")
        .order_by(ProcessingJob.started_at.desc().nullslast())
        .first()
    )
    if running_job:
        return None

    job = (
        ProcessingJob.query.filter(ProcessingJob.status == "pending")
        .order_by(ProcessingJob.created_at.asc())
        .first()
    )
    if not job:
        return None

    job.status = "running"
    job.started_at = datetime.utcnow()

    if run_id and job.jobs_manager_run_id != run_id:
        job.jobs_manager_run_id = run_id

    return {"job_id": job.id, "post_guid": job.post_guid}


def cleanup_stale_jobs_action(params: Dict[str, Any]) -> Dict[str, Any]:
    older_than_seconds = params.get("older_than_seconds", 3600)
    cutoff = datetime.utcnow() - timedelta(seconds=older_than_seconds)

    old_jobs = ProcessingJob.query.filter(ProcessingJob.created_at < cutoff).all()

    count = len(old_jobs)
    for job in old_jobs:
        db.session.delete(job)

    return {"count": count}


def clear_all_jobs_action(params: Dict[str, Any]) -> int:
    all_jobs = ProcessingJob.query.all()
    count = len(all_jobs)
    for job in all_jobs:
        db.session.delete(job)
    return count


def create_job_action(params: Dict[str, Any]) -> Dict[str, Any]:
    job_data = params.get("job_data")
    if not isinstance(job_data, dict):
        raise ValueError("job_data must be a dictionary")

    # Convert date strings back to datetime objects if necessary
    if "created_at" in job_data and isinstance(job_data["created_at"], str):
        job_data["created_at"] = datetime.fromisoformat(job_data["created_at"])

    job = ProcessingJob(**job_data)
    db.session.add(job)

    if job.jobs_manager_run_id:
        recalculate_run_counts(db.session)

    db.session.flush()
    return {"job_id": job.id}


def cancel_existing_jobs_action(params: Dict[str, Any]) -> int:
    post_guid = params.get("post_guid")
    current_job_id = params.get("current_job_id")

    existing_jobs = (
        ProcessingJob.query.filter_by(post_guid=post_guid)
        .filter(
            ProcessingJob.status.in_(["pending", "running"]),
            ProcessingJob.id != current_job_id,
        )
        .all()
    )

    count = len(existing_jobs)
    for existing_job in existing_jobs:
        db.session.delete(existing_job)

    if count > 0:
        recalculate_run_counts(db.session)

    return count


def update_job_status_action(params: Dict[str, Any]) -> Dict[str, Any]:
    job_id = params.get("job_id")
    status = params.get("status")
    step = params.get("step")
    step_name = params.get("step_name")
    progress = params.get("progress")
    error_message = params.get("error_message")

    job = db.session.get(ProcessingJob, job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    job.status = status
    job.current_step = step
    job.step_name = step_name
    if progress is not None:
        job.progress_percentage = progress

    if error_message:
        job.error_message = error_message

    if status == "running" and not job.started_at:
        job.started_at = datetime.utcnow()
    elif (
        status in ["completed", "failed", "cancelled", "skipped"]
        and not job.completed_at
    ):
        job.completed_at = datetime.utcnow()

    if job.jobs_manager_run_id:
        recalculate_run_counts(db.session)

    return {"job_id": job.id, "status": job.status}


def mark_cancelled_action(params: Dict[str, Any]) -> Dict[str, Any]:
    job_id = params.get("job_id")
    reason = params.get("reason")

    job = db.session.get(ProcessingJob, job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    job.status = "cancelled"
    job.error_message = reason
    job.completed_at = datetime.utcnow()

    if job.jobs_manager_run_id:
        recalculate_run_counts(db.session)

    return {"job_id": job.id, "status": "cancelled"}


def reassign_pending_jobs_action(params: Dict[str, Any]) -> int:
    run_id = params.get("run_id")
    if not run_id:
        return 0

    pending_jobs = (
        ProcessingJob.query.filter(ProcessingJob.status == "pending")
        .order_by(ProcessingJob.created_at.asc())
        .all()
    )

    reassigned = 0
    for job in pending_jobs:
        if job.jobs_manager_run_id != run_id:
            job.jobs_manager_run_id = run_id
            reassigned += 1

    if reassigned:
        recalculate_run_counts(db.session)

    return reassigned
