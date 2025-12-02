import logging
import re
from decimal import Decimal
from pathlib import Path
from threading import Thread
from typing import Any, Optional, cast
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
from app.credits import credits_enabled, resolve_sponsor_user
from app.db_concurrency import commit_with_profile
from app.extensions import db
from app.feeds import add_or_refresh_feed, generate_feed_xml, refresh_feed
from app.jobs_manager import get_jobs_manager
from app.models import (
    CreditTransaction,
    Feed,
    FeedAccessToken,
    FeedSupporter,
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
        feed = add_or_refresh_feed(url)
        _assign_feed_sponsor(feed)
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
def delete_feed(f_id: int) -> ResponseReturnValue:  # pylint: disable=too-many-branches
    user, error = _require_authenticated_user(allow_missing_auth=True)
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
    batch_size = 200
    if post_ids:
        # Delete identifications and transcript segments in batches
        while True:
            seg_ids = [
                seg_id
                for (seg_id,) in db.session.query(TranscriptSegment.id)
                .filter(TranscriptSegment.post_id.in_(post_ids))
                .limit(batch_size)
                .all()
            ]
            if not seg_ids:
                break
            db.session.query(Identification).filter(
                Identification.transcript_segment_id.in_(seg_ids)
            ).delete(synchronize_session=False)
            db.session.query(TranscriptSegment).filter(
                TranscriptSegment.id.in_(seg_ids)
            ).delete(synchronize_session=False)
            commit_with_profile(
                db.session,
                must_succeed=False,
                context="delete_feed_segments_batch",
                logger_obj=logger,
            )

        # Delete model calls in batches
        while True:
            mc_ids = [
                mc_id
                for (mc_id,) in db.session.query(ModelCall.id)
                .filter(ModelCall.post_id.in_(post_ids))
                .limit(batch_size)
                .all()
            ]
            if not mc_ids:
                break
            db.session.query(ModelCall).filter(ModelCall.id.in_(mc_ids)).delete(
                synchronize_session=False
            )
            commit_with_profile(
                db.session,
                must_succeed=False,
                context="delete_feed_model_calls_batch",
                logger_obj=logger,
            )

        # Delete processing jobs in batches
        while True:
            job_ids = [
                job_id
                for (job_id,) in db.session.query(ProcessingJob.id)
                .filter(ProcessingJob.post_guid.in_(post_guids))
                .limit(batch_size)
                .all()
            ]
            if not job_ids:
                break
            db.session.query(ProcessingJob).filter(
                ProcessingJob.id.in_(job_ids)
            ).delete(synchronize_session=False)
            commit_with_profile(
                db.session,
                must_succeed=False,
                context="delete_feed_jobs_batch",
                logger_obj=logger,
            )

        # Delete all posts for this feed
        posts_to_delete = Post.query.filter(Post.feed_id == feed.id).all()
        for post in posts_to_delete:
            db.session.delete(post)

    # Delete feed access tokens for this feed
    FeedAccessToken.query.filter(FeedAccessToken.feed_id == feed.id).delete()

    # Nullify feed_id on credit transactions (keep transaction history)
    CreditTransaction.query.filter(CreditTransaction.feed_id == feed.id).update(
        {CreditTransaction.feed_id: None}
    )

    # Delete the feed from the database
    db.session.delete(feed)
    commit_with_profile(
        db.session,
        must_succeed=True,
        context="delete_feed_final",
        logger_obj=logger,
    )

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


def _assign_feed_sponsor(feed: Feed) -> None:
    """Set the sponsor for a feed based on the current user or admin fallback."""
    if not credits_enabled():
        return

    current = getattr(g, "current_user", None)
    sponsor_id = None
    if current is not None:
        sponsor_id = current.id
    else:
        sponsor = resolve_sponsor_user(feed)
        sponsor_id = getattr(sponsor, "id", None)

    did_update = False
    if sponsor_id and feed.sponsor_user_id != sponsor_id:
        feed.sponsor_user_id = sponsor_id
        db.session.add(feed)
        did_update = True
    if sponsor_id:
        did_update = _ensure_feed_supporter(feed, sponsor_id) or did_update
    if did_update:
        commit_with_profile(
            db.session,
            must_succeed=True,
            context="assign_feed_sponsor",
            logger_obj=logger,
        )


def _ensure_feed_supporter(feed: Feed, user_id: int | None) -> bool:
    if not user_id:
        return False
    existing = FeedSupporter.query.filter_by(feed_id=feed.id, user_id=user_id).first()
    if existing:
        return False
    db.session.add(FeedSupporter(feed_id=feed.id, user_id=user_id))
    return True


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
    current = getattr(g, "current_user", None)
    feeds_data = [_serialize_feed(feed, current_user=current) for feed in feeds]
    return jsonify(feeds_data)


@feed_bp.route("/api/feeds/<int:feed_id>/join", methods=["POST"])
def api_join_feed(feed_id: int) -> ResponseReturnValue:
    user, error = _require_authenticated_user()
    if error:
        return error
    if user is None:
        return jsonify({"error": "Authentication required."}), 401

    feed = Feed.query.get_or_404(feed_id)
    changed = _ensure_feed_supporter(feed, getattr(user, "id", None))
    if changed:
        commit_with_profile(
            db.session,
            must_succeed=True,
            context="feed_join",
            logger_obj=logger,
        )
    refreshed = Feed.query.get(feed_id)
    return (
        jsonify(_serialize_feed(refreshed or feed, current_user=user)),
        200,
    )


@feed_bp.route("/api/feeds/<int:feed_id>/exit", methods=["POST"])
def api_exit_feed(feed_id: int) -> ResponseReturnValue:
    user, error = _require_authenticated_user()
    if error:
        return error
    if user is None:
        return jsonify({"error": "Authentication required."}), 401

    feed = Feed.query.get_or_404(feed_id)
    removed = FeedSupporter.query.filter_by(feed_id=feed.id, user_id=user.id).delete()
    if removed:
        commit_with_profile(
            db.session,
            must_succeed=True,
            context="feed_exit",
            logger_obj=logger,
        )
    refreshed = Feed.query.get(feed_id)
    return (
        jsonify(_serialize_feed(refreshed or feed, current_user=user)),
        200,
    )


@feed_bp.route("/api/feeds/<int:feed_id>/sponsor", methods=["POST"])
def sponsor_feed(feed_id: int) -> ResponseReturnValue:
    """Assign the current user as the sponsor for the feed."""
    user, error = _require_authenticated_user()
    if error:
        return error
    if user is None:
        return jsonify({"error": "Authentication is disabled."}), 404

    feed = Feed.query.get_or_404(feed_id)
    if feed.sponsor_user_id == user.id:
        return jsonify(_serialize_feed(feed, current_user=user))

    existing_sponsor = (
        db.session.get(User, feed.sponsor_user_id) if feed.sponsor_user_id else None
    )
    if existing_sponsor and Decimal(existing_sponsor.credits_balance or 0) > Decimal(
        "1.0"
    ):
        return (
            jsonify(
                {
                    "error": (
                        "Current sponsor still has available credits; "
                        "feed ownership cannot be changed."
                    )
                }
            ),
            403,
        )

    feed.sponsor_user_id = user.id
    _ensure_feed_supporter(feed, user.id)
    db.session.add(feed)
    commit_with_profile(
        db.session,
        must_succeed=True,
        context="sponsor_feed",
        logger_obj=logger,
    )

    return jsonify(_serialize_feed(feed, current_user=user))


def _require_authenticated_user(
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

    user = db.session.get(User, current.id)
    if user is None:
        return None, (jsonify({"error": "User not found."}), 404)

    return user, None


def _serialize_feed(
    feed: Feed,
    *,
    current_user: Optional[User] = None,
    include_supporters: Optional[bool] = None,
) -> dict[str, Any]:
    sponsor_balance = (
        Decimal(feed.sponsor.credits_balance or 0) if feed.sponsor else Decimal("0")
    )
    out_of_credits = feed.sponsor is not None and sponsor_balance <= Decimal(0)
    supporters_payload: list[dict[str, Any]] = []
    supporter_memberships = list(getattr(feed, "supporters", []) or [])
    supporter_count = len(supporter_memberships)
    if include_supporters is None:
        include_supporters = bool(
            current_user
            and (
                getattr(current_user, "role", None) == "admin"
                or feed.sponsor_user_id == getattr(current_user, "id", None)
            )
        )
    if include_supporters:
        for membership in supporter_memberships:
            supporter_user = membership.user
            if not supporter_user:
                continue
            supporters_payload.append(
                {
                    "user_id": membership.user_id,
                    "username": supporter_user.username,
                    "credits_balance": str(
                        Decimal(supporter_user.credits_balance or 0)
                    ),
                }
            )
    is_supporter = bool(
        getattr(current_user, "id", None)
        and any(
            membership.user_id == getattr(current_user, "id", None)
            for membership in supporter_memberships
        )
    )
    feed_payload = {
        "id": feed.id,
        "title": feed.title,
        "rss_url": feed.rss_url,
        "description": feed.description,
        "author": feed.author,
        "image_url": feed.image_url,
        "posts_count": len(feed.posts),
        "sponsor_username": feed.sponsor.username if feed.sponsor else None,
        "sponsor_user_id": feed.sponsor_user_id,
        "sponsor_note": feed.sponsor_note,
        "sponsor_credits_balance": (
            str(sponsor_balance) if feed.sponsor is not None else None
        ),
        "sponsor_out_of_credits": out_of_credits,
        "supporters_count": supporter_count,
        "is_current_user_supporter": is_supporter,
    }
    if include_supporters:
        feed_payload["supporters"] = supporters_payload
    return feed_payload
