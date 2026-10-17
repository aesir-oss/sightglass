"""Structured logging setup shared by the API and the workers."""

import sys
from typing import Any, TextIO

import structlog

_LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40, "critical": 50}


def configure_logging(level: str = "info", *, json: bool = True, stream: TextIO | None = None) -> None:
    """Configure structlog for the whole process.

    Args:
        level: Minimum level to emit: debug, info, warning, error or critical (case-insensitive).
        json: Render one JSON object per line when true, key=value pairs when false.
        stream: Where to write log lines. Defaults to standard error.

    Raises:
        ValueError: If ``level`` isn't a known level name.
    """
    try:
        threshold = _LEVELS[level.lower()]
    except KeyError:
        raise ValueError(f"unknown log level {level!r}; expected one of {', '.join(_LEVELS)}") from None

    renderer: Any = structlog.processors.JSONRenderer() if json else structlog.processors.KeyValueRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(threshold),
        logger_factory=structlog.PrintLoggerFactory(file=stream or sys.stderr),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> structlog.typing.FilteringBoundLogger:
    """Return a logger bound with the component name.

    Args:
        name: Component name, usually the module's ``__name__``.

    Returns:
        A structlog logger with ``logger=name`` bound.
    """
    logger: structlog.typing.FilteringBoundLogger = structlog.get_logger().bind(logger=name)
    return logger
