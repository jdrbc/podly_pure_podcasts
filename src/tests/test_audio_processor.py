import logging
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from app.models import Identification, Post, TranscriptSegment
from podcast_processor.audio_processor import AudioProcessor
from shared.config import Config, get_config


@pytest.fixture
def test_processor(
    test_config: Config,
    test_logger: logging.Logger,
) -> AudioProcessor:
    """Return an AudioProcessor instance with default dependencies for testing."""
    return AudioProcessor(config=test_config, logger=test_logger)


@pytest.fixture
def test_processor_with_mocks(
    test_config: Config,
    test_logger: logging.Logger,
    mock_db_session: MagicMock,
) -> AudioProcessor:
    """Return an AudioProcessor instance with mock dependencies for testing."""
    mock_identification_query = MagicMock()
    mock_transcript_segment_query = MagicMock()
    mock_model_call_query = MagicMock()

    return AudioProcessor(
        config=test_config,
        logger=test_logger,
        identification_query=mock_identification_query,
        transcript_segment_query=mock_transcript_segment_query,
        model_call_query=mock_model_call_query,
        db_session=mock_db_session,
    )


def test_get_ad_segments(app: Flask) -> None:
    """Test retrieving ad segments from the database"""
    # Create test data
    post = Post(id=1, title="Test Post")
    segment = TranscriptSegment(
        id=1,
        post_id=1,
        sequence_num=0,
        start_time=0.0,
        end_time=10.0,
        text="Test segment",
    )
    identification = Identification(
        transcript_segment_id=1, model_call_id=1, label="ad", confidence=0.9
    )

    with app.app_context():
        # Create mocks
        mock_identification_query = MagicMock()
        mock_query_chain = MagicMock()
        mock_identification_query.join.return_value = mock_query_chain
        mock_query_chain.join.return_value = mock_query_chain
        mock_query_chain.filter.return_value = mock_query_chain
        mock_query_chain.all.return_value = [identification]

        # Create processor with mocks
        test_processor = AudioProcessor(
            config=get_config("config/config_test.yml"),
            identification_query=mock_identification_query,
        )

        with patch.object(identification, "transcript_segment", segment):
            segments = test_processor.get_ad_segments(post)

            assert len(segments) == 1
            assert segments[0] == (0.0, 10.0)


def test_merge_ad_segments(
    test_processor_with_mocks: AudioProcessor,
) -> None:
    """Test merging of nearby ad segments"""
    duration_ms = 30000  # 30 seconds
    ad_segments = [
        (0.0, 5.0),  # 0-5s
        (6.0, 10.0),  # 6-10s - should merge with first segment
        (20.0, 25.0),  # 20-25s - should stay separate
    ]

    merged = test_processor_with_mocks.merge_ad_segments(
        duration_ms=duration_ms,
        ad_segments=ad_segments,
        min_ad_segment_length_seconds=2.0,
        min_ad_segment_separation_seconds=2.0,
    )

    # Should merge first two segments
    assert len(merged) == 2
    assert merged[0] == (0, 10000)  # 0-10s
    assert merged[1] == (20000, 25000)  # 20-25s


def test_merge_ad_segments_with_short_segments(
    test_processor_with_mocks: AudioProcessor,
) -> None:
    """Test that segments shorter than minimum length are filtered out"""
    duration_ms = 30000
    ad_segments = [
        (0.0, 1.0),  # Too short, should be filtered
        (10.0, 15.0),  # Long enough, should stay
        (20.0, 20.5),  # Too short, should be filtered
    ]

    merged = test_processor_with_mocks.merge_ad_segments(
        duration_ms=duration_ms,
        ad_segments=ad_segments,
        min_ad_segment_length_seconds=2.0,
        min_ad_segment_separation_seconds=2.0,
    )

    assert len(merged) == 1
    assert merged[0] == (10000, 15000)


def test_merge_ad_segments_end_extension(
    test_processor_with_mocks: AudioProcessor,
) -> None:
    """Test that segments near the end are extended to the end"""
    duration_ms = 30000
    ad_segments = [
        (28.0, 29.0),  # Near end, should extend to 30s
    ]

    merged = test_processor_with_mocks.merge_ad_segments(
        duration_ms=duration_ms,
        ad_segments=ad_segments,
        min_ad_segment_length_seconds=2.0,
        min_ad_segment_separation_seconds=2.0,
    )

    assert len(merged) == 1
    assert merged[0] == (28000, 30000)  # Extended to end


def test_process_audio(app: Flask, test_processor_with_mocks: AudioProcessor) -> None:
    """Test the process_audio method"""
    with app.app_context():
        # Create actual Post instance
        post = Post(
            id=1,
            title="Test Post",
            guid="test-audio-guid",
            unprocessed_audio_path="path/to/audio.mp3",
        )
        output_path = "path/to/output.mp3"

        # Set up mocks for get_ad_segments and get_audio_duration_ms
        with patch.object(
            test_processor_with_mocks, "get_ad_segments", return_value=[(5.0, 10.0)]
        ), patch(
            "podcast_processor.audio_processor.get_audio_duration_ms",
            return_value=30000,
        ), patch(
            "podcast_processor.audio_processor.clip_segments_with_fade"
        ) as mock_clip:
            # Call the method
            test_processor_with_mocks.process_audio(post, output_path)

            # Assertions
            assert post.duration == 30.0  # 30000ms / 1000 = 30s
            assert post.processed_audio_path == output_path
            assert test_processor_with_mocks.db_session.commit.called
            mock_clip.assert_called_once()
