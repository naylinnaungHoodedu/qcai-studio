from collections import deque
import threading
import time

from fastapi import Request
from slowapi import Limiter

from app.core.client_identity import client_address
from app.core.config import get_settings
from app.core.rate_limit_storage import DATABASE_STORAGE_URI


def build_rate_limit_key(request: Request) -> str:
    """The validated principal, or the trusted client address; never a header the client chose (E-39).

    The limiter runs inside the endpoint, after its dependencies, so a route that authenticates has
    already stored its principal on the request (`app.core.auth.get_current_user`).
    """
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        return f"{principal.provider}:{principal.user_id}"
    return f"ip:{client_address(request)}"


limiter = Limiter(
    key_func=build_rate_limit_key,
    headers_enabled=True,
    storage_uri=DATABASE_STORAGE_URI if get_settings().rate_limit_storage == "database" else "memory://",
)


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
