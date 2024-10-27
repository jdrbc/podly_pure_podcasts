import logging
import os
from typing import Any, Optional

import requests
import validators
from flask import abort

DOWNLOAD_DIR = "in"


def download_episode(
    podcast_title: str, episode_name: str, episode_url: str
) -> Optional[str]:
    download_path = get_and_make_download_path(podcast_title, episode_name)
    if not os.path.exists(download_path):
        # Download the podcast episode
        audio_link = episode_url
        if audio_link is None or not validators.url(audio_link):
            abort(404)

        logging.info(f"Downloading {audio_link} into {download_path}...")
        response = requests.get(audio_link)  # pylint: disable=missing-timeout
        if response.status_code == 200:
            with open(download_path, "wb") as file:
                file.write(response.content)
                logging.info("Download complete.")
        else:
            logging.info(
                f"Failed to download the podcast episode, response: {response.status_code}"
            )
            return None
    else:
        logging.info("Episode already downloaded.")
    return download_path


def get_and_make_download_path(podcast_title: str, episode_name: str) -> str:
    if not os.path.exists(f"{DOWNLOAD_DIR}/{podcast_title}"):
        os.makedirs(f"{DOWNLOAD_DIR}/{podcast_title}")
    return f"{DOWNLOAD_DIR}/{podcast_title}/{episode_name}"


def find_audio_link(entry: Any) -> Optional[str]:
    for link in entry.links:
        if link.type == "audio/mpeg":
            href = link.href
            assert isinstance(href, str)
            return href

    return None
