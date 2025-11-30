import datetime
import logging
import uuid
from email.utils import format_datetime, parsedate_to_datetime
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser  # type: ignore[import-untyped]
import PyRSS2Gen  # type: ignore[import-untyped]
from flask import current_app, g, request

from app.db_concurrency import commit_with_profile
from app.extensions import db
from app.models import Feed, Post, ProcessingJob
from app.runtime_config import config
from podcast_processor.podcast_downloader import find_audio_link
from podcast_processor.processing_status_manager import ProcessingStatusManager

logger = logging.getLogger("global_logger")


def _get_base_url() -> str:
    try:
        # Check various ways HTTP/2 pseudo-headers might be available
        http2_scheme = (
            request.headers.get(":scheme")
            or request.headers.get("scheme")
            or request.environ.get("HTTP2_SCHEME")
        )
        http2_authority = (
            request.headers.get(":authority")
            or request.headers.get("authority")
            or request.environ.get("HTTP2_AUTHORITY")
        )
        host = request.headers.get("Host")

        if http2_scheme and http2_authority:
            return f"{http2_scheme}://{http2_authority}"

        # Fall back to Host header with scheme detection
        if host:
            # Check multiple indicators for HTTPS
            is_https = (
                request.is_secure
                or request.headers.get("X-Forwarded-Proto") == "https"
                or request.headers.get("Strict-Transport-Security") is not None
                or request.headers.get("X-Forwarded-Ssl") == "on"
                or request.environ.get("HTTPS") == "on"
                or request.scheme == "https"
            )
            scheme = "https" if is_https else "http"
            return f"{scheme}://{host}"
    except RuntimeError:
        # Working outside of request context
        pass

    # Use localhost with main app port
    return "http://localhost:5001"


def fetch_feed(url: str) -> feedparser.FeedParserDict:
    logger.info(f"Fetching feed from URL: {url}")
    feed_data = feedparser.parse(url)
    for entry in feed_data.entries:
        entry.id = get_guid(entry)
    return feed_data


def refresh_feed(feed: Feed) -> None:
    logger.info(f"Refreshing feed with ID: {feed.id}")
    feed_data = fetch_feed(feed.rss_url)
    status_manager = ProcessingStatusManager(db_session=db.session, logger=logger)

    image_info = feed_data.feed.get("image")
    if image_info and "href" in image_info:
        new_image_url = image_info["href"]
        if feed.image_url != new_image_url:
            feed.image_url = new_image_url
            db.session.add(feed)

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
                and p.release_date
                and oldest_post.release_date
                and p.release_date.date() < oldest_post.release_date.date()
            ):
                p.whitelisted = False
                logger.debug(
                    f"skipping post from archive due to \
number_of_episodes_to_whitelist_from_archive_of_new_feed setting: {entry.title}"
                )
            else:
                p.whitelisted = config.automatically_whitelist_new_episodes
            _ensure_job_for_post_guid(p.guid, status_manager)
            db.session.add(p)
    commit_with_profile(
        db.session,
        must_succeed=True,
        context="refresh_feed",
        logger_obj=logger,
    )

    for post in feed.posts:  # type: ignore[attr-defined]
        _ensure_job_for_post_guid(post.guid, status_manager)
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
            image_url=feed_data.feed.image.href,
        )
        db.session.add(feed)
        commit_with_profile(
            db.session,
            must_succeed=True,
            context="add_feed_initial",
            logger_obj=logger,
        )

        status_manager = ProcessingStatusManager(db_session=db.session, logger=logger)
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
            _ensure_job_for_post_guid(p.guid, status_manager)
        commit_with_profile(
            db.session,
            must_succeed=True,
            context="add_feed_posts",
            logger_obj=logger,
        )
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

    base_url = _get_base_url()

    # Generate URLs that will be proxied by the frontend to the backend
    audio_url = _append_feed_token_params(f"{base_url}/api/posts/{post.guid}/download")
    post_details_url = _append_feed_token_params(f"{base_url}/api/posts/{post.guid}")

    description = (
        f'{post.description}\n<p><a href="{post_details_url}">Podly Post Page</a></p>'
    )

    item = PyRSS2Gen.RSSItem(
        title=post.title,
        enclosure=PyRSS2Gen.Enclosure(
            url=audio_url,
            type="audio/mpeg",
            length=post.audio_len_bytes(),
        ),
        description=description,
        guid=post.guid,
        pubDate=_format_pub_date(post.release_date),
    )

    return item


def generate_feed_xml(feed: Feed) -> Any:
    logger.info(f"Generating XML for feed with ID: {feed.id}")
    items = [feed_item(post) for post in feed.posts]  # type: ignore[attr-defined]

    base_url = _get_base_url()
    link = _append_feed_token_params(f"{base_url}/feed/{feed.id}")

    last_build_date = format_datetime(datetime.datetime.now(datetime.timezone.utc))

    rss_feed = PyRSS2Gen.RSS2(
        title="[podly] " + feed.title,
        link=link,
        description=feed.description,
        lastBuildDate=last_build_date,
        image=PyRSS2Gen.Image(url=feed.image_url, title=feed.title, link=link),
        items=items,
    )
    logger.info(f"XML generated for feed with ID: {feed.id}")
    return rss_feed.to_xml("utf-8")


def _append_feed_token_params(url: str) -> str:
    if not current_app.config.get("REQUIRE_AUTH"):
        return url

    try:
        token_result = getattr(g, "feed_token", None)
        token_id = request.args.get("feed_token")
        secret = request.args.get("feed_secret")
    except RuntimeError:
        return url

    if token_result is not None:
        token_id = token_id or token_result.token.token_id
        secret = secret or token_result.token.token_secret

    if not token_id or not secret:
        return url

    parsed = urlparse(url)
    query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query_params["feed_token"] = token_id
    query_params["feed_secret"] = secret
    new_query = urlencode(query_params)
    return urlunparse(parsed._replace(query=new_query))


def make_post(feed: Feed, entry: feedparser.FeedParserDict) -> Post:
    # Extract episode image URL, fallback to feed image
    episode_image_url = None

    # Try to get episode-specific image from various RSS fields
    if hasattr(entry, "image") and entry.image:
        if isinstance(entry.image, dict) and "href" in entry.image:
            episode_image_url = entry.image["href"]
        elif isinstance(entry.image, str):
            episode_image_url = entry.image

    # Try iTunes image tag
    if not episode_image_url and hasattr(entry, "itunes_image"):
        if isinstance(entry.itunes_image, dict) and "href" in entry.itunes_image:
            episode_image_url = entry.itunes_image["href"]
        elif isinstance(entry.itunes_image, str):
            episode_image_url = entry.itunes_image

    # Try media:thumbnail or media:content
    if not episode_image_url and hasattr(entry, "media_thumbnail"):
        if entry.media_thumbnail and len(entry.media_thumbnail) > 0:
            episode_image_url = entry.media_thumbnail[0].get("url")

    # Fallback to feed image if no episode-specific image found
    if not episode_image_url:
        episode_image_url = feed.image_url

    return Post(
        feed_id=feed.id,
        guid=get_guid(entry),
        download_url=find_audio_link(entry),
        title=entry.title,
        description=entry.get("description", ""),
        release_date=_parse_release_date(entry),
        duration=get_duration(entry),
        image_url=episode_image_url,
    )


def _get_entry_field(entry: feedparser.FeedParserDict, field: str) -> Optional[Any]:
    value = getattr(entry, field, None)
    return value if value is not None else entry.get(field)


def _parse_datetime_string(
    value: Optional[str], field: str
) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        logger.debug("Failed to parse %s string for release date", field)
        return None


def _parse_struct_time(value: Optional[Any], field: str) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        dt = datetime.datetime(*value[:6])
    except (TypeError, ValueError):
        logger.debug("Failed to parse %s for release date", field)
        return None
    gmtoff = getattr(value, "tm_gmtoff", None)
    if gmtoff is not None:
        dt = dt.replace(tzinfo=datetime.timezone(datetime.timedelta(seconds=gmtoff)))
    return dt


def _normalize_to_utc(dt: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def _parse_release_date(
    entry: feedparser.FeedParserDict,
) -> Optional[datetime.datetime]:
    """Parse a release datetime from a feed entry and normalize to UTC."""
    for field in ("published", "updated"):
        dt = _parse_datetime_string(_get_entry_field(entry, field), field)
        normalized = _normalize_to_utc(dt)
        if normalized:
            return normalized

    for field in ("published_parsed", "updated_parsed"):
        dt = _parse_struct_time(_get_entry_field(entry, field), field)
        normalized = _normalize_to_utc(dt)
        if normalized:
            return normalized

    return None


def _format_pub_date(release_date: Optional[datetime.datetime]) -> Optional[str]:
    if not release_date:
        return None

    normalized = release_date
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=datetime.timezone.utc)

    return format_datetime(normalized.astimezone(datetime.timezone.utc))


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


def _ensure_job_for_post_guid(
    post_guid: str, status_manager: ProcessingStatusManager
) -> None:
    """Ensure there's a ProcessingJob record for the provided post GUID."""
    post = Post.query.filter_by(guid=post_guid).first()
    if not post or not post.whitelisted:
        return
    existing_job = (
        ProcessingJob.query.filter_by(post_guid=post_guid)
        .order_by(ProcessingJob.created_at.desc())
        .first()
    )
    if existing_job:
        return
    job_id = status_manager.generate_job_id()
    status_manager.create_job(post_guid, job_id)
