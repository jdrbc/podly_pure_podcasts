import logging
import shutil
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List

import whisper  # type: ignore[import-untyped]
from openai import OpenAI
from openai.types.audio.transcription_segment import TranscriptionSegment
from pydantic import BaseModel
import json
import requests

from podcast_processor.audio import split_audio
from shared.config import GroqWhisperConfig, RemoteWhisperConfig


class Segment(BaseModel):
    start: float
    end: float
    text: str


class Transcriber(ABC):

    @abstractmethod
    def transcribe(self, audio_file_path: str) -> List[Segment]:
        pass


class LocalTranscriptSegment(BaseModel):
    id: int
    seek: int
    start: float
    end: float
    text: str
    tokens: List[int]
    temperature: float
    avg_logprob: float
    compression_ratio: float
    no_speech_prob: float

    def to_segment(self) -> Segment:
        return Segment(start=self.start, end=self.end, text=self.text)


class TestWhisperTranscriber(Transcriber):

    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def transcribe(self, _: str) -> List[Segment]:
        self.logger.info("Using test whisper")
        return [
            Segment(start=0, end=1, text="This is a test"),
            Segment(start=1, end=2, text="This is another test"),
        ]


class LocalWhisperTranscriber(Transcriber):

    def __init__(self, logger: logging.Logger, whisper_model: str):
        self.logger = logger
        self.whisper_model = whisper_model

    @staticmethod
    def convert_to_pydantic(transcript_data: List[Any],) -> List[LocalTranscriptSegment]:
        return [LocalTranscriptSegment(**item) for item in transcript_data]

    @staticmethod
    def local_seg_to_seg(local_segments: List[LocalTranscriptSegment]) -> List[Segment]:
        return [seg.to_segment() for seg in local_segments]

    def transcribe(self, audio_file_path: str) -> List[Segment]:
        self.logger.info("Using local whisper")
        models = whisper.available_models()
        self.logger.info(f"Available models: {models}")

        model = whisper.load_model(name=self.whisper_model)

        self.logger.info("Beginning transcription")
        start = time.time()
        result = model.transcribe(audio_file_path, fp16=False, language="English")
        end = time.time()
        elapsed = end - start
        self.logger.info(f"Transcription completed in {elapsed}")
        segments = result["segments"]
        typed_segments = self.convert_to_pydantic(segments)

        return self.local_seg_to_seg(typed_segments)


class RemoteWhisperTranscriber(Transcriber):

    def __init__(self, logger: logging.Logger, config: RemoteWhisperConfig):
        self.logger = logger
        self.config = config

        self.openai_client = OpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
        )

    def transcribe(self, audio_file_path: str) -> List[Segment]:
        self.logger.info("Using remote whisper")
        audio_chunk_path = audio_file_path + "_parts"

        chunks = split_audio(Path(audio_file_path), Path(audio_chunk_path), 12 * 1024 * 1024)

        all_segments: List[TranscriptionSegment] = []

        for chunk in chunks:
            chunk_path, offset = chunk
            segments = self.get_segments_for_chunk(str(chunk_path))
            all_segments.extend(self.add_offset_to_segments(segments, offset))

        shutil.rmtree(audio_chunk_path)
        return self.convert_segments(all_segments)

    @staticmethod
    def convert_segments(segments: List[TranscriptionSegment]) -> List[Segment]:
        return [Segment(
            start=seg.start,
            end=seg.end,
            text=seg.text,
        ) for seg in segments]

    @staticmethod
    def add_offset_to_segments(segments: List[TranscriptionSegment], offset_ms: int) -> List[TranscriptionSegment]:
        offset_sec = float(offset_ms) / 1000.0
        for segment in segments:
            segment.start += offset_sec
            segment.end += offset_sec

        return segments

    def get_segments_for_chunk(self, chunk_path: str) -> List[TranscriptionSegment]:
        with open(chunk_path, "rb") as f:
            self.logger.info(f"Transcribing chunk {chunk_path}")

            transcription = self.openai_client.audio.transcriptions.create(
                model=self.config.model,
                file=f,
                timestamp_granularities=["segment"],
                language=self.config.language,
                response_format="verbose_json",
            )

            self.logger.debug("Got transcription")

            segments = transcription.segments
            assert segments is not None

            self.logger.debug(f"Got {len(segments)} segments")

            return segments


class GroqTranscriptionSegment(BaseModel):
    start: float
    end: float
    text: str


class GroqTranscriptionResponse(BaseModel):
    segments: List[GroqTranscriptionSegment]


class GroqWhisperTranscriber(Transcriber):

    def __init__(self, logger: logging.Logger, config: GroqWhisperConfig):
        self.logger = logger
        self.config = config
        self.api_url = "https://api.groq.com/openai/v1/audio/transcriptions"
        self.max_retries = 3
        self.initial_backoff = 1.0  # seconds
        self.backoff_factor = 2.0

    def transcribe(self, audio_file_path: str) -> List[Segment]:
        self.logger.info("Using Groq whisper")
        audio_chunk_path = audio_file_path + "_parts"

        chunks = split_audio(Path(audio_file_path), Path(audio_chunk_path), 24 * 1024 * 1024)

        all_segments: List[GroqTranscriptionSegment] = []

        for chunk in chunks:
            chunk_path, offset = chunk
            segments = self.get_segments_for_chunk(str(chunk_path))
            all_segments.extend(self.add_offset_to_segments(segments, offset))

        shutil.rmtree(audio_chunk_path)
        return self.convert_segments(all_segments)

    @staticmethod
    def convert_segments(segments: List[GroqTranscriptionSegment]) -> List[Segment]:
        return [Segment(
            start=seg.start,
            end=seg.end,
            text=seg.text,
        ) for seg in segments]

    @staticmethod
    def add_offset_to_segments(segments: List[GroqTranscriptionSegment],
                               offset_ms: int) -> List[GroqTranscriptionSegment]:
        offset_sec = float(offset_ms) / 1000.0
        for segment in segments:
            segment.start += offset_sec
            segment.end += offset_sec

        return segments

    def get_segments_for_chunk(self, chunk_path: str) -> List[GroqTranscriptionSegment]:
        retries = 0
        backoff_time = self.initial_backoff

        while True:
            try:
                with open(chunk_path, "rb") as f:
                    self.logger.info(f"Transcribing chunk {chunk_path}")

                    headers = {
                        "Authorization": f"Bearer {self.config.api_key}",
                    }

                    files = {
                        "file": (chunk_path, f),
                        "model": (None, self.config.model),
                        "response_format": (None, "verbose_json"),
                        "language": (None, self.config.language),
                    }

                    response = requests.post(
                        self.api_url,
                        headers=headers,
                        files=files,
                    )

                    if response.status_code != 200:
                        if retries < self.max_retries:
                            self.logger.warning(
                                f"Groq API error (attempt {retries+1}/{self.max_retries+1}): {response.status_code} - {response.text}"
                            )
                            retries += 1
                            time.sleep(backoff_time)
                            backoff_time *= self.backoff_factor
                            continue
                        else:
                            self.logger.error(f"Error with Groq API after {retries+1} attempts: {response.text}")
                            raise Exception(f"Groq API error: {response.status_code} - {response.text}")

                    response_data = response.json()
                    self.logger.debug("Got transcription")

                    # Parse the response into our model
                    if "segments" not in response_data:
                        self.logger.error(f"Unexpected response format: {response_data}")
                        return []

                    groq_segments = [GroqTranscriptionSegment(**seg) for seg in response_data["segments"]]
                    self.logger.debug(f"Got {len(groq_segments)} segments")

                    return groq_segments

            except (requests.RequestException, IOError) as e:
                if retries < self.max_retries:
                    self.logger.warning(f"Request error (attempt {retries+1}/{self.max_retries+1}): {str(e)}")
                    retries += 1
                    time.sleep(backoff_time)
                    backoff_time *= self.backoff_factor
                else:
                    self.logger.error(f"Request failed after {retries+1} attempts: {str(e)}")
                    raise
