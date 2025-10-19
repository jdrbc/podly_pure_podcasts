import logging
from pathlib import Path
from typing import Optional

from app.extensions import db
from app.models import Identification, ModelCall, Post, ProcessingJob, TranscriptSegment
from podcast_processor.podcast_downloader import get_and_make_download_path
from podcast_processor.podcast_processor import get_post_processed_audio_path

logger = logging.getLogger("global_logger")


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


def clear_post_processing_data(post: Post) -> None:
    """
    Clear all processing data for a post including:
    - Audio files (unprocessed and processed)
    - Database entries (transcript segments, identifications, model calls, processing jobs)
    - Reset relevant post fields
    """
    try:
        logger.info(
            f"Starting to clear processing data for post: {post.title} (ID: {post.id})"
        )

        # Remove audio files first
        remove_associated_files(post)

        # Get segment IDs for this post to delete related identifications
        segment_ids = [
            row[0]
            for row in db.session.query(TranscriptSegment.id)
            .filter_by(post_id=post.id)
            .all()
        ]

        if segment_ids:
            # Delete identifications that reference these segments
            db.session.query(Identification).filter(
                Identification.transcript_segment_id.in_(segment_ids)
            ).delete(synchronize_session=False)
            logger.info(f"Deleted identifications for post {post.id}")

        # Delete transcript segments for this post
        db.session.query(TranscriptSegment).filter_by(post_id=post.id).delete(
            synchronize_session=False
        )
        logger.info(f"Deleted transcript segments for post {post.id}")

        # Delete model calls for this post
        db.session.query(ModelCall).filter_by(post_id=post.id).delete(
            synchronize_session=False
        )
        logger.info(f"Deleted model calls for post {post.id}")

        # Delete processing jobs for this post
        db.session.query(ProcessingJob).filter_by(post_guid=post.guid).delete(
            synchronize_session=False
        )
        logger.info(f"Deleted processing jobs for post {post.id}")

        # Reset post audio paths and duration
        post.unprocessed_audio_path = None
        post.processed_audio_path = None
        post.duration = None

        # Commit all changes
        db.session.commit()

        logger.info(
            f"Successfully cleared all processing data for post: {post.title} (ID: {post.id})"
        )

    except Exception as e:
        logger.error(
            f"Error clearing processing data for post {post.id}: {e}",
            exc_info=True,
        )
        db.session.rollback()
        raise PostException(f"Failed to clear processing data: {str(e)}") from e


class PostException(Exception):
    pass
