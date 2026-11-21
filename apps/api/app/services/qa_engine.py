"""The /qa/ask engine: lexical or hybrid retrieval, then D-19 containment (AC-1-14).

Phase 3 (plan task 3.8): with EVIDENCE_PANEL_ENABLED (development by default) the answer carries the evidence panel,
as a tutor answer does (E-46 names the Q&A citation cards; spec 18.8 F3); outside development the body is unchanged.
Plan task 3.8, F-1 ("100% carry span IDs, model ID, prompt hash and verdicts" of delivered responses): each
answer also prepares its legacy ledger record, exactly as a tutor turn does (TUTOR_LEDGER_ENABLED; spec 7.12). The
record has a random qa- response id that is stored nowhere else, and it holds no question, user id or account id;
the route appends it after the commit, bounded and fail-open. The learner's response is unchanged. The record can
still be matched to the asker's qa_interactions row while that row exists (the same answer, whose sha256 is the
record's rendered_text_sha256, the same cited spans, a close time), so it is pseudonymous, not unlinkable, until
erasure or guest retention deletes the row (spec 18.6 D10).

Phase 4 (spec 7.5; plan Phase 4 L): the contained answer passes the legacy guard (V1.1 and V1.2; no flag) before the
answer, its Q&A row and its ledger record read it. Conflicting quotations (V1.7) are labelled by the evidence panel
when it is shown, and otherwise withheld by the guard (AC-4-6); GET /qa/history shows a stored answer again with the
same labels, from its stored citations, whether or not the panel is on.
"""

from uuid import uuid4

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.core.corpus_governance import get_corpus_registry
from app.schemas import QAResponse
from app.services.contained_answers import EXTRACTIVE_MODE, contain_answer
from app.services.evidence_panel import build_evidence_panel, panel_conflicts
from app.services.ledger import legacy_delivery_for, preparation_failed
from app.services.provenance import native_citation
from app.services.retrieval_engine import RetrievalEngine
from app.services.retrieval_metrics import record_citations
from app.services.v1_checks.legacy_guard import guard_contained

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
        # Plan Phase 4 L: V1.1 and V1.2 stay enforced on every delivery path (no flag). AC-4-6: conflicting quotations
        # are labelled by the evidence panel when it is shown and the package's conflict policy is disclose, else
        # withheld (V1.7); the Q&A history and the ledger record's read label them too.
        package = get_config_package(self.settings)
        contained = guard_contained(contained, store=store, package=package, surface="qa",
                                    disclosure_shown=self.settings.evidence_panel_enabled).contained
        record_citations("qa", len(contained.citations), contained.dropped_unresolved, 0)
        retrieval_mode = f"{retrieval.mode}-{EXTRACTIVE_MODE}"
        response = QAResponse(
            answer=contained.answer,
            citations=contained.citations,
            retrieval_mode=retrieval_mode,
            decision=contained.decision,
            grounded=contained.grounded,
        )
        if self.settings.evidence_panel_enabled:
            # Task 3.8 on the Q&A panel too (E-46 names its citation cards; spec 18.8 F3): labels for what is delivered.
            response.evidence = build_evidence_panel(
                decision=contained.decision, citations=contained.citations, retrieval_mode=retrieval_mode, settings=self.settings,
                conflicts=panel_conflicts(contained, package),
            )
        if self.settings.tutor_ledger_enabled:
            # Counted as attempted by the route once the answer has committed (spec 18.7 E5), never here.
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
            except Exception as exc:  # noqa: BLE001 - a lost record is counted after the commit (plan L stop); the answer is unchanged
                response._ledger = preparation_failed(exc, contained=contained, retrieval=retrieval, surface="qa")
        return response
