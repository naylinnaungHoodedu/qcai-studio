from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.db_models import QAInteraction
from app.schemas import AssistantChatRequest, AssistantChatResponse, TutorThreadCreate, TutorThreadDetail, TutorThreadRead
from app.services.store import get_tutor_orchestrator
from app.services.text_utils import sanitize_user_text


router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/chat", response_model=AssistantChatResponse)
@limiter.limit(lambda: get_settings().assistant_chat_rate_limit)
def chat_with_teaching_assistant(
    request: Request,
    response: Response,
    payload: AssistantChatRequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    clean_message = sanitize_user_text(payload.message)
    if not clean_message:
        raise HTTPException(status_code=422, detail="Message cannot be empty.")

    assistant_response = get_tutor_orchestrator().chat(db, user, payload.model_copy(update={"message": clean_message}))
    db.add(
        QAInteraction(
            user_id=user.user_id,
            lesson_slug=payload.lesson_slug,
            question=clean_message,
            answer=assistant_response.answer,
            citations=[citation.model_dump() for citation in assistant_response.citations],
        )
    )
    db.commit()
    response.headers["x-assistant-provider"] = assistant_response.provider
    response.headers["x-assistant-model"] = assistant_response.model
    return assistant_response


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
