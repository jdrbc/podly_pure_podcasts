import logging
import os


def setup_logger(
    name: str, log_file: str, level: int = logging.DEBUG
) -> logging.Logger:
    """Create or return a configured logger.

    - Writes to the specified log_file
    - Emits to console exactly once (no duplicates)
    - Disables propagation to avoid duplicate root handling
    - Guards against adding duplicate handlers across repeated calls
    """
    file_formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    console_formatter = logging.Formatter("%(levelname)s  [%(name)s] %(message)s")

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
