from pathlib import Path
from typing import Optional

from app import config, db, logger
from app.models import Post
from podcast_processor.podcast_processor import (
    PodcastProcessor,
    get_post_processed_audio_path,
)
from shared.podcast_downloader import (
    download_episode,
    get_and_make_download_path,
    sanitize_title,
)


def remove_associated_files(post: Post) -> None:
    """
    Remove unprocessed and processed audio files associated with a post.
    Safeguarded to handle cases where paths might be None.
    """
    try:
        # Determine unprocessed and processed paths
        unprocessed_path = (
            get_and_make_download_path(post.title) if post.title else None
        )
        processing_paths = get_post_processed_audio_path(post)

        # Define absolute paths
        unprocessed_abs_path: Optional[Path] = (
            Path(unprocessed_path).resolve() if unprocessed_path else None
        )
        processed_abs_path: Optional[Path] = (
            Path(processing_paths.post_processed_audio_path).resolve()
            if processing_paths
            else None
        )

        # Remove unprocessed audio file
        if unprocessed_abs_path and unprocessed_abs_path.exists():
            try:
                unprocessed_abs_path.unlink()
                logger.info(f"Removed unprocessed audio file: {unprocessed_abs_path}")
            except OSError as e:  # pylint: disable=broad-except
                logger.error(
                    f"Failed to remove unprocessed audio file {unprocessed_abs_path}: {e}"
                )
        else:
            if unprocessed_abs_path:
                logger.debug(f"No unprocessed audio file to remove for post {post.id}.")
            else:
                logger.debug(f"Unprocessed audio path is None for post {post.id}.")

        # Remove processed audio file
        if processed_abs_path and processed_abs_path.exists():
            try:
                processed_abs_path.unlink()
                logger.info(f"Removed processed audio file: {processed_abs_path}")
            except OSError as e:  # pylint: disable=broad-except
                logger.error(
                    f"Failed to remove processed audio file {processed_abs_path}: {e}"
                )
        else:
            if processed_abs_path:
                logger.debug(f"No processed audio file to remove for post {post.id}.")
            else:
                logger.debug(f"Processed audio path is None for post {post.id}.")

    except Exception as e:  # pylint: disable=broad-except
        logger.error(
            f"Unexpected error in remove_associated_files for post {post.id}: {e}",
            exc_info=True,
        )


def download_and_process_post(p_guid: str, blocking: bool = True) -> Optional[str]:
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        logger.warning(f"Post with GUID: {p_guid} not found")
        raise PostException(f"Post with GUID: {p_guid} not found")

    if not post.whitelisted:
        logger.warning(f"Post: {post.title} is not whitelisted")
        raise PostException(f"Post with GUID: {p_guid} not whitelisted")

    logger.info(
        f"Checking database for both unprocessed & processed files for post '{post.title}'"
    )

    # ---------------------------------------------------------------------------------------
    # 1) IF unprocessed_audio_path is MISSING, try to fix from disk or else download
    # ---------------------------------------------------------------------------------------
    if post.unprocessed_audio_path is None:
        logger.debug(
            "unprocessed_audio_path is None. Checking for existing file on disk."
        )

        # Figure out the expected unprocessed path
        safe_post_title = sanitize_title(post.title)
        post_subdir = safe_post_title.replace(".mp3", "")
        expected_unprocessed_path = Path("in") / post_subdir / safe_post_title

        if (
            expected_unprocessed_path.exists()
            and expected_unprocessed_path.stat().st_size > 0
        ):
            # Found a local unprocessed file
            post.unprocessed_audio_path = str(expected_unprocessed_path.resolve())
            logger.info(
                f"Found existing unprocessed audio for post '{post.title}' at '{post.unprocessed_audio_path}'. "
                f"Updated the database path."
            )
            db.session.commit()
        else:
            # Need to do the normal download
            logger.info(f"Downloading post: {post.title}")
            download_path = download_episode(post)
            if download_path is None:
                raise PostException("Download failed")

            post.unprocessed_audio_path = download_path
            db.session.commit()

    # ---------------------------------------------------------------------------------------
    # 2) IF processed_audio_path is MISSING, try to fix from disk or else run processor
    # ---------------------------------------------------------------------------------------
    if post.processed_audio_path is None:
        logger.debug(
            "processed_audio_path is None. Checking for existing file on disk."
        )

        safe_feed_title = sanitize_title(post.feed.title)
        safe_post_title = sanitize_title(post.title)
        expected_processed_path = (
            Path("srv") / safe_feed_title / f"{safe_post_title}.mp3"
        )

        if (
            expected_processed_path.exists()
            and expected_processed_path.stat().st_size > 0
        ):
            # Found a local processed file
            post.processed_audio_path = str(expected_processed_path.resolve())
            logger.info(
                f"Found existing processed audio for post '{post.title}' at '{post.processed_audio_path}'. "
                f"Updated the database path."
            )
            db.session.commit()
        else:
            # Need to actually process the audio
            logger.info(f"Processing post: {post.title}")
            processor = PodcastProcessor(config)
            output_path = processor.process(post, blocking)
            if output_path is None:
                raise PostException("Processing failed")
            post.processed_audio_path = output_path
            db.session.commit()

    # if we get here, then the post is already completely processed and valid
    logger.info(f"Post already downloaded and validated")
    return post.processed_audio_path


class PostException(Exception):
    pass
