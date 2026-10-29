from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, require_role
from app.core.db import get_db
from app.schemas import GuestRevocationCreate, GuestRevocationRead
from app.services.guest_sessions import revoke_guest
from app.services.store import rebuild_course_store

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/rebuild-content")
def rebuild_content(_: AuthUser = Depends(require_role("instructor", "admin"))):
    store = rebuild_course_store()
    return {
        "status": "rebuilt",
        "module_count": len(store.modules),
        "lesson_count": len(store.lessons),
        "chunk_count": len(store.chunks),
    }


@router.post("/guest-revocations", response_model=GuestRevocationRead)
def revoke_guest_session(
    payload: GuestRevocationCreate,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_role("admin")),
):
    revocation = revoke_guest(db, payload.guest_id, payload.reason)
    return GuestRevocationRead(status="revoked", revoked_at=revocation.revoked_at)
