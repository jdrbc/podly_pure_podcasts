import contextlib
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from flask_sqlalchemy.session import Session as FlaskSession
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

logger = logging.getLogger("global_logger")

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
DEFAULT_SQLITE_RETRY_ATTEMPTS = 5
DEFAULT_SQLITE_RETRY_BACKOFF_MS = 50


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


class RetryingSession(FlaskSession):
    """Session that retries SQLite writes on lock errors."""

    _retry_settings: SQLiteConcurrencySettings | None = None

    @classmethod
    def configure_retry(cls, settings: SQLiteConcurrencySettings) -> None:
        cls._retry_settings = settings if settings.enabled else None

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
                return
            except OperationalError as exc:
                if not _is_sqlite_locked_error(exc):
                    raise
                if attempt == attempts - 1:
                    raise
                # Rollback to reset session state before retry
                logger.warning(
                    "SQLite database locked on commit (attempt %d/%d), rolling back and retrying...",
                    attempt + 1,
                    attempts,
                )
                super().rollback()
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
                return
            except OperationalError as exc:
                if not _is_sqlite_locked_error(exc):
                    raise
                if attempt == attempts - 1:
                    raise
                # Rollback to reset session state before retry
                logger.warning(
                    "SQLite database locked on flush (attempt %d/%d), rolling back and retrying...",
                    attempt + 1,
                    attempts,
                )
                super().rollback()
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
