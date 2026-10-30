"""Structured, redaction-by-construction logging. Standard library only.

Rule (MEDIA-2.0 section 5, AVR-385): a log line carries the route TEMPLATE, status, duration, the
adapter/service name and an error CLASS. Never a username, e-mail, group, raw header, title, item
id, upstream URL, key or exception message.

The helper enforces that structurally instead of by habit: `log_event` accepts only a fixed set
of field names, and a string value must look like an identifier (letters, digits and `_./{}:-`,
at most 64 characters) or it is replaced by `invalid`. A title or a username cannot be passed
through by mistake because it would not survive the check. The JSON formatter prints those
fields only; for an exception it prints the class name, never the message or the traceback.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from typing import Any

ALLOWED_FIELDS = frozenset({"route", "method", "status", "duration_ms", "service", "section",
                            "state", "reason", "error_class", "count",
                            "ref"})       # ref: a short one-way hash (komga_keys.subject_ref), never an identity
_IDENT = re.compile(r"[A-Za-z0-9_./{}:\-]{0,64}\Z")
_METHOD = re.compile(r"[A-Z]{1,12}\Z")
ATTR = "avrana_fields"
HANDLER_MARK = "_avrana_json_handler"

access_log = logging.getLogger("avrana_home.access")
app_log = logging.getLogger("avrana_home.app")


def safe_value(name: str, value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if name == "method":
        return value if isinstance(value, str) and _METHOD.fullmatch(value) else "invalid"
    if isinstance(value, str) and _IDENT.fullmatch(value):
        return value
    return "invalid"


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """`event` is a fixed literal chosen by the caller (never request data)."""
    clean = {}
    for name, value in fields.items():
        if name not in ALLOWED_FIELDS:
            raise ValueError(f"log field not allowed: {name}")
        clean[name] = safe_value(name, value)
    if logger.isEnabledFor(level):
        logger.log(level, event, extra={ATTR: clean})


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Free text appears only for our own loggers' fixed messages."""

    OWN = ("avrana_home", "uvicorn.error")

    def format(self, record: logging.LogRecord) -> str:
        doc = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
               "level": record.levelname, "logger": record.name}
        fields = getattr(record, ATTR, None)
        if fields is not None:
            doc["event"] = record.msg if isinstance(record.msg, str) else "event"
            doc.update(fields)
        elif record.name.startswith(self.OWN):
            doc["event"] = record.getMessage()[:300]
        else:
            doc["event"] = "log"
        if record.exc_info and record.exc_info[0] is not None:
            doc["error_class"] = record.exc_info[0].__name__      # class only, never the message
        return json.dumps(doc, sort_keys=True)


def silence_uvicorn_access() -> None:
    """uvicorn's access log prints the raw request target, query string included. Switch it off
    whoever started the server (also pass --no-access-log / access_log=False)."""
    lg = logging.getLogger("uvicorn.access")
    lg.handlers.clear()
    lg.propagate = False
    lg.disabled = True


def configure_logging(level: str = "INFO", stream=None) -> None:
    """Idempotent. Called by the server entry points, never by `create_app` or at import."""
    silence_uvicorn_access()
    root = logging.getLogger("avrana_home")
    root.setLevel(getattr(logging, level, logging.INFO))
    if not any(getattr(h, HANDLER_MARK, False) for h in root.handlers):
        handler = logging.StreamHandler(stream or sys.stderr)
        handler.setFormatter(JsonFormatter())
        setattr(handler, HANDLER_MARK, True)
        root.addHandler(handler)
    err = logging.getLogger("uvicorn.error")
    err.handlers.clear()
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    err.addHandler(handler)
    err.propagate = False


class ForbiddenValues:
    """Test helper: does any log record contain a forbidden string anywhere (message, args,
    exc_info, extra attributes)?"""

    def __init__(self, forbidden):
        self.forbidden = [f for f in forbidden if f]

    def scan(self, record: logging.LogRecord) -> list:
        blob = []
        for key, value in vars(record).items():
            blob.append(f"{key}={value!r}")
        try:
            blob.append(record.getMessage())
        except Exception:
            pass
        if record.exc_info:
            import traceback
            blob.append("".join(traceback.format_exception(*record.exc_info)))
        text = "\n".join(blob)
        return [f for f in self.forbidden if f in text]
