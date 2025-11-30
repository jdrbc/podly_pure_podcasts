import logging
import os
from pathlib import Path
from typing import Dict, Tuple

import flask
from flask import Blueprint, current_app, g, jsonify, request, send_file
from flask.typing import ResponseReturnValue
from sqlalchemy.exc import OperationalError

from app.extensions import db
from app.jobs_manager import get_jobs_manager
from app.models import Feed, Identification, ModelCall, Post, TranscriptSegment, User
from app.posts import clear_post_processing_data

logger = logging.getLogger("global_logger")


post_bp = Blueprint("post", __name__)


def _require_sponsor_or_admin(
    feed: Feed,
    action: str = "perform this action",
) -> Tuple[User | None, flask.Response | None]:
    """Check if the current user is the feed sponsor or an admin.

    When auth is disabled, returns (None, None) to allow access.

    Args:
        feed: The feed to check authorization for.
        action: A description of the action for the error message.
    """
    settings = current_app.config.get("AUTH_SETTINGS")
    if not settings or not settings.require_auth:
        return None, None

    current = getattr(g, "current_user", None)
    if current is None:
        return None, flask.make_response(
            flask.jsonify({"error": "Authentication required."}), 401
        )

    user: User | None = User.query.get(current.id)
    if user is None:
        return None, flask.make_response(
            flask.jsonify({"error": "User not found."}), 404
        )

    is_admin = user.role == "admin"
    is_sponsor = feed.sponsor_user_id == user.id
    if not (is_admin or is_sponsor):
        return None, flask.make_response(
            flask.jsonify({"error": f"Only the sponsor or an admin can {action}."}),
            403,
        )

    return user, None


def _increment_download_count(post: Post) -> None:
    """Safely increment the download counter for a post."""
    try:
        updated = Post.query.filter_by(id=post.id).update(
            {Post.download_count: (Post.download_count or 0) + 1},
            synchronize_session=False,
        )
        if updated:
            post.download_count = (post.download_count or 0) + 1
        db.session.commit()
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(
            "Failed to increment download count for post %s: %s", post.guid, exc
        )
        db.session.rollback()


@post_bp.route("/api/feeds/<int:feed_id>/posts", methods=["GET"])
def api_feed_posts(feed_id: int) -> flask.Response:
    """Returns a JSON list of posts for a specific feed."""

    feed = Feed.query.get_or_404(feed_id)
    posts = [
        {
            "id": post.id,
            "guid": post.guid,
            "title": post.title,
            "description": post.description,
            "release_date": (
                post.release_date.isoformat() if post.release_date else None
            ),
            "duration": post.duration,
            "whitelisted": post.whitelisted,
            "has_processed_audio": post.processed_audio_path is not None,
            "has_unprocessed_audio": post.unprocessed_audio_path is not None,
            "download_url": post.download_url,
            "image_url": post.image_url,
            "download_count": post.download_count,
        }
        for post in feed.posts
    ]
    return flask.jsonify(posts)


@post_bp.route("/post/<string:p_guid>/json", methods=["GET"])
def get_post_json(p_guid: str) -> flask.Response:
    logger.info(f"API request for post details with GUID: {p_guid}")
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        return flask.make_response(jsonify({"error": "Post not found"}), 404)

    segment_count = post.segments.count()
    transcript_segments = []

    if segment_count > 0:
        sample_segments = post.segments.limit(5).all()
        for segment in sample_segments:
            transcript_segments.append(
                {
                    "id": segment.id,
                    "sequence_num": segment.sequence_num,
                    "start_time": segment.start_time,
                    "end_time": segment.end_time,
                    "text": (
                        segment.text[:100] + "..."
                        if len(segment.text) > 100
                        else segment.text
                    ),
                }
            )

    whisper_model_calls = []
    for model_call in post.model_calls.filter(
        ModelCall.model_name.like("%whisper%")
    ).all():
        whisper_model_calls.append(
            {
                "id": model_call.id,
                "model_name": model_call.model_name,
                "status": model_call.status,
                "first_segment": model_call.first_segment_sequence_num,
                "last_segment": model_call.last_segment_sequence_num,
                "timestamp": (
                    model_call.timestamp.isoformat() if model_call.timestamp else None
                ),
                "response": (
                    model_call.response[:100] + "..."
                    if model_call.response and len(model_call.response) > 100
                    else model_call.response
                ),
                "error": model_call.error_message,
            }
        )

    post_data = {
        "id": post.id,
        "guid": post.guid,
        "title": post.title,
        "feed_id": post.feed_id,
        "unprocessed_audio_path": post.unprocessed_audio_path,
        "processed_audio_path": post.processed_audio_path,
        "has_unprocessed_audio": post.unprocessed_audio_path is not None,
        "has_processed_audio": post.processed_audio_path is not None,
        "transcript_segment_count": segment_count,
        "transcript_sample": transcript_segments,
        "model_call_count": post.model_calls.count(),
        "whisper_model_calls": whisper_model_calls,
        "whitelisted": post.whitelisted,
        "download_count": post.download_count,
    }

    return flask.jsonify(post_data)


@post_bp.route("/post/<string:p_guid>/debug", methods=["GET"])
def post_debug(p_guid: str) -> flask.Response:
    """Debug view for a post, showing model calls, transcript segments, and identifications."""
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        return flask.make_response(("Post not found", 404))

    model_calls = (
        ModelCall.query.filter_by(post_id=post.id)
        .order_by(ModelCall.model_name, ModelCall.first_segment_sequence_num)
        .all()
    )

    transcript_segments = post.segments.all()

    identifications = (
        Identification.query.join(TranscriptSegment)
        .filter(TranscriptSegment.post_id == post.id)
        .order_by(TranscriptSegment.sequence_num)
        .all()
    )

    model_call_statuses: Dict[str, int] = {}
    model_types: Dict[str, int] = {}

    for call in model_calls:
        if call.status not in model_call_statuses:
            model_call_statuses[call.status] = 0
        model_call_statuses[call.status] += 1

        if call.model_name not in model_types:
            model_types[call.model_name] = 0
        model_types[call.model_name] += 1

    content_segments = sum(1 for i in identifications if i.label == "content")
    ad_segments = sum(1 for i in identifications if i.label == "ad")

    stats = {
        "total_segments": len(transcript_segments),
        "total_model_calls": len(model_calls),
        "total_identifications": len(identifications),
        "content_segments": content_segments,
        "ad_segments_count": ad_segments,
        "model_call_statuses": model_call_statuses,
        "model_types": model_types,
        "download_count": post.download_count,
    }

    return flask.make_response(
        flask.render_template(
            "post_debug.html",
            post=post,
            model_calls=model_calls,
            transcript_segments=transcript_segments,
            identifications=identifications,
            stats=stats,
        ),
        200,
    )


@post_bp.route("/api/posts/<string:p_guid>/stats", methods=["GET"])
def api_post_stats(p_guid: str) -> flask.Response:
    """Get processing statistics for a post in JSON format."""
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        return flask.make_response(flask.jsonify({"error": "Post not found"}), 404)

    model_calls = (
        ModelCall.query.filter_by(post_id=post.id)
        .order_by(ModelCall.model_name, ModelCall.first_segment_sequence_num)
        .all()
    )

    transcript_segments = post.segments.all()

    identifications = (
        Identification.query.join(TranscriptSegment)
        .filter(TranscriptSegment.post_id == post.id)
        .order_by(TranscriptSegment.sequence_num)
        .all()
    )

    model_call_statuses: Dict[str, int] = {}
    model_types: Dict[str, int] = {}

    for call in model_calls:
        if call.status not in model_call_statuses:
            model_call_statuses[call.status] = 0
        model_call_statuses[call.status] += 1

        if call.model_name not in model_types:
            model_types[call.model_name] = 0
        model_types[call.model_name] += 1

    content_segments = sum(1 for i in identifications if i.label == "content")
    ad_segments = sum(1 for i in identifications if i.label == "ad")

    model_call_details = []
    for call in model_calls:
        model_call_details.append(
            {
                "id": call.id,
                "model_name": call.model_name,
                "status": call.status,
                "segment_range": f"{call.first_segment_sequence_num}-{call.last_segment_sequence_num}",
                "first_segment_sequence_num": call.first_segment_sequence_num,
                "last_segment_sequence_num": call.last_segment_sequence_num,
                "timestamp": call.timestamp.isoformat() if call.timestamp else None,
                "retry_attempts": call.retry_attempts,
                "error_message": call.error_message,
                "prompt": call.prompt,
                "response": call.response,
            }
        )

    transcript_segments_data = []
    for segment in transcript_segments:
        segment_identifications = [
            i for i in identifications if i.transcript_segment_id == segment.id
        ]

        has_ad_label = any(i.label == "ad" for i in segment_identifications)
        primary_label = "ad" if has_ad_label else "content"

        transcript_segments_data.append(
            {
                "id": segment.id,
                "sequence_num": segment.sequence_num,
                "start_time": round(segment.start_time, 1),
                "end_time": round(segment.end_time, 1),
                "text": segment.text,
                "primary_label": primary_label,
                "identifications": [
                    {
                        "id": ident.id,
                        "label": ident.label,
                        "confidence": (
                            round(ident.confidence, 2) if ident.confidence else None
                        ),
                        "model_call_id": ident.model_call_id,
                    }
                    for ident in segment_identifications
                ],
            }
        )

    identifications_data = []
    for identification in identifications:
        segment = identification.transcript_segment
        identifications_data.append(
            {
                "id": identification.id,
                "transcript_segment_id": identification.transcript_segment_id,
                "label": identification.label,
                "confidence": (
                    round(identification.confidence, 2)
                    if identification.confidence
                    else None
                ),
                "model_call_id": identification.model_call_id,
                "segment_sequence_num": segment.sequence_num,
                "segment_start_time": round(segment.start_time, 1),
                "segment_end_time": round(segment.end_time, 1),
                "segment_text": segment.text,
            }
        )

    stats_data = {
        "post": {
            "guid": post.guid,
            "title": post.title,
            "duration": post.duration,
            "release_date": (
                post.release_date.isoformat() if post.release_date else None
            ),
            "whitelisted": post.whitelisted,
            "has_processed_audio": post.processed_audio_path is not None,
            "download_count": post.download_count,
        },
        "processing_stats": {
            "total_segments": len(transcript_segments),
            "total_model_calls": len(model_calls),
            "total_identifications": len(identifications),
            "content_segments": content_segments,
            "ad_segments_count": ad_segments,
            "model_call_statuses": model_call_statuses,
            "model_types": model_types,
        },
        "model_calls": model_call_details,
        "transcript_segments": transcript_segments_data,
        "identifications": identifications_data,
    }

    return flask.jsonify(stats_data)


@post_bp.route("/api/posts/<string:p_guid>/whitelist", methods=["POST"])
def api_toggle_whitelist(p_guid: str) -> ResponseReturnValue:
    """Toggle whitelist status for a post via API.

    Only the feed sponsor or an admin can use this endpoint.
    """
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        return flask.make_response(flask.jsonify({"error": "Post not found"}), 404)

    feed = Feed.query.get(post.feed_id)
    if feed is None:
        return flask.make_response(flask.jsonify({"error": "Feed not found"}), 404)

    _, error = _require_sponsor_or_admin(feed, "whitelist this episode")
    if error:
        return error

    data = request.get_json()
    if data is None or "whitelisted" not in data:
        return flask.make_response(
            flask.jsonify({"error": "Missing whitelisted field"}), 400
        )

    post.whitelisted = bool(data["whitelisted"])
    try:
        db.session.commit()
    except OperationalError:
        db.session.rollback()
        return (
            flask.jsonify(
                {
                    "error": "Database busy, please retry",
                    "retry_after_seconds": 1,
                }
            ),
            503,
        )

    return flask.jsonify(
        {
            "guid": post.guid,
            "whitelisted": post.whitelisted,
            "message": "Whitelist status updated successfully",
        }
    )


@post_bp.route("/api/feeds/<int:feed_id>/toggle-whitelist-all", methods=["POST"])
def api_toggle_whitelist_all(feed_id: int) -> ResponseReturnValue:
    """Intelligently toggle whitelist status for all posts in a feed.

    Only the feed sponsor or an admin can use this endpoint.
    """
    feed = Feed.query.get_or_404(feed_id)

    _, error = _require_sponsor_or_admin(feed, "whitelist all posts")
    if error:
        return error

    if not feed.posts:
        return flask.jsonify(
            {
                "message": "No posts found in this feed",
                "whitelisted_count": 0,
                "total_count": 0,
            }
        )

    all_whitelisted = all(post.whitelisted for post in feed.posts)
    new_status = not all_whitelisted

    try:
        updated = Post.query.filter_by(feed_id=feed.id).update(
            {Post.whitelisted: new_status}, synchronize_session=False
        )
        db.session.commit()
    except OperationalError:
        db.session.rollback()
        return (
            flask.jsonify(
                {
                    "error": "Database busy, please retry",
                    "retry_after_seconds": 1,
                }
            ),
            503,
        )

    whitelisted_count = Post.query.filter_by(feed_id=feed.id, whitelisted=True).count()
    total_count = Post.query.filter_by(feed_id=feed.id).count()

    return flask.jsonify(
        {
            "message": f"{'Whitelisted' if new_status else 'Unwhitelisted'} all posts",
            "whitelisted_count": whitelisted_count,
            "total_count": total_count,
            "all_whitelisted": new_status,
            "updated_count": updated,
        }
    )


@post_bp.route("/api/posts/<string:p_guid>/process", methods=["POST"])
def api_process_post(p_guid: str) -> ResponseReturnValue:
    """Start processing a post and return immediately.

    Only the feed sponsor or an admin can use this endpoint.
    """
    post = Post.query.filter_by(guid=p_guid).first()
    if not post:
        return (
            flask.jsonify(
                {
                    "status": "error",
                    "error_code": "NOT_FOUND",
                    "message": "Post not found",
                }
            ),
            404,
        )

    feed = Feed.query.get(post.feed_id)
    if feed is None:
        return (
            flask.jsonify(
                {
                    "status": "error",
                    "error_code": "FEED_NOT_FOUND",
                    "message": "Feed not found",
                }
            ),
            404,
        )

    _, error = _require_sponsor_or_admin(feed, "process this episode")
    if error:
        return error

    if not post.whitelisted:
        return (
            flask.jsonify(
                {
                    "status": "error",
                    "error_code": "NOT_WHITELISTED",
                    "message": "Post not whitelisted",
                }
            ),
            400,
        )

    if post.processed_audio_path and os.path.exists(post.processed_audio_path):
        return flask.jsonify(
            {
                "status": "completed",
                "message": "Post already processed",
                "download_url": f"/api/posts/{p_guid}/download",
            }
        )

    try:
        result = get_jobs_manager().start_post_processing(
            p_guid, priority="interactive"
        )
        status_code = 200 if result.get("status") in ("started", "completed") else 400
        return flask.jsonify(result), status_code
    except Exception as e:
        logger.error(f"Failed to start processing job for {p_guid}: {e}")
        return (
            flask.jsonify(
                {
                    "status": "error",
                    "error_code": "JOB_START_FAILED",
                    "message": f"Failed to start processing job: {str(e)}",
                }
            ),
            500,
        )


@post_bp.route("/api/posts/<string:p_guid>/reprocess", methods=["POST"])
def api_reprocess_post(p_guid: str) -> ResponseReturnValue:
    """Clear all processing data for a post and start processing from scratch.

    Only the feed sponsor or an admin can use this endpoint.
    """
    post = Post.query.filter_by(guid=p_guid).first()
    if not post:
        return (
            flask.jsonify(
                {
                    "status": "error",
                    "error_code": "NOT_FOUND",
                    "message": "Post not found",
                }
            ),
            404,
        )

    feed = Feed.query.get(post.feed_id)
    if feed is None:
        return (
            flask.jsonify(
                {
                    "status": "error",
                    "error_code": "FEED_NOT_FOUND",
                    "message": "Feed not found",
                }
            ),
            404,
        )

    _, error = _require_sponsor_or_admin(feed, "reprocess this episode")
    if error:
        return error

    if not post.whitelisted:
        return (
            flask.jsonify(
                {
                    "status": "error",
                    "error_code": "NOT_WHITELISTED",
                    "message": "Post not whitelisted",
                }
            ),
            400,
        )

    try:
        get_jobs_manager().cancel_post_jobs(p_guid)
        clear_post_processing_data(post)
        result = get_jobs_manager().start_post_processing(
            p_guid, priority="interactive"
        )
        status_code = 200 if result.get("status") in ("started", "completed") else 400
        if result.get("status") == "started":
            result["message"] = "Post cleared and reprocessing started"
        return flask.jsonify(result), status_code
    except Exception as e:
        logger.error(f"Failed to reprocess post {p_guid}: {e}", exc_info=True)
        return (
            flask.jsonify(
                {
                    "status": "error",
                    "error_code": "REPROCESS_FAILED",
                    "message": f"Failed to reprocess post: {str(e)}",
                }
            ),
            500,
        )


@post_bp.route("/api/posts/<string:p_guid>/status", methods=["GET"])
def api_post_status(p_guid: str) -> ResponseReturnValue:
    """Get the current processing status of a post via JobsManager."""
    result = get_jobs_manager().get_post_status(p_guid)
    status_code = (
        200
        if result.get("status") != "error"
        else (404 if result.get("error_code") == "NOT_FOUND" else 400)
    )
    return flask.jsonify(result), status_code


@post_bp.route("/api/posts/<string:p_guid>/audio", methods=["GET"])
def api_get_post_audio(p_guid: str) -> ResponseReturnValue:
    """API endpoint to serve processed audio files with proper CORS headers."""
    logger.info(f"API request for audio file with GUID: {p_guid}")

    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        logger.warning(f"Post with GUID: {p_guid} not found")
        return flask.make_response(
            jsonify({"error": "Post not found", "error_code": "NOT_FOUND"}), 404
        )

    if not post.whitelisted:
        logger.warning(f"Post: {post.title} is not whitelisted")
        return flask.make_response(
            jsonify({"error": "Post not whitelisted", "error_code": "NOT_WHITELISTED"}),
            403,
        )

    if not post.processed_audio_path or not Path(post.processed_audio_path).exists():
        logger.warning(f"Processed audio not found for post: {post.id}")
        return flask.make_response(
            jsonify(
                {
                    "error": "Processed audio not available",
                    "error_code": "AUDIO_NOT_READY",
                    "message": "Post needs to be processed first",
                }
            ),
            404,
        )

    try:
        response = send_file(
            path_or_file=Path(post.processed_audio_path).resolve(),
            mimetype="audio/mpeg",
            as_attachment=False,
        )
        response.headers["Accept-Ranges"] = "bytes"
        return response
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Error serving audio file for {p_guid}: {e}")
        return flask.make_response(
            jsonify(
                {"error": "Error serving audio file", "error_code": "SERVER_ERROR"}
            ),
            500,
        )


@post_bp.route("/api/posts/<string:p_guid>/download", methods=["GET"])
def api_download_post(p_guid: str) -> flask.Response:
    """API endpoint to download processed audio files."""
    logger.info(f"Request to download post with GUID: {p_guid}")
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        logger.warning(f"Post with GUID: {p_guid} not found")
        return flask.make_response(("Post not found", 404))

    if not post.whitelisted:
        logger.warning(f"Post: {post.title} is not whitelisted")
        return flask.make_response(("Post not whitelisted", 403))

    if not post.processed_audio_path or not Path(post.processed_audio_path).exists():
        logger.warning(f"Processed audio not found for post: {post.id}")
        return flask.make_response(("Processed audio not found", 404))

    try:
        response = send_file(
            path_or_file=Path(post.processed_audio_path).resolve(),
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name=f"{post.title}.mp3",
        )
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Error serving file for {p_guid}: {e}")
        return flask.make_response(("Error serving file", 500))

    _increment_download_count(post)
    return response


@post_bp.route("/api/posts/<string:p_guid>/download/original", methods=["GET"])
def api_download_original_post(p_guid: str) -> flask.Response:
    """API endpoint to download original (unprocessed) audio files."""
    logger.info(f"Request to download original post with GUID: {p_guid}")
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        logger.warning(f"Post with GUID: {p_guid} not found")
        return flask.make_response(("Post not found", 404))

    if not post.whitelisted:
        logger.warning(f"Post: {post.title} is not whitelisted")
        return flask.make_response(("Post not whitelisted", 403))

    if (
        not post.unprocessed_audio_path
        or not Path(post.unprocessed_audio_path).exists()
    ):
        logger.warning(f"Original audio not found for post: {post.id}")
        return flask.make_response(("Original audio not found", 404))

    try:
        response = send_file(
            path_or_file=Path(post.unprocessed_audio_path).resolve(),
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name=f"{post.title}_original.mp3",
        )
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Error serving original file for {p_guid}: {e}")
        return flask.make_response(("Error serving file", 500))

    _increment_download_count(post)
    return response


# Legacy endpoints for backward compatibility
@post_bp.route("/post/<string:p_guid>.mp3", methods=["GET"])
def download_post_legacy(p_guid: str) -> flask.Response:
    return api_download_post(p_guid)


@post_bp.route("/post/<string:p_guid>/original.mp3", methods=["GET"])
def download_original_post_legacy(p_guid: str) -> flask.Response:
    return api_download_original_post(p_guid)
