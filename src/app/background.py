from datetime import datetime, timedelta
from typing import Optional

from app.extensions import scheduler
from app.jobs_manager import (
    scheduled_refresh_all_feeds,
)
from app.post_cleanup import scheduled_cleanup_processed_posts


def add_background_job(minutes: int) -> None:
    """Add the recurring background job for refreshing feeds.

    minutes: interval in minutes; must be a positive integer.
    """

    scheduler.add_job(
        id="refresh_all_feeds",
        func=scheduled_refresh_all_feeds,
        trigger="interval",
        minutes=minutes,
        replace_existing=True,
    )


def schedule_cleanup_job(retention_days: Optional[int]) -> None:
    """Ensure the periodic cleanup job is scheduled or disabled as needed."""
    job_id = "cleanup_processed_posts"
    if retention_days is None or retention_days <= 0:
        try:
            scheduler.remove_job(job_id)
        except Exception:
            # Job may not be scheduled; ignore.
            pass
        return

    # Run daily; allow scheduler to coalesce missed runs.
    scheduler.add_job(
        id=job_id,
        func=scheduled_cleanup_processed_posts,
        trigger="interval",
        hours=24,
        next_run_time=datetime.utcnow() + timedelta(minutes=15),
        replace_existing=True,
    )
