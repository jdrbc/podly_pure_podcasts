import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

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


def get_step_name(step: int) -> str:
    """
    Get human-readable name for processing step.

    Args:
        step: Step number (1-4)

    Returns:
        Human-readable step name
    """
    step_names = {
        1: "Download",
        2: "Transcription",
        3: "LLM Ad Identification",
        4: "Audio Processing"
    }
    return step_names.get(step, f"Step {step}")


def validate_step_dependencies(post: Post, from_step: int) -> Tuple[bool, Optional[int], Optional[str]]:
    """
    Validate that dependencies exist for starting from specified step.

    Args:
        post: The Post object to validate
        from_step: Step to start from (1-4)

    Returns:
        Tuple of (is_valid, fallback_step, error_message)
        - If is_valid=True, can start from from_step
        - If is_valid=False, must start from fallback_step with error_message
    """
    if from_step == 1:
        return (True, None, None)

    # Step 2 requires audio (unprocessed or processed - cleanup will restore if needed)
    if from_step == 2:
        has_unprocessed = post.unprocessed_audio_path and os.path.exists(post.unprocessed_audio_path)
        has_processed = post.processed_audio_path and os.path.exists(post.processed_audio_path)
        if not has_unprocessed and not has_processed:
            return (False, 1, "No audio file found, starting from download")

    # Step 3+ requires transcript segments (but not audio)
    if from_step >= 3:
        transcript_count = TranscriptSegment.query.filter_by(post_id=post.id).count()
        if transcript_count == 0:
            # If no transcripts but have audio (unprocessed or processed), can start from step 2
            has_unprocessed = post.unprocessed_audio_path and os.path.exists(post.unprocessed_audio_path)
            has_processed = post.processed_audio_path and os.path.exists(post.processed_audio_path)
            if has_unprocessed or has_processed:
                return (False, 2, "No transcript segments found, starting from transcription")
            else:
                return (False, 1, "No transcript segments or audio found, starting from download")

    # Step 4 requires identifications and audio (unprocessed or processed)
    if from_step >= 4:
        identification_count = db.session.query(Identification).join(
            TranscriptSegment, Identification.transcript_segment_id == TranscriptSegment.id
        ).filter(TranscriptSegment.post_id == post.id).count()
        if identification_count == 0:
            return (False, 3, "No ad identifications found, starting from LLM identification")

        # Check if we have either unprocessed or processed audio
        has_unprocessed = post.unprocessed_audio_path and os.path.exists(post.unprocessed_audio_path)
        has_processed = post.processed_audio_path and os.path.exists(post.processed_audio_path)
        if not has_unprocessed and not has_processed:
            return (False, 1, "No audio file found, starting from download")

    return (True, None, None)


def selective_clear_post_processing_data(post: Post, from_step: int) -> Dict[str, Any]:
    """
    Selectively clear processing data based on starting step.

    Args:
        post: The Post object to clear data for
        from_step: Step to start from (1-4)

    Returns:
        Dict with cleanup summary including:
        - from_step: int
        - from_step_name: str
        - files_removed: List[str]
        - db_records_deleted: Dict[str, int]
    """
    try:
        logger.info(
            f"Selective clear for post: {post.title} (ID: {post.id}) from step {from_step}"
        )

        files_removed = []
        db_records_deleted = {
            "transcript_segments": 0,
            "identifications": 0,
            "model_calls": 0,
            "processing_jobs": 0,
        }

        # Step 1: Full cleanup (delegate to existing function)
        if from_step == 1:
            clear_post_processing_data(post)
            return {
                "from_step": from_step,
                "from_step_name": get_step_name(from_step),
                "files_removed": ["all"],
                "db_records_deleted": db_records_deleted,
            }

        # For steps 2-4: Selective cleanup

        # Steps 2-4: If unprocessed audio is missing, restore it from processed audio before deleting processed
        # This is needed because steps 2+ require unprocessed audio as input
        if from_step >= 2:
            if not (post.unprocessed_audio_path and os.path.exists(post.unprocessed_audio_path)):
                if post.processed_audio_path and os.path.exists(post.processed_audio_path):
                    # Need to restore unprocessed audio for step 4 to work
                    import shutil
                    from podcast_processor.podcast_downloader import get_and_make_download_path
                    try:
                        unprocessed_path = get_and_make_download_path(post.title)
                        shutil.copy2(post.processed_audio_path, unprocessed_path)
                        post.unprocessed_audio_path = str(unprocessed_path)
                        logger.info(f"Restored unprocessed audio from processed for step {from_step}: {unprocessed_path}")
                    except Exception as e:
                        logger.warning(f"Failed to restore unprocessed audio: {e}")

        # Always remove processed audio file for steps 2-4
        if post.processed_audio_path and os.path.exists(post.processed_audio_path):
            try:
                os.remove(post.processed_audio_path)
                files_removed.append(post.processed_audio_path)
                logger.info(f"Removed processed audio: {post.processed_audio_path}")
            except Exception as e:
                logger.warning(f"Failed to remove processed audio: {e}")

        # Use pessimistic lock for database operations
        with pessimistic_write_lock():
            # Step 2: Delete transcript segments and identifications
            if from_step == 2:
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

                        # Delete identifications first
                        deleted_ids = db.session.query(Identification).filter(
                            Identification.transcript_segment_id.in_(ids_batch)
                        ).delete(synchronize_session=False)
                        db_records_deleted["identifications"] += deleted_ids

                        # Then delete transcript segments
                        deleted_segs = db.session.query(TranscriptSegment).filter(
                            TranscriptSegment.id.in_(ids_batch)
                        ).delete(synchronize_session=False)
                        db_records_deleted["transcript_segments"] += deleted_segs

                _chunked_delete_segments()
                logger.info(
                    f"Deleted {db_records_deleted['transcript_segments']} segments and "
                    f"{db_records_deleted['identifications']} identifications for post {post.id}"
                )

            # Step 3: Delete only identifications (keep transcripts)
            elif from_step == 3:
                # Get transcript segment IDs for this post
                segment_ids = [
                    row[0]
                    for row in db.session.query(TranscriptSegment.id)
                    .filter_by(post_id=post.id)
                    .all()
                ]

                if segment_ids:
                    deleted_ids = db.session.query(Identification).filter(
                        Identification.transcript_segment_id.in_(segment_ids)
                    ).delete(synchronize_session=False)
                    db_records_deleted["identifications"] = deleted_ids
                    logger.info(f"Deleted {deleted_ids} identifications for post {post.id}")

            # Step 4: Keep everything (transcripts + identifications), only processed audio is removed above
            # No database cleanup needed for step 4

            # Delete model calls for steps 2-3 only (step 4 reuses identifications)
            if from_step in (2, 3):
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
                    deleted = db.session.query(ModelCall).filter(
                        ModelCall.id.in_(model_call_ids)
                    ).delete(synchronize_session=False)
                    db_records_deleted["model_calls"] += deleted
                    commit_with_profile(
                        db.session,
                        must_succeed=False,
                        context="selective_clear_model_calls",
                        logger_obj=logger,
                    )
                logger.info(f"Deleted {db_records_deleted['model_calls']} model calls for post {post.id}")

            # Delete processing jobs for steps 2-4
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
                deleted = db.session.query(ProcessingJob).filter(
                    ProcessingJob.id.in_(job_ids)
                ).delete(synchronize_session=False)
                db_records_deleted["processing_jobs"] += deleted
                commit_with_profile(
                    db.session,
                    must_succeed=False,
                    context="selective_clear_processing_jobs",
                    logger_obj=logger,
                )
            logger.info(f"Deleted {db_records_deleted['processing_jobs']} processing jobs for post {post.id}")

            # Reset processed audio path for steps 2-4 (keep unprocessed for steps 2+)
            post.processed_audio_path = None

            # Reset duration only for step 2 (transcription will recalculate it)
            if from_step == 2:
                post.duration = None

            # Commit all changes
            commit_with_profile(
                db.session,
                must_succeed=True,
                context="selective_clear_final",
                logger_obj=logger,
            )

        logger.info(
            f"Successfully cleared processing data for post: {post.title} (ID: {post.id}) from step {from_step}"
        )

        return {
            "from_step": from_step,
            "from_step_name": get_step_name(from_step),
            "files_removed": files_removed,
            "db_records_deleted": db_records_deleted,
        }

    except Exception as e:
        logger.error(
            f"Error in selective clear for post {post.id}: {e}",
            exc_info=True,
        )
        db.session.rollback()
        raise PostException(f"Failed to selectively clear processing data: {str(e)}") from e
