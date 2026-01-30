"""Read chapter metadata from MP3 files using ID3 CHAP frames."""

import logging
from dataclasses import dataclass
from typing import List

from mutagen.id3 import CHAP, ID3  # type: ignore[attr-defined]
from mutagen.mp3 import MP3

logger = logging.getLogger("global_logger")


@dataclass
class Chapter:
    """Represents a chapter in an audio file."""

    element_id: str
    title: str
    start_time_ms: int
    end_time_ms: int


def read_chapters(audio_path: str) -> List[Chapter]:
    """
    Read ID3 CHAP frames from an MP3 file.

    Args:
        audio_path: Path to the MP3 file

    Returns:
        List of Chapter objects, sorted by start time.
        Returns empty list if no chapters found or file has no ID3 tags.
    """
    chapters: List[Chapter] = []

    try:
        audio = MP3(audio_path, ID3=ID3)
        if audio.tags is None:
            logger.debug("No ID3 tags found in %s", audio_path)
            return []

        for _, frame in audio.tags.items():
            if not isinstance(frame, CHAP):
                continue

            element_id = frame.element_id  # type: ignore[attr-defined]
            start_time_ms = frame.start_time  # type: ignore[attr-defined]
            end_time_ms = frame.end_time  # type: ignore[attr-defined]

            # Extract title from sub-frames (TIT2)
            title = ""
            if frame.sub_frames:  # type: ignore[attr-defined]
                for sub_frame in frame.sub_frames.values():  # type: ignore[attr-defined]
                    if sub_frame.FrameID == "TIT2":
                        title = str(sub_frame.text[0]) if sub_frame.text else ""
                        break

            if not title:
                title = element_id

            chapters.append(
                Chapter(
                    element_id=element_id,
                    title=title,
                    start_time_ms=start_time_ms,
                    end_time_ms=end_time_ms,
                )
            )

        # Sort by start time
        chapters.sort(key=lambda c: c.start_time_ms)

        logger.info("Found %d chapters in %s", len(chapters), audio_path)
        for chapter in chapters:
            logger.debug(
                "  Chapter: %s (%d ms - %d ms)",
                chapter.title,
                chapter.start_time_ms,
                chapter.end_time_ms,
            )

    except Exception as e:
        logger.warning("Failed to read chapters from %s: %s", audio_path, e)
        return []

    return chapters
