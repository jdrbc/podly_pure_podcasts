import logging
from typing import Generator
from unittest.mock import MagicMock

import pytest
from flask import Flask

from app.extensions import db
from app.models import ModelCall, Post, TranscriptSegment
from podcast_processor.transcribe import Segment, Transcriber
from podcast_processor.transcription_manager import TranscriptionManager
from shared.config import Config, TestWhisperConfig
from shared.test_utils import create_standard_test_config


class MockTranscriber(Transcriber):
    """Mock transcriber for testing TranscriptionManager."""

    def __init__(self, mock_response=None):
        self.mock_response = mock_response or []
        self._model_name = "mock_transcriber"

    @property
    def model_name(self) -> str:
        """Implementation of the abstract property"""
        return self._model_name

    def transcribe(self, audio_path):
        """Return mock segments or raise exception based on configuration."""
        if isinstance(self.mock_response, Exception):
            raise self.mock_response
        return self.mock_response


@pytest.fixture
def app() -> Generator[Flask, None, None]:
    """Create and configure a Flask app for testing."""
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    with app.app_context():
        db.init_app(app)
        db.create_all()
        yield app


@pytest.fixture
def test_config() -> Config:
    config = create_standard_test_config()
    # Override whisper config to use test mode
    config.whisper = TestWhisperConfig()
    return config


@pytest.fixture
def test_logger() -> logging.Logger:
    return logging.getLogger("test_logger")


@pytest.fixture
def mock_db_session() -> MagicMock:
    """Create a mock database session"""
    mock_session = MagicMock()
    mock_session.add = MagicMock()
    mock_session.add_all = MagicMock()
    mock_session.commit = MagicMock()
    mock_session.rollback = MagicMock()
    return mock_session


@pytest.fixture
def mock_transcriber() -> MockTranscriber:
    """Return a mock transcriber for testing."""
    return MockTranscriber(
        [
            Segment(start=0.0, end=5.0, text="Test segment 1"),
            Segment(start=5.0, end=10.0, text="Test segment 2"),
        ]
    )


@pytest.fixture
def test_manager(
    test_config: Config,
    test_logger: logging.Logger,
    mock_db_session: MagicMock,
    mock_transcriber: MockTranscriber,
    app: Flask,
) -> TranscriptionManager:
    """Return a TranscriptionManager instance for testing."""
    with app.app_context():
        # We need to create mock query objects with proper structure
        mock_model_call_query = MagicMock()
        mock_segment_query = MagicMock()

        # Create a manager with our mocks
        return TranscriptionManager(
            test_logger,
            test_config,
            model_call_query=mock_model_call_query,
            segment_query=mock_segment_query,
            db_session=mock_db_session,
            transcriber=mock_transcriber,
        )


def test_check_existing_transcription_success(
    test_manager: TranscriptionManager,
    app: Flask,
) -> None:
    """Test finding existing successful transcription"""
    post = Post(id=1, title="Test Post")

    # Create test data
    model_call = ModelCall(
        post_id=1,
        model_name=test_manager.transcriber.model_name,
        status="success",
        first_segment_sequence_num=0,
        last_segment_sequence_num=1,
    )
    segments = [
        TranscriptSegment(
            post_id=1, sequence_num=0, start_time=0.0, end_time=5.0, text="Segment 1"
        ),
        TranscriptSegment(
            post_id=1, sequence_num=1, start_time=5.0, end_time=10.0, text="Segment 2"
        ),
    ]

    with app.app_context():
        # Configure the existing mocks in the manager
        test_manager.model_call_query.filter_by().order_by().first.return_value = (
            model_call
        )
        test_manager.segment_query.filter_by().order_by().all.return_value = segments

        result = test_manager._check_existing_transcription(post)

        assert result is not None
        assert len(result) == 2
        assert result[0].text == "Segment 1"
        assert result[1].text == "Segment 2"


def test_check_existing_transcription_no_model_call(
    test_manager: TranscriptionManager,
    app: Flask,
) -> None:
    """Test when no existing ModelCall exists"""
    post = Post(id=1, title="Test Post")

    with app.app_context():
        # Set return value for the existing mock in the manager
        test_manager.model_call_query.filter_by().order_by().first.return_value = None

        result = test_manager._check_existing_transcription(post)
        assert result is None


def test_transcribe_new(
    test_config: Config,
    test_logger: logging.Logger,
    mock_db_session: MagicMock,
    app: Flask,
) -> None:
    """Test transcribing a new audio file"""
    # Create a new manager instance with mocks
    with app.app_context():
        # Set up mock responses
        mock_model_call_query = MagicMock()
        mock_model_call_query.filter_by().order_by().first.return_value = None
        mock_model_call_query.get.return_value = None

        mock_segment_query = MagicMock()

        # Create a mock transcriber with specific response
        mock_transcriber = MockTranscriber(
            [
                Segment(start=0.0, end=5.0, text="Test segment 1"),
                Segment(start=5.0, end=10.0, text="Test segment 2"),
            ]
        )

        # Create manager with constructor injection of all dependencies
        manager = TranscriptionManager(
            test_logger,
            test_config,
            model_call_query=mock_model_call_query,
            segment_query=mock_segment_query,
            db_session=mock_db_session,
            transcriber=mock_transcriber,
        )

        post = Post(
            id=1, title="Test Post", unprocessed_audio_path="/path/to/audio.mp3"
        )

        # Call the method under test
        segments = manager.transcribe(post)

        assert len(segments) == 2
        assert segments[0].text == "Test segment 1"
        assert segments[1].text == "Test segment 2"
        assert mock_db_session.add.called
        assert mock_db_session.commit.called


def test_transcribe_handles_error(
    test_config: Config,
    test_logger: logging.Logger,
    mock_db_session: MagicMock,
    app: Flask,
) -> None:
    """Test error handling during transcription"""
    # Create a new manager instance with mocks
    with app.app_context():
        # Set up mock responses
        mock_model_call_query = MagicMock()
        mock_model_call_query.filter_by().order_by().first.return_value = None
        mock_model_call_query.get.return_value = ModelCall(id=1)

        mock_segment_query = MagicMock()
        mock_segment_query.filter_by().order_by().all.return_value = []

        # Create a mock transcriber that raises an exception
        error_transcriber = MockTranscriber(Exception("Transcription failed"))

        # Create manager with constructor injection of all dependencies
        manager = TranscriptionManager(
            test_logger,
            test_config,
            model_call_query=mock_model_call_query,
            segment_query=mock_segment_query,
            db_session=mock_db_session,
            transcriber=error_transcriber,
        )

        post = Post(
            id=1, title="Test Post", unprocessed_audio_path="/path/to/audio.mp3"
        )

        # Test the exception
        with pytest.raises(Exception) as exc_info:
            manager.transcribe(post)

        assert str(exc_info.value) == "Transcription failed"
        assert mock_db_session.rollback.called
        assert mock_db_session.add.called
        assert mock_db_session.commit.called
