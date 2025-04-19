import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List

import bleach
import flask
import validators
from flask import Blueprint, jsonify, request, send_file, url_for
from flask.typing import ResponseReturnValue

from app import config, db, logger, scheduler
from app.feeds import add_or_refresh_feed, generate_feed_xml, refresh_feed
from app.jobs import run_refresh_feed
from app.models import Feed, Post
from podcast_processor.podcast_processor import PodcastProcessor
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

    return flask.make_response(
        flask.render_template(
            "post.html", post=post, clean_description=clean_description
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


processor = PodcastProcessor(config)  # pre-initialize here rather than each post


# Restore a simplified download_and_process helper
def download_and_process(post: Post) -> Dict[str, Any]:
    """Downloads and processes a podcast episode atomically.

    Handles downloading the audio file, processing it (transcription, etc.),
    and saving all changes to the database in a single transaction.
    If any step fails, the entire transaction is rolled back.

    Args:
        post: The Post object representing the episode to process.
              This object will be modified in place.

    Returns:
        A dictionary containing the status and results:
            {
                "status": "success" | "failed" | "error",
                "message": str (contains output path on success, error message otherwise),
                "post_id": int,
                "title": str,
            }
    """
    logger.info(f"[download_and_process {post.id}] Starting for post: {post.title}")
    try:
        # Assume we are within request context providing app_context and session

        # --- Download ---
        logger.debug(f"[download_and_process {post.id}] Downloading...")
        download_path = download_episode(post)
        if download_path is None:
            logger.error(f"[download_and_process {post.id}] Download failed.")
            # Return failure without altering DB state yet
            return {
                "status": "failed",
                "message": "Download failed",
                "post_id": post.id,
                "title": post.title,
            }
        post.unprocessed_audio_path = download_path
        logger.info(
            f"[download_and_process {post.id}] Download complete: {download_path}"
        )

        # --- Process ---
        logger.debug(f"[download_and_process {post.id}] Processing...")
        # processor.process updates the post object in memory (incl. transcript)
        output_path = processor.process(post, blocking=True)
        if output_path is None:
            logger.error(
                f"[download_and_process {post.id}] Processing failed internally."
            )
            raise ValueError("Processor returned None")  # Will trigger rollback
        post.processed_audio_path = output_path
        logger.info(
            f"[download_and_process {post.id}] Processing complete: {output_path}"
        )

        # --- Single Commit ---
        logger.debug(
            f"[download_and_process {post.id}] Merging final state before commit."
        )
        # Merge 'post' state before commit. Necessary because this function receives 'post'
        # as input and is called by 'download_all_posts' using threads. This ensures
        # the session in *this* thread reflects all changes made to 'post' before commit.
        db.session.merge(post)  # Ensure session sees all changes
        logger.debug(f"[download_and_process {post.id}] >>> ATTEMPTING FINAL COMMIT.")
        db.session.commit()
        logger.info(f"[download_and_process {post.id}] >>> COMMIT SUCCESSFUL.")
        return {
            "status": "success",
            "message": output_path,
            "post_id": post.id,
            "title": post.title,
        }

    except Exception as e:
        logger.error(f"[download_and_process {post.id}] Exception: {e}", exc_info=True)
        logger.debug(f"[download_and_process {post.id}] >>> ROLLING BACK transaction.")
        db.session.rollback()
        return {
            "status": "error",
            "message": str(e),
            "post_id": post.id,
            "title": post.title,
        }
    # No complex session removal needed here, assuming Flask handles request session lifecycle.


@main_bp.route("/post/<string:p_guid>.mp3", methods=["GET"])
def download_post(p_guid: str) -> flask.Response:
    logger.info(f"Request to download post with GUID: {p_guid}")
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        logger.warning(f"Post with GUID: {p_guid} not found")
        return flask.make_response(("Post not found", 404))

    # Check if already processed and file exists
    if post.processed_audio_path:
        processed_path = Path(post.processed_audio_path)
        if processed_path.is_file() and processed_path.stat().st_size > 0:
            logger.info(f"Processed file found for post {post.id}. Sending file.")
            try:
                return send_file(path_or_file=processed_path.resolve())
            except Exception as e:
                logger.error(f"Error sending file '{processed_path}': {e}")
                return flask.make_response(("Error sending file", 500))
        else:
            logger.warning(
                f"Processed path in DB for post {post.id} but file missing/empty. Will re-process."
            )
    else:  # Explicitly handle case where path is None
        logger.info(f"Processed path not set for post {post.id}. Will process.")

    # Check whitelist status (moved here to be checked just before processing)
    if not post.whitelisted:
        logger.warning(f"Post: {post.title} is not whitelisted for processing/download")
        return flask.make_response(("Episode not whitelisted", 403))

    logger.info(f"Attempting synchronous download/process for post {post.id}.")
    result = download_and_process(post)  # Call the simplified helper

    if result["status"] == "success":
        try:
            output_path = result["message"]
            logger.info(
                f"Processing successful for post {post.id}. Sending file: {output_path}"
            )
            return send_file(path_or_file=Path(output_path).resolve())
        except Exception as e:
            logger.error(f"Error sending file after processing post {post.id}: {e}")
            return flask.make_response(("Error sending file after processing", 500))
    else:
        logger.error(
            f"Processing failed for post {post.id}: {result.get('message', 'Unknown error')}"
        )
        return flask.make_response(
            (f"Processing failed: {result.get('message', 'Unknown error')}", 500)
        )


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

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit tasks using the simplified download_and_process helper
        future_to_post = {
            executor.submit(download_and_process, post): post for post in posts
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
    for post in feed.posts:
        if post.transcript:
            db.session.delete(post.transcript)
        db.session.delete(post)
    db.session.delete(feed)
    db.session.commit()
    logger.info(f"Feed with ID: {f_id} deleted")
    return flask.Response(status=204)


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
