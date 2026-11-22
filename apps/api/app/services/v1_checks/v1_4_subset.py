"""V1.4, factual sentences map to locked claims (plan Phase 4 D: EHMF D and E, "HARD; regen <= 2"; Phase 4 spec 4.5).

V1.4 IS the Phase 3 subset check (app.services.claim_gate, rule segment-exact-whitespace-v3): every factual segment of
a rendering names a locked claim and carries its text exactly; questions and template connectives are typed
non-factual by the renderer. There is no second implementation: render_checked runs the subset check through the
pipeline module's check_subset global (the one seam tests patch) and hands its result to the V1 hook in
RenderAttempt.subset; this module only maps that result to a CheckResult:
  the renderer raised, or the subset check raised on a valid envelope   hard_fail / render_failed
  the subset check passed                                               pass / mapped
  otherwise                                                             hard_fail / its first problem code
A hard fail judges that rendering only: the runner re-renders (at most twice), then abstains.
"""

from __future__ import annotations

from app.services.claim_gate import PROBLEM_CODES, SubsetCheckResult
from app.services.tutor_pipeline.contracts import SUBSET_PROBLEM_CODES, CheckResult
from app.services.v1_checks.results import make_result

if tuple(PROBLEM_CODES) != tuple(SUBSET_PROBLEM_CODES):  # pragma: no cover - package_check and a test compare them too
    raise ImportError("contracts.SUBSET_PROBLEM_CODES must equal claim_gate.PROBLEM_CODES")


def v1_4_result(subset: SubsetCheckResult | None, *, fault: str | None, attempt: int) -> CheckResult:
    if fault is not None or subset is None:
        return make_result("V1.4", "post_render", attempt, "render_failed")
    if subset.passed:
        return make_result("V1.4", "post_render", attempt, "mapped")
    return make_result("V1.4", "post_render", attempt, subset.problems[0])
