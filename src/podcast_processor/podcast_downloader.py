import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

import requests
import validators
from flask import abort

from app.models import Post

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = "in"


class PodcastDownloader:
    """
    Handles downloading podcast episodes with robust file checking and path management.
    """

    def __init__(
        self, download_dir: str = DOWNLOAD_DIR, logger: Optional[logging.Logger] = None
    ):
        self.download_dir = download_dir
        self.logger = logger or logging.getLogger(__name__)

    def download_episode(self, post: Post, dest_path: str) -> Optional[str]:
        """
        Download a podcast episode if it doesn't already exist.

        Args:
            post: The Post object containing the podcast episode to download

        Returns:
            Path to the downloaded file, or None if download failed
        """
        # Destination is required; ensure parent directory exists
        download_path = dest_path
        Path(download_path).parent.mkdir(parents=True, exist_ok=True)
        if not download_path:
            self.logger.error(f"Invalid download path for post {post.id}")
            return None

        # First, check if the file truly exists and has nonzero size.
        try:
            if os.path.isfile(download_path) and os.path.getsize(download_path) > 0:
                self.logger.info("Episode already downloaded.")
                return download_path
            self.logger.info("File is zero bytes, re-downloading.")  # else

        except FileNotFoundError:
            # Covers both "file actually missing" and "broken symlink"
            pass

        # If we get here, the file is missing or zero bytes -> perform download
        audio_link = post.download_url
        if audio_link is None or not validators.url(audio_link):
            abort(404)

        self.logger.info(f"Downloading {audio_link} into {download_path}...")
        response = requests.get(audio_link)  # pylint: disable=missing-timeout
        if response.status_code == 200:
            with open(download_path, "wb") as file:
                file.write(response.content)
                self.logger.info("Download complete.")
        else:
            self.logger.info(
                f"Failed to download the podcast episode, response: {response.status_code}"
            )
            return None

        return download_path

    def get_and_make_download_path(self, post_title: str) -> Path:
        """
        Generate the download path for a post and create necessary directories.

        Args:
            post_title: The title of the post to generate a path for

        Returns:
            Path object for the download location
        """
        sanitized_title = sanitize_title(post_title)

        post_directory = sanitized_title
        post_filename = sanitized_title + ".mp3"

        post_directory_path = Path(self.download_dir) / post_directory

        post_directory_path.mkdir(parents=True, exist_ok=True)

        return post_directory_path / post_filename


def sanitize_title(title: str) -> str:
    """Sanitize a title for use in file paths."""
    return re.sub(r"[^a-zA-Z0-9\s]", "", title)


def find_audio_link(entry: Any) -> str:
    """Find the audio link in a feed entry."""
    for link in entry.links:
        if link.type == "audio/mpeg":
            href = link.href
            assert isinstance(href, str)
            return href

    return str(entry.id)


# Backward compatibility - create a default instance
_default_downloader = PodcastDownloader()


def download_episode(post: Post, dest_path: str) -> Optional[str]:
    return _default_downloader.download_episode(post, dest_path)


def get_and_make_download_path(post_title: str) -> Path:
    return _default_downloader.get_and_make_download_path(post_title)
