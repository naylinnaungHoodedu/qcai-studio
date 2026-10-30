"""Sign-in lockout (plan task 1.6): repeated failed sign-ins for one email lock it for the rest of the window.

Failures are counted per email, not per address, so spreading guesses across addresses does not help. The
count lives in the rate-limit store, so with the database store it holds across API instances. While an
email is locked even the right password is refused. The accepted cost: anyone who knows an email can lock
it for one window at a time.
"""

from functools import lru_cache
import time

from limits.storage import Storage, storage_from_string

from app.core.config import get_settings
from app.core.rate_limit_storage import DATABASE_STORAGE_URI


@lru_cache
def _storage(mode: str) -> Storage:
    return storage_from_string(DATABASE_STORAGE_URI if mode == "database" else "memory://")


def _store() -> Storage:
    return _storage(get_settings().rate_limit_storage)


def _key(email: str) -> str:
    # The database store keeps only a keyed digest of this key.
    return f"sign-in-lockout/{email.strip().lower()}"


def seconds_locked(email: str) -> int:
    """How long this email stays locked; 0 if it is not locked."""
    settings = get_settings()
    store = _store()
    if store.get(_key(email)) < settings.auth_lockout_failures:
        return 0
    return max(1, int(store.get_expiry(_key(email)) - time.time()))


def register_failure(email: str) -> int:
    """Count one failed sign-in and return the failures in the current window."""
    return _store().incr(_key(email), get_settings().auth_lockout_window_seconds)


def clear(email: str) -> None:
    _store().clear(_key(email))
