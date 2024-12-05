import logging
import os
import re
from typing import Any, Optional

import requests
import validators
from flask import abort

from app.models import Post

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = "in"


def download_episode(post: Post) -> Optional[str]:
    download_path = get_and_make_download_path(
        post.title,
        re.sub(r"[^a-zA-Z0-9\s]", "", post.title) + ".mp3",
    )
    if not os.path.exists(download_path):
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


def get_and_make_download_path(podcast_title: str, episode_name: str) -> str:
    if not os.path.exists(f"{DOWNLOAD_DIR}/{podcast_title}"):
        os.makedirs(f"{DOWNLOAD_DIR}/{podcast_title}")
    return f"{DOWNLOAD_DIR}/{podcast_title}/{episode_name}"


def find_audio_link(entry: Any) -> str:
    for link in entry.links:
        if link.type == "audio/mpeg":
            href = link.href
            assert isinstance(href, str)
            return href

    return str(entry.id)
