import flask
from flask import Blueprint

from app import config, db, logger
from app.models import Feed, Post

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index() -> flask.Response:
    feeds = Feed.query.all()

    return flask.make_response(
        flask.render_template("index.html", feeds=feeds, config=config), 200
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
