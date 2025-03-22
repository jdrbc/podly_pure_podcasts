import logging
from unittest.mock import MagicMock

import pytest
import yaml
from openai.types.audio.transcription_segment import TranscriptionSegment
from pytest_mock import MockerFixture


@pytest.fixture(autouse=True)
def mock_whisper_fixture(mocker: MockerFixture) -> None:
    mocker.patch.dict("sys.modules", {"whisper": MagicMock()})


@pytest.mark.skip
def test_remote_transcribe() -> None:
    # import here instead of the toplevel because torch is not installed properly in CI.
    from podcast_processor.transcribe import (  # pylint: disable=import-outside-toplevel
        RemoteWhisperTranscriber,
    )

    logger = logging.getLogger("global_logger")
    with open("config/config.yml", "r") as f:
        config = yaml.safe_load(f)

    transcriber = RemoteWhisperTranscriber(logger, config)

    transcription = transcriber.transcribe("file.mp3")
    assert transcription == []


@pytest.mark.skip
def test_local_transcribe() -> None:
    # import here instead of the toplevel because torch is not installed properly in CI.
    from podcast_processor.transcribe import (  # pylint: disable=import-outside-toplevel
        LocalWhisperTranscriber,
    )

    logger = logging.getLogger("global_logger")
    transcriber = LocalWhisperTranscriber(logger, "base")
    transcription = transcriber.transcribe("src/tests/file.mp3")
    assert transcription == []


@pytest.mark.skip
def test_groq_transcribe(mocker: MockerFixture) -> None:
    # import here instead of the toplevel because dependencies aren't installed properly in CI.
    from podcast_processor.transcribe import (  # pylint: disable=import-outside-toplevel
        GroqWhisperTranscriber,
    )
    from shared.config import (
        GroqWhisperConfig,
    )  # pylint: disable=import-outside-toplevel

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
        RemoteWhisperTranscriber,
    )

    assert RemoteWhisperTranscriber.add_offset_to_segments(
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
