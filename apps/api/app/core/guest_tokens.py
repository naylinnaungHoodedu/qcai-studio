"""Keyed-MAC guest tokens (plan task 1.1, Decision D-09).

A token reads ``g1.<guest_id>.<issued_unix>.<hmac>``. The frontend server issues it with the shared
GUEST_TOKEN_SECRET and the API verifies it, so a guest id alone is no longer a credential. The CSRF
value is a second MAC over the same token, which binds it to that guest session.
The frontend's ``src/lib/guest-session.ts`` implements the same format; keep the two in step.
"""

from dataclasses import dataclass
import hashlib
import hmac
import re
import time

from app.core.config import Settings

GUEST_TOKEN_COOKIE = "qcai_guest_token"
GUEST_TOKEN_VERSION = "g1"
GUEST_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 365
GUEST_CSRF_LENGTH = 48
MIN_GUEST_TOKEN_SECRET_LENGTH = 32
_CLOCK_SKEW_SECONDS = 300
_GUEST_ID_PATTERN = re.compile(r"guest-[0-9a-f-]{8,64}")


@dataclass(frozen=True)
class GuestToken:
    guest_id: str
    issued_at: int
    csrf: str


def _mac(secret: str, purpose: str, guest_id: str, issued_at: int) -> str:
    message = f"{GUEST_TOKEN_VERSION}|{purpose}|{guest_id}|{issued_at}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _secrets(settings: Settings) -> list[str]:
    return [secret for secret in (settings.guest_token_secret, settings.guest_token_previous_secret) if secret]


def issue_guest_token(secret: str, guest_id: str, issued_at: int) -> str:
    return f"{GUEST_TOKEN_VERSION}.{guest_id}.{issued_at}.{_mac(secret, 'token', guest_id, issued_at)}"


def guest_csrf_for(secret: str, guest_id: str, issued_at: int) -> str:
    return _mac(secret, "csrf", guest_id, issued_at)[:GUEST_CSRF_LENGTH]


def verify_guest_token(token: str | None, settings: Settings, now: int | None = None) -> GuestToken | None:
    """Return the guest session for a well-formed, unexpired token signed with a configured key."""
    if not token:
        return None
    parts = token.strip().split(".")
    if len(parts) != 4 or parts[0] != GUEST_TOKEN_VERSION:
        return None
    _, guest_id, issued_text, mac = parts
    if not _GUEST_ID_PATTERN.fullmatch(guest_id) or not issued_text.isdigit():
        return None
    issued_at = int(issued_text)
    current = int(time.time()) if now is None else now
    if issued_at > current + _CLOCK_SKEW_SECONDS or current - issued_at > GUEST_TOKEN_MAX_AGE_SECONDS:
        return None
    # The previous secret stays valid during a key rotation; its CSRF values stay valid with it.
    for secret in _secrets(settings):
        if hmac.compare_digest(mac, _mac(secret, "token", guest_id, issued_at)):
            return GuestToken(guest_id=guest_id, issued_at=issued_at, csrf=guest_csrf_for(secret, guest_id, issued_at))
    return None


def require_guest_token_secret(settings: Settings) -> None:
    if settings.environment.lower() == "development":
        return
    if not settings.guest_token_secret or len(settings.guest_token_secret) < MIN_GUEST_TOKEN_SECRET_LENGTH:
        raise RuntimeError(
            f"GUEST_TOKEN_SECRET of at least {MIN_GUEST_TOKEN_SECRET_LENGTH} characters is required outside development."
        )
