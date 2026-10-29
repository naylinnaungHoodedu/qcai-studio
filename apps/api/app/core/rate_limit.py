import hashlib

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings
from app.core.guest_tokens import GUEST_TOKEN_COOKIE, verify_guest_token


def build_rate_limit_key(request: Request) -> str:
    authorization = request.headers.get("authorization")
    if authorization and authorization.lower().startswith("bearer "):
        token_fingerprint = hashlib.sha256(authorization.encode("utf-8")).hexdigest()[:24]
        return f"auth:{token_fingerprint}"

    demo_user = request.headers.get("x-demo-user")
    if demo_user:
        return f"demo:{demo_user.strip().lower()}"

    guest = verify_guest_token(request.cookies.get(GUEST_TOKEN_COOKIE), get_settings())
    if guest:
        return f"guest:{guest.guest_id}"

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return f"ip:{forwarded_for.split(',')[0].strip()}"

    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=build_rate_limit_key, headers_enabled=True)
