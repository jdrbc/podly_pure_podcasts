import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import flask
import validators
from flask import (
    Blueprint,
    jsonify,
    request,
    send_file,
    url_for,
    current_app,
    Flask
)
from flask.typing import ResponseReturnValue

from app import config, db, logger
from app.feeds import add_or_refresh_feed, generate_feed_xml, refresh_feed
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

    return flask.make_response(flask.render_template("post.html", post=post), 200)


@main_bp.route("/set_whitelist/<string:p_guid>/<val>", methods=["GET"])
def set_whitelist(p_guid: str, val: str) -> flask.Response:
    logger.info(f"Setting whitelist status for post with GUID: {p_guid} to {val}")
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        return flask.make_response(("Post not found", 404))

    post.whitelisted = val.lower() == "true"
    db.session.commit()

    return index()

processor = PodcastProcessor(config) #pre-initialize here rather than each post

def download_and_process(post: Post, app: Flask) -> dict:
    """
    Downloads and processes a single podcast episode.

    Args:
        post (Post): The podcast post to download and process.
        app (Flask): The Flask application instance.

    Returns:
        dict: A dictionary containing the status and any relevant messages.
    """
    try:
        with app.app_context():  # Push application context
            # Download the episode
            download_path = download_episode(post)
            if download_path is None:
                logger.error(f"Failed to download post: {post.title} (ID: {post.id})")
                return {
                    "post_id": post.id,
                    "title": post.title,
                    "status": "failed",
                    "message": "Download failed."
                }

            post.unprocessed_audio_path = download_path
            db.session.commit()

            # Process the episode
            output_path = processor.process(post)
            if output_path is None:
                logger.error(f"Failed to process post: {post.title} (ID: {post.id})")
                return {
                    "post_id": post.id,
                    "title": post.title,
                    "status": "failed",
                    "message": "Processing failed."
                }

            post.processed_audio_path = output_path
            db.session.commit()

            logger.info(f"Successfully downloaded and processed post: {post.title} (ID: {post.id})")
            return {
                "post_id": post.id,
                "title": post.title,
                "status": "success",
                "message": output_path
            }

    except Exception as e:
        logger.error(f"Error downloading and processing post {post.id}: {e}")
        return {
            "post_id": post.id,
            "title": post.title,
            "status": "error",
            "message": str(e)
        }

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

    # Retrieve the Flask application instance
    app = current_app._get_current_object()

    # Utilize the refactored download_and_process function with app
    result = download_and_process(post, app)

    if result["status"] == "success":
        try:
            output_path = result["message"]
            return send_file(path_or_file=Path(output_path).resolve())
        except Exception as e:
            logger.error(f"Error sending file: {e}")
            return flask.make_response(("Error sending file", 500))
    else:
        return flask.make_response((result["message"], 500))

@main_bp.route("/download_all", methods=["POST"])
def download_all_posts() -> flask.Response:
    logger.info("Initiating bulk download of all podcasts (ignoring whitelist status).")
    posts = Post.query.all()
    if not posts:
        logger.info("No podcast posts available for download.")
        return flask.make_response(("No podcasts available for download.", 400))

    download_results = []

    # Determine the number of worker threads based on config
    max_workers = config.threads if config.threads > 0 else 1  # Default to 1 if not set

    # Retrieve the Flask application instance
    app = current_app._get_current_object()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all download tasks to the executor, passing both post and app
        future_to_post = {executor.submit(download_and_process, post, app): post for post in posts}

        for future in as_completed(future_to_post):
            post = future_to_post[future]
            try:
                result = future.result()
                download_results.append(result)
            except Exception as e:
                logger.error(f"Unhandled exception for post {post.id}: {e}")
                download_results.append({
                    "post_id": post.id,
                    "title": post.title,
                    "status": "error",
                    "message": str(e)
                })

    logger.info("Bulk download completed.")
    return jsonify(download_results), 200

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
    refresh_feed(feed)
    feed_xml = generate_feed_xml(feed)
    logger.info(f"Feed with ID: {f_id} fetched and XML generated")
    return flask.make_response(feed_xml, 200, {"Content-Type": "application/xml"})


@main_bp.route("/feed/<int:f_id>", methods=["DELETE"])
def delete_feed(f_id: int) -> flask.Response:
    logger.info(f"Deleting feed with ID: {f_id}")
    feed = Feed.query.get_or_404(f_id)
    for post in feed.posts:
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
