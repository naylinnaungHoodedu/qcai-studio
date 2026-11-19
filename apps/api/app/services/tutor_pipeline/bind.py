"""Claim binding, rule resolver-bundle-sentence-v1 (plan tasks 3.3-3.4; Phase 3 spec 4.6; R-11, R-13).

Every proposed claim is validated against the spans it cites, and dropped whole on the first failing check:
  unbound        it cites no span
  outside_bundle a cited span is not in the evidence bundle
  unresolvable   the Phase 2 SpanResolver does not resolve it, or its content hash differs from the bundle's
  not_quotable   a cited span is not a quotable (public-plane, bound, approved) document span (D-19, D-31)
  not_verbatim   the claim is not a whole sentences-v2 sentence of EVERY cited span (no entailment checker exists
                 before Phase 4, so a truncated sentence that drops a qualification or a negation never binds), or
                 the cited spans hold the sentence in different characters
  duplicate      the same sentence was already bound on all of the spans it cites
A claim is never re-bound to a span it did not cite: Phase 1's overlap rebinding is gone (plan 3.4).

What is locked is the span's own sentence (whitespace() form), never the generator's text: NFKC is used only to
compare (spec conflict 32; D-19 "verbatim"), so a generator that folds "x²" to "x2" binds, but the locked, ledgered
and rendered claim still reads "x²". A sentence proposed again on other spans that also hold it verbatim (the
splitter overlaps chunks, so one sentence can sit in two adjacent spans) is merged into the first claim, whose span
set becomes the union; it is counted as "merged", never as a binding failure (contracts.bound_claim_ratio_terms).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.core.config_package import TutorPipelineParams
from app.core.corpus_governance import CorpusRegistry
from app.services.contained_answers import span_is_quotable
from app.services.tutor_pipeline.contracts import (
    BINDING_FAILURES,
    MERGED,
    ClaimPlan,
    EvidenceBundle,
    ledger_canonical,
    sha256_hex,
)
from app.services.tutor_pipeline.text import normalise, sentences

if TYPE_CHECKING:  # pragma: no cover
    from app.services.content_assembler import CourseStore
    from app.services.span_resolver import SpanResolver

BINDING_RULE = "resolver-bundle-sentence-v1"
# What bind() counts in BindResult.dropped: every binding failure, and "merged" (which is not a failure).
DROP_REASONS = (*BINDING_FAILURES, MERGED)


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
    # Bound sentences in first-bound order: (normalised, verbatim) -> the union of the spans that cite it.
    bound: dict[tuple[str, str], set[str]] = {}
    dropped: Counter = Counter()
    sentence_cache: dict[str, dict[str, str]] = {}

    def sentences_of(span_id: str) -> dict[str, str]:
        """The span's sentences-v2 sentences: normalised form -> the span's own (whitespace-collapsed) text."""
        if span_id not in sentence_cache:
            record = store.span_registry.get(span_id)
            text = record.text if record is not None else ""
            found: dict[str, str] = {}
            for sentence in sentences(text, min_words=params.min_sentence_words, max_chars=params.max_sentence_chars):
                found.setdefault(normalise(sentence), sentence)
            sentence_cache[span_id] = found
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
                verbatim = {sentences_of(span_id).get(key) for span_id in span_ids}
                if None in verbatim or len(verbatim) != 1:
                    reason = "not_verbatim"
                else:
                    merge_key = (key, verbatim.pop())
                    spans = bound.get(merge_key)
                    if spans is None:
                        bound[merge_key] = set(span_ids)
                    elif set(span_ids) <= spans:
                        reason = "duplicate"
                    else:
                        spans.update(span_ids)
                        reason = MERGED
        if reason is not None:
            dropped[reason] += 1
    drafts = tuple(
        LockedClaimDraft(claim_id=claim_id_for(text, spans), text=text, span_ids=tuple(sorted(spans))) for (_, text), spans in bound.items()
    )
    return BindResult(bound=drafts, dropped=dropped, proposed=len(plan.claims))
