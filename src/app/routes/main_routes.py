import logging
import os

import flask
from flask import Blueprint, current_app, g, send_from_directory

from app.extensions import db
from app.models import Feed, Post, User
from app.runtime_config import config
from app.writer.client import writer_client

logger = logging.getLogger("global_logger")

logger = logging.getLogger("global_logger")


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


def _require_admin(action: str = "perform this action") -> flask.Response | None:
    """Guard endpoints so only admins can access them when auth is enabled."""

    settings = current_app.config.get("AUTH_SETTINGS")
    if not settings or not settings.require_auth:
        return None

    current = getattr(g, "current_user", None)
    if current is None:
        return flask.make_response(
            flask.jsonify({"error": "Authentication required."}), 401
        )

    user: User | None = db.session.get(User, current.id)
    if user is None:
        return flask.make_response(flask.jsonify({"error": "User not found."}), 404)

    if user.role != "admin":
        return flask.make_response(
            flask.jsonify({"error": f"Only admins can {action}."}), 403
        )

    return None


@main_bp.route("/feed/<int:f_id>/toggle-whitelist-all/<val>", methods=["POST"])
def whitelist_all(f_id: str, val: str) -> flask.Response:
    error_response = _require_admin("toggle whitelist for all posts")
    if error_response:
        return error_response

    feed = Feed.query.get_or_404(f_id)
    new_status = val.lower() == "true"
    try:
        result = writer_client.action(
            "toggle_whitelist_all_for_feed",
            {"feed_id": feed.id, "new_status": new_status},
            wait=True,
        )
        if not result or not result.success:
            raise RuntimeError(getattr(result, "error", "Unknown writer error"))
    except Exception:  # pylint: disable=broad-except
        return flask.make_response(
            (
                flask.jsonify(
                    {
                        "error": "Database busy, please retry",
                        "retry_after_seconds": 1,
                    }
                ),
                503,
            )
        )
    return flask.make_response("", 200)


@main_bp.route("/set_whitelist/<string:p_guid>/<val>", methods=["GET"])
def set_whitelist(p_guid: str, val: str) -> flask.Response:
    logger.info(f"Setting whitelist status for post with GUID: {p_guid} to {val}")
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        return flask.make_response(("Post not found", 404))

    new_status = val.lower() == "true"
    try:
        result = writer_client.update(
            "Post", post.id, {"whitelisted": new_status}, wait=True
        )
        if not result or not result.success:
            raise RuntimeError(getattr(result, "error", "Unknown writer error"))
        db.session.expire(post)
    except Exception:  # pylint: disable=broad-except
        return flask.make_response(
            (
                flask.jsonify(
                    {
                        "error": "Database busy, please retry",
                        "retry_after_seconds": 1,
                    }
                ),
                503,
            )
        )

    return index()
