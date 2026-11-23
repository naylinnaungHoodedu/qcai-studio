"""Queue priority: severity x exposure x (1 - K) (plan Phase 6 D task 2, AC-6-3; plan L861-862 "V3 ordering severity x
exposure x (1 - K) are built for study, pending confirmation"; Phase 6 spec 4.3; PD-34).

Exact rationals throughout (fractions.Fraction); an item stores float() of each value, and with the small denominators
these rules give (weights in fifths, a share's members at most 3, a mean over at most 20 claims) two distinct priorities
never collide as floats. Rules (configuration package v5 v3.priority, provisional):
  severity  severity-exposure-one-minus-k-v1: the largest EHMF weight among an item's types (V2 objections and non-pass
            V1 results; a disclosed V1.7 conflict weighs nothing), the "unknown" weight (1.0) when no type is known
  exposure  learner-deliveries-of-claim-set-v1: the learner deliveries the scan considered (v3_draws rows) whose claim-set
            key (sorted-claim-ids-sha256-v1, draw.claim_set_key) equals the record's, up to its record, at least 1; 1 for a
            shadow record, an abstention or a record without a key. Computed once, when the item is created.
  K         panel-support-share-v1: a claim's V2 panel support share (families voting SUPPORTED over members), the mean
            over a response's judged claims, 0 without a panel vote (a withheld claim included).
The queue orders by priority descending, then enqueued_at, then item_id (TIE_BREAK).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from fractions import Fraction
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session


def severity(types: Iterable[str], weights: Mapping[str, Fraction]) -> Fraction:
    known = [weights[name] for name in types if name in weights]
    return max(known) if known else weights["unknown"]


def support_share(v2: Any) -> Fraction:
    if v2 is None or not v2.members or v2.outcome == "withheld":
        return Fraction(0)
    members = len(v2.members)
    return Fraction(members - int(v2.objections), members)


def response_k(entry: Any) -> Fraction:
    verification = getattr(entry, "verification", None)
    verdicts = getattr(verification, "verdicts", ()) if verification is not None else ()
    shares = [support_share(verdict.v2) for verdict in verdicts
              if getattr(verdict, "v2", None) is not None and verdict.v2.members]
    return sum(shares, Fraction(0)) / len(shares) if shares else Fraction(0)


def exposure_for(db: Session, record: Any, key: str | None) -> int:
    """record: a response_ledger row (seq, delivery, decision)."""
    from app.db_models import V3Draw

    if key is None or record.delivery == "shadow" or record.decision == "abstain":
        return 1
    count = db.scalar(select(func.count()).select_from(V3Draw).where(V3Draw.claim_set_key == key, V3Draw.ledger_seq <= int(record.seq)))
    return max(1, int(count or 0))


def priority(severity: Fraction, exposure: int, k: Fraction) -> Fraction:
    return Fraction(severity) * int(exposure) * (1 - Fraction(k))
