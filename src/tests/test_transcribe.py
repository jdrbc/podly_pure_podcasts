import logging
from typing import Any
from unittest.mock import MagicMock

import pytest
from openai.types.audio.transcription_segment import TranscriptionSegment

# from pytest_mock import MockerFixture


@pytest.mark.skip
def test_remote_transcribe() -> None:
    # import here instead of the toplevel because torch is not installed properly in CI.
    from podcast_processor.transcribe import (  # pylint: disable=import-outside-toplevel
        OpenAIWhisperTranscriber,
    )

    logger = logging.getLogger("global_logger")
    from shared.test_utils import create_standard_test_config

    config = create_standard_test_config().model_dump()

    transcriber = OpenAIWhisperTranscriber(logger, config)

    transcription = transcriber.transcribe("file.mp3")
    assert transcription == []


@pytest.mark.skip
def test_local_transcribe() -> None:
    # import here instead of the toplevel because torch is not installed properly in CI.
    from podcast_processor.transcribe import (  # pylint: disable=import-outside-toplevel
        LocalWhisperTranscriber,
    )

    logger = logging.getLogger("global_logger")
    transcriber = LocalWhisperTranscriber(logger, "base.en")
    transcription = transcriber.transcribe("src/tests/file.mp3")
    assert transcription == []


@pytest.mark.skip
def test_groq_transcribe(mocker: Any) -> None:
    # import here instead of the toplevel because dependencies aren't installed properly in CI.
    from podcast_processor.transcribe import (  # pylint: disable=import-outside-toplevel
        GroqWhisperTranscriber,
    )
    from shared.config import (  # pylint: disable=import-outside-toplevel
        GroqWhisperConfig,
    )

    # Mock the requests call
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "segments": [
            {"start": 0.0, "end": 1.0, "text": "This is a test segment."},
            {"start": 1.0, "end": 2.0, "text": "This is another test segment."},
        ]
    }
    mocker.patch("requests.post", return_value=mock_response)

    # Mock file operations
    mocker.patch("builtins.open", mocker.mock_open(read_data="test audio data"))
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("podcast_processor.audio.split_audio", return_value=[("test.mp3", 0)])
    mocker.patch("shutil.rmtree")

    logger = logging.getLogger("global_logger")
    config = GroqWhisperConfig(
        api_key="test_key", model="whisper-large-v3-turbo", language="en"
    )

    transcriber = GroqWhisperTranscriber(logger, config)
    transcription = transcriber.transcribe("test.mp3")

    assert len(transcription) == 2
    assert transcription[0].text == "This is a test segment."
    assert transcription[1].text == "This is another test segment."


def test_offset() -> None:
    # import here instead of the toplevel because torch is not installed properly in CI.
    from podcast_processor.transcribe import (  # pylint: disable=import-outside-toplevel
        OpenAIWhisperTranscriber,
    )

    assert OpenAIWhisperTranscriber.add_offset_to_segments(
        [
            TranscriptionSegment(
                id=1,
                avg_logprob=2,
                seek=6,
                temperature=7,
                text="hi",
                tokens=[],
                compression_ratio=3,
                no_speech_prob=4,
                start=12.345,
                end=45.678,
            )
        ],
        123,
    ) == [
        TranscriptionSegment(
            id=1,
            avg_logprob=2,
            seek=6,
            temperature=7,
            text="hi",
            tokens=[],
            compression_ratio=3,
            no_speech_prob=4,
            start=12.468,
            end=45.800999999999995,
        )
    ]
