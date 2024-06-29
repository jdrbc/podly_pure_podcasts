from podcast_processor.podcast_processor import PodcastProcessor, PodcastProcessorTask
from flask import Flask, request, url_for, abort
from waitress import serve
import feedparser
import PyRSS2Gen
import validators
from logger import setup_logger
from dotenv import dotenv_values
import os
import datetime
import yaml
import logging
import requests
import re
import time
from zeroconf import ServiceInfo, Zeroconf
import threading
import socket
import urllib.parse

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
download_dir = "in"


@app.get("/download/<path:episode_name>")
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
    with open(output_path, "rb") as file:
        return file.read()


def get_args(full_request_url):
    args = urllib.parse.parse_qs(
        urllib.parse.urlparse(full_request_url.replace(PARAM_SEP, "&")).query
    )
    return args["podcast_title"][0], args["episode_url"][0]


def fix_url(url):
    return re.sub(r"(http(s)?):/([^/])", r"\1://\3", url)


@app.get("/<path:podcast_rss>")
def rss(podcast_rss):
    url = fix_url(podcast_rss)
    if not validators.url(url):
        abort(404)
    feed = feedparser.parse(url)
    transformed_items = []
    for entry in feed.entries:
        dl_link = get_download_link(entry, feed.feed.title)
        transformed_items.append(
            PyRSS2Gen.RSSItem(
                title=entry.title,
                link=dl_link,
                description=entry.description,
                guid=PyRSS2Gen.Guid(dl_link),
                pubDate=datetime.datetime(*entry.published_parsed[:6]),
            )
        )
    rss = PyRSS2Gen.RSS2(
        title="[podly] " + feed.feed.title,
        link=request.url_root,
        description=feed.feed.description,
        lastBuildDate=datetime.datetime.now(),
        items=transformed_items,
    )
    return rss.to_xml("utf-8"), 200, {"Content-Type": "application/rss+xml"}


def get_download_link(entry, podcast_title):
    return (
        (env["SERVER"] if "SERVER" in env else "")
        + url_for(
            "download",
            episode_name=f"{remove_odd_characters(entry.title)}.mp3",
            _external="SERVER" not in env,
        )
        + f"?podcast_title={urllib.parse.quote('[podly] ' + remove_odd_characters(podcast_title))}"
        + f"{PARAM_SEP}episode_url={urllib.parse.quote(find_audio_link(entry))}"
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
    return f"{download_dir}/{podcast_title}/{episode_name}"


def find_audio_link(entry):
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
        threads=int(env["THREADS"] if "THREADS" in env else 1),
        port=int(env["SERVER_PORT"]) if "SERVER_PORT" in env else 5001,
    )
