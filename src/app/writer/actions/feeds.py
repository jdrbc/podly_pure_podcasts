import hashlib
import secrets
import uuid
from datetime import datetime
from typing import Any, Dict

from sqlalchemy import func

from app.extensions import db
from app.jobs_manager_run_service import recalculate_run_counts
from app.models import (
    Feed,
    FeedAccessToken,
    Identification,
    ModelCall,
    Post,
    ProcessingJob,
    TranscriptSegment,
    UserFeed,
)


def refresh_feed_action(params: Dict[str, Any]) -> Dict[str, Any]:
    feed_id = params.get("feed_id")
    updates = params.get("updates", {})
    new_posts_data = params.get("new_posts", [])

    feed = db.session.get(Feed, feed_id)
    if not feed:
        raise ValueError(f"Feed {feed_id} not found")

    for k, v in updates.items():
        setattr(feed, k, v)

    created_posts = []
    for post_data in new_posts_data:
        # Handle datetime deserialization
        if "release_date" in post_data and isinstance(post_data["release_date"], str):
            post_data["release_date"] = datetime.fromisoformat(
                post_data["release_date"]
            )

        post = Post(**post_data)
        db.session.add(post)
        created_posts.append(post)

    db.session.flush()

    for post in created_posts:
        if post.whitelisted:
            job = ProcessingJob(
                id=str(uuid.uuid4()),
                post_guid=post.guid,
                status="pending",
                current_step=0,
                total_steps=4,
                progress_percentage=0.0,
                created_at=datetime.utcnow(),
            )
            db.session.add(job)

    recalculate_run_counts(db.session)

    return {"feed_id": feed.id, "new_posts_count": len(created_posts)}


def add_feed_action(params: Dict[str, Any]) -> Dict[str, Any]:
    feed_data = params.get("feed")
    if not isinstance(feed_data, dict):
        raise ValueError("feed data must be a dictionary")
    posts_data = params.get("posts", [])

    feed = Feed(**feed_data)
    db.session.add(feed)
    db.session.flush()

    created_posts = []
    for post_data in posts_data:
        post_data["feed_id"] = feed.id
        if "release_date" in post_data and isinstance(post_data["release_date"], str):
            post_data["release_date"] = datetime.fromisoformat(
                post_data["release_date"]
            )

        post = Post(**post_data)
        db.session.add(post)
        created_posts.append(post)

    db.session.flush()

    for post in created_posts:
        if post.whitelisted:
            job = ProcessingJob(
                id=str(uuid.uuid4()),
                post_guid=post.guid,
                status="pending",
                current_step=0,
                total_steps=4,
                progress_percentage=0.0,
                created_at=datetime.utcnow(),
            )
            db.session.add(job)

    recalculate_run_counts(db.session)

    return {"feed_id": feed.id}


def increment_download_count_action(params: Dict[str, Any]) -> Dict[str, Any]:
    post_id = params.get("post_id")
    if not post_id:
        raise ValueError("post_id is required")

    updated = Post.query.filter_by(id=post_id).update(
        {Post.download_count: func.coalesce(Post.download_count, 0) + 1},
        synchronize_session=False,
    )

    return {"post_id": post_id, "updated": updated}


def ensure_user_feed_membership_action(params: Dict[str, Any]) -> Dict[str, Any]:
    feed_id = params.get("feed_id")
    user_id = params.get("user_id")
    if not feed_id or not user_id:
        raise ValueError("feed_id and user_id are required")

    feed_id_i = int(feed_id)
    user_id_i = int(user_id)

    previous_count = int(UserFeed.query.filter_by(feed_id=feed_id_i).count())
    existing = UserFeed.query.filter_by(feed_id=feed_id_i, user_id=user_id_i).first()
    if existing:
        return {"created": False, "previous_count": previous_count}

    db.session.add(UserFeed(feed_id=feed_id_i, user_id=user_id_i))
    db.session.flush()
    return {"created": True, "previous_count": previous_count}


def remove_user_feed_membership_action(params: Dict[str, Any]) -> Dict[str, Any]:
    feed_id = params.get("feed_id")
    user_id = params.get("user_id")
    if not feed_id or not user_id:
        raise ValueError("feed_id and user_id are required")

    removed = UserFeed.query.filter_by(
        feed_id=int(feed_id), user_id=int(user_id)
    ).delete(synchronize_session=False)
    return {"removed": int(removed)}


def whitelist_latest_post_for_feed_action(params: Dict[str, Any]) -> Dict[str, Any]:
    feed_id = params.get("feed_id")
    if not feed_id:
        raise ValueError("feed_id is required")

    latest = (
        Post.query.filter_by(feed_id=int(feed_id))
        .order_by(Post.release_date.desc().nullslast(), Post.id.desc())
        .first()
    )
    if not latest:
        return {"updated": False}
    if latest.whitelisted:
        return {"updated": False, "post_guid": latest.guid}

    latest.whitelisted = True
    db.session.flush()
    return {"updated": True, "post_guid": latest.guid}


def toggle_whitelist_all_for_feed_action(params: Dict[str, Any]) -> Dict[str, Any]:
    feed_id = params.get("feed_id")
    new_status = params.get("new_status")
    if feed_id is None or new_status is None:
        raise ValueError("feed_id and new_status are required")

    updated = Post.query.filter_by(feed_id=int(feed_id)).update(
        {Post.whitelisted: bool(new_status)},
        synchronize_session=False,
    )
    return {"feed_id": int(feed_id), "updated_count": int(updated)}


def create_dev_test_feed_action(params: Dict[str, Any]) -> Dict[str, Any]:
    rss_url = params.get("rss_url")
    title = params.get("title")
    if not rss_url or not title:
        raise ValueError("rss_url and title are required")

    existing = Feed.query.filter_by(rss_url=rss_url).first()
    if existing:
        return {"feed_id": existing.id, "created": False}

    feed = Feed(
        title=title,
        rss_url=rss_url,
        image_url=params.get("image_url"),
        description=params.get("description"),
        author=params.get("author"),
    )
    db.session.add(feed)
    db.session.flush()

    now = datetime.utcnow()
    post_count = int(params.get("post_count") or 5)
    for i in range(1, post_count + 1):
        guid = f"{params.get('guid_prefix') or 'test-guid'}-{feed.id}-{i}"
        post = Post(
            feed_id=feed.id,
            guid=guid,
            title=f"Test Episode {i}",
            download_url=f"{params.get('download_url_prefix') or 'http://test-feed'}/{feed.id}/{i}.mp3",
            release_date=now,
            duration=3600,
            description=f"Test episode description {i}",
            whitelisted=True,
        )
        db.session.add(post)
        db.session.flush()

        job = ProcessingJob(
            post_guid=post.guid,
            status="completed",
            current_step=4,
            total_steps=4,
            progress_percentage=100.0,
            started_at=now,
            completed_at=now,
            step_name="completed",
        )
        db.session.add(job)

    return {"feed_id": feed.id, "created": True}


def delete_feed_cascade_action(params: Dict[str, Any]) -> Dict[str, Any]:
    feed_id = params.get("feed_id")
    if not feed_id:
        raise ValueError("feed_id is required")

    feed_id_i = int(feed_id)
    feed = db.session.get(Feed, feed_id_i)
    if not feed:
        return {"deleted": False}

    post_rows = db.session.query(Post.id, Post.guid).filter_by(feed_id=feed_id_i).all()
    post_ids = [row[0] for row in post_rows]
    post_guids = [row[1] for row in post_rows]

    batch_size = 200
    if post_ids:
        while True:
            seg_ids = [
                seg_id
                for (seg_id,) in db.session.query(TranscriptSegment.id)
                .filter(TranscriptSegment.post_id.in_(post_ids))
                .limit(batch_size)
                .all()
            ]
            if not seg_ids:
                break
            db.session.query(Identification).filter(
                Identification.transcript_segment_id.in_(seg_ids)
            ).delete(synchronize_session=False)
            db.session.query(TranscriptSegment).filter(
                TranscriptSegment.id.in_(seg_ids)
            ).delete(synchronize_session=False)

        while True:
            mc_ids = [
                mc_id
                for (mc_id,) in db.session.query(ModelCall.id)
                .filter(ModelCall.post_id.in_(post_ids))
                .limit(batch_size)
                .all()
            ]
            if not mc_ids:
                break
            db.session.query(ModelCall).filter(ModelCall.id.in_(mc_ids)).delete(
                synchronize_session=False
            )

        while True:
            job_ids = [
                job_id
                for (job_id,) in db.session.query(ProcessingJob.id)
                .filter(ProcessingJob.post_guid.in_(post_guids))
                .limit(batch_size)
                .all()
            ]
            if not job_ids:
                break
            db.session.query(ProcessingJob).filter(
                ProcessingJob.id.in_(job_ids)
            ).delete(synchronize_session=False)

        db.session.query(Post).filter(Post.id.in_(post_ids)).delete(
            synchronize_session=False
        )

    FeedAccessToken.query.filter(FeedAccessToken.feed_id == feed_id_i).delete(
        synchronize_session=False
    )
    UserFeed.query.filter(UserFeed.feed_id == feed_id_i).delete(
        synchronize_session=False
    )
    db.session.delete(feed)
    return {"deleted": True, "feed_id": feed_id_i}


def _hash_token(secret_value: str) -> str:
    return hashlib.sha256(secret_value.encode("utf-8")).hexdigest()


def create_feed_access_token_action(params: Dict[str, Any]) -> Dict[str, Any]:
    user_id = params.get("user_id")
    feed_id = params.get("feed_id")

    if not user_id:
        raise ValueError("user_id is required")

    # feed_id can be None for aggregate tokens

    query = FeedAccessToken.query.filter_by(user_id=int(user_id), revoked=False)

    if feed_id is not None:
        query = query.filter_by(feed_id=int(feed_id))
    else:
        query = query.filter(FeedAccessToken.feed_id.is_(None))

    existing = query.first()

    if existing is not None:
        if existing.token_secret:
            return {"token_id": existing.token_id, "secret": existing.token_secret}

        secret_value = secrets.token_urlsafe(18)
        existing.token_hash = _hash_token(secret_value)
        existing.token_secret = secret_value
        db.session.flush()
        return {"token_id": existing.token_id, "secret": secret_value}

    token_id = uuid.uuid4().hex
    secret_value = secrets.token_urlsafe(18)
    token = FeedAccessToken(
        token_id=token_id,
        token_hash=_hash_token(secret_value),
        token_secret=secret_value,
        feed_id=int(feed_id) if feed_id is not None else None,
        user_id=int(user_id),
    )
    db.session.add(token)
    db.session.flush()
    return {"token_id": token_id, "secret": secret_value}


def touch_feed_access_token_action(params: Dict[str, Any]) -> Dict[str, Any]:
    token_id = params.get("token_id")
    secret_value = params.get("secret")
    if not token_id:
        raise ValueError("token_id is required")

    token = FeedAccessToken.query.filter_by(token_id=token_id, revoked=False).first()
    if token is None:
        return {"updated": False}

    token.last_used_at = datetime.utcnow()
    if token.token_secret is None and secret_value:
        token.token_secret = str(secret_value)
    db.session.flush()
    return {"updated": True}
