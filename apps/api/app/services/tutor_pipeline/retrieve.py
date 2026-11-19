"""Retrieval request and evidence bundle (plan tasks 3.1-3.2; plan 7.4; Phase 3 spec 4.3).

The retrieval request is exactly the resolved text, the lesson scope and the corpus version (R-41); depth comes
from the configuration package, never the client. Retrieval is lexical only (RetrievalEngine.evidence), whatever
SEMANTIC_RETRIEVAL_ENABLED says, so the shadow never sends learner text to a provider (spec conflict 33). The
sufficiency decision is the active Phase 2 gate's: abstain exactly when the gate returns nothing; near_miss when
the gate marks the top result near_floor (within the margin above the floor), which proceeds and is recorded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.corpus_governance import CorpusRegistry
from app.services.contained_answers import span_is_quotable
from app.services.tutor_pipeline.contracts import EvidenceBundle, EvidenceSpan, ResolvedQuestion, RetrievalRequest, Sufficiency

if TYPE_CHECKING:  # pragma: no cover
    from app.services.retrieval_engine import RetrievalEngine


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
        spans.append(
            EvidenceSpan(
                span_id=record.span_id,
                item_id=record.item_id,
                item_version=record.item_version,
                kind=record.item_kind,
                char_start=record.start,
                char_end=record.end,
                content_hash=record.content_hash,
                score=result.score,
                near_floor=bool(result.near_floor),
                license_class="public",
                quotable=span_is_quotable(record, registry),
            )
        )
    if not spans:
        sufficiency = Sufficiency(score=None, gate=response.gate, threshold_version=threshold_version, floor=response.floor,
                                  margin=response.margin, decision="abstain", reason=response.reason)
    else:
        top = response.results[0]
        sufficiency = Sufficiency(score=top.score, gate=response.gate, threshold_version=threshold_version, floor=response.floor,
                                  margin=response.margin, decision="near_miss" if top.near_floor else "answer", reason="evidence")
    return EvidenceBundle(
        corpus_version=store.corpus_version,
        index_version=store.index_version,
        retrieval_mode="lexical",
        spans=tuple(spans),
        sufficiency=sufficiency,
    )
