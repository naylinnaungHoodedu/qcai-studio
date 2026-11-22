"""The V3 scan: ledger records into the queue (plan Phase 6 D tasks 1-2; Phase 6 spec 4.4).

run_scan reads up to `limit` response_ledger rows past the cursor (the largest v3_scans.to_seq) in seq order, in one
transaction (on PostgreSQL under a transaction-scoped advisory lock), and for each:
  1. validates it with ENTRY_SCHEMAS[entry_schema]; an unknown schema or a failure is counted unparsed and skips the
     triggers, and a delivery is still drawn (with no claim-set key);
  2. records its model sightings (v3_model_versions): triggers.x5_model_changes names each known model key seen with
     another version, an X5 model_change event (v3_events); a first sighting is a baseline; the registry's verifiers are
     compared once per scan;
  3. evaluates the triggers (triggers.evaluate);
  4. for a learner delivery (legacy or delivered) inserts its v3_draws row (primary key: its seq, so each delivery is
     considered exactly once) at 1/20, or 1/5 while an X5 window is open, and a drawn delivery gets an X6 or X5 response
     item; then it raises the exposure of any item already on the record (an X3 flag that came first) to the record's
     full count (queue.refresh_exposure), so an item's exposure never depends on which path created it;
  5. upserts each item (queue.upsert_item).
Then it appends the v3_scans row and logs v3.scan. Write order: model versions and events, then draws, then queue
items, then the scan row (the guard's lock order). The ledger is read only: no ledger row changes. On SQLite a
"database is locked" error (two writers that both began deferred transactions) retries the whole scan, at most
queue.ATTEMPTS times; then queue.V3Busy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
from typing import Any

from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.structured_logging import FIELDS
from app.services import v3
from app.services.v3 import triggers as trig
from app.services.v3.draw import claim_set_key, draw_trigger
from app.services.v3.queue import ATTEMPTS, V3Busy, _dialect, parse_entry, refresh_exposure, sqlite_busy, upsert_item, utc
from app.services.v3.rules import DELIVERIES, DRAW_RULE

LOGGER = logging.getLogger("qcai.v3")
V3_SCAN_LOCK_KEY = 7_401_206


@dataclass(frozen=True)
class ScanResult:
    from_seq: int
    to_seq: int
    records: int
    deliveries: int
    drawn_x6: int
    drawn_x5: int
    items_created: int
    items_updated: int
    model_changes: int
    unparsed: int
    done: bool                          # no record past to_seq when the scan ended


def known_versions(db: Session) -> dict[str, str]:
    from app.db_models import V3ModelVersion

    known: dict[str, str] = {}
    for key, version in db.execute(select(V3ModelVersion.model_key, V3ModelVersion.model_version).order_by(V3ModelVersion.id)):
        known[key] = version
    return known


def open_windows(db: Session) -> list[list[int]]:
    """Each X5 event as [from_ledger_seq, remaining deliveries], remaining = its window less the deliveries considered
    after it."""
    from app.db_models import V3Draw, V3Event

    windows = []
    for from_seq, size in db.execute(select(V3Event.from_ledger_seq, V3Event.window_deliveries).order_by(V3Event.seq)):
        seen = db.scalar(select(func.count()).select_from(V3Draw).where(V3Draw.ledger_seq > int(from_seq))) or 0
        windows.append([int(from_seq), max(0, int(size) - int(seen))])
    return windows


def record_model_change(db: Session, change: trig.ModelChange, *, source: str, from_ledger_seq: int, window: int, now: datetime) -> None:
    from app.db_models import V3Event

    payload = json.dumps({"model_key": change.model_key, "from_version": change.from_version, "to_version": change.to_version,
                          "source": source}, sort_keys=True, separators=(",", ":"))
    db.execute(insert(V3Event).values(kind="model_change", payload=payload, from_ledger_seq=int(from_ledger_seq), window_deliveries=int(window),
                                      created_at=utc(now)))
    LOGGER.warning("A model version changed: the audit rate is raised (X5)", extra={FIELDS: {
        "event": "v3.x5_event", "kind": "model_change", "model_key": change.model_key, "from_version": change.from_version,
        "to_version": change.to_version}})


def _sightings(db: Session, known: dict[str, str], sightings, *, source: str, seq: int, window: int, windows: list, now: datetime) -> int:
    from app.db_models import V3ModelVersion

    changes = 0
    for key, version in sightings:
        if known.get(key) == version:
            continue
        for change in trig.x5_model_changes(known, ((key, version),)):
            record_model_change(db, change, source=source, from_ledger_seq=seq, window=window, now=now)
            windows.append([int(seq), int(window)])
            changes += 1
        db.execute(insert(V3ModelVersion).values(model_key=key, model_version=version, first_seen_seq=int(seq), source=source, seen_at=utc(now)))
        known[key] = version
    return changes


def run_scan(*, settings: Any, package: Any, session_factory: Callable[[], Session] = SessionLocal, now: datetime | None = None,
             limit: int = 500) -> ScanResult:
    v3.require_on(settings, package)
    now = utc(now or datetime.now(UTC))
    last: Exception | None = None
    for _ in range(ATTEMPTS):
        try:
            result = _scan_once(settings=settings, package=package, session_factory=session_factory, now=now, limit=limit)
            break
        except OperationalError as exc:
            if not sqlite_busy(exc):
                raise
            last = exc
    else:
        raise V3Busy("the V3 scan could not complete within its attempts: the database stayed locked") from last
    LOGGER.info("V3 scan", extra={FIELDS: {"event": "v3.scan", **{key: getattr(result, key) for key in (
        "from_seq", "to_seq", "records", "deliveries", "drawn_x6", "drawn_x5", "items_created", "items_updated", "model_changes", "unparsed", "done")}}})
    return result


def _scan_once(*, settings: Any, package: Any, session_factory: Callable[[], Session], now: datetime, limit: int) -> ScanResult:
    from app.db_models import ResponseLedgerRecord, V3Draw, V3Scan
    from app.gateway.registry import registry_for

    params = package.v3
    margins = dict(package.v1.x4_margin) if package.v1 is not None else {}
    with session_factory() as db:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": V3_SCAN_LOCK_KEY})
        cursor = int(db.scalar(select(func.coalesce(func.max(V3Scan.to_seq), 0))) or 0)
        rows = db.execute(select(ResponseLedgerRecord.__table__).where(ResponseLedgerRecord.seq > cursor)
                          .order_by(ResponseLedgerRecord.seq).limit(int(limit))).all()
        known = known_versions(db)
        windows = open_windows(db)
        window = int(params.x5_window_deliveries)
        changes = _sightings(db, known, trig.registry_sightings(registry_for(package, settings)), source="registry", seq=cursor, window=window,
                             windows=windows, now=now)
        counts = {"deliveries": 0, "drawn_x6": 0, "drawn_x5": 0, "items_created": 0, "items_updated": 0, "unparsed": 0}
        for row in rows:
            entry = parse_entry(row)
            specs = []
            if entry is None:
                counts["unparsed"] += 1
            else:
                changes += _sightings(db, known, trig.record_sightings(entry), source="record", seq=int(row.seq), window=window,
                                      windows=windows, now=now)
                specs.extend(trig.evaluate(entry, x4_margin=margins).items)
            if row.delivery in DELIVERIES:
                counts["deliveries"] += 1
                active = trig.x5_active(windows, int(row.seq))
                rate = params.x5_rate if active else params.draw_rate
                drawn = draw_trigger(params.draw_seed, row.response_id, base=params.draw_rate, elevated=params.x5_rate, x5_active=active)
                statement = _dialect(db).insert(V3Draw).values(
                    ledger_seq=int(row.seq), delivered_at=utc(row.created_at), claim_set_key=claim_set_key(entry), rate_numerator=rate.numerator,
                    rate_denominator=rate.denominator, x5_active=active, drawn=drawn, rule=DRAW_RULE, package_sha256=package.sha256,
                    considered_at=now).on_conflict_do_nothing(index_elements=["ledger_seq"]).returning(V3Draw.ledger_seq)
                # RETURNING says whether the row was inserted, whatever rowcount a driver reports for this statement.
                inserted = db.execute(statement).first() is not None
                if inserted and active:
                    for item in windows:
                        if item[0] < int(row.seq) and item[1] > 0:
                            item[1] -= 1
                if inserted and drawn is not None:
                    counts["drawn_x6" if drawn == "X6" else "drawn_x5"] += 1
                    specs.append(trig.response_spec(entry, drawn))
                refresh_exposure(db, record_row=row, entry=entry, package=package)
            for spec in specs:
                _, created = upsert_item(db, record_row=row, spec=spec, entry=entry, package=package, now=now)
                counts["items_created" if created else "items_updated"] += 1
        to_seq = int(rows[-1].seq) if rows else cursor
        result = ScanResult(from_seq=cursor, to_seq=to_seq, records=len(rows), model_changes=changes, done=len(rows) < int(limit), **counts)
        db.execute(insert(V3Scan).values(from_seq=cursor, to_seq=to_seq, records=len(rows), deliveries=counts["deliveries"],
                                         drawn_x6=counts["drawn_x6"], drawn_x5=counts["drawn_x5"], items_created=counts["items_created"],
                                         items_updated=counts["items_updated"], model_changes=changes, unparsed=counts["unparsed"],
                                         package_version=package.package_version, package_sha256=package.sha256, created_at=now))
        db.commit()
    return result


def scan_until_done(*, settings: Any, package: Any, session_factory: Callable[[], Session] = SessionLocal, now: datetime | None = None,
                    limit: int = 500, max_batches: int = 10_000) -> list[ScanResult]:
    results = []
    for _ in range(max_batches):
        result = run_scan(settings=settings, package=package, session_factory=session_factory, now=now, limit=limit)
        results.append(result)
        if result.done:
            break
    return results
