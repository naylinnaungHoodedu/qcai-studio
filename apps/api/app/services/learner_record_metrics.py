"""Process-local Phase 8 counters and identifier-free event records."""

from collections import Counter
import logging
from threading import Lock

from app.core.structured_logging import FIELDS


LOGGER = logging.getLogger(__name__)
_counts: Counter[str] = Counter()
_lock = Lock()


def record_signal(event: str, *, reason: str | None = None) -> None:
    with _lock:
        _counts[f"{event}.{reason}" if reason else event] += 1
    fields = {"event": event}
    if reason is not None:
        fields["reason"] = reason
    LOGGER.info(event, extra={FIELDS: fields})


def snapshot() -> dict[str, int]:
    with _lock:
        return dict(_counts)
