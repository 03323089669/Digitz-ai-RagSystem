"""
Enterprise logging module for Digitz AI.
Structured logging with levels, timestamps, and request tracking.
"""
import logging
import sys
import json
import time
from datetime import datetime, timezone
from pathlib import Path


LOG_FORMAT = '[%(levelname)s] %(name)s | %(asctime)s | %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


class StructuredFormatter(logging.Formatter):
    """Formats logs as structured JSON for production, text for dev."""

    def __init__(self, fmt: str = LOG_FORMAT, datefmt: str = DATE_FORMAT):
        super().__init__(fmt, datefmt)

    def format(self, record: logging.LogRecord) -> str:
        # Always include basic info
        log_entry = {
            'timestamp': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            'level': record.levelname,
            'module': record.name,
            'message': record.getMessage(),
        }
        # Include exception info if present
        if record.exc_info and record.exc_info[0]:
            log_entry['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
            }
        # Include extra fields
        if hasattr(record, 'extra'):
            log_entry.update(record.extra)

        # Use JSON in production-like environments, text for dev
        if sys.stderr.isatty():
            return super().format(record)
        return json.dumps(log_entry)


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Get a configured logger instance."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredFormatter())
        logger.addHandler(handler)

    return logger


# Convenience decorator for timing functions
def log_time(logger: logging.Logger = None):
    """Decorator that logs execution time of a function."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            _log = logger or get_logger(func.__module__)
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                elapsed = time.perf_counter() - start
                _log.info(f"{func.__name__} completed in {elapsed:.3f}s")
                return result
            except Exception as e:
                elapsed = time.perf_counter() - start
                _log.error(f"{func.__name__} failed after {elapsed:.3f}s: {e}")
                raise
        return wrapper
    return decorator

