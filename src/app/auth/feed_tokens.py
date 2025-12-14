from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from typing import Optional

from app.auth.service import AuthenticatedUser
from app.extensions import db
from app.models import Feed, FeedAccessToken, Post, User, UserFeed
from app.writer.client import writer_client

logger = logging.getLogger("global_logger")


def _hash_token(secret_value: str) -> str:
    return hashlib.sha256(secret_value.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class FeedTokenAuthResult:
    user: AuthenticatedUser
    feed_id: int
    token: FeedAccessToken


def create_feed_access_token(user: User, feed: Feed) -> tuple[str, str]:
    result = writer_client.action(
        "create_feed_access_token",
        {"user_id": user.id, "feed_id": feed.id},
        wait=True,
    )
    if not result or not result.success or not isinstance(result.data, dict):
        raise RuntimeError(getattr(result, "error", "Failed to create feed token"))
    return str(result.data["token_id"]), str(result.data["secret"])


def authenticate_feed_token(
    token_id: str, secret: str, path: str
) -> Optional[FeedTokenAuthResult]:
    if not token_id:
        return None

    token = FeedAccessToken.query.filter_by(token_id=token_id, revoked=False).first()
    if token is None:
        return None

    expected_hash = _hash_token(secret)
    if not secrets.compare_digest(token.token_hash, expected_hash):
        return None

    feed_id = _resolve_feed_id(path)
    if feed_id is None or feed_id != token.feed_id:
        return None

    user = db.session.get(User, token.user_id)
    if user is None:
        return None

    # Verify active subscription
    if user.role != "admin":
        # Hack: Always allow Feed 1
        if token.feed_id == 1:
            pass
        else:
            membership = UserFeed.query.filter_by(
                user_id=user.id, feed_id=token.feed_id
            ).first()
            if not membership:
                logger.warning(
                    "Access denied: User %s has valid token but no active subscription for feed %s",
                    user.id,
                    token.feed_id,
                )
                return None

    try:
        writer_client.action(
            "touch_feed_access_token",
            {"token_id": token_id, "secret": secret},
            wait=False,
        )
    except Exception:  # pylint: disable=broad-except
        pass

    return FeedTokenAuthResult(
        user=AuthenticatedUser(id=user.id, username=user.username, role=user.role),
        feed_id=token.feed_id,
        token=token,
    )


def _resolve_feed_id(path: str) -> Optional[int]:
    if path.startswith("/feed/"):
        remainder = path[len("/feed/") :]
        try:
            return int(remainder.split("/", 1)[0])
        except ValueError:
            return None

    if path.startswith("/api/posts/"):
        parts = path.split("/")
        if len(parts) < 4:
            return None
        guid = parts[3]
        post = Post.query.filter_by(guid=guid).first()
        return post.feed_id if post else None

    if path.startswith("/post/"):
        remainder = path[len("/post/") :]
        guid = remainder.split("/", 1)[0]
        guid = guid.split(".", 1)[0]
        post = Post.query.filter_by(guid=guid).first()
        return post.feed_id if post else None

    return None
