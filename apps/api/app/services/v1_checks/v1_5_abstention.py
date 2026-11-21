"""V1.5, abstention below the score floor (rule gate-decision-margin-v2; plan Phase 4 D: "below score floor; within
margin X4 mark", EHMF A, "abstain"; R-15; Phase 4 spec 4.6 and conflict 19).

V1.5 reads the active Phase 2 gate's sufficiency, which the evidence bundle carries, and applies the X4 margin that
configuration package v3 names for that gate (v1.v1_5.x4_margin, an operator value under Q-22):
  the gate returned nothing (below_floor, no_match, insufficient_coverage, no_query_terms), the corpus version
  differs, or no quotable span is left                                        abstain, with the gate's reason
  the top result's score lies within the X4 margin above the floor
  (score < floor + x4_margin)                                                 mark / near_miss
  otherwise                                                                   pass / answer
The floor is the gate's own (abstention.floor under bm25f-v1, P1-D-04's floor under p1-floor), and both gates drop
every result below it, so V1.5 never re-scores a span: it compares the top score the bundle records. The shipped X4
margins are bm25f-v1's abstention.margin (so V1.5 marks exactly what the gate flags near_floor) and 0.0 for p1-floor
(V1.5 never marks there); an owner value replaces either in the package alone. A mark is the Phase 6 X4 trigger
candidate: the response is labelled near_floor and its claims carry a V3 intent with trigger X4; it is never delivered
as confident.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.tutor_pipeline.contracts import CheckResult, Sufficiency
from app.services.v1_checks.results import make_result

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config_package import ConfigPackage


def check_v1_5(sufficiency: Sufficiency, *, x4_margin: float, attempt: int = 1) -> CheckResult:
    if sufficiency.decision == "abstain":
        return make_result("V1.5", "pre_render", attempt, sufficiency.reason)
    within = sufficiency.score is not None and sufficiency.score < sufficiency.floor + x4_margin
    return make_result("V1.5", "pre_render", attempt, "near_miss" if within else "answer")


def x4_margin(package: "ConfigPackage", gate: str) -> float:
    """The X4 margin V1.5 applies under this gate: package v3's v1.v1_5.x4_margin[gate]."""
    if package.v1 is None:
        raise ValueError("the configuration package has no v1 block")
    return package.v1.x4_margin[gate]
