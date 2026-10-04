"""
Logging setup and redaction filter for SatyaSetu.
Ensures request ids are tracked and PII is scrubbed before writing to streams.
"""

import contextvars
import logging
import sys
from typing import Any

from app.core.redaction import redact

# Context variable for tracking request ID across async tasks
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


class RedactionFilter(logging.Filter):
    """
    Logging filter that sanitizes log records by redacting phone numbers,
    emails, and sensitive digit runs from log messages.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Add request_id to record if not set
        if not hasattr(record, "request_id") or not record.request_id:
            record.request_id = request_id_var.get() or "no-req-id"

        # Redact the main message
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)

        # Redact arguments if present
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: (redact(v) if isinstance(v, str) else v)
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    redact(arg) if isinstance(arg, str) else arg
                    for arg in record.args
                )

        return True


def configure_logging(level: str = "INFO") -> None:
    """
    Configure root logging with RedactionFilter and uniform format.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Clear existing handlers to avoid duplicates
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(numeric_level)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(request_id)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    handler.addFilter(RedactionFilter())

    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the given name.
    """
    return logging.getLogger(name)
