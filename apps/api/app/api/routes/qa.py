from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user
from app.core.db import get_db
from app.db_models import QAInteraction
from app.schemas import QARequest, QAResponse
from app.services.store import get_qa_engine

router = APIRouter(prefix="/qa", tags=["qa"])


@router.post("/ask", response_model=QAResponse)
def ask_question(
    payload: QARequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    question = payload.question.strip()
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
