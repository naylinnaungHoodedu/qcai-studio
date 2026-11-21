"""V1.1 and V1.2 on the legacy contained answer (plan Phase 4 L: "V1.1/V1.2 stay enforced with extractive mode or
abstention [Decision D-19], never the legacy overlap gate alone [Risk R-16]"; Phase 4 spec 4.15, conflicts 4, 22, 34).

Every delivery path that can deliver a claim (/assistant/chat, /tutor/turns, /qa/ask) passes the D-19 contained answer
through guard_contained before anything reads it. For each quotation (a GroundedClaim) and each span it cites:
  V1.1  the span id resolves in the current corpus (SpanResolver.resolve_current) with the citation's content hash;
  V1.2  the quotation cites at least one span and, without a trailing display "...", is a substring of the span's
        normalize_display_text (verbatim binding);
  V1.2  polarity, claim to span (E-27; only with a package v1 block): every quantity of the quotation is covered by the
        span (lexicon.quantities_covered, closed units) and every negation cue of the quotation is in the span at
        least as often.
Any failure withholds the whole answer: the contained answer becomes today's abstention (the same bytes), the guard
counts it (V1_METRICS.legacy_guard) and logs tutor.v1.legacy_guard_withheld with the check, the reason and the surface
(a guard failure is an upstream defect). The guard has no flag and runs in every V1_PIPELINE mode. contain_answer
quotes only verified spans, so every current quotation passes and response bytes are unchanged; under D-31 nothing
is quoted outside development. Without a v1 block (a v1 or v2 package, development only: a governed build refuses
one at start-up) the polarity rule is skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Literal

from app.core.structured_logging import FIELDS
from app.services.contained_answers import ABSTENTION, ContainedAnswer
from app.services.span_resolver import SpanResolver
from app.services.text_utils import normalize_display_text
from app.services.v1_checks.lexicon import negation_cues, quantities_covered
from app.services.v1_checks.metrics import V1_METRICS

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config_package import ConfigPackage
    from app.services.content_assembler import CourseStore

LOGGER = logging.getLogger("qcai.tutor")
DISPLAY_ELLIPSIS = "..."


@dataclass(frozen=True)
class GuardResult:
    contained: ContainedAnswer
    withheld: tuple[tuple[str, str], ...]   # (check_id, reason_code)


def _collapsed(text: str) -> str:
    return " ".join(text.split())


def quotation_problem(text: str, span_ids, hashes: dict[str, str], resolver: SpanResolver, package: "ConfigPackage") -> tuple[str, str] | None:
    """(check_id, reason_code) of the first failure of one quotation, or None."""
    if not span_ids:
        return "V1.2", "unbound"
    quotation = _collapsed(text.removesuffix(DISPLAY_ELLIPSIS))
    for span_id in span_ids:
        resolved = resolver.resolve_current(span_id)
        if resolved is None:
            return "V1.1", "unresolvable"
        if span_id in hashes and hashes[span_id] != resolved.content_hash:
            return "V1.1", "content_hash_mismatch"
        span_text = _collapsed(normalize_display_text(resolved.text or ""))
        if not quotation or quotation not in span_text:
            return "V1.2", "not_verbatim"
        if package.v1 is not None:
            lexicon = package.v1.lexicon
            if not quantities_covered(quotation, span_text, lexicon):
                return "V1.2", "quantity_mismatch"
            span_cues = negation_cues(span_text, lexicon)
            if any(span_cues[cue] < count for cue, count in negation_cues(quotation, lexicon).items()):
                return "V1.2", "negation_mismatch"
    return None


def guard_contained(contained: ContainedAnswer, *, store: "CourseStore", package: "ConfigPackage",
                    surface: Literal["tutor", "qa"]) -> GuardResult:
    if contained.decision != "answer":
        V1_METRICS.guard(surface, withheld_by=None)
        return GuardResult(contained=contained, withheld=())
    resolver = SpanResolver(store)
    hashes = {citation.span_id or citation.chunk_id: citation.content_hash for citation in contained.citations}
    withheld = []
    for claim in contained.claims:
        problem = quotation_problem(claim.text, list(claim.cited_span_ids), hashes, resolver, package)
        if problem is not None:
            withheld.append(problem)
    if not contained.claims:
        withheld.append(("V1.2", "no_bound_claims"))
    if not withheld:
        V1_METRICS.guard(surface, withheld_by=None)
        return GuardResult(contained=contained, withheld=())
    check_id, reason = withheld[0]
    V1_METRICS.guard(surface, withheld_by=check_id)
    LOGGER.warning(
        "The V1.1/V1.2 legacy guard withheld a contained answer",
        extra={FIELDS: {"event": "tutor.v1.legacy_guard_withheld", "check_id": check_id, "reason_code": reason, "surface": surface}},
    )
    # Exactly contain_answer's own abstention, so the body bytes equal today's abstention.
    abstention = ContainedAnswer(answer=ABSTENTION, decision="abstain", reason="no_approved_span", dropped_unresolved=contained.dropped_unresolved)
    return GuardResult(contained=abstention, withheld=tuple(withheld))
