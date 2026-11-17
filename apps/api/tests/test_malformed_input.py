"""Malformed client input is refused with 4xx, never HTTP 500 (Release R1.1; AC-1-1 "returns 401").

The R1 production check sent two malformed guest cookies to /auth/me and got 500: an issue time of 5000 digits
(int() refuses more than 4300) and a non-ASCII MAC (hmac.compare_digest refuses non-ASCII str). A sweep then
found the same class at every place that parses or compares a client-supplied credential, in Origin parsing,
in FastAPI's 422 renderer and in learner-record values. One test per call site; unit tests per input class.

Starlette's TestClient re-encodes header text as UTF-8, so a raw latin-1 byte such as 0xB2 ("²") cannot be
sent through it; those inputs are checked by calling the verifiers directly.
"""

import json
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.arena_tickets import issue_arena_ticket, verify_arena_ticket
from app.core.client_identity import CLIENT_ADDRESS_HEADER, client_address_mac, vouched_client_address
from app.core.config import DEVELOPMENT_GUEST_TOKEN_SECRET, Settings, get_settings
from app.core.guest_tokens import GUEST_TOKEN_COOKIE, guest_csrf_for, issue_guest_token, verify_guest_token
from app.core.safe_input import parse_unix_time, text_matches
from app.main import app

TRUSTED_ORIGIN = "http://localhost:3000"
SETTINGS = Settings(environment="development", guest_token_secret=DEVELOPMENT_GUEST_TOKEN_SECRET)
GUEST_ID = "guest-0123456789abcdef"
NOW = 1_800_000_000
MALFORMED_TIMES = ["1" * 5000, "1" * 4301, "²", "١٢٣", "0" + str(NOW), "", "-1", "1e9", " 1"]
NON_ASCII_MAC = "é" * 64


def _short_id(value: str) -> str:
    return f"{len(value)} chars" if len(value) > 24 else repr(value)


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _source() -> dict[str, str]:
    # A distinct client address keeps the per-address rate limits of separate tests apart.
    return {"x-forwarded-for": f"203.0.113.{uuid4().int % 250 + 1}"}


def _raw(value: str) -> bytes:
    # A header value as the bytes a client sends; the server decodes headers as latin-1.
    return value.encode("latin-1")


def _valid_guest() -> tuple[str, str]:
    guest_id, issued = f"guest-{uuid4().hex}", int(time.time())
    return (
        issue_guest_token(DEVELOPMENT_GUEST_TOKEN_SECRET, guest_id, issued),
        guest_csrf_for(DEVELOPMENT_GUEST_TOKEN_SECRET, guest_id, issued),
    )


# --- The helpers ---


@pytest.mark.parametrize("text", MALFORMED_TIMES, ids=_short_id)
def test_a_malformed_unix_time_is_none(text):
    assert parse_unix_time(text) is None


def test_a_canonical_unix_time_parses():
    assert parse_unix_time(str(NOW)) == NOW


@pytest.mark.parametrize(("supplied", "expected"), [(NON_ASCII_MAC, "a" * 64), ("a" * 64, NON_ASCII_MAC), ("\x00", "a"), ("", "a")])
def test_a_non_ascii_or_different_value_does_not_match(supplied, expected):
    assert text_matches(supplied, expected) is False


def test_an_equal_ascii_value_matches():
    assert text_matches("a" * 64, "a" * 64) is True


# --- Each verifier refuses, and does not raise ---


@pytest.mark.parametrize("issued", MALFORMED_TIMES, ids=_short_id)
def test_a_guest_token_with_a_malformed_issue_time_is_refused(issued):
    assert verify_guest_token(f"g1.{GUEST_ID}.{issued}.{'0' * 64}", SETTINGS, now=NOW) is None


def test_a_guest_token_with_a_non_ascii_mac_is_refused():
    assert verify_guest_token(f"g1.{GUEST_ID}.{NOW}.{NON_ASCII_MAC}", SETTINGS, now=NOW) is None


def test_a_valid_guest_token_still_verifies():
    token = issue_guest_token(DEVELOPMENT_GUEST_TOKEN_SECRET, GUEST_ID, NOW)
    assert verify_guest_token(token, SETTINGS, now=NOW).guest_id == GUEST_ID


def test_an_arena_ticket_with_a_malformed_expiry_or_mac_is_refused():
    ticket, expires_at = issue_arena_ticket(DEVELOPMENT_GUEST_TOKEN_SECRET, GUEST_ID, "guest", now=NOW)
    version, encoded, provider, _, nonce, mac = ticket.split(".")
    for expiry in ("²", "1" * 400, "0" + str(expires_at)):
        assert verify_arena_ticket(".".join([version, encoded, provider, expiry, nonce, mac]), SETTINGS, now=NOW) is None
    forged = ".".join([version, encoded, provider, str(expires_at), nonce, NON_ASCII_MAC])
    assert verify_arena_ticket(forged, SETTINGS, now=NOW) is None
    assert verify_arena_ticket(ticket, SETTINGS, now=NOW).user_id == GUEST_ID


def test_a_vouched_client_address_with_a_non_ascii_mac_is_refused():
    assert vouched_client_address(f"198.51.100.7 {'é' * 32}") is None
    address = "198.51.100.7"
    assert vouched_client_address(f"{address} {client_address_mac(get_settings().guest_token_secret, address)}") == address


# --- Over HTTP: every call site answers 4xx ---


@pytest.mark.parametrize(
    "cookie",
    [f"g1.{GUEST_ID}.{'1' * 5000}.{'0' * 64}", f"g1.{GUEST_ID}.{int(time.time())}.{NON_ASCII_MAC}"],
    ids=["5000-digit issue time", "non-ASCII MAC"],
)
def test_a_malformed_guest_cookie_gets_401_on_reads_and_403_on_writes(cookie):
    client = _client()
    raw_cookie = _raw(f"{GUEST_TOKEN_COOKIE}={cookie}")
    read = client.get("/auth/me", headers={"cookie": raw_cookie, **_source()})
    write = client.post("/auth/logout", headers={"cookie": raw_cookie, "origin": TRUSTED_ORIGIN, **_source()})
    assert (read.status_code, read.json()["detail"]) == (401, "Invalid guest session.")
    assert (write.status_code, write.json()["detail"]) == (403, "Invalid guest session.")


def test_a_non_ascii_csrf_header_gets_403_on_the_session_and_guest_paths():
    session = _client()
    session.cookies.set("qcai_session_token", "s" * 43)
    session.cookies.set("qcai_auth_csrf", "c" * 43)
    guest = _client()
    token, _ = _valid_guest()
    guest.cookies.set(GUEST_TOKEN_COOKIE, token)
    for client in (session, guest):
        response = client.post("/auth/logout", headers={"origin": TRUSTED_ORIGIN, "x-qcai-csrf": _raw("é" * 48), **_source()})
        assert (response.status_code, response.json()["detail"]) == (403, "CSRF validation failed.")


@pytest.mark.parametrize("origin", ["http://[", "http://[zz]", "https://[::1"])
def test_an_unparsable_origin_is_untrusted(origin):
    client = _client()
    token, csrf = _valid_guest()
    client.cookies.set(GUEST_TOKEN_COOKIE, token)
    response = client.post("/auth/logout", headers={"origin": origin, "x-qcai-csrf": csrf, **_source()})
    assert (response.status_code, response.json()["detail"]) == (403, "Missing trusted request origin.")


def test_a_forged_client_address_header_with_a_non_ascii_mac_is_ignored():
    response = _client().post(
        "/auth/login",
        json={"email": f"nobody-{uuid4().hex[:8]}@example.com", "password": "S3cureQuantumPath"},
        headers={CLIENT_ADDRESS_HEADER: _raw(f"198.51.100.7 {'é' * 32}"), "origin": TRUSTED_ORIGIN, **_source()},
    )
    assert response.status_code == 401


@pytest.mark.parametrize("token", ["garbage", "a.b.c", "éÿ", "x" * 5000], ids=_short_id)
def test_a_malformed_bearer_token_gets_401_when_auth0_is_configured(token):
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="development", auth0_domain="auth0.example.invalid", auth0_audience="https://api.example.invalid"
    )
    try:
        response = _client().get("/auth/me", headers={"authorization": _raw(f"Bearer {token}"), **_source()})
    finally:
        app.dependency_overrides.pop(get_settings, None)
    assert (response.status_code, response.json()["detail"]) == (401, "Invalid bearer token.")


# --- The 422 renderer ---


@pytest.mark.parametrize(
    "body",
    [
        b'{"email":"a@example.com","password":"\\ud800"}',
        b'{"email":"\\udfff@example.com","password":"S3cureQuantumPath"}',
        b'{"\\ud800":1}',
        b"[" * 1000 + b"]" * 1000,
        b'{"email":' + b"[" * 2000 + b"]" * 2000 + b',"password":"x"}',
    ],
    ids=["surrogate password", "surrogate email", "surrogate key", "1000-deep list", "2000-deep field"],
)
def test_an_unprocessable_body_gets_a_4xx_that_echoes_no_input(body):
    response = _client().post(
        "/auth/login", content=body, headers={"content-type": "application/json", "origin": TRUSTED_ORIGIN, **_source()}
    )
    assert 400 <= response.status_code < 500, response.text
    if response.status_code == 422:
        assert all(set(error) == {"type", "loc", "msg"} for error in response.json()["detail"])


def test_a_422_keeps_the_fields_clients_read_and_drops_the_password():
    response = _client().post(
        "/auth/login", json={"email": "not-an-email", "password": "S3cureQuantumPath"}, headers={"origin": TRUSTED_ORIGIN, **_source()}
    )
    assert response.status_code == 422
    assert "S3cureQuantumPath" not in response.text
    (error,) = response.json()["detail"]
    assert set(error) == {"type", "loc", "msg"}, "no echoed input or ctx"
    assert error["loc"] == ["body", "email"] and error["msg"]


# --- Learner-record values ---


def _learner_record_write(payload: dict, operation_type: str):
    client = _client()
    registered = client.post(
        "/auth/register",
        json={"email": f"malformed-{uuid4().hex[:8]}@example.com", "password": "S3cureQuantumPath"},
        headers={"origin": TRUSTED_ORIGIN, **_source()},
    )
    assert registered.status_code == 201
    operation = {
        "operation_id": f"op-{uuid4().hex[:12]}",
        "replica_id": f"replica-{uuid4().hex[:8]}",
        "logical_counter": 1,
        "operation_type": operation_type,
        "payload": payload,
    }
    headers = {"origin": TRUSTED_ORIGIN, "x-qcai-csrf": client.cookies.get("qcai_auth_csrf"), "content-type": "application/json", **_source()}
    written = client.post("/learner-record/operations", content=json.dumps({"operations": [operation]}), headers=headers)
    return written, client.get("/learner-record", headers=_source())


@pytest.mark.parametrize(
    ("operation_type", "payload"),
    [
        ("mastery_set", {"skill_id": "s1", "value": 10**400}),
        ("set_cursor", {"value": "cursor-\udfff"}),
        ("set_preference", {"key": "k", "value": "\ud800"}),
    ],
    ids=["overflowing mastery", "surrogate cursor", "surrogate preference"],
)
def test_a_learner_record_value_that_cannot_be_stored_is_refused_and_the_record_still_reads(operation_type, payload):
    written, read = _learner_record_write(payload, operation_type)
    assert written.status_code == 422, written.text
    assert read.status_code == 200
