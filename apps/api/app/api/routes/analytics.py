from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user
from app.core.db import get_db
from app.db_models import AnalyticsEvent
from app.schemas import AnalyticsEventCreate

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post("/events")
def record_event(
    payload: AnalyticsEventCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    event = AnalyticsEvent(
        user_id=user.user_id,
        event_type=payload.event_type,
        lesson_slug=payload.lesson_slug,
        payload=payload.payload,
    )
    db.add(event)
    db.commit()
    return {"status": "ok"}
