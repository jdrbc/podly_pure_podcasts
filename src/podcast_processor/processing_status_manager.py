import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import object_session

from app.db_concurrency import (
    commit_with_profile,
)
from app.jobs_manager_run_service import recalculate_run_counts
from app.models import ProcessingJob


class ProcessingStatusManager:
    """
    Manages processing job status, creation, updates, and cleanup.
    Handles all database operations related to job tracking.
    """

    def __init__(self, db_session: Any, logger: Optional[logging.Logger] = None):
        self.db_session = db_session
        self.logger = logger or logging.getLogger(__name__)

    def generate_job_id(self) -> str:
        """Generate a unique job ID."""
        return str(uuid.uuid4())

    def create_job(
        self,
        post_guid: str,
        job_id: str,
        run_id: Optional[str] = None,
        *,
        requested_by_user_id: Optional[int] = None,
        billing_user_id: Optional[int] = None,
    ) -> ProcessingJob:
        """Create a new pending job record for the provided post."""
        # Create new job
        job = ProcessingJob(
            id=job_id,
            jobs_manager_run_id=run_id,
            post_guid=post_guid,
            status="pending",
            current_step=0,
            total_steps=4,
            progress_percentage=0.0,
            created_at=datetime.utcnow(),
            requested_by_user_id=requested_by_user_id,
            billing_user_id=billing_user_id,
        )
        self.db_session.add(job)
        if run_id:
            recalculate_run_counts(self.db_session)
        commit_with_profile(
            self.db_session,
            must_succeed=True,
            context="create_job",
            logger_obj=self.logger,
        )
        return job

    def cancel_existing_jobs(self, post_guid: str, current_job_id: str) -> None:
        """Delete any existing active jobs for this post (called when we acquire the lock).

        NOTE: Must use self.db_session.query() instead of ProcessingJob.query
        to ensure we use the same session. Using ProcessingJob.query
        (the Flask-SQLAlchemy scoped session) can cause deadlock with SQLite
        pessimistic locking when another query on self.db_session holds the write lock.
        """
        existing_jobs = (
            self.db_session.query(ProcessingJob)
            .filter_by(post_guid=post_guid)
            .filter(
                ProcessingJob.status.in_(["pending", "running"]),
                ProcessingJob.id != current_job_id,
            )
            .all()
        )

        for existing_job in existing_jobs:
            self.db_session.delete(existing_job)

        self.db_session.flush()
        recalculate_run_counts(self.db_session)
        commit_with_profile(
            self.db_session,
            must_succeed=True,
            context="cancel_existing_jobs",
            logger_obj=self.logger,
        )

    def update_job_status(
        self,
        job: ProcessingJob,
        status: str,
        step: int,
        step_name: str,
        progress: Optional[float] = None,
    ) -> None:
        """Update job status in database."""
        self.logger.info(
            "[JOB_STATUS_UPDATE] job_id=%s status=%s step=%s step_name=%s bound=%s",
            getattr(job, "id", None),
            status,
            step,
            step_name,
            object_session(job) is not None,
        )
        job.status = status
        job.current_step = step
        job.step_name = step_name

        if progress is not None:
            job.progress_percentage = progress
        else:
            # Calculate progress based on step
            job.progress_percentage = (step / job.total_steps) * 100.0

        if status == "running" and not job.started_at:
            job.started_at = datetime.utcnow()
        elif status in ["completed", "failed", "skipped", "cancelled"]:
            job.completed_at = datetime.utcnow()

        if job.jobs_manager_run_id:
            recalculate_run_counts(self.db_session)
        commit_with_profile(
            self.db_session,
            must_succeed=True,
            context="update_job_status",
            logger_obj=self.logger,
        )
        if status in {"failed", "cancelled"}:
            progress_to_log = (
                progress
                if progress is not None
                else (
                    job.progress_percentage or 0.0 if job.progress_percentage else 0.0
                )
            )
            self.logger.error(
                "[JOB_STATUS_ERROR] job_id=%s post_guid=%s status=%s step=%s step_name=%s progress=%.2f",
                getattr(job, "id", None),
                getattr(job, "post_guid", None),
                status,
                step,
                step_name,
                progress_to_log,
            )
        if self.logger:
            self.logger.debug(
                (
                    "update_job_status committed: job_id=%s status=%s step=%s progress=%.2f"
                ),
                getattr(job, "id", None),
                job.status,
                job.current_step,
                job.progress_percentage,
            )

    def mark_cancelled(self, job_id: str, error_message: Optional[str] = None) -> None:
        # Use a fresh query to ensure we get the latest state
        job = self.db_session.query(ProcessingJob).filter_by(id=job_id).first()
        if not job:
            return

        job.status = "cancelled"
        job.error_message = error_message
        job.completed_at = datetime.utcnow()

        run_id = job.jobs_manager_run_id
        if run_id:
            recalculate_run_counts(self.db_session)
        commit_with_profile(
            self.db_session,
            must_succeed=True,
            context="mark_cancelled",
            logger_obj=self.logger,
        )
        self.logger.info(f"Successfully cancelled job {job_id}")
