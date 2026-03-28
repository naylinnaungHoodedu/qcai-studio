from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user
from app.core.db import get_db
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.db_models import QAInteraction
from app.schemas import Citation, QAHistoryItem, QARequest, QAResponse
from app.services.store import get_qa_engine
from app.services.text_utils import sanitize_user_text

router = APIRouter(prefix="/qa", tags=["qa"])


@router.post("/ask", response_model=QAResponse)
@limiter.limit(lambda: get_settings().qa_ask_rate_limit)
def ask_question(
    request: Request,
    response: Response,
    payload: QARequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    question = sanitize_user_text(payload.question)
    if not question:
        raise HTTPException(status_code=422, detail="Question cannot be empty.")
    response = get_qa_engine().ask(question, payload.lesson_slug, payload.top_k)
    db.add(
        QAInteraction(
            user_id=user.user_id,
            lesson_slug=payload.lesson_slug,
            question=question,
            answer=response.answer,
            citations=[citation.model_dump() for citation in response.citations],
        )
    )
    db.commit()
    return response


@router.get("/history", response_model=list[QAHistoryItem])
def read_question_history(
    lesson_slug: str | None = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    filters = [QAInteraction.user_id == user.user_id]
    if lesson_slug:
        filters.append(QAInteraction.lesson_slug == lesson_slug)
    records = db.scalars(
        select(QAInteraction)
        .where(*filters)
        .order_by(QAInteraction.created_at.desc(), QAInteraction.id.desc())
    ).all()[offset : offset + limit]
    return [
        QAHistoryItem(
            id=record.id,
            lesson_slug=record.lesson_slug,
            question=record.question,
            answer=record.answer,
            citations=[Citation.model_validate(citation) for citation in (record.citations or [])],
            created_at=record.created_at,
        )
        for record in records
    ]
