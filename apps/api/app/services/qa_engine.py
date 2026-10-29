from app.core.config import Settings
from app.core.corpus_governance import get_corpus_registry
from app.schemas import Citation, QAResponse
from app.services.contained_answers import EXTRACTIVE_MODE, contain_answer
from app.services.retrieval_engine import RetrievalEngine
from app.services.provenance import evidence_provenance
from app.services.text_utils import truncate_display_excerpt


class QAEngine:
    def __init__(self, retrieval_engine: RetrievalEngine, settings: Settings):
        self.retrieval_engine = retrieval_engine
        self.settings = settings

    def ask(self, question: str, lesson_slug: str | None = None, top_k: int = 4) -> QAResponse:
        retrieval = self.retrieval_engine.search(question, lesson_slug=lesson_slug, top_k=top_k)
        citations = []
        for hit in retrieval.results:
            span_id, content_hash, corpus_version = evidence_provenance(
                settings=self.settings,
                chunk_id=hit.chunk_id,
                source_title=hit.source_title,
                source_kind=hit.source_kind,
                excerpt=hit.excerpt,
                timestamp_label=hit.timestamp_label,
            )
            citations.append(
                Citation(
                    chunk_id=hit.chunk_id,
                    span_id=span_id,
                    corpus_version=corpus_version,
                    content_hash=content_hash,
                    source_title=hit.source_title,
                    source_kind=hit.source_kind,
                    section_title=hit.title,
                    excerpt=truncate_display_excerpt(hit.excerpt, 320),
                    timestamp_label=hit.timestamp_label,
                    source_filename=hit.source_filename,
                )
            )

        # Decision D-19: no generation; verbatim approved spans or an abstention (AC-1-14).
        contained = contain_answer(citations, get_corpus_registry(self.settings))
        return QAResponse(
            answer=contained.answer,
            citations=contained.citations,
            retrieval_mode=f"{retrieval.mode}-{EXTRACTIVE_MODE}",
            decision=contained.decision,
            grounded=contained.grounded,
        )
