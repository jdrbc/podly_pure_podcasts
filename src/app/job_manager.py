import os
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import case

from app import config
from app import db as _db
from app import logger, scheduler
from app.feeds import refresh_feed
from app.models import Feed, Post, ProcessingJob
from app.processor import get_processor
from podcast_processor.podcast_processor import ProcessorException
from podcast_processor.processing_status_manager import ProcessingStatusManager


class JobManager:
    """
    Centralized manager for starting, tracking, listing, and cancelling
    podcast processing jobs.

    Owns a shared worker pool and coordinates with ProcessingStatusManager.
    """

    def __init__(self) -> None:
        # Shared thread pool across all submissions (API and scheduled)
        max_workers = max(1, int(config.threads))
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

        # Status manager for DB interactions
        self._status_manager = ProcessingStatusManager(
            db_session=_db.session, logger=logger
        )

    # ------------------------ Public API ------------------------
    def start_post_processing(
        self, post_guid: str, priority: str = "interactive"
    ) -> Dict[str, Any]:
        """
        Idempotently start processing for a post. If an active job exists, return it.
        """
        # All DB work must be within app context when running outside request context
        with scheduler.app.app_context():
            post = Post.query.filter_by(guid=post_guid).first()
            if not post:
                return {
                    "status": "error",
                    "error_code": "NOT_FOUND",
                    "message": "Post not found",
                }

            if not post.whitelisted:
                return {
                    "status": "error",
                    "error_code": "NOT_WHITELISTED",
                    "message": "Post not whitelisted",
                }

            # Short-circuit if processed
            if post.processed_audio_path and os.path.exists(post.processed_audio_path):
                return {
                    "status": "completed",
                    "message": "Post already processed",
                    "download_url": f"/api/posts/{post_guid}/download",
                }

            # Check for existing active jobs in database
            # Refresh the session to ensure we see the latest data
            _db.session.expire_all()

            active_job = (
                ProcessingJob.query.filter_by(post_guid=post_guid)
                .filter(ProcessingJob.status.in_(["pending", "running"]))
                .order_by(ProcessingJob.created_at.desc())
                .first()
            )
            if active_job:
                return {
                    "status": active_job.status,
                    "message": "Another processing job is already running for this episode",
                    "job_id": active_job.id,
                }

            # Create a new job record and submit to pool
            job_id = self._status_manager.generate_job_id()
            self._status_manager.create_job(post_guid, job_id)
            return self._submit_processing_job(job_id, post_guid)

    def get_post_status(self, post_guid: str) -> Dict[str, Any]:
        with scheduler.app.app_context():
            post = Post.query.filter_by(guid=post_guid).first()
            if not post:
                return {
                    "status": "error",
                    "error_code": "NOT_FOUND",
                    "message": "Post not found",
                }

            job = (
                ProcessingJob.query.filter_by(post_guid=post_guid)
                .order_by(ProcessingJob.created_at.desc())
                .first()
            )

            if not job:
                if post.processed_audio_path and os.path.exists(
                    post.processed_audio_path
                ):
                    return {
                        "status": "completed",
                        "step": 4,
                        "step_name": "Processing complete",
                        "total_steps": 4,
                        "progress_percentage": 100.0,
                        "message": "Post already processed",
                        "download_url": f"/api/posts/{post_guid}/download",
                    }
                return {
                    "status": "not_started",
                    "step": 0,
                    "step_name": "Not started",
                    "total_steps": 4,
                    "progress_percentage": 0.0,
                    "message": "No processing job found",
                }

            response = {
                "status": job.status,
                "step": job.current_step,
                "step_name": job.step_name or "Unknown",
                "total_steps": job.total_steps,
                "progress_percentage": job.progress_percentage,
                "message": job.step_name
                or f"Step {job.current_step} of {job.total_steps}",
            }
            if job.started_at:
                response["started_at"] = job.started_at.isoformat()
            if (
                job.status == "completed"
                and post.processed_audio_path
                and os.path.exists(post.processed_audio_path)
            ):
                response["download_url"] = f"/api/posts/{post_guid}/download"
            if job.status == "failed" and job.error_message:
                response["error"] = job.error_message
            if job.status == "cancelled" and job.error_message:
                response["message"] = job.error_message
            return response

    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        with scheduler.app.app_context():
            job = ProcessingJob.query.get(job_id)
            if not job:
                return {
                    "status": "error",
                    "error_code": "NOT_FOUND",
                    "message": "Job not found",
                }
            return {
                "job_id": job.id,
                "post_guid": job.post_guid,
                "status": job.status,
                "step": job.current_step,
                "step_name": job.step_name,
                "total_steps": job.total_steps,
                "progress_percentage": job.progress_percentage,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": (
                    job.completed_at.isoformat() if job.completed_at else None
                ),
                "error": job.error_message,
            }

    def list_active_jobs(self, limit: int = 100) -> List[Dict[str, Any]]:
        with scheduler.app.app_context():
            # Derive a simple priority from status: running > pending
            priority_order = case(
                (ProcessingJob.status == "running", 2),
                (ProcessingJob.status == "pending", 1),
                else_=0,
            ).label("priority")

            rows = (
                _db.session.query(ProcessingJob, Post, priority_order)
                .outerjoin(Post, ProcessingJob.post_guid == Post.guid)
                .filter(ProcessingJob.status.in_(["pending", "running"]))
                .order_by(priority_order.desc(), ProcessingJob.created_at.desc())
                .limit(limit)
                .all()
            )

            results: List[Dict[str, Any]] = []
            for job, post, prio in rows:
                results.append(
                    {
                        "job_id": job.id,
                        "post_guid": job.post_guid,
                        "post_title": post.title if post else None,
                        "feed_title": post.feed.title if post and post.feed else None,
                        "status": job.status,
                        "priority": int(prio) if prio is not None else 0,
                        "step": job.current_step,
                        "step_name": job.step_name,
                        "total_steps": job.total_steps,
                        "progress_percentage": job.progress_percentage,
                        "created_at": (
                            job.created_at.isoformat() if job.created_at else None
                        ),
                        "started_at": (
                            job.started_at.isoformat() if job.started_at else None
                        ),
                        "completed_at": (
                            job.completed_at.isoformat() if job.completed_at else None
                        ),
                        "error_message": job.error_message,
                    }
                )

            return results

    def list_all_jobs_detailed(self, limit: int = 200) -> List[Dict[str, Any]]:
        with scheduler.app.app_context():
            # Priority by status, others ranked lowest
            priority_order = case(
                (ProcessingJob.status == "running", 2),
                (ProcessingJob.status == "pending", 1),
                else_=0,
            ).label("priority")

            rows = (
                _db.session.query(ProcessingJob, Post, priority_order)
                .outerjoin(Post, ProcessingJob.post_guid == Post.guid)
                .order_by(priority_order.desc(), ProcessingJob.created_at.desc())
                .limit(limit)
                .all()
            )

            results: List[Dict[str, Any]] = []
            for job, post, prio in rows:
                results.append(
                    {
                        "job_id": job.id,
                        "post_guid": job.post_guid,
                        "post_title": post.title if post else None,
                        "feed_title": post.feed.title if post and post.feed else None,
                        "status": job.status,
                        "priority": int(prio) if prio is not None else 0,
                        "step": job.current_step,
                        "step_name": job.step_name,
                        "total_steps": job.total_steps,
                        "progress_percentage": job.progress_percentage,
                        "created_at": (
                            job.created_at.isoformat() if job.created_at else None
                        ),
                        "started_at": (
                            job.started_at.isoformat() if job.started_at else None
                        ),
                        "completed_at": (
                            job.completed_at.isoformat() if job.completed_at else None
                        ),
                        "error_message": job.error_message,
                    }
                )

            return results

    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        with scheduler.app.app_context():
            job = ProcessingJob.query.get(job_id)
            if not job:
                return {
                    "status": "error",
                    "error_code": "NOT_FOUND",
                    "message": "Job not found",
                }

            if job.status in ["completed", "failed", "cancelled"]:
                return {
                    "status": "error",
                    "error_code": "ALREADY_FINISHED",
                    "message": f"Job already {job.status}",
                }

            # Mark job as cancelled in database
            self._status_manager.mark_cancelled(job_id, "Cancelled by user request")

            return {
                "status": "cancelled",
                "job_id": job_id,
                "message": "Job cancelled",
            }

    def cancel_post_jobs(self, post_guid: str) -> Dict[str, Any]:
        with scheduler.app.app_context():
            # Find active jobs for this post in database
            active_jobs = (
                ProcessingJob.query.filter_by(post_guid=post_guid)
                .filter(ProcessingJob.status.in_(["pending", "running"]))
                .all()
            )

            job_ids = [job.id for job in active_jobs]
            for job in active_jobs:
                self._status_manager.mark_cancelled(job.id, "Cancelled by user request")

            return {
                "status": "cancelled",
                "post_guid": post_guid,
                "job_ids": job_ids,
                "message": f"Cancelled {len(job_ids)} jobs",
            }

    def cleanup_stale_jobs(self, older_than: timedelta) -> int:
        cutoff = datetime.utcnow() - older_than
        with scheduler.app.app_context():
            old_jobs = ProcessingJob.query.filter(
                ProcessingJob.created_at < cutoff
            ).all()
            count = len(old_jobs)
            for j in old_jobs:
                try:
                    # Best-effort cleanup
                    _db.session.delete(j)
                    _db.session.commit()
                except Exception:  # pylint: disable=broad-except
                    pass
            return count

    def cleanup_stuck_pending_jobs(self, stuck_threshold_minutes: int = 10) -> int:
        """
        Clean up jobs that have been stuck in 'pending' status for too long.
        This indicates they were never picked up by the thread pool.
        """
        cutoff = datetime.utcnow() - timedelta(minutes=stuck_threshold_minutes)
        with scheduler.app.app_context():
            stuck_jobs = ProcessingJob.query.filter(
                ProcessingJob.status == "pending", ProcessingJob.created_at < cutoff
            ).all()

            count = len(stuck_jobs)
            for job in stuck_jobs:
                try:
                    logger.warning(
                        f"Marking stuck pending job {job.id} as failed (created at {job.created_at})"
                    )
                    self._status_manager.update_job_status(
                        job,
                        "failed",
                        job.current_step,
                        f"Job was stuck in pending status for over {stuck_threshold_minutes} minutes",
                    )
                except Exception as e:  # pylint: disable=broad-except
                    logger.error(f"Failed to update stuck job {job.id}: {e}")

            return count

    def clear_all_jobs(self) -> Dict[str, Any]:
        """
        Clear all processing jobs from the database.
        This is typically called during application startup to ensure a clean state.
        """
        with scheduler.app.app_context():
            try:
                # Delete all processing jobs from database
                all_jobs = ProcessingJob.query.all()
                job_count = len(all_jobs)

                for job in all_jobs:
                    _db.session.delete(job)

                _db.session.commit()

                logger.info(f"Cleared {job_count} processing jobs on startup")

                return {
                    "status": "success",
                    "cleared_jobs": job_count,
                    "message": f"Cleared {job_count} jobs from database",
                }

            except Exception as e:
                logger.error(f"Error clearing all jobs: {e}")
                return {"status": "error", "message": f"Failed to clear jobs: {str(e)}"}

    def start_refresh_all_feeds(self) -> Dict[str, Any]:
        """
        Refresh feeds and enqueue per-post processing into internal worker pool.
        """
        with scheduler.app.app_context():
            feeds = Feed.query.all()
            for feed in feeds:
                refresh_feed(feed)

            # Clean up posts with missing audio files
            self._cleanup_inconsistent_posts()

            # Process new posts
            enqueued_count = self._cleanup_and_process_new_posts()

            return {"status": "ok", "enqueued": enqueued_count}

    # ------------------------ Helpers ------------------------
    def _cleanup_inconsistent_posts(self) -> None:
        """Clean up posts with missing audio files."""
        inconsistent_posts = Post.query.filter(
            Post.whitelisted,
            (
                (Post.unprocessed_audio_path.isnot(None))
                | (Post.processed_audio_path.isnot(None))
            ),
        ).all()

        for post in inconsistent_posts:
            try:
                if post.processed_audio_path and not os.path.exists(
                    post.processed_audio_path
                ):
                    logger.warning(
                        f"Processed audio file missing for post '{post.title}' "
                        f"(ID: {post.id}): {post.processed_audio_path}"
                    )
                    post.processed_audio_path = None
                    _db.session.commit()
                if post.unprocessed_audio_path and not os.path.exists(
                    post.unprocessed_audio_path
                ):
                    logger.warning(
                        f"Unprocessed audio file missing for post '{post.title}' "
                        f"(ID: {post.id}): {post.unprocessed_audio_path}"
                    )
                    post.unprocessed_audio_path = None
                    _db.session.commit()
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error(
                    f"Failed to reset fields for post '{post.title}' (ID: {post.id}): {e}",
                    exc_info=True,
                )

    def _cleanup_and_process_new_posts(self) -> int:
        """Clean up and process new posts, returning the count of enqueued posts."""
        new_posts = Post.query.filter(
            Post.processed_audio_path.is_(None), Post.whitelisted
        ).all()

        if not new_posts:
            return 0

        # Start processing for new posts
        for post in new_posts:
            if post.download_url:
                self.start_post_processing(post.guid, priority="scheduled")

        return len(new_posts)

    # Removed _get_active_job_for_guid - now using direct database queries

    # ------------------------ Internal helpers ------------------------
    def _submit_processing_job(self, job_id: str, post_guid: str) -> Dict[str, Any]:
        """Encapsulate job submission and callback wiring to reduce complexity."""

        def _cancelled() -> bool:
            # Check cancellation status from database
            with scheduler.app.app_context():
                current_job = ProcessingJob.query.get(job_id)
                return current_job is None or current_job.status == "cancelled"

        def _run_job() -> None:
            # Ensure app context in worker
            with scheduler.app.app_context():
                try:
                    logger.debug(
                        "_run_job start: job_id=%s post_guid=%s", job_id, post_guid
                    )
                    # Reload Post inside the worker thread to avoid detached instances
                    worker_post = Post.query.filter_by(guid=post_guid).first()
                    if not worker_post:
                        # If the post disappeared, mark job failed and exit
                        logger.error(
                            f"Post with GUID {post_guid} not found in worker; failing job {job_id}"
                        )
                        try:
                            # Best-effort status update
                            self._status_manager.update_job_status(
                                ProcessingJob.query.get(job_id),
                                "failed",
                                0,
                                "Post not found",
                            )
                        except Exception:  # pylint: disable=broad-except
                            pass
                        return

                    logger.debug("_run_job calling processor.process job_id=%s", job_id)
                    get_processor().process(
                        worker_post, job_id=job_id, cancel_callback=_cancelled
                    )
                except ProcessorException as e:
                    # Cancellation is handled cooperatively inside processor
                    logger.info(f"Job {job_id} ended with ProcessorException: {e}")
                except Exception as e:  # pylint: disable=broad-except
                    logger.error(f"Unexpected error in job {job_id}: {e}")

        try:
            future = self._executor.submit(_run_job)

            # Add callback to handle any submission failures
            def _on_job_done(fut: Future[None]) -> None:
                try:
                    # This will raise any exception that occurred during execution
                    fut.result()
                except Exception as e:
                    # Update job status to failed if there was an unhandled exception
                    logger.error(
                        f"Job {job_id} failed with exception: {e}", exc_info=True
                    )
                    try:
                        with scheduler.app.app_context():
                            failed_job = ProcessingJob.query.get(job_id)
                            if failed_job and failed_job.status not in [
                                "completed",
                                "cancelled",
                            ]:
                                self._status_manager.update_job_status(
                                    failed_job,
                                    "failed",
                                    failed_job.current_step,
                                    f"Job execution failed: {str(e)}",
                                )
                    except Exception as cleanup_error:
                        logger.error(
                            f"Failed to update job status after failure: {cleanup_error}"
                        )

            future.add_done_callback(_on_job_done)
            logger.info(f"Successfully submitted job {job_id} to thread pool")

            return {"status": "started", "job_id": job_id}

        except Exception as e:
            # Thread pool submission failed
            logger.error(f"Failed to submit job {job_id} to thread pool: {e}")
            # Reload job from database to avoid session detachment issues
            fresh_job = ProcessingJob.query.get(job_id)
            if fresh_job:
                self._status_manager.update_job_status(
                    fresh_job, "failed", 0, f"Failed to start job: {str(e)}"
                )
            return {
                "status": "error",
                "error_code": "SUBMISSION_FAILED",
                "message": f"Failed to submit job to thread pool: {str(e)}",
                "job_id": job_id,
            }


# Singleton accessor
def get_job_manager() -> JobManager:
    if not hasattr(get_job_manager, "_instance"):
        get_job_manager._instance = JobManager()  # type: ignore[attr-defined]
    return get_job_manager._instance  # type: ignore[attr-defined, no-any-return]


def scheduled_refresh_all_feeds() -> None:
    """Top-level function for APScheduler to invoke periodically."""
    try:
        get_job_manager().start_refresh_all_feeds()
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Scheduled refresh failed: {e}")
