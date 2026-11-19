"""POST /tutor/turns: the two-pass tutor endpoint (plan 7.3; Phase 3 spec 9, conflict 4).

Always registered, so the authorization matrix stays static, but 404 outside development unless TWO_PASS_TUTOR is
on, which settings refuse before the Phase 4 exit: production behaviour is unchanged. Where it runs it delivers
the legacy contained answer exactly as /assistant/chat does (delivery "legacy") and, in shadow mode, runs the
two-pass pipeline after the response is sent; zero of its outputs reach the learner (AC-3-6). The body refuses
unknown fields, so no learner-state field (page_path, history, mastery, ids) can be sent (AC-3-1).
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.routes.assistant import deliver_tutor_turn
from app.core.auth import AuthUser, get_current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.schemas import AssistantChatRequest, TutorTurnRequest, TutorTurnResponse
from app.services.text_utils import sanitize_user_text

router = APIRouter(prefix="/tutor", tags=["tutor"])


@router.post("/turns", response_model=TutorTurnResponse, responses={404: {"description": "Not Found"}})
@limiter.limit(lambda: get_settings().tutor_turns_rate_limit)
def create_tutor_turn(
    request: Request,
    response: Response,
    payload: TutorTurnRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    if not get_settings().tutor_turns_route_enabled:
        return JSONResponse(status_code=404, content={"detail": "Not Found"}, headers={"Cache-Control": "no-store"})
    clean_message = sanitize_user_text(payload.message)
    if not clean_message:
        raise HTTPException(status_code=422, detail="Message cannot be empty.")
    chat = AssistantChatRequest(message=clean_message, thread_id=payload.thread_id, lesson_slug=payload.lesson_slug)
    delivered = deliver_tutor_turn(request, response, chat, background_tasks, db, user, presentation_plan=payload.presentation_plan)
    return TutorTurnResponse(**delivered.model_dump(), delivery="legacy")
