from app.core.config import Settings
from app.core.corpus_governance import get_corpus_registry
from app.schemas import QAResponse
from app.services.contained_answers import EXTRACTIVE_MODE, contain_answer
from app.services.provenance import native_citation
from app.services.retrieval_engine import RetrievalEngine
from app.services.retrieval_metrics import record_citations


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
        contained = contain_answer(citations, get_corpus_registry(self.settings), store.span_registry, settings=self.settings)
        record_citations("qa", len(contained.citations), contained.dropped_unresolved, 0)
        return QAResponse(
            answer=contained.answer,
            citations=contained.citations,
            retrieval_mode=f"{retrieval.mode}-{EXTRACTIVE_MODE}",
            decision=contained.decision,
            grounded=contained.grounded,
        )
