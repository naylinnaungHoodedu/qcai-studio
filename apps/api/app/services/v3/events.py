"""X5 events and the CUSUM interface (plan Phase 6 D task 1 "X5 CUSUM alarm or model change (audit 20%)"; plan 6.3
"version change -> X5 audit 20%"; Phase 6 spec 4.8; DI-96).

The CUSUM statistic, the meaning of "sustained", the stop-the-line (13.6) and "promotions held" are Phase 9's. Phase 6
defines the alarm contract (contracts.CusumAlarm, cusum-alarm-v1) and records each alarm: record_cusum_alarm inserts a
v3_events row whose window raises the audit rate to 1/5 over the next window_deliveries learner deliveries after the
ledger head, whatever the V3 mode (the next scan applies it), and logs v3.x5_event at WARNING. A synthetic-test alarm
is refused outside development. Model-version changes are recorded by the scan (scan.record_model_change). The Phase 9
ranking scan raises its alarms here (source phase9-cusum) inside its own transaction: with db the row is inserted in the
caller's session and not committed, so the alarm, the ranking event that names it and the scan commit together.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import logging
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.structured_logging import FIELDS
from app.services.tutor_pipeline.contracts import ledger_canonical
from app.services.v3.contracts import CusumAlarm

LOGGER = logging.getLogger("qcai.v3")


def record_cusum_alarm(alarm: CusumAlarm, *, settings: Any, package: Any, session_factory: Callable[[], Session] = SessionLocal,
                       now: datetime | None = None, db: Session | None = None) -> int:
    from app.db_models import ResponseLedgerHead, V3Event
    from app.services.ledger import CHAIN

    if alarm.source == "synthetic-test" and settings.environment.lower() != "development":
        raise ValueError("a synthetic-test CUSUM alarm is refused outside development")
    if package.v3 is None:
        raise ValueError("the configuration package has no v3 block")
    now = now or datetime.now(UTC)

    def insert_alarm(session: Session) -> int:
        head = session.scalar(select(ResponseLedgerHead.seq).where(ResponseLedgerHead.chain == CHAIN))
        result = session.execute(insert(V3Event).values(kind="cusum_alarm", payload=ledger_canonical(alarm.model_dump(mode="json")).decode("utf-8"),
                                                        from_ledger_seq=int(head or 0), window_deliveries=int(package.v3.x5_window_deliveries),
                                                        created_at=now))
        return int(result.inserted_primary_key[0])

    if db is not None:
        seq = insert_alarm(db)
    else:
        with session_factory() as session:
            seq = insert_alarm(session)
            session.commit()
    LOGGER.warning("A CUSUM alarm raised the audit rate (X5)", extra={FIELDS: {"event": "v3.x5_event", "kind": "cusum_alarm", "stream": alarm.stream}})
    return seq
