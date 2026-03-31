from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.db_models import QAInteraction
from app.schemas import AssistantChatRequest, AssistantChatResponse
from app.services.store import get_teaching_assistant
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

    assistant_response = get_teaching_assistant().chat(
        clean_message,
        lesson_slug=payload.lesson_slug,
        page_path=payload.page_path,
        history=payload.history,
        top_k=payload.top_k,
    )
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
