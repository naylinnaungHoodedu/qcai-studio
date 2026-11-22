"""The V3 SLIs (plan Phase 6 I "Escalation share (V-3 <= 10% ...); queue age p90 alert [Risk R-40]"; plan 7.7 "SLIs
(citation resolution, verification completion, abstention, escalation share, queue age, residual error) derive from
ledger rows"; plan 13.7; Phase 6 spec 4.11, 10.4; PD-37).

slis(db, package, now) reports, from the stored queue, draws, gold rows and ledger rows:
  escalation_share  V-3: learner deliveries the scan considered in the window (slo.window_days) with an item whose
                    triggers include a counted trigger (X1-X4; audits X5 and X6 are proof tests, plan 15.3), over those
                    deliveries; a shadow record's item counts on the delivery it shadowed (resolved by ledger seq at read
                    time, never by a digest); at most 1/10, report only
  queue             open and claimed items, the open items' age p90 (nearest rank; the alert's measure) and oldest age
  draws             deliveries considered, drawn X6 and X5, the X6 rate, and the deliveries that are not auditable
  double_review     the round-2 pairs and how many agreed with round 1
  residual          the Wilson bound over X6-audited answer deliveries (residual.residual)
  gold              rows, the head, the claims labelled (toward Dawid-Skene's 200, a non-goal before then, DI-102)
  stop, x5          the stop (stop.stop_state) and the X5 windows
Ratios are "k/n" strings, so no float rounding is published. Counts only: no id, no digest, no text. Served on the
reviewer-only GET /v3/metrics and the worker's status line, never on the public /ready (DI-95 for the alerts).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import math
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

DAWID_SKENE_MINIMUM = 200


def _ratio(numerator: int, denominator: int) -> str:
    return f"{int(numerator)}/{int(denominator)}"


def nearest_rank(values: list[int], share: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def non_auditable(db: Session) -> dict:
    """Deliveries before the ledger, never drawn (plan Phase 6 G): tutor turns without a ledger record that expected
    none or came from an image that keeps no ledger, and the Q&A answers created before the ledger began."""
    from app.db_models import QAInteraction
    from app.services.ledger import ledger_coverage, ledger_started_at

    coverage = ledger_coverage(db, datetime(1970, 1, 1, tzinfo=UTC), horizon_s=0)
    started = ledger_started_at(db)
    query = select(func.count()).select_from(QAInteraction)
    if started is not None:
        query = query.where(QAInteraction.created_at < started)
    return {"tutor_turns": int(coverage["unrecorded"] + coverage["not_expected_earlier_image"] + coverage["ledger_disabled"]),
            "qa_before_ledger": int(db.scalar(query) or 0)}


def _delivery_seqs(db: Session, items: list[tuple[int, str]]) -> set[int]:
    """The delivery seq of each (ledger_seq, record_kind) item: its own for a delivery, the shadowed delivery's for a
    shadow record (skipped when that record is absent)."""
    from app.db_models import ResponseLedgerRecord

    seqs = {seq for seq, kind in items if kind == "delivery"}
    shadow = sorted({seq for seq, kind in items if kind == "shadow"})
    if shadow:
        shadowed = [row[0] for row in db.execute(select(ResponseLedgerRecord.shadowed_response_id).where(ResponseLedgerRecord.seq.in_(shadow)))
                    if row[0]]
        if shadowed:
            seqs |= {int(row[0]) for row in db.execute(select(ResponseLedgerRecord.seq).where(ResponseLedgerRecord.response_id.in_(shadowed)))}
    return seqs


def slis(db: Session, package: Any, *, now: datetime) -> dict:
    from app.db_models import V3Claim, V3Draw, V3Event, V3GoldLabelRecord, V3QueueItem
    from app.services.v3.queue import split, utc
    from app.services.v3.residual import residual
    from app.services.v3.scan import open_windows
    from app.services.v3.stop import stop_state

    v3 = package.v3
    now = utc(now)
    since = now - timedelta(days=int(v3.window_days))
    window_seqs = {int(seq) for (seq,) in db.execute(select(V3Draw.ledger_seq).where(V3Draw.delivered_at >= since, V3Draw.delivered_at <= now))}
    counted = set(v3.counted)
    flagged = [(int(seq), kind) for seq, kind, triggers in db.execute(select(V3QueueItem.ledger_seq, V3QueueItem.record_kind, V3QueueItem.triggers))
               if split(triggers) & counted]
    escalated = len(_delivery_seqs(db, flagged) & window_seqs)
    deliveries = len(window_seqs)
    share_max = v3.escalation_share_max
    open_rows = db.execute(select(V3QueueItem.item_id, V3QueueItem.review_round, V3QueueItem.enqueued_at).where(V3QueueItem.state == "queued")).all()
    live = {(row.item_id, int(row.review_round)) for row in db.execute(select(V3Claim.item_id, V3Claim.review_round, V3Claim.lease_expires_at).where(
        V3Claim.adjudicated_at.is_(None))) if utc(row.lease_expires_at) > now}
    ages = [max(0, int((now - utc(row.enqueued_at)).total_seconds())) for row in open_rows]
    p90 = nearest_rank(ages, 0.9)
    considered = int(db.scalar(select(func.count()).select_from(V3Draw)) or 0)
    x6 = int(db.scalar(select(func.count()).select_from(V3Draw).where(V3Draw.drawn == "X6")) or 0)
    x5 = int(db.scalar(select(func.count()).select_from(V3Draw).where(V3Draw.drawn == "X5")) or 0)
    rounds: dict[str, dict[int, Any]] = {}
    for item_id, review_round, entry in db.execute(select(V3GoldLabelRecord.item_id, V3GoldLabelRecord.review_round, V3GoldLabelRecord.entry)):
        label = json.loads(entry)
        rounds.setdefault(item_id, {})[int(review_round)] = (label.get("claim_labels"), label.get("abstention_label"))
    pairs = [item for item in rounds.values() if 1 in item and 2 in item]
    agreeing = sum(1 for item in pairs if item[1] == item[2])
    head = db.execute(select(V3GoldLabelRecord.seq).order_by(V3GoldLabelRecord.seq.desc()).limit(1)).first()
    finals = [seq for (seq,) in db.execute(select(V3QueueItem.final_gold_seq).where(V3QueueItem.final_gold_seq.is_not(None)))]
    claims_labelled = 0
    if finals:
        for (entry,) in db.execute(select(V3GoldLabelRecord.entry).where(V3GoldLabelRecord.seq.in_(finals))):
            claims_labelled += len(json.loads(entry).get("claim_labels") or [])
    windows = open_windows(db)
    return {
        "escalation_share": {"deliveries": deliveries, "escalated": escalated, "share": _ratio(escalated, deliveries),
                             "max": _ratio(share_max.numerator, share_max.denominator),
                             "above_max": bool(deliveries) and escalated * share_max.denominator > share_max.numerator * deliveries,
                             "counted": sorted(counted), "window_days": int(v3.window_days)},
        "queue": {"open": len(open_rows), "claimed": sum(1 for row in open_rows if (row.item_id, int(row.review_round)) in live),
                  "age_p90_s": p90, "age_max_s": max(ages) if ages else None, "slo_s": int(v3.queue_age_slo_s),
                  "above_slo": p90 is not None and p90 > int(v3.queue_age_slo_s)},
        "draws": {"considered": considered, "x6": x6, "x5": x5, "x6_rate": _ratio(x6, considered), "non_auditable": non_auditable(db)},
        "double_review": {"pairs": len(pairs), "agreeing": agreeing, "agreement": _ratio(agreeing, len(pairs))},
        "residual": residual(db, package),
        "gold": {"rows": int(db.scalar(select(func.count()).select_from(V3GoldLabelRecord)) or 0), "head_seq": int(head[0]) if head else 0,
                 "claims_labelled": claims_labelled, "dawid_skene_minimum": DAWID_SKENE_MINIMUM},
        "stop": stop_state(db, package, now=now).as_dict(),
        "x5": {"active": any(remaining > 0 for _, remaining in windows), "events": int(db.scalar(select(func.count()).select_from(V3Event)) or 0)},
    }
