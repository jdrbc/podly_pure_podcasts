import logging
import os
from datetime import datetime, timedelta
from threading import Event, Lock, Thread
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import case

from app.db_concurrency import (
    commit_with_profile,
)
from app.extensions import db as _db
from app.extensions import scheduler
from app.feeds import refresh_feed
from app.job_manager import JobManager as SingleJobManager
from app.jobs_manager_run_service import ensure_active_run, recalculate_run_counts
from app.models import Feed, JobsManagerRun, Post, ProcessingJob
from app.processor import get_processor
from podcast_processor.podcast_processor import ProcessorException
from podcast_processor.processing_status_manager import ProcessingStatusManager

logger = logging.getLogger("global_logger")


class JobsManager:
    """
    Centralized manager for starting, tracking, listing, and cancelling
    podcast processing jobs.

    Owns a shared worker pool and coordinates with ProcessingStatusManager.
    """

    # Class-level lock to ensure only one job processes at a time across ALL instances
    _global_processing_lock = Lock()

    def __init__(self) -> None:
        # Status manager for DB interactions
        self._status_manager = ProcessingStatusManager(
            db_session=_db.session, logger=logger
        )

        # Track the singleton run id with thread-safe access
        self._run_lock = Lock()
        self._run_id: Optional[str] = None

        # Persistent worker thread coordination
        self._stop_event = Event()
        self._work_event = Event()
        with scheduler.app.app_context():
            run = ensure_active_run(
                _db.session, trigger="startup", context={"source": "init"}
            )
            self._set_run_id(run.id)
            commit_with_profile(
                _db.session, must_succeed=True, context="init_run", logger_obj=logger
            )
        self._worker_thread = Thread(
            target=self._worker_loop, name="jobs-manager-worker", daemon=True
        )
        self._worker_thread.start()

    def _set_run_id(self, run_id: Optional[str]) -> None:
        with self._run_lock:
            self._run_id = run_id

    def _get_run_id(self) -> Optional[str]:
        with self._run_lock:
            return self._run_id

    def _wake_worker(self) -> None:
        self._work_event.set()

    def _wait_for_work(self, timeout: float = 5.0) -> None:
        triggered = self._work_event.wait(timeout)
        if triggered:
            self._work_event.clear()

    # ------------------------ Public API ------------------------
    def start_post_processing(
        self, post_guid: str, priority: str = "interactive"
    ) -> Dict[str, Any]:
        """
        Idempotently start processing for a post. If an active job exists, return it.
        """
        with scheduler.app.app_context():
            run = ensure_active_run(
                _db.session,
                trigger="interactive_start",
                context={"post_guid": post_guid, "priority": priority},
            )
            self._set_run_id(run.id if run else None)
            result = SingleJobManager(
                post_guid, self._status_manager, logger, run.id if run else None
            ).start_processing(priority)
        if result.get("status") in {"started", "running"}:
            self._wake_worker()
        return result

    def enqueue_pending_jobs(
        self,
        trigger: str = "system",
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Ensure all posts have job records and enqueue pending work.

        Returns basic stats for logging/monitoring.
        """
        with scheduler.app.app_context():
            active_run = ensure_active_run(_db.session, trigger, context)
            self._set_run_id(active_run.id if active_run else None)
            created_count, pending_count = self._cleanup_and_process_new_posts(
                active_run
            )
            recalculate_run_counts(_db.session)
            commit_with_profile(
                _db.session,
                must_succeed=True,
                context="enqueue_pending_jobs",
                logger_obj=logger,
            )
            response = {
                "status": "ok",
                "created": created_count,
                "pending": pending_count,
                "enqueued": pending_count,
                "run_id": active_run.id if active_run else None,
            }
        if pending_count:
            self._wake_worker()
        return response

    def _ensure_jobs_for_all_posts(self, run_id: Optional[str]) -> int:
        """Ensure every post has an associated ProcessingJob record."""
        posts_without_jobs = (
            Post.query.outerjoin(ProcessingJob, ProcessingJob.post_guid == Post.guid)
            .filter(ProcessingJob.id.is_(None))
            .all()
        )

        created = 0
        for post in posts_without_jobs:
            if post.whitelisted:
                SingleJobManager(
                    post.guid, self._status_manager, logger, run_id
                ).ensure_job()
                created += 1
        return created

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
                        "status": "skipped",
                        "step": 4,
                        "step_name": "Processing skipped",
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
                job.status in {"completed", "skipped"}
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
            job = _db.session.get(ProcessingJob, job_id)
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
            job = _db.session.get(ProcessingJob, job_id)
            if not job:
                return {
                    "status": "error",
                    "error_code": "NOT_FOUND",
                    "message": "Job not found",
                }

            if job.status in ["completed", "failed", "cancelled", "skipped"]:
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
            batch: list[ProcessingJob] = []
            for j in old_jobs:
                try:
                    batch.append(j)
                    if len(batch) >= 200:
                        for job in batch:
                            _db.session.delete(job)
                        commit_with_profile(
                            _db.session,
                            must_succeed=False,
                            context="cleanup_stale_jobs",
                            logger_obj=logger,
                        )
                        batch = []
                except Exception:  # pylint: disable=broad-except
                    batch = []
            if batch:
                try:
                    for job in batch:
                        _db.session.delete(job)
                    commit_with_profile(
                        _db.session,
                        must_succeed=False,
                        context="cleanup_stale_jobs",
                        logger_obj=logger,
                    )
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

                commit_with_profile(
                    _db.session,
                    must_succeed=True,
                    context="clear_all_jobs",
                    logger_obj=logger,
                )

                logger.info(f"Cleared {job_count} processing jobs on startup")

                return {
                    "status": "success",
                    "cleared_jobs": job_count,
                    "message": f"Cleared {job_count} jobs from database",
                }

            except Exception as e:
                logger.error(f"Error clearing all jobs: {e}")
                return {"status": "error", "message": f"Failed to clear jobs: {str(e)}"}

    def start_refresh_all_feeds(
        self,
        trigger: str = "scheduled",
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
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
            return self.enqueue_pending_jobs(trigger=trigger, context=context)

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
                    commit_with_profile(
                        _db.session,
                        must_succeed=False,
                        context="cleanup_missing_audio_paths",
                        logger_obj=logger,
                    )
                if post.unprocessed_audio_path and not os.path.exists(
                    post.unprocessed_audio_path
                ):
                    logger.warning(
                        f"Unprocessed audio file missing for post '{post.title}' "
                        f"(ID: {post.id}): {post.unprocessed_audio_path}"
                    )
                    post.unprocessed_audio_path = None
                    commit_with_profile(
                        _db.session,
                        must_succeed=False,
                        context="cleanup_missing_audio_paths",
                        logger_obj=logger,
                    )
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error(
                    f"Failed to reset fields for post '{post.title}' (ID: {post.id}): {e}",
                    exc_info=True,
                )

    def _cleanup_and_process_new_posts(
        self, active_run: Optional[JobsManagerRun]
    ) -> Tuple[int, int]:
        """Ensure all posts have jobs and return counts for monitoring."""
        run_id = active_run.id if active_run else None
        created_jobs = self._ensure_jobs_for_all_posts(run_id)

        pending_jobs = (
            ProcessingJob.query.filter(ProcessingJob.status == "pending")
            .order_by(ProcessingJob.created_at.asc())
            .all()
        )

        if active_run and pending_jobs:
            reassigned = 0
            for job in pending_jobs:
                if job.jobs_manager_run_id != run_id:
                    job.jobs_manager_run_id = run_id
                    reassigned += 1
            if reassigned:
                _db.session.flush()
                recalculate_run_counts(_db.session)

        if created_jobs:
            logger.info("Created %s new job records", created_jobs)

        logger.info(
            "Pending jobs ready for worker: count=%s run_id=%s",
            len(pending_jobs),
            run_id,
        )

        return created_jobs, len(pending_jobs)

    # Removed _get_active_job_for_guid - now using direct database queries

    # ------------------------ Internal helpers ------------------------

    def _dequeue_next_job(self) -> Optional[Tuple[str, str]]:
        """Return the next pending job id and post guid, or None if idle.

        CRITICAL: This method atomically marks the job as "running" when dequeuing
        to prevent race conditions where multiple jobs could be dequeued before
        any is marked as running.
        """
        with scheduler.app.app_context():
            # Clear any stale session state before querying
            try:
                _db.session.rollback()
            except Exception:  # pylint: disable=broad-except
                pass
            _db.session.expire_all()

            # Enforce single-job processing: if any job is already running, wait.
            running_job = (
                ProcessingJob.query.filter(ProcessingJob.status == "running")
                .order_by(ProcessingJob.started_at.desc().nullslast())
                .first()
            )
            if running_job:
                logger.debug(
                    "[JOB_DEQUEUE] Skipping dequeue - job %s is still running (started_at=%s)",
                    running_job.id,
                    running_job.started_at,
                )
                return None

            job = (
                ProcessingJob.query.filter(ProcessingJob.status == "pending")
                .order_by(ProcessingJob.created_at.asc())
                .first()
            )
            if not job:
                return None

            job.status = "running"
            job.started_at = datetime.utcnow()

            run_id = self._get_run_id()
            if run_id and job.jobs_manager_run_id != run_id:
                job.jobs_manager_run_id = run_id
                _db.session.flush()
                recalculate_run_counts(_db.session)

            # Commit the status change immediately to block other potential dequeuers
            commit_with_profile(
                _db.session,
                must_succeed=True,
                context="dequeue_job_set_running",
                logger_obj=logger,
            )

            logger.info(
                "[JOB_DEQUEUE] Successfully dequeued and marked running: job_id=%s post_guid=%s",
                job.id,
                job.post_guid,
            )
            return job.id, job.post_guid

    def _worker_loop(self) -> None:
        """Background loop that continuously processes pending jobs.

        CRITICAL: This runs in a single dedicated daemon thread. Combined with
        the _global_processing_lock in _process_job, this ensures truly sequential
        job execution with no parallelism.
        """
        import threading

        logger.info(
            "[WORKER_LOOP] Started single worker thread: thread_name=%s thread_id=%s",
            threading.current_thread().name,
            threading.current_thread().ident,
        )
        while not self._stop_event.is_set():
            try:
                job_details = self._dequeue_next_job()
                if not job_details:
                    self._wait_for_work()
                    continue
                job_id, post_guid = job_details
                self._process_job(job_id, post_guid)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Worker loop error: %s", exc, exc_info=True)

    def _process_job(self, job_id: str, post_guid: str) -> None:
        """Execute a single job using the processor.

        Uses a global processing lock to absolutely guarantee single-job execution.
        """
        # Acquire global lock to ensure only one job runs at a time
        logger.info(
            "[JOB_PROCESS] Waiting for processing lock: job_id=%s post_guid=%s",
            job_id,
            post_guid,
        )
        with JobsManager._global_processing_lock:
            logger.info(
                "[JOB_PROCESS] Acquired processing lock: job_id=%s post_guid=%s",
                job_id,
                post_guid,
            )
            with scheduler.app.app_context():
                try:
                    # Clear any failed transaction state from prior work on this session.
                    try:
                        _db.session.rollback()
                    except Exception:  # pylint: disable=broad-except
                        pass

                    # Expire all cached objects to ensure fresh reads
                    _db.session.expire_all()

                    logger.debug(
                        "Worker starting job_id=%s post_guid=%s", job_id, post_guid
                    )
                    worker_post = Post.query.filter_by(guid=post_guid).first()
                    if not worker_post:
                        logger.error(
                            "Post with GUID %s not found; failing job %s",
                            post_guid,
                            job_id,
                        )
                        job = _db.session.get(ProcessingJob, job_id)
                        if job:
                            self._status_manager.update_job_status(
                                job,
                                "failed",
                                job.current_step or 0,
                                "Post not found",
                                0.0,
                            )
                        return

                    def _cancelled() -> bool:
                        # Expire the job before re-querying to get fresh state
                        _db.session.expire_all()
                        current_job = _db.session.get(ProcessingJob, job_id)
                        return current_job is None or current_job.status == "cancelled"

                    get_processor().process(
                        worker_post, job_id=job_id, cancel_callback=_cancelled
                    )
                except ProcessorException as exc:
                    logger.info(
                        "Job %s finished with processor exception: %s", job_id, exc
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    logger.error(
                        "Unexpected error in job %s: %s", job_id, exc, exc_info=True
                    )
                    try:
                        _db.session.expire_all()
                        failed_job = _db.session.get(ProcessingJob, job_id)
                        if failed_job and failed_job.status not in [
                            "completed",
                            "cancelled",
                            "failed",
                        ]:
                            self._status_manager.update_job_status(
                                failed_job,
                                "failed",
                                failed_job.current_step or 0,
                                f"Job execution failed: {exc}",
                                failed_job.progress_percentage or 0.0,
                            )
                    except Exception as cleanup_error:  # pylint: disable=broad-except
                        logger.error(
                            "Failed to update job status after error: %s",
                            cleanup_error,
                            exc_info=True,
                        )
                finally:
                    # Always clean up session state after job processing to release any locks
                    try:
                        _db.session.rollback()
                    except Exception:  # pylint: disable=broad-except
                        pass
                    try:
                        _db.session.remove()
                    except Exception as exc:  # pylint: disable=broad-except
                        logger.warning("Failed to remove session after job: %s", exc)
            logger.info(
                "[JOB_PROCESS] Released processing lock: job_id=%s post_guid=%s",
                job_id,
                post_guid,
            )


# Singleton accessor
def get_jobs_manager() -> JobsManager:
    if not hasattr(get_jobs_manager, "_instance"):
        get_jobs_manager._instance = JobsManager()  # type: ignore[attr-defined]
    return get_jobs_manager._instance  # type: ignore[attr-defined, no-any-return]


def scheduled_refresh_all_feeds() -> None:
    """Top-level function for APScheduler to invoke periodically."""
    try:
        get_jobs_manager().start_refresh_all_feeds(trigger="scheduled")
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Scheduled refresh failed: {e}")
