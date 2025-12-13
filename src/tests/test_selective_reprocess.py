"""Tests for selective reprocessing functionality."""
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from app.extensions import db
from app.models import Feed, Post, ProcessingJob, TranscriptSegment, Identification, ModelCall
from app.routes.post_routes import post_bp


@pytest.fixture
def test_post_with_processing_data(app, tmp_path):
    """Create a test post with complete processing data."""
    with app.app_context():
        # Create feed
        feed = Feed(title="Test Feed", rss_url="https://example.com/feed.xml")
        db.session.add(feed)
        db.session.commit()

        # Create audio files
        unprocessed_audio = tmp_path / "unprocessed.mp3"
        unprocessed_audio.write_bytes(b"unprocessed audio data")

        processed_audio = tmp_path / "processed.mp3"
        processed_audio.write_bytes(b"processed audio data")

        # Create post
        post = Post(
            feed_id=feed.id,
            guid="test-guid-123",
            download_url="https://example.com/audio.mp3",
            title="Test Episode",
            unprocessed_audio_path=str(unprocessed_audio),
            processed_audio_path=str(processed_audio),
            whitelisted=True,
        )
        db.session.add(post)
        db.session.commit()

        # Add transcript segments
        for i in range(5):
            segment = TranscriptSegment(
                post_id=post.id,
                sequence_num=i,
                start_time=i * 10.0,
                end_time=(i + 1) * 10.0,
                text=f"Segment {i} text",
            )
            db.session.add(segment)
        db.session.commit()

        # Create a model call for identifications
        model_call = ModelCall(
            post_id=post.id,
            first_segment_sequence_num=0,
            last_segment_sequence_num=4,
            model_name="test-model",
            prompt="Test prompt",
            response="Test response",
            status="completed",
        )
        db.session.add(model_call)
        db.session.commit()

        # Add identifications (get the first segment)
        first_segment = TranscriptSegment.query.filter_by(
            post_id=post.id, sequence_num=0
        ).first()
        identification = Identification(
            transcript_segment_id=first_segment.id,
            model_call_id=model_call.id,
            label="ad",
            confidence=0.9,
        )
        db.session.add(identification)
        db.session.commit()

        yield post


def test_reprocess_endpoint_accepts_from_step(app, test_post_with_processing_data):
    """Test that the reprocess endpoint accepts and processes from_step parameter."""
    app.testing = True
    app.register_blueprint(post_bp)

    with app.app_context():
        post = test_post_with_processing_data
        client = app.test_client()

        # Mock the jobs manager to capture the call
        with patch('app.routes.post_routes.get_jobs_manager') as mock_get_jm:
            mock_jm = MagicMock()
            mock_jm.start_post_processing.return_value = {
                'status': 'started',
                'message': 'Job queued for processing',
                'job_id': 'test-job-123'
            }
            mock_get_jm.return_value = mock_jm

            # Test with from_step = 3
            response = client.post(
                f'/api/posts/{post.guid}/reprocess',
                data=json.dumps({'from_step': 3}),
                content_type='application/json'
            )

            assert response.status_code == 200
            data = json.loads(response.data)

            # Verify the jobs manager was called with start_from_step=3
            mock_jm.start_post_processing.assert_called_once()
            call_kwargs = mock_jm.start_post_processing.call_args[1]
            assert 'start_from_step' in call_kwargs
            assert call_kwargs['start_from_step'] == 3


def test_validate_step_dependencies(app, test_post_with_processing_data):
    """Test step dependency validation."""
    from app.posts import validate_step_dependencies

    with app.app_context():
        post = test_post_with_processing_data

        # Step 3 should be valid (has audio and transcripts)
        is_valid, fallback, msg = validate_step_dependencies(post, 3)
        assert is_valid is True
        assert fallback is None or fallback == 3

        # Step 4 should be valid (has identifications)
        is_valid, fallback, msg = validate_step_dependencies(post, 4)
        assert is_valid is True
        assert fallback is None or fallback == 4


def test_validate_step_dependencies_missing_audio(app, tmp_path):
    """Test validation when audio file is missing."""
    from app.posts import validate_step_dependencies

    with app.app_context():
        feed = Feed(title="Test Feed", rss_url="https://example.com/feed.xml")
        db.session.add(feed)
        db.session.commit()

        # Post without audio file
        post = Post(
            feed_id=feed.id,
            guid="test-guid-no-audio",
            download_url="https://example.com/audio.mp3",
            title="Test Episode",
            unprocessed_audio_path="/nonexistent/audio.mp3",
            whitelisted=True,
        )
        db.session.add(post)
        db.session.commit()

        # Should fall back to step 1
        is_valid, fallback, msg = validate_step_dependencies(post, 2)
        assert is_valid is False
        assert fallback == 1


def test_validate_step_dependencies_missing_transcripts(app, tmp_path):
    """Test validation when transcripts are missing."""
    from app.posts import validate_step_dependencies

    with app.app_context():
        feed = Feed(title="Test Feed", rss_url="https://example.com/feed.xml")
        db.session.add(feed)
        db.session.commit()

        # Create audio file
        unprocessed_audio = tmp_path / "unprocessed.mp3"
        unprocessed_audio.write_bytes(b"audio data")

        # Post with audio but no transcripts
        post = Post(
            feed_id=feed.id,
            guid="test-guid-no-transcripts",
            download_url="https://example.com/audio.mp3",
            title="Test Episode",
            unprocessed_audio_path=str(unprocessed_audio),
            whitelisted=True,
        )
        db.session.add(post)
        db.session.commit()

        # Should fall back to step 2
        is_valid, fallback, msg = validate_step_dependencies(post, 3)
        assert is_valid is False
        assert fallback == 2


def test_processor_respects_start_from_step(app, test_post_with_processing_data):
    """Test that the processor respects start_from_step parameter."""
    with app.app_context():
        post = test_post_with_processing_data

        # Create a job with start_from_step=3
        job = ProcessingJob(
            id="test-job-456",
            post_guid=post.guid,
            status="pending",
            current_step=0,
            progress_percentage=0.0,
            start_from_step=3,
        )
        db.session.add(job)
        db.session.commit()

        # Verify the job has start_from_step set
        assert job.start_from_step == 3

        # Read back from DB
        db.session.refresh(job)
        assert job.start_from_step == 3


def test_selective_clear_step_2(app, test_post_with_processing_data):
    """Test selective clear keeps audio when starting from step 2."""
    from app.posts import selective_clear_post_processing_data

    with app.app_context():
        post = test_post_with_processing_data
        original_audio_path = post.unprocessed_audio_path

        # Verify we have transcripts and identifications
        assert TranscriptSegment.query.filter_by(post_id=post.id).count() > 0
        identification_count = db.session.query(Identification).join(
            TranscriptSegment, Identification.transcript_segment_id == TranscriptSegment.id
        ).filter(TranscriptSegment.post_id == post.id).count()
        assert identification_count > 0

        # Clear from step 2
        result = selective_clear_post_processing_data(post, 2)
        db.session.commit()

        # Audio should still exist
        assert post.unprocessed_audio_path == original_audio_path
        assert os.path.exists(original_audio_path)

        # Transcripts and identifications should be deleted
        assert TranscriptSegment.query.filter_by(post_id=post.id).count() == 0
        identification_count = db.session.query(Identification).join(
            TranscriptSegment, Identification.transcript_segment_id == TranscriptSegment.id
        ).filter(TranscriptSegment.post_id == post.id).count()
        assert identification_count == 0

        # Processed audio should be cleared
        assert post.processed_audio_path is None


def test_selective_clear_step_3(app, test_post_with_processing_data):
    """Test selective clear keeps audio and transcripts when starting from step 3."""
    from app.posts import selective_clear_post_processing_data

    with app.app_context():
        post = test_post_with_processing_data
        original_audio_path = post.unprocessed_audio_path
        transcript_count = TranscriptSegment.query.filter_by(post_id=post.id).count()

        # Verify we have identifications
        identification_count = db.session.query(Identification).join(
            TranscriptSegment, Identification.transcript_segment_id == TranscriptSegment.id
        ).filter(TranscriptSegment.post_id == post.id).count()
        assert identification_count > 0

        # Clear from step 3
        result = selective_clear_post_processing_data(post, 3)
        db.session.commit()

        # Audio and transcripts should still exist
        assert post.unprocessed_audio_path == original_audio_path
        assert os.path.exists(original_audio_path)
        assert TranscriptSegment.query.filter_by(post_id=post.id).count() == transcript_count

        # Identifications should be deleted
        identification_count = db.session.query(Identification).join(
            TranscriptSegment, Identification.transcript_segment_id == TranscriptSegment.id
        ).filter(TranscriptSegment.post_id == post.id).count()
        assert identification_count == 0

        # Processed audio should be cleared
        assert post.processed_audio_path is None


def test_selective_clear_step_4(app, test_post_with_processing_data):
    """Test selective clear keeps everything when starting from step 4."""
    from app.posts import selective_clear_post_processing_data

    with app.app_context():
        post = test_post_with_processing_data
        original_audio_path = post.unprocessed_audio_path
        transcript_count = TranscriptSegment.query.filter_by(post_id=post.id).count()
        identification_count = db.session.query(Identification).join(
            TranscriptSegment, Identification.transcript_segment_id == TranscriptSegment.id
        ).filter(TranscriptSegment.post_id == post.id).count()

        # Clear from step 4
        result = selective_clear_post_processing_data(post, 4)
        db.session.commit()

        # Everything should still exist except processed audio
        assert post.unprocessed_audio_path == original_audio_path
        assert os.path.exists(original_audio_path)
        assert TranscriptSegment.query.filter_by(post_id=post.id).count() == transcript_count
        identification_count_after = db.session.query(Identification).join(
            TranscriptSegment, Identification.transcript_segment_id == TranscriptSegment.id
        ).filter(TranscriptSegment.post_id == post.id).count()
        assert identification_count_after == identification_count

        # Processed audio should be cleared
        assert post.processed_audio_path is None
