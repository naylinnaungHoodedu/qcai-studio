"""The V3 stop (plan Phase 6 L "Stop (operator policy, set under Decision D-06): queue age above SLO for two days limits
tier 1 to pre-verified content"; Phase 6 spec 4.10, conflicts 9 and 26; PD-37).

stop_state samples the stored queue every stop_sample_s (1 hour) over the last stop_window_s (48 hours), 49 samples: at
each sample the open items are those enqueued by then and not yet closed, and the measure is the age of the oldest open
item (oldest-open-item-age-v1), never below the p90 (the alert's measure, metrics.slis) and not diluted by new items.
The stop is active (reason queue_age) when every sample has an open item older than the queue-age SLO (72 hours).

tier1_withheld is what the V2 track reads at a tier-1 response's first consult: False for a package without a v3 block,
else the stop over the pipeline's own database (session_factory), whatever the V3 mode, so an aged queue stays a stop
after V3 is switched off; a queue that cannot be read is a stop (reason unreadable, v3.stop_unread at WARNING). While it
holds, the track runs Phase 5's pre-verified-only path on tier 1: no call, every claim withheld in ZERO, and under on
the response abstains and queues (v2_panel.track). It releases nothing. The value is cached per process and session
factory for stop_refresh_s (60 s); a change of value logs v3.stop (WARNING when active, INFO when clear).
reset_stop_cache is the test seam. No module-level import of the V2 panel or the gateway, so the V2 track imports this.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import logging
import threading
import time
from typing import Any, Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.structured_logging import FIELDS

LOGGER = logging.getLogger("qcai.v3")


@dataclass(frozen=True)
class StopState:
    active: bool
    reason: Literal["clear", "queue_age", "unreadable"]
    window_s: int
    slo_s: int
    samples: int
    open_items: int
    oldest_age_s: int

    def as_dict(self) -> dict:
        return asdict(self)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def stop_state(db: Session, package: Any, *, now: datetime) -> StopState:
    from app.db_models import V3QueueItem

    v3 = package.v3
    window, step, slo = int(v3.stop_window_s), int(v3.stop_sample_s), int(v3.queue_age_slo_s)
    now = _utc(now)
    start = now - timedelta(seconds=window)
    rows = [(_utc(enqueued), _utc(closed) if closed is not None else None) for enqueued, closed in db.execute(
        select(V3QueueItem.enqueued_at, V3QueueItem.closed_at).where(
            V3QueueItem.enqueued_at <= now, or_(V3QueueItem.closed_at.is_(None), V3QueueItem.closed_at > start)))]

    def oldest_at(sample: datetime) -> tuple[int, int | None]:
        open_times = [enqueued for enqueued, closed in rows if enqueued <= sample and (closed is None or closed > sample)]
        if not open_times:
            return 0, None
        return len(open_times), int((sample - min(open_times)).total_seconds())

    samples = window // step + 1
    above = 0
    for index in range(samples):
        _, age = oldest_at(start + timedelta(seconds=index * step))
        if age is not None and age > slo:
            above += 1
    open_items, oldest = oldest_at(now)
    active = above == samples
    return StopState(active=active, reason="queue_age" if active else "clear", window_s=window, slo_s=slo, samples=samples,
                     open_items=open_items, oldest_age_s=int(oldest or 0))


_LOCK = threading.Lock()
_CACHE: dict[Any, tuple[float, bool, str]] = {}


def reset_stop_cache() -> None:
    with _LOCK:
        _CACHE.clear()


def tier1_withheld(settings: Any, package: Any, *, now: datetime | None = None, session_factory: Callable[[], Session] = SessionLocal) -> bool:
    if getattr(package, "v3", None) is None:
        return False
    refresh = float(package.v3.stop_refresh_s)
    with _LOCK:
        cached = _CACHE.get(session_factory)
    if cached is not None and time.monotonic() - cached[0] < refresh:
        return cached[1]
    try:
        with session_factory() as db:
            state = stop_state(db, package, now=now or datetime.now(UTC))
        active, reason = state.active, state.reason
    except Exception:  # noqa: BLE001 - an unreadable queue is a stop (PD-37), never a raise into the pipeline
        LOGGER.warning("The V3 queue could not be read: tier 1 is withheld", extra={FIELDS: {"event": "v3.stop_unread"}})
        active, reason = True, "unreadable"
        state = None
    with _LOCK:
        previous = _CACHE.get(session_factory)
        _CACHE[session_factory] = (time.monotonic(), active, reason)
    if previous is None or previous[1] != active or previous[2] != reason:
        window = int(package.v3.stop_window_s)
        slo = int(package.v3.queue_age_slo_s)
        if active or previous is not None:
            LOGGER.log(logging.WARNING if active else logging.INFO, "The V3 stop " + ("holds: tier 1 is pre-verified-only" if active else "is clear"),
                       extra={FIELDS: {"event": "v3.stop", "active": active, "reason": reason, "window_s": window, "slo_s": slo}})
    return active
