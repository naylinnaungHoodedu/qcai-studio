from dataclasses import dataclass

import jwt
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from jwt import PyJWKClient
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.guest_tokens import GUEST_TOKEN_COOKIE, verify_guest_token
from app.services.guest_sessions import is_guest_revoked
from app.services.local_accounts import AUTH_SESSION_COOKIE_NAME, resolve_local_account_from_session
from app.services.security_log import record_security_event, route_template


@dataclass
class AuthUser:
    user_id: str
    email: str | None
    role: str
    provider: str = "guest"


def _decode_auth0_token(token: str, settings: Settings) -> AuthUser:
    if not settings.auth0_domain or not settings.auth0_audience:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Auth0 is not configured.")

    jwks_url = f"https://{settings.auth0_domain}/.well-known/jwks.json"
    signing_key = PyJWKClient(jwks_url).get_signing_key_from_jwt(token)
    payload = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.auth0_audience,
        issuer=f"https://{settings.auth0_domain}/",
    )
    roles = payload.get("https://qcai.dev/roles") or payload.get("roles") or ["learner"]
    return AuthUser(
        user_id=payload.get("sub", "unknown"),
        email=payload.get("email"),
        role=roles[0] if roles else "learner",
        provider="auth0",
    )


def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    x_demo_user: str | None = Header(default=None),
    x_demo_role: str | None = Header(default=None),
    qcai_session_token: str | None = Cookie(default=None, alias=AUTH_SESSION_COOKIE_NAME),
    qcai_guest_token: str | None = Cookie(default=None, alias=GUEST_TOKEN_COOKIE),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> AuthUser:
    user = _authenticate(
        request, authorization, x_demo_user, x_demo_role, qcai_session_token, qcai_guest_token, settings, db
    )
    # The rate limiter keys on this validated principal, never on a client header (task 1.6).
    request.state.principal = user
    return user


def _authenticate(
    request: Request,
    authorization: str | None,
    x_demo_user: str | None,
    x_demo_role: str | None,
    qcai_session_token: str | None,
    qcai_guest_token: str | None,
    settings: Settings,
    db: Session,
) -> AuthUser:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            return _decode_auth0_token(token, settings)
        except HTTPException:
            record_security_event(
                "auth.credential_rejected", "denied", connection=request, details={"credential": "bearer"}
            )
            raise

    local_account = resolve_local_account_from_session(db, qcai_session_token)
    if local_account:
        return AuthUser(
            user_id=local_account.user_id,
            email=local_account.email,
            role=local_account.role,
            provider="local",
        )

    if settings.enable_demo_auth and (x_demo_user or x_demo_role):
        return AuthUser(
            user_id=x_demo_user or "demo-learner",
            email="demo@qcai.local",
            role=(x_demo_role or "learner").lower(),
            provider="demo",
        )

    if qcai_guest_token:
        # A presented guest credential must verify; it never falls through to another identity (AC-1-1).
        guest = verify_guest_token(qcai_guest_token, settings)
        if guest is None:
            record_security_event(
                "auth.credential_rejected",
                "denied",
                connection=request,
                details={"credential": "guest_token", "reason": "invalid"},
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid guest session.")
        if is_guest_revoked(db, guest.guest_id):
            record_security_event(
                "auth.credential_rejected",
                "denied",
                connection=request,
                subject=guest.guest_id,
                details={"credential": "guest_token", "reason": "revoked"},
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Guest session revoked.")
        return AuthUser(user_id=guest.guest_id, email=None, role="learner", provider="guest")

    if settings.enable_demo_auth:
        return AuthUser(user_id="demo-learner", email="demo@qcai.local", role="learner", provider="demo")

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")


def _record_denial(request: Request, user: AuthUser, required: str) -> None:
    record_security_event(
        "authz.denied",
        "denied",
        connection=request,
        actor_role=user.role,
        subject=user.user_id,
        details={"route": route_template(request), "required": required, "provider": user.provider},
    )


def require_role(*allowed_roles: str):
    def dependency(request: Request, user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if user.role not in allowed_roles:
            _record_denial(request, user, "role:" + "|".join(sorted(allowed_roles)))
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' cannot access this resource.",
            )
        return user

    # Read by the authorization matrix (app.core.authorization) to check each route against its policy.
    dependency.allowed_roles = frozenset(allowed_roles)
    return dependency


def require_durable_learner(request: Request, user: AuthUser = Depends(get_current_user)) -> AuthUser:
    """Reject browser-only guest/demo identities from the cross-device record boundary."""
    if user.provider in {"guest", "demo"}:
        _record_denial(request, user, "durable_learner")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A signed-in durable account is required for the Learner Record.",
        )
    if user.role not in {"learner", "admin"}:
        _record_denial(request, user, "role:admin|learner")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Learner role is required.")
    return user
