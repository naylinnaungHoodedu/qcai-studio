"""Claim binding, rule resolver-bundle-sentence-v1 (plan tasks 3.3-3.4; Phase 3 spec 4.6; R-11, R-13).

Every proposed claim is validated against the spans it cites, and dropped whole on the first failing check:
  unbound        it cites no span
  outside_bundle a cited span is not in the evidence bundle
  unresolvable   the Phase 2 SpanResolver does not resolve it, or its content hash differs from the bundle's
  not_quotable   a cited span is not a quotable (public-plane, bound, approved) document span (D-19, D-31)
  not_verbatim   the claim is not a whole sentences-v1 sentence of EVERY cited span (no entailment checker exists
                 before Phase 4, so a truncated sentence that drops a qualification or a negation never binds)
  duplicate      the same claim and span set was already bound
A claim is never re-bound to a span it did not cite: Phase 1's overlap rebinding is gone (plan 3.4).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.core.config_package import TutorPipelineParams
from app.core.corpus_governance import CorpusRegistry
from app.services.contained_answers import span_is_quotable
from app.services.tutor_pipeline.contracts import ClaimPlan, EvidenceBundle, ledger_canonical, sha256_hex
from app.services.tutor_pipeline.text import normalise, sentences_v1, whitespace

if TYPE_CHECKING:  # pragma: no cover
    from app.services.content_assembler import CourseStore
    from app.services.span_resolver import SpanResolver

BINDING_RULE = "resolver-bundle-sentence-v1"
DROP_REASONS = ("unbound", "outside_bundle", "unresolvable", "not_quotable", "not_verbatim", "duplicate")


@dataclass(frozen=True)
class LockedClaimDraft:
    claim_id: str
    text: str
    span_ids: tuple[str, ...]


@dataclass(frozen=True)
class BindResult:
    bound: tuple[LockedClaimDraft, ...]
    dropped: Counter = field(default_factory=Counter)
    proposed: int = 0


def claim_id_for(text: str, span_ids) -> str:
    """Content-addressed: the same claim on the same spans has the same id in every plan and response."""
    return "claim-" + sha256_hex(ledger_canonical({"text": normalise(text), "span_ids": sorted(span_ids)}))[:32]


def bind(
    plan: ClaimPlan,
    bundle: EvidenceBundle,
    *,
    resolver: "SpanResolver",
    store: "CourseStore",
    registry: CorpusRegistry,
    params: TutorPipelineParams,
) -> BindResult:
    in_bundle = {span.span_id: span for span in bundle.spans}
    bound: list[LockedClaimDraft] = []
    dropped: Counter = Counter()
    seen: set[tuple[str, tuple[str, ...]]] = set()
    sentence_cache: dict[str, set[str]] = {}

    def sentences_of(span_id: str) -> set[str]:
        if span_id not in sentence_cache:
            record = store.span_registry.get(span_id)
            text = record.text if record is not None else ""
            sentence_cache[span_id] = {
                normalise(sentence)
                for sentence in sentences_v1(text, min_words=params.min_sentence_words, max_chars=params.max_sentence_chars)
            }
        return sentence_cache[span_id]

    for claim in plan.claims:
        span_ids = tuple(sorted(set(claim.span_ids)))
        reason = None
        if not span_ids:
            reason = "unbound"
        elif any(span_id not in in_bundle for span_id in span_ids):
            reason = "outside_bundle"
        else:
            for span_id in span_ids:
                resolved = resolver.resolve_current(span_id)
                if resolved is None or resolved.content_hash != in_bundle[span_id].content_hash:
                    reason = "unresolvable"
                    break
            if reason is None:
                for span_id in span_ids:
                    record = store.span_registry.get(span_id)
                    if record is None or not span_is_quotable(record, registry):
                        reason = "not_quotable"
                        break
            if reason is None:
                key = normalise(claim.text)
                if not all(key in sentences_of(span_id) for span_id in span_ids):
                    reason = "not_verbatim"
                elif (key, span_ids) in seen:
                    reason = "duplicate"
                else:
                    seen.add((key, span_ids))
        if reason is not None:
            dropped[reason] += 1
            continue
        text = whitespace(claim.text)
        bound.append(LockedClaimDraft(claim_id=claim_id_for(text, span_ids), text=text, span_ids=span_ids))
    return BindResult(bound=tuple(bound), dropped=dropped, proposed=len(plan.claims))
