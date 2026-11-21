"""Persistent Tutor orchestration with explicit evidence and pedagogical channels.

Phase 3 (docs/architecture/phase3-implementation-spec.md 7.11): the learner still receives only the legacy
contained answer (D-19, unchanged). Each turn also prepares its follow-ups, which the route runs after the commit:
a legacy ledger record (TUTOR_LEDGER_ENABLED) and, when two_pass_tutor is in shadow, a two-pass shadow run whose
output reaches no learner (AC-3-6). The evidence panel (task 3.8) is added only when EVIDENCE_PANEL_ENABLED.

Phase 4 (spec 7.4; plan Phase 4 L): the contained answer passes the legacy guard (V1.1 and V1.2; no flag) before
anything reads it (every current quotation passes, so the body is unchanged), and the shadow job carries the learner's
decision for V1's comparison. Conflicting quotations (V1.7) are labelled by the evidence panel when it is shown, and
otherwise withheld by the guard (AC-4-6). A stored reply that read_thread shows again carries the same V1.7 labels,
from its turn's citations, whether or not the panel is on, so no surface re-shows conflicting quotations undisclosed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, select
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
    EvidenceConflict,
    TutorMessageRead,
    TutorThreadDetail,
    TutorThreadRead,
)
from app.services.answer_history import WITHDRAWN_ANSWER, stored_before_containment
from app.services.contained_answers import ContainedAnswer, contain_answer
from app.services.evidence_panel import build_evidence_panel, panel_conflicts, stored_conflicts
from app.services.ledger import LegacyDelivery, LegacyPreparationFailed, legacy_delivery_for, preparation_failed
from app.services.retrieval_metrics import record_citations
from app.services.span_store import persist_cited_spans
from app.services.teaching_assistant import TeachingAssistantService
from app.services.tutor_followups import TurnFollowups
from app.services.tutor_pipeline.contracts import PresentationPlan
from app.services.tutor_pipeline.metrics import TWO_PASS_METRICS
from app.services.tutor_pipeline.shadow import ShadowJob, effective_mode
from app.services.tutor_pipeline.shadow import run_shadow as run_shadow_job
from app.services.v1_checks.legacy_guard import guard_contained

TUTOR_LOGGER = logging.getLogger("qcai.tutor")
# The reply follows the learner's message by this much, and each turn follows the thread's latest message by it.
MESSAGE_TICK = timedelta(microseconds=1)
# A thread read returns its first THREAD_MESSAGES messages; their replies belong to at most half as many turns, so
# reading the first THREAD_TURNS turns finds each reply's turn.
THREAD_MESSAGES = 100
THREAD_TURNS = 100


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    # SQLite returns these timestamps without a zone (stored as UTC); PostgreSQL returns them with one.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def next_message_time(db: Session, thread_id: str) -> datetime:
    """The time of a new turn's first message: now (timezone-aware UTC), but never before the thread's latest message
    plus MESSAGE_TICK, so a thread's messages keep a strict order whatever the clocks of the instances that wrote them.

    The thread row is locked first (SELECT ... FOR UPDATE on PostgreSQL, held until the turn commits; SQLite
    serialises writers), so two concurrent turns of one thread take their times one after the other: the second
    reads the first's committed messages. The thread row was already locked from the turn's UPDATE of updated_at to
    its commit; this takes the same lock a few statements earlier. Phase 3 spec M5 and 18.5 (a production change
    to stored data that ships only with a D-05 release)."""
    db.execute(select(TutorThread.id).where(TutorThread.id == thread_id).with_for_update())
    latest = db.scalar(select(func.max(TutorMessage.created_at)).where(TutorMessage.thread_id == thread_id))
    now = _utc_now()
    if latest is not None and now < _as_utc(latest) + MESSAGE_TICK:
        now = _as_utc(latest) + MESSAGE_TICK
    return now


def _thread_title(message: str) -> str:
    compact = " ".join(message.split())
    return (compact[:120] + "...") if len(compact) > 123 else compact


def _withdrawn(message: TutorMessage) -> bool:
    return message.role == "assistant" and stored_before_containment(message.created_at)


def _message_read(message: TutorMessage, conflicts: list[EvidenceConflict] | None = None) -> TutorMessageRead:
    # A reply the uncontained build stored is withheld; the learner's own messages stay (R-16).
    withdrawn = _withdrawn(message)
    return TutorMessageRead(
        id=message.id,
        role=message.role,
        content=WITHDRAWN_ANSWER if withdrawn else message.content,
        created_at=message.created_at,
        withdrawn=withdrawn,
        conflicts=None if withdrawn else conflicts,
    )


def _reply_conflicts(db: Session, thread_id: str, messages: list[TutorMessage], package) -> dict[str, list[EvidenceConflict]]:
    """The V1.7 labels of each stored reply whose quoted passages conflict, by message id: the evidence panel's rule
    over the citations of the reply's turn (AC-4-6 where a reply is shown again; Phase 4 spec 4.15).

    A reply's turn is the thread's turn stamped one MESSAGE_TICK before it (chat() sets both times, Phase 3 spec M5),
    or, for a reply the database clock stamped (before chat() set the times), the turn stamped at the same instant. An
    instant two turns share links neither. Only a turn that answered is read, and only the first THREAD_TURNS turns,
    which hold every reply of the first 100 messages."""
    replies = [message for message in messages if message.role == "assistant" and not _withdrawn(message)]
    if package.v1 is None or not replies:
        return {}
    turns = db.execute(
        select(TutorTurn.created_at, TutorTurn.decision, TutorTurn.citations)
        .where(TutorTurn.thread_id == thread_id)
        .order_by(TutorTurn.created_at.asc(), TutorTurn.id.asc())
        .limit(THREAD_TURNS)
    ).all()
    by_time: dict[datetime, list[tuple[str, list]]] = {}
    for created_at, decision, citations in turns:
        by_time.setdefault(_as_utc(created_at), []).append((decision, citations or []))
    found: dict[str, list[EvidenceConflict]] = {}
    for reply in replies:
        stamped = _as_utc(reply.created_at)
        linked = by_time.get(stamped - MESSAGE_TICK) or by_time.get(stamped) or []
        if len(linked) != 1 or linked[0][0] != "answer":
            continue
        conflicts = stored_conflicts(linked[0][1], package)
        if conflicts:
            found[reply.id] = conflicts
    return found


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
        messages = list(db.scalars(
            select(TutorMessage)
            .where(TutorMessage.thread_id == thread.id)
            .order_by(TutorMessage.created_at.asc(), TutorMessage.id.asc())
            .limit(THREAD_MESSAGES)
        ).all())
        # AC-4-6 where a reply is shown again: its V1.7 labels, whatever EVIDENCE_PANEL_ENABLED says (spec 4.15).
        conflicts = _reply_conflicts(db, thread.id, messages, get_config_package(self.settings))
        return TutorThreadDetail(
            **self._thread_read(thread).model_dump(),
            messages=[_message_read(message, conflicts.get(message.id)) for message in messages],
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
        # Plan Phase 4 L: V1.1 and V1.2 stay enforced on every delivery path, in every V1_PIPELINE mode (no flag).
        # AC-4-6: conflicting quotations are labelled by the evidence panel when it is shown and the package's conflict
        # policy is disclose, else withheld (V1.7); the stored reply carries the same labels when read_thread shows it
        # again, and its ledger record when the ledger route does.
        package = get_config_package(self.settings)
        contained = guard_contained(contained, store=self._store(), package=package, surface="tutor",
                                    disclosure_shown=self.settings.evidence_panel_enabled).contained
        record_citations("tutor", len(contained.citations), contained.dropped_unresolved, 0)
        turn_id = f"turn-{uuid4()}"
        user_message_id = f"message-{uuid4()}"
        # Times are set here, not by the database, so the learner's turns of a thread have a strict order even
        # within one second on SQLite and within one transaction on PostgreSQL (Phase 3 spec M5): the reply follows
        # the question by one microsecond, and a turn follows the thread's latest message (next_message_time).
        now = next_message_time(db, thread.id)
        db.add(TutorMessage(id=user_message_id, thread_id=thread.id, role="user", content=payload.message, created_at=now))
        db.add(
            TutorMessage(
                id=f"message-{uuid4()}",
                thread_id=thread.id,
                role="assistant",
                content=contained.answer,
                created_at=now + MESSAGE_TICK,
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
                # Whether this turn's delivery is ledgered (spec 18.8 F12): an image that keeps no ledger leaves it
                # null, so a turn it served is never read as a lost record.
                ledger_record_expected=bool(self.settings.tutor_ledger_enabled),
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
                decision=contained.decision, citations=contained.citations, retrieval_mode=candidate.retrieval_mode, settings=self.settings,
                conflicts=panel_conflicts(contained, package),
            )
        response._followups = TurnFollowups(
            legacy=self._legacy_followup(turn_id, candidate, contained, registry),
            shadow=self._shadow_followup(turn_id, thread.id, user_message_id, payload.lesson_slug, presentation_plan,
                                         legacy_decision=contained.decision),
        )
        return response

    # --- Phase 3 follow-ups: prepared here, run by the route after the commit (tutor_followups) ---

    def _legacy_followup(
        self, turn_id: str, candidate: AssistantChatResponse, contained: ContainedAnswer, registry: CorpusRegistry
    ) -> LegacyDelivery | LegacyPreparationFailed | None:
        """The turn's legacy record, prepared before the commit. Nothing is counted here: the route's
        run_turn_followups counts the attempt (and a preparation failure) only once the turn has committed, so a turn
        that rolls back never lowers the ledger coverage SLI (spec 18.7 E5)."""
        if not self.settings.tutor_ledger_enabled:
            return None
        try:
            return self._legacy_delivery(turn_id, candidate, contained, registry)
        except Exception as exc:  # noqa: BLE001 - a lost record is counted after the commit (plan L stop); the answer is unchanged
            return preparation_failed(exc, contained=contained, retrieval=getattr(candidate, "_retrieval", None), surface="tutor")

    def _legacy_delivery(self, turn_id: str, candidate: AssistantChatResponse, contained: ContainedAnswer, registry: CorpusRegistry) -> LegacyDelivery:
        store = self._store()
        retrieval = getattr(candidate, "_retrieval", None)
        return legacy_delivery_for(
            response_id=turn_id,
            contained=contained,
            retrieval=retrieval if retrieval is not None and isinstance(getattr(retrieval, "results", None), list) else None,
            store=store,
            registry=registry,
            retrieval_mode=candidate.retrieval_mode,
            provider=candidate.provider,
            model=candidate.model,
            policy_version=self.settings.grounding_policy_version,
            surface="legacy",
        )

    def _shadow_followup(
        self, turn_id: str, thread_id: str, user_message_id: str, lesson_slug: str | None, presentation_plan: str | None,
        *, legacy_decision: str | None = None,
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
                legacy_decision=legacy_decision if legacy_decision in ("answer", "abstain") else None,
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
