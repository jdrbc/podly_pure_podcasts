import re
from pathlib import Path

import flask
import validators
from flask import Blueprint, current_app, send_file
from flask.typing import ResponseReturnValue

from app import db, logger
from app.feeds import add_or_refresh_feed, generate_feed_xml, refresh_feed
from app.models import (
    Feed,
    Identification,
    ModelCall,
    Post,
    ProcessingJob,
    TranscriptSegment,
)
from podcast_processor.podcast_downloader import sanitize_title

feed_bp = Blueprint("feed", __name__)


def fix_url(url: str) -> str:
    url = re.sub(r"(http(s)?):/([^/])", r"\1://\3", url)
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url


@feed_bp.route("/feed", methods=["POST"])
def add_feed() -> ResponseReturnValue:
    url = flask.request.form.get("url")
    if not url:
        return flask.make_response(("URL is required", 400))

    url = fix_url(url)

    if not validators.url(url):
        return flask.make_response(("Invalid URL", 400))

    try:
        add_or_refresh_feed(url)
        return flask.redirect(flask.url_for("main.index"))
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Error adding feed: {e}")
        return flask.make_response((f"Error adding feed: {e}", 500))


@feed_bp.route("/feed/<int:f_id>", methods=["GET"])
def get_feed(f_id: int) -> flask.Response:
    feed = Feed.query.get_or_404(f_id)

    # Refresh the feed
    refresh_feed(feed)

    # Generate the XML
    xml_content = generate_feed_xml(feed)

    response = flask.make_response(xml_content)
    response.headers["Content-Type"] = "application/rss+xml"
    return response


@feed_bp.route("/feed/<int:f_id>", methods=["DELETE"])
def delete_feed(f_id: int) -> flask.Response:
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
    return flask.make_response("", 204)


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

    srv_feed_dir = Path("srv") / sanitized_feed_title
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
        in_post_dir = Path("in") / sanitized_post_title
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
def get_feed_by_alt_or_url(something_or_rss: str) -> flask.Response:
    # first try to serve ANY static file matching the path
    if current_app.static_folder is not None:
        static_file_path = Path(current_app.static_folder) / something_or_rss
        if static_file_path.exists() and static_file_path.is_file():
            return send_file(static_file_path)
    feed = Feed.query.filter_by(rss_url=something_or_rss).first()
    if feed:
        xml_content = generate_feed_xml(feed)
        response = flask.make_response(xml_content)
        response.headers["Content-Type"] = "application/rss+xml"
        return response

    return flask.make_response(("Feed not found", 404))
