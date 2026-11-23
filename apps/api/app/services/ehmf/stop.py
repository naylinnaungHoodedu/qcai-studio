"""The rising-A/B stop (plan Phase 7 L "a rising A/B rate after a change reverts it and sets audit to 20%"; Phase 7 spec
4.10; PD-46).

Computed state over the typed records (ledger-entry-v4), never a configuration write (D-05):
  ab_series   per typed record (seq, config_version, typed claims, A/B claims) of the last stop.scan_records records
  detect      for each change of config_version, the A/B claims among the first window_claims typed claims of the new
              version against those among the last window_claims of the old one; active at min_claims new claims, at
              least min_ab A/B claims and a rate above rise times the old (integers only). It inserts one ehmf_stops row
              per change (ON CONFLICT DO NOTHING RETURNING seq); v3.scan.open_windows reads it as a window of raised
              audit rate (1/5, plan "sets audit to 20%") over the next v3 X5 window of learner deliveries after
              detected_seq. Run once per V3 scan, inside its transaction and lock, only when EHMF is not off.
  stop_state  the latest row: "revert required" while the package in force is the version the stop followed; reverted
              once the prior package is reloaded (the operator's action: runbook "Reload the prior package").
Outside development no typed record is written, so the stop cannot fire in production until EHMF runs there (DI-111).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
import threading
import time
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.structured_logging import FIELDS

LOGGER = logging.getLogger("qcai.ehmf")
AB_TYPES = frozenset({"A", "B1", "B2"})


@dataclass(frozen=True)
class StopState:
    revert_required: bool | None          # None: unreadable, or EHMF off
    reason: Literal["clear", "rising_ab", "reverted", "unreadable", "not_evaluated"]
    from_config_version: str | None
    to_config_version: str | None


def _typed_counts(entry: dict) -> tuple[int, int]:
    ehmf = ((entry.get("verification") or {}).get("ehmf")) or {}
    claims = ehmf.get("claims") or []
    typed = len(claims)
    ab = sum(1 for claim in claims if any(finding.get("type") in AB_TYPES for finding in claim.get("findings") or []))
    dropped = {}
    for finding in ehmf.get("response_findings") or []:
        claim_id = finding.get("claim_id")
        if claim_id:
            dropped[claim_id] = dropped.get(claim_id, False) or finding.get("type") in AB_TYPES
    return typed + len(dropped), ab + sum(1 for value in dropped.values() if value)


def ab_series(db: Session, *, limit_records: int) -> list[tuple[int, str, int, int]]:
    """(seq, config_version, typed claims, A/B claims) of the last limit_records ledger-entry-v4 records, in seq order."""
    from app.db_models import ResponseLedgerRecord
    from app.services.ledger import config_version_of

    rows = db.execute(select(ResponseLedgerRecord.seq, ResponseLedgerRecord.entry)
                      .where(ResponseLedgerRecord.entry_schema == "ledger-entry-v4")
                      .order_by(ResponseLedgerRecord.seq.desc()).limit(int(limit_records))).all()
    series = []
    for seq, raw in reversed(rows):
        try:
            entry = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(entry, dict):
            continue
        typed, ab = _typed_counts(entry)
        series.append((int(seq), config_version_of(entry.get("versions")), typed, ab))
    return series


def _fires(before_claims: int, before_ab: int, after_claims: int, after_ab: int, params: Any) -> bool:
    rise = params.stop_rise
    return (before_claims > 0 and after_claims >= params.stop_min_claims and after_ab >= params.stop_min_ab
            and after_ab * before_claims * rise.denominator > before_ab * after_claims * rise.numerator)


def detect(db: Session, package: Any, *, now: datetime) -> int | None:
    """Insert an ehmf_stops row for a change point whose after-window meets the stop; returns its seq, or None."""
    from app.db_models import EhmfStop

    params = package.ehmf
    series = ab_series(db, limit_records=params.stop_scan_records)
    inserted = None
    for index in range(1, len(series)):
        if series[index][1] == series[index - 1][1]:
            continue
        change_seq, new_version, old_version = series[index][0], series[index][1], series[index - 1][1]
        before_claims = before_ab = 0
        for _seq, version, typed, ab in reversed(series[:index]):
            if version != old_version or before_claims >= params.stop_window_claims:
                break
            before_claims, before_ab = before_claims + typed, before_ab + ab
        after_claims = after_ab = 0
        detected_seq = None
        for seq, version, typed, ab in series[index:]:
            if version != new_version or after_claims >= params.stop_window_claims:
                break
            after_claims, after_ab = after_claims + typed, after_ab + ab
            if _fires(before_claims, before_ab, after_claims, after_ab, params):
                detected_seq = seq
                break
        if detected_seq is None:
            continue
        window = int(package.v3.x5_window_deliveries) if package.v3 is not None else 1500
        dialect = db.get_bind().dialect.name
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        statement = insert(EhmfStop).values(
            from_config_version=old_version, to_config_version=new_version, change_seq=int(change_seq), detected_seq=int(detected_seq),
            before_claims=before_claims, before_ab=before_ab, after_claims=after_claims, after_ab=after_ab, window_deliveries=window,
            package_sha256=package.sha256, created_at=now.astimezone(UTC),
        ).on_conflict_do_nothing(index_elements=["from_config_version", "to_config_version", "change_seq"]).returning(EhmfStop.seq)
        row = db.execute(statement).first()
        if row is not None:
            inserted = int(row[0])
            LOGGER.warning("A rising A/B rate followed a configuration change: revert required, audit raised to 1/5", extra={FIELDS: {
                "event": "ehmf.stop", "from_config_version": old_version, "to_config_version": new_version, "before_claims": before_claims,
                "before_ab": before_ab, "after_claims": after_claims, "after_ab": after_ab}})
    return inserted


STOP_STATEMENT_COLUMNS = ("to_config_version", "from_config_version")


def stop_state(db: Session, package: Any) -> StopState:
    from app.db_models import EhmfStop

    try:
        row = db.execute(select(EhmfStop.to_config_version, EhmfStop.from_config_version).order_by(EhmfStop.seq.desc()).limit(1)).first()
    except Exception:  # noqa: BLE001 - an unreadable state is reported as such, never as clear
        LOGGER.warning("The EHMF stop state could not be read", extra={FIELDS: {"event": "ehmf.stop_unread"}})
        return StopState(None, "unreadable", None, None)
    if row is None:
        return StopState(False, "clear", None, None)
    to_version, from_version = row
    if to_version == package.package_version:
        return StopState(True, "rising_ab", from_version, to_version)
    if from_version == package.package_version:
        return StopState(False, "reverted", from_version, to_version)
    return StopState(False, "clear", from_version, to_version)


_CACHE: dict[str, tuple[float, StopState]] = {}
_CACHE_LOCK = threading.Lock()


def process_stop_state(settings: Any, package: Any, *, session_factory: Any = None) -> StopState:
    """The stop state for /ready, cached per process for ehmf.stop.refresh_s; not_evaluated (no read) when EHMF is off."""
    from app.services import ehmf

    if getattr(package, "ehmf", None) is None or ehmf.mode(settings, package) == "off":
        return StopState(None, "not_evaluated", None, None)
    key = f"{package.sha256}"
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None and now - cached[0] < package.ehmf.stop_refresh_s:
            return cached[1]
    if session_factory is None:
        from app.core.db import SessionLocal

        session_factory = SessionLocal
    try:
        with session_factory() as db:
            state = stop_state(db, package)
    except Exception:  # noqa: BLE001
        LOGGER.warning("The EHMF stop state could not be read", extra={FIELDS: {"event": "ehmf.stop_unread"}})
        state = StopState(None, "unreadable", None, None)
    with _CACHE_LOCK:
        _CACHE[key] = (now, state)
    return state


def reset_stop_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
