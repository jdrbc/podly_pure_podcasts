import logging
import os
from typing import Any, Dict

from app.extensions import db
from app.jobs_manager_run_service import recalculate_run_counts
from app.models import (
    Identification,
    ModelCall,
    Post,
    ProcessingJob,
    TranscriptSegment,
)

logger = logging.getLogger("writer")


def cleanup_missing_audio_paths_action(params: Dict[str, Any]) -> int:
    inconsistent_posts = Post.query.filter(
        Post.whitelisted,
        (
            (Post.unprocessed_audio_path.isnot(None))
            | (Post.processed_audio_path.isnot(None))
        ),
    ).all()

    count = 0
    for post in inconsistent_posts:
        changed = False
        if post.processed_audio_path and not os.path.exists(post.processed_audio_path):
            post.processed_audio_path = None
            changed = True
        if post.unprocessed_audio_path and not os.path.exists(
            post.unprocessed_audio_path
        ):
            post.unprocessed_audio_path = None
            changed = True

        if changed:
            latest_job = (
                ProcessingJob.query.filter_by(post_guid=post.guid)
                .order_by(ProcessingJob.created_at.desc())
                .first()
            )
            if latest_job and latest_job.status not in {"pending", "running"}:
                latest_job.status = "pending"
                latest_job.current_step = 0
                latest_job.progress_percentage = 0.0
                latest_job.step_name = "Not started"
                latest_job.error_message = None
                latest_job.started_at = None
                latest_job.completed_at = None

            count += 1

    return count


def clear_post_processing_data_action(params: Dict[str, Any]) -> Dict[str, Any]:
    post_id = params.get("post_id")
    post = db.session.get(Post, post_id)
    if not post:
        raise ValueError(f"Post {post_id} not found")

    logger.info("[WRITER] clear_post_processing_data_action: post_id=%s", post_id)

    # Chunked deletes for segments and identifications
    while True:
        ids_batch = [
            row[0]
            for row in db.session.query(TranscriptSegment.id)
            .filter_by(post_id=post.id)
            .limit(500)
            .all()
        ]
        if not ids_batch:
            logger.debug(
                "[WRITER] clear_post_processing_data_action: no more segments for post_id=%s",
                post_id,
            )
            break

        db.session.query(Identification).filter(
            Identification.transcript_segment_id.in_(ids_batch)
        ).delete(synchronize_session=False)

        db.session.query(TranscriptSegment).filter(
            TranscriptSegment.id.in_(ids_batch)
        ).delete(synchronize_session=False)

    # Model calls
    db.session.query(ModelCall).filter_by(post_id=post.id).delete()

    # Processing jobs
    db.session.query(ProcessingJob).filter_by(post_guid=post.guid).delete()

    # Reset post fields
    post.unprocessed_audio_path = None
    post.processed_audio_path = None
    post.duration = None

    logger.info(
        "[WRITER] clear_post_processing_data_action: completed post_id=%s", post_id
    )

    return {"post_id": post.id}


def cleanup_processed_post_action(params: Dict[str, Any]) -> Dict[str, Any]:
    post_id = params.get("post_id")
    if not post_id:
        raise ValueError("post_id is required")

    post = db.session.get(Post, int(post_id))
    if not post:
        raise ValueError(f"Post {post_id} not found")

    logger.info("[WRITER] cleanup_processed_post_action: post_id=%s", post_id)

    # Remove processing artifacts and dependent rows.
    clear_post_processing_data_action({"post_id": post.id})
    post.whitelisted = False

    recalculate_run_counts(db.session)

    logger.info("[WRITER] cleanup_processed_post_action: completed post_id=%s", post_id)

    return {"post_id": post.id}
