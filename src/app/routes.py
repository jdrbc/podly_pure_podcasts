import datetime
import logging

import feedparser  # type: ignore[import-untyped]
import flask
import PyRSS2Gen  # type: ignore[import-untyped]
from flask import Blueprint, jsonify, request, url_for

from app import db
from app.models import Feed, Post

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

main_bp = Blueprint("main", __name__)


def fetch_feed(url: str) -> feedparser.FeedParserDict:
    logger.info(f"Fetching feed from URL: {url}")
    return feedparser.parse(url)


def store_feed(feed_data: feedparser.FeedParserDict) -> Feed:
    logger.info(f"Storing feed: {feed_data.feed.title}")
    feed = Feed(
        title=feed_data.feed.title,
        description=feed_data.feed.get("description", ""),
        author=feed_data.feed.get("author", ""),
        rss_url=feed_data.href,
    )
    db.session.add(feed)
    db.session.commit()

    for entry in feed_data.entries:
        post = Post(
            feed_id=feed.id,
            download_url=entry.link,
            title=entry.title,
            description=entry.get("description", ""),
            release_date=(
                datetime.datetime(*entry.published_parsed[:6])
                if entry.get("published_parsed")
                else None
            ),
            duration=int(entry.get("itunes_duration", 0)),
        )
        db.session.add(post)
    db.session.commit()
    logger.info(f"Feed stored with ID: {feed.id}")
    return feed


def refresh_feed(feed: Feed) -> None:
    logger.info(f"Refreshing feed with ID: {feed.id}")
    feed_data = fetch_feed(feed.rss_url)
    existing_posts = {post.download_url for post in feed.posts}  # type: ignore[attr-defined]
    for entry in feed_data.entries:
        if entry.link not in existing_posts:
            post = Post(
                feed_id=feed.id,
                download_url=entry.link,
                title=entry.title,
                description=entry.get("description", ""),
                release_date=(
                    datetime.datetime(*entry.published_parsed[:6])
                    if entry.get("published_parsed")
                    else None
                ),
                duration=int(entry.get("itunes_duration", 0)),
            )
            db.session.add(post)
    db.session.commit()
    logger.info(f"Feed with ID: {feed.id} refreshed")


def generate_feed_xml(feed: Feed) -> str:
    logger.info(f"Generating XML for feed with ID: {feed.id}")
    items = []
    for post in feed.posts:  # type: ignore[attr-defined]
        items.append(
            PyRSS2Gen.RSSItem(
                title=post.title,
                link=post.download_url,
                description=post.description,
                guid=PyRSS2Gen.Guid(post.download_url),
                pubDate=(
                    post.release_date.strftime("%a, %d %b %Y %H:%M:%S %z")
                    if post.release_date
                    else None
                ),
            )
        )
    rss_feed = PyRSS2Gen.RSS2(
        title=feed.title,
        link=url_for("main.get_feed", id=feed.id, _external=True),
        description=feed.description,
        lastBuildDate=datetime.datetime.now(),
        items=items,
    )
    logger.info(f"XML generated for feed with ID: {feed.id}")
    return str(rss_feed.to_xml("utf-8"), "utf-8")


@main_bp.route("/v1/feed", methods=["POST"])
def add_feed() -> flask.Response:
    data = request.get_json()
    if not data or "url" not in data:
        logger.error("URL is required")
        return flask.make_response(jsonify({"error": "URL is required"}), 400)

    url = data["url"]
    feed_data = fetch_feed(url)
    if "title" not in feed_data.feed:
        logger.error("Invalid feed URL")
        return flask.make_response(jsonify({"error": "Invalid feed URL"}), 400)

    feed = Feed.query.filter_by(rss_url=url).first()
    if feed:
        refresh_feed(feed)
    else:
        feed = store_feed(feed_data)

    logger.info(f"Feed added with ID: {feed.id}")
    return flask.make_response(jsonify({"id": feed.id, "title": feed.title}), 201)


@main_bp.route("/v1/feed/<int:e_id>", methods=["GET"])
def get_feed(e_id: int) -> flask.Response:
    logger.info(f"Fetching feed with ID: {e_id}")
    feed = Feed.query.get_or_404(e_id)
    refresh_feed(feed)
    feed_xml = generate_feed_xml(feed)
    logger.info(f"Feed with ID: {e_id} fetched and XML generated")
    return flask.make_response(feed_xml, 200, {"Content-Type": "application/xml"})
