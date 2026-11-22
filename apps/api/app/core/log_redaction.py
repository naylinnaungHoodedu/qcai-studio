"""Scrub credentials from every log record (plan Action 24, AC-1-8).

Installed as the log-record factory, so it applies to every logger (httpx included) and to exception
tracebacks, whatever handlers uvicorn or a worker configures. It masks key-like URL parameters,
credential headers and the literal values of configured secrets.

A secret may be registered with an owner (install_log_redaction(values, owner="gateway")), and an owner may register a
listener (add_secret_listener): whenever redaction masks an owned secret's literal value, it calls the owner's listeners
with the owner's name. A listener runs inside the logging call that made the record, so it only sets a flag; it never
logs, raises or touches a database (the model gateway stops at its next call; Phase 5 spec 4.3, 4.5).
"""

from collections.abc import Iterable
import logging
import re
import traceback
from typing import Any
import weakref

REDACTED = "[REDACTED]"
_MIN_SECRET_LENGTH = 8
_QUERY_SECRET = re.compile(r"(?i)([?&](?:key|api_key|apikey|access_token|token)=)[^&\s'\"]+")
_HEADER_SECRET = re.compile(
    r"(?i)((?:x-goog-api-key|x-api-key|authorization)['\"]?\s*[:=]\s*['\"]?(?:bearer\s+)?)[^\s'\",}]+"
)
_secrets: set[str] = set()
# secret value -> owner, and owner -> listeners (callables, or weak references to them, taking the owner's name).
_owners: dict[str, str] = {}
_listeners: dict[str, list[Any]] = {}
# Uvicorn's access formatter unpacks the record's arguments (client, method, path, version, status), so its
# records keep their argument tuple, each string in it masked. Flattened like every other record, each
# access line became a "--- Logging error ---" traceback instead (found on the Release R1 tagged revision).
_ARGUMENT_TUPLE_LOGGERS = frozenset({"uvicorn.access"})


def add_secret_listener(owner: str, callback: Any) -> None:
    """Register a listener for an owner's secrets: a callable, or a weakref.WeakMethod to one (dead ones are dropped)."""
    alive = [item for item in _listeners.get(owner, ()) if not (isinstance(item, weakref.WeakMethod) and item() is None)]
    _listeners[owner] = [*alive, callback]


def _notify(owners: set[str]) -> None:
    for owner in owners:
        alive = []
        for listener in _listeners.get(owner, ()):
            callback = listener() if isinstance(listener, weakref.WeakMethod) else listener
            if callback is None:
                continue
            alive.append(listener)
            try:
                callback(owner)
            except Exception:  # noqa: BLE001 - a listener never breaks logging
                pass
        _listeners[owner] = alive


def redact(text: str) -> str:
    if _listeners:
        seen = {owner for secret, owner in _owners.items() if owner in _listeners and secret in text}
        if seen:
            _notify(seen)
    for secret in sorted(_secrets, key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    text = _QUERY_SECRET.sub(rf"\1{REDACTED}", text)
    return _HEADER_SECRET.sub(rf"\1{REDACTED}", text)


def install_log_redaction(secret_values: Iterable[str | None] = (), *, owner: str | None = None) -> None:
    """Register secret values to mask (each with its owner, when one is named) and install the redacting record
    factory (idempotent)."""
    values = [value.strip() for value in secret_values if value and len(value.strip()) >= _MIN_SECRET_LENGTH]
    _secrets.update(values)
    if owner is not None:
        _owners.update((value, owner) for value in values)
    previous = logging.getLogRecordFactory()
    if getattr(previous, "redacts_credentials", False):
        return

    def factory(*args, **kwargs) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        try:
            if record.name in _ARGUMENT_TUPLE_LOGGERS and isinstance(record.args, tuple):
                record.msg = redact(str(record.msg))
                record.args = tuple(redact(value) if isinstance(value, str) else value for value in record.args)
            else:
                record.msg = redact(record.getMessage())
                record.args = None
            if record.exc_info and not record.exc_text:
                record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)).rstrip("\n"))
        except Exception:  # never let redaction break logging itself
            record.msg, record.args = "[log message withheld: redaction failed]", None
        return record

    factory.redacts_credentials = True
    logging.setLogRecordFactory(factory)
