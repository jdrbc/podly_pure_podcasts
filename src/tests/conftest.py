"""
Fixtures for pytest tests in the tests directory.
"""

import logging
import sys
from typing import Generator
from unittest.mock import MagicMock

import pytest
from flask import Flask

from app import db
from podcast_processor.ad_classifier import AdClassifier
from podcast_processor.audio_processor import AudioProcessor
from podcast_processor.transcription_manager import TranscriptionManager
from shared.config import Config, get_config

# Set up whisper and torch mocks
whisper_mock = MagicMock()
whisper_mock.available_models.return_value = [
    "tiny",
    "base",
    "small",
    "medium",
    "large",
]
whisper_mock.load_model.return_value = MagicMock()
whisper_mock.load_model.return_value.transcribe.return_value = {"segments": []}

torch_mock = MagicMock()
torch_mock.cuda = MagicMock()
torch_mock.device = MagicMock()

# Pre-mock the modules to avoid imports during test collection
sys.modules["whisper"] = whisper_mock
sys.modules["torch"] = torch_mock


@pytest.fixture
def app() -> Generator[Flask, None, None]:
    """Create a Flask app for testing."""
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    with app.app_context():
        db.init_app(app)
        db.create_all()
        yield app


@pytest.fixture
def test_config() -> Config:
    return get_config("config/config.yml")


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
def mock_transcription_manager() -> MagicMock:
    manager = MagicMock(spec=TranscriptionManager)
    manager.transcribe.return_value = [
        MagicMock(sequence_num=0, start_time=0.0, end_time=5.0, text="Test segment 1"),
        MagicMock(sequence_num=1, start_time=5.0, end_time=10.0, text="Test segment 2"),
    ]
    return manager


@pytest.fixture
def mock_ad_classifier() -> MagicMock:
    classifier = MagicMock(spec=AdClassifier)
    classifier.classify.return_value = None  # classify method has no return value
    return classifier


@pytest.fixture
def mock_audio_processor() -> MagicMock:
    processor = MagicMock(spec=AudioProcessor)
    processor.get_ad_segments.return_value = [(0.0, 5.0)]
    return processor
