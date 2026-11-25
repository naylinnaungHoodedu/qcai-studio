from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, has_bearer_subject, learner_write_observation, require_bearer_subject, require_durable_learner
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.core.config import get_settings
from app.schemas import (
    LearnerRecordOperationsRequest, LearnerRecordOperationsResponse, LearnerRecordRead,
    LearnerReplicaIssued, LearnerReplicaRequest,
)
from app.services.learner_record import apply_learner_record_operations, read_learner_record
from app.services.learner_record_identity import find_subject, write_subject
from app.services.learner_record_sync import issue_learner_replica, read_existing_learner_record, synchronize_client_operations


router = APIRouter(prefix="/learner-record", tags=["learner-record"])


@router.get("", response_model=LearnerRecordRead)
def get_learner_record(
    user: AuthUser = Depends(require_durable_learner),
    db: Session = Depends(get_db),
):
    sync = get_settings().learner_sync == "on"
    if sync:
        require_bearer_subject(user)
    subject = find_subject(db, user.provider, user.user_id) if has_bearer_subject(user) else None
    if sync or subject:
        return read_existing_learner_record(db, subject or user.user_id)
    return read_learner_record(db, user.user_id)


def require_sync_enabled() -> None:
    if get_settings().learner_sync != "on":
        raise HTTPException(404, "Not found.")


@router.post("/replicas", response_model=LearnerReplicaIssued, status_code=201, dependencies=[Depends(require_sync_enabled)])
@limiter.limit(lambda: get_settings().assistant_chat_rate_limit)
def post_learner_replica(
    request: Request,
    response: Response,
    payload: LearnerReplicaRequest | None = None,
    user: AuthUser = Depends(require_durable_learner),
    db: Session = Depends(get_db),
):
    require_bearer_subject(user)
    subject = write_subject(
        db, user.provider, user.user_id, bind=get_settings().learner_identity == "on",
        guarded=True, observation=learner_write_observation(request),
    )
    replica_id = issue_learner_replica(db, subject, payload.preferred_replica_id if payload else None)
    db.commit()
    return LearnerReplicaIssued(replica_id=replica_id)


@router.post("/operations", response_model=LearnerRecordOperationsResponse)
@limiter.limit(lambda: get_settings().assistant_chat_rate_limit)
def post_learner_record_operations(
    request: Request,
    response: Response,
    payload: LearnerRecordOperationsRequest,
    user: AuthUser = Depends(require_durable_learner),
    db: Session = Depends(get_db),
):
    sync = get_settings().learner_sync == "on"
    if sync:
        require_bearer_subject(user)
        version = payload.expected_record_version
        if type(version) is not int or not 0 <= version <= 2_147_483_647:
            raise HTTPException(422, "An integer expected_record_version is required.")
        subject = write_subject(
            db, user.provider, user.user_id, bind=get_settings().learner_identity == "on",
            guarded=True, observation=learner_write_observation(request),
        )
        receipts, record = synchronize_client_operations(db, subject, version, payload.operations)
    else:
        subject = user.user_id
        if has_bearer_subject(user):
            subject = write_subject(
                db, user.provider, user.user_id, bind=False, guarded=False, observation=learner_write_observation(request),
            )
        receipts, record = apply_learner_record_operations(db, subject, payload.operations)
    db.commit()
    return LearnerRecordOperationsResponse(receipts=receipts, record=record)
