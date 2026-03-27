from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user
from app.core.db import get_db
from app.schemas import BuilderShareCreate, BuilderSubmissionCreate
from app.services.microlearning import (
    get_builder_profile,
    list_builder_feed,
    list_builder_scenarios,
    share_builder_map,
    submit_builder_run,
)

router = APIRouter(prefix="/builder", tags=["builder"])


@router.get("/scenarios")
def read_builder_scenarios(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return list_builder_scenarios(db, user.user_id)


@router.get("/profile")
def read_builder_profile(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return get_builder_profile(db, user.user_id)


@router.get("/feed")
def read_builder_feed(
    limit: Annotated[int, Query(ge=1, le=30)] = 12,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
):
    return list_builder_feed(db, limit=limit, offset=offset)


@router.post("/submit")
def submit_builder_scenario(
    payload: BuilderSubmissionCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    try:
        return submit_builder_run(db, user.user_id, payload.scenario_slug, payload.placements)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/share")
def share_builder_submission(
    payload: BuilderShareCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    try:
        return share_builder_map(
            db,
            user.user_id,
            payload.scenario_slug,
            payload.caption.strip(),
            payload.placements,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
