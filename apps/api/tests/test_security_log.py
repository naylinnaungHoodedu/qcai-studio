"""Append-only, hash-chained security event log (plan task 1.7)."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from starlette.websockets import WebSocketDisconnect

import app.main as main_module
from app.api.routes import arena
from app.core.config import DEVELOPMENT_GUEST_TOKEN_SECRET, Settings
from app.core.db import Base, SessionLocal
from app.core.guest_tokens import GUEST_TOKEN_COOKIE, issue_guest_token
from app.core.rate_limit import SlidingWindowLimiter
from app.core.schema_upgrades import run_schema_upgrades
from app.db_models import SecurityEvent
from app.main import app
from app.services import security_log
from app.services.erasure import user_keyed_tables
from app.services.guest_sessions import revoke_guest
from app.services.retention import SECURITY_EVENT_RETENTION_DAYS, run_retention_cleanup
from app.services.security_log import GENESIS_HASH, append_security_event, keyed_digest, verify_security_log

API_ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)
NOW = datetime.now(UTC)
# Internal id shapes (as test_api.INTERNAL_ID_PATTERN) and raw emails must never be stored in the log.
RAW_ID_FRAGMENTS = ("guest-", "acct-", "@")


@pytest.fixture(autouse=True)
def fresh_caps(monkeypatch):
    # Failure events are capped per type; earlier tests' traffic must not use up this test's allowance.
    monkeypatch.setattr(security_log, "_caps", security_log._Caps())


# --- An isolated database per test, so tampering in one test cannot touch the shared chain. ---


@pytest.fixture
def isolated(fresh_database_url) -> Iterator[tuple[Engine, sessionmaker]]:
    engine = create_engine(fresh_database_url)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    try:
        yield engine, sessionmaker(bind=engine)
    finally:
        engine.dispose()


def _append(factory, count: int, **kwargs) -> list[security_log.AppendedEvent]:
    return [
        append_security_event("test.event", "success", details={"n": index}, session_factory=factory, **kwargs)
        for index in range(count)
    ]


def _check(factory) -> security_log.SecurityLogCheck:
    with factory() as db:
        return verify_security_log(db)


@contextmanager
def _guards_lifted(engine: Engine):
    # Stand-in for an attacker with database rights: lift the triggers, then put them back.
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.exec_driver_sql("ALTER TABLE security_events DISABLE TRIGGER USER")
        else:
            connection.exec_driver_sql("DROP TRIGGER security_events_no_update")
            connection.exec_driver_sql("DROP TRIGGER security_events_retention_delete")
    try:
        yield
    finally:
        if engine.dialect.name == "postgresql":
            with engine.begin() as connection:
                connection.exec_driver_sql("ALTER TABLE security_events ENABLE TRIGGER USER")
        else:
            run_schema_upgrades(engine)


def test_appended_events_form_a_verifiable_chain(isolated):
    _, factory = isolated
    appended = _append(factory, 3)

    check = _check(factory)

    assert check.ok, check.problems
    assert (check.count, check.first_seq, check.last_seq) == (3, 1, 3)
    assert check.head_hash == appended[-1].hash
    with factory() as db:
        rows = db.scalars(select(SecurityEvent).order_by(SecurityEvent.seq)).all()
    assert rows[0].prev_hash == GENESIS_HASH
    assert [row.prev_hash for row in rows[1:]] == [row.hash for row in rows[:-1]]


def _refused(engine: Engine, statement: str) -> bool:
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(statement)
    except DBAPIError as error:
        return "append-only" in str(error)
    return False


def test_update_truncate_and_recent_delete_are_refused(isolated):
    engine, factory = isolated
    _append(factory, 2)

    assert _refused(engine, "UPDATE security_events SET outcome = 'success' WHERE seq = 1")
    assert _refused(engine, "UPDATE security_events SET details = '{}'")
    assert _refused(engine, "DELETE FROM security_events WHERE seq = 2")
    assert _refused(engine, "DELETE FROM security_events")
    if engine.dialect.name == "postgresql":
        assert _refused(engine, "TRUNCATE security_events")
    check = _check(factory)
    assert check.ok and check.count == 2


def test_retention_deletes_only_expired_rows_and_keeps_the_newest(isolated):
    engine, factory = isolated
    old = NOW - timedelta(days=SECURITY_EVENT_RETENTION_DAYS + 30)
    _append(factory, 2, now=old)
    _append(factory, 1)

    with factory() as db:
        counts = run_retention_cleanup(db, now=NOW)
    check = _check(factory)

    assert counts.get("security_events") == 2
    assert check.ok, check.problems
    assert (check.count, check.first_seq, check.last_seq) == (1, 3, 3)


def test_retention_keeps_the_newest_event_even_when_it_has_expired(isolated):
    _, factory = isolated
    _append(factory, 2, now=NOW - timedelta(days=SECURITY_EVENT_RETENTION_DAYS + 30))

    with factory() as db:
        run_retention_cleanup(db, now=NOW)
    check = _check(factory)

    # The chain continues from seq 2 instead of restarting from the genesis hash.
    assert (check.count, check.first_seq) == (1, 2)
    assert check.ok


def test_verify_names_edited_and_removed_rows(isolated):
    engine, factory = isolated
    _append(factory, 5)

    with _guards_lifted(engine):
        with engine.begin() as connection:
            connection.execute(text("UPDATE security_events SET outcome = 'success', actor_role = 'admin' WHERE seq = 2"))
            connection.execute(text("DELETE FROM security_events WHERE seq = 4"))
    check = _check(factory)

    assert not check.ok
    assert "seq 2 does not match its hash" in check.problems
    assert "seq 4 to 4 missing" in check.problems
    assert "seq 5 does not chain onto seq 3" in check.problems


def test_verify_detects_a_rewritten_history(isolated):
    engine, factory = isolated
    _append(factory, 3)
    with factory() as db:
        first = db.get(SecurityEvent, 1)
        forged = security_log.event_hash(
            seq=1,
            created_at=first.created_at,
            event_type="test.forged",
            outcome=first.outcome,
            actor_role=first.actor_role,
            subject_digest=first.subject_digest,
            source_digest=first.source_digest,
            details=first.details,
            prev_hash=first.prev_hash,
        )

    # A rewrite that fixes up its own hash still breaks the link to the next row.
    with _guards_lifted(engine):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE security_events SET event_type = 'test.forged', hash = :hash WHERE seq = 1"), {"hash": forged}
            )
    check = _check(factory)

    assert check.problems == ("seq 2 does not chain onto seq 1",)


def test_a_write_conflict_retries_onto_the_new_head(isolated, monkeypatch):
    _, factory = isolated
    _append(factory, 2)
    real_head = security_log._chain_head
    calls = {"count": 0}

    def stale_then_real(db: Session):
        calls["count"] += 1
        return (1, _check(factory).head_hash) if calls["count"] == 1 else real_head(db)

    monkeypatch.setattr(security_log, "_chain_head", stale_then_real)
    appended = append_security_event("test.event", "success", session_factory=factory)
    check = _check(factory)

    assert calls["count"] == 2
    assert appended.seq == 3
    assert check.ok and check.count == 3


def test_concurrent_writers_never_fork_the_chain(isolated):
    _, factory = isolated
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            _append(factory, 10)
        except BaseException as error:  # pragma: no cover - reported below
            errors.append(error)

    threads = [threading.Thread(target=writer) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    check = _check(factory)

    assert errors == []
    assert check.ok, check.problems
    assert (check.count, check.first_seq, check.last_seq) == (40, 1, 40)


def _run_job(database_url: str) -> tuple[int, dict]:
    env = {**os.environ, "DATABASE_URL": database_url, "PYTHONUNBUFFERED": "1"}
    completed = subprocess.run(
        [sys.executable, "-m", "app.workers.security_log"],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    report = next(line for line in completed.stderr.splitlines() if '"job": "security_log"' in line)
    return completed.returncode, json.loads(report[report.index("{"):])


def test_the_job_logs_the_head_hash_and_fails_on_a_broken_chain(fresh_database_url, isolated):
    engine, factory = isolated
    appended = _append(factory, 2)

    returncode, report = _run_job(fresh_database_url)
    assert returncode == 0
    assert (report["status"], report["events"], report["head_hash"]) == ("ok", 2, appended[-1].hash)

    with _guards_lifted(engine):
        with engine.begin() as connection:
            connection.execute(text("UPDATE security_events SET actor_role = 'admin' WHERE seq = 1"))
    returncode, report = _run_job(fresh_database_url)
    assert returncode == 1
    assert (report["status"], report["problems"]) == ("broken", ["seq 1 does not match its hash"])


# --- Events recorded by the running app, in the shared test database. ---


def _head_seq() -> int:
    with SessionLocal() as db:
        return db.scalar(select(SecurityEvent.seq).order_by(SecurityEvent.seq.desc()).limit(1)) or 0


def _events_since(seq: int, event_type: str | None = None) -> list[SecurityEvent]:
    with SessionLocal() as db:
        query = select(SecurityEvent).where(SecurityEvent.seq > seq).order_by(SecurityEvent.seq)
        if event_type:
            query = query.where(SecurityEvent.event_type == event_type)
        return list(db.scalars(query))


def _stored_text(event: SecurityEvent) -> str:
    return json.dumps(
        [event.event_type, event.outcome, event.actor_role, event.subject_digest, event.source_digest, event.details]
    )


def _source() -> dict[str, str]:
    # A distinct client address per test keeps the per-address HTTP rate limits apart.
    # The trusted address is the rightmost entry (task 1.6); the one on the left is what a client could forge.
    return {"x-forwarded-for": f"10.0.0.1, 198.51.100.{uuid4().hex[:8]}"}


def test_sign_in_events_carry_digests_not_identifiers():
    email = f"security-log-{uuid4().hex[:8]}@example.com"
    headers = _source()
    browser = TestClient(app)
    start = _head_seq()

    registered = browser.post("/auth/register", json={"email": email, "password": "S3cureQuantumPath"}, headers=headers)
    browser.cookies.clear()  # A signed-in session would need CSRF for the next POST.
    failed = browser.post("/auth/login", json={"email": email, "password": "wrong-password-123"}, headers=headers)
    signed_in = browser.post("/auth/login", json={"email": email, "password": "S3cureQuantumPath"}, headers=headers)

    assert (registered.status_code, failed.status_code, signed_in.status_code) == (201, 401, 200)
    user_id = signed_in.json()["user"]["user_id"]
    events = [(event.event_type, event.outcome) for event in _events_since(start)]
    assert events == [("auth.register", "success"), ("auth.login", "failure"), ("auth.login", "success")]
    success = _events_since(start, "auth.login")[-1]
    assert success.subject_digest == keyed_digest(user_id, "subject")
    assert success.source_digest == keyed_digest(headers["x-forwarded-for"].split(",")[-1].strip(), "source")
    for event in _events_since(start):
        stored = _stored_text(event)
        assert user_id not in stored and email not in stored
        assert not any(fragment in stored for fragment in RAW_ID_FRAGMENTS), stored


def test_rejected_and_revoked_guest_credentials_are_recorded():
    revoked_id = f"guest-{uuid4().hex}"
    with SessionLocal() as db:
        revoke_guest(db, revoked_id, "task 1.7 test")
    start = _head_seq()
    forged = TestClient(app)
    forged.cookies.set(GUEST_TOKEN_COOKIE, "g1.guest-00000000.1.not-a-mac")
    revoked = TestClient(app)
    revoked.cookies.set(GUEST_TOKEN_COOKIE, issue_guest_token(DEVELOPMENT_GUEST_TOKEN_SECRET, revoked_id, int(time.time())))

    assert forged.get("/auth/me").status_code == 401
    assert revoked.get("/auth/me").status_code == 401

    events = _events_since(start, "auth.credential_rejected")
    assert [event.details["reason"] for event in events] == ["invalid", "revoked"]
    assert events[0].subject_digest is None
    assert events[1].subject_digest == keyed_digest(revoked_id, "subject")


def test_a_csrf_denial_records_the_route_template_not_the_path():
    guest_id = f"guest-{uuid4().hex}"
    guest = TestClient(app)
    guest.cookies.set(GUEST_TOKEN_COOKIE, issue_guest_token(DEVELOPMENT_GUEST_TOKEN_SECRET, guest_id, int(time.time())))
    start = _head_seq()

    response = guest.delete("/projects/submissions/987654321", headers={"origin": "http://localhost:3000"})

    assert response.status_code == 403
    (event,) = _events_since(start, "request.forbidden")
    assert event.details == {"route": "/projects/submissions/{submission_id}", "method": "DELETE", "reason": "Missing CSRF protection."}
    assert "987654321" not in _stored_text(event)


def test_a_rate_limit_denial_is_recorded():
    headers = _source()
    start = _head_seq()

    # A different email each time, so the per-email sign-in lockout (task 1.6) stays out of this test.
    statuses = [
        client.post(
            "/auth/login", json={"email": f"nobody-{uuid4().hex[:8]}@example.com", "password": "wrong-password-123"}, headers=headers
        ).status_code
        for _ in range(11)
    ]

    assert statuses[-1] == 429
    (event,) = _events_since(start, "rate_limit.exceeded")
    assert event.details["route"] == "/auth/login"
    assert event.outcome == "denied"


def test_failure_events_are_capped_per_type(monkeypatch):
    caps = security_log._Caps()
    caps._limiter = SlidingWindowLimiter(limit=2, window_seconds=0.3)
    monkeypatch.setattr(security_log, "_caps", caps)
    start = _head_seq()

    for _ in range(5):
        security_log.record_security_event("test.capped", "denied")
    time.sleep(0.35)
    security_log.record_security_event("test.capped", "denied")
    security_log.record_security_event("test.uncapped", "success")

    events = _events_since(start)
    assert [event.event_type for event in events] == ["test.capped"] * 3 + ["test.uncapped"]
    assert events[2].details == {"dropped_before": 3}


def test_admin_revocation_and_legacy_upgrade_are_recorded():
    guest_id = f"guest-{uuid4().hex}"
    start = _head_seq()

    revoked = client.post(
        "/admin/guest-revocations",
        json={"guest_id": guest_id, "reason": "task 1.7 test"},
        headers={"x-demo-user": f"admin-{uuid4().hex[:6]}", "x-demo-role": "admin"},
    )
    upgrade = client.post(
        "/auth/guest-upgrade", json={"legacy_guest_id": guest_id, "legacy_csrf": "0" * 48}, headers=_source()
    )

    assert revoked.status_code == 200 and upgrade.status_code == 200
    revocation = _events_since(start, "guest.revoked")[0]
    assert (revocation.actor_role, revocation.subject_digest) == ("admin", keyed_digest(guest_id, "subject"))
    assert "task 1.7 test" not in _stored_text(revocation)
    assert _events_since(start, "guest.legacy_upgrade")[0].outcome == "denied"


def test_arena_socket_rejections_are_recorded(monkeypatch):
    enabled = Settings(environment="development", arena_enabled=True, allowed_origins=["http://localhost:3000"])
    monkeypatch.setattr(arena, "get_settings", lambda: enabled)
    start = _head_seq()

    for origin in ("https://untrusted.example", "http://localhost:3000"):
        with client.websocket_connect("/arena/ws?mode=bot", headers={"origin": origin}) as websocket:
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_text()

    events = _events_since(start, "arena.socket_rejected")
    assert [event.details["close_code"] for event in events] == [4403, 4401]


def test_configuration_overrides_are_recorded_outside_development(monkeypatch):
    relaxed = Settings(
        environment="production",
        allowed_origins=["https://qantumlearn.academy"],
        guest_token_secret="a-production-like-secret-of-sufficient-length",
        enable_demo_auth=True,
        enforce_corpus_governance=False,
    )
    start = _head_seq()
    main_module._record_configuration_overrides()
    assert _events_since(start, "config.override") == []

    monkeypatch.setattr(main_module, "IS_PRODUCTION", True)
    monkeypatch.setattr(main_module, "settings", relaxed)
    main_module._record_configuration_overrides()

    (event,) = _events_since(start, "config.override")
    assert (event.outcome, event.actor_role) == ("warning", "system")
    assert event.details == {"demo_auth_enabled": True, "corpus_governance_disabled": True}


def test_a_recording_fault_never_changes_the_response(monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(security_log, "append_security_event", broken)

    with caplog.at_level(logging.ERROR, logger="qcai.security"):
        response = client.post(
            "/auth/login", json={"email": f"nobody-{uuid4().hex[:8]}@example.com", "password": "wrong-password-123"}, headers=_source()
        )

    assert response.status_code == 401
    assert "could not be recorded" in caplog.text


def test_the_log_is_outside_erasure_and_guarded_at_start_up():
    assert "security_events" not in {table.name for table in user_keyed_tables()}
    security_log.record_security_event("test.startup_guard", "success")
    with SessionLocal() as db:
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(text("UPDATE security_events SET outcome = 'failure'"))
        db.rollback()
        check = verify_security_log(db)
    assert check.ok, check.problems
