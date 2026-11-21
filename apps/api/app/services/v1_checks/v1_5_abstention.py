"""V1.5, abstention below the score floor (rule gate-decision-margin-v1; plan Phase 4 D: "below score floor; within
margin X4 mark", EHMF A, "abstain"; R-15; Phase 4 spec 4.6 and conflict 19).

V1.5 maps the active Phase 2 gate's own sufficiency decision, which the evidence bundle carries:
  the gate returned nothing (below_floor, no_match, insufficient_coverage, no_query_terms), the corpus version
  differs, or no quotable span is left                                        abstain, with the gate's reason
  near_miss: the top result lies within the X4 margin above the floor         mark / near_miss
  answer                                                                      pass / answer
Under bm25f-v1 the gate already drops every result below abstention.floor and flags near_floor exactly when
score < floor + margin, so a second scoring could never disagree and none is made. A mark is the Phase 6 X4 trigger
candidate: the response is labelled near_floor and its claims carry a V3 intent with trigger X4; it is never
delivered as confident. Under p1-floor the gate's margin is 0, so V1.5 never marks there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.tutor_pipeline.contracts import CheckResult, Sufficiency
from app.services.v1_checks.results import make_result

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config_package import ConfigPackage


def check_v1_5(sufficiency: Sufficiency, *, attempt: int = 1) -> CheckResult:
    if sufficiency.decision == "abstain":
        return make_result("V1.5", "pre_render", attempt, sufficiency.reason)
    return make_result("V1.5", "pre_render", attempt, "near_miss" if sufficiency.decision == "near_miss" else "answer")


def x4_margin(package: "ConfigPackage", gate: str) -> float:
    """The X4 margin frozen in package v3 for this gate (recorded, never re-applied): bm25f-v1's is abstention.margin,
    p1-floor's 0.0 (the loader refuses any other value)."""
    if package.v1 is None:
        raise ValueError("the configuration package has no v1 block")
    return package.v1.x4_margin[gate]
