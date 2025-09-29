from app.extensions import scheduler


def add_background_job(minutes: int) -> None:
    """Add the recurring background job for refreshing feeds.

    minutes: interval in minutes; must be a positive integer.
    """
    from app.job_manager import (  # pylint: disable=import-outside-toplevel
        scheduled_refresh_all_feeds,
    )

    scheduler.add_job(
        id="refresh_all_feeds",
        func=scheduled_refresh_all_feeds,
        trigger="interval",
        minutes=minutes,
        replace_existing=True,
    )
