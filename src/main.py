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

if not os.path.exists(".env"):
    raise FileNotFoundError("No .env file found.")

env = dotenv_values(".env")

stop = threading.Event()

app = Flask(__name__)
setup_logger("global_logger", "config/app.log")
logger = logging.getLogger("global_logger")
with open("config/config.yml", "r") as f:
    config = yaml.safe_load(f)
download_dir = "in"


@app.get("/download/<path:episode_url>")
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


def fix_url(url):
    pattern = r"(http(s)?):/([^/])"
    replacement = r"\1://\3"
    output_string = re.sub(pattern, replacement, url)
    return output_string


@app.get("/<path:podcast_rss>")
def rss(podcast_rss):
    url = podcast_rss
    url = fix_url(url)
    if not validators.url(url):
        abort(404)
    feed = feedparser.parse(url)
    transformed_items = []
    for entry in feed.entries:
        transformed_items.append(
            PyRSS2Gen.RSSItem(
                title=entry.title,
                link=get_download_link(entry, feed.feed.title),
                description=entry.description,
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
    return (env["SERVER"] if "SERVER" in env else "") + url_for(
        "download",
        _external="SERVER" not in env,
        episode_url=find_audio_link(entry),
        podcast_title="[podly] " + podcast_title,
        episode_name=entry.title,
    )


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
    return f"{download_dir}/{podcast_title}/{episode_name}.mp3"


def find_audio_link(entry):
    for link in entry.links:
        if link.type == "audio/mpeg":
            return link.href
    return None


def get_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = "127.0.0.1"
    finally:
        s.close()
    return IP


def register_mdns_service():
    info = ServiceInfo(
        "_http._tcp.local.",
        "Podly._http._tcp.local.",
        addresses=[socket.inet_aton(get_ip_address())],
        port=int(env["SERVER_PORT"]) if "SERVER_PORT" in env else 5001,
        properties={"path": "/"},
        server="podly.local.",
    )

    zeroconf = Zeroconf()
    zeroconf.register_service(info)
    try:
        while not stop.is_set():
            time.sleep(1)
    finally:
        print("Unregistering...")
        zeroconf.unregister_service(info)
        zeroconf.close()


if __name__ == "__main__":
    if not os.path.exists("processing"):
        os.makedirs("processing")
    if not os.path.exists("in"):
        os.makedirs("in")
    if not os.path.exists("srv"):
        os.makedirs("srv")
    # Start a new thread for the mDNS service registration
    thread = threading.Thread(target=register_mdns_service)
    thread.start()
    try:
        serve(
            app,
            host="0.0.0.0",
            port=int(env["SERVER_PORT"]) if "SERVER_PORT" in env else 5001,
        )
    except KeyboardInterrupt:
        stop.set()
        thread.join()
