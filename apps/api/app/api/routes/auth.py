from time import monotonic

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user, learner_write_observation, require_durable_learner, require_verified_principal
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.core.guest_tokens import GUEST_TOKEN_COOKIE
from app.core.request_protection import validate_request_origin
from app.schemas import (
    AuthActionRead,
    AuthSessionRead,
    GuestUpgradeRead,
    GuestUpgradeRequest,
    LocalAccountDeleteRead,
    LocalAccountDeleteRequest,
    LocalAccountLoginRequest,
    LocalAccountRegisterRequest,
    LearnerConsentUpdate,
    LearnerPrivacyErasureRequest,
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
    verify_password,
)
from app.services.guest_sessions import upgrade_legacy_guest
from app.services.learner_record_identity import claim_guest
from app.services.learner_record_privacy import CONSENT_VERSION, erase_subject_with_counts, iter_export, read_consent, set_consent
from app.db_models import UserAccount


router = APIRouter(prefix="/auth", tags=["auth"])


def require_privacy_enabled() -> None:
    if get_settings().learner_privacy != "on":
        raise HTTPException(404, "Not found.")


@router.get("/learner-consent", dependencies=[Depends(require_privacy_enabled)])
def get_learner_consent(user: AuthUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"consent_version": CONSENT_VERSION, "consent": read_consent(db, user.provider, user.user_id)}


@router.put("/learner-consent", dependencies=[Depends(require_privacy_enabled)])
def put_learner_consent(
    request: Request, payload: LearnerConsentUpdate, user: AuthUser = Depends(get_current_user), db: Session = Depends(get_db),
):
    states = set_consent(
        db, user.provider, user.user_id, payload.consent_class, payload.granted, get_settings(),
        observation=learner_write_observation(request),
    )
    db.commit()
    return {"consent_version": CONSENT_VERSION, "consent": states}


@router.get("/learner-export", dependencies=[Depends(require_privacy_enabled)])
def get_learner_export(
    request: Request, user: AuthUser = Depends(require_verified_principal), db: Session = Depends(get_db),
):
    record_security_event(
        "learner.export", "success", connection=request, actor_role=user.role, subject=user.user_id,
    )
    return StreamingResponse(
        iter_export(db, user.provider, user.user_id), media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "Content-Disposition": 'attachment; filename="learner-export.ndjson"'},
    )


@router.post("/learner-erasure", dependencies=[Depends(require_privacy_enabled)])
@limiter.limit(lambda: get_settings().auth_login_rate_limit)
def post_learner_erasure(
    request: Request, payload: LearnerPrivacyErasureRequest, response: Response,
    user: AuthUser = Depends(require_verified_principal), db: Session = Depends(get_db),
):
    settings = get_settings()
    validate_request_origin(request, settings)
    if user.provider == "local":
        account = db.get(UserAccount, user.user_id)
        if account is None or not payload.password or not verify_password(payload.password, account.password_hash):
            db.rollback()
            record_security_event("learner.erasure", "failure", connection=request, actor_role=user.role,
                                  subject=user.user_id, details={"status": 401})
            raise HTTPException(401, "Password confirmation failed.")
    started = monotonic()
    receipt, counts = erase_subject_with_counts(db, user.provider, user.user_id, settings)
    db.commit()
    record_security_event("learner.erasure", "success", connection=request, actor_role=user.role,
                          subject=user.user_id, details={"rows": sum(counts.values()), "duration_ms": round((monotonic() - started) * 1000)})
    _clear_auth_cookies(response)
    response.delete_cookie(GUEST_TOKEN_COOKIE, path="/")
    response.headers["Cache-Control"] = "no-store"
    return receipt


def require_identity_enabled() -> None:
    if get_settings().learner_identity != "on":
        raise HTTPException(404, "Not found.")


@router.post("/guest-claim", response_model=AuthActionRead, dependencies=[Depends(require_identity_enabled)])
@limiter.limit(lambda: get_settings().guest_legacy_upgrade_rate_limit)
def claim_guest_record(
    request: Request,
    response: Response,
    user: AuthUser = Depends(require_durable_learner),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    validate_request_origin(request, settings)
    try:
        moved = claim_guest(
            db, user.provider, user.user_id, request.cookies.get(GUEST_TOKEN_COOKIE),
            request.headers.get("x-guest-claim-csrf"), settings, verify_account=True,
            observation=learner_write_observation(request),
        )
        db.commit()
    except HTTPException:
        db.rollback()
        record_security_event("subject.claim_refused", "denied", connection=request, actor_role=user.role)
        raise
    record_security_event(
        "subject.claimed", "success", connection=request, actor_role=user.role,
        details={"rows": sum(moved.values())},
    )
    response.delete_cookie(GUEST_TOKEN_COOKIE, path="/")
    return AuthActionRead(status="claimed")


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


@router.delete("/account", response_model=LocalAccountDeleteRead, response_model_exclude_none=True)
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
    if erasure.receipt is not None:
        response.headers["Cache-Control"] = "no-store"
    return LocalAccountDeleteRead(status="deleted", receipt=erasure.receipt)


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
