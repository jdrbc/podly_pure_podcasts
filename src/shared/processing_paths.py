import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProcessingPaths:
    post_processed_audio_path: Path


def paths_from_unprocessed_path(
    unprocessed_path: str, feed_title: str
) -> ProcessingPaths:
    unprocessed_filename = Path(unprocessed_path).name
    # Sanitize feed_title to prevent illegal characters in paths
    # Keep spaces, alphanumeric. Remove others.
    sanitized_feed_title = re.sub(r"[^a-zA-Z0-9\s_.-]", "", feed_title).strip()
    # Remove any trailing dots that might result from sanitization
    sanitized_feed_title = sanitized_feed_title.rstrip(".")
    # Replace spaces with underscores for friendlier directory names
    sanitized_feed_title = re.sub(r"\s+", "_", sanitized_feed_title)

    return ProcessingPaths(
        post_processed_audio_path=Path("srv")
        / sanitized_feed_title
        / unprocessed_filename,
    )
