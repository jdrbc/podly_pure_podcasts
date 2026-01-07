import datetime
import logging
import uuid
from email.utils import format_datetime, parsedate_to_datetime
from typing import Any, Iterable, Optional, cast
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser  # type: ignore[import-untyped]
import PyRSS2Gen  # type: ignore[import-untyped]
from flask import current_app, g, request

from app.extensions import db
from app.models import Feed, Post, User, UserFeed
from app.runtime_config import config
from app.writer.client import writer_client
from podcast_processor.podcast_downloader import find_audio_link

logger = logging.getLogger("global_logger")


def is_feed_active_for_user(feed_id: int, user: User) -> bool:
    """Check if the feed is within the user's allowance based on subscription date."""
    if user.role == "admin":
        return True

    # Hack: Always treat Feed 1 as active
    if feed_id == 1:
        return True

    # Use manual allowance if set, otherwise fall back to plan allowance
    manual_allowance = user.manual_feed_allowance
    if manual_allowance is not None:
        allowance = int(manual_allowance)
    else:
        allowance = int(getattr(user, "feed_allowance", 0))

    # Sort user's feeds by creation date to determine priority
    user_feeds = sorted(user.user_feeds, key=lambda uf: uf.created_at)

    for i, uf in enumerate(user_feeds):
        if uf.feed_id == feed_id:
            return i < allowance

    return False


def _should_auto_whitelist_new_posts(feed: Feed, post: Optional[Post] = None) -> bool:
    """Return True when new posts should default to whitelisted for this feed."""

    if not getattr(config, "automatically_whitelist_new_episodes", False):
        return False

    memberships = getattr(feed, "user_feeds", None) or []
    if not memberships:
        return False

    # Check if at least one member has this feed in their "active" list (within allowance)
    for membership in memberships:
        user = membership.user
        if not user:
            continue

        if is_feed_active_for_user(feed.id, user):
            return True

    return False


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

    updates = {}
    image_info = feed_data.feed.get("image")
    if image_info and "href" in image_info:
        new_image_url = image_info["href"]
        if feed.image_url != new_image_url:
            updates["image_url"] = new_image_url

    existing_posts = {post.guid for post in feed.posts}  # type: ignore[attr-defined]
    oldest_post = min(
        (post for post in feed.posts if post.release_date),  # type: ignore[attr-defined]
        key=lambda p: p.release_date,
        default=None,
    )

    new_posts = []
    for entry in feed_data.entries:
        if entry.id not in existing_posts:
            logger.debug("found new podcast: %s", entry.title)
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
                p.whitelisted = _should_auto_whitelist_new_posts(feed, p)

            post_data = {
                "guid": p.guid,
                "title": p.title,
                "description": p.description,
                "download_url": p.download_url,
                "release_date": p.release_date.isoformat() if p.release_date else None,
                "duration": p.duration,
                "image_url": p.image_url,
                "whitelisted": p.whitelisted,
                "feed_id": feed.id,
            }
            new_posts.append(post_data)

    if updates or new_posts:
        writer_client.action(
            "refresh_feed",
            {"feed_id": feed.id, "updates": updates, "new_posts": new_posts},
            wait=True,
        )

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
        feed_dict = {
            "title": feed_data.feed.title,
            "description": feed_data.feed.get("description", ""),
            "author": feed_data.feed.get("author", ""),
            "rss_url": feed_data.href,
            "image_url": feed_data.feed.image.href,
        }

        # Create a temporary feed object to use make_post helper
        temp_feed = Feed(**feed_dict)
        temp_feed.id = 0  # Dummy ID

        posts_data = []
        num_posts_added = 0
        for entry in feed_data.entries:
            p = make_post(temp_feed, entry)
            if (
                config.number_of_episodes_to_whitelist_from_archive_of_new_feed
                is not None
                and num_posts_added
                >= config.number_of_episodes_to_whitelist_from_archive_of_new_feed
            ):
                p.whitelisted = False
            else:
                num_posts_added += 1
                p.whitelisted = config.automatically_whitelist_new_episodes

            post_data = {
                "guid": p.guid,
                "title": p.title,
                "description": p.description,
                "download_url": p.download_url,
                "release_date": p.release_date.isoformat() if p.release_date else None,
                "duration": p.duration,
                "image_url": p.image_url,
                "whitelisted": p.whitelisted,
            }
            posts_data.append(post_data)

        result = writer_client.action(
            "add_feed", {"feed": feed_dict, "posts": posts_data}, wait=True
        )

        if result is None or result.data is None:
            raise RuntimeError("Failed to get result from writer action")

        feed_id = result.data["feed_id"]
        logger.info(f"Feed stored with ID: {feed_id}")

        # Return the feed object
        feed = db.session.get(Feed, feed_id)
        if feed is None:
            raise RuntimeError(f"Feed {feed_id} not found after creation")
        return feed

    except Exception as e:
        logger.error(f"Failed to store feed: {e}")
        raise e


class ItunesRSSItem(PyRSS2Gen.RSSItem):  # type: ignore[misc]
    def __init__(
        self,
        *,
        title: str,
        enclosure: PyRSS2Gen.Enclosure,
        description: str,
        guid: str,
        pubDate: Optional[str],
        image_url: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        self.image_url = image_url
        super().__init__(
            title=title,
            enclosure=enclosure,
            description=description,
            guid=guid,
            pubDate=pubDate,
            **kwargs,
        )

    def publish_extensions(self, handler: Any) -> None:
        if self.image_url:
            handler.startElement("itunes:image", {"href": self.image_url})
            handler.endElement("itunes:image")
        super().publish_extensions(handler)


def feed_item(post: Post, prepend_feed_title: bool = False) -> PyRSS2Gen.RSSItem:
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

    title = post.title
    if prepend_feed_title and post.feed:
        title = f"[{post.feed.title}] {title}"

    item = ItunesRSSItem(
        title=title,
        enclosure=PyRSS2Gen.Enclosure(
            url=audio_url,
            type="audio/mpeg",
            length=post.audio_len_bytes(),
        ),
        description=description,
        guid=post.guid,
        pubDate=_format_pub_date(post.release_date),
        image_url=post.image_url,
    )

    return item


def generate_feed_xml(feed: Feed) -> Any:
    logger.info(f"Generating XML for feed with ID: {feed.id}")

    include_unprocessed = getattr(config, "autoprocess_on_download", True)

    if include_unprocessed:
        posts = list(cast(Iterable[Post], feed.posts))
    else:
        posts = (
            Post.query.filter(
                Post.feed_id == feed.id,
                Post.whitelisted.is_(True),
                Post.processed_audio_path.isnot(None),
            )
            .order_by(Post.release_date.desc().nullslast(), Post.id.desc())
            .all()
        )

    items = [feed_item(post) for post in posts]

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

    rss_feed.rss_attrs["xmlns:itunes"] = "http://www.itunes.com/dtds/podcast-1.0.dtd"
    rss_feed.rss_attrs["xmlns:content"] = "http://purl.org/rss/1.0/modules/content/"

    logger.info(f"XML generated for feed with ID: {feed.id}")
    return rss_feed.to_xml("utf-8")


def generate_aggregate_feed_xml(user: User) -> Any:
    """Generate RSS XML for a user's aggregate feed (last 3 processed posts per feed)."""
    logger.info(f"Generating aggregate feed XML for user: {user.username}")

    posts = get_user_aggregate_posts(user.id)
    items = [feed_item(post, prepend_feed_title=True) for post in posts]

    base_url = _get_base_url()
    link = _append_feed_token_params(f"{base_url}/feed/user/{user.id}")

    last_build_date = format_datetime(datetime.datetime.now(datetime.timezone.utc))

    if current_app.config.get("REQUIRE_AUTH"):
        feed_title = f"Podly Podcasts - {user.username}"
        feed_description = f"Aggregate feed for {user.username} - Last 3 processed episodes from each subscribed feed."
    else:
        feed_title = "Podly Podcasts"
        feed_description = (
            "Aggregate feed - Last 3 processed episodes from each subscribed feed."
        )

    rss_feed = PyRSS2Gen.RSS2(
        title=feed_title,
        link=link,
        description=feed_description,
        lastBuildDate=last_build_date,
        items=items,
        image=PyRSS2Gen.Image(
            url=f"{base_url}/static/images/logos/manifest-icon-512.maskable.png",
            title=feed_title,
            link=link,
        ),
    )

    rss_feed.rss_attrs["xmlns:itunes"] = "http://www.itunes.com/dtds/podcast-1.0.dtd"
    rss_feed.rss_attrs["xmlns:content"] = "http://purl.org/rss/1.0/modules/content/"

    logger.info(f"Aggregate XML generated for user: {user.username}")
    return rss_feed.to_xml("utf-8")


def get_user_aggregate_posts(user_id: int, limit_per_feed: int = 3) -> list[Post]:
    """Fetch last N processed posts from each of the user's subscribed feeds."""
    if not current_app.config.get("REQUIRE_AUTH"):
        feed_ids = [r[0] for r in Feed.query.with_entities(Feed.id).all()]
    else:
        user_feeds = UserFeed.query.filter_by(user_id=user_id).all()
        feed_ids = [uf.feed_id for uf in user_feeds]

    all_posts = []
    for feed_id in feed_ids:
        # Fetch last N processed posts for this feed
        posts = (
            Post.query.filter(
                Post.feed_id == feed_id,
                Post.whitelisted.is_(True),
                Post.processed_audio_path.isnot(None),
            )
            .order_by(Post.release_date.desc().nullslast(), Post.id.desc())
            .limit(limit_per_feed)
            .all()
        )
        all_posts.extend(posts)

    # Sort all posts by release date descending
    all_posts.sort(key=lambda p: p.release_date or datetime.datetime.min, reverse=True)

    return all_posts


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

    # Try multiple description fields in order of preference
    description = entry.get("description", "")
    if not description:
        description = entry.get("summary", "")
    if not description and hasattr(entry, "content") and entry.content:
        description = entry.content[0].get("value", "")
    if not description:
        description = entry.get("subtitle", "")

    return Post(
        feed_id=feed.id,
        guid=get_guid(entry),
        download_url=find_audio_link(entry),
        title=entry.title,
        description=description,
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
        logger.error("Failed to get duration")
        return None
