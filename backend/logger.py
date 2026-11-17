"""Structured JSON & console logging with `contextvars` correlation (`request_id`, `session_id`)."""

from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import sys
from typing import Any

from backend.config import settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
session_id_var: ContextVar[str] = ContextVar("session_id", default="-")

_STANDARD_RECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()) | {
    "message",
    "asctime",
}


def set_log_context(*, request_id: str | None = None, session_id: str | None = None) -> None:
    """Bind `request_id` and/or `session_id` to the current async execution context."""
    if request_id is not None:
        request_id_var.set(request_id)
    if session_id is not None:
        session_id_var.set(session_id)


class StructuredLogFormatter(logging.Formatter):
    """Emit single-line UTF-8 JSON (for Liara/Docker stdout) or compact key=value console logs."""

    def __init__(self, fmt_mode: str = "json") -> None:
        super().__init__()
        self.fmt_mode = (fmt_mode or "json").strip().lower()

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds")
        req_id = getattr(record, "request_id", None) or request_id_var.get()
        sess_id = getattr(record, "session_id", None) or session_id_var.get()
        msg = record.getMessage()

        extras: dict[str, Any] = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _STANDARD_RECORD_ATTRS and not k.startswith("_") and k not in ("request_id", "session_id")
        }

        if self.fmt_mode == "console":
            ctx = f"req={req_id}" + (f" sess={sess_id}" if sess_id != "-" else "")
            kv = " ".join(f"{k}={v}" for k, v in extras.items())
            line = f"{ts} {record.levelname:<7} [{ctx}] {record.name}: {msg}"
            if kv:
                line = f"{line} | {kv}"
            if record.exc_info:
                line = f"{line}\n{self.formatException(record.exc_info)}"
            return line

        payload: dict[str, Any] = {
            "timestamp": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": msg,
            "request_id": req_id,
            "session_id": sess_id,
            **extras,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str | None = None, fmt_mode: str | None = None) -> None:
    """Configure root logger with `StructuredLogFormatter` and quiet noisy third-party transport logs."""
    resolved_level = getattr(logging, (level or settings.log_level or "INFO").upper(), logging.INFO)
    resolved_fmt = fmt_mode or settings.log_format or "json"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredLogFormatter(fmt_mode=resolved_fmt))

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(resolved_level)
    root.addHandler(handler)

    if resolved_level > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
