from concurrent.futures import ThreadPoolExecutor, as_completed

from app import config, logger, scheduler
from app.feeds import refresh_feed
from app.models import Feed, Post
from app.posts import download_and_process_post


def run_refresh_all_feeds() -> None:
    """Main entry point for refreshing all feeds."""
    logger.info("run_refresh_all_feeds call")
    with scheduler.app.app_context():
        refresh_all_feeds()


def process_post(post: Post) -> None:
    """Process a single post within the app context."""
    with scheduler.app.app_context():
        try:
            logger.info(f"Processing post: {post.title} (ID: {post.id})")
            download_and_process_post(post.guid, blocking=False)
            logger.info(f"Post {post.title} (ID: {post.id}) processed successfully.")
        except Exception as e:  # pylint: disable=broad-exception-caught
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
        logger.info("All feeds refreshed and database updated.")

        # Identify new posts
        new_posts = Post.query.filter(
            Post.processed_audio_path is None, Post.whitelisted is True
        ).all()
        logger.info(f"Found {len(new_posts)} new posts to download and process.")

        if not new_posts:
            logger.info("No new posts to process.")
            return

        logger.info(f"Found {len(new_posts)} whitelisted new posts to process.")

        if not new_posts:
            logger.info("No whitelisted new posts to process.")
            return

        # Process posts in parallel using ThreadPoolExecutor
        max_workers = min(
            config.threads, len(new_posts)
        )  # Limit threads to config or number of posts
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_post = {
                executor.submit(process_post, post): post for post in new_posts
            }

            for future in as_completed(future_to_post):
                post = future_to_post[future]
                try:
                    future.result()  # Check for exceptions
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.error(f"Error processing post {post.id}: {e}")

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error(f"Error in scheduled job 'refresh_all_feeds': {e}")
