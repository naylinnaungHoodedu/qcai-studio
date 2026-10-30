"""Arena socket principal, Origin and per-principal limits (plan task 1.4, AC-1-4)."""

import json
import re
import socket
import threading
import time
from uuid import uuid4

import pytest
import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as connect_on_the_wire

from app.api.routes import arena
from app.core.arena_tickets import ARENA_PROTOCOL, ARENA_TICKET_TTL_SECONDS, issue_arena_ticket, verify_arena_ticket
from app.core.config import DEVELOPMENT_GUEST_TOKEN_SECRET, Settings, get_settings
from app.core.db import SessionLocal
from app.core.guest_tokens import GUEST_TOKEN_COOKIE, guest_csrf_for, issue_guest_token
from app.core.rate_limit import SlidingWindowLimiter
from app.db_models import ArenaProfile
from app.main import app
from app.services.guest_sessions import revoke_guest
from app.services.public_handles import public_handle

TRUSTED_ORIGIN = "http://localhost:3000"
# The internal id shapes of test_api.INTERNAL_ID_PATTERN (AC-1-3): none may reach another player.
INTERNAL_ID_PATTERN = re.compile(
    r"(?i)\b(?:acct|guest|player|arena|bot)[-_][0-9a-f]{6,}"
    r"|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def arena_on(monkeypatch):
    settings = Settings(environment="development", arena_enabled=True, allowed_origins=[TRUSTED_ORIGIN])
    monkeypatch.setattr(arena, "get_settings", lambda: settings)
    # Fresh per-principal limits for each test, at the route's own values.
    monkeypatch.setattr(
        arena, "_connection_attempts", SlidingWindowLimiter(limit=arena.ARENA_CONNECTIONS_PER_MINUTE, window_seconds=60)
    )
    monkeypatch.setattr(
        arena, "_messages", SlidingWindowLimiter(limit=arena.ARENA_MESSAGES_PER_10_SECONDS, window_seconds=10)
    )
    return settings


def _guest_id() -> str:
    return f"guest-{uuid4().hex}"


def _ticket(user_id: str, provider: str = "guest", secret: str = DEVELOPMENT_GUEST_TOKEN_SECRET, now: int | None = None) -> str:
    return issue_arena_ticket(secret, user_id, provider, now=now)[0]


def _open(ticket: str | None = None, origin: str | None = TRUSTED_ORIGIN, query: str = "?mode=bot&display_name=Pilot", protocols=None):
    if protocols is None:
        protocols = [ARENA_PROTOCOL, ticket] if ticket else [ARENA_PROTOCOL]
    headers = {"origin": origin} if origin is not None else {}
    return client.websocket_connect(f"/arena/ws{query}", subprotocols=protocols, headers=headers)


def _close_code(**kwargs) -> int:
    # A rejected socket's first frame is its close. Reading only that frame means a broken check fails the
    # test instead of leaving it waiting on an open socket.
    try:
        with _open(**kwargs) as websocket:
            message = websocket.receive()
    except WebSocketDisconnect as closed_before_accept:
        return closed_before_accept.code
    assert message["type"] == "websocket.close", f"the socket stayed open: {message}"
    return message["code"]


def _profile_count(player_id: str) -> int:
    with SessionLocal() as session:
        return session.scalar(select(func.count()).select_from(ArenaProfile).where(ArenaProfile.player_id == player_id))


def _answer_for(challenge: dict) -> str:
    if challenge["options"]:
        return challenge["options"][0]
    prompt = challenge["prompt"].lower()
    if "softmax" in prompt:
        return "np.exp(shifted).sum()"
    if "optimizer" in prompt:
        return "step()"
    if "reward" in prompt:
        return "reward"
    return "target_network"


@pytest.mark.parametrize(
    "protocols",
    [[], [ARENA_PROTOCOL], [ARENA_PROTOCOL, "at1.not-a-ticket"], ["at1.only-a-ticket"]],
    ids=["no-subprotocol", "protocol-without-ticket", "malformed-ticket", "ticket-without-protocol"],
)
def test_socket_without_a_valid_ticket_closes_with_4401(protocols):
    assert _close_code(protocols=protocols) == 4401


def test_socket_with_two_tickets_closes_with_4401():
    first, second = _ticket(_guest_id()), _ticket(_guest_id())
    assert _close_code(protocols=[ARENA_PROTOCOL, first, second]) == 4401


@pytest.mark.parametrize(
    "origin",
    ["https://untrusted.example", "null", "http://localhost:3000.untrusted.example", None],
    ids=["foreign", "opaque", "lookalike", "missing"],
)
def test_socket_from_an_untrusted_or_missing_origin_closes_with_4403(origin):
    guest_id = _guest_id()
    ticket = _ticket(guest_id)

    assert _close_code(ticket=ticket, origin=origin) == 4403
    assert _profile_count(guest_id) == 0
    # The Origin is checked before the ticket is spent, so a hostile page cannot burn a learner's ticket.
    with _open(ticket=ticket) as websocket:
        assert websocket.receive_json()["type"] == "connected"


def test_forged_expired_future_and_foreign_key_tickets_close_with_4401():
    guest_id = _guest_id()
    now = int(time.time())
    valid = _ticket(guest_id)
    forged = valid[:-1] + ("0" if valid[-1] != "0" else "1")
    expired = _ticket(guest_id, now=now - ARENA_TICKET_TTL_SECONDS - 5)
    future = _ticket(guest_id, now=now + 600)
    foreign = _ticket(guest_id, secret="another-deployment-secret-of-sufficient-length")

    for ticket in (forged, expired, future, foreign):
        assert _close_code(ticket=ticket) == 4401
    assert _profile_count(guest_id) == 0


def test_a_ticket_opens_one_socket_only():
    ticket = _ticket(_guest_id())
    with _open(ticket=ticket) as websocket:
        assert websocket.receive_json()["type"] == "connected"

    assert _close_code(ticket=ticket) == 4401


def test_a_revoked_guest_ticket_closes_with_4401():
    guest_id = _guest_id()
    ticket = _ticket(guest_id)
    with SessionLocal() as session:
        revoke_guest(session, guest_id, "task 1.4 test")

    assert _close_code(ticket=ticket) == 4401
    assert _profile_count(guest_id) == 0


def test_the_player_is_the_ticket_principal_not_a_client_asserted_id():
    guest_id = _guest_id()
    victim = f"arena-victim-{uuid4().hex[:8]}"

    with _open(ticket=_ticket(guest_id), query=f"?mode=bot&player_id={victim}&display_name=Pilot") as websocket:
        connected = websocket.receive_json()

    with SessionLocal() as session:
        assert connected["public_handle"] == public_handle(session, guest_id)
    assert "player_id" not in connected
    assert _profile_count(guest_id) == 1
    assert _profile_count(victim) == 0


def test_bot_match_streams_rounds_and_sends_no_internal_id():
    guest_id = _guest_id()
    with _open(ticket=_ticket(guest_id)) as websocket:
        assert websocket.accepted_subprotocol == ARENA_PROTOCOL
        raw = [websocket.receive_text() for _ in range(3)]
        connected, match_found, challenge = (json.loads(text) for text in raw)
        assert [connected["type"], match_found["type"], challenge["type"]] == ["connected", "match_found", "challenge"]
        websocket.send_json({"type": "answer", "answer": _answer_for(challenge["challenge"])})
        raw.append(websocket.receive_text())
        round_result = json.loads(raw[-1])

    assert round_result["type"] == "round_result"
    assert round_result["correct_answer"]
    assert {player["public_handle"] for player in round_result["players"]} == {connected["public_handle"], "arena-bot"}
    for text in raw:
        assert guest_id not in text
        assert INTERNAL_ID_PATTERN.search(text) is None, text


def test_a_display_name_is_trimmed_and_never_defaults_to_the_player_id():
    guest_id = _guest_id()
    with _open(ticket=_ticket(guest_id), query="?mode=bot&display_name=" + "N" * 80) as websocket:
        assert websocket.receive_json()["display_name"] == "N" * arena.ARENA_DISPLAY_NAME_MAX_LENGTH
    other_id = _guest_id()
    with _open(ticket=_ticket(other_id), query="?mode=bot") as websocket:
        assert websocket.receive_json()["display_name"] == "Challenger"

    with SessionLocal() as session:
        names = dict(session.execute(select(ArenaProfile.player_id, ArenaProfile.display_name).where(ArenaProfile.player_id.in_([guest_id, other_id]))).all())
    assert names == {guest_id: "N" * arena.ARENA_DISPLAY_NAME_MAX_LENGTH, other_id: "Challenger"}


def test_connection_attempts_are_limited_per_principal():
    guest_id = _guest_id()
    # An unsupported mode closes each socket right after it is counted, so no match is started.
    for _ in range(arena.ARENA_CONNECTIONS_PER_MINUTE):
        assert _close_code(ticket=_ticket(guest_id), query="?mode=unsupported") == 4400
    assert _close_code(ticket=_ticket(guest_id), query="?mode=unsupported") == 4429
    # The limit is per principal: another learner is unaffected.
    assert _close_code(ticket=_ticket(_guest_id()), query="?mode=unsupported") == 4400


def test_ticket_endpoint_binds_the_ticket_to_the_resolved_principal():
    user = f"arena-ticket-{uuid4().hex[:8]}"
    response = client.post("/arena/ticket", headers={"x-demo-user": user, "x-demo-role": "learner"})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["protocol"] == ARENA_PROTOCOL and body["expires_in"] == ARENA_TICKET_TTL_SECONDS
    ticket = verify_arena_ticket(body["ticket"], arena.get_settings())
    assert (ticket.user_id, ticket.provider) == (user, "demo")


def test_ticket_endpoint_issues_a_guest_ticket_through_the_csrf_and_origin_checks():
    guest_id = _guest_id()
    issued = int(time.time())
    token = issue_guest_token(DEVELOPMENT_GUEST_TOKEN_SECRET, guest_id, issued)
    csrf = guest_csrf_for(DEVELOPMENT_GUEST_TOKEN_SECRET, guest_id, issued)
    guest_client = TestClient(app)
    guest_client.cookies.set(GUEST_TOKEN_COOKIE, token)

    missing_csrf = guest_client.post("/arena/ticket", headers={"origin": TRUSTED_ORIGIN})
    response = guest_client.post("/arena/ticket", headers={"origin": TRUSTED_ORIGIN, "x-qcai-csrf": csrf})

    assert missing_csrf.status_code == 403
    assert response.status_code == 200
    ticket = verify_arena_ticket(response.json()["ticket"], arena.get_settings())
    assert (ticket.user_id, ticket.provider) == (guest_id, "guest")


def test_ticket_endpoint_refuses_without_a_principal_or_while_disabled(monkeypatch):
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="development", enable_demo_auth=False, allowed_origins=[TRUSTED_ORIGIN]
    )
    try:
        anonymous = client.post("/arena/ticket")
    finally:
        app.dependency_overrides.pop(get_settings, None)
    disabled = Settings(environment="development", arena_enabled=False, allowed_origins=[TRUSTED_ORIGIN])
    monkeypatch.setattr(arena, "get_settings", lambda: disabled)
    while_disabled = client.post("/arena/ticket", headers={"x-demo-user": f"arena-off-{uuid4().hex[:8]}"})

    assert anonymous.status_code == 401
    assert while_disabled.status_code == 403


def test_tickets_signed_with_the_previous_key_still_verify_during_rotation():
    rotated = Settings(
        environment="development",
        guest_token_secret="the-new-guest-token-secret-of-sufficient-length",
        guest_token_previous_secret=DEVELOPMENT_GUEST_TOKEN_SECRET,
    )
    ticket = _ticket(_guest_id(), secret=DEVELOPMENT_GUEST_TOKEN_SECRET)

    assert verify_arena_ticket(ticket, rotated) is not None
    assert verify_arena_ticket(ticket, Settings(environment="development", guest_token_secret=rotated.guest_token_secret)) is None


def test_own_profile_reads_create_nothing_and_carry_no_internal_id():
    guest_id = _guest_id()
    guest_client = TestClient(app)
    guest_client.cookies.set(GUEST_TOKEN_COOKIE, issue_guest_token(DEVELOPMENT_GUEST_TOKEN_SECRET, guest_id, int(time.time())))

    before = guest_client.get("/arena/me")
    assert (before.status_code, before.json()) == (200, None)
    with _open(ticket=_ticket(guest_id)) as websocket:
        websocket.receive_json()
    own = guest_client.get("/arena/me")

    assert own.status_code == 200
    assert "player_id" not in own.json()
    assert INTERNAL_ID_PATTERN.search(own.text) is None
    with SessionLocal() as session:
        assert own.json()["public_handle"] == public_handle(session, guest_id)


def test_leaderboard_never_shows_a_player_id_as_the_display_name():
    guest_id = _guest_id()
    with SessionLocal() as session:
        top_xp = (session.scalar(select(func.max(ArenaProfile.xp))) or 0) + 1000
        session.add(
            ArenaProfile(
                player_id=guest_id,
                display_name=guest_id,
                xp=top_xp,
                matches_played=1,
                wins=1,
                skill_rating=1000,
                adaptive_level=2,
            )
        )
        session.commit()

    response = client.get("/arena/leaderboard", params={"limit": 1})

    assert response.json()[0]["display_name"] == "Challenger"
    assert guest_id not in response.text


def test_sliding_window_limiter_counts_per_key_within_the_window():
    limiter = SlidingWindowLimiter(limit=2, window_seconds=10)

    assert [limiter.allow("a", now=0.0), limiter.allow("a", now=1.0), limiter.allow("a", now=2.0)] == [True, True, False]
    assert limiter.allow("b", now=2.0) is True
    assert limiter.allow("a", now=10.5) is True


# On the wire: a real uvicorn server and a real WebSocket client. The test client reports a close sent before
# accept as its code, but a real client then sees only an HTTP 403 handshake rejection (task 1.4 finding).


@pytest.fixture
def live_arena_url():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("The test uvicorn server did not start.")
        time.sleep(0.05)
    yield f"ws://127.0.0.1:{port}/arena/ws"
    server.should_exit = True
    thread.join(timeout=10)
    listener.close()


# Every read below has a timeout, so a socket that wrongly stays open fails the test rather than hanging it.
WIRE_TIMEOUT_SECONDS = 5


def _on_the_wire(base_url: str, protocols: list[str], origin: str | None = TRUSTED_ORIGIN, mode: str = "bot"):
    return connect_on_the_wire(
        f"{base_url}?mode={mode}&display_name=Pilot", origin=origin, subprotocols=protocols, open_timeout=WIRE_TIMEOUT_SECONDS
    )


def _wire_close_code(base_url: str, origin: str | None, protocols: list[str]) -> int:
    with _on_the_wire(base_url, protocols, origin) as websocket:
        # A rejected socket's first frame is its close.
        with pytest.raises(ConnectionClosed) as excinfo:
            websocket.recv(timeout=WIRE_TIMEOUT_SECONDS)
    return excinfo.value.rcvd.code


def _wire_close_code_after_sending(base_url: str, frames: list[str | bytes]) -> int:
    # Ranked mode with no opponent goes quiet after the queue status, so only a close can end the wait.
    with _on_the_wire(base_url, [ARENA_PROTOCOL, _ticket(_guest_id())], mode="ranked") as websocket:
        assert json.loads(websocket.recv(timeout=WIRE_TIMEOUT_SECONDS))["type"] == "connected"
        for frame in frames:
            websocket.send(frame)
        with pytest.raises(ConnectionClosed) as excinfo:
            for _ in range(5):
                websocket.recv(timeout=WIRE_TIMEOUT_SECONDS)
    return excinfo.value.rcvd.code


def test_on_the_wire_a_client_sees_4401_and_4403_after_an_accepted_handshake(live_arena_url, monkeypatch):
    assert _wire_close_code(live_arena_url, TRUSTED_ORIGIN, [ARENA_PROTOCOL]) == 4401
    assert _wire_close_code(live_arena_url, "https://untrusted.example", [ARENA_PROTOCOL, _ticket(_guest_id())]) == 4403
    disabled = Settings(environment="development", arena_enabled=False, allowed_origins=[TRUSTED_ORIGIN])
    monkeypatch.setattr(arena, "get_settings", lambda: disabled)
    assert _wire_close_code(live_arena_url, TRUSTED_ORIGIN, [ARENA_PROTOCOL, _ticket(_guest_id())]) == 4403


def test_on_the_wire_oversized_binary_and_non_object_messages_close_the_socket(live_arena_url):
    assert _wire_close_code_after_sending(live_arena_url, ["x" * (arena.ARENA_MAX_MESSAGE_BYTES + 1)]) == 1009
    assert _wire_close_code_after_sending(live_arena_url, [b"\x00\x01"]) == 1003
    assert _wire_close_code_after_sending(live_arena_url, ["not json"]) == 1003
    assert _wire_close_code_after_sending(live_arena_url, ["[1, 2]"]) == 1003


def test_on_the_wire_a_message_flood_closes_with_4429(live_arena_url):
    flood = [json.dumps({"type": "noop"})] * (arena.ARENA_MESSAGES_PER_10_SECONDS + 1)
    assert _wire_close_code_after_sending(live_arena_url, flood) == 4429


def test_on_the_wire_a_newer_socket_replaces_the_older_one_with_4409(live_arena_url):
    guest_id = _guest_id()
    with _on_the_wire(live_arena_url, [ARENA_PROTOCOL, _ticket(guest_id)]) as first:
        assert first.subprotocol == ARENA_PROTOCOL
        assert json.loads(first.recv(timeout=WIRE_TIMEOUT_SECONDS))["type"] == "connected"
        with _on_the_wire(live_arena_url, [ARENA_PROTOCOL, _ticket(guest_id)]) as second:
            with pytest.raises(ConnectionClosed) as excinfo:
                for _ in range(10):
                    first.recv(timeout=WIRE_TIMEOUT_SECONDS)
            connected = json.loads(second.recv(timeout=WIRE_TIMEOUT_SECONDS))
            # The newer socket takes over the principal's match.
            assert connected["type"] == "connected"
            assert json.loads(second.recv(timeout=WIRE_TIMEOUT_SECONDS))["type"] == "match_found"

    assert excinfo.value.rcvd.code == 4409
