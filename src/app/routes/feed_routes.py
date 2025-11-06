import logging
import re
from pathlib import Path
from threading import Thread
from typing import Any, cast
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

from app.auth.feed_tokens import create_feed_access_token
from app.extensions import db
from app.feeds import add_or_refresh_feed, generate_feed_xml, refresh_feed
from app.jobs_manager import get_jobs_manager
from app.models import (
    Feed,
    Identification,
    ModelCall,
    Post,
    ProcessingJob,
    TranscriptSegment,
    User,
)
from podcast_processor.podcast_downloader import sanitize_title
from shared.processing_paths import get_in_root, get_srv_root

logger = logging.getLogger("global_logger")


feed_bp = Blueprint("feed", __name__)


def fix_url(url: str) -> str:
    url = re.sub(r"(http(s)?):/([^/])", r"\1://\3", url)
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url


@feed_bp.route("/feed", methods=["POST"])
def add_feed() -> ResponseReturnValue:
    url = request.form.get("url")
    if not url:
        return make_response(("URL is required", 400))

    url = fix_url(url)

    if not validators.url(url):
        return make_response(("Invalid URL", 400))

    try:
        add_or_refresh_feed(url)
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
    user = User.query.get(current.id)
    if user is None:
        return jsonify({"error": "User not found."}), 404

    token_id, secret = create_feed_access_token(user, feed)

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
    feed = Feed.query.get_or_404(f_id)

    # Refresh the feed
    refresh_feed(feed)

    # Generate the XML
    xml_content = generate_feed_xml(feed)

    response = make_response(xml_content)
    response.headers["Content-Type"] = "application/rss+xml"
    return response


@feed_bp.route("/feed/<int:f_id>", methods=["DELETE"])
def delete_feed(f_id: int) -> Response:
    feed = Feed.query.get_or_404(f_id)

    # Get all post IDs for this feed
    post_ids = [post.id for post in feed.posts]
    post_guids = [post.guid for post in feed.posts]

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

    # Delete related database records in the correct order to avoid foreign key constraints
    if post_ids:
        # Delete identifications for all posts in this feed
        identifications_to_delete = (
            db.session.query(Identification)
            .join(
                TranscriptSegment,
                Identification.transcript_segment_id == TranscriptSegment.id,
            )
            .filter(TranscriptSegment.post_id.in_(post_ids))
            .all()
        )

        for identification in identifications_to_delete:
            db.session.delete(identification)

        # Delete model calls for all posts in this feed
        model_calls_to_delete = ModelCall.query.filter(
            ModelCall.post_id.in_(post_ids)
        ).all()
        for model_call in model_calls_to_delete:
            db.session.delete(model_call)

        # Delete transcript segments for all posts in this feed
        transcript_segments_to_delete = TranscriptSegment.query.filter(
            TranscriptSegment.post_id.in_(post_ids)
        ).all()
        for segment in transcript_segments_to_delete:
            db.session.delete(segment)

        # Delete processing jobs for all posts in this feed
        if post_guids:
            processing_jobs_to_delete = ProcessingJob.query.filter(
                ProcessingJob.post_guid.in_(post_guids)
            ).all()
            for job in processing_jobs_to_delete:
                db.session.delete(job)

        # Delete all posts for this feed
        posts_to_delete = Post.query.filter(Post.feed_id == feed.id).all()
        for post in posts_to_delete:
            db.session.delete(post)

    # Delete the feed from the database
    db.session.delete(feed)
    db.session.commit()

    logger.info(
        f"Deleted feed: {feed.title} (ID: {feed.id}) with {len(post_ids)} posts"
    )
    return make_response("", 204)


@feed_bp.route("/api/feeds/<int:f_id>/refresh", methods=["POST"])
def refresh_feed_endpoint(f_id: int) -> ResponseReturnValue:
    """
    Refresh the specified feed and return a JSON response indicating the result.
    """
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
        feed = Feed.query.get(feed_id)
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
def api_feeds() -> Response:
    feeds = Feed.query.all()
    feeds_data = [
        {
            "id": feed.id,
            "title": feed.title,
            "rss_url": feed.rss_url,
            "description": feed.description,
            "author": feed.author,
            "image_url": feed.image_url,
            "posts_count": len(feed.posts),
        }
        for feed in feeds
    ]
    return jsonify(feeds_data)
