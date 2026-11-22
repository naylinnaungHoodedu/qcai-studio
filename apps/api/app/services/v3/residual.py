"""The residual-error bound (plan Phase 6 D task 4 "Wilson residual bounds"; AC-6-5; plan 15.3 "HR-3 deployment form:
monthly Wilson bound from the 5% draw [Evidence E-85]"; Phase 6 spec 4.11).

The population is every X6-drawn learner delivery that was an answer and whose item has a final gold label; an error is
one whose final label has residual_error (a claim labelled other than SUPPORTED). The bound is the 95% Wilson upper bound
(app.services.citation_migration.wilson_interval, the API image's copy of evaluation/qcai_eval/statistics.wilson_interval,
which test_citation_migration keeps equal), overall and per UTC month of delivery. Report only: audit counts are
telemetry, not research results (plan Phase 6 H); HR-3's study form is Phase 10's.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.citation_migration import wilson_interval

EVIDENCE_CLASS = "telemetry, not research results (plan Phase 6 H)"


def wilson_upper(errors: int, audited: int) -> float:
    return wilson_interval(int(errors), int(audited))["upper"]


def residual(db: Session, package: Any) -> dict:
    from app.db_models import V3Draw, V3GoldLabelRecord, V3QueueItem
    from app.services.v3.queue import split, utc

    audited = errors = 0
    months: dict[str, list[int]] = {}
    query = (select(V3QueueItem.triggers, V3GoldLabelRecord.entry, V3Draw.delivered_at)
             .join(V3GoldLabelRecord, V3GoldLabelRecord.seq == V3QueueItem.final_gold_seq)
             .join(V3Draw, V3Draw.ledger_seq == V3QueueItem.ledger_seq)
             .where(V3QueueItem.final_gold_seq.is_not(None)))
    for triggers, entry, delivered_at in db.execute(query):
        if "X6" not in split(triggers):
            continue
        label = json.loads(entry)
        if not label.get("delivered_answer"):
            continue
        error = bool(label.get("residual_error"))
        audited += 1
        errors += int(error)
        month = utc(delivered_at).strftime("%Y-%m")
        bucket = months.setdefault(month, [0, 0])
        bucket[0] += 1
        bucket[1] += int(error)
    interval = wilson_interval(errors, audited)
    return {
        "audited": audited, "errors": errors, "wilson95": {"lower": interval["lower"], "upper": interval["upper"]},
        "by_month": [{"month": month, "audited": count, "errors": wrong, "upper": wilson_upper(wrong, count)}
                     for month, (count, wrong) in sorted(months.items())],
        "report_only": True, "evidence_class": EVIDENCE_CLASS,
    }
