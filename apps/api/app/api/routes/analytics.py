from statistics import mean

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.core.request_protection import validate_request_origin
from app.db_models import AnalyticsEvent, PublicWebVital
from app.schemas import (
    AnalyticsEventCreate,
    PublicWebVitalCreate,
    PublicWebVitalReceipt,
    PublicWebVitalSummaryItem,
    PublicWebVitalSummaryRead,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _p75(values: list[float]) -> float:
    sorted_values = sorted(values)
    if not sorted_values:
        return 0.0
    index = max(0, int(round(0.75 * (len(sorted_values) - 1))))
    return round(sorted_values[index], 2)


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


@router.post("/public-web-vitals", response_model=PublicWebVitalReceipt)
@limiter.limit(lambda: get_settings().public_web_vitals_rate_limit)
def record_public_web_vital(
    payload: PublicWebVitalCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    validate_request_origin(request, settings)
    metric = PublicWebVital(
        metric_id=payload.metric_id,
        metric_name=payload.metric_name,
        path=payload.path,
        value=payload.value,
        delta=payload.delta,
        rating=payload.rating,
        navigation_type=payload.navigation_type,
        user_agent=request.headers.get("user-agent"),
        connection_type=payload.connection_type,
    )
    db.add(metric)
    db.commit()
    return PublicWebVitalReceipt(status="accepted")


@router.get("/public-web-vitals/summary", response_model=PublicWebVitalSummaryRead)
def read_public_web_vitals_summary(db: Session = Depends(get_db)):
    samples = (
        db.query(PublicWebVital)
        .order_by(PublicWebVital.created_at.desc())
        .limit(500)
        .all()
    )
    metrics: list[PublicWebVitalSummaryItem] = []
    monitored_paths = sorted({sample.path for sample in samples})

    for metric_name in sorted({sample.metric_name for sample in samples}):
        metric_samples = [sample for sample in samples if sample.metric_name == metric_name]
        values = [sample.value for sample in metric_samples]
        good_count = sum(1 for sample in metric_samples if sample.rating == "good")
        metrics.append(
            PublicWebVitalSummaryItem(
                metric_name=metric_name,
                sample_count=len(metric_samples),
                average_value=round(mean(values), 2),
                p75_value=_p75(values),
                good_rate_percent=round((good_count / len(metric_samples)) * 100, 1),
            )
        )

    return PublicWebVitalSummaryRead(
        status="ok",
        total_samples=len(samples),
        monitored_paths=monitored_paths,
        last_sample_at=samples[0].created_at if samples else None,
        metrics=metrics,
    )
