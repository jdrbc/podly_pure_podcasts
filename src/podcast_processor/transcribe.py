import logging
import shutil
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List

import whisper  # type: ignore[import-untyped]
from groq import APIError, Groq
from openai import OpenAI
from openai.types.audio.transcription_segment import TranscriptionSegment
from pydantic import BaseModel

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
    def convert_to_pydantic(
        transcript_data: List[Any],
    ) -> List[LocalTranscriptSegment]:
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

        chunks = split_audio(
            Path(audio_file_path), Path(audio_chunk_path), 24 * 1024 * 1024
        )

        all_segments: List[TranscriptionSegment] = []

        for chunk in chunks:
            chunk_path, offset = chunk
            segments = self.get_segments_for_chunk(str(chunk_path))
            all_segments.extend(self.add_offset_to_segments(segments, offset))

        shutil.rmtree(audio_chunk_path)
        return self.convert_segments(all_segments)

    @staticmethod
    def convert_segments(segments: List[TranscriptionSegment]) -> List[Segment]:
        return [
            Segment(
                start=seg.start,
                end=seg.end,
                text=seg.text,
            )
            for seg in segments
        ]

    @staticmethod
    def add_offset_to_segments(
        segments: List[TranscriptionSegment], offset_ms: int
    ) -> List[TranscriptionSegment]:
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


class GroqWhisperTranscriber(Transcriber):

    def __init__(self, logger: logging.Logger, config: GroqWhisperConfig):
        self.logger = logger
        self.config = config
        self.client = Groq(
            api_key=config.api_key,
            max_retries=config.max_retries,
        )

    def transcribe(self, audio_file_path: str) -> List[Segment]:
        self.logger.info("Using Groq whisper")
        audio_chunk_path = audio_file_path + "_parts"

        chunks = split_audio(
            Path(audio_file_path), Path(audio_chunk_path), 12 * 1024 * 1024
        )

        all_segments: List[GroqTranscriptionSegment] = []

        for chunk in chunks:
            chunk_path, offset = chunk
            segments = self.get_segments_for_chunk(str(chunk_path))
            all_segments.extend(self.add_offset_to_segments(segments, offset))

        shutil.rmtree(audio_chunk_path)
        return self.convert_segments(all_segments)

    @staticmethod
    def convert_segments(segments: List[GroqTranscriptionSegment]) -> List[Segment]:
        return [
            Segment(
                start=seg.start,
                end=seg.end,
                text=seg.text,
            )
            for seg in segments
        ]

    @staticmethod
    def add_offset_to_segments(
        segments: List[GroqTranscriptionSegment], offset_ms: int
    ) -> List[GroqTranscriptionSegment]:
        offset_sec = float(offset_ms) / 1000.0
        for segment in segments:
            segment.start += offset_sec
            segment.end += offset_sec

        return segments

    def get_segments_for_chunk(self, chunk_path: str) -> List[GroqTranscriptionSegment]:
        try:
            self.logger.info(f"Transcribing chunk {chunk_path} using groq client")
            transcription = self.client.audio.transcriptions.create(
                file=Path(chunk_path),
                model=self.config.model,
                response_format="verbose_json",  # Ensure segments are included
                language=self.config.language,
            )
            self.logger.debug("Got transcription from groq client")

            if transcription.segments is None:  # type: ignore [attr-defined]
                self.logger.warning(
                    f"No segments found in transcription for {chunk_path}"
                )
                return []

            groq_segments = [
                GroqTranscriptionSegment(
                    start=seg["start"], end=seg["end"], text=seg["text"]
                )
                for seg in transcription.segments  # type: ignore [attr-defined]
            ]

            self.logger.debug(f"Got {len(groq_segments)} segments")
            return groq_segments

        except APIError as e:
            self.logger.error(
                f"Groq API error after retries for chunk {chunk_path}: {e.message}"
            )
            raise Exception(f"Groq API transcription failed: {e.message}") from e
        except Exception as e:
            self.logger.error(
                f"An unexpected error occurred during transcription for chunk {chunk_path}: {str(e)}"
            )
            raise Exception("An unexpected error occurred during transcription.") from e
