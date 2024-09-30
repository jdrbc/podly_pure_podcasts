import logging
import math
import os
import shutil
from abc import ABC, abstractmethod
from typing import List, Tuple

from openai import OpenAI
from openai.types.audio.transcription_segment import TranscriptionSegment
from pydub import AudioSegment  # type: ignore[import-untyped]


class Transcriber(ABC):
    @abstractmethod
    def transcribe(self, path: str) -> List[TranscriptionSegment]:
        pass


class RemoteWhisperTranscriber(Transcriber):
    def __init__(self, logger: logging.Logger, openai_client: OpenAI):
        self.logger = logger
        self.openai_client = openai_client

    def transcribe(self, audio_file_path: str) -> List[TranscriptionSegment]:
        self.logger.info("Using remote whisper")
        audio_chunk_path = audio_file_path + "_parts"

        chunks = self.split_file(audio_file_path, audio_chunk_path)

        all_segments = []

        for chunk in chunks:
            chunk_path, offset = chunk
            segments = self.get_segments_for_chunk(chunk_path)
            all_segments.extend(self.add_offset_to_segments(segments, offset))

        shutil.rmtree(audio_chunk_path)
        return all_segments

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
