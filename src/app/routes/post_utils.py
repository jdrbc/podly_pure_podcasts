"""Utility functions for post route handlers."""

import logging
from typing import Optional, cast

import flask

from app.jobs_manager import get_jobs_manager
from app.models import Feed, Post
from app.runtime_config import config as runtime_config
from app.writer.client import writer_client

logger = logging.getLogger("global_logger")


def is_latest_post(feed: Feed, post: Post) -> bool:
    """Return True if the post is the latest by release_date (fallback to id)."""
    latest = (
        Post.query.filter_by(feed_id=feed.id)
        .order_by(Post.release_date.desc().nullslast(), Post.id.desc())
        .first()
    )
    return bool(latest and latest.id == post.id)


def increment_download_count(post: Post) -> None:
    """Safely increment the download counter for a post."""
    try:
        writer_client.action(
            "increment_download_count", {"post_id": post.id}, wait=False
        )
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Failed to increment download count for post {post.guid}: {e}")


def ensure_whitelisted_for_download(
    post: Post, p_guid: str
) -> Optional[flask.Response]:
    """Make sure a post is whitelisted before serving or queuing processing."""
    if post.whitelisted:
        return None

    if not getattr(runtime_config, "autoprocess_on_download", False):
        logger.warning(
            "Post %s not whitelisted and auto-process is disabled", post.guid
        )
        return flask.make_response(("Post not whitelisted", 403))

    try:
        writer_client.action(
            "whitelist_post",
            {"post_id": post.id},
            wait=True,
        )
        post.whitelisted = True
        logger.info("Auto-whitelisted post %s on download request", p_guid)
        return None
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "Failed to auto-whitelist post %s on download: %s", post.guid, exc
        )
        return flask.make_response(("Post not whitelisted", 403))


def missing_processed_audio_response(post: Post, p_guid: str) -> flask.Response:
    """Return a response when processed audio is missing, optionally queueing work."""
    if not getattr(runtime_config, "autoprocess_on_download", False):
        logger.warning("Processed audio not found for post: %s", post.id)
        return flask.make_response(("Processed audio not found", 404))

    logger.info(
        "Auto-processing on download is enabled; queuing processing for %s",
        p_guid,
    )
    requester = getattr(getattr(flask.g, "current_user", None), "id", None)
    job_response = get_jobs_manager().start_post_processing(
        p_guid,
        priority="download",
        requested_by_user_id=requester,
        billing_user_id=requester,
    )
    status = cast(Optional[str], job_response.get("status"))
    status_code = {
        "completed": 200,
        "skipped": 200,
        "error": 400,
        "running": 202,
        "started": 202,
    }.get(status or "pending", 202)
    message = job_response.get(
        "message",
        "Processing queued because audio was not ready for download",
    )
    return flask.make_response(
        flask.jsonify({**job_response, "message": message}),
        status_code,
    )
