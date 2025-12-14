"""Shared helpers to protect long-lived sessions in background threads."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy.exc import OperationalError, PendingRollbackError
from sqlalchemy.orm import Session, scoped_session

SessionType = Session | scoped_session[Any]


def reset_session(
    session: SessionType,
    logger: logging.Logger,
    context: str,
    exc: Exception | None = None,
) -> None:
    """
    Roll back and remove a session after a failure to avoid leaving it in a bad state.
    Safe to call even if the session is already closed/invalid.
    """
    if exc:
        logger.warning(
            "[SESSION_RESET] context=%s exc=%s; rolling back and removing session",
            context,
            exc,
        )
    try:
        session.rollback()
    except Exception as rb_exc:  # pylint: disable=broad-except
        logger.warning(
            "[SESSION_RESET] rollback failed in context=%s: %s", context, rb_exc
        )
    try:
        remove_fn = getattr(session, "remove", None)
        if callable(remove_fn):
            remove_fn()
    except Exception as rm_exc:  # pylint: disable=broad-except
        logger.warning(
            "[SESSION_RESET] remove failed in context=%s: %s", context, rm_exc
        )


@contextmanager
def db_guard(
    context: str, session: SessionType, logger: logging.Logger
) -> Iterator[None]:
    """
    Guard a block of DB work so lock/rollback errors always clean the session
    before propagating.
    """
    try:
        yield
    except (OperationalError, PendingRollbackError) as exc:
        reset_session(session, logger, context, exc)
        raise
