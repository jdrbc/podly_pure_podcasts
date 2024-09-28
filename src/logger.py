import logging


def setup_logger(name: str, log_file, level=logging.INFO) -> logging.Logger:
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    logger = logging.getLogger(name)
    logger.setLevel(level)

    handler = logging.FileHandler(log_file)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger
