"""The /qa/ask engine: lexical or hybrid retrieval, then D-19 containment (AC-1-14).

Phase 3 (plan task 3.8, F-1 "100% carry span IDs, model ID, prompt hash and verdicts" of delivered responses): each
answer also prepares its legacy ledger record, exactly as a tutor turn does (TUTOR_LEDGER_ENABLED; spec 7.12). The
record has a qa- response id that is stored nowhere else, so it holds no learner link, no question and no identity;
the route appends it after the commit, bounded and fail-open. The learner's response is unchanged.
"""

from uuid import uuid4

from app.core.config import Settings
from app.core.corpus_governance import get_corpus_registry
from app.schemas import QAResponse
from app.services.contained_answers import EXTRACTIVE_MODE, contain_answer
from app.services.ledger import legacy_delivery_for, record_ledger_failure
from app.services.provenance import native_citation
from app.services.retrieval_engine import RetrievalEngine
from app.services.retrieval_metrics import record_citations
from app.services.tutor_pipeline.metrics import LEDGER_METRICS

QA_PROVIDER = "none"


class QAEngine:
    def __init__(self, retrieval_engine: RetrievalEngine, settings: Settings):
        self.retrieval_engine = retrieval_engine
        self.settings = settings

    def ask(self, question: str, lesson_slug: str | None = None, top_k: int = 4) -> QAResponse:
        store = self.retrieval_engine.store
        retrieval = self.retrieval_engine.search(question, lesson_slug=lesson_slug, top_k=top_k, surface="qa")
        # Phase 2: every citation names a span record (AC-2-3); corpus_version is a field, not an id input.
        citations = [native_citation(hit, corpus_version=store.corpus_version, settings=self.settings) for hit in retrieval.results]

        # Decision D-19: no generation; verbatim approved spans or an abstention (AC-1-14).
        registry = get_corpus_registry(self.settings)
        contained = contain_answer(citations, registry, store.span_registry, settings=self.settings)
        record_citations("qa", len(contained.citations), contained.dropped_unresolved, 0)
        retrieval_mode = f"{retrieval.mode}-{EXTRACTIVE_MODE}"
        response = QAResponse(
            answer=contained.answer,
            citations=contained.citations,
            retrieval_mode=retrieval_mode,
            decision=contained.decision,
            grounded=contained.grounded,
        )
        if self.settings.tutor_ledger_enabled:
            LEDGER_METRICS.attempt("legacy", surface="qa")
            try:
                response._ledger = legacy_delivery_for(
                    response_id=f"qa-{uuid4()}",
                    contained=contained,
                    retrieval=retrieval if isinstance(getattr(retrieval, "results", None), list) else None,
                    store=store,
                    registry=registry,
                    retrieval_mode=retrieval_mode,
                    provider=QA_PROVIDER,
                    model=EXTRACTIVE_MODE,
                    policy_version=self.settings.grounding_policy_version,
                    surface="qa",
                )
            except Exception as exc:  # noqa: BLE001 - a lost record is counted (plan L stop); the answer is unchanged
                record_ledger_failure("legacy", "prepare", exc, surface="qa")
        return response
