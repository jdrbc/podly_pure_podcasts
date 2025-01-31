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


def download_episode(post: Post) -> Optional[str]:
    download_path = str(get_and_make_download_path(post.title))
    if not download_path:
        logger.error(f"Invalid download path for post {post.id}")
        return None

    # First, check if the file truly exists and has nonzero size.
    try:
        if os.path.isfile(download_path) and os.path.getsize(download_path) > 0:
            logger.info("Episode already downloaded.")
            return download_path
        else:
            logger.info("File is zero bytes, re-downloading.")
    except FileNotFoundError:
        # Covers both “file actually missing” and “broken symlink”
        pass

    # If we get here, the file is missing or zero bytes -> perform download
    audio_link = post.download_url
    if audio_link is None or not validators.url(audio_link):
        abort(404)

    logger.info(f"Downloading {audio_link} into {download_path}...")
    response = requests.get(audio_link)  # pylint: disable=missing-timeout
    if response.status_code == 200:
        with open(download_path, "wb") as file:
            file.write(response.content)
            logger.info("Download complete.")
    else:
        logger.info(
            f"Failed to download the podcast episode, response: {response.status_code}"
        )
        return None

    return download_path


def get_and_make_download_path(post_title: str) -> Path:
    # sanitized_title = re.sub(r"[^a-zA-Z0-9\s]", "", post_title)
    sanitized_title = sanitize_title(
        post_title
    )  # need logic in multiple places, needs to be consistent

    post_directory = sanitized_title
    post_filename = sanitized_title + ".mp3"

    post_directory_path = Path(DOWNLOAD_DIR) / post_directory

    post_directory_path.mkdir(parents=True, exist_ok=True)

    return post_directory_path / post_filename


def sanitize_title(title: str) -> str:
    return re.sub(r"[^a-zA-Z0-9\s]", "", title)


def find_audio_link(entry: Any) -> str:
    for link in entry.links:
        if link.type == "audio/mpeg":
            href = link.href
            assert isinstance(href, str)
            return href

    return str(entry.id)
