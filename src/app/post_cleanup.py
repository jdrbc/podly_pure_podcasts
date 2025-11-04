"""Cleanup job for pruning processed posts and associated artifacts."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Sequence, Set

from sqlalchemy import func

from app.extensions import db, scheduler
from app.jobs_manager_run_service import recalculate_run_counts
from app.models import Identification, ModelCall, Post, ProcessingJob, TranscriptSegment
from app.runtime_config import config as runtime_config
from shared import defaults as DEFAULTS

logger = logging.getLogger("global_logger")


def cleanup_processed_posts(retention_days: Optional[int]) -> int:
    """Remove posts whose latest completed job finished before the retention window.

    Returns the number of posts that were deleted. Callers must ensure an
    application context is active.
    """
    if retention_days is None or retention_days <= 0:
        return 0

    cutoff = datetime.utcnow() - timedelta(days=retention_days)

    latest_jobs = (
        db.session.query(
            ProcessingJob.post_guid.label("post_guid"),
            func.max(ProcessingJob.completed_at).label("last_completed_at"),
        )
        .group_by(ProcessingJob.post_guid)
        .subquery()
    )

    active_jobs_exists = (
        db.session.query(ProcessingJob.id)
        .filter(ProcessingJob.post_guid == Post.guid)
        .filter(ProcessingJob.status.in_(["pending", "running"]))
        .exists()
    )

    posts: Sequence[Post] = (
        Post.query.join(latest_jobs, Post.guid == latest_jobs.c.post_guid)
        .filter(latest_jobs.c.last_completed_at.isnot(None))
        .filter(latest_jobs.c.last_completed_at < cutoff)
        .filter(~active_jobs_exists)
        .all()
    )

    if not posts:
        return 0

    affected_run_ids: Set[str] = set()
    removed_posts = 0

    for post in posts:
        removed_posts += 1
        logger.info(
            "Cleanup removing post '%s' (guid=%s) completed before %s",
            post.title,
            post.guid,
            cutoff.isoformat(),
        )
        affected_run_ids.update(
            run_id
            for (run_id,) in db.session.query(ProcessingJob.jobs_manager_run_id)
            .filter(ProcessingJob.post_guid == post.guid)
            .filter(ProcessingJob.jobs_manager_run_id.isnot(None))
            .distinct()
            .all()
            if run_id
        )
        _remove_associated_files(post)
        _delete_post_related_rows(post)
        db.session.delete(post)

    db.session.flush()
    recalculate_run_counts(db.session)
    db.session.commit()

    logger.info(
        "Cleanup job removed %s posts%s",
        removed_posts,
        f" (runs updated: {len(affected_run_ids)})" if affected_run_ids else "",
    )
    return removed_posts


def scheduled_cleanup_processed_posts() -> None:
    """Entry-point for APScheduler."""
    retention = getattr(
        runtime_config,
        "post_cleanup_retention_days",
        DEFAULTS.APP_POST_CLEANUP_RETENTION_DAYS,
    )
    if scheduler.app is None:
        logger.warning("Cleanup skipped: scheduler has no associated app.")
        return

    try:
        with scheduler.app.app_context():
            cleanup_processed_posts(retention)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Scheduled cleanup failed: %s", exc, exc_info=True)


def _remove_associated_files(post: Post) -> None:
    """Delete processed and unprocessed audio files for a post."""
    for path_str in [post.unprocessed_audio_path, post.processed_audio_path]:
        if not path_str:
            continue
        try:
            file_path = Path(path_str)
        except Exception:  # pylint: disable=broad-except
            logger.warning("Cleanup: invalid path for post %s: %s", post.guid, path_str)
            continue
        if not file_path.exists():
            continue
        try:
            file_path.unlink()
            logger.info("Cleanup deleted file: %s", file_path)
        except OSError as exc:
            logger.warning("Cleanup unable to delete %s: %s", file_path, exc)


def _delete_post_related_rows(post: Post) -> None:
    """Remove dependent rows linked to a post."""
    segment_ids = [
        segment_id
        for (segment_id,) in db.session.query(TranscriptSegment.id)
        .filter(TranscriptSegment.post_id == post.id)
        .all()
    ]
    if segment_ids:
        db.session.query(Identification).filter(
            Identification.transcript_segment_id.in_(segment_ids)
        ).delete(synchronize_session=False)

    db.session.query(TranscriptSegment).filter(
        TranscriptSegment.post_id == post.id
    ).delete(synchronize_session=False)
    db.session.query(ModelCall).filter(ModelCall.post_id == post.id).delete(
        synchronize_session=False
    )
    db.session.query(ProcessingJob).filter(ProcessingJob.post_guid == post.guid).delete(
        synchronize_session=False
    )
