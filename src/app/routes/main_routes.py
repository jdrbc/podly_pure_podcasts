import os

import flask
from flask import Blueprint, current_app, send_from_directory

from app import config, db, logger
from app.models import Feed, Post

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index() -> flask.Response:
    """Serve the React app's index.html."""
    static_folder = current_app.static_folder
    if static_folder and os.path.exists(os.path.join(static_folder, "index.html")):
        return send_from_directory(static_folder, "index.html")

    feeds = Feed.query.all()
    return flask.make_response(
        flask.render_template("index.html", feeds=feeds, config=config), 200
    )


@main_bp.route("/<path:path>")
def catch_all(path: str) -> flask.Response:
    """Serve React app for all frontend routes, or serve static files."""
    # Don't handle API routes - let them be handled by API blueprint
    if path.startswith("api/"):
        flask.abort(404)

    static_folder = current_app.static_folder
    if static_folder:
        # First try to serve a static file if it exists
        static_file_path = os.path.join(static_folder, path)
        if os.path.exists(static_file_path) and os.path.isfile(static_file_path):
            return send_from_directory(static_folder, path)

        # If it's not a static file and index.html exists, serve the React app
        if os.path.exists(os.path.join(static_folder, "index.html")):
            return send_from_directory(static_folder, "index.html")

    # Fallback to 404
    flask.abort(404)


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
