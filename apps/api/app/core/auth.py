from dataclasses import dataclass
import re

import jwt
from fastapi import Cookie, Depends, Header, HTTPException, status
from jwt import PyJWKClient
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.services.local_accounts import AUTH_SESSION_COOKIE_NAME, resolve_local_account_from_session


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
    authorization: str | None = Header(default=None),
    x_demo_user: str | None = Header(default=None),
    x_demo_role: str | None = Header(default=None),
    qcai_session_token: str | None = Cookie(default=None, alias=AUTH_SESSION_COOKIE_NAME),
    qcai_guest_id: str | None = Cookie(default=None),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> AuthUser:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        return _decode_auth0_token(token, settings)

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

    if qcai_guest_id:
        guest_id = qcai_guest_id.strip().lower()
        if re.fullmatch(r"guest-[0-9a-f-]{8,64}", guest_id):
            return AuthUser(user_id=guest_id, email=None, role="learner", provider="guest")

    if settings.enable_demo_auth:
        return AuthUser(user_id="demo-learner", email="demo@qcai.local", role="learner", provider="demo")

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")


def require_role(*allowed_roles: str):
    def dependency(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' cannot access this resource.",
            )
        return user

    return dependency
