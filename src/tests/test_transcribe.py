import logging

import pytest
from openai import OpenAI
from openai.types.audio.transcription_segment import TranscriptionSegment

from podcast_processor.env_settings import populate_env_settings
from podcast_processor.transcribe import RemoteWhisperTranscriber


@pytest.mark.skip
def test_transcribe() -> None:
    logger = logging.getLogger("global_logger")
    env_settings = populate_env_settings()
    client = OpenAI(
        base_url=env_settings.openai_base_url,
        api_key=env_settings.openai_api_key,
    )
    transcriber = RemoteWhisperTranscriber(logger, client)

    transcription = transcriber.transcribe("file.mp3")
    assert transcription == []


def test_offset() -> None:
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
