from flask_apscheduler import APScheduler  # type: ignore
from waitress import serve

import global_ctx  # global context, death to flask app context errors
from app import config, create_app, db, logger
from app.feeds import add_or_refresh_feed
from app.models import Feed
from app.jobs import run_refresh_all_feeds

def port_over_old_feeds() -> None:
    """Port over feeds from old configuration."""
    assert global_ctx.app is not None, "Flask application context is None"  # what?
    with global_ctx.app.app_context():
        if config.podcasts is None:
            return
        for podcast, url in config.podcasts.items():
            if not Feed.query.filter_by(rss_url=url).first():
                feed = add_or_refresh_feed(url)
                feed.alt_id = podcast
                logger.info(f"Added feed {feed.title} with alt_id {podcast}")
                db.session.add(feed)
        db.session.commit()


def setup_scheduler() -> None:

    global_ctx.scheduler = APScheduler()
    assert global_ctx.scheduler is not None, "Scheduler failed to initialize"
    assert global_ctx.app is not None, "Flask application context is None"

    global_ctx.scheduler.init_app(global_ctx.app)
    global_ctx.scheduler.start()

    global_ctx.scheduler.add_job(
        id="refresh_all_feeds",
        func=run_refresh_all_feeds,
        trigger="interval",
        minutes=config.update_interval_minutes,
        replace_existing=True,
    )


def main() -> None:

    global_ctx.app = create_app()

    if global_ctx.app is None:
        raise RuntimeError(
            "Failed to initialize the Flask application in global context"
        )

    assert global_ctx.app is not None, "Flask application context is None"

    """Main entry point for the application."""
    if config.enable_background_scheduler:
        logger.info(f"Background scheduler is enabled with {config.threads} thread(s).")
        setup_scheduler()
    else:
        logger.info("Background scheduler is disabled by configuration.")

    # Port over old feeds if needed
    port_over_old_feeds()

    # Start the application server
    serve(
        global_ctx.app,
        host="0.0.0.0",
        threads=config.threads,
        port=config.server_port,
    )


if __name__ == "__main__":
    main()
