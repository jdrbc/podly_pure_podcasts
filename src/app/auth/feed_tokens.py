from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.auth.service import AuthenticatedUser
from app.db_concurrency import commit_with_profile
from app.extensions import db
from app.models import Feed, FeedAccessToken, Post, User

logger = logging.getLogger("global_logger")


@dataclass(slots=True)
class FeedTokenAuthResult:
    user: AuthenticatedUser
    feed_id: int
    token: FeedAccessToken


def _hash_token(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def create_feed_access_token(user: User, feed: Feed) -> tuple[str, str]:
    existing = FeedAccessToken.query.filter_by(
        user_id=user.id, feed_id=feed.id, revoked=False
    ).first()
    if existing is not None:
        if existing.token_secret:
            return existing.token_id, existing.token_secret

        secret = secrets.token_urlsafe(18)
        existing.token_hash = _hash_token(secret)
        existing.token_secret = secret
        db.session.add(existing)
        commit_with_profile(
            db.session,
            must_succeed=True,
            context="update_feed_access_token",
            logger_obj=logger,
        )
        return existing.token_id, secret

    token_id = uuid.uuid4().hex
    secret = secrets.token_urlsafe(18)
    token = FeedAccessToken(
        token_id=token_id,
        token_hash=_hash_token(secret),
        token_secret=secret,
        feed_id=feed.id,
        user_id=user.id,
    )
    db.session.add(token)
    commit_with_profile(
        db.session,
        must_succeed=True,
        context="create_feed_access_token",
        logger_obj=logger,
    )

    return token_id, secret


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

    token.last_used_at = datetime.utcnow()
    if token.token_secret is None:
        token.token_secret = secret
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
