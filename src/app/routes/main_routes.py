import logging
import os

import flask
from flask import Blueprint, send_from_directory

from app.auth.guards import require_admin
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
    static_folder = flask.current_app.static_folder
    if static_folder and os.path.exists(os.path.join(static_folder, "index.html")):
        return send_from_directory(static_folder, "index.html")

    feeds = Feed.query.all()
    return flask.make_response(
        flask.render_template("index.html", feeds=feeds, config=config), 200
    )


@main_bp.route("/api/landing/status", methods=["GET"])
def landing_status() -> flask.Response:
    """Public landing-page status with user counts and limits.

    Intended for the unauthenticated landing page; returns current user count
    and configured total limit (if any) so the UI can show remaining slots.
    """

    require_auth = False
    landing_enabled = False

    try:
        settings = flask.current_app.config.get("AUTH_SETTINGS")
        require_auth = bool(settings and settings.require_auth)
    except Exception:  # pragma: no cover - defensive
        require_auth = False

    try:
        landing_enabled = bool(getattr(config, "enable_public_landing_page", False))
    except Exception:  # pragma: no cover - defensive
        landing_enabled = False

    try:
        user_count = int(User.query.count())
    except Exception:  # pragma: no cover - defensive
        user_count = 0

    limit_raw = getattr(config, "user_limit_total", None)
    try:
        user_limit_total = int(limit_raw) if limit_raw is not None else None
    except Exception:  # pragma: no cover - defensive
        user_limit_total = None

    slots_remaining = None
    if user_limit_total is not None:
        slots_remaining = max(user_limit_total - user_count, 0)

    return flask.jsonify(
        {
            "require_auth": require_auth,
            "landing_page_enabled": landing_enabled,
            "user_count": user_count,
            "user_limit_total": user_limit_total,
            "slots_remaining": slots_remaining,
        }
    )


@main_bp.route("/<path:path>")
def catch_all(path: str) -> flask.Response:
    """Serve React app for all frontend routes, or serve static files."""
    # Don't handle API routes - let them be handled by API blueprint
    if path.startswith("api/"):
        flask.abort(404)

    static_folder = flask.current_app.static_folder
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
    _, error_response = require_admin("toggle whitelist for all posts")
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
