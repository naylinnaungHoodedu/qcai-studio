from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.schemas import (
    AuthActionRead,
    AuthSessionRead,
    GuestUpgradeRead,
    GuestUpgradeRequest,
    LocalAccountDeleteRequest,
    LocalAccountLoginRequest,
    LocalAccountRegisterRequest,
    UserProfile,
)
from app.services import sign_in_lockout
from app.services.security_log import record_security_event
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
from app.services.guest_sessions import upgrade_legacy_guest


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
    try:
        account = register_local_account(db, payload.email, payload.password)
    except HTTPException as exc:
        record_security_event("auth.register", "failure", connection=request, details={"status": exc.status_code})
        raise
    session_token, csrf_token, _expires_at = create_local_session(db, account.user_id)
    _set_auth_cookies(response, request, settings, session_token, csrf_token)
    record_security_event(
        "auth.register", "success", connection=request, actor_role=account.role, subject=account.user_id
    )
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
    locked_seconds = sign_in_lockout.seconds_locked(payload.email)
    if locked_seconds:
        # Checked before the password, so a locked email gives a guesser nothing, right or wrong.
        record_security_event("auth.lockout", "denied", connection=request, details={"retry_after": locked_seconds})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed sign-ins for this account. Try again later.",
            headers={"Retry-After": str(locked_seconds)},
        )
    try:
        account = authenticate_local_account(db, payload.email, payload.password)
    except HTTPException as exc:
        failures = sign_in_lockout.register_failure(payload.email) if exc.status_code == 401 else 0
        record_security_event("auth.login", "failure", connection=request, details={"status": exc.status_code})
        if failures == settings.auth_lockout_failures:
            record_security_event("auth.lockout", "warning", connection=request, details={"failures": failures})
        raise
    sign_in_lockout.clear(payload.email)
    session_token, csrf_token, _expires_at = create_local_session(db, account.user_id)
    _set_auth_cookies(response, request, settings, session_token, csrf_token)
    record_security_event("auth.login", "success", connection=request, actor_role=account.role, subject=account.user_id)
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
    request: Request,
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
    try:
        erasure = delete_local_account(db, user.user_id, payload.password)
    except HTTPException as exc:
        record_security_event(
            "account.delete",
            "failure",
            connection=request,
            actor_role=user.role,
            subject=user.user_id,
            details={"status": exc.status_code},
        )
        raise
    revoke_local_session(db, qcai_session_token)
    _clear_auth_cookies(response)
    # The digest outlives the account's rows by design: it cannot be turned back into the deleted id.
    record_security_event(
        "account.delete",
        "success",
        connection=request,
        actor_role=user.role,
        subject=user.user_id,
        details={"duration_ms": erasure.duration_ms, "rows": sum(erasure.rows.values())},
    )
    return AuthActionRead(status="deleted")


@router.post("/guest-upgrade", response_model=GuestUpgradeRead)
@limiter.limit(lambda: get_settings().guest_legacy_upgrade_rate_limit)
def upgrade_legacy_guest_session(
    request: Request,
    response: Response,
    payload: GuestUpgradeRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    # Called by the frontend server for a browser that still holds a legacy unsigned guest id.
    issued = upgrade_legacy_guest(db, settings, payload.legacy_guest_id, payload.legacy_csrf)
    record_security_event(
        "guest.legacy_upgrade",
        "denied" if issued is None else "success",
        connection=request,
        subject=payload.legacy_guest_id.strip().lower(),
    )
    if issued is None:
        return GuestUpgradeRead(upgraded=False)
    guest_token, csrf = issued
    return GuestUpgradeRead(upgraded=True, guest_token=guest_token, csrf=csrf)
