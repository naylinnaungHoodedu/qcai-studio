"""Application logs reach the platform as JSON lines; the Phase 1 SLIs are built from them (plan Phase 1, item I)."""

from collections.abc import Iterator
from contextlib import contextmanager
import io
import json
import logging
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
from sqlalchemy import select

import app.main as main_module
from app.core.config import DEVELOPMENT_GUEST_TOKEN_SECRET
from app.core.db import SessionLocal
from app.core.guest_tokens import GUEST_TOKEN_COOKIE
from app.core.log_redaction import install_log_redaction
from app.core.structured_logging import FIELDS, JsonLineFormatter, JsonLineHandler, configure_logging
from app.db_models import SecurityEvent
from app.main import app
from app.services import local_accounts, security_log
from app.services.security_log import keyed_digest, record_security_event

API_ROOT = Path(__file__).resolve().parents[1]
SECRET = "structured-logging-test-secret-0123456789"
ORIGIN = {"origin": "http://localhost:3000"}


@pytest.fixture(autouse=True)
def fresh_caps(monkeypatch):
    monkeypatch.setattr(security_log, "_caps", security_log._Caps())


@contextmanager
def _formatted(name: str) -> Iterator[tuple[logging.Logger, io.StringIO]]:
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(JsonLineFormatter())
    logger = logging.getLogger(name)
    saved = (logger.level, logger.propagate)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    try:
        yield logger, buffer
    finally:
        logger.removeHandler(handler)
        logger.setLevel(saved[0])
        logger.propagate = saved[1]


def _entries(buffer: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in buffer.getvalue().splitlines()]


# --- The line format ---


def test_each_record_is_one_json_line_with_severity_and_fields():
    with _formatted("qcai.test.format") as (logger, buffer):
        logger.debug("debug")
        logger.info("info %s", "argument", extra={FIELDS: {"event": "startup", "count": 3, "severity": "DEBUG"}})
        logger.warning("warning")
        logger.error("error")
        logger.critical("critical")

    entries = _entries(buffer)
    assert [entry["severity"] for entry in entries] == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    info = entries[1]
    assert (info["message"], info["logger"], info["event"], info["count"]) == ("info argument", "qcai.test.format", "startup", 3)
    assert info["time"].endswith("Z") and "T" in info["time"]
    assert all(entry["severity"] != "DEBUG" for entry in entries[1:]), "a field must not override the record's severity"


def test_a_traceback_stays_inside_one_entry():
    with _formatted("qcai.test.traceback") as (logger, buffer):
        try:
            raise RuntimeError("database went away")
        except RuntimeError:
            logger.exception("Unhandled server error", extra={FIELDS: {"route": "/auth/me"}})

    assert buffer.getvalue().count("\n") == 1
    (entry,) = _entries(buffer)
    assert entry["severity"] == "ERROR" and entry["route"] == "/auth/me"
    assert entry["message"].startswith("Unhandled server error\nTraceback") and "RuntimeError: database went away" in entry["message"]


def test_secrets_are_masked_in_the_message_the_fields_and_the_traceback():
    install_log_redaction([SECRET])
    with _formatted("qcai.test.redaction") as (logger, buffer):
        try:
            raise ValueError(f"provider said no to {SECRET}")
        except ValueError:
            logger.exception(
                "call with %s failed", SECRET, extra={FIELDS: {"url": "https://example.test/v1?key=AIzaFakeKey123", "secret": SECRET}}
            )

    output = buffer.getvalue()
    assert SECRET not in output and "AIzaFakeKey123" not in output
    assert output.count("[REDACTED]") >= 4


# --- The configuration ---


def test_logging_is_configured_once_on_the_root_with_application_loggers_at_info():
    buffer = io.StringIO()
    try:
        configure_logging(buffer)
        configure_logging(buffer)
        root = logging.getLogger()
        assert sum(1 for handler in root.handlers if isinstance(handler, JsonLineHandler)) == 1

        logging.getLogger("qcai.test.levels").info("application info")
        logging.getLogger("app.services.test_levels").info("module info")
        logging.getLogger("httpx").info("HTTP Request: GET https://example.test")
        logging.getLogger("httpx").warning("library warning")
    finally:
        configure_logging()

    messages = [entry["message"] for entry in _entries(buffer)]
    assert messages == ["application info", "module info", "library warning"]


def test_the_api_configures_it_at_import():
    assert any(isinstance(handler, JsonLineHandler) for handler in logging.getLogger().handlers)
    assert logging.getLogger("qcai.api").getEffectiveLevel() == logging.INFO


# --- What the SLIs and alerts are built from ---


def _security_records(caplog) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == "qcai.security" and hasattr(record, FIELDS)]


def test_each_recorded_security_event_is_mirrored_without_digests(caplog):
    subject = f"acct-{uuid4().hex}"
    with caplog.at_level(logging.INFO, logger="qcai.security"):
        record_security_event("auth.login", "success", actor_role="learner", subject=subject)
        record_security_event("auth.login", "failure", details={"status": 401})

    success, failure = (getattr(record, FIELDS) for record in _security_records(caplog))
    with SessionLocal() as db:
        stored = db.get(SecurityEvent, success["seq"])
    assert (success["event_type"], success["outcome"], success["actor_role"], success["hash"]) == ("auth.login", "success", "learner", stored.hash)
    assert (failure["outcome"], failure["details"]) == ("failure", {"status": 401})
    assert [record.levelname for record in _security_records(caplog)] == ["INFO", "WARNING"]
    mirrored = json.dumps([success, failure])
    assert subject not in mirrored and keyed_digest(subject, "subject") not in mirrored and "digest" not in mirrored


def test_events_dropped_by_the_cap_are_not_mirrored(caplog, monkeypatch):
    # The per-type cap also bounds the log volume an anonymous client can cause.
    monkeypatch.setattr(security_log, "CAPPED_EVENTS_PER_MINUTE", 1)
    monkeypatch.setattr(security_log, "_caps", security_log._Caps())
    with caplog.at_level(logging.INFO, logger="qcai.security"):
        for _ in range(3):
            record_security_event("request.forbidden", "denied", details={"reason": "test"})

    assert len(_security_records(caplog)) == 1


def test_an_unrecorded_event_is_still_counted_in_the_logs(caplog, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(security_log, "append_security_event", broken)
    with caplog.at_level(logging.INFO, logger="qcai.security"):
        record_security_event("auth.login", "failure")

    (record,) = _security_records(caplog)
    assert record.levelname == "ERROR"
    assert getattr(record, FIELDS) == {"event_type": "auth.login", "outcome": "failure", "recorded": False}


def test_a_configuration_override_is_logged_for_the_alert(caplog, monkeypatch):
    monkeypatch.setattr(main_module, "IS_PRODUCTION", True)
    monkeypatch.setattr(main_module.settings, "enable_demo_auth", True)
    with caplog.at_level(logging.INFO, logger="qcai.security"):
        main_module._record_configuration_overrides()

    (record,) = _security_records(caplog)
    fields = getattr(record, FIELDS)
    assert (record.levelname, fields["event_type"], fields["details"]["demo_auth_enabled"]) == ("WARNING", "config.override", True)


def test_account_deletion_reports_how_long_the_erasure_took(caplog):
    email = f"erasure-time-{uuid4().hex[:8]}@example.com"
    password = "S3cureQuantumPath"
    # A distinct client address keeps this test's requests apart from the per-address rate limits.
    headers = {**ORIGIN, "x-forwarded-for": f"10.0.0.1, 198.51.100.{uuid4().hex[:8]}"}
    with TestClient(app) as browser, caplog.at_level(logging.INFO, logger="qcai.security"):
        assert browser.post("/auth/register", json={"email": email, "password": password}, headers=headers).status_code == 201
        deleted = browser.request(
            "DELETE",
            "/auth/account",
            headers={**headers, "x-qcai-csrf": browser.cookies.get("qcai_auth_csrf")},
            json={"password": password},
        )

    assert deleted.status_code == 200
    (fields,) = [getattr(record, FIELDS) for record in _security_records(caplog) if getattr(record, FIELDS)["event_type"] == "account.delete"]
    assert isinstance(fields["details"]["duration_ms"], int) and fields["details"]["duration_ms"] >= 0
    assert fields["details"]["rows"] >= 1, "at least the account row"
    with SessionLocal() as db:
        stored = db.scalars(select(SecurityEvent).where(SecurityEvent.seq == fields["seq"])).one()
    assert stored.details == fields["details"]


def test_erasure_time_covers_the_erase_and_its_commit_but_not_the_password_check(monkeypatch):
    # A fake clock: the password check takes 5 s, the erase 7 ms and its commit 3 ms, so the SLI reads 10.
    clock = {"now": 100.0}

    def taking(seconds: float, call):
        def timed(*args, **kwargs):
            clock["now"] += seconds
            return call(*args, **kwargs)

        return timed

    password = "S3cureQuantumPath"
    with SessionLocal() as db:
        account = local_accounts.register_local_account(db, f"erasure-clock-{uuid4().hex[:8]}@example.com", password)
        monkeypatch.setattr(local_accounts, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
        monkeypatch.setattr(local_accounts, "verify_password", taking(5.0, local_accounts.verify_password))
        monkeypatch.setattr(local_accounts, "erase_user", taking(0.007, local_accounts.erase_user))
        monkeypatch.setattr(db, "commit", taking(0.003, db.commit))
        erasure = local_accounts.delete_local_account(db, account.user_id, password)

    assert erasure.duration_ms == 10
    assert erasure.rows["user_accounts"] == 1


def test_startup_logs_what_the_instance_started_with(caplog):
    with caplog.at_level(logging.INFO, logger="qcai.api"), TestClient(app):
        pass

    (fields,) = [getattr(record, FIELDS) for record in caplog.records if record.name == "qcai.api" and hasattr(record, FIELDS)]
    assert fields == {"event": "startup", "environment": main_module.settings.environment, **main_module._build_fields()}
    assert set(fields) >= {"governance_enforced", "corpus_version", "commit"}


# --- A real API process: the lines reach its output stream under uvicorn's own logging setup ---


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


def test_a_real_api_process_writes_json_lines_for_startup_and_security_events(fresh_database_url, tmp_path):
    port = _free_port()
    env = {**os.environ, "DATABASE_URL": fresh_database_url, "ENVIRONMENT": "development", "PYTHONUNBUFFERED": "1"}
    env.pop("TEST_DATABASE_URL", None)
    output = tmp_path / "api.log"
    with output.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            cwd=API_ROOT,
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
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
                    raise RuntimeError("The API process did not start.")
                time.sleep(0.3)
            forged = httpx.get(f"{base}/auth/me", cookies={GUEST_TOKEN_COOKIE: "g1.guest-00000000.1.not-a-mac"}, timeout=10)
        finally:
            _stop(process)

    assert forged.status_code == 401
    entries = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if line.startswith("{")]
    startup = [entry for entry in entries if entry.get("event") == "startup"]
    rejected = [entry for entry in entries if entry.get("event_type") == "auth.credential_rejected"]
    assert len(startup) == 1 and startup[0]["severity"] == "INFO" and "governance_enforced" in startup[0]
    assert len(rejected) == 1 and rejected[0]["severity"] == "WARNING" and rejected[0]["details"]["reason"] == "invalid"
    assert DEVELOPMENT_GUEST_TOKEN_SECRET not in output.read_text(encoding="utf-8")
