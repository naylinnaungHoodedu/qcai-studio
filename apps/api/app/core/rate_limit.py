import hashlib

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def build_rate_limit_key(request: Request) -> str:
    authorization = request.headers.get("authorization")
    if authorization and authorization.lower().startswith("bearer "):
        token_fingerprint = hashlib.sha256(authorization.encode("utf-8")).hexdigest()[:24]
        return f"auth:{token_fingerprint}"

    demo_user = request.headers.get("x-demo-user")
    if demo_user:
        return f"demo:{demo_user.strip().lower()}"

    guest_user = request.cookies.get("qcai_guest_id")
    if guest_user:
        return f"guest:{guest_user.strip().lower()}"

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return f"ip:{forwarded_for.split(',')[0].strip()}"

    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=build_rate_limit_key, headers_enabled=True)
