import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, cast

import bleach
import flask
import validators
from flask import Blueprint, Flask, current_app, jsonify, request, send_file, url_for
from flask.typing import ResponseReturnValue
from sqlalchemy.orm import sessionmaker

from app import config, db, logger, scheduler
from app.feeds import add_or_refresh_feed, generate_feed_xml, refresh_feed
from app.jobs import run_refresh_feed
from app.models import Feed, Identification, ModelCall, Post, TranscriptSegment
from app.processor import get_processor
from app.utils.renderers import render_transcript_html
from shared.podcast_downloader import download_episode

main_bp = Blueprint("main", __name__)


def fix_url(url: str) -> str:
    url = re.sub(r"(http(s)?):/([^/])", r"\1://\3", url)
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url


@main_bp.route("/")
def index() -> flask.Response:
    feeds = Feed.query.all()

    return flask.make_response(
        flask.render_template("index.html", feeds=feeds, config=config), 200
    )


@main_bp.route("/post/<string:p_guid>.html", methods=["GET"])
def post_page(p_guid: str) -> flask.Response:
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        return flask.make_response(("Post not found", 404))

    # the spec defines some allowed tags. strip other for security
    # https://github.com/Podcast-Standards-Project/PSP-1-Podcast-RSS-Specification?tab=readme-ov-file#item-description
    spec_tags = ["p", "ol", "ul", "li", "a", "b", "i", "strong", "em"]
    allowed_tags = spec_tags + ["br"]
    allowed_attributes = {"a": ["href", "title"]}
    clean_description = bleach.clean(
        post.description,
        tags=allowed_tags,
        attributes=allowed_attributes,
    )

    # Render the transcript HTML using the utility function
    transcript_html = render_transcript_html(post)

    return flask.make_response(
        flask.render_template(
            "post.html",
            post=post,
            clean_description=clean_description,
            transcript_html=transcript_html,
        ),
        200,
    )


@main_bp.route("/feed/<int:f_id>/toggle-whitelist-all/<val>", methods=["POST"])
def whitelist_all(f_id: str, val: str) -> flask.Response:
    feed = Feed.query.get_or_404(f_id)
    for post in feed.posts:
        post.whitelisted = val.lower() == "true"
    db.session.commit()
    return flask.make_response("", 200)


@main_bp.route("/set_whitelist/<string:p_guid>/<val>", methods=["GET"])
def set_whitelist(p_guid: str, val: str) -> flask.Response:
    logger.info(f"Setting whitelist status for post with GUID: {p_guid} to {val}")
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        return flask.make_response(("Post not found", 404))

    post.whitelisted = val.lower() == "true"
    db.session.commit()

    return index()


def download_and_process(post: Post, app: Flask) -> Dict[str, Any]:
    """
    Downloads and processes a single podcast episode.

    Args:
        post (Post): The podcast post to download and process.
        app (Flask): The Flask application instance.

    Returns:
        dict: A dictionary containing the status and any relevant messages.
    """
    thread_session = None
    result = {}

    try:
        with app.app_context():  # Push application context
            engine = db.get_engine()
            session_factory = sessionmaker(bind=engine)
            thread_session = session_factory()

            post_in_thread = thread_session.merge(post)
            # Download the episode
            download_path = download_episode(post_in_thread)
            if download_path is None:
                logger.error(
                    f"Failed to download post: {post_in_thread.title} (ID: {post_in_thread.id})"
                )
                result = {
                    "post_id": post_in_thread.id,
                    "title": post_in_thread.title,
                    "status": "failed",
                    "message": "Download failed.",
                }
                return result

            post_in_thread.unprocessed_audio_path = download_path
            thread_session.commit()

            output_path = get_processor().process(post_in_thread, blocking=True)
            if output_path is None:
                logger.error(
                    f"Failed to process post: {post_in_thread.title} (ID: {post_in_thread.id})"
                )
                result = {
                    "post_id": post_in_thread.id,
                    "title": post_in_thread.title,
                    "status": "failed",
                    "message": "Processing failed.",
                }
                return result

            post_in_thread.processed_audio_path = output_path
            thread_session.commit()

            logger.info(
                f"Successfully downloaded and processed post: "
                f"{post_in_thread.title} (ID: {post_in_thread.id})"
            )
            result = {
                "post_id": post_in_thread.id,
                "title": post_in_thread.title,
                "status": "success",
                "message": output_path,
            }

    except Exception as e:  # pylint: disable=broad-except
        post_id = post.id if "post_in_thread" not in locals() else post_in_thread.id
        post_title = (
            post.title if "post_in_thread" not in locals() else post_in_thread.title
        )
        logger.error(f"Error downloading and processing post {post_id}: {e}")
        if thread_session:
            thread_session.rollback()
        result = {
            "post_id": post_id,
            "title": post_title,
            "status": "error",
            "message": str(e),
        }
    finally:
        if thread_session:
            thread_session.close()

    return result


@main_bp.route("/post/<string:p_guid>.mp3", methods=["GET"])
def download_post(p_guid: str) -> flask.Response:
    logger.info(f"Request to download post with GUID: {p_guid}")
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        logger.warning(f"Post with GUID: {p_guid} not found")
        return flask.make_response(("Post not found", 404))

    if not post.whitelisted:
        logger.warning(f"Post: {post.title} is not whitelisted")
        return flask.make_response(("Episode not whitelisted", 403))

    # pylint: disable=protected-access
    app = cast(Flask, current_app._get_current_object())  # type: ignore[attr-defined]

    result = download_and_process(post, app)
    if result["status"] == "success":
        try:
            output_path = result["message"]
            return send_file(path_or_file=Path(output_path).resolve())
        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"Error sending file: {e}")
            return flask.make_response(("Error sending file", 500))
    else:
        return flask.make_response((result["message"], 500))


@main_bp.route("/post/<string:p_guid>/original.mp3", methods=["GET"])
def download_original_post(p_guid: str) -> flask.Response:
    """Endpoint to access the original unprocessed audio file for testing purposes."""
    logger.info(
        f"Request to download original unprocessed audio for post with GUID: {p_guid}"
    )
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        logger.warning(f"Post with GUID: {p_guid} not found")
        return flask.make_response(("Post not found", 404))

    if not post.whitelisted:
        logger.warning(f"Post: {post.title} is not whitelisted")
        return flask.make_response(("Episode not whitelisted", 403))

    # pylint: disable=protected-access
    app = cast(Flask, current_app._get_current_object())  # type: ignore[attr-defined]

    # If the episode hasn't been downloaded yet, do that first
    if post.unprocessed_audio_path is None:
        result = download_and_process(post, app)
        if result["status"] != "success":
            return flask.make_response((result["message"], 500))

    # Try to send the original unprocessed file
    try:
        if post.unprocessed_audio_path and Path(post.unprocessed_audio_path).exists():
            return send_file(path_or_file=Path(post.unprocessed_audio_path).resolve())
        logger.error(f"Original unprocessed audio file not found for post: {post.id}")
        return flask.make_response(("Original audio file not found", 404))
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Error sending original file: {e}")
        return flask.make_response(("Error sending original file", 500))


@main_bp.route("/download_all", methods=["POST"])
def download_all_posts() -> flask.Response:
    logger.info("Initiating bulk download of all podcasts (ignoring whitelist status).")
    posts = Post.query.all()
    if not posts:
        logger.info("No podcast posts available for download.")
        return flask.make_response(("No podcasts available for download.", 400))

    download_results: List[Dict[str, Any]] = []

    # Determine the number of worker threads based on config
    max_workers = config.threads if config.threads > 0 else 1  # Default to 1 if not set

    # Retrieve the Flask application instance

    # pylint: disable=protected-access
    app = current_app._get_current_object()  # type: ignore[attr-defined]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all download tasks to the executor, passing both post and app
        future_to_post = {
            executor.submit(download_and_process, post, app): post for post in posts
        }

        for future in as_completed(future_to_post):
            post = future_to_post[future]
            try:
                result = future.result()
                download_results.append(result)
            except Exception as e:  # pylint: disable=broad-except
                logger.error(f"Unhandled exception for post {post.id}: {e}")
                download_results.append(
                    {
                        "post_id": post.id,
                        "title": post.title,
                        "status": "error",
                        "message": str(e),
                    }
                )

    logger.info("Bulk download completed.")
    return flask.make_response(jsonify(download_results), 200)


@main_bp.route("/feeds", methods=["GET"])
def api_feeds() -> flask.Response:
    """Returns a JSON list of all feeds with their ID, URL, and title."""
    feeds = Feed.query.all()
    feed_list = [
        {"id": feed.id, "rss_url": feed.rss_url, "title": feed.title} for feed in feeds
    ]
    return flask.jsonify(feed_list)


@main_bp.route("/feed", methods=["POST"])
def add_feed() -> ResponseReturnValue:
    data = request.form

    if not data or "url" not in data:
        logger.error("URL is required")
        return flask.make_response(jsonify({"error": "URL is required"}), 400)

    try:
        add_or_refresh_feed(data["url"])
        db.session.commit()
        return flask.redirect(url_for("main.index"))
    except ValueError as e:
        logger.error(f"Error adding feed: {e}")
        db.session.rollback()
        return flask.make_response(jsonify({"error": "Invalid feed URL"}), 400)
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Unexpected error: {e}")
        db.session.rollback()
        return flask.make_response(
            jsonify({"error": "An unexpected error occurred"}), 500
        )


@main_bp.route("/feed/<int:f_id>", methods=["GET"])
def get_feed(f_id: int) -> flask.Response:
    logger.info(f"Fetching feed with ID: {f_id}")
    feed = Feed.query.get_or_404(f_id)

    if config.background_update_interval_minute is None:
        refresh_feed(feed)
    else:
        scheduler.add_job(
            id=f"refresh-feed-{feed.id}", func=run_refresh_feed, args=[f_id]
        )

    feed_xml = generate_feed_xml(feed)
    logger.info(f"Feed with ID: {f_id} fetched and XML generated")
    return flask.make_response(feed_xml, 200, {"Content-Type": "application/xml"})


@main_bp.route("/feed/<int:f_id>", methods=["DELETE"])
def delete_feed(f_id: int) -> flask.Response:
    logger.info(f"Deleting feed with ID: {f_id}")
    feed = Feed.query.get_or_404(f_id)
    try:
        for post in feed.posts:
            # Delete identifications first to avoid constraint violations
            for model_call in post.model_calls.all():
                # Delete all identifications associated with this model call
                db.session.query(Identification).filter_by(
                    model_call_id=model_call.id
                ).delete()
                db.session.delete(model_call)

            # Now it's safe to delete segments
            for segment in post.segments.all():
                db.session.delete(segment)

            db.session.delete(post)

        db.session.delete(feed)
        db.session.commit()
        logger.info(f"Feed with ID: {f_id} deleted")
        return flask.Response(status=204)
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Error deleting feed {f_id}: {e}")
        db.session.rollback()
        return flask.make_response(
            jsonify({"error": f"Failed to delete feed: {str(e)}"}), 500
        )


# backwards compatibility for the old method of subscribing to feeds
@main_bp.route("/<path:feed_alt_or_url>", methods=["GET"])
def get_feed_by_alt_or_url(feed_alt_or_url: str) -> flask.Response:
    # first try to serve ANY static file matching the path
    try:
        if "favicon.ico" in feed_alt_or_url:
            return flask.send_from_directory("static", "favicon.ico")
        return flask.send_from_directory("static", feed_alt_or_url)
    except Exception as e:  # pylint: disable=broad-except
        logger.debug(
            f"no static file match on {feed_alt_or_url}, continuing with catch-all subscribe: {e}"
        )

    logger.info(f"Fetching feed with url/alt ID: {feed_alt_or_url}")
    feed = Feed.query.filter_by(alt_id=feed_alt_or_url).first()
    if feed is not None:
        logger.info(f"Feed: {feed.title} found, refreshing")
        refresh_feed(feed)
        feed_xml = generate_feed_xml(feed)
        logger.info(
            f"Feed with alternate ID: {feed_alt_or_url} fetched and XML generated"
        )
        return flask.make_response(feed_xml, 200, {"Content-Type": "application/xml"})

    logger.debug("No existing feed found, checking URL")
    feed_alt_or_url = fix_url(feed_alt_or_url)
    if not validators.url(feed_alt_or_url):
        logger.error("Invalid URL")
        return flask.make_response(("Invalid URL", 400))
    logger.info(f"Feed with URL: {feed_alt_or_url} not found, adding")
    feed = add_or_refresh_feed(feed_alt_or_url)
    feed_xml = generate_feed_xml(feed)
    logger.info(
        f"Feed with ID: {feed.id} added/refreshed via old method and XML generated"
    )
    return flask.make_response(feed_xml, 200, {"Content-Type": "application/xml"})


@main_bp.route("/post/<string:p_guid>/json", methods=["GET"])
def get_post_json(p_guid: str) -> flask.Response:
    logger.info(f"API request for post details with GUID: {p_guid}")
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        return flask.make_response(jsonify({"error": "Post not found"}), 404)

    # Check how many transcript segments exist
    segment_count = post.segments.count()
    transcript_segments = []

    # Get a sample of segments if they exist (limited to 5 for response size)
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

    # Get Whisper model call information
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

    # Prepare response data
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
    }

    return flask.jsonify(post_data)


@main_bp.route("/post/<string:p_guid>/debug", methods=["GET"])
def post_debug(p_guid: str) -> flask.Response:
    """Debug view for a post, showing model calls, transcript segments, and identifications."""
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        return flask.make_response(("Post not found", 404))

    # Get model calls for this post
    model_calls = (
        ModelCall.query.filter_by(post_id=post.id)
        .order_by(ModelCall.model_name, ModelCall.first_segment_sequence_num)
        .all()
    )

    # Get transcript segments (they're already ordered by sequence_num from the relationship)
    transcript_segments = post.segments.all()

    # Get identifications for this post's segments
    identifications = (
        Identification.query.join(TranscriptSegment)
        .filter(TranscriptSegment.post_id == post.id)
        .order_by(TranscriptSegment.sequence_num)
        .all()
    )

    # Create dictionaries to track stats
    model_call_statuses: Dict[str, int] = {}
    model_types: Dict[str, int] = {}

    # Count model call statuses
    for call in model_calls:
        if call.status not in model_call_statuses:
            model_call_statuses[call.status] = 0
        model_call_statuses[call.status] += 1

        if call.model_name not in model_types:
            model_types[call.model_name] = 0
        model_types[call.model_name] += 1

    # Compute some stats for display with proper type annotations
    stats: Dict[str, Any] = {
        "total_segments": len(transcript_segments),
        "total_model_calls": len(model_calls),
        "total_identifications": len(identifications),
        "ad_segments_count": sum(1 for i in identifications if i.label == "ad"),
        "model_call_statuses": model_call_statuses,
        "model_types": model_types,
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
