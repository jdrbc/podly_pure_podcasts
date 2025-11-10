import os
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
    # Limit length to prevent path too long errors
    max_length = 100  # Conservative limit for directory name
    if len(sanitized_feed_title) > max_length:
        sanitized_feed_title = sanitized_feed_title[:max_length].rstrip("_")

    return ProcessingPaths(
        post_processed_audio_path=get_srv_root()
        / sanitized_feed_title
        / unprocessed_filename,
    )


def get_job_unprocessed_path(post_guid: str, job_id: str, post_title: str) -> Path:
    """Return a unique per-job path for the unprocessed audio file.

    Layout: in/jobs/{post_guid}/{job_id}/{sanitized_title}.mp3
    """
    # Keep same sanitization behavior used for download filenames
    sanitized_title = re.sub(r"[^a-zA-Z0-9\s]", "", post_title).strip()
    # Replace multiple spaces with single space
    sanitized_title = re.sub(r"\s+", " ", sanitized_title)
    # Limit length to prevent filename too long errors
    max_length = 100  # Conservative limit for filename
    if len(sanitized_title) > max_length:
        sanitized_title = sanitized_title[:max_length].rstrip()
    return get_in_root() / "jobs" / post_guid / job_id / f"{sanitized_title}.mp3"


# ---- New centralized data-root helpers ----


def get_instance_dir() -> Path:
    """Absolute instance directory inside the container.

    Defaults to /app/src/instance. Can be overridden via PODLY_INSTANCE_DIR for tests.
    """
    return Path(os.environ.get("PODLY_INSTANCE_DIR", "/app/src/instance"))


def get_base_podcast_data_dir() -> Path:
    """Root under which podcasts (in/srv) live, e.g., /app/src/instance/data."""
    return Path(
        os.environ.get("PODLY_PODCAST_DATA_DIR", str(get_instance_dir() / "data"))
    )


def get_in_root() -> Path:
    return get_base_podcast_data_dir() / "in"


def get_srv_root() -> Path:
    return get_base_podcast_data_dir() / "srv"
