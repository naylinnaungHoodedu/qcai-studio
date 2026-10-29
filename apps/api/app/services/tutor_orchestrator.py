"""Persistent Tutor orchestration with explicit evidence and pedagogical channels."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.corpus_governance import get_corpus_registry
from app.core.config import Settings
from app.core.auth import AuthUser
from app.db_models import TutorMessage, TutorThread, TutorTurn
from app.schemas import (
    AssistantChatMessage,
    AssistantChatRequest,
    AssistantChatResponse,
    TutorMessageRead,
    TutorThreadDetail,
    TutorThreadRead,
)
from app.services.contained_answers import contain_answer
from app.services.teaching_assistant import TeachingAssistantService


def _thread_title(message: str) -> str:
    compact = " ".join(message.split())
    return (compact[:120] + "...") if len(compact) > 123 else compact


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
        thread = TutorThread(id=f"thread-{uuid4()}", user_id=user.user_id, title=(title or "New grounded Tutor thread").strip()[:255])
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
            messages=[
                TutorMessageRead(id=message.id, role=message.role, content=message.content, created_at=message.created_at)
                for message in messages
            ],
        )

    def chat(self, db: Session, user: AuthUser, payload: AssistantChatRequest) -> AssistantChatResponse:
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
        contained = contain_answer(candidate.citations, get_corpus_registry(self.settings))
        turn_id = f"turn-{uuid4()}"
        db.add(TutorMessage(id=f"message-{uuid4()}", thread_id=thread.id, role="user", content=payload.message))
        db.add(TutorMessage(id=f"message-{uuid4()}", thread_id=thread.id, role="assistant", content=contained.answer))
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
                corpus_version=get_corpus_registry(self.settings).corpus_version,
                policy_version=self.settings.grounding_policy_version,
            )
        )
        thread.updated_at = datetime.now(timezone.utc)
        db.flush()
        return AssistantChatResponse(
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
        history = [
            AssistantChatMessage(role=record.role, content=record.content)
            for record in stored
            if record.role in {"user", "assistant"}
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
