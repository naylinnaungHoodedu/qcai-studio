"""Persistent Tutor orchestration with explicit evidence and pedagogical channels.

Phase 3 (docs/architecture/phase3-implementation-spec.md 7.11): the learner still receives only the legacy
contained answer (D-19, unchanged). Each turn also prepares its follow-ups, which the route runs after the commit:
a legacy ledger record (TUTOR_LEDGER_ENABLED) and, when two_pass_tutor is in shadow, a two-pass shadow run whose
output reaches no learner (AC-3-6). The evidence panel (task 3.8) is added only when EVIDENCE_PANEL_ENABLED.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config_package import get_config_package
from app.core.corpus_governance import CorpusRegistry, get_corpus_registry
from app.core.config import Settings
from app.core.auth import AuthUser
from app.core.structured_logging import FIELDS
from app.db_models import TutorMessage, TutorThread, TutorTurn
from app.schemas import (
    AssistantChatMessage,
    AssistantChatRequest,
    AssistantChatResponse,
    TutorMessageRead,
    TutorThreadDetail,
    TutorThreadRead,
)
from app.services.answer_history import WITHDRAWN_ANSWER, stored_before_containment
from app.services.contained_answers import ContainedAnswer, contain_answer, span_is_quotable
from app.services.evidence_panel import build_evidence_panel
from app.services.ledger import LegacyDelivery, record_ledger_failure
from app.services.retrieval_metrics import record_citations
from app.services.span_store import persist_cited_spans
from app.services.teaching_assistant import TeachingAssistantService
from app.services.tutor_followups import TurnFollowups
from app.services.tutor_pipeline.contracts import EvidenceSpan, PresentationPlan, sha256_hex
from app.services.tutor_pipeline.metrics import LEDGER_METRICS, TWO_PASS_METRICS
from app.services.tutor_pipeline.shadow import ShadowJob, effective_mode
from app.services.tutor_pipeline.shadow import run_shadow as run_shadow_job

TUTOR_LOGGER = logging.getLogger("qcai.tutor")


def _thread_title(message: str) -> str:
    compact = " ".join(message.split())
    return (compact[:120] + "...") if len(compact) > 123 else compact


def _withdrawn(message: TutorMessage) -> bool:
    return message.role == "assistant" and stored_before_containment(message.created_at)


def _message_read(message: TutorMessage) -> TutorMessageRead:
    # A reply the uncontained build stored is withheld; the learner's own messages stay (R-16).
    withdrawn = _withdrawn(message)
    return TutorMessageRead(
        id=message.id,
        role=message.role,
        content=WITHDRAWN_ANSWER if withdrawn else message.content,
        created_at=message.created_at,
        withdrawn=withdrawn,
    )


class TutorOrchestrator:
    def __init__(self, assistant: TeachingAssistantService, settings: Settings):
        self.assistant = assistant
        self.settings = settings

    def list_threads(self, db: Session, user: AuthUser) -> list[TutorThreadRead]:
        records = db.scalars(
            select(TutorThread)
            .where(TutorThread.user_id == user.user_id)
            .order_by(TutorThread.updated_at.desc(), TutorThread.id.desc())
            .limit(50)
        ).all()
        return [self._thread_read(record) for record in records]

    def create_thread(self, db: Session, user: AuthUser, title: str | None = None) -> TutorThreadRead:
        thread = TutorThread(id=f"thread-{uuid4()}", user_id=user.user_id, title=(title or "New Tutor thread").strip()[:255])
        db.add(thread)
        db.flush()
        return self._thread_read(thread)

    def read_thread(self, db: Session, user: AuthUser, thread_id: str) -> TutorThreadDetail:
        thread = self._require_thread(db, user, thread_id)
        messages = db.scalars(
            select(TutorMessage)
            .where(TutorMessage.thread_id == thread.id)
            .order_by(TutorMessage.created_at.asc(), TutorMessage.id.asc())
            .limit(100)
        ).all()
        return TutorThreadDetail(
            **self._thread_read(thread).model_dump(),
            messages=[_message_read(message) for message in messages],
        )

    def chat(
        self, db: Session, user: AuthUser, payload: AssistantChatRequest, *, presentation_plan: str | None = None
    ) -> AssistantChatResponse:
        thread = self._require_thread(db, user, payload.thread_id) if payload.thread_id else None
        if thread is None:
            thread = TutorThread(id=f"thread-{uuid4()}", user_id=user.user_id, title=_thread_title(payload.message))
            db.add(thread)
            db.flush()

        resolved_query, history = self._resolve_query(db, thread, payload.message, payload.history)
        # Learner state stays out of the assistant until the two-pass tutor exists (AC-1-14, R-41).
        candidate = self.assistant.chat(
            resolved_query,
            lesson_slug=payload.lesson_slug,
            page_path=payload.page_path,
            history=history,
            top_k=payload.top_k,
        )

        # Decision D-19, enforced here whatever the assistant returned: only verbatim approved spans or
        # an abstention reach the learner, never candidate.answer itself.
        registry = get_corpus_registry(self.settings)
        contained = contain_answer(candidate.citations, registry, self._span_registry(), settings=self.settings)
        record_citations("tutor", len(contained.citations), contained.dropped_unresolved, 0)
        turn_id = f"turn-{uuid4()}"
        user_message_id = f"message-{uuid4()}"
        # Times are set here, not by the database, so the learner's turns of a thread have a strict order even
        # within one second on SQLite (Phase 3 spec M5); the reply follows the question by one microsecond.
        now = datetime.now(timezone.utc)
        db.add(TutorMessage(id=user_message_id, thread_id=thread.id, role="user", content=payload.message, created_at=now))
        db.add(
            TutorMessage(
                id=f"message-{uuid4()}",
                thread_id=thread.id,
                role="assistant",
                content=contained.answer,
                created_at=now + timedelta(microseconds=1),
            )
        )
        db.add(
            TutorTurn(
                id=turn_id,
                thread_id=thread.id,
                user_id=user.user_id,
                resolved_query=resolved_query,
                retrieval_mode=candidate.retrieval_mode,
                provider=candidate.provider,
                model=candidate.model,
                decision=contained.decision,
                decision_reason=contained.reason,
                citations=[citation.model_dump() for citation in contained.citations],
                claims=[claim.model_dump() for claim in contained.claims],
                corpus_version=registry.corpus_version,
                policy_version=self.settings.grounding_policy_version,
                created_at=now,
            )
        )
        thread.updated_at = now
        # Text-free identity of the spans this turn cited, so its citations keep resolving (task 2.2).
        persist_cited_spans(db, contained.citations, self._store())
        db.flush()
        response = AssistantChatResponse(
            answer=contained.answer,
            citations=contained.citations,
            retrieval_mode=candidate.retrieval_mode,
            provider=candidate.provider,
            model=candidate.model,
            grounded=contained.grounded,
            thread_id=thread.id,
            turn_id=turn_id,
            decision=contained.decision,
            decision_reason=contained.reason,
            claims=contained.claims,
        )
        if self.settings.evidence_panel_enabled:
            response.evidence = build_evidence_panel(
                decision=contained.decision, citations=contained.citations, retrieval_mode=candidate.retrieval_mode, settings=self.settings
            )
        response._followups = TurnFollowups(
            legacy=self._legacy_followup(turn_id, candidate, contained, registry),
            shadow=self._shadow_followup(turn_id, thread.id, user_message_id, payload.lesson_slug, presentation_plan),
        )
        return response

    # --- Phase 3 follow-ups: prepared here, run by the route after the commit (tutor_followups) ---

    def _legacy_followup(self, turn_id: str, candidate: AssistantChatResponse, contained: ContainedAnswer, registry: CorpusRegistry) -> LegacyDelivery | None:
        if not self.settings.tutor_ledger_enabled:
            return None
        LEDGER_METRICS.attempt("legacy")
        try:
            return self._legacy_delivery(turn_id, candidate, contained, registry)
        except Exception as exc:  # noqa: BLE001 - a lost record is counted (plan L stop), the answer is unchanged
            record_ledger_failure("legacy", "prepare", exc)
            return None

    def _legacy_delivery(self, turn_id: str, candidate: AssistantChatResponse, contained: ContainedAnswer, registry: CorpusRegistry) -> LegacyDelivery:
        store = self._store()
        floor, margin, threshold_version = store.index.thresholds
        quoted = tuple(
            EvidenceSpan(
                span_id=citation.span_id,
                item_id=citation.item_id,
                item_version=citation.item_version,
                kind="document",
                char_start=citation.start,
                char_end=citation.end,
                content_hash=citation.content_hash,
                score=None,
                near_floor=bool(citation.near_floor),
                license_class="public",
                quotable=True,
            )
            for citation in contained.citations
        )
        retrieval = getattr(candidate, "_retrieval", None)
        retrieved: tuple[EvidenceSpan, ...] | None = None
        if retrieval is not None and isinstance(getattr(retrieval, "results", None), list):
            spans = []
            for result in retrieval.results:
                record = store.span_registry.get(result.span_id or result.chunk_id)
                if record is None:
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
            retrieved = tuple(spans)
        return LegacyDelivery(
            response_id=turn_id,
            decision=contained.decision,
            reason=contained.reason,
            claims=tuple((claim.text, tuple(claim.cited_span_ids)) for claim in contained.claims),
            quoted=quoted,
            retrieved=retrieved,
            answer_sha256=sha256_hex(contained.answer),
            retrieval_mode=candidate.retrieval_mode,
            provider=candidate.provider,
            model=candidate.model,
            corpus_version=registry.corpus_version,
            index_version=store.index_version,
            gate=store.gate,
            threshold_version=threshold_version,
            floor=floor,
            margin=margin,
            policy_version=self.settings.grounding_policy_version,
            dropped_unresolved=contained.dropped_unresolved,
            manifest_sha256=registry.manifest_sha256,
        )

    def _shadow_followup(
        self, turn_id: str, thread_id: str, user_message_id: str, lesson_slug: str | None, presentation_plan: str | None
    ) -> ShadowJob | None:
        try:
            package = get_config_package(self.settings)
            if effective_mode(self.settings, package) != "shadow" or package.tutor_pipeline is None:
                return None
            plan_id = presentation_plan or package.tutor_pipeline.default_plan
            return ShadowJob(
                shadow_response_id=f"shadow-{uuid4()}",
                shadowed_response_id=turn_id,
                thread_id=thread_id,
                user_message_id=user_message_id,
                lesson_slug=lesson_slug,
                presentation=PresentationPlan(plan_id=plan_id, source="request" if presentation_plan else "default"),
            )
        except Exception as exc:  # noqa: BLE001 - the shadow never changes the learner's answer
            TWO_PASS_METRICS.failed("pipeline")
            TUTOR_LOGGER.error(
                "Two-pass shadow run failed", extra={FIELDS: {"event": "tutor.two_pass.shadow_failed", "step": "prepare", "error": type(exc).__name__}}
            )
            return None

    def run_shadow(self, job: ShadowJob) -> None:
        """The background task the route schedules after the response is sent. Never raises."""
        run_shadow_job(job, pipeline_factory=self._pipeline, settings=self.settings)

    def _pipeline(self):
        if isinstance(self.assistant, TeachingAssistantService):
            return self.assistant.pipeline
        from app.services.store import get_retrieval_engine
        from app.services.tutor_pipeline.pipeline import TwoPassPipeline

        return TwoPassPipeline(get_retrieval_engine(), self.settings)

    def _store(self):
        engine = getattr(self.assistant, "retrieval_engine", None)
        if engine is not None and getattr(engine, "store", None) is not None:
            return engine.store
        from app.services.store import get_course_store

        return get_course_store()

    def _span_registry(self):
        return self._store().span_registry

    def _resolve_query(
        self,
        db: Session,
        thread: TutorThread,
        message: str,
        supplied_history: list[AssistantChatMessage],
    ) -> tuple[str, list[AssistantChatMessage]]:
        stored = db.scalars(
            select(TutorMessage)
            .where(TutorMessage.thread_id == thread.id)
            .order_by(TutorMessage.created_at.desc(), TutorMessage.id.desc())
            .limit(8)
        ).all()
        stored.reverse()
        # A withheld reply never feeds a new turn (R-16).
        history = [
            AssistantChatMessage(role=record.role, content=record.content)
            for record in stored
            if record.role == "user" or (record.role == "assistant" and not _withdrawn(record))
        ]
        if not history:
            history = supplied_history[-8:]
        previous_user = next((record.content for record in reversed(stored) if record.role == "user"), None)
        normalized = " ".join(message.split())
        looks_like_follow_up = len(normalized.split()) <= 8 or normalized.lower().startswith(("why", "how", "what about", "and "))
        if previous_user and looks_like_follow_up:
            return f"Previous question: {previous_user}\nFollow-up question: {normalized}", history
        return normalized, history

    @staticmethod
    def _thread_read(thread: TutorThread) -> TutorThreadRead:
        return TutorThreadRead(id=thread.id, title=thread.title, created_at=thread.created_at, updated_at=thread.updated_at)

    @staticmethod
    def _require_thread(db: Session, user: AuthUser, thread_id: str) -> TutorThread:
        thread = db.get(TutorThread, thread_id)
        if thread is None or thread.user_id != user.user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tutor thread not found.")
        return thread
