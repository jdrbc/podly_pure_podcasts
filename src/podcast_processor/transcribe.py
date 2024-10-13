import logging
import math
import os
import shutil
import time
from abc import ABC, abstractmethod
from typing import Any, List, Tuple

import whisper  # type: ignore[import-untyped]
from openai import OpenAI
from openai.types.audio.transcription_segment import TranscriptionSegment
from pydantic import BaseModel
from pydub import AudioSegment  # type: ignore[import-untyped]


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
    def __init__(self, logger: logging.Logger, openai_client: OpenAI):
        self.logger = logger
        self.openai_client = openai_client

    def transcribe(self, audio_file_path: str) -> List[Segment]:
        self.logger.info("Using remote whisper")
        audio_chunk_path = audio_file_path + "_parts"

        chunks = self.split_file(audio_file_path, audio_chunk_path)

        all_segments: List[TranscriptionSegment] = []

        for chunk in chunks:
            chunk_path, offset = chunk
            segments = self.get_segments_for_chunk(chunk_path)
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

    def split_file(
        self,
        audio_file_path: str,
        audio_chunk_path: str,
        chunk_size_bytes: int = 24 * 1024 * 1024,
    ) -> List[Tuple[str, int]]:

        if not os.path.exists(audio_chunk_path):
            os.makedirs(audio_chunk_path)
        audio = AudioSegment.from_mp3(audio_file_path)
        duration_ms = len(audio)
        chunk_duration_ms = (
            chunk_size_bytes / os.path.getsize(audio_file_path)
        ) * duration_ms
        chunk_duration_ms = int(chunk_duration_ms)

        num_chunks = math.ceil(duration_ms / chunk_duration_ms)
        chunks: List[Tuple[str, int]] = []

        for i in range(num_chunks):
            start_offset_ms = i * chunk_duration_ms
            end_offset_ms = (i + 1) * chunk_duration_ms
            chunk = audio[start_offset_ms:end_offset_ms]
            export_path = f"{audio_chunk_path}/{i}.mp3"
            chunk.export(export_path, format="mp3")
            chunks.append((export_path, start_offset_ms))

        return chunks

    def get_segments_for_chunk(self, chunk_path: str) -> List[TranscriptionSegment]:
        with open(chunk_path, "rb") as f:
            transcription = self.openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                timestamp_granularities=["segment"],
                language="en",
                response_format="verbose_json",
            )

            segments = transcription.segments
            assert segments is not None
            return segments
