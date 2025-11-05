from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.auth.service import AuthenticatedUser
from app.extensions import db
from app.models import Feed, FeedAccessToken, Post, User


@dataclass(slots=True)
class FeedTokenAuthResult:
    user: AuthenticatedUser
    feed_id: int
    token: FeedAccessToken


def _hash_token(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def create_feed_access_token(user: User, feed: Feed) -> tuple[str, str]:
    token_id = uuid.uuid4().hex
    secret = secrets.token_urlsafe(18)
    token = FeedAccessToken(
        token_id=token_id,
        token_hash=_hash_token(secret),
        feed_id=feed.id,
        user_id=user.id,
    )
    db.session.add(token)
    db.session.commit()

    return f"feed-{token_id}", secret


def authenticate_feed_token(
    username: str, secret: str, path: str
) -> Optional[FeedTokenAuthResult]:
    if not username.startswith("feed-"):
        return None

    token_id = username[len("feed-") :]
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

    user = User.query.get(token.user_id)
    if user is None:
        return None

    token.last_used_at = datetime.utcnow()
    db.session.add(token)
    # Defer commit to request teardown

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
