"""Retrieval request and evidence bundle (plan tasks 3.1-3.2; plan 7.4; Phase 3 spec 4.3).

The retrieval request is exactly the resolved text, the lesson scope and the corpus version (R-41); depth comes
from the configuration package, never the client. Retrieval is lexical only (RetrievalEngine.evidence), whatever
SEMANTIC_RETRIEVAL_ENABLED says, so the shadow never sends learner text to a provider (spec conflict 33). The
sufficiency decision is the active Phase 2 gate's: abstain exactly when the gate returns nothing; near_miss when
the gate marks the top result near_floor (within the margin above the floor), which proceeds and is recorded. Its
score is the top result's gate score (RetrievalResponse.gate_scores): the score the gate compared with the floor, at
the gate's precision (bm25f-v1's 9-digit score; p1-floor's P1 floor score), so score, floor and margin are on one
scale and V1.5 applies its X4 margin to them (Phase 4 spec 4.6, M11). A span's own score stays its display score.

license_class is derived for every span from its record's plane and the manifest (CorpusRegistry.license_class),
never written as a label: a span that is not public-plane is never emitted (plan H "public-corpus spans only";
plan 7.5 "the license_class gate is defense in depth"). It is dropped from the bundle, counted and logged, so the
gate holds even if an upstream guard (the span builder, the index) ever let such a span through.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.corpus_governance import CorpusRegistry
from app.core.structured_logging import FIELDS
from app.services.contained_answers import span_is_quotable
from app.services.tutor_pipeline.contracts import NO_QUOTABLE_EVIDENCE, EvidenceBundle, EvidenceSpan, ResolvedQuestion, RetrievalRequest, Sufficiency
from app.services.tutor_pipeline.metrics import LICENSE_METRICS

if TYPE_CHECKING:  # pragma: no cover
    from app.services.retrieval_engine import RetrievalEngine
    from app.services.spans import SpanRecord

LOGGER = logging.getLogger("qcai.tutor")
# The near-miss rule this module applies; configuration package v2 names it (tutor_pipeline.retrieval.near_miss_rule)
# and package_check requires the two to agree, so the rule cannot change under its old id (spec 18.8 F4).
NEAR_MISS_RULE = "gate-near-floor-flag-of-top-result-v1"


def sufficiency_of(response, *, threshold_version: str) -> Sufficiency:
    """The sufficiency decision of a Phase 2 retrieval response (a RetrievalResponse), by NEAR_MISS_RULE: abstain
    exactly when the gate returned nothing, with the gate's reason; near_miss when the top result is near_floor;
    answer otherwise. The score is the top result's gate score (None when the response carries none). The legacy
    ledger record uses it for the retrieval behind a contained answer (spec 18.8 F1)."""
    if response.results:
        top = response.results[0]
        return Sufficiency(score=gate_score_of(response, top), gate=response.gate, threshold_version=threshold_version,
                           floor=response.floor, margin=response.margin, decision="near_miss" if top.near_floor else "answer",
                           reason="evidence")
    return Sufficiency(score=None, gate=response.gate, threshold_version=threshold_version, floor=response.floor,
                       margin=response.margin, decision="abstain", reason=response.reason)


def gate_score_of(response, result) -> float | None:
    """The gate score of one result of a RetrievalResponse: the score the active gate compared with its floor."""
    scores = getattr(response, "gate_scores", None) or {}
    return scores.get(result.span_id or result.chunk_id)


def evidence_span_for(record: "SpanRecord", registry: CorpusRegistry, *, score: float | None, near_floor: bool, surface: str) -> EvidenceSpan | None:
    """The EvidenceSpan of a span record, or None when its derived license class is not public (fail closed). Used by
    the two-pass bundle and by the legacy ledger record, so neither ever labels a span public that is not."""
    license_class = registry.license_class(plane=getattr(record, "plane", None), item_id=record.item_id, source_filename=record.source_filename)
    if license_class is None:
        LICENSE_METRICS.excluded(surface)
        LOGGER.warning(
            "A span that is not public-plane was excluded from the evidence",
            extra={FIELDS: {"event": "tutor.evidence.non_public_excluded", "surface": surface}},
        )
        return None
    return EvidenceSpan(
        span_id=record.span_id,
        item_id=record.item_id,
        item_version=record.item_version,
        kind=record.item_kind,
        char_start=record.start,
        char_end=record.end,
        content_hash=record.content_hash,
        score=score,
        near_floor=near_floor,
        license_class=license_class,
        quotable=span_is_quotable(record, registry),
    )


def build_request(resolved: ResolvedQuestion, *, lesson_slug: str | None, corpus_version: str) -> RetrievalRequest:
    return RetrievalRequest(text=resolved.text, lesson_slug=lesson_slug, corpus_version=corpus_version)


def retrieve(engine: "RetrievalEngine", request: RetrievalRequest, *, top_k: int, registry: CorpusRegistry) -> EvidenceBundle:
    store = engine.store
    floor, margin, threshold_version = store.index.thresholds
    gate = store.gate
    if request.corpus_version != store.corpus_version:
        return EvidenceBundle(
            corpus_version=store.corpus_version,
            index_version=store.index_version,
            retrieval_mode="lexical",
            spans=(),
            sufficiency=Sufficiency(score=None, gate=gate, threshold_version=threshold_version, floor=floor, margin=margin,
                                    decision="abstain", reason="corpus_version_mismatch"),
        )
    response = engine.evidence(request.text, lesson_slug=request.lesson_slug, top_k=top_k)
    spans = []
    for result in response.results:
        record = store.span_registry.get(result.span_id)
        if record is None:  # pragma: no cover - every index entry is a span record
            continue
        span = evidence_span_for(record, registry, score=result.score, near_floor=bool(result.near_floor), surface="two_pass")
        if span is not None:
            spans.append(span)
    if not spans:
        # Every result excluded by the license gate: nothing quotable is left, so the bundle abstains.
        reason = NO_QUOTABLE_EVIDENCE if response.results else response.reason
        sufficiency = Sufficiency(score=None, gate=response.gate, threshold_version=threshold_version, floor=response.floor,
                                  margin=response.margin, decision="abstain", reason=reason)
    else:
        top = next(result for result in response.results if result.span_id == spans[0].span_id)
        sufficiency = Sufficiency(score=gate_score_of(response, top), gate=response.gate, threshold_version=threshold_version,
                                  floor=response.floor, margin=response.margin, decision="near_miss" if top.near_floor else "answer",
                                  reason="evidence")
    return EvidenceBundle(
        corpus_version=store.corpus_version,
        index_version=store.index_version,
        retrieval_mode="lexical",
        spans=tuple(spans),
        sufficiency=sufficiency,
    )
