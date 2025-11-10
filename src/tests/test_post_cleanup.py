from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from app.extensions import db
from app.models import (
    Feed,
    Identification,
    ModelCall,
    Post,
    ProcessingJob,
    TranscriptSegment,
)
from app.post_cleanup import cleanup_processed_posts, count_cleanup_candidates


def _create_feed() -> Feed:
    feed = Feed(
        title="Test Feed",
        description="desc",
        author="author",
        rss_url="https://example.com/feed.xml",
        image_url="https://example.com/image.png",
    )
    db.session.add(feed)
    db.session.commit()
    return feed


def _create_post(feed: Feed, guid: str, download_url: str) -> Post:
    post = Post(
        feed_id=feed.id,
        guid=guid,
        download_url=download_url,
        title=f"Episode {guid}",
        description="test",
        whitelisted=True,
    )
    db.session.add(post)
    db.session.commit()
    return post


def test_cleanup_removes_expired_posts(app, tmp_path) -> None:
    with app.app_context():
        feed = _create_feed()

        old_post = _create_post(feed, "old-guid", "https://example.com/old.mp3")
        recent_post = _create_post(
            feed, "recent-guid", "https://example.com/recent.mp3"
        )

        old_processed = Path(tmp_path) / "old_processed.mp3"
        old_unprocessed = Path(tmp_path) / "old_unprocessed.mp3"
        old_processed.write_text("processed")
        old_unprocessed.write_text("unprocessed")
        old_post.processed_audio_path = str(old_processed)
        old_post.unprocessed_audio_path = str(old_unprocessed)
        db.session.commit()

        completed_at = datetime.utcnow() - timedelta(days=10)
        db.session.add(
            ProcessingJob(
                id="job-old",
                post_guid=old_post.guid,
                status="completed",
                current_step=4,
                total_steps=4,
                progress_percentage=100.0,
                created_at=completed_at,
                started_at=completed_at,
                completed_at=completed_at,
            )
        )

        recent_completed = datetime.utcnow() - timedelta(days=2)
        db.session.add(
            ProcessingJob(
                id="job-recent",
                post_guid=recent_post.guid,
                status="completed",
                current_step=4,
                total_steps=4,
                progress_percentage=100.0,
                created_at=recent_completed,
                started_at=recent_completed,
                completed_at=recent_completed,
            )
        )

        # Populate related tables for the old post to ensure cascading deletes
        model_call = ModelCall(
            post_id=old_post.id,
            first_segment_sequence_num=0,
            last_segment_sequence_num=0,
            model_name="test",
            prompt="prompt",
            response="resp",
            status="completed",
            timestamp=completed_at,
        )
        db.session.add(model_call)
        segment = TranscriptSegment(
            post_id=old_post.id,
            sequence_num=0,
            start_time=0.0,
            end_time=1.0,
            text="segment",
        )
        db.session.add(segment)
        db.session.flush()
        db.session.add(
            Identification(
                transcript_segment_id=segment.id,
                model_call_id=model_call.id,
                confidence=0.5,
                label="ad",
            )
        )

        db.session.commit()

        removed = cleanup_processed_posts(retention_days=5)

        assert removed == 1
        assert Post.query.filter_by(guid="old-guid").first() is None
        assert Post.query.filter_by(guid="recent-guid").first() is not None
        assert ProcessingJob.query.filter_by(post_guid="old-guid").first() is None
        assert Identification.query.count() == 0
        assert TranscriptSegment.query.count() == 0
        assert ModelCall.query.count() == 0
        assert not old_processed.exists()
        assert not old_unprocessed.exists()


def test_cleanup_skips_when_retention_disabled(app) -> None:
    with app.app_context():
        feed = _create_feed()
        post = _create_post(feed, "guid", "https://example.com/audio.mp3")
        completed_at = datetime.utcnow() - timedelta(days=10)
        db.session.add(
            ProcessingJob(
                id="job-disable",
                post_guid=post.guid,
                status="completed",
                current_step=4,
                total_steps=4,
                progress_percentage=100.0,
                created_at=completed_at,
                started_at=completed_at,
                completed_at=completed_at,
            )
        )
        db.session.commit()

        removed = cleanup_processed_posts(retention_days=None)
        assert removed == 0
        assert Post.query.filter_by(guid="guid").first() is not None


def test_cleanup_includes_non_whitelisted_processed_posts(app, tmp_path) -> None:
    with app.app_context():
        feed = _create_feed()
        post = _create_post(feed, "non-white", "https://example.com/nonwhite.mp3")
        post.whitelisted = False
        post.release_date = datetime.utcnow() - timedelta(days=10)
        processed = tmp_path / "processed.mp3"
        processed.write_text("audio")
        post.processed_audio_path = str(processed)
        db.session.commit()

        count, _ = count_cleanup_candidates(retention_days=5)
        assert count == 1

        removed = cleanup_processed_posts(retention_days=5)
        assert removed == 1
        assert Post.query.filter_by(guid="non-white").first() is None


def test_cleanup_skips_unprocessed_unwhitelisted_posts(app) -> None:
    with app.app_context():
        feed = _create_feed()
        post = _create_post(feed, "non-white-2", "https://example.com/nonwhite2.mp3")
        post.whitelisted = False
        post.release_date = datetime.utcnow() - timedelta(days=10)
        db.session.commit()

        count, _ = count_cleanup_candidates(retention_days=5)
        assert count == 0

        removed = cleanup_processed_posts(retention_days=5)
        assert removed == 0
        assert Post.query.filter_by(guid="non-white-2").first() is not None
