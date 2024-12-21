from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from app import config, db, logger
from app.feeds import refresh_feed
from app.models import Feed, Post
from app.routes import download_post
from global_ctx import app  # Import global app context


def run_refresh_all_feeds() -> None:
    """Main entry point for refreshing all feeds."""
    logger.info("run_refresh_all_feeds call")

    if app is None:
        raise RuntimeError("Flask application context is None")

    assert app is not None  # For mypy type checking
    with app.app_context():
        refresh_all_feeds()


def process_post(post: Post) -> None:
    """Process a single post within the app context."""
    assert app is not None  # For mypy type checking
    with app.app_context():
        try:
            logger.info(f"Processing post: {post.title} (ID: {post.id})")
            download_post(post.guid)
            logger.info(f"Post {post.title} (ID: {post.id}) processed successfully.")
        except Exception as e:
            logger.error(f"Error processing post {post.id}: {e}")


def refresh_all_feeds() -> None:
    """Refresh all feeds and process newly released episodes."""
    logger.info("Scheduled job started: Refreshing all podcast feeds.")

    try:
        # Refresh each feed
        feeds = Feed.query.all()
        logger.info(f"Found {len(feeds)} feeds to refresh.")

        for feed in feeds:
            logger.info(f"Refreshing feed: {feed.title} (ID: {feed.id})")
            refresh_feed(feed)

        db.session.commit()
        logger.info("All feeds refreshed and database updated.")

        # Identify new posts
        new_posts = Post.query.filter(Post.processed_audio_path == None).all()
        logger.info(f"Found {len(new_posts)} new posts to download and process.")

        if not new_posts:
            logger.info("No new posts to process.")
            return

        # Automatically whitelist new episodes if enabled
        if config.automatically_whitelist_new_episodes:
            for post in new_posts:
                if not post.whitelisted:
                    post.whitelisted = True

            try:
                db.session.commit()
                logger.info("All new posts have been automatically whitelisted.")
            except Exception as e:
                logger.error(f"Failed to automatically whitelist new posts: {e}")
                db.session.rollback()
                return

        # Filter posts to only process those that are whitelisted
        posts_to_process = Post.query.filter(
            Post.processed_audio_path == None, Post.whitelisted == True
        ).all()
        logger.info(f"Found {len(posts_to_process)} whitelisted new posts to process.")

        if not posts_to_process:
            logger.info("No whitelisted new posts to process.")
            return

        # Process posts in parallel using ThreadPoolExecutor
        max_workers = min(
            config.threads, len(posts_to_process)
        )  # Limit threads to config or number of posts
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_post = {
                executor.submit(process_post, post): post for post in posts_to_process
            }

            for future in as_completed(future_to_post):
                post = future_to_post[future]
                try:
                    future.result()  # Check for exceptions
                except Exception as e:
                    logger.error(f"Error processing post {post.id}: {e}")

    except Exception as e:
        logger.error(f"Error in scheduled job 'refresh_all_feeds': {e}")
