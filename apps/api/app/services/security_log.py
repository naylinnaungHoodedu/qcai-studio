"""Append-only, hash-chained security event log (plan task 1.7).

Each row stores the hash of the row before it, so an edited, removed or reordered row breaks the chain and
`verify_security_log` names where. Database triggers refuse UPDATE, TRUNCATE and the DELETE of any row
still inside the retention period (`app.core.schema_upgrades`). `python -m app.workers.security_log`
verifies the chain and writes its head hash to the platform logs, a copy kept outside the database.

A row carries no learner identifier: the subject and the network source are keyed digests. Erasure
therefore has nothing to remove here, and the log can stay append-only.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json
import logging
import random
import threading
import time
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.requests import HTTPConnection
from starlette.routing import BaseRoute, Match

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.rate_limit import SlidingWindowLimiter
from app.db_models import SecurityEvent

LOGGER = logging.getLogger("qcai.security")

GENESIS_HASH = "0" * 64
OUTCOMES = ("success", "failure", "denied", "warning")
# Anyone can trigger a failure or a denial, so each event type is capped per instance. The next event of
# that type that is recorded says how many were dropped before it.
CAPPED_OUTCOMES = ("failure", "denied")
CAPPED_EVENTS_PER_MINUTE = 60
_MAX_DETAIL_LENGTH = 200
_APPEND_ATTEMPTS = 10
_APPEND_LOCK_KEY = 7_401_007  # Arbitrary; names this log's transaction-scoped PostgreSQL advisory lock.
_MAX_REPORTED_PROBLEMS = 20


@dataclass(frozen=True)
class AppendedEvent:
    seq: int
    hash: str


@dataclass(frozen=True)
class SecurityLogCheck:
    count: int
    first_seq: int | None
    last_seq: int | None
    head_hash: str | None
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


def _utc(value: datetime) -> datetime:
    # SQLite returns these timestamps without a zone (stored as UTC); PostgreSQL returns them with one.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def keyed_digest(value: str, purpose: str) -> str:
    """A pseudonym for an id or address: stable while the key is, and not reversible without it."""
    key = (get_settings().guest_token_secret or "").encode("utf-8")
    return hmac.new(key, f"security-log|{purpose}|{value}".encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def client_source(connection: HTTPConnection) -> str | None:
    forwarded_for = connection.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip() or None
    return connection.client.host if connection.client else None


def route_template(connection: HTTPConnection, candidates: Iterable[BaseRoute] = ()) -> str:
    """The route's template (`/arena/profiles/{player_id}`), so no id from the path is logged.

    After routing it is the matched route; before routing (in middleware) the first full match among
    `candidates`, or "unmatched".
    """
    route = connection.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    for candidate in candidates:
        match, _ = candidate.matches(connection.scope)
        if match == Match.FULL and getattr(candidate, "path", None):
            return candidate.path
    return "unmatched"


def _clean_details(details: dict[str, Any] | None) -> dict[str, str | int | bool | None]:
    cleaned: dict[str, str | int | bool | None] = {}
    for key, value in (details or {}).items():
        cleaned[str(key)] = value if value is None or isinstance(value, (bool, int)) else str(value)[:_MAX_DETAIL_LENGTH]
    return cleaned


def event_hash(
    *,
    seq: int,
    created_at: datetime,
    event_type: str,
    outcome: str,
    actor_role: str,
    subject_digest: str | None,
    source_digest: str | None,
    details: dict[str, Any],
    prev_hash: str,
) -> str:
    canonical = json.dumps(
        {
            "seq": seq,
            "created_at": _utc(created_at).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "event_type": event_type,
            "outcome": outcome,
            "actor_role": actor_role,
            "subject_digest": subject_digest,
            "source_digest": source_digest,
            "details": details,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def _row_hash(row: SecurityEvent) -> str:
    return event_hash(
        seq=row.seq,
        created_at=row.created_at,
        event_type=row.event_type,
        outcome=row.outcome,
        actor_role=row.actor_role,
        subject_digest=row.subject_digest,
        source_digest=row.source_digest,
        details=row.details or {},
        prev_hash=row.prev_hash,
    )


def _chain_head(db: Session) -> tuple[int, str] | None:
    head = db.execute(select(SecurityEvent.seq, SecurityEvent.hash).order_by(SecurityEvent.seq.desc()).limit(1)).first()
    return (head.seq, head.hash) if head else None


def append_security_event(
    event_type: str,
    outcome: str,
    *,
    actor_role: str = "anonymous",
    subject_digest: str | None = None,
    source_digest: str | None = None,
    details: dict[str, Any] | None = None,
    now: datetime | None = None,
    session_factory: Callable[[], Session] = SessionLocal,
) -> AppendedEvent:
    """Append one event in its own transaction and return its sequence number and hash."""
    if outcome not in OUTCOMES:
        raise ValueError(f"Unknown security event outcome: {outcome}")
    created_at = _utc(now or datetime.now(UTC))
    cleaned = _clean_details(details)
    for attempt in range(_APPEND_ATTEMPTS):
        if attempt:
            time.sleep(random.uniform(0, 0.005 * attempt))
        with session_factory() as db:
            if db.get_bind().dialect.name == "postgresql":
                # One writer at a time on PostgreSQL; the sequence-number retry below covers other databases.
                db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _APPEND_LOCK_KEY})
            head = _chain_head(db)
            row = SecurityEvent(
                seq=head[0] + 1 if head else 1,
                created_at=created_at,
                event_type=event_type,
                outcome=outcome,
                actor_role=actor_role,
                subject_digest=subject_digest,
                source_digest=source_digest,
                details=cleaned,
                prev_hash=head[1] if head else GENESIS_HASH,
            )
            row.hash = _row_hash(row)
            appended = AppendedEvent(seq=row.seq, hash=row.hash)
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                # Another writer took this sequence number; read the new head and chain onto it.
                db.rollback()
                continue
            return appended
    raise RuntimeError("The security event could not be appended after repeated write conflicts.")


class _Caps:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._limiter = SlidingWindowLimiter(limit=CAPPED_EVENTS_PER_MINUTE, window_seconds=60)
        self._dropped: dict[str, int] = {}

    def admit(self, event_type: str) -> int | None:
        """None to drop this event; otherwise how many of its type were dropped before it."""
        with self._lock:
            if not self._limiter.allow(event_type):
                self._dropped[event_type] = self._dropped.get(event_type, 0) + 1
                return None
            return self._dropped.pop(event_type, 0)


_caps = _Caps()


def record_security_event(
    event_type: str,
    outcome: str,
    *,
    connection: HTTPConnection | None = None,
    actor_role: str = "anonymous",
    subject: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Record an event. It never raises: a logging fault must not change the outcome of the request."""
    try:
        details = dict(details or {})
        if outcome in CAPPED_OUTCOMES:
            dropped = _caps.admit(event_type)
            if dropped is None:
                return
            if dropped:
                details["dropped_before"] = dropped
        source = client_source(connection) if connection is not None else None
        append_security_event(
            event_type,
            outcome,
            actor_role=actor_role,
            subject_digest=keyed_digest(subject, "subject") if subject else None,
            source_digest=keyed_digest(source, "source") if source else None,
            details=details,
        )
    except Exception:
        LOGGER.exception("Security event %s/%s could not be recorded.", event_type, outcome)


async def record_security_event_async(event_type: str, outcome: str, **kwargs: Any) -> None:
    await run_in_threadpool(record_security_event, event_type, outcome, **kwargs)


def verify_security_log(db: Session) -> SecurityLogCheck:
    """Walk the chain in sequence order. Retention removes the oldest rows, so the first remaining row's
    prev_hash is taken as given unless that row is the genesis row."""
    problems: list[str] = []
    count = 0
    first_seq: int | None = None
    previous: SecurityEvent | None = None
    for row in db.scalars(select(SecurityEvent).order_by(SecurityEvent.seq)):
        count += 1
        if previous is None:
            first_seq = row.seq
            if row.seq == 1 and row.prev_hash != GENESIS_HASH:
                problems.append("seq 1 does not start from the genesis hash")
        else:
            if row.seq != previous.seq + 1:
                problems.append(f"seq {previous.seq + 1} to {row.seq - 1} missing")
            if row.prev_hash != previous.hash:
                problems.append(f"seq {row.seq} does not chain onto seq {previous.seq}")
        if _row_hash(row) != row.hash:
            problems.append(f"seq {row.seq} does not match its hash")
        previous = row
    return SecurityLogCheck(
        count=count,
        first_seq=first_seq,
        last_seq=previous.seq if previous else None,
        head_hash=previous.hash if previous else None,
        problems=tuple(problems[:_MAX_REPORTED_PROBLEMS]),
    )
