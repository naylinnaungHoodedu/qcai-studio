from fastapi import APIRouter, Depends

from app.core.auth import AuthUser, get_current_user
from app.schemas import UserProfile

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=UserProfile)
def read_current_user(user: AuthUser = Depends(get_current_user)):
    return UserProfile(user_id=user.user_id, email=user.email, role=user.role)
