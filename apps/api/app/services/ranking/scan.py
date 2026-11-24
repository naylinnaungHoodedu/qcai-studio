"""The ranking scan: ledger records into the controller (plan Phase 9 E, tasks 1-5; spec 4.10). The only module that writes
the ranking tables.

run_scan needs the ranking mode shadow (else RankingOff). One transaction (on PostgreSQL under the ranking advisory lock
7_401_209, then V3's 7_401_206, always in that order; SQLite serialises on the database lock and a busy database is
retried as the V3 scan does):
  1. refuse while the last stop/clear_stop row is a stop (RankingStopped);
  2. load the stored state: its bytes must be the last checkpoint's (the first scan starts from empty_state); a mismatch
     appends `stop {state_mismatch}`, commits, logs ranking.stop and returns stopped;
  3. append `config` when the package's ranking block differs from the state's, `availability` when a candidate's
     availability changed (the gateway's ineligible_reason for a registry member; kill_switch for a static one under
     MODEL_GATEWAY_KILL_SWITCH), and `model_seen` or `model_change` per candidate; a model change records its X5 window
     under V3's lock with the key and version a record would carry (generator:<adapter_id>, <model_id>@<model_version>;
     generator-prompt:<id> for a static generator), reusing V3's event when V3 already recorded a change to that version
     (conflict 14), else from V3's known version or the candidate's previous one (record_x5_change);
  4. while a static candidate is uncommissioned, commit and refuse (RankingUncommissioned; conflict 26);
  5. append `hold_release` for each open hold once every X5 window raised under it closed (v3.scan.window_remaining == 0
     for the v3_event_seq of its `hold` row and of every `alarm` row naming it, a sustained alarm's included; a row
     without a V3 event keeps the hold open);
  6. read the ledger past the cursor (the largest ranking_scans.to_seq), in seq order, up to `limit`: each record is an
     `outcome` or `skipped` input (input_key ledger:<seq>), applied, with its derived events and their side effects: an
     alarm through Phase 6's record_cusum_alarm (source phase9-cusum; X5), a fallback through a V3 response item
     (ranking_empty_eligible_set) when V3 is not off, else the row notes v3_off;
  7. `feedback` for a pending outcome of a record the learner was shown with an X3 item (none exists today: conflict 12);
  8. `tick {at: now}`, then the ranking_scans row, the checkpoint, ranking_states and ranking_incumbents; commit.
The ledger is only read. Every event is hash-chained (ranking-chain-v1) and its derived events follow it. take_locks is
the one lock order every ranking writer uses (the scan, append_inputs, and the worker's replay --check and clear-stop).
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
from app.services import ranking
from app.services.ranking.controller import apply_in_place
from app.services.ranking.replay import chain_sha256, stopped
from app.services.ranking.signals import outcome_of, outcome_payload, utc_text
from app.services.ranking.state import canonical, empty_state, sha256_hex, state_sha256
from app.services.ranking.types import Outcome
from app.services.ranking.vocabulary import GENESIS, RANKING_SCAN_LOCK_KEY, STATE_KEY

LOGGER = logging.getLogger("qcai.ranking")


@dataclass(frozen=True)
class ScanResult:
    from_seq: int
    to_seq: int
    records: int
    outcomes: int
    skipped: int
    batches: int
    alarms: int
    fallbacks: int
    done: bool
    refused: str | None = None          # "uncommissioned" | "stopped" (a state mismatch found by this scan)


class EventLog:
    """Appends hash-chained rows to ranking_events inside the scan's transaction and keeps the in-memory state."""

    def __init__(self, db: Session, state: dict, *, now: datetime) -> None:
        from app.db_models import RankingEvent

        self.db, self.state, self.now = db, state, now
        last = db.execute(select(RankingEvent.seq, RankingEvent.sha256).order_by(RankingEvent.seq.desc()).limit(1)).first()
        self.prev = last[1] if last is not None else GENESIS
        self.last_seq = int(last[0]) if last is not None else 0
        self.counts = {"batches": 0, "alarms": 0, "fallbacks": 0}
        self.side_effects: list[tuple[str, dict, int]] = []

    def _insert(self, kind: str, payload: dict, *, input_key: str | None = None, **columns: Any) -> int | None:
        from app.db_models import RankingEvent

        body = canonical(payload).decode("utf-8")
        digest = chain_sha256(self.prev, kind, body)
        values = dict(kind=kind, payload=body, prev_sha256=self.prev, sha256=digest, input_key=input_key, observed_at=self.now, **columns)
        if input_key is not None:
            dialect = self.db.get_bind().dialect.name
            if dialect == "postgresql":
                from sqlalchemy.dialects.postgresql import insert as dialect_insert
            else:
                from sqlalchemy.dialects.sqlite import insert as dialect_insert
            statement = dialect_insert(RankingEvent).values(**values).on_conflict_do_nothing(index_elements=["input_key"]).returning(RankingEvent.seq)
            row = self.db.execute(statement).first()
            if row is None:
                return None
            seq = int(row[0])
        else:
            seq = int(self.db.execute(insert(RankingEvent).values(**values)).inserted_primary_key[0])
        self.prev, self.last_seq = digest, seq
        return seq

    def control(self, kind: str, payload: dict) -> int:
        return int(self._insert(kind, payload))

    def append(self, kind: str, payload: dict, *, input_key: str | None = None, v3_event_seq: int | None = None, **columns: Any) -> int | None:
        """Append one input, apply it, and append its derived events right after it; None when input_key exists."""
        seq = self._insert(kind, payload, input_key=input_key, v3_event_seq=v3_event_seq, **columns)
        if seq is None:
            return None
        for derived_kind, derived_payload in apply_in_place(self.state, {"seq": seq, "kind": kind, "payload": payload}):
            self._derived(derived_kind, derived_payload, input_seq=seq, input_v3=v3_event_seq)
        return seq

    def _derived(self, kind: str, payload: dict, *, input_seq: int, input_v3: int | None) -> None:
        columns: dict[str, Any] = {}
        if kind in ("select", "batch", "promote", "demote"):
            columns["context_key"] = payload["context"]
        if kind == "select":
            columns["ledger_seq"] = payload["ledger_seq"]
            columns["model_key"] = payload["model"]
        if kind == "batch":
            columns["batch_seq"] = payload["batch_seq"]
            self.counts["batches"] += 1
        if kind in ("promote", "demote"):
            columns["model_key"] = payload["to"]
        v3_seq, note = None, None
        if kind == "alarm":
            self.counts["alarms"] += 1
            v3_seq = self._alarm(payload)
            note = payload["hold_id"]   # the hold this alarm's X5 window keeps open (a sustained alarm's included)
        if kind == "hold":
            v3_seq = self._hold_window(payload, input_v3)
            columns["model_key"] = ",".join(payload["models"])
            note = payload["hold_id"]
        if kind == "select" and payload["kind"] == "fallback":
            self.counts["fallbacks"] += 1
            note = self._fallback(payload)
        self._insert(kind, payload, v3_event_seq=v3_seq, note=note, **columns)
        if kind == "alarm":
            self.last_alarm_v3 = v3_seq
        log_derived(kind, payload)

    # side effects ----------------------------------------------------------------------------------------------------

    settings: Any = None
    package: Any = None
    current_row: Any = None
    current_entry: Any = None
    last_alarm_v3: int | None = None

    def _alarm(self, payload: dict) -> int:
        from app.services.v3.contracts import CusumAlarm
        from app.services.v3.events import record_cusum_alarm

        alarm = CusumAlarm(stream=payload["stream"], p0=float(payload["p0"]), p1=float(payload["p1"]), h=float(payload["h"]),
                           statistic=float(payload["statistic"]), observations=int(payload["observations"]), raised_at=payload["created_at"],
                           source="phase9-cusum")
        return record_cusum_alarm(alarm, settings=self.settings, package=self.package, db=self.db, now=self.now)

    def _hold_window(self, payload: dict, input_v3: int | None) -> int | None:
        if payload["cause"] == "alarm":
            return self.last_alarm_v3
        return input_v3

    def _fallback(self, payload: dict) -> str | None:
        from app.services import v3
        from app.services.v3.priority import response_k
        from app.services.v3.queue import upsert_item
        from app.services.v3.triggers import ItemSpec, response_types

        if v3.mode(self.settings, self.package) == "off" or self.current_row is None:
            return "v3_off"
        entry = self.current_entry
        spec = ItemSpec(claim_key="", subject="response", triggers=frozenset(), reasons=frozenset({ranking.vocabulary.QUEUE_REASON}),
                        ehmf_types=response_types(entry) if entry is not None else frozenset(), k=response_k(entry), held=False)
        upsert_item(self.db, record_row=self.current_row, spec=spec, entry=entry, package=self.package, now=self.now)
        return None


def log_derived(kind: str, payload: dict) -> None:
    if kind == "batch":
        LOGGER.info("A ranking micro-batch closed", extra={FIELDS: {"event": "ranking.batch", "context": payload["context"],
                                                                    "batch_seq": payload["batch_seq"], "trigger": payload["trigger"],
                                                                    "models": sorted(payload["states"])}})
    elif kind in ("promote", "demote"):
        LOGGER.warning("The ranking incumbent changed", extra={FIELDS: {"event": f"ranking.{kind}", "context": payload["context"],
                                                                        "from": payload["from"], "to": payload["to"]}})
    elif kind == "alarm":
        event = "ranking.sustained_alarm" if payload["sustained"] else "ranking.alarm"
        LOGGER.warning("A ranking CUSUM alarm raised the X5 audit", extra={FIELDS: {"event": event, "stream": payload["stream"],
                                                                                    "statistic": payload["statistic"],
                                                                                    "observations": payload["observations"],
                                                                                    "sustained": payload["sustained"]}})
    elif kind == "select" and payload["kind"] == "fallback":
        LOGGER.warning("The eligible set was empty: the decision abstains", extra={FIELDS: {"event": "ranking.fallback", "context": payload["context"]}})


def _dialect_name(db: Session) -> str:
    return db.get_bind().dialect.name


def take_locks(db: Session) -> None:
    """The ranking advisory lock, then V3's, transaction-scoped, on PostgreSQL (SQLite serialises writers on its database
    lock). Every writer of ranking_events takes them first, so no two writers chain from the same prev_sha256."""
    from app.services.v3.scan import V3_SCAN_LOCK_KEY

    if _dialect_name(db) == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": RANKING_SCAN_LOCK_KEY})
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": V3_SCAN_LOCK_KEY})


def hold_windows_closed(db: Session, hold_id: str) -> bool:
    """Whether every X5 window raised under a hold has closed: its `hold` row's and every `alarm` row's naming it (note)."""
    from app.db_models import RankingEvent
    from app.services.v3.scan import window_remaining

    seqs = db.scalars(select(RankingEvent.v3_event_seq).where(RankingEvent.kind.in_(("hold", "alarm")), RankingEvent.note == hold_id)).all()
    return bool(seqs) and all(seq is not None and window_remaining(db, int(seq)) == 0 for seq in seqs)


def _load_state(db: Session) -> tuple[dict | None, str | None, str | None]:
    """(state or None on a mismatch, expected sha, actual sha). The first scan, with no event row, starts empty."""
    from app.db_models import RankingEvent, RankingState

    stored = db.get(RankingState, STATE_KEY)
    checkpoint = db.scalar(select(RankingEvent.payload).where(RankingEvent.kind == "checkpoint").order_by(RankingEvent.seq.desc()).limit(1))
    any_row = db.scalar(select(func.count()).select_from(RankingEvent)) or 0
    if stored is None and checkpoint is None and not any_row:
        return empty_state(), None, None
    expected = json.loads(checkpoint)["state_sha256"] if checkpoint is not None else None
    actual = sha256_hex(stored.payload.encode("utf-8")) if stored is not None else None
    if stored is None or expected is None or expected != actual or stored.sha256 != actual:
        return None, expected, actual
    return json.loads(stored.payload), expected, actual


def save_state(db: Session, state: dict, *, event_seq: int) -> None:
    from app.db_models import RankingIncumbent, RankingState

    body = canonical(state).decode("utf-8")
    rows = {STATE_KEY: body}
    for key, context in state["contexts"].items():
        for model, entry in context["models"].items():
            rows[f"{model}|{key}"] = canonical(entry).decode("utf-8")
    for key, payload in rows.items():
        row = db.get(RankingState, key)
        digest = sha256_hex(payload.encode("utf-8"))
        if row is None:
            db.add(RankingState(state_key=key, payload=payload, sha256=digest, updated_event_seq=int(event_seq)))
        elif row.payload != payload:
            row.payload, row.sha256, row.updated_event_seq = payload, digest, int(event_seq)
    for key, context in state["contexts"].items():
        row = db.get(RankingIncumbent, key)
        if row is None:
            db.add(RankingIncumbent(context_key=key, model_key=context["incumbent"], since_event_seq=int(event_seq)))
        elif row.model_key != context["incumbent"]:
            row.model_key, row.since_event_seq = context["incumbent"], int(event_seq)
    db.flush()


def _ledger_head(db: Session) -> int:
    from app.db_models import ResponseLedgerHead
    from app.services.ledger import CHAIN

    return int(db.scalar(select(ResponseLedgerHead.seq).where(ResponseLedgerHead.chain == CHAIN)) or 0)


def availability_of(candidates: list, *, settings: Any, package: Any, gateway: Any = None) -> dict:
    from app.gateway.registry import registry_for

    registry = {spec.adapter_id: spec for spec in registry_for(package, settings).members}
    out = {}
    for model in candidates:
        if model.adapter_id in package.ranking.static_models:
            out[model.adapter_id] = "kill_switch" if (settings.model_gateway_kill_switch or "none") != "none" else None
            continue
        if gateway is None:
            from app.gateway.gateway import get_gateway

            gateway = get_gateway()
        out[model.adapter_id] = gateway.ineligible_reason(registry[model.adapter_id], settings=settings)
    return out


def x5_key(model: Any, *, static: bool) -> tuple[str, str]:
    """The V3 model key and version a record of this candidate carries (spec conflict 14)."""
    if static:
        return f"generator-prompt:{model.adapter_id}", model.model_version
    return f"generator:{model.adapter_id}", f"{model.model_id}@{model.model_version}"


def record_x5_change(db: Session, model: Any, *, static: bool, from_version: str, settings: Any, package: Any, now: datetime) -> tuple[int, bool]:
    """The X5 model_change event for a candidate's version change: (v3 event seq, reused). V3's lock is held. `from_version`
    is the previous version in the form a record carries (x5_key's). When V3 already knows the new version from its own
    model_change event, that event is reused; when V3 knows it only from a first sighting (no event), the event is written
    from `from_version` and no second v3_model_versions row is added."""
    from app.db_models import V3Event, V3ModelVersion
    from app.services.v3 import triggers as trig
    from app.services.v3.queue import utc
    from app.services.v3.scan import known_versions, record_model_change

    key, version = x5_key(model, static=static)
    known = known_versions(db)
    sighted = known.get(key) == version
    if sighted:
        for seq, payload in db.execute(select(V3Event.seq, V3Event.payload).where(V3Event.kind == "model_change").order_by(V3Event.seq.desc())):
            body = json.loads(payload)
            if body.get("model_key") == key and body.get("to_version") == version:
                return int(seq), True
    previous = from_version if sighted or key not in known else known[key]
    head = _ledger_head(db)
    seq = record_model_change(db, trig.ModelChange(model_key=key, from_version=previous, to_version=version),
                              source="ranking", from_ledger_seq=head, window=int(package.v3.x5_window_deliveries), now=now)
    if not sighted:
        db.execute(insert(V3ModelVersion).values(model_key=key, model_version=version, first_seen_seq=head, source="ranking", seen_at=utc(now)))
    return seq, False


def run_scan(*, settings: Any, package: Any, session_factory: Callable[[], Session] = SessionLocal, store: Any = None, now: datetime | None = None,
             limit: int = 500, gateway: Any = None) -> ScanResult:
    from app.services.v3.queue import ATTEMPTS, V3Busy, sqlite_busy, utc

    if ranking.mode(settings, package) != "shadow":
        raise ranking.RankingOff("RANKING is off")
    now = utc(now or datetime.now(UTC))
    last: Exception | None = None
    for _ in range(ATTEMPTS):
        try:
            result = _scan_once(settings=settings, package=package, session_factory=session_factory, store=store, now=now, limit=limit,
                                gateway=gateway)
            break
        except OperationalError as exc:
            if not sqlite_busy(exc):
                raise
            last = exc
    else:
        raise V3Busy("the ranking scan could not complete within its attempts: the database stayed locked") from last
    if result.refused == "uncommissioned":
        raise ranking.RankingUncommissioned("a static candidate has no commission event: run python -m app.workers.ranking commission <id>")
    if result.refused is None:
        LOGGER.info("Ranking scan", extra={FIELDS: {"event": "ranking.scan", **{key: getattr(result, key) for key in (
            "from_seq", "to_seq", "records", "outcomes", "skipped", "batches", "alarms", "fallbacks", "done")}}})
    return result


def _scan_once(*, settings: Any, package: Any, session_factory: Callable[[], Session], store: Any, now: datetime, limit: int,
               gateway: Any) -> ScanResult:
    from app.db_models import RankingScan, ResponseLedgerRecord
    from app.services.ranking.contexts import span_modules
    from app.services.v3.queue import parse_entry

    with session_factory() as db:
        take_locks(db)
        if stopped(db):
            raise ranking.RankingStopped("the ranking log is stopped: run replay --check, fix the cause, then clear-stop")
        state, expected, actual = _load_state(db)
        if state is None:
            log = EventLog(db, empty_state(), now=now)
            log.control("stop", {"reason": "state_mismatch", "expected_sha256": expected, "actual_sha256": actual})
            db.commit()
            LOGGER.error("The ranking state does not match its checkpoint: the ranking is stopped",
                         extra={FIELDS: {"event": "ranking.stop", "reason": "state_mismatch", "expected_sha256": expected, "actual_sha256": actual}})
            return ScanResult(0, 0, 0, 0, 0, 0, 0, 0, True, refused="stopped")
        log = EventLog(db, state, now=now)
        log.settings, log.package = settings, package
        params = package.ranking
        known = _sync(db, log, state, settings=settings, package=package, gateway=gateway, now=now)
        uncommissioned = [name for name in params.static_models if not state["models"].get(name, {}).get("commissioned")]
        if uncommissioned:
            _finish(db, log, state)
            db.commit()
            return ScanResult(0, 0, 0, 0, 0, 0, 0, 0, True, refused="uncommissioned")
        for hold_id in sorted(state["holds"]):
            if hold_windows_closed(db, hold_id):
                log.append("hold_release", {"hold_id": hold_id})
        cursor = int(db.scalar(select(func.coalesce(func.max(RankingScan.to_seq), 0))) or 0)
        rows = db.execute(select(ResponseLedgerRecord.__table__).where(ResponseLedgerRecord.seq > cursor)
                          .order_by(ResponseLedgerRecord.seq).limit(int(limit))).all()
        if store is None:
            from app.services.store import get_course_store

            store = get_course_store()
        modules = span_modules(store)
        by_id = {model.adapter_id: model for model in known}
        versions = {name: entry["version"] for name, entry in state["models"].items()}
        outcomes = skipped = 0
        for row in rows:
            entry = parse_entry(row)
            result = outcome_of(entry, ledger_seq=int(row.seq), created_at=utc_text(row.created_at), candidates=by_id, modules=modules,
                                corpus_version=store.corpus_version, package=package, current_versions=versions)
            log.current_row, log.current_entry = row, entry
            if isinstance(result, Outcome):
                payload = outcome_payload(result)
                if log.append("outcome", payload, input_key=f"ledger:{int(row.seq)}", ledger_seq=int(row.seq),
                              context_key=result.context.key(), model_key=result.model) is not None:
                    outcomes += 1
            else:
                if log.append("skipped", {"ledger_seq": result.ledger_seq, "reason": result.reason, "model": result.model},
                              input_key=f"ledger:{int(row.seq)}", ledger_seq=int(row.seq), model_key=result.model) is not None:
                    skipped += 1
        log.current_row = log.current_entry = None
        _feedback(db, log)
        log.append("tick", {"at": utc_text(now)})
        to_seq = int(rows[-1].seq) if rows else cursor
        result = ScanResult(from_seq=cursor, to_seq=to_seq, records=len(rows), outcomes=outcomes, skipped=skipped, batches=log.counts["batches"],
                            alarms=log.counts["alarms"], fallbacks=log.counts["fallbacks"], done=len(rows) < int(limit))
        db.execute(insert(RankingScan).values(from_seq=cursor, to_seq=to_seq, records=len(rows), outcomes=outcomes, skipped=skipped,
                                              batches=result.batches, alarms=result.alarms, fallbacks=result.fallbacks,
                                              package_version=package.package_version, package_sha256=package.sha256, created_at=now))
        _finish(db, log, state)
        db.commit()
    return result


def _sync(db: Session, log: EventLog, state: dict, *, settings: Any, package: Any, gateway: Any, now: datetime) -> list:
    """Steps 3 of the scan: config, model_seen or model_change per candidate, then availability. Returns the candidates."""
    from app.services.ranking.models import candidates as list_candidates

    params = package.ranking
    if state["parameters_sha256"] != params.parameters_sha256:
        log.append("config", {"package_version": package.package_version, "package_sha256": package.sha256,
                              "parameters_sha256": params.parameters_sha256, "parameters": params.block})
    known = list_candidates(package, settings)
    for model in known:
        entry = state["models"].get(model.adapter_id)
        if entry is None:
            log.append("model_seen", {"model": model.as_dict()}, model_key=model.adapter_id)
        elif entry["version"] != model.model_version:
            static = model.adapter_id in params.static_models
            previous = entry["version"] if static else f"{entry['model_id']}@{entry['version']}"   # x5_key's form, before the change
            v3_seq, reused = record_x5_change(db, model, static=static, from_version=previous, settings=settings, package=package, now=now)
            payload = {"adapter_id": model.adapter_id, "from_version": entry["version"], "to_version": model.model_version,
                       "source": "package" if static else "registry"}
            log.append("model_change", payload, model_key=model.adapter_id, v3_event_seq=v3_seq)
            LOGGER.warning("A ranking candidate's version changed: deflated, capped at C, X5 raised", extra={FIELDS: {
                "event": "ranking.model_change", "adapter_id": model.adapter_id, "from_version": payload["from_version"],
                "to_version": payload["to_version"], "reused_v3_event": reused}})
    availability = availability_of(known, settings=settings, package=package, gateway=gateway)
    if any(state["availability"].get(name, "unseen") != reason for name, reason in availability.items()):
        log.append("availability", {"models": availability})
    return known


def _feedback(db: Session, log: EventLog) -> None:
    """A learner's X3 flag (F = 0) on a pending outcome of a record the learner was shown (delivery "delivered"); a shadow
    record was never shown, and a legacy record has no ranked generator, so none arises today (spec conflict 12)."""
    from app.db_models import ResponseLedgerRecord
    from app.services.v3.feedback import f_i

    pending = sorted(int(item["ledger_seq"]) for context in log.state["contexts"].values() for item in context["pending"]
                     if item["signals"].get("F") is None)
    if not pending:
        return
    shown = db.scalars(select(ResponseLedgerRecord.seq).where(ResponseLedgerRecord.seq.in_(pending),
                                                              ResponseLedgerRecord.delivery == "delivered")).all()
    for seq in sorted(shown):
        if f_i(db, int(seq)) == 0.0:
            log.append("feedback", {"ledger_seq": int(seq), "F": "0", "source": "x3"}, input_key=f"feedback:{int(seq)}", ledger_seq=int(seq))


def _finish(db: Session, log: EventLog, state: dict) -> None:
    seq = log.control("checkpoint", {"state_sha256": state_sha256(state), "last_input_seq": int(state["last_input_seq"])})
    save_state(db, state, event_seq=seq)


def scan_until_done(*, settings: Any, package: Any, session_factory: Callable[[], Session] = SessionLocal, now: datetime | None = None,
                    limit: int = 500, max_batches: int = 10_000, store: Any = None, gateway: Any = None) -> list[ScanResult]:
    results = []
    for _ in range(max_batches):
        result = run_scan(settings=settings, package=package, session_factory=session_factory, now=now, limit=limit, store=store, gateway=gateway)
        results.append(result)
        if result.done or result.refused:
            break
    return results


def append_inputs(db: Session, inputs: list[tuple[str, dict]], *, settings: Any, package: Any, now: datetime, gateway: Any = None) -> list[int]:
    """Append operator inputs (commission, recommission_pass, recommission_fail) with their derived events and a checkpoint,
    under the scan's locks, in the caller's transaction (the worker commits). The state must match its checkpoint. An input
    the controller would refuse (recommission.refusal: an unknown model, a commission for a model with outcomes, another
    version) raises RankingInputRefused before anything of the call is appended; the caller does not commit."""
    from app.services.ranking.recommission import refusal

    take_locks(db)
    if stopped(db):
        raise ranking.RankingStopped("the ranking log is stopped")
    state, _expected, _actual = _load_state(db)
    if state is None:
        raise ranking.RankingStopped("the ranking state does not match its checkpoint")
    log = EventLog(db, state, now=now)
    log.settings, log.package = settings, package
    _sync(db, log, state, settings=settings, package=package, gateway=gateway, now=now)
    seqs = []
    for kind, payload in inputs:
        reason = refusal(log.state, kind, payload) if kind in ("commission", "recommission_pass", "recommission_fail") else None
        if reason is not None:
            db.rollback()
            raise ranking.RankingInputRefused(kind, reason)
        seqs.append(log.append(kind, payload, model_key=payload.get("adapter_id")))
    _finish(db, log, state)
    return seqs
