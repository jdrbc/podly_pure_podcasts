"""Cleanup job for pruning processed posts and associated artifacts."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from flask import current_app
from sqlalchemy import func
from sqlalchemy.orm import Query

from app.db_guard import db_guard, reset_session
from app.extensions import db, scheduler
from app.models import Post, ProcessingJob
from app.runtime_config import config as runtime_config
from app.writer.client import writer_client
from shared import defaults as DEFAULTS

logger = logging.getLogger("global_logger")


def _get_most_recent_posts_per_feed(post_guids: Sequence[str]) -> set[str]:
    """Return GUIDs of the most recent post for each feed.

    For feeds with multiple posts in the candidate list, returns only the
    most recent one (determined by latest completion timestamp or file mtime).
    These posts should never be cleaned up to ensure each feed has at least
    one processed episode available.
    """
    if not post_guids:
        return set()

    # Get posts with their feed_id and processed timestamp info
    posts = Post.query.filter(Post.guid.in_(post_guids)).all()

    # Build map of completion timestamps
    latest_completed = _load_latest_completed_map(post_guids)

    # Group by feed and find most recent per feed
    feed_posts: Dict[int, tuple[str, Optional[datetime]]] = {}

    for post in posts:
        timestamp = _get_post_timestamp(post, latest_completed)

        if post.feed_id not in feed_posts:
            feed_posts[post.feed_id] = (post.guid, timestamp)
        else:
            _, current_timestamp = feed_posts[post.feed_id]
            # Keep the post with the latest timestamp
            if timestamp and current_timestamp:
                if timestamp > current_timestamp:
                    feed_posts[post.feed_id] = (post.guid, timestamp)
            elif timestamp:  # Only new post has timestamp
                feed_posts[post.feed_id] = (post.guid, timestamp)
            # If neither has timestamp, keep current

    return {guid for guid, _ in feed_posts.values()}


def _get_post_timestamp(
    post: Post, latest_completed: Dict[str, Optional[datetime]]
) -> Optional[datetime]:
    """Get the most recent timestamp for a post (file or job completion)."""
    file_timestamp = _get_processed_file_timestamp(post)
    job_timestamp = latest_completed.get(post.guid)

    if file_timestamp and job_timestamp:
        return max(file_timestamp, job_timestamp)
    return file_timestamp or job_timestamp


def _build_cleanup_query(
    retention_days: Optional[int],
) -> Tuple[Optional[Query["Post"]], Optional[datetime]]:
    """Construct the base query for posts eligible for cleanup."""
    if retention_days is None:
        return None, None

    # In developer mode, allow retention_days=0 for testing (cutoff = now)
    # In production, require retention_days > 0
    developer_mode = current_app.config.get("developer_mode", False)
    if retention_days <= 0 and not developer_mode:
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
    post_guids = [post.guid for post in posts]
    latest_completed = _load_latest_completed_map(post_guids)
    most_recent_per_feed = _get_most_recent_posts_per_feed(post_guids)

    count = sum(
        1
        for post in posts
        if post.guid not in most_recent_per_feed
        and _processed_timestamp_before_cutoff(post, cutoff, latest_completed)
    )
    return count, cutoff


def cleanup_processed_posts(retention_days: Optional[int]) -> int:
    """Prune processed posts older than the retention window.

    Posts qualify when their processed audio artifact (or, if missing, the
    latest completed job) is older than the retention window. The most recent
    post for each feed is always preserved, even if older than the retention
    window, to ensure each feed has at least one processed episode available.
    Eligible posts are un-whitelisted, artifacts are removed, and dependent
    rows are deleted, but the post row is retained to prevent reprocessing.
    Returns the number of posts that were cleaned. Callers must ensure an
    application context is active.
    """
    with db_guard("cleanup_processed_posts", db.session, logger):
        posts_query, cutoff = _build_cleanup_query(retention_days)
        if posts_query is None or cutoff is None:
            return 0

        posts: Sequence[Post] = posts_query.all()
        post_guids = [post.guid for post in posts]
        latest_completed = _load_latest_completed_map(post_guids)
        most_recent_per_feed = _get_most_recent_posts_per_feed(post_guids)

        if not posts:
            return 0

        removed_posts = 0

        for post in posts:
            # Always preserve the most recent post for each feed
            if post.guid in most_recent_per_feed:
                continue

            if not _processed_timestamp_before_cutoff(post, cutoff, latest_completed):
                continue

            removed_posts += 1
            logger.info(
                "Cleanup removing post '%s' (guid=%s) completed before %s",
                post.title,
                post.guid,
                cutoff.isoformat(),
            )
            _remove_associated_files(post)
            try:
                writer_client.action(
                    "cleanup_processed_post_files_only", {"post_id": post.id}, wait=True
                )
            except Exception as exc:  # pylint: disable=broad-except
                logger.error(
                    "Cleanup failed for post %s (guid=%s): %s",
                    post.id,
                    post.guid,
                    exc,
                    exc_info=True,
                )

        logger.info(
            "Cleanup job removed %s posts",
            removed_posts,
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
        reset_session(db.session, logger, "scheduled_cleanup_processed_posts", exc)


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
