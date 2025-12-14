from __future__ import annotations

import logging
from typing import Any


def safe_commit(
    session: Any,
    *,
    context: str,
    logger_obj: logging.Logger | None = None,
    must_succeed: bool = True,
) -> None:
    """Commit the current transaction and rollback on failure.

    This is a minimal replacement for the old SQLite concurrency helpers.
    """
    log = logger_obj or logging.getLogger("global_logger")
    try:
        session.commit()
    except Exception as exc:  # pylint: disable=broad-except
        log.error("Commit failed in %s, rolling back: %s", context, exc, exc_info=True)
        try:
            session.rollback()
        except Exception as rb_exc:  # pylint: disable=broad-except
            log.error("Rollback also failed in %s: %s", context, rb_exc, exc_info=True)
        if must_succeed:
            raise
