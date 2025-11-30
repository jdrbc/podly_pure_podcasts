"""Cleanup job for pruning processed posts and associated artifacts."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Sequence, Set, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Query

from app.db_concurrency import commit_with_profile
from app.extensions import db, scheduler
from app.jobs_manager_run_service import recalculate_run_counts
from app.models import Identification, ModelCall, Post, ProcessingJob, TranscriptSegment
from app.runtime_config import config as runtime_config
from shared import defaults as DEFAULTS

logger = logging.getLogger("global_logger")


def _build_cleanup_query(
    retention_days: Optional[int],
) -> Tuple[Optional[Query["Post"]], Optional[datetime]]:
    """Construct the base query for posts eligible for cleanup."""
    if retention_days is None or retention_days <= 0:
        return None, None

    cutoff = datetime.utcnow() - timedelta(days=retention_days)

    active_jobs_exists = (
        db.session.query(ProcessingJob.id)
        .filter(ProcessingJob.post_guid == Post.guid)
        .filter(ProcessingJob.status.in_(["pending", "running"]))
        .exists()
    )

    posts_query = Post.query.filter(Post.processed_audio_path.isnot(None)).filter(
        ~active_jobs_exists
    )

    return posts_query, cutoff


def count_cleanup_candidates(
    retention_days: Optional[int],
) -> Tuple[int, Optional[datetime]]:
    """Return how many posts would currently be removed along with the cutoff."""
    posts_query, cutoff = _build_cleanup_query(retention_days)
    if posts_query is None or cutoff is None:
        return 0, None

    posts = posts_query.all()
    latest_completed = _load_latest_completed_map([post.guid for post in posts])
    count = sum(
        1
        for post in posts
        if _processed_timestamp_before_cutoff(post, cutoff, latest_completed)
    )
    return count, cutoff


def cleanup_processed_posts(retention_days: Optional[int]) -> int:
    """Prune processed posts older than the retention window.

    Posts qualify when their processed audio artifact (or, if missing, the
    latest completed job) is older than the retention window. Eligible posts
    are un-whitelisted, artifacts are removed, and dependent rows are deleted,
    but the post row is retained to prevent reprocessing. Returns the number of
    posts that were cleaned. Callers must ensure an application context is
    active.
    """
    posts_query, cutoff = _build_cleanup_query(retention_days)
    if posts_query is None or cutoff is None:
        return 0

    posts: Sequence[Post] = posts_query.all()
    latest_completed = _load_latest_completed_map([post.guid for post in posts])

    if not posts:
        return 0

    affected_run_ids: Set[str] = set()
    removed_posts = 0

    for post in posts:
        if not _processed_timestamp_before_cutoff(post, cutoff, latest_completed):
            continue

        removed_posts += 1
        logger.info(
            "Cleanup removing post '%s' (guid=%s) completed before %s",
            post.title,
            post.guid,
            cutoff.isoformat(),
        )
        # Keep the post record but ensure it cannot be reprocessed.
        post.whitelisted = False
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
        _clear_post_paths(post)
        _delete_post_related_rows(post)

    db.session.flush()
    recalculate_run_counts(db.session)
    commit_with_profile(
        db.session,
        must_succeed=True,
        context="cleanup_processed_posts",
        logger_obj=logger,
    )

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


def _clear_post_paths(post: Post) -> None:
    """Clear stored paths now that artifacts are removed."""
    post.unprocessed_audio_path = None
    post.processed_audio_path = None


def _delete_post_related_rows(post: Post) -> None:
    """Remove dependent rows linked to a post."""
    # Smaller batches reduce lock time on SQLite
    batch_size = 50
    batch_num = 0

    # Delete transcript segments and identifications in batches
    while True:
        segment_ids = [
            segment_id
            for (segment_id,) in db.session.query(TranscriptSegment.id)
            .filter(TranscriptSegment.post_id == post.id)
            .limit(batch_size)
            .all()
        ]
        if not segment_ids:
            break

        batch_num += 1
        logger.info(
            "[CLEANUP_DELETE] post_id=%s batch=%s size=%s",
            post.id,
            batch_num,
            len(segment_ids),
        )
        db.session.query(Identification).filter(
            Identification.transcript_segment_id.in_(segment_ids)
        ).delete(synchronize_session=False)

        db.session.query(TranscriptSegment).filter(
            TranscriptSegment.id.in_(segment_ids)
        ).delete(synchronize_session=False)

        commit_with_profile(
            db.session,
            must_succeed=False,
            context="delete_transcript_segments_batch",
            logger_obj=logger,
        )
        logger.info(
            "[CLEANUP_DELETE] post_id=%s batch=%s committed", post.id, batch_num
        )

    # Delete model calls in batches
    while True:
        model_call_ids = [
            mc_id
            for (mc_id,) in db.session.query(ModelCall.id)
            .filter(ModelCall.post_id == post.id)
            .limit(batch_size)
            .all()
        ]
        if not model_call_ids:
            break
        db.session.query(ModelCall).filter(ModelCall.id.in_(model_call_ids)).delete(
            synchronize_session=False
        )
        commit_with_profile(
            db.session,
            must_succeed=False,
            context="delete_model_calls_batch",
            logger_obj=logger,
        )

    # Delete processing jobs in batches
    while True:
        job_ids = [
            job_id
            for (job_id,) in db.session.query(ProcessingJob.id)
            .filter(ProcessingJob.post_guid == post.guid)
            .limit(batch_size)
            .all()
        ]
        if not job_ids:
            break
        db.session.query(ProcessingJob).filter(ProcessingJob.id.in_(job_ids)).delete(
            synchronize_session=False
        )
        commit_with_profile(
            db.session,
            must_succeed=False,
            context="delete_processing_jobs_batch",
            logger_obj=logger,
        )


def _load_latest_completed_map(
    post_guids: Sequence[str],
) -> Dict[str, Optional[datetime]]:
    if not post_guids:
        return {}

    rows = (
        db.session.query(
            ProcessingJob.post_guid,
            func.max(ProcessingJob.completed_at),
        )
        .filter(ProcessingJob.post_guid.in_(post_guids))
        .group_by(ProcessingJob.post_guid)
        .all()
    )
    return dict(rows)


def _processed_timestamp_before_cutoff(
    post: Post, cutoff: datetime, latest_completed: Dict[str, Optional[datetime]]
) -> bool:
    file_timestamp = _get_processed_file_timestamp(post)
    job_timestamp = latest_completed.get(post.guid)

    candidate: Optional[datetime]
    if file_timestamp and job_timestamp:
        candidate = min(file_timestamp, job_timestamp)
    else:
        candidate = file_timestamp or job_timestamp

    return bool(candidate and candidate < cutoff)


def _get_processed_file_timestamp(post: Post) -> Optional[datetime]:
    if not post.processed_audio_path:
        return None

    try:
        file_path = Path(post.processed_audio_path)
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "Cleanup: invalid processed path for post %s: %s",
            post.guid,
            post.processed_audio_path,
        )
        return None

    if not file_path.exists():
        return None

    try:
        mtime = file_path.stat().st_mtime
    except OSError as exc:
        logger.warning("Cleanup: unable to stat processed file %s: %s", file_path, exc)
        return None

    return datetime.utcfromtimestamp(mtime)
