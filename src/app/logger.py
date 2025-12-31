import json
import logging
import os


class ExtraFormatter(logging.Formatter):
    """Formatter that appends structured extras to log lines.

    Any LogRecord attributes not in the standard set are captured into a JSON
    object and appended as ``extra={...}`` so contextual fields are visible in
    plain-text logs.
    """

    _standard_attrs = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
    }

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        base = super().format(record)
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in self._standard_attrs
        }
        if extras:
            try:
                extras_json = json.dumps(extras, ensure_ascii=True, default=str)
            except Exception:
                extras_json = str(extras)
            return f"{base} | extra={extras_json}"
        return base


def setup_logger(
    name: str, log_file: str, level: int = logging.DEBUG
) -> logging.Logger:
    """Create or return a configured logger.

    - Writes to the specified log_file
    - Emits to console exactly once (no duplicates)
    - Disables propagation to avoid duplicate root handling
    - Guards against adding duplicate handlers across repeated calls
    """
    file_formatter = ExtraFormatter("%(asctime)s %(levelname)s %(message)s")
    console_formatter = ExtraFormatter("%(levelname)s  [%(name)s] %(message)s")

    logger = logging.getLogger(name)
    logger.setLevel(level)
    # Prevent records from also bubbling up to root logger handlers (which can cause duplicates)
    logger.propagate = False

    # Ensure directory exists for log file
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    # Add file handler if not already present for this file
    abs_log_file = os.path.abspath(log_file)
    has_file_handler = any(
        isinstance(h, logging.FileHandler)
        and getattr(h, "baseFilename", None) == abs_log_file
        for h in logger.handlers
    )
    if not has_file_handler:
        file_handler = logging.FileHandler(abs_log_file)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    # Add a single console handler if not already present
    has_stream_handler = any(
        isinstance(h, logging.StreamHandler) for h in logger.handlers
    )
    if not has_stream_handler:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(console_formatter)
        logger.addHandler(stream_handler)

    return logger
