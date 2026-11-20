"""The evidential pass: envelope, generator interface and the D-19 extractive generator (plan task 3.3; spec 4.5).

The generator sees only a typed EvidentialEnvelope: the resolved question, the corpus version and, for each quotable
span of the bundle, the span's whole-sentence text, with the rule in typed instruction fields (F-2, R-11). It returns
a ClaimPlan, which is re-validated with extra="forbid"; a malformed plan abstains (claim_plan_invalid).

The whole-sentence text (bind.whole_sentence_text) is the span's own characters from the start of its first whole
document sentence to the end of its last: a span is a splitter chunk that can start or end inside a sentence, and
that leading or trailing fragment never reaches a generator, so a generator that quotes the envelope never proposes
a fragment that drops a sentence's opening words or its end (spec 18.10 H1). A span that holds no whole sentence is
left out; binding still checks every claim against the section text itself.

When no span is left, the pipeline abstains, and no_envelope_reason says why (spec 18.11 I1): no_quotable_evidence
when the bundle holds no quotable span (nothing approved under D-31), and no_whole_sentence when it holds quotable
spans of which none holds a whole document sentence. A bundle the license gate emptied never gets here: it abstains
at retrieval with no_quotable_evidence too (retrieve.retrieve; spec 4.3). The two causes have
different remedies (an approval, or a sentence rule that fits the corpus), so plan I's "abstention by reason" keeps
them apart.

D-12 (the provider) is open, so no provider generator exists (hold H6, PD-09): ClaimGenerator is the interface a
Phase 5 gateway generator implements, and get_generator refuses any id outside WIRED_GENERATORS. The only wired
generator is extractive-d19-v1 (D-19 RECOMMENDATION, PD-08): each claim is one verbatim whole sentence of a quotable
span that shares at least tutor_pipeline.evidential.min_question_overlap_terms content terms (1; PD-11, spec 18.8 F5)
with the question. Under D-31 no span is quotable, so the governed build abstains.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from app.core.config_package import WIRED_GENERATORS, ConfigPackage, TutorPipelineParams, canonical_sha256
from app.services.tutor_pipeline.bind import whole_sentence_text
from app.services.tutor_pipeline.contracts import (
    NO_QUOTABLE_EVIDENCE,
    NO_WHOLE_SENTENCE,
    ClaimPlan,
    EnvelopeSpan,
    EvidenceBundle,
    EvidentialEnvelope,
    EvidentialInstructions,
    GeneratorRef,
    ProposedClaim,
    RetrievalRequest,
)
from app.services.tutor_pipeline.text import SENTENCE_RULE, content_terms, sentences, whitespace

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config_package import RetrievalParams
    from app.services.content_assembler import CourseStore

EXTRACTIVE_ID = "extractive-d19-v1"
# "whole sentence": each envelope text holds only the span's whole document sentences (bind.whole_sentence_text).
EXTRACTIVE_RULE = (
    "D-19 extractive mode: each claim is one verbatim whole sentence (sentences-v2) of an approved, public-plane "
    "document span in the envelope, whose text holds only the span's whole document sentences, that shares at least "
    "{min_question_overlap_terms} content terms with the question; at most {max_claims_per_span} per span and "
    "{max_claims} in all, in evidence order."
)


class GeneratorUnavailable(RuntimeError):
    """The package names a generator that is not wired (D-12 open)."""


def evidential_prompt_hash(params: TutorPipelineParams) -> str:
    return canonical_sha256(
        {
            "id": EXTRACTIVE_ID,
            "rule": EXTRACTIVE_RULE,
            "sentence_rule": SENTENCE_RULE,
            "max_claims": params.max_claims,
            "max_claims_per_span": params.max_claims_per_span,
            "min_sentence_words": params.min_sentence_words,
            "max_sentence_chars": params.max_sentence_chars,
            "min_question_overlap_terms": params.min_question_overlap_terms,
        }
    )


def build_envelope(request: RetrievalRequest, bundle: EvidenceBundle, *, store: "CourseStore", params: TutorPipelineParams) -> EvidentialEnvelope | None:
    """The quotable bundle spans with their whole-sentence text, in bundle order; None when there is none (D-19, D-31).
    A span holding no whole document sentence is left out (spec 18.10 H1)."""
    evidence = []
    for span in bundle.spans:
        if not span.quotable:
            continue
        record = store.span_registry.get(span.span_id)
        if record is None:
            continue
        text = whole_sentence_text(record, store)
        if text is None or not text.strip():
            continue
        evidence.append(EnvelopeSpan(span_id=span.span_id, text=text))
    if not evidence:
        return None  # no_envelope_reason(bundle, store=store) says why
    return EvidentialEnvelope(
        question=request.text,
        corpus_version=request.corpus_version,
        evidence=tuple(evidence),
        instructions=EvidentialInstructions(
            rule_id=EXTRACTIVE_ID,
            prompt_hash=params.evidential_prompt_hash,
            max_claims=params.max_claims,
            max_claims_per_span=params.max_claims_per_span,
            min_sentence_words=params.min_sentence_words,
        ),
    )


def no_envelope_reason(bundle: EvidenceBundle, *, store: "CourseStore") -> str:
    """Why build_envelope found nothing to send (spec 18.11 I1): no_quotable_evidence when the bundle holds no quotable,
    registered span; no_whole_sentence when it holds some, none of which holds a whole document sentence."""
    quotable = any(span.quotable and store.span_registry.get(span.span_id) is not None for span in bundle.spans)
    return NO_WHOLE_SENTENCE if quotable else NO_QUOTABLE_EVIDENCE


class ClaimGenerator(Protocol):
    """The generator interface (E2): a Phase 5 provider generator implements it behind the gateway."""

    ref: GeneratorRef

    def propose(self, envelope: EvidentialEnvelope) -> ClaimPlan: ...


class ExtractiveD19Generator:
    """D-19 extractive mode: verbatim whole sentences of quotable spans, each bound to its own span. The envelope text
    holds only whole document sentences (build_envelope), so each sentences-v2 piece of it is one."""

    def __init__(self, package: ConfigPackage) -> None:
        if package.tutor_pipeline is None:
            raise GeneratorUnavailable("the configuration package has no tutor_pipeline block")
        self.params = package.tutor_pipeline
        self.retrieval: "RetrievalParams" = package.retrieval
        self.ref = GeneratorRef(generator_id=EXTRACTIVE_ID, model_id=EXTRACTIVE_ID, kind="extractive",
                                prompt_hash=self.params.evidential_prompt_hash)

    def propose(self, envelope: EvidentialEnvelope) -> ClaimPlan:
        question_terms = content_terms(envelope.question, self.retrieval)
        claims: list[ProposedClaim] = []
        for span in envelope.evidence:
            if len(claims) >= self.params.max_claims:
                break
            candidates = sentences(span.text, min_words=self.params.min_sentence_words, max_chars=self.params.max_sentence_chars)
            overlap = self.params.min_question_overlap_terms
            matching = [sentence for sentence in candidates if len(content_terms(sentence, self.retrieval) & question_terms) >= overlap]
            for sentence in matching[: self.params.max_claims_per_span]:
                if len(claims) >= self.params.max_claims:
                    break
                claims.append(ProposedClaim(text=whitespace(sentence), span_ids=(span.span_id,)))
        return ClaimPlan(generator=self.ref, claims=tuple(claims))


GENERATORS: dict[str, Callable[[ConfigPackage], ClaimGenerator]] = {EXTRACTIVE_ID: ExtractiveD19Generator}


def get_generator(package: ConfigPackage) -> ClaimGenerator:
    if package.tutor_pipeline is None:
        raise GeneratorUnavailable("the configuration package has no tutor_pipeline block")
    generator_id = package.tutor_pipeline.generator_default
    if generator_id not in package.tutor_pipeline.generators_allowed or generator_id not in WIRED_GENERATORS or generator_id not in GENERATORS:
        raise GeneratorUnavailable(f"generator {generator_id!r} is not wired (D-12 open, hold H6)")
    return GENERATORS[generator_id](package)
