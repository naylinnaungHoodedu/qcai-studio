from collections.abc import Callable

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.db_models import QAInteraction
from app.schemas import AssistantChatRequest, AssistantChatResponse, TutorThreadCreate, TutorThreadDetail, TutorThreadRead
from app.services.span_store import persist_cited_spans
from app.services.store import get_course_store, get_tutor_orchestrator
from app.services.text_utils import sanitize_user_text
from app.services.tutor_followups import run_turn_followups


router = APIRouter(prefix="/assistant", tags=["assistant"])

# One rate-limit window for every path that delivers a tutor turn (spec 18.10 H5): POST /assistant/chat and
# POST /tutor/turns both run deliver_tutor_turn, and slowapi keeps one window per endpoint unless they share a
# scope, so a client alternating the two got twice the budget (as the /spans alias did, 18.4). The rate is
# ASSISTANT_CHAT_RATE_LIMIT, the production route's own limit, so /assistant/chat keeps its budget; requests to
# POST /tutor/turns, which answers 404 outside development, count against the same window.
TUTOR_TURN_RATE_LIMIT_SCOPE = "tutor-turn"


def tutor_turn_rate_limit() -> str:
    return get_settings().assistant_chat_rate_limit


def deliver_tutor_turn(
    request: Request,
    response: Response,
    payload: AssistantChatRequest,
    background_tasks: BackgroundTasks,
    db: Session,
    user: AuthUser,
    *,
    presentation_plan: str | None = None,
    before_commit: Callable[[AssistantChatResponse], None] | None = None,
) -> AssistantChatResponse:
    """One tutor turn as /assistant/chat has always delivered it, then its Phase 3 follow-ups after the commit:
    the legacy ledger record (bounded, fail-open) and, in shadow mode, the two-pass run as a background task.
    before_commit (POST /tutor/turns with an Idempotency-Key) adds rows to the turn's own transaction, so a turn and
    its idempotency record commit together or not at all."""
    orchestrator = get_tutor_orchestrator()
    extra = {"presentation_plan": presentation_plan} if presentation_plan is not None else {}
    assistant_response = orchestrator.chat(db, user, payload, **extra)
    db.add(
        QAInteraction(
            user_id=user.user_id,
            lesson_slug=payload.lesson_slug,
            question=payload.message,
            answer=assistant_response.answer,
            citations=[citation.model_dump() for citation in assistant_response.citations],
        )
    )
    # Idempotent: the tutor already registered the spans it cited (task 2.2).
    persist_cited_spans(db, assistant_response.citations, get_course_store())
    if before_commit is not None:
        before_commit(assistant_response)
    db.commit()
    run_turn_followups(assistant_response, orchestrator, background_tasks)
    response.headers["x-assistant-provider"] = assistant_response.provider
    response.headers["x-assistant-model"] = assistant_response.model
    return assistant_response


@router.post("/chat", response_model=AssistantChatResponse)
@limiter.shared_limit(tutor_turn_rate_limit, scope=TUTOR_TURN_RATE_LIMIT_SCOPE)
def chat_with_teaching_assistant(
    request: Request,
    response: Response,
    payload: AssistantChatRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    clean_message = sanitize_user_text(payload.message)
    if not clean_message:
        raise HTTPException(status_code=422, detail="Message cannot be empty.")
    return deliver_tutor_turn(request, response, payload.model_copy(update={"message": clean_message}), background_tasks, db, user)


@router.get("/threads", response_model=list[TutorThreadRead])
def list_tutor_threads(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return get_tutor_orchestrator().list_threads(db, user)


@router.post("/threads", response_model=TutorThreadRead, status_code=201)
def create_tutor_thread(
    payload: TutorThreadCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    thread = get_tutor_orchestrator().create_thread(db, user, payload.title)
    db.commit()
    return thread


@router.get("/threads/{thread_id}", response_model=TutorThreadDetail)
def read_tutor_thread(
    thread_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return get_tutor_orchestrator().read_thread(db, user, thread_id)
