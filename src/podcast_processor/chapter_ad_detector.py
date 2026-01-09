"""Detect ad segments using chapter metadata filtering."""

import logging
from typing import List, Optional, Tuple

from podcast_processor.chapter_filter import filter_chapters_by_strings, parse_filter_strings
from podcast_processor.chapter_reader import Chapter, read_chapters


class ChapterDetectionError(Exception):
    """Raised when chapter-based detection fails."""

    pass


class ChapterAdDetector:
    """Detects ad segments by filtering chapters based on title strings."""

    def __init__(
        self,
        filter_strings: List[str],
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the chapter-based ad detector.

        Args:
            filter_strings: List of strings to match against chapter titles
            logger: Optional logger instance
        """
        self.filter_strings = filter_strings
        self.logger = logger or logging.getLogger("global_logger")

    @classmethod
    def from_csv(
        cls,
        filter_strings_csv: str,
        logger: Optional[logging.Logger] = None,
    ) -> "ChapterAdDetector":
        """
        Create detector from comma-separated filter strings.

        Args:
            filter_strings_csv: Comma-separated string of filter terms
            logger: Optional logger instance

        Returns:
            ChapterAdDetector instance
        """
        filter_strings = parse_filter_strings(filter_strings_csv)
        return cls(filter_strings=filter_strings, logger=logger)

    def detect(
        self,
        audio_path: str,
    ) -> Tuple[List[Tuple[float, float]], List[Chapter], List[Chapter]]:
        """
        Detect ad segments in an audio file using chapter metadata.

        Args:
            audio_path: Path to the MP3 file

        Returns:
            Tuple of:
                - List of (start_time_sec, end_time_sec) tuples for ad segments
                - List of chapters to keep
                - List of chapters to remove (ads)

        Raises:
            ChapterDetectionError: If no chapters are found in the audio file
        """
        chapters = read_chapters(audio_path)

        if not chapters:
            raise ChapterDetectionError(
                f"No chapters found in audio file: {audio_path}"
            )

        chapters_to_keep, chapters_to_remove = filter_chapters_by_strings(
            chapters=chapters,
            filter_strings=self.filter_strings,
        )

        # Convert removed chapters to time segments (in seconds)
        ad_segments: List[Tuple[float, float]] = []
        for chapter in chapters_to_remove:
            start_sec = chapter.start_time_ms / 1000.0
            end_sec = chapter.end_time_ms / 1000.0
            ad_segments.append((start_sec, end_sec))

        self.logger.info(
            "Chapter-based detection found %d ad segments from %d chapters",
            len(ad_segments),
            len(chapters),
        )

        return ad_segments, chapters_to_keep, chapters_to_remove

    def detect_ad_segments(self, audio_path: str) -> List[Tuple[float, float]]:
        """
        Detect ad segments and return only the time tuples.

        This is a simplified interface that only returns ad segments,
        discarding chapter information.

        Args:
            audio_path: Path to the MP3 file

        Returns:
            List of (start_time_sec, end_time_sec) tuples for detected ads

        Raises:
            ChapterDetectionError: If no chapters are found in the audio file
        """
        ad_segments, _, _ = self.detect(audio_path)
        return ad_segments
