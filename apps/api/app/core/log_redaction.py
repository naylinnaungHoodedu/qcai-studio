"""Scrub credentials from every log record (plan Action 24, AC-1-8).

Installed as the log-record factory, so it applies to every logger (httpx included) and to exception
tracebacks, whatever handlers uvicorn or a worker configures. It masks key-like URL parameters,
credential headers and the literal values of configured secrets.
"""

from collections.abc import Iterable
import logging
import re
import traceback

REDACTED = "[REDACTED]"
_MIN_SECRET_LENGTH = 8
_QUERY_SECRET = re.compile(r"(?i)([?&](?:key|api_key|apikey|access_token|token)=)[^&\s'\"]+")
_HEADER_SECRET = re.compile(
    r"(?i)((?:x-goog-api-key|x-api-key|authorization)['\"]?\s*[:=]\s*['\"]?(?:bearer\s+)?)[^\s'\",}]+"
)
_secrets: set[str] = set()


def redact(text: str) -> str:
    for secret in sorted(_secrets, key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    text = _QUERY_SECRET.sub(rf"\1{REDACTED}", text)
    return _HEADER_SECRET.sub(rf"\1{REDACTED}", text)


def install_log_redaction(secret_values: Iterable[str | None] = ()) -> None:
    """Register secret values to mask and install the redacting record factory (idempotent)."""
    _secrets.update(value.strip() for value in secret_values if value and len(value.strip()) >= _MIN_SECRET_LENGTH)
    previous = logging.getLogRecordFactory()
    if getattr(previous, "redacts_credentials", False):
        return

    def factory(*args, **kwargs) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        try:
            record.msg = redact(record.getMessage())
            record.args = None
            if record.exc_info and not record.exc_text:
                record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)).rstrip("\n"))
        except Exception:  # never let redaction break logging itself
            record.msg, record.args = "[log message withheld: redaction failed]", None
        return record

    factory.redacts_credentials = True
    logging.setLogRecordFactory(factory)
