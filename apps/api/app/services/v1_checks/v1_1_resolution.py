"""V1.1, every span id resolves (rule span-resolution-current-v1; plan Phase 4 D: "every span id resolves; else HARD",
EHMF B; R-13, R-14; Phase 4 spec 4.2).

Every span id of every proposed claim, in order, is resolved through the Phase 2 SpanResolver against the current
corpus_version (resolve_current: the in-memory registry of this build, no database read). The first failure decides:
  malformed_span_id      the id is not span-<64 lowercase hex>
  unresolvable           no span with this id exists in the current corpus (a fabricated or stale id)
  content_hash_mismatch  the span is in the evidence bundle with another content hash
A hard fail judges the whole candidate plan: it is discarded, never repaired (HARD = final, plan rule 1), and the
runner regenerates (at most twice) or abstains with unresolvable_citation. A plan that cites nothing passes here;
V1.2 drops its claims as unbound.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.span_resolver import SPAN_ID_PATTERN
from app.services.tutor_pipeline.contracts import CheckResult, ClaimPlan, EvidenceBundle
from app.services.v1_checks.results import make_result

if TYPE_CHECKING:  # pragma: no cover
    from app.services.span_resolver import SpanResolver


def resolution_problem(span_id: str, bundle: EvidenceBundle, resolver: "SpanResolver") -> str | None:
    if not isinstance(span_id, str) or not SPAN_ID_PATTERN.match(span_id):
        return "malformed_span_id"
    resolved = resolver.resolve_current(span_id)
    if resolved is None:
        return "unresolvable"
    in_bundle = next((span for span in bundle.spans if span.span_id == span_id), None)
    if in_bundle is not None and in_bundle.content_hash != resolved.content_hash:
        return "content_hash_mismatch"
    return None


def check_v1_1(plan: ClaimPlan, bundle: EvidenceBundle, *, resolver: "SpanResolver", attempt: int) -> CheckResult:
    reason = "resolved"
    for claim in plan.claims:
        for span_id in claim.span_ids:
            problem = resolution_problem(span_id, bundle, resolver)
            if problem is not None:
                reason = problem
                break
        if reason != "resolved":
            break
    return make_result("V1.1", "pre_render", attempt, reason)
