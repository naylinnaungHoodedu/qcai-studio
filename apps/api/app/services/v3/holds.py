"""What V3 withholds (plan Phase 6 J "no reviewer -> items stay withheld", L "Disabling V3 MUST NOT release withheld
items"; AC-6-1; Phase 6 spec 4.9).

withheld_claim_ids(entry) is the record's X1 claims at tier 1 (triggers.x1_held_claims: plan task 1 "withheld at tier
1"; an X1 claim at tier 2 or 3 is queued and counted, not held), with every claim the record withholds with a V3 intent:
the scan queues each with its intent's queue reasons (triggers.queue_reasons keeps the record's own, so a V2-shadow
record's V1.3-withheld claims are queued too), and an x4_margin intent is the record's X4 response item. Both are
pure over the immutable ledger record, independent of the V3 mode and of the queue table: disabling V3, a refused queue
DELETE, an applied label or the passing of time never shrinks the set. released() is always False in Phase 6: a release
is Phase 7 change control (DI-93). These are the API the delivered path must consult (DI-97). Under V3_QUEUE=on with
MODEL_GATEWAY=on the runner's sticky hold keeps every tier-1 X1 claim's final away from deliver, so the set and the
record's finals agree (v1_checks.runner).
"""

from __future__ import annotations

from typing import Any

from app.services.v3.triggers import x1_held_claims


def withheld_claim_ids(entry: Any) -> frozenset[str]:
    verification = getattr(entry, "verification", None)
    verdicts = getattr(verification, "verdicts", ()) if verification is not None else ()
    queued = {verdict.claim_id for verdict in verdicts if verdict.final == "withhold" and getattr(verdict, "v3", None) is not None}
    return x1_held_claims(entry) | frozenset(queued)


def released(item: Any) -> bool:
    return False
