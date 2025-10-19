from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from jinja2 import Template
from litellm.exceptions import InternalServerError
from litellm.types.utils import Choices

from app.extensions import db
from app.models import ModelCall, Post, TranscriptSegment
from podcast_processor.ad_classifier import AdClassifier
from shared.config import Config
from shared.test_utils import create_standard_test_config


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
    return create_standard_test_config()


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
def test_classifier(test_config: Config) -> AdClassifier:
    """Create an AdClassifier with default dependencies"""
    return AdClassifier(config=test_config)


@pytest.fixture
def test_classifier_with_mocks(
    test_config: Config, mock_db_session: MagicMock
) -> AdClassifier:
    """Create an AdClassifier with mock dependencies"""
    mock_model_call_query = MagicMock()
    mock_identification_query = MagicMock()
    mock_logger = MagicMock()

    return AdClassifier(
        config=test_config,
        logger=mock_logger,
        model_call_query=mock_model_call_query,
        identification_query=mock_identification_query,
        db_session=mock_db_session,
    )


def test_call_model(test_config: Config, app: Flask) -> None:
    """Test the _call_model method with mocked litellm"""
    with app.app_context():
        # Create mocks
        mock_db_session = MagicMock()

        # Create a classifier with the mocks
        classifier = AdClassifier(config=test_config, db_session=mock_db_session)

        # Create a dummy ModelCall object
        dummy_model_call = ModelCall(
            post_id=0,
            model_name=test_config.llm_model,
            prompt="test prompt",
            first_segment_sequence_num=0,
            last_segment_sequence_num=0,
            status="pending",
        )

        # Create a mock message and choice directly
        mock_message = MagicMock()
        mock_message.content = "test response"

        mock_choice = MagicMock(spec=Choices)
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        # Patch the litellm.completion function for this test
        with patch("litellm.completion", return_value=mock_response):
            # Call the method
            response = classifier._call_model(
                model_call_obj=dummy_model_call,
                system_prompt="test system prompt",
            )

            # Verify response
            assert response == "test response"
            assert dummy_model_call.status == "success"
            assert dummy_model_call.response == "test response"
            assert mock_db_session.add.called
            assert mock_db_session.commit.called


def test_call_model_retry_on_internal_error(test_config: Config, app: Flask) -> None:
    """Test that _call_model retries on InternalServerError"""
    with app.app_context():
        # Create mocks
        mock_db_session = MagicMock()

        # Create a classifier with the mocks
        classifier = AdClassifier(config=test_config, db_session=mock_db_session)

        dummy_model_call = ModelCall(
            post_id=0,
            model_name=test_config.llm_model,
            prompt="test prompt",
            first_segment_sequence_num=0,
            last_segment_sequence_num=0,
            status="pending",
        )

        # Create a mock message and choice directly
        mock_message = MagicMock()
        mock_message.content = "test response"

        mock_choice = MagicMock(spec=Choices)
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        # First call fails, second succeeds
        mock_completion_side_effects = [
            InternalServerError(
                message="test error",
                llm_provider="test_provider",
                model="test_model",
            ),
            mock_response,
        ]

        # Patch time.sleep to avoid waiting during tests
        with patch("time.sleep"), patch(
            "litellm.completion", side_effect=mock_completion_side_effects
        ):
            response = classifier._call_model(
                model_call_obj=dummy_model_call,
                system_prompt="test system prompt",
            )

            assert response == "test response"
            assert dummy_model_call.status == "success"
            # The completion should be called twice
            assert mock_db_session.add.call_count >= 2
            assert mock_db_session.commit.call_count >= 2


def test_process_segment_chunk(test_config: Config, app: Flask) -> None:
    """Test processing a chunk of transcript segments"""
    with app.app_context():
        # Create mocks
        mock_db_session = MagicMock()
        mock_model_call_query = MagicMock()

        # Create the classifier with our mocks
        classifier = AdClassifier(
            config=test_config,
            model_call_query=mock_model_call_query,
            db_session=mock_db_session,
        )

        # Create test data
        post = Post(id=1, title="Test Post")
        segments = [
            TranscriptSegment(
                id=1,
                post_id=1,
                sequence_num=0,
                start_time=0.0,
                end_time=10.0,
                text="Test segment 1",
            ),
            TranscriptSegment(
                id=2,
                post_id=1,
                sequence_num=1,
                start_time=10.0,
                end_time=20.0,
                text="Test segment 2",
            ),
        ]

        # Create a proper Jinja2 Template object
        user_template = Template("Test template: {{ podcast_title }}")

        # Create an actual ModelCall instance instead of a MagicMock
        model_call = ModelCall(
            post_id=1,
            model_name=test_config.llm_model,
            prompt="test prompt",
            first_segment_sequence_num=0,
            last_segment_sequence_num=1,
            status="success",
            response='{"ad_segments": []}',
        )

        # Use patch.multiple to mock multiple methods with a single context manager
        mock_get_model_call = MagicMock(return_value=model_call)
        mock_process_response = MagicMock()

        with patch.multiple(
            classifier,
            _get_or_create_model_call=mock_get_model_call,
            _process_successful_response=mock_process_response,
        ):
            classifier._process_segment_chunk(
                transcript_segments=segments,
                start_idx=0,
                end_idx=2,
                system_prompt="test system prompt",
                user_prompt_template=user_template,
                post=post,
            )

            mock_get_model_call.assert_called_once()
