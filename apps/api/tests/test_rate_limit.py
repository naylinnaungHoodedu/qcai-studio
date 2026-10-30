"""Rate limits keyed on the validated principal, a shared database store, and the sign-in lockout (task 1.6)."""

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from starlette.requests import Request

from app.api.routes import arena
from app.core.client_identity import CLIENT_ADDRESS_HEADER, client_address, keyed_digest, vouched_client_address
from app.core.config import DEVELOPMENT_GUEST_TOKEN_SECRET, Settings, get_settings
from app.core.db import SessionLocal
from app.core.guest_tokens import GUEST_TOKEN_COOKIE, guest_csrf_for, issue_guest_token
from app.core.rate_limit import build_rate_limit_key
from app.core import rate_limit_storage
from app.core.rate_limit_storage import DatabaseStorage
from app.db_models import RateLimitCounter, SecurityEvent
from app.main import app

API_ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "S3cureQuantumPath"
TRUSTED_ORIGIN = "http://localhost:3000"
client = TestClient(app)
# The same vectors are checked by the frontend (apps/frontend/tests/client-address.integration.test.ts).
VOUCHED_VECTORS = [
    ("198.51.100.7", "198.51.100.7 b73c021526b8923cad3bbc5d977de632"),
    ("2001:db8::7", "2001:db8::7 62d6fe6ce7efe95fe3c51eec7b70e967"),
]


def _address() -> str:
    return f"198.51.100.{uuid4().hex[:8]}"


def _request(headers: dict[str, str], principal=None, host: str = "10.9.8.7") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(name.lower().encode(), value.encode()) for name, value in headers.items()],
        "client": (host, 50000),
    }
    request = Request(scope)
    if principal is not None:
        request.state.principal = principal
    return request


# --- Keys ---


def test_an_anonymous_key_ignores_every_header_the_client_chooses():
    base = {"x-forwarded-for": "203.0.113.1, 198.51.100.20"}
    variants = [
        base,
        {**base, "x-demo-user": "someone-else"},
        {**base, "authorization": "Bearer made-up-token"},
        {"x-forwarded-for": "forged-1, forged-2, 198.51.100.20"},
    ]

    assert {build_rate_limit_key(_request(headers)) for headers in variants} == {"ip:198.51.100.20"}


def test_an_authenticated_key_is_the_validated_principal():
    principal = SimpleNamespace(provider="guest", user_id="guest-0123456789abcdef")
    keys = {
        build_rate_limit_key(_request({"x-forwarded-for": address, "x-demo-user": address}, principal))
        for address in ("198.51.100.1", "198.51.100.2")
    }

    assert keys == {"guest:guest-0123456789abcdef"}


@pytest.mark.parametrize(("address", "header"), VOUCHED_VECTORS)
def test_a_vouched_address_verifies_with_the_shared_vector(address, header):
    assert vouched_client_address(header) == address
    assert client_address(_request({CLIENT_ADDRESS_HEADER: header, "x-forwarded-for": "198.51.100.99"})) == address


def test_a_forged_or_malformed_vouched_address_is_ignored():
    forged = "198.51.100.7 " + "0" * 32
    for header in (forged, "198.51.100.7", "198.51.100.7 short", " " + "a" * 32):
        assert vouched_client_address(header) is None
        assert client_address(_request({CLIENT_ADDRESS_HEADER: header, "x-forwarded-for": "198.51.100.99"})) == "198.51.100.99"


def test_the_trusted_hop_count_picks_the_entry_from_the_right(monkeypatch):
    monkeypatch.setattr("app.core.client_identity.get_settings", lambda: Settings(environment="development", client_address_hops=2))
    request = _request({"x-forwarded-for": "forged, 198.51.100.30, 10.0.0.2"})

    assert client_address(request) == "198.51.100.30"
    assert client_address(_request({"x-forwarded-for": "10.0.0.2"})) == "10.9.8.7"


# --- Limits in the running app ---


def _guest() -> tuple[TestClient, dict[str, str]]:
    guest_id = f"guest-{uuid4().hex}"
    issued = int(time.time())
    browser = TestClient(app)
    browser.cookies.set(GUEST_TOKEN_COOKIE, issue_guest_token(DEVELOPMENT_GUEST_TOKEN_SECRET, guest_id, issued))
    return browser, {"origin": TRUSTED_ORIGIN, "x-qcai-csrf": guest_csrf_for(DEVELOPMENT_GUEST_TOKEN_SECRET, guest_id, issued)}


def test_an_authenticated_limit_follows_the_principal_across_addresses(monkeypatch):
    enabled = Settings(environment="development", arena_enabled=True, allowed_origins=[TRUSTED_ORIGIN])
    monkeypatch.setattr(arena, "get_settings", lambda: enabled)
    limit = int(get_settings().arena_ticket_rate_limit.split("/")[0])
    browser, headers = _guest()

    statuses = [
        browser.post("/arena/ticket", headers={**headers, "x-forwarded-for": _address()}).status_code
        for _ in range(limit + 1)
    ]
    other, other_headers = _guest()

    assert statuses == [200] * limit + [429]
    assert other.post("/arena/ticket", headers=other_headers).status_code == 200


def test_the_limiter_stores_digests_not_keys():
    address = _address()
    client.get("/search", params={"query": "routing"}, headers={"x-forwarded-for": address})

    with SessionLocal() as db:
        keys = list(db.scalars(select(RateLimitCounter.key)))
    assert keys and all(len(key) == 32 for key in keys)
    assert not any(address in key for key in keys)


# --- The database store itself ---


class _Clock:
    def __init__(self) -> None:
        self.now = time.time()

    def time(self) -> float:
        return self.now


def test_database_storage_counts_per_window_and_restarts_after_it(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(rate_limit_storage, "time", clock)
    storage = DatabaseStorage("qcai-database://")
    key = f"test/{uuid4().hex}"

    assert [storage.incr(key, 60) for _ in range(3)] == [1, 2, 3]
    assert storage.get(key) == 3
    assert storage.get_expiry(key) == pytest.approx(clock.now + 60)
    clock.now += 61
    assert storage.get(key) == 0
    assert storage.incr(key, 60) == 1
    storage.clear(key)
    assert storage.get(key) == 0
    assert storage.check() is True


# --- Sign-in lockout ---


def _account() -> tuple[str, dict[str, str]]:
    email = f"lockout-{uuid4().hex[:8]}@example.com"
    response = TestClient(app).post("/auth/register", json={"email": email, "password": PASSWORD}, headers={"x-forwarded-for": _address()})
    assert response.status_code == 201
    return email, {"x-forwarded-for": _address()}


def _sign_in(email: str, password: str) -> httpx.Response:
    # A fresh address each time: the per-address limiter must not be what refuses these.
    return TestClient(app).post("/auth/login", json={"email": email, "password": password}, headers={"x-forwarded-for": _address()})


def test_repeated_failures_lock_the_email_even_for_the_right_password():
    email, _ = _account()
    failures = get_settings().auth_lockout_failures
    with SessionLocal() as db:
        start = db.scalar(select(SecurityEvent.seq).order_by(SecurityEvent.seq.desc()).limit(1)) or 0

    statuses = [_sign_in(email, "wrong-password-123").status_code for _ in range(failures)]
    locked = _sign_in(email, PASSWORD)

    assert statuses == [401] * failures
    assert locked.status_code == 429
    assert 0 < int(locked.headers["retry-after"]) <= get_settings().auth_lockout_window_seconds
    with SessionLocal() as db:
        lockouts = list(
            db.scalars(select(SecurityEvent).where(SecurityEvent.seq > start, SecurityEvent.event_type == "auth.lockout"))
        )
    assert [event.outcome for event in lockouts] == ["warning", "denied"]
    assert all(email not in str(event.details) for event in lockouts)


def test_a_lockout_is_per_email_and_ends_with_its_window():
    email, _ = _account()
    other, _ = _account()
    for _ in range(get_settings().auth_lockout_failures):
        _sign_in(email, "wrong-password-123")

    assert _sign_in(other, PASSWORD).status_code == 200
    assert _sign_in(email, PASSWORD).status_code == 429
    with SessionLocal() as db:
        db.execute(update(RateLimitCounter).where(RateLimitCounter.key == keyed_digest(f"sign-in-lockout/{email}", "rate-limit")).values(expires_at=time.time() - 1))
        db.commit()
    assert _sign_in(email, PASSWORD).status_code == 200


def test_a_successful_sign_in_clears_earlier_failures():
    email, _ = _account()
    below = get_settings().auth_lockout_failures - 1
    for _ in range(below):
        _sign_in(email, "wrong-password-123")
    assert _sign_in(email, PASSWORD).status_code == 200
    statuses = [_sign_in(email, "wrong-password-123").status_code for _ in range(below)]

    assert statuses == [401] * below
    assert _sign_in(email, PASSWORD).status_code == 200


# --- Two API instances, one database (the plan's multi-instance test, L1987) ---


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _stop(process: subprocess.Popen) -> None:
    if sys.platform == "win32":
        # A virtualenv's python.exe starts a child interpreter, so stop the whole tree.
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
    else:
        process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()


@contextmanager
def _instance(database_url: str, storage: str) -> Iterator[str]:
    port = _free_port()
    env = {**os.environ, "DATABASE_URL": database_url, "ENVIRONMENT": "development", "RATE_LIMIT_STORAGE": storage, "PYTHONUNBUFFERED": "1"}
    env.pop("TEST_DATABASE_URL", None)
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=API_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 90
        while True:
            try:
                if httpx.get(f"{base}/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("The API instance did not start.")
            time.sleep(0.3)
        yield base
    finally:
        _stop(process)


def _alternate_sign_ins(first: str, second: str, attempts: int, address: str) -> list[int]:
    # Unknown emails, so only the per-address limiter can refuse; the instances take turns.
    return [
        httpx.post(
            f"{(first, second)[index % 2]}/auth/login",
            json={"email": f"nobody-{uuid4().hex[:8]}@example.com", "password": "wrong-password-123"},
            headers={"x-forwarded-for": address},
            timeout=20,
        ).status_code
        for index in range(attempts)
    ]


@pytest.mark.parametrize("storage", ["database", "memory"])
def test_a_limit_holds_across_two_api_instances_only_with_the_shared_store(fresh_database_url, storage):
    limit = int(get_settings().auth_login_rate_limit.split("/")[0])
    with _instance(fresh_database_url, storage) as first, _instance(fresh_database_url, storage) as second:
        statuses = _alternate_sign_ins(first, second, limit + 2, _address())

    if storage == "database":
        assert statuses == [401] * limit + [429, 429]
    else:
        # The rollback setting: each instance counts alone, so neither reaches the limit.
        assert statuses == [401] * (limit + 2)


def test_a_lockout_holds_across_two_api_instances(fresh_database_url):
    email = f"lockout-{uuid4().hex[:8]}@example.com"
    failures = get_settings().auth_lockout_failures
    with _instance(fresh_database_url, "database") as first, _instance(fresh_database_url, "database") as second:
        bases = (first, second)
        assert httpx.post(f"{first}/auth/register", json={"email": email, "password": PASSWORD}, headers={"x-forwarded-for": _address()}, timeout=20).status_code == 201
        statuses = [
            httpx.post(f"{bases[index % 2]}/auth/login", json={"email": email, "password": "wrong-password-123"}, headers={"x-forwarded-for": _address()}, timeout=20).status_code
            for index in range(failures)
        ]
        locked = [
            httpx.post(f"{base}/auth/login", json={"email": email, "password": PASSWORD}, headers={"x-forwarded-for": _address()}, timeout=20).status_code
            for base in bases
        ]

    assert statuses == [401] * failures
    assert locked == [429, 429]
