import contextlib
import logging
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from flask_sqlalchemy.session import Session as FlaskSession
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import scoped_session

logger = logging.getLogger("global_logger")
_db_trace_logger: logging.Logger | None = None

# Ensure database lock errors are always visible on stdout
_stdout_handler = logging.StreamHandler(sys.stdout)
_stdout_handler.setLevel(logging.WARNING)
_stdout_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] [DB_LOCK] %(message)s")
)
_db_lock_logger = logging.getLogger("podly.db_lock")
_db_lock_logger.addHandler(_stdout_handler)
_db_lock_logger.setLevel(logging.WARNING)
# Allow propagation so platform log collectors that listen to root (e.g., Railway UI) also see DB_LOCK entries
_db_lock_logger.propagate = True

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

DEFAULT_SQLITE_MODE = "pessimistic"  # serialize SQLite writers to avoid lock storms
DEFAULT_SQLITE_RETRY_ATTEMPTS = 12
DEFAULT_SQLITE_RETRY_BACKOFF_MS = 200


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
    _install_query_trace(engine)
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
                _db_lock_logger.error(
                    _format_sqlite_lock_log(
                        exc,
                        statement=getattr(exc, "statement", None),
                        params=getattr(exc, "params", None),
                        context="commit",
                    )
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
                _db_lock_logger.error(
                    _format_sqlite_lock_log(
                        exc,
                        statement=getattr(exc, "statement", None),
                        params=getattr(exc, "params", None),
                        context="flush",
                    )
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
        orig = exception_context.original_exception
        if isinstance(orig, OperationalError) and _is_sqlite_locked_error(orig):
            _db_lock_logger.error(
                _format_sqlite_lock_log(
                    orig,
                    statement=getattr(exception_context, "statement", None),
                    params=getattr(exception_context, "parameters", None),
                    context="handle_error",
                )
            )

    engine._podly_write_lock_installed = True  # type: ignore[attr-defined]
    logger.info("SQLite pessimistic concurrency enabled (single-writer lock).")


def _format_sqlite_lock_log(
    exc: OperationalError, *, statement: Any = None, params: Any = None, context: str
) -> str:
    stmt_preview = ""
    if isinstance(statement, str):
        stmt_preview = statement.strip().replace("\n", " ")
        if len(stmt_preview) > 300:
            stmt_preview = stmt_preview[:300] + "...<truncated>"
    params_preview = ""
    if params is not None:
        params_str = str(params)
        if len(params_str) > 300:
            params_preview = params_str[:300] + "...<truncated>"
        else:
            params_preview = params_str
    return (
        f"[SQLITE_LOCK] context={context} thread={threading.current_thread().name} "
        f'time={datetime.utcnow().isoformat()} statement="{stmt_preview}" '
        f'params="{params_preview}" exc={exc}'
    )


def _preview(obj: Any, max_len: int = 500) -> str:
    if obj is None:
        return ""
    text = str(obj).replace("\n", " ").strip()
    if len(text) > max_len:
        return text[:max_len] + "...<truncated>"
    return text


def _install_query_trace(engine: Engine) -> None:
    """
    Attach detailed tracing for every SQL execution. Logs start/end with thread, duration,
    statement, and params to the global logger (DEBUG level).
    """
    if getattr(engine, "_podly_query_trace_installed", False):
        return

    def _trace_logger() -> logging.Logger:
        global _db_trace_logger  # pylint: disable=global-statement
        if _db_trace_logger is not None:
            return _db_trace_logger
        _db_trace_logger = logging.getLogger("podly.db_trace")
        _db_trace_logger.setLevel(logging.DEBUG)
        _db_trace_logger.propagate = False
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        # File handler only to avoid flooding stdout in production
        try:
            fh = logging.FileHandler("src/instance/logs/db_trace.log")
            fh.setFormatter(fmt)
            _db_trace_logger.addHandler(fh)
        except OSError:
            pass
        return _db_trace_logger

    trace_logger = _trace_logger()

    def _before_execute(
        conn: Any,
        cursor: Any,
        statement: Any,
        parameters: Any,
        context: Any,
        executemany: Any,
    ) -> None:
        context._podly_trace_start = time.perf_counter()
        trace_logger.debug(
            '[DB_TRACE][start] thread=%s statement="%s" params="%s"',
            threading.current_thread().name,
            _preview(statement),
            _preview(parameters),
        )

    def _after_execute(
        conn: Any,
        cursor: Any,
        statement: Any,
        parameters: Any,
        context: Any,
        executemany: Any,
    ) -> None:
        start = getattr(context, "_podly_trace_start", None)
        duration_ms = (time.perf_counter() - start) * 1000 if start else 0.0
        rowcount = getattr(cursor, "rowcount", None)
        trace_logger.debug(
            '[DB_TRACE][end] thread=%s duration_ms=%.2f rowcount=%s statement="%s" params="%s"',
            threading.current_thread().name,
            duration_ms,
            rowcount,
            _preview(statement),
            _preview(parameters),
        )

    event.listen(engine, "before_cursor_execute", _before_execute)
    event.listen(engine, "after_cursor_execute", _after_execute)
    engine._podly_query_trace_installed = True  # type: ignore[attr-defined]
    logger.info("DB trace logging enabled for engine.")
