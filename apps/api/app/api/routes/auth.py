from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.schemas import (
    AuthActionRead,
    AuthSessionRead,
    LocalAccountDeleteRequest,
    LocalAccountLoginRequest,
    LocalAccountRegisterRequest,
    UserProfile,
)
from app.services.local_accounts import (
    AUTH_CSRF_COOKIE_NAME,
    AUTH_SESSION_COOKIE_NAME,
    AUTH_SESSION_MAX_AGE_SECONDS,
    authenticate_local_account,
    create_local_session,
    delete_local_account,
    register_local_account,
    revoke_local_session,
)


router = APIRouter(prefix="/auth", tags=["auth"])


def _is_secure_cookie_request(request: Request, settings: Settings) -> bool:
    return request.url.scheme == "https" or settings.environment.lower() != "development"


def _user_profile(user: AuthUser) -> UserProfile:
    return UserProfile(
        user_id=user.user_id,
        email=user.email,
        role=user.role,
        auth_provider=user.provider,
        can_delete_account=user.provider == "local",
    )


def _clear_auth_cookies(response: Response) -> None:
    for cookie_name, http_only in (
        (AUTH_SESSION_COOKIE_NAME, True),
        (AUTH_CSRF_COOKIE_NAME, False),
    ):
        response.delete_cookie(cookie_name, path="/", httponly=http_only, samesite="lax")


def _set_auth_cookies(
    response: Response,
    request: Request,
    settings: Settings,
    session_token: str,
    csrf_token: str,
) -> None:
    secure = _is_secure_cookie_request(request, settings)
    response.set_cookie(
        key=AUTH_SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
        max_age=AUTH_SESSION_MAX_AGE_SECONDS,
    )
    response.set_cookie(
        key=AUTH_CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        samesite="lax",
        secure=secure,
        path="/",
        max_age=AUTH_SESSION_MAX_AGE_SECONDS,
    )


@router.get("/me", response_model=UserProfile)
def read_current_user(user: AuthUser = Depends(get_current_user)):
    return _user_profile(user)


@router.post("/register", response_model=AuthSessionRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(lambda: get_settings().auth_register_rate_limit)
def register_account(
    request: Request,
    response: Response,
    payload: LocalAccountRegisterRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    account = register_local_account(db, payload.email, payload.password)
    session_token, csrf_token, _expires_at = create_local_session(db, account.user_id)
    _set_auth_cookies(response, request, settings, session_token, csrf_token)
    return AuthSessionRead(
        status="registered",
        user=UserProfile(
            user_id=account.user_id,
            email=account.email,
            role=account.role,
            auth_provider="local",
            can_delete_account=True,
        ),
    )


@router.post("/login", response_model=AuthSessionRead)
@limiter.limit(lambda: get_settings().auth_login_rate_limit)
def login_account(
    request: Request,
    response: Response,
    payload: LocalAccountLoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    account = authenticate_local_account(db, payload.email, payload.password)
    session_token, csrf_token, _expires_at = create_local_session(db, account.user_id)
    _set_auth_cookies(response, request, settings, session_token, csrf_token)
    return AuthSessionRead(
        status="signed_in",
        user=UserProfile(
            user_id=account.user_id,
            email=account.email,
            role=account.role,
            auth_provider="local",
            can_delete_account=True,
        ),
    )


@router.post("/logout", response_model=AuthActionRead)
def logout_account(
    response: Response,
    qcai_session_token: str | None = Cookie(default=None, alias=AUTH_SESSION_COOKIE_NAME),
    db: Session = Depends(get_db),
):
    revoke_local_session(db, qcai_session_token)
    _clear_auth_cookies(response)
    return AuthActionRead(status="signed_out")


@router.delete("/account", response_model=AuthActionRead)
def delete_account(
    payload: LocalAccountDeleteRequest,
    response: Response,
    user: AuthUser = Depends(get_current_user),
    qcai_session_token: str | None = Cookie(default=None, alias=AUTH_SESSION_COOKIE_NAME),
    db: Session = Depends(get_db),
):
    if user.provider != "local":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only locally managed accounts can be deleted from this deployment.",
        )
    delete_local_account(db, user.user_id, payload.password)
    revoke_local_session(db, qcai_session_token)
    _clear_auth_cookies(response)
    return AuthActionRead(status="deleted")
