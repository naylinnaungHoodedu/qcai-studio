from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, require_durable_learner
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.core.config import get_settings
from app.schemas import LearnerRecordOperationsRequest, LearnerRecordOperationsResponse, LearnerRecordRead
from app.services.learner_record import apply_learner_record_operations, read_learner_record


router = APIRouter(prefix="/learner-record", tags=["learner-record"])


@router.get("", response_model=LearnerRecordRead)
def get_learner_record(
    user: AuthUser = Depends(require_durable_learner),
    db: Session = Depends(get_db),
):
    return read_learner_record(db, user.user_id)


@router.post("/operations", response_model=LearnerRecordOperationsResponse)
@limiter.limit(lambda: get_settings().assistant_chat_rate_limit)
def post_learner_record_operations(
    request: Request,
    response: Response,
    payload: LearnerRecordOperationsRequest,
    user: AuthUser = Depends(require_durable_learner),
    db: Session = Depends(get_db),
):
    receipts, record = apply_learner_record_operations(db, user.user_id, payload.operations)
    db.commit()
    return LearnerRecordOperationsResponse(receipts=receipts, record=record)
