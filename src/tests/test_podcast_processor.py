import logging
from contextlib import nullcontext
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from app.models import Post
from podcast_processor.ad_classifier import AdClassifier
from podcast_processor.audio_processor import AudioProcessor
from podcast_processor.podcast_processor import PodcastProcessor
from podcast_processor.transcription_manager import TranscriptionManager
from shared.config import Config
from shared.processing_paths import ProcessingPaths


@pytest.fixture
def test_processor(
    test_config: Config,
    test_logger: logging.Logger,
    mock_transcription_manager: MagicMock,
    mock_ad_classifier: MagicMock,
    mock_audio_processor: MagicMock,
    mock_db_session: MagicMock,
    mock_downloader: MagicMock,
    mock_status_manager: MagicMock,
) -> PodcastProcessor:
    """Create a PodcastProcessor with mock dependencies"""
    return PodcastProcessor(
        config=test_config,
        logger=test_logger,
        downloader=mock_downloader,
        status_manager=mock_status_manager,
        transcription_manager=mock_transcription_manager,
        ad_classifier=mock_ad_classifier,
        audio_processor=mock_audio_processor,
        db_session=mock_db_session,
    )


def test_process_podcast_integration(
    test_processor: PodcastProcessor,
    app: Optional[Flask] = None,
) -> None:
    """Integration test for podcast processing with mocked components"""
    # Use app context if provided
    ctx_manager = app.app_context() if app else nullcontext()

    with ctx_manager:
        # Create test post with a mock feed
        post = Post(
            id=1,
            title="Test Podcast",
            unprocessed_audio_path="/path/to/audio.mp3",
            whitelisted=True,
        )
        mock_feed = MagicMock()
        mock_feed.title = "Test Feed"
        post.feed = mock_feed

        # Create a proper ProcessingPaths instance
        mock_paths = ProcessingPaths(
            post_processed_audio_path=Path("/path/to/processed/audio.mp3")
        )

        # Set up mocks
        with patch(
            "podcast_processor.podcast_processor.get_post_processed_audio_path",
            return_value=mock_paths,
        ), patch("os.path.exists", return_value=False), patch(
            "pathlib.Path.mkdir", return_value=None
        ):

            # Process the podcast
            test_processor.process(post)

            # Verify component interactions
            test_processor.transcription_manager.transcribe.assert_called_once_with(
                post
            )
            test_processor.ad_classifier.classify.assert_called_once()
            test_processor.audio_processor.process_audio.assert_called_once()


def test_process_podcast_handles_transcription_error(
    test_config: Config,
    test_logger: logging.Logger,
    mock_ad_classifier: MagicMock,
    mock_audio_processor: MagicMock,
    mock_db_session: MagicMock,
    mock_downloader: MagicMock,
    mock_status_manager: MagicMock,
    app: Optional[Flask] = None,
) -> None:
    """Test error handling when transcription fails"""
    # Use app context if provided
    ctx_manager = app.app_context() if app else nullcontext()

    with ctx_manager:
        # Create a failing transcription manager
        mock_failing_transcription_manager = MagicMock(spec=TranscriptionManager)
        mock_failing_transcription_manager.transcribe.side_effect = Exception(
            "Transcription failed"
        )

        # Create processor with the failing manager
        test_processor = PodcastProcessor(
            config=test_config,
            logger=test_logger,
            transcription_manager=mock_failing_transcription_manager,
            ad_classifier=mock_ad_classifier,
            audio_processor=mock_audio_processor,
            db_session=mock_db_session,
            downloader=mock_downloader,
            status_manager=mock_status_manager,
        )

        # Create test post with a mock feed
        post = Post(
            id=1,
            title="Test Podcast",
            unprocessed_audio_path="/path/to/audio.mp3",
            whitelisted=True,
        )
        mock_feed = MagicMock()
        mock_feed.title = "Test Feed"
        post.feed = mock_feed

        # Create a proper ProcessingPaths instance
        mock_paths = ProcessingPaths(
            post_processed_audio_path=Path("/path/to/processed/audio.mp3")
        )

        # Set up mocks
        with patch(
            "podcast_processor.podcast_processor.get_post_processed_audio_path",
            return_value=mock_paths,
        ), patch("os.path.exists", return_value=False), patch(
            "pathlib.Path.mkdir", return_value=None
        ):

            with pytest.raises(Exception) as exc_info:
                test_processor.process(post)

            assert str(exc_info.value) == "Transcription failed"
            mock_failing_transcription_manager.transcribe.assert_called_once()
            # Verify subsequent steps were not called
            assert not mock_ad_classifier.classify.called
            assert not mock_audio_processor.process_audio.called


def test_process_podcast_handles_classification_error(
    test_config: Config,
    test_logger: logging.Logger,
    mock_transcription_manager: MagicMock,
    mock_audio_processor: MagicMock,
    mock_db_session: MagicMock,
    mock_downloader: MagicMock,
    mock_status_manager: MagicMock,
    app: Optional[Flask] = None,
) -> None:
    """Test error handling when classification fails"""
    # Use app context if provided
    ctx_manager = app.app_context() if app else nullcontext()

    with ctx_manager:
        # Create a failing ad classifier
        mock_failing_ad_classifier = MagicMock(spec=AdClassifier)
        mock_failing_ad_classifier.classify.side_effect = Exception(
            "Classification failed"
        )

        # Create processor with the failing classifier
        test_processor = PodcastProcessor(
            config=test_config,
            logger=test_logger,
            transcription_manager=mock_transcription_manager,
            ad_classifier=mock_failing_ad_classifier,
            audio_processor=mock_audio_processor,
            db_session=mock_db_session,
            downloader=mock_downloader,
            status_manager=mock_status_manager,
        )

        # Create test post with a mock feed
        post = Post(
            id=1,
            title="Test Podcast",
            unprocessed_audio_path="/path/to/audio.mp3",
            whitelisted=True,
        )
        mock_feed = MagicMock()
        mock_feed.title = "Test Feed"
        post.feed = mock_feed

        # Create a proper ProcessingPaths instance
        mock_paths = ProcessingPaths(
            post_processed_audio_path=Path("/path/to/processed/audio.mp3")
        )

        # Set up mocks
        with patch(
            "podcast_processor.podcast_processor.get_post_processed_audio_path",
            return_value=mock_paths,
        ), patch("os.path.exists", return_value=False), patch(
            "pathlib.Path.mkdir", return_value=None
        ):

            with pytest.raises(Exception) as exc_info:
                test_processor.process(post)

            assert str(exc_info.value) == "Classification failed"
            mock_transcription_manager.transcribe.assert_called_once()
            mock_failing_ad_classifier.classify.assert_called_once()
            # Verify subsequent steps were not called
            assert not mock_audio_processor.process_audio.called


def test_process_podcast_handles_audio_processing_error(
    test_config: Config,
    test_logger: logging.Logger,
    mock_transcription_manager: MagicMock,
    mock_ad_classifier: MagicMock,
    mock_db_session: MagicMock,
    mock_downloader: MagicMock,
    mock_status_manager: MagicMock,
    app: Optional[Flask] = None,
) -> None:
    """Test error handling when audio processing fails"""
    ctx_manager = app.app_context() if app else nullcontext()

    with ctx_manager:
        # Create a failing audio processor
        mock_failing_audio_processor = MagicMock(spec=AudioProcessor)
        mock_failing_audio_processor.process_audio.side_effect = Exception(
            "Audio processing failed"
        )

        # Create processor with the failing audio processor
        test_processor = PodcastProcessor(
            config=test_config,
            logger=test_logger,
            transcription_manager=mock_transcription_manager,
            ad_classifier=mock_ad_classifier,
            audio_processor=mock_failing_audio_processor,
            db_session=mock_db_session,
            downloader=mock_downloader,
            status_manager=mock_status_manager,
        )

        # Create test post with a mock feed
        post = Post(
            id=1,
            title="Test Podcast",
            unprocessed_audio_path="/path/to/audio.mp3",
            whitelisted=True,
        )
        mock_feed = MagicMock()
        mock_feed.title = "Test Feed"
        post.feed = mock_feed

        # Create a proper ProcessingPaths instance
        mock_paths = ProcessingPaths(
            post_processed_audio_path=Path("/path/to/processed/audio.mp3")
        )

        # Set up mocks
        with patch(
            "podcast_processor.podcast_processor.get_post_processed_audio_path",
            return_value=mock_paths,
        ), patch("os.path.exists", return_value=False), patch(
            "pathlib.Path.mkdir", return_value=None
        ):

            with pytest.raises(Exception) as exc_info:
                test_processor.process(post)

            assert str(exc_info.value) == "Audio processing failed"
            mock_transcription_manager.transcribe.assert_called_once()
            mock_ad_classifier.classify.assert_called_once()
            mock_failing_audio_processor.process_audio.assert_called_once()
