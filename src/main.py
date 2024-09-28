import datetime
import logging
import os
import re
import threading
import urllib.parse
from pathlib import Path
from typing import Any, Optional, cast

import feedparser  # type: ignore[import-untyped]
import PyRSS2Gen  # type: ignore[import-untyped]
import requests
import validators
import yaml
from dotenv import dotenv_values
from flask import Flask, abort, request, send_file, url_for
from waitress import serve

from logger import setup_logger
from podcast_processor.podcast_processor import PodcastProcessor, PodcastProcessorTask

if not os.path.exists(".env"):
    raise FileNotFoundError("No .env file found.")

PARAM_SEP = "PODLYPARAMSEP"  # had some issues with ampersands in the URL

env = dotenv_values(".env")

stop = threading.Event()

app = Flask(__name__)
setup_logger("global_logger", "config/app.log")
logger = logging.getLogger("global_logger")
with open("config/config.yml", "r") as f:
    config = yaml.safe_load(f)
DOWNLOAD_DIR = "in"


@app.route("/download/<path:episode_name>")
def download(episode_name):
    episode_name = urllib.parse.unquote(episode_name)
    podcast_title, episode_url = get_args(request.url)
    logging.info(f"Downloading episode {episode_name} from podcast {podcast_title}...")
    if episode_url is None or not validators.url(episode_url):
        return "Invalid episode URL", 404

    download_path = download_episode(podcast_title, episode_name, episode_url)
    if download_path is None:
        return "Failed to download episode", 500
    task = PodcastProcessorTask(podcast_title, download_path, episode_name)
    processor = PodcastProcessor(config)
    output_path = processor.process(task)
    if output_path is None:
        return "Failed to process episode", 500

    try:
        return send_file(path_or_file=Path(output_path).resolve())
    except Exception as e:  # pylint: disable=broad-exception-caught
        logging.error(f"Error sending file: {e}")
        return "Error sending file", 500


def get_args(full_request_url):
    args = urllib.parse.parse_qs(
        urllib.parse.urlparse(full_request_url.replace(PARAM_SEP, "&")).query
    )
    return args["podcast_title"][0], args["episode_url"][0]


def fix_url(url):
    url = re.sub(r"(http(s)?):/([^/])", r"\1://\3", url)
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url


@app.get("/<path:podcast_rss>")
def rss(podcast_rss):
    logging.info(f"getting rss for {podcast_rss}...")
    if podcast_rss == "favicon.ico":
        abort(404)
    if podcast_rss in config["podcasts"]:
        url = config["podcasts"][podcast_rss]
    else:
        url = fix_url(podcast_rss)
    if not validators.url(url):
        abort(404)
    feed = feedparser.parse(url)
    feed = cast(feedparser.FeedParserDict, feed)
    if "feed" not in feed or "title" not in feed.feed:
        abort(404)
    transformed_items = []
    for entry in feed.entries:
        dl_link = get_download_link(entry, feed.feed.title)
        if dl_link is None:
            continue

        transformed_items.append(
            PyRSS2Gen.RSSItem(
                title=entry.title,
                link=dl_link,
                description=entry.description,
                guid=PyRSS2Gen.Guid(dl_link),
                enclosure=PyRSS2Gen.Enclosure(
                    dl_link,
                    str(entry.get("enclosures", [{}])[0].get("length", 0)),
                    "audio/mp3",
                ),
                pubDate=datetime.datetime(*entry.published_parsed[:6]),
            )
        )
    rss_feed = PyRSS2Gen.RSS2(
        title="[podly] " + feed.feed.title,
        link=request.url_root,
        description=feed.feed.description,
        lastBuildDate=datetime.datetime.now(),
        items=transformed_items,
    )
    return rss_feed.to_xml("utf-8"), 200, {"Content-Type": "application/xml"}


def get_download_link(entry: Any, podcast_title: str) -> Optional[str]:
    audio_link = find_audio_link(entry)
    if audio_link is None:
        return None

    return (
        (env["SERVER"] if "SERVER" in env and env["SERVER"] is not None else "")
        + url_for(
            "download",
            episode_name=f"{remove_odd_characters(entry.title)}.mp3",
            _external="SERVER" not in env,
        )
        + f"?podcast_title={urllib.parse.quote('[podly] ' + remove_odd_characters(podcast_title))}"
        + f"{PARAM_SEP}episode_url={urllib.parse.quote(audio_link)}"
    )


def remove_odd_characters(title):
    return re.sub(r"[^a-zA-Z0-9\s]", "", title)


def download_episode(podcast_title, episode_name, episode_url):
    download_path = get_and_make_download_path(podcast_title, episode_name)
    if not os.path.exists(download_path):
        # Download the podcast episode
        audio_link = fix_url(episode_url)
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


def get_and_make_download_path(podcast_title, episode_name):
    if not os.path.exists(f"{DOWNLOAD_DIR}/{podcast_title}"):
        os.makedirs(f"{DOWNLOAD_DIR}/{podcast_title}")
    return f"{DOWNLOAD_DIR}/{podcast_title}/{episode_name}"


def find_audio_link(entry) -> Optional[str]:
    for link in entry.links:
        if link.type == "audio/mpeg":
            return link.href

    return None


if __name__ == "__main__":
    for key in env:
        if key == "OPENAI_API_KEY":
            logger.info(f"{key}: ********")
        else:
            logger.info(f"{key}: {env[key]}")

    if not os.path.exists("processing"):
        os.makedirs("processing")
    if not os.path.exists("in"):
        os.makedirs("in")
    if not os.path.exists("srv"):
        os.makedirs("srv")

    serve(
        app,
        host="0.0.0.0",
        threads=(
            int(env["THREADS"])
            if "THREADS" in env and env["THREADS"] is not None
            else 1
        ),
        port=(
            int(env["SERVER_PORT"])
            if "SERVER_PORT" in env and env["SERVER_PORT"] is not None
            else 5001
        ),
    )
