"""Utility functions for feed route handlers."""

import logging
import re
from typing import Optional, cast

from flask import jsonify, make_response, redirect, url_for
from flask.typing import ResponseReturnValue

from app.extensions import db
from app.jobs_manager import get_jobs_manager
from app.models import Feed, Post, User, UserFeed
from app.writer.client import writer_client

logger = logging.getLogger("global_logger")


def fix_url(url: str) -> str:
    """Fix common URL formatting issues."""
    url = re.sub(r"(http(s)?):/([^/])", r"\1://\3", url)
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url


def user_feed_count(user_id: int) -> int:
    """Count how many feeds a user is subscribed to."""
    return int(UserFeed.query.filter_by(user_id=user_id).count())


def ensure_user_feed_membership(feed: Feed, user_id: int | None) -> tuple[bool, int]:
    """Add a user↔feed link if missing. Returns (created, previous_feed_member_count)."""
    if not user_id:
        return False, UserFeed.query.filter_by(feed_id=feed.id).count()
    result = writer_client.action(
        "ensure_user_feed_membership",
        {"feed_id": feed.id, "user_id": int(user_id)},
        wait=True,
    )
    if not result or not result.success or not isinstance(result.data, dict):
        raise RuntimeError(getattr(result, "error", "Failed to join feed"))
    return bool(result.data.get("created")), int(result.data.get("previous_count") or 0)


def whitelist_latest_for_first_member(
    feed: Feed, requested_by_user_id: int | None
) -> None:
    """When a feed goes from 0→1 members, whitelist and process the latest post."""
    # Respect global/per-feed whitelist settings; skip if auto-whitelist is disabled.
    from app.feeds import _should_auto_whitelist_new_posts

    if not _should_auto_whitelist_new_posts(feed):
        return

    try:
        result = writer_client.action(
            "whitelist_latest_post_for_feed", {"feed_id": feed.id}, wait=True
        )
        if not result or not result.success or not isinstance(result.data, dict):
            return
        post_guid = result.data.get("post_guid")
        updated = bool(result.data.get("updated"))
        if not updated or not post_guid:
            return
    except Exception:  # pylint: disable=broad-except
        return
    try:
        get_jobs_manager().start_post_processing(
            str(post_guid),
            priority="interactive",
            requested_by_user_id=requested_by_user_id,
            billing_user_id=requested_by_user_id,
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(
            "Failed to enqueue processing for latest post %s: %s", post_guid, exc
        )


def handle_developer_mode_feed(url: str, user: Optional[User]) -> ResponseReturnValue:
    """Handle special developer mode feed creation."""
    try:
        feed_id_str = url.split("/")[-1]
        feed_num = int(feed_id_str)

        result = writer_client.action(
            "create_dev_test_feed",
            {
                "rss_url": url,
                "title": f"Test Feed {feed_num}",
                "image_url": "https://via.placeholder.com/150",
                "description": "A test feed for development",
                "author": "Test Author",
                "post_count": 5,
                "guid_prefix": f"test-guid-{feed_num}",
                "download_url_prefix": f"http://test-feed/{feed_num}",
            },
            wait=True,
        )
        if not result or not result.success or not isinstance(result.data, dict):
            raise RuntimeError(getattr(result, "error", "Failed to create test feed"))
        feed_id = int(result.data["feed_id"])
        feed = db.session.get(Feed, feed_id)
        if not feed:
            raise RuntimeError("Test feed disappeared")

        if user:
            created, previous_count = ensure_user_feed_membership(feed, user.id)
            if created and previous_count == 0:
                whitelist_latest_for_first_member(feed, getattr(user, "id", None))

        return redirect(url_for("main.index"))

    except Exception as e:
        logger.error(f"Error adding test feed: {e}")
        return make_response((f"Error adding test feed: {e}", 500))


def check_feed_allowance(user: User, url: str) -> Optional[ResponseReturnValue]:
    """Check if user is within their feed allowance limit."""
    if user.role == "admin":
        return None

    existing_feed = Feed.query.filter_by(rss_url=url).first()
    existing_membership = None
    if existing_feed:
        existing_membership = UserFeed.query.filter_by(
            feed_id=existing_feed.id, user_id=user.id
        ).first()

    # Use manual allowance if set, otherwise fall back to plan allowance
    allowance = user.manual_feed_allowance
    if allowance is None:
        allowance = getattr(user, "feed_allowance", 0) or 0

    if allowance > 0:
        current_count = user_feed_count(user.id)
        if current_count >= allowance and existing_membership is None:
            return (
                jsonify(
                    {
                        "error": "FEED_LIMIT_REACHED",
                        "message": f"Your plan allows {allowance} feeds. Increase your plan to add more.",
                        "feeds_in_use": current_count,
                        "feed_allowance": allowance,
                    }
                ),
                402,
            )
    return None


def cleanup_feed_directories(feed: Feed) -> None:
    """
    Clean up directory structures for a feed in both in/ and srv/ directories.

    Args:
        feed: The Feed object being deleted
    """
    from podcast_processor.podcast_downloader import sanitize_title
    from shared.processing_paths import get_in_root, get_srv_root

    # Clean up srv/ directory (processed audio)
    # srv/{sanitized_feed_title}/
    sanitized_feed_title = sanitize_title(feed.title)
    # Use the same sanitization logic as in processing_paths.py
    sanitized_feed_title = re.sub(
        r"[^a-zA-Z0-9\s_.-]", "", sanitized_feed_title
    ).strip()
    sanitized_feed_title = sanitized_feed_title.rstrip(".")
    sanitized_feed_title = re.sub(r"\s+", "_", sanitized_feed_title)

    srv_feed_dir = get_srv_root() / sanitized_feed_title
    if srv_feed_dir.exists() and srv_feed_dir.is_dir():
        try:
            # Remove all files in the directory first
            for file_path in srv_feed_dir.iterdir():
                if file_path.is_file():
                    file_path.unlink()
                    logger.info(f"Deleted processed audio file: {file_path}")
            # Remove the directory itself
            srv_feed_dir.rmdir()
            logger.info(f"Deleted processed audio directory: {srv_feed_dir}")
        except Exception as e:  # pylint: disable=broad-except
            logger.error(
                f"Error deleting processed audio directory {srv_feed_dir}: {e}"
            )

    # Clean up in/ directories (unprocessed audio)
    # in/{sanitized_post_title}/
    for post in feed.posts:  # type: ignore[attr-defined]
        sanitized_post_title = sanitize_title(post.title)
        in_post_dir = get_in_root() / sanitized_post_title
        if in_post_dir.exists() and in_post_dir.is_dir():
            try:
                # Remove all files in the directory first
                for file_path in in_post_dir.iterdir():
                    if file_path.is_file():
                        file_path.unlink()
                        logger.info(f"Deleted unprocessed audio file: {file_path}")
                # Remove the directory itself
                in_post_dir.rmdir()
                logger.info(f"Deleted unprocessed audio directory: {in_post_dir}")
            except Exception as e:  # pylint: disable=broad-except
                logger.error(
                    f"Error deleting unprocessed audio directory {in_post_dir}: {e}"
                )
