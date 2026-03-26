from fastapi import APIRouter, Depends

from app.core.auth import AuthUser, require_role
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
