"""Who is calling, as far as the API can trust it (plan task 1.6, E-39).

Rate limits and security events need a key the client cannot choose. A validated principal is one (see
`app.core.auth`). For an anonymous request it is the client's network address, taken only from a source
the API trusts:

1. the frontend server's vouched header: the address it saw, with a MAC made with the shared
   GUEST_TOKEN_SECRET (the browser's own calls reach the API through that server); otherwise
2. the X-Forwarded-For entry appended by the platform's own front end, counted CLIENT_ADDRESS_HOPS from
   the right. Entries further left are whatever the client sent, and are never used.
"""

import hashlib
import hmac

from starlette.requests import HTTPConnection

from app.core.config import get_settings

CLIENT_ADDRESS_HEADER = "x-qcai-client-address"
_CLIENT_ADDRESS_MAC_LENGTH = 32
_MAX_ADDRESS_LENGTH = 64


def keyed_digest(value: str, purpose: str) -> str:
    """A pseudonym for an id or address: stable while the key is, and not reversible without it."""
    key = (get_settings().guest_token_secret or "").encode("utf-8")
    return hmac.new(key, f"security-log|{purpose}|{value}".encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def client_address_mac(secret: str, address: str) -> str:
    message = f"c1|client-address|{address}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()[:_CLIENT_ADDRESS_MAC_LENGTH]


def vouched_client_address(header_value: str | None) -> str | None:
    """The address in the frontend server's header, if its MAC verifies with a configured key."""
    if not header_value:
        return None
    address, _, mac = header_value.strip().rpartition(" ")
    if not address or len(address) > _MAX_ADDRESS_LENGTH or len(mac) != _CLIENT_ADDRESS_MAC_LENGTH:
        return None
    settings = get_settings()
    keys = [key for key in (settings.guest_token_secret, settings.guest_token_previous_secret) if key]
    if any(hmac.compare_digest(mac, client_address_mac(key, address)) for key in keys):
        return address
    return None


def client_address(connection: HTTPConnection) -> str:
    vouched = vouched_client_address(connection.headers.get(CLIENT_ADDRESS_HEADER))
    if vouched:
        return vouched
    hops = max(1, get_settings().client_address_hops)
    entries = [entry.strip() for entry in connection.headers.get("x-forwarded-for", "").split(",") if entry.strip()]
    if len(entries) >= hops:
        return entries[-hops][:_MAX_ADDRESS_LENGTH]
    return connection.client.host if connection.client else "unknown"
