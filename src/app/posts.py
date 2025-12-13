import logging
from pathlib import Path
from typing import Optional

from app.db_concurrency import commit_with_profile, pessimistic_write_lock
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

        # If we couldn't derive the processed path from unprocessed path,
        # try using the stored processed_audio_path directly
        if processed_abs_path is None and post.processed_audio_path:
            processed_abs_path = Path(post.processed_audio_path).resolve()

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

        def _chunked_delete_segments(batch_size: int = 500) -> None:
            """Chunk deletes to shorten lock hold time."""
            while True:
                ids_batch = [
                    row[0]
                    for row in db.session.query(TranscriptSegment.id)
                    .filter_by(post_id=post.id)
                    .limit(batch_size)
                    .all()
                ]
                if not ids_batch:
                    break

                db.session.query(Identification).filter(
                    Identification.transcript_segment_id.in_(ids_batch)
                ).delete(synchronize_session=False)

                db.session.query(TranscriptSegment).filter(
                    TranscriptSegment.id.in_(ids_batch)
                ).delete(synchronize_session=False)

        # Use pessimistic lock for the multi-delete operation to avoid "database is locked"
        with pessimistic_write_lock():
            _chunked_delete_segments()
            logger.info(
                f"Deleted transcript segments and identifications for post {post.id}"
            )

            # Delete model calls for this post in batches
            while True:
                model_call_ids = [
                    row[0]
                    for row in db.session.query(ModelCall.id)
                    .filter_by(post_id=post.id)
                    .limit(500)
                    .all()
                ]
                if not model_call_ids:
                    break
                db.session.query(ModelCall).filter(
                    ModelCall.id.in_(model_call_ids)
                ).delete(synchronize_session=False)
                commit_with_profile(
                    db.session,
                    must_succeed=False,
                    context="clear_post_model_calls",
                    logger_obj=logger,
                )
            logger.info(f"Deleted model calls for post {post.id}")

            # Delete processing jobs for this post in batches
            while True:
                job_ids = [
                    row[0]
                    for row in db.session.query(ProcessingJob.id)
                    .filter_by(post_guid=post.guid)
                    .limit(500)
                    .all()
                ]
                if not job_ids:
                    break
                db.session.query(ProcessingJob).filter(
                    ProcessingJob.id.in_(job_ids)
                ).delete(synchronize_session=False)
                commit_with_profile(
                    db.session,
                    must_succeed=False,
                    context="clear_post_processing_jobs",
                    logger_obj=logger,
                )
            logger.info(f"Deleted processing jobs for post {post.id}")

            # Reset post audio paths and duration
            post.unprocessed_audio_path = None
            post.processed_audio_path = None
            post.duration = None

            # Commit all changes
            commit_with_profile(
                db.session,
                must_succeed=True,
                context="clear_post_final",
                logger_obj=logger,
            )

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
