"""Structured JSON logging module."""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add all extra fields passed via the `extra=` kwarg.
        _STANDARD_ATTRS = frozenset({
            "args", "created", "exc_info", "exc_text", "filename", "funcName",
            "levelname", "levelno", "lineno", "message", "module", "msecs",
            "msg", "name", "pathname", "process", "processName",
            "relativeCreated", "stack_info", "thread", "threadName",
            "taskName",
        })
        for key, val in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                log_data[key] = val

        return json.dumps(log_data)


def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Setup a logger with JSON formatting.
    
    Args:
        name: Logger name
        level: Logging level (default: INFO)
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Create handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    # Set formatter
    formatter = JSONFormatter()
    handler.setFormatter(formatter)

    logger.addHandler(handler)
    logger.propagate = False

    return logger


def configure_file_logging(log_file: Path, level: int = logging.INFO) -> None:
    """Reconfigure the global logger to write all output to *log_file*.

    Warnings and errors are also mirrored to stderr so they remain visible
    on the terminal alongside normal dashboard output.
    """
    _logger = logging.getLogger("s3_dashboard")
    _logger.handlers.clear()

    formatter = JSONFormatter()

    fh = logging.FileHandler(log_file)
    fh.setLevel(level)
    fh.setFormatter(formatter)
    _logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.WARNING)
    sh.setFormatter(formatter)
    _logger.addHandler(sh)


# Global logger instance
logger = setup_logger("s3_dashboard")
