"""POST /tutor/turns: the two-pass tutor endpoint (plan 7.3; Phase 3 spec 9, conflict 4).

Always registered, so the authorization matrix stays static, but 404 outside development unless TWO_PASS_TUTOR is
on, which settings refuse before the Phase 4 exit: production behaviour is unchanged. Where it runs it delivers
the legacy contained answer exactly as /assistant/chat does (delivery "legacy") and, in shadow mode, runs the
two-pass pipeline after the response is sent; zero of its outputs reach the learner (AC-3-6). The body refuses
unknown fields, so no learner-state field (page_path, history, mastery, ids) can be sent (AC-3-1).

An optional Idempotency-Key header (plan 7.3 "mutations carry client keys"; DI-40) makes a retried POST return the
first turn instead of creating a second one (app.services.turn_idempotency). It is read after the flag, so a
disabled route answers 404 whatever the header holds.

The route shares one rate-limit window with POST /assistant/chat (scope "tutor-turn", ASSISTANT_CHAT_RATE_LIMIT):
both deliver the same tutor turn, so alternating them never doubles a client's budget (spec 18.10 H5).
"""

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.routes.assistant import TUTOR_TURN_RATE_LIMIT_SCOPE, deliver_tutor_turn, tutor_turn_rate_limit
from app.core.auth import AuthUser, get_current_user
from app.core.config import get_settings
from app.core.config_package import get_config_package
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.db_models import TutorTurnIdempotency
from app.schemas import AssistantChatRequest, AssistantChatResponse, TutorTurnRequest, TutorTurnResponse
from app.services import turn_idempotency
from app.services.ledger import ledger_canonical
from app.services.text_utils import sanitize_user_text

router = APIRouter(prefix="/tutor", tags=["tutor"])


@router.post(
    "/turns",
    response_model=TutorTurnResponse,
    responses={404: {"description": "Not Found"}, 409: {"description": "A request with this Idempotency-Key is still running."}},
)
@limiter.shared_limit(tutor_turn_rate_limit, scope=TUTOR_TURN_RATE_LIMIT_SCOPE)
def create_tutor_turn(
    request: Request,
    response: Response,
    payload: TutorTurnRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias=turn_idempotency.IDEMPOTENCY_HEADER),
):
    settings = get_settings()
    if not settings.tutor_turns_route_enabled:
        return JSONResponse(status_code=404, content={"detail": "Not Found"}, headers={"Cache-Control": "no-store"})
    params = get_config_package(settings).tutor_pipeline
    key = turn_idempotency.parse_key(idempotency_key, params)
    clean_message = sanitize_user_text(payload.message)
    if not clean_message:
        raise HTTPException(status_code=422, detail="Message cannot be empty.")
    chat = AssistantChatRequest(message=clean_message, thread_id=payload.thread_id, lesson_slug=payload.lesson_slug)
    if key is None or params is None:
        delivered = deliver_tutor_turn(request, response, chat, background_tasks, db, user, presentation_plan=payload.presentation_plan)
        return TutorTurnResponse(**delivered.model_dump(), delivery="legacy")

    now = datetime.now(UTC)
    key_digest = turn_idempotency.key_sha256(key)
    request_digest = turn_idempotency.request_sha256(
        message=clean_message, thread_id=payload.thread_id, lesson_slug=payload.lesson_slug, presentation_plan=payload.presentation_plan
    )
    existing = turn_idempotency.find(db, user.user_id, key_digest, now=now, ttl_hours=params.idempotency_ttl_hours,
                                     lease_seconds=params.idempotency_lease_seconds)
    if existing is not None:
        return turn_idempotency.answer_for(existing, request_digest)
    claim = turn_idempotency.new_claim(user_id=user.user_id, key_digest=key_digest, request_digest=request_digest, now=now)
    db.add(claim)
    try:
        db.commit()
    except IntegrityError:
        # Another request with this key claimed it first.
        db.rollback()
        winner = turn_idempotency.find(db, user.user_id, key_digest, now=now, ttl_hours=params.idempotency_ttl_hours,
                                       lease_seconds=params.idempotency_lease_seconds)
        if winner is None:  # pragma: no cover - the winner expired or was released in between
            return JSONResponse(status_code=409, content={"detail": "A request with this Idempotency-Key is still being processed."},
                                headers={"Cache-Control": "no-store"})
        return turn_idempotency.answer_for(winner, request_digest)

    # The claim's identity, read once: the turn's transaction must not reload it (spec 18.8 F13).
    held = TutorTurnIdempotency(id=claim.id, claim_token=claim.claim_token)
    db.expunge(claim)

    def remember(assistant_response: AssistantChatResponse) -> None:
        body = TutorTurnResponse(**assistant_response.model_dump(), delivery="legacy")
        # Conditional on this request's claim token: a request that outlived its lease gets 409 and its turn rolls
        # back, so a retry that took the key over keeps the only turn (turn_idempotency.fill).
        turn_idempotency.fill(db, held, turn_id=body.turn_id, response_body=ledger_canonical(body.model_dump(mode="json")).decode("utf-8"))

    try:
        delivered = deliver_tutor_turn(
            request, response, chat, background_tasks, db, user, presentation_plan=payload.presentation_plan, before_commit=remember
        )
    except BaseException:
        # The turn did not commit: release the claim, so a retry with this key runs the turn again.
        db.rollback()
        try:
            turn_idempotency.release(db, held)
            db.commit()
        except Exception:  # noqa: BLE001 - never mask the turn's own error; the claim is then abandoned and its lease ends
            db.rollback()
        raise
    return TutorTurnResponse(**delivered.model_dump(), delivery="legacy")
