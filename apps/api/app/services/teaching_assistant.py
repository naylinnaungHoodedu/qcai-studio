"""The teaching assistant's candidate answer: retrieval, then D-19 containment (AC-1-14).

TeachingAssistantService.chat answers with verbatim approved spans or an abstention (contained_answers.contain_answer;
provider "none", grounded false), and the orchestrator re-contains and guards it before a learner sees it. It calls
no model provider: model egress belongs only to the gateway (app.gateway; plan Phase 5 E1), and the dead provider path
this class once held is retired with its settings (Phase 5 spec 4.18). pipeline is the two-pass pipeline over the
same retrieval engine, which runs in shadow only.
"""

from __future__ import annotations

import logging
from functools import cached_property

from app.core.config import Settings
from app.core.corpus_governance import get_corpus_registry
from app.schemas import AssistantChatMessage, AssistantChatResponse
from app.services.contained_answers import EXTRACTIVE_MODE, contain_answer
from app.services.retrieval_engine import RetrievalEngine
from app.services.provenance import native_citation
from app.services.text_utils import sanitize_user_text

LOGGER = logging.getLogger(__name__)


class TeachingAssistantService:
    def __init__(self, retrieval_engine: RetrievalEngine, settings: Settings):
        self.retrieval_engine = retrieval_engine
        self.settings = settings

    def chat(
        self,
        message: str,
        *,
        lesson_slug: str | None = None,
        page_path: str | None = None,
        history: list[AssistantChatMessage] | None = None,
        top_k: int = 4,
    ) -> AssistantChatResponse:
        # page_path and history are accepted for interface stability; contained answers do not use them.
        clean_message = sanitize_user_text(message)

        store = self.retrieval_engine.store
        retrieval = self.retrieval_engine.search(clean_message, lesson_slug=lesson_slug, top_k=top_k, surface="assistant")
        # Phase 2: every citation names a span record (AC-2-3); corpus_version is a field, not an id input.
        citations = [native_citation(hit, corpus_version=store.corpus_version, settings=self.settings) for hit in retrieval.results]

        # Decision D-19: no provider is called and nothing generated is delivered until the verified
        # tutor exists; the learner gets verbatim approved spans or an abstention (AC-1-14).
        contained = contain_answer(citations, get_corpus_registry(self.settings), store.span_registry, settings=self.settings)
        response = AssistantChatResponse(
            answer=contained.answer,
            citations=contained.citations,
            retrieval_mode=f"{retrieval.mode}-{EXTRACTIVE_MODE}",
            provider="none",
            model=EXTRACTIVE_MODE,
            grounded=contained.grounded,
            decision=contained.decision,
            decision_reason=contained.reason,
            claims=contained.claims,
        )
        # Not serialised: the retrieval set behind the quotations, for the turn's ledger record (Phase 3 spec M20).
        response._retrieval = retrieval
        return response

    @cached_property
    def pipeline(self):
        """The two-pass pipeline over this assistant's retrieval engine (plan Phase 3 E: "teaching_assistant (two
        passes)"). It runs in shadow only until the Phase 4 exit; rebuild_course_store() drops it with the store."""
        from app.services.tutor_pipeline.pipeline import TwoPassPipeline

        return TwoPassPipeline(self.retrieval_engine, self.settings)
