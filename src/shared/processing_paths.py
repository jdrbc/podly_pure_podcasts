import re
from dataclasses import dataclass
from pathlib import Path

PROCESSING_DIR: str = "processing"


@dataclass
class ProcessingPaths:
    post_processed_audio_path: Path
    audio_processing_dir: Path
    classification_dir: Path


def paths_from_unprocessed_path(unprocessed_path: str, title: str) -> ProcessingPaths:
    filename = Path(unprocessed_path).name
    sanitized_title = re.sub(r"[^a-zA-Z0-9\s]", "", title)

    audio_processing_dir = Path(PROCESSING_DIR) / sanitized_title / filename
    classification_dir = audio_processing_dir / "classification"

    return ProcessingPaths(
        post_processed_audio_path=Path("srv") / sanitized_title / filename,
        audio_processing_dir=audio_processing_dir,
        classification_dir=classification_dir,
    )
