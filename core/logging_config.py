"""
Aethelgard v2 — Structured Logging Configuration

Production-grade structured logging with context propagation,
correlation IDs, and multi-sink output (console + file + JSON).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import structlog


def setup_logging(log_level: str = "INFO", log_dir: str = "./logs") -> None:
    """
    Configure structured logging for the entire platform.
    
    Uses structlog for structured JSON logging with:
    - Correlation ID propagation
    - Timestamp formatting
    - Color console output (development)
    - JSON file output (production)
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    # Shared processors for all outputs
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Console handler with colored output
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(colors=True),
            ],
        )
    )

    # JSON file handler
    json_handler = logging.FileHandler(log_path / "aethelgard.json")
    json_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        )
    )

    # Apply handlers to root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(json_handler)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a named structured logger."""
    return structlog.get_logger(name)


def bind_context(**kwargs) -> None:
    """Bind context variables for log correlation."""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear all context variables."""
    structlog.contextvars.clear_contextvars()
