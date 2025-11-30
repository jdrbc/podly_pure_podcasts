import contextlib
import logging
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any

from flask_sqlalchemy.session import Session as FlaskSession
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import scoped_session

logger = logging.getLogger("global_logger")

# Ensure database lock errors are always visible on stdout
_stdout_handler = logging.StreamHandler(sys.stdout)
_stdout_handler.setLevel(logging.WARNING)
_stdout_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] [DB_LOCK] %(message)s")
)
_db_lock_logger = logging.getLogger("podly.db_lock")
_db_lock_logger.addHandler(_stdout_handler)
_db_lock_logger.setLevel(logging.WARNING)
_db_lock_logger.propagate = False

_WRITE_LOCK = threading.RLock()
_WRITE_PREFIXES = (
    "insert",
    "update",
    "delete",
    "replace",
    "create",
    "drop",
    "alter",
    "with",
    "pragma",
)

DEFAULT_SQLITE_MODE = "optimistic"
DEFAULT_SQLITE_RETRY_ATTEMPTS = 8
DEFAULT_SQLITE_RETRY_BACKOFF_MS = 100


@dataclass(frozen=True)
class SQLiteConcurrencySettings:
    mode: str
    retry_attempts: int
    retry_backoff_ms: int

    @property
    def enabled(self) -> bool:
        return self.mode in ("optimistic", "pessimistic")

    @property
    def pessimistic(self) -> bool:
        return self.mode == "pessimistic"


def default_sqlite_concurrency_settings() -> SQLiteConcurrencySettings:
    """Provide sensible baked-in defaults (no env configuration)."""
    return SQLiteConcurrencySettings(
        mode=DEFAULT_SQLITE_MODE,
        retry_attempts=DEFAULT_SQLITE_RETRY_ATTEMPTS,
        retry_backoff_ms=DEFAULT_SQLITE_RETRY_BACKOFF_MS,
    )


def configure_sqlite_concurrency(
    engine: Engine, settings: SQLiteConcurrencySettings
) -> None:
    """Attach locking/retry behaviors to a SQLite engine."""
    if engine.dialect.name != "sqlite" or not settings.enabled:
        return

    logger.info(
        "SQLite concurrency mode=%s retry_attempts=%s backoff_ms=%s",
        settings.mode,
        settings.retry_attempts,
        settings.retry_backoff_ms,
    )

    RetryingSession.configure_mode(settings.mode)
    RetryingSession.configure_retry(settings)

    if settings.pessimistic:
        _install_write_lock(engine)


@contextlib.contextmanager
def pessimistic_write_lock() -> Any:
    """Use for must-succeed critical writes to serialize access explicitly."""
    _WRITE_LOCK.acquire()
    try:
        yield
    finally:
        _WRITE_LOCK.release()


def commit_with_profile(
    session: FlaskSession | OrmSession | scoped_session[Any],
    *,
    must_succeed: bool,
    context: str,
    logger_obj: logging.Logger | None = None,
) -> None:
    """
    Commit with optional pessimistic serialization; always rollback on failure to avoid
    leaving the session in an unusable state after lock errors.
    """
    log = logger_obj or logger
    lock_cm = (
        pessimistic_write_lock()
        if must_succeed and RetryingSession.is_pessimistic_mode()
        else contextlib.nullcontext()
    )
    with lock_cm:
        try:
            session.commit()
        except Exception as exc:  # pylint: disable=broad-except
            is_lock_error = isinstance(
                exc, OperationalError
            ) and _is_sqlite_locked_error(exc)
            if is_lock_error:
                _db_lock_logger.error(
                    "DATABASE LOCKED in commit_with_profile context=%s: %s",
                    context,
                    str(exc),
                )
            log.error(
                "Commit failed in %s, rolling back: %s", context, exc, exc_info=True
            )
            try:
                session.rollback()
            except Exception as rb_exc:  # pylint: disable=broad-except
                log.error(
                    "Rollback also failed in %s: %s", context, rb_exc, exc_info=True
                )
            raise


class RetryingSession(FlaskSession):
    """Session that retries SQLite writes on lock errors."""

    _retry_settings: SQLiteConcurrencySettings | None = None
    _mode: str = DEFAULT_SQLITE_MODE

    @classmethod
    def configure_retry(cls, settings: SQLiteConcurrencySettings) -> None:
        cls._retry_settings = settings if settings.enabled else None

    @classmethod
    def configure_mode(cls, mode: str) -> None:
        cls._mode = mode

    @classmethod
    def is_pessimistic_mode(cls) -> bool:
        return cls._mode == "pessimistic"

    def _rollback_safely(self, context: str) -> None:
        """Rollback after an error without tripping illegal state changes."""
        try:
            if self.is_active:
                super().rollback()
        except Exception as exc:  # pylint: disable=broad-except
            logger.error(
                "Rollback failed while handling SQLite lock during %s: %s",
                context,
                exc,
                exc_info=True,
            )

    def commit(self) -> None:
        settings = self._retry_settings
        bind = self.get_bind()
        if (
            settings is None
            or bind is None
            or bind.dialect.name != "sqlite"
            or settings.retry_attempts <= 1
        ):
            super().commit()
            return

        delay = settings.retry_backoff_ms / 1000
        attempts = settings.retry_attempts

        for attempt in range(attempts):
            try:
                super().commit()
                if attempt > 0:
                    _db_lock_logger.info(
                        "SQLite commit succeeded after %d retries", attempt
                    )
                return
            except OperationalError as exc:
                if not _is_sqlite_locked_error(exc):
                    raise
                self._rollback_safely("commit")
                _db_lock_logger.warning(
                    "DATABASE LOCKED on commit (attempt %d/%d): %s - retrying in %.2fs",
                    attempt + 1,
                    attempts,
                    str(exc),
                    delay,
                )
                logger.warning(
                    "SQLite database locked on commit (attempt %d/%d), rolling back and retrying...",
                    attempt + 1,
                    attempts,
                )
                if attempt == attempts - 1:
                    _db_lock_logger.error(
                        "DATABASE LOCKED FAILED after %d attempts: %s",
                        attempts,
                        str(exc),
                    )
                    raise
                time.sleep(delay)
                delay *= 2

    def flush(self, objects: Any = None) -> None:
        settings = self._retry_settings
        bind = self.get_bind()
        if (
            settings is None
            or bind is None
            or bind.dialect.name != "sqlite"
            or settings.retry_attempts <= 1
        ):
            super().flush(objects=objects)
            return

        delay = settings.retry_backoff_ms / 1000
        attempts = settings.retry_attempts

        for attempt in range(attempts):
            try:
                super().flush(objects=objects)
                if attempt > 0:
                    _db_lock_logger.info(
                        "SQLite flush succeeded after %d retries", attempt
                    )
                return
            except OperationalError as exc:
                if not _is_sqlite_locked_error(exc):
                    raise
                self._rollback_safely("flush")
                _db_lock_logger.warning(
                    "DATABASE LOCKED on flush (attempt %d/%d): %s - retrying in %.2fs",
                    attempt + 1,
                    attempts,
                    str(exc),
                    delay,
                )
                logger.warning(
                    "SQLite database locked on flush (attempt %d/%d), rolling back and retrying...",
                    attempt + 1,
                    attempts,
                )
                if attempt == attempts - 1:
                    _db_lock_logger.error(
                        "DATABASE LOCKED FAILED after %d attempts: %s",
                        attempts,
                        str(exc),
                    )
                    raise
                time.sleep(delay)
                delay *= 2


def _is_sqlite_locked_error(exc: OperationalError) -> bool:
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message


def _is_write_statement(statement: Any) -> bool:
    if not isinstance(statement, str):
        return False
    stripped = statement.lstrip()
    if not stripped:
        return False
    first_token = stripped.split(" ", 1)[0].lower()
    return first_token.startswith(_WRITE_PREFIXES)


def _install_write_lock(engine: Engine) -> None:
    # Pylint suggests using context managers, but SQLAlchemy event hooks require manual acquire/release.
    # pylint: disable=consider-using-with
    if getattr(engine, "_podly_write_lock_installed", False):
        return

    @event.listens_for(engine, "before_cursor_execute")
    def _before_execute(
        conn: Any,
        cursor: Any,
        statement: Any,
        parameters: Any,
        context: Any,
        executemany: Any,
    ) -> None:
        if _is_write_statement(statement):
            _WRITE_LOCK.acquire()
            context._podly_write_lock_acquired = True

    @event.listens_for(engine, "after_cursor_execute")
    def _after_execute(
        conn: Any,
        cursor: Any,
        statement: Any,
        parameters: Any,
        context: Any,
        executemany: Any,
    ) -> None:
        if getattr(context, "_podly_write_lock_acquired", False):
            _WRITE_LOCK.release()
            context._podly_write_lock_acquired = False

    @event.listens_for(engine, "handle_error")
    def _handle_error(exception_context: Any) -> None:
        ctx = exception_context.execution_context
        if ctx is not None and getattr(ctx, "_podly_write_lock_acquired", False):
            _WRITE_LOCK.release()
            ctx._podly_write_lock_acquired = False

    engine._podly_write_lock_installed = True  # type: ignore[attr-defined]
    logger.info("SQLite pessimistic concurrency enabled (single-writer lock).")
