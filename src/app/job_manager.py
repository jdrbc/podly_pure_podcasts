import logging
import os
from typing import Any, Dict, Optional, Tuple

from app.extensions import db as _db
from app.models import Post, ProcessingJob
from podcast_processor.processing_status_manager import ProcessingStatusManager


class JobManager:
    """Manage the lifecycle guarantees for a single `ProcessingJob` record."""

    ACTIVE_STATUSES = {"pending", "running"}

    def __init__(
        self,
        post_guid: str,
        status_manager: ProcessingStatusManager,
        logger_obj: logging.Logger,
        run_id: Optional[str],
    ) -> None:
        self.post_guid = post_guid
        self._status_manager = status_manager
        self._logger = logger_obj
        self._run_id = run_id
        self.job: Optional[ProcessingJob] = None

    @property
    def job_id(self) -> Optional[str]:
        return getattr(self.job, "id", None) if self.job else None

    def _reload_job(self) -> Optional[ProcessingJob]:
        self.job = (
            ProcessingJob.query.filter_by(post_guid=self.post_guid)
            .order_by(ProcessingJob.created_at.desc())
            .first()
        )
        return self.job

    def get_active_job(self) -> Optional[ProcessingJob]:
        job = self.job or self._reload_job()
        if job and job.status in self.ACTIVE_STATUSES:
            return job
        return None

    def ensure_job(self) -> ProcessingJob:
        job = self.get_active_job()
        if job:
            if self._run_id and job.jobs_manager_run_id != self._run_id:
                job.jobs_manager_run_id = self._run_id
                self._status_manager.db_session.flush()
            return job
        job_id = self._status_manager.generate_job_id()
        job = self._status_manager.create_job(self.post_guid, job_id, self._run_id)
        self.job = job
        return job

    def fail(self, message: str, step: int = 0, progress: float = 0.0) -> ProcessingJob:
        job = self.ensure_job()
        step = step or job.current_step or 0
        progress = progress or job.progress_percentage or 0.0
        self._status_manager.update_job_status(job, "failed", step, message, progress)
        return job

    def complete(self, message: str = "Processing complete") -> ProcessingJob:
        job = self.ensure_job()
        total_steps = job.total_steps or 4
        self._status_manager.update_job_status(
            job, "completed", total_steps, message, 100.0
        )
        return job

    def skip(
        self,
        message: str = "Processing skipped",
        step: Optional[int] = None,
        progress: Optional[float] = None,
    ) -> ProcessingJob:
        job = self.ensure_job()
        total_steps = job.total_steps or 4
        resolved_step = step if step is not None else total_steps
        resolved_progress = progress if progress is not None else 100.0
        job.error_message = None
        self._status_manager.update_job_status(
            job, "skipped", resolved_step, message, resolved_progress
        )
        return job

    def _load_and_validate_post(
        self,
    ) -> Tuple[Optional[Post], Optional[Dict[str, Any]]]:
        """Load the post and perform lifecycle validations."""
        post = Post.query.filter_by(guid=self.post_guid).first()
        if not post:
            job = self._mark_job_skipped("Post no longer exists")
            return (
                None,
                {
                    "status": "error",
                    "error_code": "NOT_FOUND",
                    "message": "Post not found",
                    "job_id": getattr(job, "id", None),
                },
            )

        if not post.whitelisted:
            job = self._mark_job_skipped("Post not whitelisted")
            return (
                None,
                {
                    "status": "error",
                    "error_code": "NOT_WHITELISTED",
                    "message": "Post not whitelisted",
                    "job_id": getattr(job, "id", None),
                },
            )

        if not post.download_url:
            self._logger.warning(
                "Post %s (%s) is whitelisted but missing download_url; marking job as failed",
                post.guid,
                post.title,
            )
            job = self.fail("Download URL missing")
            return (
                None,
                {
                    "status": "error",
                    "error_code": "MISSING_DOWNLOAD_URL",
                    "message": "Post is missing a download URL",
                    "job_id": job.id,
                },
            )

        if post.processed_audio_path and os.path.exists(post.processed_audio_path):
            try:
                job = self.skip("Post already processed")
            except Exception as err:  # pylint: disable=broad-exception-caught
                self._logger.error(
                    "Failed to mark job as completed during short-circuit for %s: %s",
                    self.post_guid,
                    err,
                )
                job = None
            return (
                None,
                {
                    "status": "skipped",
                    "message": "Post already processed",
                    "job_id": getattr(job, "id", None),
                    "download_url": f"/api/posts/{self.post_guid}/download",
                },
            )

        return post, None

    def _mark_job_skipped(self, reason: str) -> Optional[ProcessingJob]:
        job = self.get_active_job()
        if job and job.status in {"pending", "running"}:
            job.error_message = None
            total_steps = job.total_steps or job.current_step or 4
            self._status_manager.update_job_status(
                job,
                "skipped",
                total_steps,
                reason,
                100.0,
            )
            return job

        try:
            return self.skip(reason)
        except Exception as err:  # pylint: disable=broad-exception-caught
            self._logger.error(
                "Failed to mark job as skipped for %s: %s", self.post_guid, err
            )
        return job

    def start_processing(self, priority: str) -> Dict[str, Any]:
        """
        Handle the end-to-end lifecycle for a single post processing request.
        Ensures a job exists and is marked ready for the worker thread.
        """
        _, early_result = self._load_and_validate_post()
        if early_result:
            return early_result

        _db.session.expire_all()

        job = self.ensure_job()

        if job.status == "running":
            return {
                "status": "running",
                "message": "Another processing job is already running for this episode",
                "job_id": job.id,
            }

        self._status_manager.update_job_status(
            job,
            "pending",
            0,
            f"Queued for processing (priority={priority})",
            0.0,
        )

        return {
            "status": "started",
            "message": "Job queued for processing",
            "job_id": job.id,
        }
