import datetime
import uuid
from typing import Any, Optional

import feedparser  # type: ignore[import-untyped]
import PyRSS2Gen  # type: ignore[import-untyped]
from flask import url_for

from app import config, db, logger
from app.models import Feed, Post
from shared.podcast_downloader import find_audio_link


def fetch_feed(url: str) -> feedparser.FeedParserDict:
    logger.info(f"Fetching feed from URL: {url}")
    feed_data = feedparser.parse(url)
    for entry in feed_data.entries:
        entry.id = get_guid(entry)
    return feed_data


def refresh_feed(feed: Feed) -> None:
    logger.info(f"Refreshing feed with ID: {feed.id}")
    feed_data = fetch_feed(feed.rss_url)
    existing_posts = {post.guid for post in feed.posts}  # type: ignore[attr-defined]
    oldest_post = min(
        (post for post in feed.posts if post.release_date),  # type: ignore[attr-defined]
        key=lambda p: p.release_date,
        default=None,
    )
    for entry in feed_data.entries:
        if entry.id not in existing_posts:
            logger.debug(f"found new podcast: {entry.title}")
            p = make_post(feed, entry)
            # do not allow automatic download of any backcatalog added to the feed
            if (
                oldest_post is not None
                and p.release_date.date() < oldest_post.release_date
            ):
                p.whitelisted = False
                logger.debug(
                    f"skipping post from archive due to \
number_of_episodes_to_whitelist_from_archive_of_new_feed setting: {entry.title}"
                )
            else:
                p.whitelisted = config.automatically_whitelist_new_episodes
            db.session.add(p)
    db.session.commit()
    logger.info(f"Feed with ID: {feed.id} refreshed")


def add_or_refresh_feed(url: str) -> Feed:
    feed_data = fetch_feed(url)
    if "title" not in feed_data.feed:
        logger.error("Invalid feed URL")
        raise ValueError(f"Invalid feed URL: {url}")

    feed = Feed.query.filter_by(rss_url=url).first()
    if feed:
        refresh_feed(feed)
    else:
        feed = add_feed(feed_data)
    return feed  # type: ignore[no-any-return]


def add_feed(feed_data: feedparser.FeedParserDict) -> Feed:
    logger.info(f"Storing feed: {feed_data.feed.title}")
    try:
        feed = Feed(
            title=feed_data.feed.title,
            description=feed_data.feed.get("description", ""),
            author=feed_data.feed.get("author", ""),
            rss_url=feed_data.href,
        )
        db.session.add(feed)
        db.session.commit()

        num_posts_added = 0
        for entry in feed_data.entries:
            p = make_post(feed, entry)
            if (
                config.number_of_episodes_to_whitelist_from_archive_of_new_feed
                is not None
                and num_posts_added
                >= config.number_of_episodes_to_whitelist_from_archive_of_new_feed
            ):
                logger.info(
                    f"Number of episodes to load from archive reached: {num_posts_added}"
                )
                p.whitelisted = False
            else:
                num_posts_added += 1
                p.whitelisted = config.automatically_whitelist_new_episodes
            db.session.add(p)
        db.session.commit()
        logger.info(f"Feed stored with ID: {feed.id}")
        return feed
    except Exception as e:
        logger.error(f"Failed to store feed: {e}")
        db.session.rollback()
        raise e


def feed_item(post: Post) -> PyRSS2Gen.RSSItem:
    """
    Given a post, return the corresponding RSS item. Reference:
    https://github.com/Podcast-Standards-Project/PSP-1-Podcast-RSS-Specification?tab=readme-ov-file#required-item-elements
    """

    audio_url = (config.server if config.server is not None else "") + url_for(
        "main.download_post",
        p_guid=post.guid,
        _external=config.server is None,
    )

    item = PyRSS2Gen.RSSItem(
        title=post.title,
        enclosure=PyRSS2Gen.Enclosure(
            url=audio_url,
            type="audio/mpeg",
            length=post.audio_len_bytes(),
        ),
        description=post.description,
        guid=post.guid,
        pubDate=(
            post.release_date.strftime("%a, %d %b %Y %H:%M:%S %z")
            if post.release_date
            else None
        ),
    )

    return item


def generate_feed_xml(feed: Feed) -> Any:
    logger.info(f"Generating XML for feed with ID: {feed.id}")
    items = [feed_item(post) for post in feed.posts]  # type: ignore[attr-defined]
    rss_feed = PyRSS2Gen.RSS2(
        title="[podly] " + feed.title,
        link=url_for("main.get_feed", f_id=feed.id, _external=True),
        description=feed.description,
        lastBuildDate=datetime.datetime.now(),
        items=items,
    )
    logger.info(f"XML generated for feed with ID: {feed.id}")
    return rss_feed.to_xml("utf-8")


def make_post(feed: Feed, entry: feedparser.FeedParserDict) -> Post:
    return Post(
        feed_id=feed.id,
        guid=get_guid(entry),
        download_url=find_audio_link(entry),
        title=entry.title,
        description=entry.get("description", ""),
        release_date=(
            datetime.datetime(*entry.published_parsed[:6])
            if entry.get("published_parsed")
            else None
        ),
        duration=get_duration(entry),
    )


# sometimes feed entry ids are the post url or something else
def get_guid(entry: feedparser.FeedParserDict) -> str:
    try:
        uuid.UUID(entry.id)
        return str(entry.id)
    except ValueError:
        dlurl = find_audio_link(entry)
        return str(uuid.uuid5(uuid.NAMESPACE_URL, dlurl))


def get_duration(entry: feedparser.FeedParserDict) -> Optional[int]:
    try:
        return int(entry["itunes_duration"])
    except Exception:  # pylint: disable=broad-except
        logger.error("Failed to get duration")
        return None
