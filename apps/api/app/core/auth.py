from dataclasses import dataclass

import jwt
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from jwt import PyJWKClient
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.client_identity import AUTH0_LEGACY_FALLBACK, is_legacy_auth0_fallback
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.guest_tokens import GUEST_TOKEN_COOKIE, verify_guest_token
from app.db_models import LearnerSubject, UserAccount
from app.services.guest_sessions import is_guest_revoked
from app.services.learner_record_identity import principal_digest
from app.services.learner_record_lock import WriteObservation, guard_request_writes, learner_writer, phase8_writes_enabled
from app.services.local_accounts import AUTH_SESSION_COOKIE_NAME, resolve_local_account_from_session
from app.services.security_log import record_security_event, route_template


@dataclass
class AuthUser:
    user_id: str
    email: str | None
    role: str
    provider: str = "guest"


class _Auth0WithoutSubject(AuthUser):
    """A legacy fallback principal without a subject claim from the issuer."""


_EXPLICIT_PRIVACY_LOCKS = {
    ("POST", "/auth/learner-erasure"), ("DELETE", "/auth/account"), ("POST", "/auth/guest-claim"),
}


def learner_write_observation(request: Request) -> WriteObservation | None:
    return getattr(request.state, "learner_write_observation", None)


def demo_principal_allowed(db: Session, identifier: str, settings: Settings) -> bool:
    if not phase8_writes_enabled(settings):
        return True
    if identifier.startswith(("acct-", "guest-", "subj-")) or "|" in identifier:
        return False
    if db.get(UserAccount, identifier) is not None:
        return False
    binding = select(LearnerSubject.principal_digest).where(or_(
        LearnerSubject.user_id == identifier,
        LearnerSubject.principal_digest == principal_digest("auth0", identifier),
    ))
    return db.scalar(binding.limit(1)) is None


def _decode_auth0_token(token: str, settings: Settings) -> AuthUser:
    if not settings.auth0_domain or not settings.auth0_audience:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Auth0 is not configured.")

    jwks_url = f"https://{settings.auth0_domain}/.well-known/jwks.json"
    try:
        signing_key = PyJWKClient(jwks_url).get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.auth0_audience,
            issuer=f"https://{settings.auth0_domain}/",
        )
    except jwt.PyJWKClientConnectionError:
        # Auth0's keys could not be fetched: an outage on our side, not a bad credential. Left to the server-error
        # handler, which logs it, so it is not counted as a credential rejection.
        raise
    except jwt.PyJWTError as exc:
        # A malformed, expired or wrongly signed token: a refusal, not a 500.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token.") from exc
    roles = payload.get("https://qcai.dev/roles") or payload.get("roles") or ["learner"]
    subject = payload.get("sub")
    has_subject = isinstance(subject, str) and not is_legacy_auth0_fallback(subject)
    if settings.learner_identity == "on" and not has_subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token.")
    principal_type = AuthUser if has_subject else _Auth0WithoutSubject
    return principal_type(
        user_id=payload.get("sub", AUTH0_LEGACY_FALLBACK),
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
    if user.provider == "demo" and not demo_principal_allowed(db, user.user_id, settings):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A verified session is required.")
    # The rate limiter keys on this validated principal, never on a client header (task 1.6).
    request.state.principal = user
    if user.provider != "demo" and has_bearer_subject(user) and phase8_writes_enabled(settings):
        writer = learner_writer(db, user.provider, user.user_id)
        request.state.learner_write_observation = writer.observation
        if (request.method, route_template(request)) not in _EXPLICIT_PRIVACY_LOCKS:
            guard_request_writes(db, writer)
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


def has_bearer_subject(user: AuthUser) -> bool:
    """Allow non-bearer identities and tokens with a subject to enter Phase 8."""
    return not isinstance(user, _Auth0WithoutSubject)


def require_bearer_subject(user: AuthUser) -> None:
    """Reject an Auth0 credential that lacks a verified, nonblank subject."""
    if not has_bearer_subject(user):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="A bearer subject is required.")


def require_verified_principal(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    """Require an authenticated account or signed guest credential for privacy operations."""
    require_bearer_subject(user)
    if user.provider not in {"local", "auth0", "guest"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A verified session is required.")
    return user
