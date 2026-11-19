"""The evidential pass: envelope, generator interface and the D-19 extractive generator (plan task 3.3; spec 4.5).

The generator sees only a typed EvidentialEnvelope: the resolved question, the corpus version and the text of the
quotable spans of the bundle, with the rule in typed instruction fields (F-2, R-11). It returns a ClaimPlan, which
is re-validated with extra="forbid"; a malformed plan abstains (claim_plan_invalid).

D-12 (the provider) is open, so no provider generator exists (hold H6, PD-09): ClaimGenerator is the interface a
Phase 5 gateway generator implements, and get_generator refuses any id outside WIRED_GENERATORS. The only wired
generator is extractive-d19-v1 (D-19 RECOMMENDATION, PD-08): each claim is one verbatim sentence of a quotable span
that shares a content term with the question. Under D-31 no span is quotable, so the governed build abstains.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from app.core.config_package import WIRED_GENERATORS, ConfigPackage, TutorPipelineParams, canonical_sha256
from app.services.tutor_pipeline.contracts import (
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
EXTRACTIVE_RULE = (
    "D-19 extractive mode: each claim is one verbatim sentence (sentences-v2) of an approved, public-plane document "
    "span in the envelope that shares at least one content term with the question; at most {max_claims_per_span} "
    "per span and {max_claims} in all, in evidence order."
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
        }
    )


def build_envelope(request: RetrievalRequest, bundle: EvidenceBundle, *, store: "CourseStore", params: TutorPipelineParams) -> EvidentialEnvelope | None:
    """The quotable bundle spans with their registry text, in bundle order; None when there is none (D-19, D-31)."""
    evidence = []
    for span in bundle.spans:
        if not span.quotable:
            continue
        record = store.span_registry.get(span.span_id)
        if record is None or not record.text.strip():
            continue
        evidence.append(EnvelopeSpan(span_id=span.span_id, text=record.text))
    if not evidence:
        return None
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


class ClaimGenerator(Protocol):
    """The generator interface (E2): a Phase 5 provider generator implements it behind the gateway."""

    ref: GeneratorRef

    def propose(self, envelope: EvidentialEnvelope) -> ClaimPlan: ...


class ExtractiveD19Generator:
    """D-19 extractive mode: verbatim whole sentences of quotable spans, each bound to its own span."""

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
            matching = [sentence for sentence in candidates if content_terms(sentence, self.retrieval) & question_terms]
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
