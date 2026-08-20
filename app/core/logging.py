"""Structured JSON logging (ADR-012).

Every log line is a single JSON object to stdout with at least ``timestamp``,
``level``, ``logger``, ``event`` and (inside a request) ``request_id``,
``path``, ``method``, ``status``, ``duration_ms``. PII (names, emails, notes,
tokens, email bodies, passwords) must never be logged.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, cast

import structlog

# Event names used by the request middleware and domain services.
ACCESS_LOG_EVENT = "http.request"


def configure_logging(log_level: str = "INFO", *, json_logs: bool = True) -> None:
    """Configure structlog + stdlib logging to emit JSON lines to stdout."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
    ]

    if json_logs:
        renderer: Any = structlog.processors.JSONRenderer(ensure_ascii=False)
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Keep uvicorn access logs from double-printing raw text; route them through
    # the same JSON formatter.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # silence noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
