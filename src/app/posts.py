from pathlib import Path
from typing import Optional

from app import config, db, logger
from app.models import Post
from podcast_processor.podcast_processor import (
    PodcastProcessor,
    get_post_processed_audio_path,
)
from shared.podcast_downloader import download_episode, get_and_make_download_path


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
            except OSError as e:
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
            except OSError as e:
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


def download_and_process_post(p_guid: str, blocking: bool = True) -> str:
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        logger.warning(f"Post with GUID: {p_guid} not found")
        raise PostException(f"Post with GUID: {p_guid} not found")

    if not post.whitelisted:
        logger.warning(f"Post: {post.title} is not whitelisted")
        raise PostException(f"Post with GUID: {p_guid} not whitelisted")

    logger.info(f"Downloading post: {post.title}")

    # Download the episode
    download_path = download_episode(post)

    if download_path is None:
        raise PostException("Download failed")

    post.unprocessed_audio_path = download_path
    db.session.commit()

    # Process the episode
    processor = PodcastProcessor(config)
    output_path = processor.process(post, blocking)
    if output_path is None:
        raise PostException("Processing failed")
    return output_path


class PostException(Exception):
    pass
