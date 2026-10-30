from collections import deque
import hashlib
import threading
import time

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


class SlidingWindowLimiter:
    """At most ``limit`` events per key in any ``window_seconds``, counted in this process.

    The Arena socket uses it for per-principal limits (task 1.4), as its matches also live in one
    process; task 1.6 moves the HTTP limits to a shared store.
    """

    _SWEEP_ABOVE_KEYS = 10_000

    def __init__(self, limit: int, window_seconds: float):
        self._limit = limit
        self._window = window_seconds
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        with self._lock:
            if len(self._events) > self._SWEEP_ABOVE_KEYS:
                self._events = {k: v for k, v in self._events.items() if v and current - v[-1] < self._window}
            events = self._events.setdefault(key, deque())
            while events and current - events[0] >= self._window:
                events.popleft()
            if len(events) >= self._limit:
                return False
            events.append(current)
            return True
