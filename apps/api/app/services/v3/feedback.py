"""Learner flags and F_i (plan Phase 6 D task 1 "X3 learner flag (F_i = 0, never a verdict)"; plan 7.8 invariant 5
"Ratings never certify truth -> F_i feeds quality only; X3 feeds the V3 queue"; AC-6-6; Phase 6 spec 4.7; PD-39).

record_flag is the intake behind POST /v3/flags, in development only until DI-97 adds the learner-facing control and its
privacy disclosure: the caller's own tutor turn (anyone else's, or a missing one, is the same V3NotFound), its legacy
ledger record (a pre-ledger turn is not auditable), one flag per learner and record (v3_flags, user-keyed, so erasure
and guest retention delete it), and, once triggers.x3_fires holds for the record's stored flags, the record's response
item with trigger X3. It writes no ledger row and changes no
verdict. f_i reads the queue: 0.0 for a record with an X3 item, None otherwise, so F_i outlives the learner's erasure
and never names a learner. No ledger schema holds a learner rating or flag (invariant 5's schema test).
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.structured_logging import FIELDS
from app.services import v3
from app.services.v3 import triggers as trig
from app.services.v3.queue import V3Conflict, V3NotFound, _dialect, _retrying, parse_entry, record_row, split, upsert_item, utc

LOGGER = logging.getLogger("qcai.v3")


def record_flag(db: Session, *, user_id: str, response_id: str, settings: Any, package: Any, now: datetime) -> tuple[int, bool]:
    from app.db_models import ResponseLedgerRecord, TutorTurn, V3Flag

    v3.require_on(settings, package)
    if settings.environment.lower() != "development":
        raise v3.V3Off("the flag intake is development-only (DI-97)")

    def body() -> tuple[int, bool]:
        turn = db.get(TutorTurn, response_id)
        if turn is None or turn.user_id != user_id:
            raise V3NotFound(response_id)
        seq = db.scalar(select(ResponseLedgerRecord.seq).where(ResponseLedgerRecord.response_id == response_id))
        if seq is None:
            if turn.ledger_record_expected is True:
                raise V3Conflict("not_recorded_yet")
            raise V3NotFound(response_id)
        # RETURNING says whether the row was inserted: psycopg reports rowcount -1 for this statement (an autoincrement key).
        statement = _dialect(db).insert(V3Flag).values(user_id=user_id, ledger_seq=int(seq), created_at=utc(now)).on_conflict_do_nothing(
            index_elements=["user_id", "ledger_seq"]).returning(V3Flag.id)
        if db.execute(statement).first() is None:
            return int(seq), True
        flags = db.scalar(select(func.count()).select_from(V3Flag).where(V3Flag.ledger_seq == int(seq))) or 0
        if trig.x3_fires(int(flags)):
            row = record_row(db, int(seq))
            entry = parse_entry(row)
            upsert_item(db, record_row=row, spec=trig.response_spec(entry, "X3"), entry=entry, package=package, now=now)
        return int(seq), False

    seq, duplicate = _retrying(db, body)
    LOGGER.info("A learner flag was recorded (X3)", extra={FIELDS: {"event": "v3.flag_recorded", "duplicate": duplicate}})
    return seq, duplicate


def f_i(db: Session, ledger_seq: int) -> float | None:
    from app.db_models import V3QueueItem

    for (triggers,) in db.execute(select(V3QueueItem.triggers).where(V3QueueItem.ledger_seq == int(ledger_seq))):
        if "X3" in split(triggers):
            return 0.0
    return None
