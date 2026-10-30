"""Short-lived keyed-MAC tickets that carry a validated principal into the Arena socket (plan task 1.4).

The browser opens the socket on the API host directly. The frontend's session cookies are host-only on
the frontend, so they never reach that socket. The browser therefore first asks the API, through the
frontend proxy, for a ticket bound to the principal that ``get_current_user`` resolved. It offers the
ticket as a WebSocket subprotocol, which keeps it out of URLs and access logs.

A ticket reads ``at1.<b64url user_id>.<provider>.<expires_unix>.<nonce>.<hmac>``. It lasts
ARENA_TICKET_TTL_SECONDS and is redeemed at most once per API instance.
"""

import base64
import binascii
from dataclasses import dataclass
import hashlib
import hmac
import re
import secrets
import threading
import time

from app.core.config import Settings

ARENA_PROTOCOL = "qcai-arena.v1"
ARENA_TICKET_VERSION = "at1"
ARENA_TICKET_TTL_SECONDS = 30
_MAX_TICKET_LENGTH = 512
_PROVIDERS = {"auth0", "demo", "guest", "local"}
_NONCE_PATTERN = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class ArenaTicket:
    user_id: str
    provider: str
    expires_at: int
    nonce: str


def _encode_user_id(user_id: str) -> str:
    return base64.urlsafe_b64encode(user_id.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_user_id(value: str) -> str | None:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None


def _mac(secret: str, encoded_user_id: str, provider: str, expires_at: int, nonce: str) -> str:
    message = f"{ARENA_TICKET_VERSION}|arena-ticket|{encoded_user_id}|{provider}|{expires_at}|{nonce}"
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def issue_arena_ticket(secret: str, user_id: str, provider: str, now: int | None = None) -> tuple[str, int]:
    """Return a ticket for this principal and the unix time it expires."""
    if provider not in _PROVIDERS:
        raise ValueError(f"Unknown principal provider: {provider}")
    expires_at = (int(time.time()) if now is None else now) + ARENA_TICKET_TTL_SECONDS
    encoded = _encode_user_id(user_id)
    nonce = secrets.token_hex(16)
    mac = _mac(secret, encoded, provider, expires_at, nonce)
    return f"{ARENA_TICKET_VERSION}.{encoded}.{provider}.{expires_at}.{nonce}.{mac}", expires_at


def verify_arena_ticket(ticket: str | None, settings: Settings, now: int | None = None) -> ArenaTicket | None:
    """Return the principal of a well-formed, unexpired ticket signed with a configured key."""
    if not ticket or len(ticket) > _MAX_TICKET_LENGTH:
        return None
    parts = ticket.split(".")
    if len(parts) != 6 or parts[0] != ARENA_TICKET_VERSION:
        return None
    _, encoded, provider, expires_text, nonce, mac = parts
    if provider not in _PROVIDERS or not expires_text.isdigit() or not _NONCE_PATTERN.fullmatch(nonce):
        return None
    expires_at = int(expires_text)
    current = int(time.time()) if now is None else now
    # Expired, or further ahead than any ticket this API issues.
    if current > expires_at or expires_at - current > ARENA_TICKET_TTL_SECONDS:
        return None
    keys = [key for key in (settings.guest_token_secret, settings.guest_token_previous_secret) if key]
    if not any(hmac.compare_digest(mac, _mac(key, encoded, provider, expires_at, nonce)) for key in keys):
        return None
    user_id = _decode_user_id(encoded)
    if not user_id:
        return None
    return ArenaTicket(user_id=user_id, provider=provider, expires_at=expires_at, nonce=nonce)


class _RedeemedNonces:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._expiry_by_nonce: dict[str, int] = {}

    def claim(self, nonce: str, expires_at: int, now: int) -> bool:
        with self._lock:
            self._expiry_by_nonce = {key: expiry for key, expiry in self._expiry_by_nonce.items() if expiry >= now}
            if nonce in self._expiry_by_nonce:
                return False
            self._expiry_by_nonce[nonce] = expires_at
            return True


_redeemed = _RedeemedNonces()


def redeem_arena_ticket(ticket: str | None, settings: Settings, now: int | None = None) -> ArenaTicket | None:
    """Verify a ticket and spend it, so a copied ticket cannot open a second socket on this instance."""
    current = int(time.time()) if now is None else now
    verified = verify_arena_ticket(ticket, settings, now=current)
    if verified is None or not _redeemed.claim(verified.nonce, verified.expires_at, current):
        return None
    return verified
