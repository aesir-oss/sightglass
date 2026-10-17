"""Structured logging setup shared by the API and the workers."""

# stdlib logging is imported only to route third-party records (procrastinate's) into the same structured output.
import logging
import sys
from typing import Any, TextIO

import structlog

_LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40, "critical": 50}
# get_logger's name travels under this key until the first processor renames it to `logger`. structlog's lazy logger
# can't take `logger` as an initial value, and binding it eagerly would fix the configuration at import time.
_NAME_KEY = "_sightglass_logger"


def _logger_name(
    _: structlog.typing.WrappedLogger, __: str, event_dict: structlog.typing.EventDict
) -> structlog.typing.EventDict:
    if (name := event_dict.pop(_NAME_KEY, None)) is not None:
        event_dict.setdefault("logger", name)
    return event_dict


def configure_logging(level: str = "info", *, json: bool = True, stream: TextIO | None = None) -> None:
    """Configure structlog for the whole process, and render stdlib log records from libraries the same way.

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
            _logger_name,
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
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                renderer,
            ],
            foreign_pre_chain=[
                structlog.stdlib.add_log_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.ExtraAdder(),
                structlog.processors.TimeStamper(fmt="iso", utc=True),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(threshold)


def get_logger(name: str) -> structlog.typing.FilteringBoundLogger:
    """Return a logger that adds ``logger=name`` to every event.

    The logger is lazy, so one created at import time follows :func:`configure_logging` when it runs later.

    Args:
        name: Component name, usually the module's ``__name__``.

    Returns:
        A structlog logger.
    """
    logger: structlog.typing.FilteringBoundLogger = structlog.get_logger(**{_NAME_KEY: name})
    return logger
