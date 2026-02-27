import logging
import sys


def get_logger(name: str) -> logging.Logger:
    """
    Structured JSON-style logger for TuskerSquad.
    """

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
