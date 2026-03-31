from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.core.request_protection import validate_request_origin
from app.db_models import SupportRequest
from app.schemas import SupportRequestCreate, SupportRequestRead


router = APIRouter(prefix="/support", tags=["support"])
SUPPORT_RESPONSE_TARGET = "2 business days for product/privacy requests; 5 business days for partnership and security follow-up."


@router.post("/requests", response_model=SupportRequestRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(lambda: get_settings().support_request_rate_limit)
def create_support_request(
    payload: SupportRequestCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if payload.website:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported request payload.")

    request_origin = validate_request_origin(request, settings)
    support_request = SupportRequest(
        name=payload.name,
        email=payload.email,
        organization=payload.organization,
        request_type=payload.request_type,
        page_url=payload.page_url,
        message=payload.message,
        requester_origin=request_origin,
        user_agent=request.headers.get("user-agent"),
        status="received",
    )
    db.add(support_request)
    db.commit()
    db.refresh(support_request)
    return SupportRequestRead(
        status="received",
        ticket_id=f"SUP-{support_request.id:06d}",
        request_type=support_request.request_type,
        response_target=SUPPORT_RESPONSE_TARGET,
        created_at=support_request.created_at,
    )
