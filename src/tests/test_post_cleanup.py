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

        # Give recent post processed audio too so it's in the candidate list
        recent_processed = Path(tmp_path) / "recent_processed.mp3"
        recent_processed.write_text("processed")
        recent_post.processed_audio_path = str(recent_processed)

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
        cleaned_old_post = Post.query.filter_by(guid="old-guid").first()
        assert cleaned_old_post is not None
        assert cleaned_old_post.whitelisted is False
        assert cleaned_old_post.processed_audio_path is None
        assert cleaned_old_post.unprocessed_audio_path is None
        assert Post.query.filter_by(guid="recent-guid").first() is not None
        # Processing metadata is now preserved for historical tracking
        assert ProcessingJob.query.filter_by(post_guid="old-guid").first() is not None
        assert Identification.query.count() == 1
        assert TranscriptSegment.query.count() == 1
        assert ModelCall.query.count() == 1
        # Audio files are still deleted
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
    """Test that non-whitelisted posts can be cleaned if they're not the most recent."""
    with app.app_context():
        feed = _create_feed()

        # Create two non-whitelisted posts - only the older one should be cleaned
        old_post = _create_post(
            feed, "non-white-old", "https://example.com/nonwhite-old.mp3"
        )
        old_post.whitelisted = False
        old_post.release_date = datetime.utcnow() - timedelta(days=15)
        old_processed = tmp_path / "old_processed.mp3"
        old_processed.write_text("audio")
        old_post.processed_audio_path = str(old_processed)

        recent_post = _create_post(
            feed, "non-white-recent", "https://example.com/nonwhite-recent.mp3"
        )
        recent_post.whitelisted = False
        recent_post.release_date = datetime.utcnow() - timedelta(days=10)
        recent_processed = tmp_path / "recent_processed.mp3"
        recent_processed.write_text("audio")
        recent_post.processed_audio_path = str(recent_processed)

        # Add old completed jobs so both posts qualify for cleanup by age
        old_completed = datetime.utcnow() - timedelta(days=15)
        db.session.add(
            ProcessingJob(
                id="job-non-white-old",
                post_guid=old_post.guid,
                status="completed",
                current_step=4,
                total_steps=4,
                progress_percentage=100.0,
                created_at=old_completed,
                started_at=old_completed,
                completed_at=old_completed,
            )
        )

        recent_completed = datetime.utcnow() - timedelta(days=10)
        db.session.add(
            ProcessingJob(
                id="job-non-white-recent",
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
        db.session.commit()

        # Both are older than 5 days, but only the old one should be cleaned
        # The recent one should be preserved as the most recent for the feed
        count, _ = count_cleanup_candidates(retention_days=5)
        assert count == 1  # Only the older post

        removed = cleanup_processed_posts(retention_days=5)
        assert removed == 1

        # Older post should be cleaned
        cleaned_post = Post.query.filter_by(guid="non-white-old").first()
        assert cleaned_post is not None
        assert cleaned_post.whitelisted is False
        assert cleaned_post.processed_audio_path is None
        assert cleaned_post.unprocessed_audio_path is None

        # Recent post should be preserved (most recent for feed)
        preserved_post = Post.query.filter_by(guid="non-white-recent").first()
        assert preserved_post is not None
        assert preserved_post.processed_audio_path is not None


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


def test_cleanup_preserves_most_recent_post_per_feed(app, tmp_path) -> None:
    """Test that the most recent post for each feed is never cleaned up."""
    with app.app_context():
        feed = _create_feed()

        # Create multiple old posts for the same feed
        oldest_post = _create_post(feed, "oldest", "https://example.com/oldest.mp3")
        old_post = _create_post(feed, "old", "https://example.com/old.mp3")
        recent_post = _create_post(
            feed, "most-recent", "https://example.com/recent.mp3"
        )

        # All posts have processed audio
        for idx, post in enumerate([oldest_post, old_post, recent_post]):
            processed = tmp_path / f"processed_{idx}.mp3"
            processed.write_text("audio")
            post.processed_audio_path = str(processed)

        # All posts completed before retention window (10 days ago)
        oldest_completed = datetime.utcnow() - timedelta(days=20)
        old_completed = datetime.utcnow() - timedelta(days=15)
        recent_completed = datetime.utcnow() - timedelta(days=10)

        for post, completed_at in [
            (oldest_post, oldest_completed),
            (old_post, old_completed),
            (recent_post, recent_completed),
        ]:
            db.session.add(
                ProcessingJob(
                    id=f"job-{post.guid}",
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

        # With retention of 5 days, all 3 posts are technically expired
        # But the most recent one should be preserved
        count, _ = count_cleanup_candidates(retention_days=5)
        assert count == 2  # Only oldest and old should be candidates

        removed = cleanup_processed_posts(retention_days=5)
        assert removed == 2  # Only oldest and old should be removed

        # Most recent post should still exist with processed audio
        most_recent = Post.query.filter_by(guid="most-recent").first()
        assert most_recent is not None
        assert most_recent.processed_audio_path is not None

        # Older posts should be cleaned
        oldest = Post.query.filter_by(guid="oldest").first()
        old = Post.query.filter_by(guid="old").first()
        assert oldest is not None  # Post row preserved
        assert oldest.processed_audio_path is None  # But audio cleaned
        assert old is not None
        assert old.processed_audio_path is None


def test_cleanup_preserves_most_recent_across_multiple_feeds(app, tmp_path) -> None:
    """Test that each feed keeps its most recent post, even if old."""
    with app.app_context():
        feed1 = _create_feed()
        feed2 = Feed(
            title="Test Feed 2",
            description="desc",
            author="author",
            rss_url="https://example.com/feed2.xml",
            image_url="https://example.com/image2.png",
        )
        db.session.add(feed2)
        db.session.commit()

        # Feed 1: two old posts
        feed1_old = _create_post(feed1, "feed1-old", "https://example.com/f1old.mp3")
        feed1_recent = _create_post(
            feed1, "feed1-recent", "https://example.com/f1recent.mp3"
        )

        # Feed 2: two old posts
        feed2_old = _create_post(feed2, "feed2-old", "https://example.com/f2old.mp3")
        feed2_recent = _create_post(
            feed2, "feed2-recent", "https://example.com/f2recent.mp3"
        )

        # All posts have processed audio
        for idx, post in enumerate([feed1_old, feed1_recent, feed2_old, feed2_recent]):
            processed = tmp_path / f"processed_{idx}.mp3"
            processed.write_text("audio")
            post.processed_audio_path = str(processed)

        # All completed 10+ days ago (before retention window)
        for post in [feed1_old, feed1_recent, feed2_old, feed2_recent]:
            completed_at = datetime.utcnow() - timedelta(days=10)
            db.session.add(
                ProcessingJob(
                    id=f"job-{post.guid}",
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

        # Make feed1_recent and feed2_recent actually more recent
        db.session.query(ProcessingJob).filter_by(
            post_guid="feed1-recent"
        ).first().completed_at = datetime.utcnow() - timedelta(days=8)
        db.session.query(ProcessingJob).filter_by(
            post_guid="feed2-recent"
        ).first().completed_at = datetime.utcnow() - timedelta(days=8)

        db.session.commit()

        # Should preserve one post per feed (2 total)
        count, _ = count_cleanup_candidates(retention_days=5)
        assert count == 2  # feed1-old and feed2-old

        removed = cleanup_processed_posts(retention_days=5)
        assert removed == 2

        # Most recent from each feed should be preserved
        f1_recent = Post.query.filter_by(guid="feed1-recent").first()
        f2_recent = Post.query.filter_by(guid="feed2-recent").first()
        assert f1_recent is not None
        assert f1_recent.processed_audio_path is not None
        assert f2_recent is not None
        assert f2_recent.processed_audio_path is not None

        # Older posts should be cleaned
        f1_old = Post.query.filter_by(guid="feed1-old").first()
        f2_old = Post.query.filter_by(guid="feed2-old").first()
        assert f1_old is not None
        assert f1_old.processed_audio_path is None
        assert f2_old is not None
        assert f2_old.processed_audio_path is None


def test_cleanup_with_single_old_post_per_feed(app, tmp_path) -> None:
    """Test that a feed with only one post keeps it, even if very old."""
    with app.app_context():
        feed = _create_feed()

        # Single post, very old (30 days)
        only_post = _create_post(feed, "only-post", "https://example.com/only.mp3")

        processed = tmp_path / "processed.mp3"
        processed.write_text("audio")
        only_post.processed_audio_path = str(processed)

        completed_at = datetime.utcnow() - timedelta(days=30)
        db.session.add(
            ProcessingJob(
                id="job-only",
                post_guid=only_post.guid,
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

        # Even with 5 day retention, this single post should be preserved
        count, _ = count_cleanup_candidates(retention_days=5)
        assert count == 0  # Nothing should be cleaned

        removed = cleanup_processed_posts(retention_days=5)
        assert removed == 0

        # Post should still have processed audio
        post_after = Post.query.filter_by(guid="only-post").first()
        assert post_after is not None
        assert post_after.processed_audio_path is not None
