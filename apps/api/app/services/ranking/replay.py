"""The replay and the stop (plan Phase 9 F "replay report", L "Stop: a replay mismatch."; AC-9-8; spec 4.11).

replay(events) folds the input events in seq order from empty_state() with controller.apply_in_place (control rows are
skipped) and returns the final state, the derived events it recomputed and the state sha256 at each checkpoint row.
compare() checks a stored log against its replay: the hash chain, every stored derived event (same order, count, kind and
canonical bytes), every checkpoint's state sha256 at its position, and the stored final state. A mismatch is the plan L
stop: the worker's `replay --check` (and the scan, on a state that does not match its checkpoint) appends a `stop` row and
the scan refuses until `clear-stop`. process_stop_state is /ready's cached read of the last stop or clear_stop row.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import threading
import time
from typing import Any

from app.core.structured_logging import FIELDS
from app.services.ranking.controller import RankingInputError, apply_in_place
from app.services.ranking.state import canonical, empty_state, sha256_hex, state_sha256
from app.services.ranking.vocabulary import CONTROL_KINDS, DERIVED_KINDS, GENESIS, INPUT_KINDS

LOGGER = logging.getLogger("qcai.ranking")


@dataclass(frozen=True)
class Replayed:
    state: dict
    derived: list            # [(input seq, kind, canonical payload text)]
    checkpoints: dict        # checkpoint row seq -> the replay's state sha256 there


@dataclass(frozen=True)
class ReplayCheck:
    ok: bool
    state_sha256: str | None
    stored_sha256: str | None
    first_mismatch_seq: int | None
    reason: str | None


def chain_sha256(prev: str, kind: str, payload: str) -> str:
    return sha256_hex(f"{prev}|{kind}|{payload}".encode("utf-8"))


def replay(events: list[dict]) -> Replayed:
    """events: dicts with seq, kind and payload (a dict, or its canonical text), in seq order."""
    state = empty_state()
    derived: list = []
    checkpoints: dict = {}
    for event in sorted(events, key=lambda item: int(item["seq"])):
        kind = event["kind"]
        if kind in INPUT_KINDS:
            payload = event["payload"] if isinstance(event["payload"], dict) else json.loads(event["payload"])
            for derived_kind, derived_payload in apply_in_place(state, {"seq": int(event["seq"]), "kind": kind, "payload": payload}):
                derived.append((int(event["seq"]), derived_kind, canonical(derived_payload).decode("utf-8")))
        elif kind == "checkpoint":
            checkpoints[int(event["seq"])] = state_sha256(state)
    return Replayed(state=state, derived=derived, checkpoints=checkpoints)


def compare(events: list[dict], stored_state_text: str | None) -> ReplayCheck:
    """A stored log (rows with seq, kind, payload text, prev_sha256, sha256) against its replay and the stored state."""
    rows = sorted(events, key=lambda item: int(item["seq"]))
    prev = GENESIS
    for row in rows:
        if row.get("sha256") is not None and (row["prev_sha256"] != prev or chain_sha256(prev, row["kind"], row["payload"]) != row["sha256"]):
            return ReplayCheck(False, None, None, int(row["seq"]), "chain")
        prev = row.get("sha256") or prev
    try:
        replayed = replay(rows)
    except (RankingInputError, KeyError, ValueError, TypeError, ArithmeticError) as exc:
        return ReplayCheck(False, None, None, None, f"input:{type(exc).__name__}")
    # Each stored derived row with the seq of the input row before it: a derived event follows the input that caused it.
    stored, last_input = [], 0
    for row in rows:
        if row["kind"] in INPUT_KINDS:
            last_input = int(row["seq"])
        elif row["kind"] in DERIVED_KINDS:
            stored.append(((last_input, row["kind"], row["payload"]), int(row["seq"])))
    recomputed = replayed.derived
    for index in range(max(len(stored), len(recomputed))):
        mine = recomputed[index] if index < len(recomputed) else None
        theirs = stored[index] if index < len(stored) else None
        if mine is None or theirs is None or mine != theirs[0]:
            seq = theirs[1] if theirs is not None else mine[0]
            return ReplayCheck(False, state_sha256(replayed.state), None, seq, "derived")
    for row in rows:
        if row["kind"] == "checkpoint":
            expected = json.loads(row["payload"])["state_sha256"]
            if replayed.checkpoints.get(int(row["seq"])) != expected:
                return ReplayCheck(False, replayed.checkpoints.get(int(row["seq"])), expected, int(row["seq"]), "checkpoint")
    final = state_sha256(replayed.state)
    stored_sha = sha256_hex(stored_state_text.encode("utf-8")) if stored_state_text is not None else None
    if stored_state_text is not None and canonical(replayed.state).decode("utf-8") != stored_state_text:
        return ReplayCheck(False, final, stored_sha, None, "state")
    return ReplayCheck(True, final, stored_sha, None, None)


def load_log(db: Any) -> tuple[list[dict], str | None]:
    from sqlalchemy import select

    from app.db_models import RankingEvent, RankingState
    from app.services.ranking.vocabulary import STATE_KEY

    rows = [{"seq": row.seq, "kind": row.kind, "payload": row.payload, "prev_sha256": row.prev_sha256, "sha256": row.sha256}
            for row in db.execute(select(RankingEvent).order_by(RankingEvent.seq)).scalars()]
    stored = db.get(RankingState, STATE_KEY)
    return rows, (stored.payload if stored is not None else None)


def check(db: Any) -> ReplayCheck:
    rows, stored = load_log(db)
    return compare(rows, stored)


def stopped(db: Any) -> bool:
    """Whether the last stop or clear_stop row is a stop."""
    from sqlalchemy import select

    from app.db_models import RankingEvent

    kind = db.scalar(select(RankingEvent.kind).where(RankingEvent.kind.in_(("stop", "clear_stop"))).order_by(RankingEvent.seq.desc()).limit(1))
    return kind == "stop"


_CACHE: dict[str, tuple[float, bool | None]] = {}
_CACHE_LOCK = threading.Lock()


def process_stop_state(settings: Any, package: Any, *, session_factory: Any = None) -> bool | None:
    """/ready's stop: None with no read when the ranking mode is off, else the last stop/clear_stop row (cached per process
    for ranking.replay.stop_refresh_s; None when the read fails). The read runs in a SAVEPOINT on PostgreSQL."""
    from app.services import ranking

    if ranking.mode(settings, package) == "off":
        return None
    key = package.sha256
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None and now - cached[0] < package.ranking.stop_refresh_s:
            return cached[1]
    if session_factory is None:
        from app.core.db import SessionLocal

        session_factory = SessionLocal
    value: bool | None
    try:
        with session_factory() as db:
            if db.get_bind().dialect.name == "postgresql":
                with db.begin_nested():
                    value = stopped(db)
            else:
                value = stopped(db)
    except Exception:  # noqa: BLE001 - an unreadable stop is reported as unknown (null), never as clear
        LOGGER.warning("The ranking stop could not be read", extra={FIELDS: {"event": "ranking.stop_unread"}})
        value = None
    with _CACHE_LOCK:
        _CACHE[key] = (now, value)
    return value


def reset_stop_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = ["CONTROL_KINDS", "ReplayCheck", "Replayed", "chain_sha256", "check", "compare", "load_log", "process_stop_state", "replay",
           "reset_stop_cache", "stopped"]
