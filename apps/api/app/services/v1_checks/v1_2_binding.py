"""V1.2, every claim is bound, with its numbers and negations intact (rule binding-polarity-v1; plan Phase 4 D:
">=1 resolved span per claim", EHMF A and B, "drop/abstain"; E-27; R-16; Phase 4 spec 4.3).

Binding is the Phase 3 rule resolver-bundle-sentence-v2 (tutor_pipeline.bind, unchanged): each proposed claim must be a
verbatim whole sentence of every span it cites, so a claim is bound to at least one resolved span or dropped. bind()
reports one outcome per proposed claim, which becomes that claim's V1.2 result.

On top of it, the polarity rule quantity-negation-polarity-v1, which never strips a negation or a number (the legacy
overlap gate's stopwords did, E-27). For a claim and the whole sentences of its cited bundle spans (the sentences-v2
pieces of the span text when it holds none):
  best = the highest Jaccard similarity of alignment terms between the claim and a sentence; best 0 means the claim
  aligns with nothing, so no polarity judgement is made (its binding outcome stands);
  among the sentences at best, the claim passes when one of them covers every quantity of the claim (same number and
  unit; a unit-less claim number may match the number with any unit) and holds exactly the claim's negation cues;
  otherwise quantity_mismatch (no top sentence covers the quantities) or negation_mismatch.
A claim whose polarity fails is dropped with that reason whatever bind said; a bound draft whose sentence fails is
removed from the locked set and counted (polarity_dropped). A verbatim draft cannot fail, so for the extractive
generator the rule is defence in depth for later binding rules and generators.

A claim-scoped hard_fail drops that proposed claim for good; the candidate's other claims go on. No claim left is a
response-level abstain (no_bound_claims), never a regeneration (plan "drop/abstain"). The legacy overlap gate is never
the decision (R-16).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from app.services.tutor_pipeline.bind import BindResult, LockedClaimDraft, bind, claim_id_for, whole_sentences
from app.services.tutor_pipeline.contracts import DUPLICATE, MERGED, CheckResult, ClaimPlan, EvidenceBundle
from app.services.tutor_pipeline.text import normalise, sentences
from app.services.v1_checks.lexicon import alignment_terms, jaccard, negation_cues, quantities_covered
from app.services.v1_checks.results import make_result

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config_package import TutorPipelineParams, V1Params
    from app.core.corpus_governance import CorpusRegistry
    from app.services.content_assembler import CourseStore
    from app.services.span_resolver import SpanResolver

BOUND_OUTCOMES = ("bound", MERGED, DUPLICATE)


@dataclass(frozen=True)
class BindingCheck:
    results: tuple[CheckResult, ...]
    bind: BindResult
    drafts: tuple[LockedClaimDraft, ...]
    polarity_dropped: Counter = field(default_factory=Counter)

    @property
    def dropped(self) -> Counter:
        """bind's drop counts plus V1.2's polarity drops: what an enforce record's counts.dropped holds."""
        total = Counter(self.bind.dropped)
        total.update(self.polarity_dropped)
        return total


def polarity_problem(claim_text: str, candidates: Sequence[str], *, v1: "V1Params", stopwords: Iterable[str]
                     ) -> Literal["quantity_mismatch", "negation_mismatch"] | None:
    lexicon = v1.lexicon
    terms = alignment_terms(claim_text, lexicon, stopwords)
    scored = [(jaccard(terms, alignment_terms(candidate, lexicon, stopwords)), candidate) for candidate in candidates]
    best = max((score for score, _ in scored), default=0.0)
    if best == 0:
        return None
    top = [candidate for score, candidate in scored if score == best]
    cues = negation_cues(claim_text, lexicon)
    covering = [candidate for candidate in top if quantities_covered(claim_text, candidate, lexicon)]
    if any(negation_cues(candidate, lexicon) == cues for candidate in covering):
        return None
    return "quantity_mismatch" if not covering else "negation_mismatch"


def span_candidates(span_ids: Iterable[str], bundle: EvidenceBundle, *, store: "CourseStore", params: "TutorPipelineParams") -> list[str]:
    """The whole sentences of the cited spans that are in the bundle, or, when they hold none, the sentences-v2 pieces
    of those spans' own text."""
    in_bundle = {span.span_id for span in bundle.spans}
    records = [store.span_registry.get(span_id) for span_id in span_ids if span_id in in_bundle]
    records = [record for record in records if record is not None]
    found = [sentence.text for record in records
             for sentence in whole_sentences(record, store, min_words=params.min_sentence_words, max_chars=params.max_sentence_chars)]
    if found:
        return found
    return [piece for record in records for piece in sentences(record.text, min_words=params.min_sentence_words, max_chars=params.max_sentence_chars)]


def check_v1_2(
    plan: ClaimPlan,
    bundle: EvidenceBundle,
    *,
    resolver: "SpanResolver",
    store: "CourseStore",
    registry: "CorpusRegistry",
    params: "TutorPipelineParams",
    v1: "V1Params",
    stopwords: Iterable[str],
    attempt: int,
    bind_fn: Callable[..., BindResult] = bind,
) -> BindingCheck:
    outcomes: list[str] = []
    bound = bind_fn(plan, bundle, resolver=resolver, store=store, registry=registry, params=params, outcomes=outcomes)
    if len(outcomes) != len(plan.claims):
        raise ValueError("bind reported no outcome for some proposed claim")
    # The drafts whose locked sentence fails polarity are removed (defence in depth; a verbatim draft cannot fail).
    draft_problem = {
        draft.claim_id: polarity_problem(draft.text, span_candidates(draft.span_ids, bundle, store=store, params=params), v1=v1, stopwords=stopwords)
        for draft in bound.bound
    }
    by_text = {normalise(draft.text): draft for draft in bound.bound}
    results: list[CheckResult] = []
    for claim, outcome in zip(plan.claims, outcomes):
        draft = by_text.get(normalise(claim.text)) if outcome in BOUND_OUTCOMES else None
        if draft is not None:
            reason = draft_problem[draft.claim_id] or outcome
            claim_id = draft.claim_id
        else:
            candidates = span_candidates(claim.span_ids, bundle, store=store, params=params)
            reason = polarity_problem(claim.text, candidates, v1=v1, stopwords=stopwords) or outcome
            claim_id = claim_id_for(claim.text, claim.span_ids)
        results.append(make_result("V1.2", "pre_render", attempt, reason, claim_id=claim_id))
    drafts = tuple(draft for draft in bound.bound if draft_problem[draft.claim_id] is None)
    polarity_dropped: Counter = Counter(problem for problem in draft_problem.values() if problem is not None)
    if not drafts:
        results.append(make_result("V1.2", "pre_render", attempt, "no_bound_claims"))
    return BindingCheck(results=tuple(results), bind=bound, drafts=drafts, polarity_dropped=polarity_dropped)
