from __future__ import annotations

import logging
import sys
from typing import Iterable


class SecretMaskingFilter(logging.Filter):
    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        self._secrets = tuple(s for s in secrets if s)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = message
        for secret in self._secrets:
            redacted = redacted.replace(secret, "***REDACTED***")
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging(level: str, secrets: Iterable[str] = ()) -> logging.Logger:
    logger = logging.getLogger("dba_agent")
    logger.setLevel(level)
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            '{"time":"%(asctime)s","level":"%(levelname)s",'
            '"logger":"%(name)s","message":"%(message)s"}'
        )
    )
    handler.addFilter(SecretMaskingFilter(secrets))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
