"""What a route does after a tutor turn commits (Phase 3 spec 7.12; conflicts 3 and 29).

1. The legacy ledger record, synchronously, so the record exists before the answer leaves (plan I "ledger writes
   100% of deliveries"). The route waits at most the append budget plus the wait grace (the shipped configuration
   package's tutor_pipeline.budgets, v5 since Phase 6 and v4 since Phase 5: 1500 + 250 ms; TUTOR_LEDGER_APPEND_BUDGET_MS overrides the
   budget), whatever the database does
   (pool checkout included); the append fails open and is counted (ledger.record_legacy_delivery). The delivery counts
   as attempted here, after the commit, never while it is prepared, so a turn that rolls back is no attempt (18.7 E5).
2. The two-pass shadow, as a background task that runs after the response body is sent; it never raises.
Both read identifiers prepared by the orchestrator, never request text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.ledger import LegacyDelivery, LegacyPreparationFailed, record_legacy_delivery
from app.services.tutor_pipeline.metrics import TWO_PASS_METRICS
from app.services.tutor_pipeline.shadow import ShadowJob


@dataclass(frozen=True)
class TurnFollowups:
    legacy: LegacyDelivery | LegacyPreparationFailed | None
    shadow: ShadowJob | None


def run_turn_followups(response: Any, orchestrator: Any, background_tasks: Any) -> None:
    followups = getattr(response, "_followups", None)
    if not isinstance(followups, TurnFollowups):
        return
    if followups.legacy is not None:
        record_legacy_delivery(followups.legacy, settings=getattr(orchestrator, "settings", None))  # never raises
    if followups.shadow is not None and hasattr(orchestrator, "run_shadow"):
        TWO_PASS_METRICS.scheduled()
        background_tasks.add_task(orchestrator.run_shadow, followups.shadow)
