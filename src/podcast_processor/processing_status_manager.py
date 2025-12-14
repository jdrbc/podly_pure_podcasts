import logging
import uuid
from datetime import datetime
from typing import Any, Optional, cast

from sqlalchemy.orm import object_session

from app.models import ProcessingJob
from app.writer.client import writer_client


class ProcessingStatusManager:
    """
    Manages processing job status, creation, updates, and cleanup.
    Handles all database operations related to job tracking via Writer Service.
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
        job_data = {
            "id": job_id,
            "jobs_manager_run_id": run_id,
            "post_guid": post_guid,
            "status": "pending",
            "current_step": 0,
            "total_steps": 4,
            "progress_percentage": 0.0,
            "created_at": datetime.utcnow().isoformat(),
            "requested_by_user_id": requested_by_user_id,
            "billing_user_id": billing_user_id,
        }

        writer_client.action("create_job", {"job_data": job_data}, wait=True)

        self.db_session.expire_all()
        job = self.db_session.get(ProcessingJob, job_id)
        if not job:
            raise RuntimeError(f"Failed to create job {job_id}")
        return cast(ProcessingJob, job)

    def cancel_existing_jobs(self, post_guid: str, current_job_id: str) -> None:
        """Delete any existing active jobs for this post."""
        writer_client.action(
            "cancel_existing_jobs",
            {"post_guid": post_guid, "current_job_id": current_job_id},
            wait=True,
        )
        self.db_session.expire_all()

    def update_job_status(
        self,
        job: ProcessingJob,
        status: str,
        step: int,
        step_name: str,
        progress: Optional[float] = None,
    ) -> None:
        """Update job status in database."""
        # Cache job attributes before any operations that might expire the object
        job_id = job.id
        total_steps = job.total_steps
        is_bound = object_session(job) is not None

        self.logger.info(
            "[JOB_STATUS_UPDATE] job_id=%s status=%s step=%s step_name=%s bound=%s",
            job_id,
            status,
            step,
            step_name,
            is_bound,
        )

        if progress is None:
            progress = (step / total_steps) * 100.0

        writer_client.action(
            "update_job_status",
            {
                "job_id": job_id,
                "status": status,
                "step": step,
                "step_name": step_name,
                "progress": progress,
            },
            wait=True,
        )

        self.db_session.expire_all()

        if status in {"failed", "cancelled"}:
            self.logger.error(
                "[JOB_STATUS_ERROR] job_id=%s post_guid=%s status=%s step=%s step_name=%s progress=%.2f",
                job_id,
                job.post_guid,  # post_guid is safe - not cached but accessed before expire_all
                status,
                step,
                step_name,
                progress,
            )

    def mark_cancelled(self, job_id: str, error_message: Optional[str] = None) -> None:
        writer_client.action(
            "mark_cancelled", {"job_id": job_id, "reason": error_message}, wait=True
        )
        self.db_session.expire_all()
        self.logger.info(f"Successfully cancelled job {job_id}")
