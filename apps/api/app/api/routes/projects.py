from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user
from app.core.db import get_db
from app.schemas import PeerReviewCreate, PeerReviewRead, ProjectBrief, ProjectSubmissionCreate, ProjectSubmissionRead, ReviewQueueItem
from app.services.project_studio import (
    create_project_submission,
    list_project_catalog,
    list_review_queue,
    list_user_submissions,
    retract_project_submission,
    submit_peer_review,
)


router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/catalog", response_model=list[ProjectBrief])
def read_project_catalog(db: Session = Depends(get_db)):
    return list_project_catalog(db)


@router.get("/my-submissions", response_model=list[ProjectSubmissionRead])
def read_user_project_submissions(
    limit: Annotated[int, Query(ge=1, le=50)] = 12,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return list_user_submissions(db, user.user_id, limit=limit, offset=offset)


@router.get("/review-queue", response_model=list[ReviewQueueItem])
def read_project_review_queue(
    limit: Annotated[int, Query(ge=1, le=25)] = 8,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return list_review_queue(db, user.user_id, limit=limit, offset=offset)


@router.post("/submissions", response_model=ProjectSubmissionRead)
def create_submission(
    payload: ProjectSubmissionCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    try:
        return create_project_submission(
            db,
            user.user_id,
            payload.project_slug,
            payload.title,
            payload.solution_summary,
            payload.implementation_notes,
            payload.confidence_level,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/reviews", response_model=PeerReviewRead)
def create_peer_review(
    payload: PeerReviewCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    try:
        return submit_peer_review(
            db,
            user.user_id,
            payload.submission_id,
            payload.rubric_scores,
            payload.feedback,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/submissions/{submission_id}", response_model=ProjectSubmissionRead)
def retract_submission(
    submission_id: int,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    try:
        return retract_project_submission(db, user.user_id, submission_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
