"""Structured logging configuration for the GitHub Issue Triage service."""
import logging
import os


def configure_logging() -> None:
    """Configure root logger based on environment.

    Set LOG_LEVEL env var to control verbosity (default: INFO).
    Set LOG_FORMAT=json for structured JSON output (useful in production).
    """
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_format = os.getenv("LOG_FORMAT", "text").lower()

    if log_format == "json":
        fmt = (
            '{"time": "%(asctime)s", "level": "%(levelname)s", '
            '"logger": "%(name)s", "message": %(message)r}'
        )
    else:
        fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format=fmt,
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
