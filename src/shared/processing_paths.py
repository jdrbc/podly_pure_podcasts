import re
from dataclasses import dataclass
from pathlib import Path

PROCESSING_DIR: str = "processing"


@dataclass
class ProcessingPaths:
    post_processed_audio_path: Path
    audio_processing_dir: Path
    classification_dir: Path


def paths_from_unprocessed_path(
    unprocessed_path: str, feed_title: str
) -> ProcessingPaths:
    unprocessed_filename = Path(unprocessed_path).name
    sanitized_feed_title = re.sub(r"[^a-zA-Z0-9\s]", "", feed_title)

    audio_processing_dir = (
        Path(PROCESSING_DIR) / sanitized_feed_title / unprocessed_filename
    )
    classification_dir = audio_processing_dir / "classification"

    return ProcessingPaths(
        post_processed_audio_path=Path("srv")
        / sanitized_feed_title
        / unprocessed_filename,
        audio_processing_dir=audio_processing_dir,
        classification_dir=classification_dir,
    )
