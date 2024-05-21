from podcast_processor.podcast_processor import PodcastProcessor, PodcastProcessorTask
from flask import Flask, request, url_for
import feedparser
import PyRSS2Gen
from logger import setup_logger
from dotenv import load_dotenv
import os
import datetime
import yaml
import logging
import requests
import time

if not os.path.exists(".env"):
    raise FileNotFoundError("No .env file found.")

load_dotenv()

app = Flask(__name__)
setup_logger("global_logger", "config/app.log")
logger = logging.getLogger("global_logger")
with open("config/config.yml", "r") as f:
    config = yaml.safe_load(f)
download_dir = "in"


@app.route("/download/<path:episode_url>")
def download(episode_url):
    podcast_title = request.args.get("podcast_title")
    episode_name = request.args.get("episode_name")
    logging.info(f"Downloading episode {episode_name} from podcast {podcast_title}...")

    download_path = download_episode(podcast_title, episode_name, episode_url)
    if download_path is None:
        return "Failed to download episode", 500
    task = PodcastProcessorTask(podcast_title, download_path, episode_name)
    processor = PodcastProcessor(config)
    output_path = processor.process(task)
    if output_path is None:
        return "Failed to process episode", 500
    with open(output_path, "rb") as file:
        return file.read()


@app.route("/rss/<path:podcast_rss>")
def rss(podcast_rss):
    url = podcast_rss
    feed = feedparser.parse(url)
    transformed_items = []
    for entry in feed.entries:
        transformed_items.append(
            PyRSS2Gen.RSSItem(
                title=entry.title,
                link=url_for(
                    "download",
                    _external=True,
                    episode_url=find_audio_link(entry),
                    podcast_title="[podly] " + feed.feed.title,
                    episode_name=entry.title,
                ),
                description=entry.description,
            )
        )
    rss = PyRSS2Gen.RSS2(
        title="[podly] " + feed.feed.title,
        link=request.url_root,
        description=feed.feed.description,
        lastBuildDate=datetime.datetime.fromtimestamp(
            time.mktime(feed.feed.updated_parsed)
        ),
        items=transformed_items,
    )
    return rss.to_xml("utf-8"), 200, {"Content-Type": "application/rss+xml"}


@app.route("/srv/<path:path>")
def basic_srv(path):
    logger.info(f'Serving file "srv/{path}"')
    if not os.path.exists(f"srv/{path}"):
        logger.error(f'File "srv/{path}" not found')
        return "File not found", 404

    with open(f"srv/{path}", "rb") as file:
        return file.read()


def download_episode(podcast_title, episode_name, episode_url):
    download_path = get_and_make_download_path(podcast_title, episode_name)
    if not os.path.exists(download_path):
        # Download the podcast episode
        audio_link = episode_url
        if audio_link is None:
            logger.error("No audio link found.")
            raise ValueError("No audio link found.")

        logger.info(f"Downloading {audio_link} into {download_path}...")
        response = requests.get(audio_link)
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
    if not os.path.exists(f"{download_dir}/{podcast_title}"):
        os.makedirs(f"{download_dir}/{podcast_title}")
    return f"{download_dir}/{podcast_title}/{episode_name}.mp3"


def find_audio_link(entry):
    for link in entry.links:
        if link.type == "audio/mpeg":
            return link.href
    return None


if __name__ == "__main__":
    if not os.path.exists("processing"):
        os.makedirs("processing")
    if not os.path.exists("in"):
        os.makedirs("in")
    if not os.path.exists("srv"):
        os.makedirs("srv")

    app.run(host="0.0.0.0", port=5001)
