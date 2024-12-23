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
    if not os.path.exists(download_path) or os.path.getsize(download_path) == 0:
        # Download the podcast episode
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
    else:
        logger.info("Episode already downloaded.")
    return download_path


def get_and_make_download_path(post_title: str) -> Path:
    sanitized_title = re.sub(r"[^a-zA-Z0-9\s]", "", post_title)

    post_directory = sanitized_title
    post_filename = sanitized_title + ".mp3"

    post_directory_path = Path(DOWNLOAD_DIR) / post_directory

    post_directory_path.mkdir(parents=True, exist_ok=True)

    return post_directory_path / post_filename

def find_audio_link(entry: Any) -> str:
    for link in entry.links:
        if link.type == "audio/mpeg":
            href = link.href
            assert isinstance(href, str)
            return href

    return str(entry.id)
