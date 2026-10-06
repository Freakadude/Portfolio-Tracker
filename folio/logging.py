import logging
import sys
from collections import deque
from contextvars import ContextVar
from typing import Any

import structlog
from structlog.typing import EventDict

from folio.security.redact import scrub_value

# Request ID for web requests, job ID for worker jobs (NFR-09).
correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def _add_correlation_id(_: Any, __: str, event: EventDict) -> EventDict:
    cid = correlation_id.get()
    if cid is not None:
        event.setdefault("request_id", cid)
    return event


def _redact(_: Any, __: str, event: EventDict) -> EventDict:
    scrubbed = scrub_value(event)
    return scrubbed if isinstance(scrubbed, dict) else event


_PROBLEMS: deque[str] = deque(maxlen=200)


class _RecentProblems(logging.Handler):
    """Keeps the last warnings and errors, already scrubbed, for the diagnostics file."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            _PROBLEMS.append(self.format(record)[:4000])
        except Exception:  # noqa: BLE001 - logging must never break the request it describes
            self.handleError(record)


def recent_problems() -> list[str]:
    return list(_PROBLEMS)


def configure_logging(level: str = "INFO", stream: Any = None) -> None:
    """JSON lines on stdout for our code and for stdlib loggers (uvicorn, sqlalchemy, ...)."""
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_correlation_id,
    ]
    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    handler = logging.StreamHandler(stream or sys.stdout)
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _redact,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler.setFormatter(formatter)
    problems = _RecentProblems(level=logging.WARNING)
    problems.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = [handler, problems]
    root.setLevel(level.upper())


def get_logger(name: str = "folio") -> Any:
    return structlog.stdlib.get_logger(name)
