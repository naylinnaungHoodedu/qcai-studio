"""Application logs as one JSON object per line, the shape Cloud Logging reads (plan Phase 1, item I).

Before this, the API configured no logging. Uvicorn sets up only its own loggers, so application records
at INFO were dropped, and WARNING and above reached stderr as bare text through Python's last-resort
handler (task 1.7, finding 2). Now each record is one line with `severity`, `message`, `logger` and `time`,
plus any fields passed as `extra={"json_fields": {...}}`, which the platform keeps as queryable fields.
The Phase 1 SLIs and the alert on overrides are built from those fields (`infra/cloudrun/observability.md`).
A traceback stays inside its record's message, so a failure is one entry, not one entry per line.
"""

from datetime import UTC, datetime
import json
import logging
import sys
from typing import TextIO

from app.core.log_redaction import redact

FIELDS = "json_fields"
_ENTRY_KEYS = ("logger", "message", "severity", "time")
# The application's own loggers log from INFO; libraries from WARNING, which keeps httpx's per-request
# INFO lines out. Uvicorn keeps its own handlers and does not propagate to the root logger.
_APPLICATION_LOGGERS = ("qcai", "app")


def severity(levelno: int) -> str:
    for threshold, name in ((logging.CRITICAL, "CRITICAL"), (logging.ERROR, "ERROR"), (logging.WARNING, "WARNING"), (logging.INFO, "INFO")):
        if levelno >= threshold:
            return name
    return "DEBUG"


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            message = f"{message}\n{record.exc_text}"
        entry = {
            "severity": severity(record.levelno),
            "message": message,
            "logger": record.name,
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        }
        fields = getattr(record, FIELDS, None)
        if isinstance(fields, dict):
            entry.update({str(key): value for key, value in fields.items() if str(key) not in _ENTRY_KEYS})
        # The record factory has already masked the message; this masks the extra fields too.
        return redact(json.dumps(entry, default=str, sort_keys=True))


class JsonLineHandler(logging.StreamHandler):
    pass


def configure_logging(stream: TextIO | None = None) -> logging.Handler:
    """Send every record through one JSON-line handler on the root logger. Calling it again replaces it."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, JsonLineHandler):
            root.removeHandler(handler)
    handler = JsonLineHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(JsonLineFormatter())
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    for name in _APPLICATION_LOGGERS:
        logging.getLogger(name).setLevel(logging.INFO)
    return handler
