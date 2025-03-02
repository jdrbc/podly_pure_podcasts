import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

from app import config, db, logger, scheduler
from app.feeds import refresh_feed
from app.models import Feed, Post
from app.posts import download_and_process_post, remove_associated_files
from app.timeout_decorator import TimeoutException, timeout_decorator


def run_refresh_all_feeds() -> None:
    """Main entry point for refreshing all feeds."""
    logger.info("run_refresh_all_feeds call")
    with scheduler.app.app_context():
        refresh_all_feeds()


@timeout_decorator(config.job_timeout)
def process_post(post: Post) -> None:
    """Process a single post within the app context."""
    with scheduler.app.app_context():
        try:
            logger.info(f"Processing post: {post.title} (ID: {post.id})")

            # **Cleanup Step:** Remove existing associated files
            # (resolves partial processes getting stuck)
            remove_associated_files(post)

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

        # Identify and Handle Inconsistent Posts
        inconsistent_posts = Post.query.filter(
            Post.whitelisted,
            (
                (Post.unprocessed_audio_path.isnot(None))
                | (Post.processed_audio_path.isnot(None))
            ),
        ).all()
        logger.info(f"Checking {len(inconsistent_posts)} for file integrity...")

        clean_inconsistent_posts(inconsistent_posts)

        # Identify new posts
        new_posts = Post.query.filter(
            Post.processed_audio_path.is_(None), Post.whitelisted
        ).all()
        logger.info(
            f"Found {len(new_posts)} whitelisted new posts to download and process."
        )

        if not new_posts:
            logger.info("No new posts to process.")
            return

        logger.info("Checking for stale jobs...")

        # Preemptively delete files for posts with processed_audio_path == None
        clean_download_paths(new_posts)

        # Process posts in parallel using ThreadPoolExecutor
        max_workers = min(
            config.threads, len(new_posts)
        )  # Limit threads to config or number of posts
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_post = {
                executor.submit(process_post, post): post
                for post in new_posts
                if post.download_url
            }

            for future in as_completed(future_to_post):
                post = future_to_post[future]
                try:
                    future.result()  # Check for exceptions
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.error(f"Error processing post {post.id}: {e}")

    except TimeoutException as te:
        logger.error(f"Job timed out: {te}")

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error(f"Error in scheduled job 'refresh_all_feeds': {e}")


def clean_download_paths(posts: List[Post]) -> None:
    for post in posts:
        clean_download_path(post)


def clean_download_path(post: Post) -> None:
    if not post.download_url:
        logger.error(f"Skipping Post ID {post.id}: Download URL is missing.")
        return
    download_path = post.unprocessed_audio_path  # Retrieve download path for each post
    if (
        post.processed_audio_path is None
        and download_path is not None
        and os.path.exists(download_path)
    ):
        try:
            os.remove(download_path)
            logger.info(
                f"Deleted existing file at {download_path} for post '{post.title}'\
                     (ID: {post.id}) because processed_audio_path is None."
            )
        except OSError as e:
            logger.error(
                f"Error deleting file {download_path} for post '{post.title}' (ID: {post.id}): {e}",
                exc_info=True,
            )


def clean_inconsistent_posts(posts: List[Post]) -> None:
    for post in posts:
        clean_post(post)


def clean_post(post: Post) -> None:
    try:
        # Determine if processed_audio_path needs to be reset
        if post.processed_audio_path and not os.path.exists(post.processed_audio_path):
            logger.warning(
                f"Processed audio file missing for post '{post.title}'\
                     (ID: {post.id}): {post.processed_audio_path}"
            )
            post.processed_audio_path = None
            db.session.commit()

        # Determine if unprocessed_audio_path needs to be reset
        if post.unprocessed_audio_path and not os.path.exists(
            post.unprocessed_audio_path
        ):
            logger.warning(
                f"Unprocessed audio file missing for post '{post.title}'\
                     (ID: {post.id}): {post.unprocessed_audio_path}"
            )
            post.unprocessed_audio_path = None
            db.session.commit()
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error(
            f"Failed to reset fields for post '{post.title}' (ID: {post.id}): {e}",
            exc_info=True,
        )
