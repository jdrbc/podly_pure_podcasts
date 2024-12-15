import os

# Configure ffmpeg threading
num_processors = os.cpu_count()
os.environ["PYDUB_FFMPEG_BINARY"] = f"ffmpeg -threads {num_processors}"
print(f"Set PYDUB_FFMPEG_BINARY to use ffmpeg with {num_processors} threads.")

from waitress import serve

from app import config, create_app, db, logger
from app.feeds import add_or_refresh_feed
from app.models import Feed

app = create_app()


def port_over_old_feeds() -> None:
    with app.app_context():
        if config.podcasts is None:
            return
        for podcast, url in config.podcasts.items():
            if not Feed.query.filter_by(rss_url=url).first():
                feed = add_or_refresh_feed(url)
                feed.alt_id = podcast
                logger.info(f"Added feed {feed.title} with alt_id {podcast}")
                db.session.add(feed)
            db.session.commit()


def main() -> None:
    port_over_old_feeds()
    serve(
        app,
        host="0.0.0.0",
        threads=config.threads,
        port=config.server_port,
    )


if __name__ == "__main__":
    main()
