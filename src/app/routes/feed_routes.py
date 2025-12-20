import logging
import re
import secrets
from pathlib import Path
from threading import Thread
from typing import Any, Optional, cast

# pylint: disable=chained-comparison
from urllib.parse import urlencode, urlparse, urlunparse

import requests
import validators
from flask import (
    Blueprint,
    Flask,
    Response,
    current_app,
    g,
    jsonify,
    make_response,
    redirect,
    request,
    send_from_directory,
    url_for,
)
from flask.typing import ResponseReturnValue

from app.auth.service import update_user_last_active
from app.extensions import db
from app.feeds import (
    add_or_refresh_feed,
    generate_aggregate_feed_xml,
    generate_feed_xml,
    is_feed_active_for_user,
    refresh_feed,
)
from app.jobs_manager import get_jobs_manager
from app.models import (
    Feed,
    Post,
    User,
    UserFeed,
)
from app.writer.client import writer_client
from podcast_processor.podcast_downloader import sanitize_title
from shared.processing_paths import get_in_root, get_srv_root

from .auth_routes import _require_authenticated_user as _auth_get_user

logger = logging.getLogger("global_logger")


feed_bp = Blueprint("feed", __name__)


def fix_url(url: str) -> str:
    url = re.sub(r"(http(s)?):/([^/])", r"\1://\3", url)
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url


def _user_feed_count(user_id: int) -> int:
    return int(UserFeed.query.filter_by(user_id=user_id).count())


def _get_latest_post(feed: Feed) -> Post | None:
    return cast(
        Optional[Post],
        Post.query.filter_by(feed_id=feed.id)
        .order_by(Post.release_date.desc().nullslast(), Post.id.desc())
        .first(),
    )


def _ensure_user_feed_membership(feed: Feed, user_id: int | None) -> tuple[bool, int]:
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


def _whitelist_latest_for_first_member(
    feed: Feed, requested_by_user_id: int | None
) -> None:
    """When a feed goes from 0→1 members, whitelist and process the latest post."""
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


def _handle_developer_mode_feed(url: str, user: Optional[User]) -> ResponseReturnValue:
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
            created, previous_count = _ensure_user_feed_membership(feed, user.id)
            if created and previous_count == 0:
                _whitelist_latest_for_first_member(feed, getattr(user, "id", None))

        return redirect(url_for("main.index"))

    except Exception as e:
        logger.error(f"Error adding test feed: {e}")
        return make_response((f"Error adding test feed: {e}", 500))


def _check_feed_allowance(user: User, url: str) -> Optional[ResponseReturnValue]:
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
        current_count = _user_feed_count(user.id)
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


@feed_bp.route("/feed", methods=["POST"])
def add_feed() -> ResponseReturnValue:
    settings = current_app.config.get("AUTH_SETTINGS")
    user = None
    if settings and settings.require_auth:
        user, error = _require_user_or_error()
        if error:
            return error
    url = request.form.get("url")
    if not url:
        return make_response(("URL is required", 400))

    url = fix_url(url)

    if current_app.config.get("developer_mode") and url.startswith("http://test-feed/"):
        return _handle_developer_mode_feed(url, user)

    if not validators.url(url):
        return make_response(("Invalid URL", 400))

    try:
        if user:
            allowance_error = _check_feed_allowance(user, url)
            if allowance_error:
                return allowance_error

        feed = add_or_refresh_feed(url)
        if user:
            created, previous_count = _ensure_user_feed_membership(feed, user.id)
            if created and previous_count == 0:
                _whitelist_latest_for_first_member(feed, getattr(user, "id", None))

        app = cast(Any, current_app)._get_current_object()
        Thread(
            target=_enqueue_pending_jobs_async,
            args=(app,),
            daemon=True,
            name="enqueue-jobs-after-add",
        ).start()
        return redirect(url_for("main.index"))
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Error adding feed: {e}")
        return make_response((f"Error adding feed: {e}", 500))


@feed_bp.route("/api/feeds/<int:feed_id>/share-link", methods=["POST"])
def create_feed_share_link(feed_id: int) -> ResponseReturnValue:
    settings = current_app.config.get("AUTH_SETTINGS")
    if not settings or not settings.require_auth:
        return jsonify({"error": "Authentication is disabled."}), 404

    current = getattr(g, "current_user", None)
    if current is None:
        return jsonify({"error": "Authentication required."}), 401

    feed = Feed.query.get_or_404(feed_id)
    user = db.session.get(User, current.id)
    if user is None:
        return jsonify({"error": "User not found."}), 404

    result = writer_client.action(
        "create_feed_access_token",
        {"user_id": user.id, "feed_id": feed.id},
        wait=True,
    )
    if not result or not result.success or not isinstance(result.data, dict):
        return jsonify({"error": "Failed to create feed token"}), 500
    token_id = str(result.data["token_id"])
    secret = str(result.data["secret"])

    parsed = urlparse(request.host_url)
    netloc = parsed.netloc
    scheme = parsed.scheme
    path = f"/feed/{feed.id}"
    query = urlencode({"feed_token": token_id, "feed_secret": secret})
    prefilled_url = urlunparse((scheme, netloc, path, "", query, ""))

    return (
        jsonify(
            {
                "url": prefilled_url,
                "feed_token": token_id,
                "feed_secret": secret,
                "feed_id": feed.id,
            }
        ),
        201,
    )


@feed_bp.route("/api/feeds/search", methods=["GET"])
def search_feeds() -> ResponseReturnValue:
    term = (request.args.get("term") or "").strip()
    logger.info("Searching for podcasts with term: %s", term)
    if not term:
        return jsonify({"error": "term parameter is required"}), 400

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"
        }
        response = requests.get(
            "http://api.podcastindex.org/search",
            headers=headers,
            params={"term": term},
            timeout=10,
        )
        response.raise_for_status()
        upstream_data = response.json()
    except requests.exceptions.RequestException as exc:
        logger.error("Podcast search request failed: %s", exc)
        return jsonify({"error": "Search request failed"}), 502
    except ValueError:
        logger.error("Podcast search returned non-JSON response")
        return (
            jsonify({"error": "Unexpected response from search provider"}),
            502,
        )

    results = upstream_data.get("results") or []
    transformed_results = []

    if current_app.config.get("developer_mode") and term.lower() == "test":
        logger.info("Developer mode test search - adding mock results")
        for i in range(1, 11):
            transformed_results.append(
                {
                    "title": f"Test Feed {i}",
                    "author": "Test Author",
                    "feedUrl": f"http://test-feed/{i}",
                    "artwork": "https://via.placeholder.com/150",
                    "genres": ["Test Genre"],
                }
            )
    else:
        logger.info(
            "(dev mode disabled) Podcast search returned %d results", len(results)
        )

    for item in results:
        feed_url = item.get("feedUrl")
        if not feed_url:
            continue

        transformed_results.append(
            {
                "title": item.get("collectionName")
                or item.get("trackName")
                or "Unknown title",
                "author": item.get("artistName") or "",
                "feedUrl": feed_url,
                "artworkUrl": item.get("artworkUrl100")
                or item.get("artworkUrl600")
                or "",
                "description": item.get("collectionCensoredName")
                or item.get("trackCensoredName")
                or "",
                "genres": item.get("genres") or [],
            }
        )

    total = upstream_data.get("resultCount")
    if not isinstance(total, int) or total == 0:
        total = len(transformed_results)

    return jsonify(
        {
            "results": transformed_results,
            "total": total,
        }
    )


@feed_bp.route("/feed/<int:f_id>", methods=["GET"])
def get_feed(f_id: int) -> Response:
    if hasattr(g, "current_user") and g.current_user:
        update_user_last_active(g.current_user.id)

    feed = Feed.query.get_or_404(f_id)

    # Refresh the feed
    refresh_feed(feed)

    # Generate the XML
    xml_content = generate_feed_xml(feed)

    response = make_response(xml_content)
    response.headers["Content-Type"] = "application/rss+xml"
    return response


@feed_bp.route("/feed/<int:f_id>", methods=["DELETE"])
def delete_feed(f_id: int) -> ResponseReturnValue:  # pylint: disable=too-many-branches
    user, error = _require_user_or_error(allow_missing_auth=True)
    if error:
        return error

    feed = Feed.query.get_or_404(f_id)
    if user is not None and user.role != "admin":
        return (
            jsonify({"error": "Only administrators can delete feeds."}),
            403,
        )

    # Get all post IDs for this feed
    post_ids = [post.id for post in feed.posts]

    # Delete audio files if they exist
    for post in feed.posts:
        if post.unprocessed_audio_path and Path(post.unprocessed_audio_path).exists():
            try:
                Path(post.unprocessed_audio_path).unlink()
                logger.info(f"Deleted unprocessed audio: {post.unprocessed_audio_path}")
            except Exception as e:  # pylint: disable=broad-except
                logger.error(
                    f"Error deleting unprocessed audio {post.unprocessed_audio_path}: {e}"
                )

        if post.processed_audio_path and Path(post.processed_audio_path).exists():
            try:
                Path(post.processed_audio_path).unlink()
                logger.info(f"Deleted processed audio: {post.processed_audio_path}")
            except Exception as e:  # pylint: disable=broad-except
                logger.error(
                    f"Error deleting processed audio {post.processed_audio_path}: {e}"
                )

    # Clean up directory structures
    _cleanup_feed_directories(feed)

    try:
        result = writer_client.action(
            "delete_feed_cascade", {"feed_id": feed.id}, wait=True
        )
        if not result or not result.success:
            raise RuntimeError(getattr(result, "error", "Failed to delete feed"))
    except Exception as e:  # pylint: disable=broad-except
        logger.error("Failed to delete feed %s: %s", feed.id, e)
        return make_response(("Failed to delete feed", 500))

    logger.info(
        f"Deleted feed: {feed.title} (ID: {feed.id}) with {len(post_ids)} posts"
    )
    return make_response("", 204)


@feed_bp.route("/api/feeds/<int:f_id>/refresh", methods=["POST"])
def refresh_feed_endpoint(f_id: int) -> ResponseReturnValue:
    """
    Refresh the specified feed and return a JSON response indicating the result.
    """
    if hasattr(g, "current_user") and g.current_user:
        update_user_last_active(g.current_user.id)

    feed = Feed.query.get_or_404(f_id)
    feed_title = feed.title
    app = cast(Any, current_app)._get_current_object()

    Thread(
        target=_refresh_feed_background,
        args=(app, f_id),
        daemon=True,
        name=f"feed-refresh-{f_id}",
    ).start()

    return (
        jsonify(
            {
                "status": "accepted",
                "message": f'Feed "{feed_title}" refresh queued for processing',
            }
        ),
        202,
    )


def _refresh_feed_background(app: Flask, feed_id: int) -> None:
    with app.app_context():
        feed = db.session.get(Feed, feed_id)
        if not feed:
            logger.warning("Feed %s disappeared before refresh could run", feed_id)
            return

        try:
            refresh_feed(feed)
            get_jobs_manager().enqueue_pending_jobs(
                trigger="feed_refresh", context={"feed_id": feed_id}
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Failed to refresh feed %s asynchronously: %s", feed_id, exc)


@feed_bp.route("/api/feeds/refresh-all", methods=["POST"])
def refresh_all_feeds_endpoint() -> Response:
    """Trigger a refresh for all feeds and enqueue pending jobs."""
    if hasattr(g, "current_user") and g.current_user:
        update_user_last_active(g.current_user.id)

    result = get_jobs_manager().start_refresh_all_feeds(trigger="manual_refresh")
    feed_count = Feed.query.count()
    return jsonify(
        {
            "status": "success",
            "feeds_refreshed": feed_count,
            "jobs_enqueued": result.get("enqueued", 0),
        }
    )


def _enqueue_pending_jobs_async(app: Flask) -> None:
    with app.app_context():
        try:
            get_jobs_manager().enqueue_pending_jobs(trigger="feed_refresh")
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Failed to enqueue pending jobs asynchronously: %s", exc)


def _cleanup_feed_directories(feed: Feed) -> None:
    """
    Clean up directory structures for a feed in both in/ and srv/ directories.

    Args:
        feed: The Feed object being deleted
    """
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


@feed_bp.route("/<path:something_or_rss>", methods=["GET"])
def get_feed_by_alt_or_url(something_or_rss: str) -> Response:
    # first try to serve ANY static file matching the path
    if current_app.static_folder is not None:
        # Use Flask's safe helper to prevent directory traversal outside static_folder
        try:
            return send_from_directory(current_app.static_folder, something_or_rss)
        except Exception:
            # Not a valid static file; fall through to RSS/DB lookup
            pass
    feed = Feed.query.filter_by(rss_url=something_or_rss).first()
    if feed:
        xml_content = generate_feed_xml(feed)
        response = make_response(xml_content)
        response.headers["Content-Type"] = "application/rss+xml"
        return response

    return make_response(("Feed not found", 404))


@feed_bp.route("/feeds", methods=["GET"])
def api_feeds() -> ResponseReturnValue:
    settings = current_app.config.get("AUTH_SETTINGS")
    if settings and settings.require_auth:
        user, error = _require_user_or_error()
        if error:
            return error
        if user and user.role != "admin":
            feeds = (
                Feed.query.join(UserFeed, UserFeed.feed_id == Feed.id)
                .filter(UserFeed.user_id == user.id)
                .all()
            )
            # Hack: Always include Feed 1
            feed_1 = Feed.query.get(1)
            if feed_1 and feed_1 not in feeds:
                feeds.append(feed_1)
        else:
            feeds = Feed.query.all()
        current_user = user
    else:
        feeds = Feed.query.all()
        current_user = getattr(g, "current_user", None)

    feeds_data = [_serialize_feed(feed, current_user=current_user) for feed in feeds]
    return jsonify(feeds_data)


@feed_bp.route("/api/feeds/<int:feed_id>/join", methods=["POST"])
def api_join_feed(feed_id: int) -> ResponseReturnValue:
    user, error = _require_user_or_error()
    if error:
        return error
    if user is None:
        return jsonify({"error": "Authentication required."}), 401

    feed = Feed.query.get_or_404(feed_id)
    existing_membership = UserFeed.query.filter_by(
        feed_id=feed.id, user_id=user.id
    ).first()
    if user.role != "admin":
        # Use manual allowance if set, otherwise fall back to plan allowance
        allowance = user.manual_feed_allowance
        if allowance is None:
            allowance = getattr(user, "feed_allowance", 0) or 0

        at_capacity = allowance > 0 and _user_feed_count(user.id) >= allowance
        missing_membership = existing_membership is None
        if at_capacity and missing_membership:
            return (
                jsonify(
                    {
                        "error": "FEED_LIMIT_REACHED",
                        "message": f"Your plan allows {allowance} feeds. Increase your plan to add more.",
                        "feeds_in_use": _user_feed_count(user.id),
                        "feed_allowance": allowance,
                    }
                ),
                402,
            )
    if existing_membership:
        refreshed = Feed.query.get(feed_id)
        return jsonify(_serialize_feed(refreshed or feed, current_user=user)), 200

    created, previous_count = _ensure_user_feed_membership(
        feed, getattr(user, "id", None)
    )
    if created and previous_count == 0:
        _whitelist_latest_for_first_member(feed, getattr(user, "id", None))
    refreshed = Feed.query.get(feed_id)
    return (
        jsonify(_serialize_feed(refreshed or feed, current_user=user)),
        200,
    )


@feed_bp.route("/api/feeds/<int:feed_id>/exit", methods=["POST"])
def api_exit_feed(feed_id: int) -> ResponseReturnValue:
    user, error = _require_user_or_error()
    if error:
        return error
    if user is None:
        return jsonify({"error": "Authentication required."}), 401

    feed = Feed.query.get_or_404(feed_id)
    writer_client.action(
        "remove_user_feed_membership",
        {"feed_id": feed.id, "user_id": user.id},
        wait=True,
    )
    refreshed = Feed.query.get(feed_id)
    return (
        jsonify(_serialize_feed(refreshed or feed, current_user=user)),
        200,
    )


@feed_bp.route("/api/feeds/<int:feed_id>/leave", methods=["POST"])
def api_leave_feed(feed_id: int) -> ResponseReturnValue:
    """Remove current user membership; hide from their view."""
    user, error = _require_user_or_error()
    if error:
        return error
    if user is None:
        return jsonify({"error": "Authentication required."}), 401

    feed = Feed.query.get_or_404(feed_id)
    writer_client.action(
        "remove_user_feed_membership",
        {"feed_id": feed.id, "user_id": user.id},
        wait=True,
    )
    return jsonify({"status": "ok", "feed_id": feed.id})


@feed_bp.route("/feed/user/<int:user_id>", methods=["GET"])
def get_user_aggregate_feed(user_id: int) -> Response:
    """Serve the aggregate RSS feed for a specific user."""
    # Auth check is handled by middleware via feed_token
    # If auth is disabled, this is public.
    # If auth is enabled, middleware ensures we have a valid token for this user_id.

    settings = current_app.config.get("AUTH_SETTINGS")
    if settings and settings.require_auth:
        current = getattr(g, "current_user", None)
        if current is None:
            return make_response(("Authentication required", 401))
        if current.role != "admin" and current.id != user_id:
            return make_response(("Forbidden", 403))

    user = db.session.get(User, user_id)
    if not user:
        return make_response(("User not found", 404))

    xml_content = generate_aggregate_feed_xml(user)
    response = make_response(xml_content)
    response.headers["Content-Type"] = "application/rss+xml"
    return response


@feed_bp.route("/feed/aggregate", methods=["GET"])
def get_aggregate_feed_redirect() -> ResponseReturnValue:
    """Convenience endpoint to redirect to the user's aggregate feed."""
    settings = current_app.config.get("AUTH_SETTINGS")

    # Case 1: Auth Disabled -> Redirect to Admin User (Single User Mode)
    if not settings or not settings.require_auth:
        admin = User.query.filter_by(role="admin").first()
        if not admin:
            return make_response(("No admin user found to serve aggregate feed", 404))
        return redirect(url_for("feed.get_user_aggregate_feed", user_id=admin.id))

    # Case 2: Auth Enabled -> Require explicit user link
    # We cannot easily determine "current user" for a podcast player without a token.
    # If accessed via browser with session, we could redirect, but for consistency
    # we should probably just tell them to get their link.

    current = getattr(g, "current_user", None)
    if current:
        return redirect(url_for("feed.get_user_aggregate_feed", user_id=current.id))

    return (
        jsonify(
            {
                "error": "Authentication required",
                "message": "Please use your unique aggregate feed URL from the dashboard.",
            }
        ),
        401,
    )


@feed_bp.route("/api/user/aggregate-link", methods=["POST"])
def create_aggregate_feed_link() -> ResponseReturnValue:
    """Generate a unique RSS link for the current user's aggregate feed."""
    settings = current_app.config.get("AUTH_SETTINGS")

    user = None
    if not settings or not settings.require_auth:
        # Auth disabled: Use admin user or first available user
        user = User.query.filter_by(role="admin").first()
        if not user:
            user = User.query.first()

        if not user:
            # Create a default admin user if none exists
            default_username = "admin"
            default_password = secrets.token_urlsafe(16)

            result = writer_client.action(
                "create_user",
                {
                    "username": default_username,
                    "password": default_password,
                    "role": "admin",
                },
                wait=True,
            )
            if result and result.success and isinstance(result.data, dict):
                user_id = result.data.get("user_id")
                if user_id:
                    user = db.session.get(User, user_id)

            if not user:
                return (
                    jsonify({"error": "No user found and failed to create one."}),
                    500,
                )
    else:
        user, error = _require_user_or_error()
        if error:
            return error

    if user is None:
        return jsonify({"error": "Authentication required."}), 401

    # Create a token with feed_id=None (Aggregate Token)
    result = writer_client.action(
        "create_feed_access_token",
        {"user_id": user.id, "feed_id": None},
        wait=True,
    )
    if not result or not result.success or not isinstance(result.data, dict):
        return jsonify({"error": "Failed to create aggregate feed token"}), 500

    token_id = str(result.data["token_id"])
    secret = str(result.data["secret"])

    parsed = urlparse(request.host_url)
    netloc = parsed.netloc
    scheme = parsed.scheme
    path = f"/feed/user/{user.id}"

    # If auth is disabled, we don't strictly need the token params,
    # but including them doesn't hurt and ensures the link works if auth is enabled later.
    # However, to keep it clean for single-user mode:
    settings = current_app.config.get("AUTH_SETTINGS")
    if settings and settings.require_auth:
        query = urlencode({"feed_token": token_id, "feed_secret": secret})
    else:
        query = ""

    full_url = urlunparse((scheme, netloc, path, "", query, ""))

    return (
        jsonify(
            {
                "url": full_url,
                "feed_token": token_id,
                "feed_secret": secret,
            }
        ),
        201,
    )


def _require_user_or_error(
    allow_missing_auth: bool = False,
) -> tuple[User | None, ResponseReturnValue | None]:
    settings = current_app.config.get("AUTH_SETTINGS")
    if not settings or not settings.require_auth:
        if allow_missing_auth:
            return None, None
        return None, (jsonify({"error": "Authentication is disabled."}), 404)

    current = getattr(g, "current_user", None)
    if current is None:
        return None, (jsonify({"error": "Authentication required."}), 401)

    user = _auth_get_user()
    if user is None:
        return None, (jsonify({"error": "User not found."}), 404)

    return user, None


def _serialize_feed(
    feed: Feed,
    *,
    current_user: Optional[User] = None,
) -> dict[str, Any]:
    member_ids = [membership.user_id for membership in getattr(feed, "user_feeds", [])]
    is_member = bool(current_user and getattr(current_user, "id", None) in member_ids)

    # Hack: Always treat Feed 1 as a member
    if feed.id == 1 and current_user:
        is_member = True

    is_active_subscription = False
    if is_member and current_user:
        is_active_subscription = is_feed_active_for_user(feed.id, current_user)

    feed_payload = {
        "id": feed.id,
        "title": feed.title,
        "rss_url": feed.rss_url,
        "description": feed.description,
        "author": feed.author,
        "image_url": feed.image_url,
        "posts_count": len(feed.posts),
        "member_count": len(member_ids),
        "is_member": is_member,
        "is_active_subscription": is_active_subscription,
    }
    return feed_payload
