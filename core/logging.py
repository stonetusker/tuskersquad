import logging
import json
import sys
from datetime import datetime


class JsonFormatter(logging.Formatter):

    def format(self, record):

        log_record = {

            "time": datetime.utcnow().isoformat(),

            "level": record.levelname,

            "logger": record.name,

            "message": record.getMessage(),
        }

        return json.dumps(log_record)


def get_logger(name):

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:

        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())

        logger.addHandler(handler)

    return logger