"""The tutor response ledger (plan task 3.8, 7.5; R-22; Phase 3 spec 4.12, 7.15, 7.16, 13.2).

Chain tests use an isolated database (fresh_database_url): the shared in-memory session database runs on one
StaticPool connection (spec M17).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from app.core.config_package import get_config_package
from app.core.config import Settings
from app.core.db import Base
from app.core.schema_upgrades import run_schema_upgrades
from app.db_models import ResponseLedgerRecord, TutorThread, TutorTurn
from app.services import ledger
from app.services.ledger import (
    CHAIN,
    GENESIS_HASH,
    LedgerAppendError,
    LedgerConflict,
    LegacyDelivery,
    append_ledger_entry,
    chain_head,
    entry_bytes,
    record_hash_for,
    record_legacy_delivery,
    verify_response_ledger,
)
from app.services.tutor_pipeline.metrics import LEDGER_METRICS
from tutor_fakes import make_entry

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]


@pytest.fixture
def isolated(fresh_database_url) -> Iterator[tuple[Engine, sessionmaker]]:
    engine = create_engine(fresh_database_url)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    try:
        yield engine, sessionmaker(bind=engine)
    finally:
        engine.dispose()


def _check(factory, **kwargs):
    with factory() as db:
        return verify_response_ledger(db, **kwargs)


def test_canonical_bytes_and_record_hash_vectors():
    entry = make_entry("turn-00000000-0000-4000-8000-000000000001")
    raw = entry_bytes(entry)
    assert raw == json.dumps(entry.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    when = datetime(2026, 11, 19, 12, 0, 0, 123456, tzinfo=UTC)
    expected = hashlib.sha256(
        b'{"chain":"tutor-responses","created_at":"2026-11-19T12:00:00.123456Z","entry_sha256":"' + b"e" * 64
        + b'","prev_hash":"' + b"0" * 64 + b'","seq":1}'
    ).hexdigest()
    assert record_hash_for(seq=1, created_at=when, prev_hash=GENESIS_HASH, entry_sha256="e" * 64) == expected
    # A naive value is read as UTC (SQLite), an aware one is converted.
    assert record_hash_for(seq=1, created_at=when.replace(tzinfo=None), prev_hash=GENESIS_HASH, entry_sha256="e" * 64) == expected
    assert record_hash_for(seq=1, created_at=when.astimezone(), prev_hash=GENESIS_HASH, entry_sha256="e" * 64) == expected


def test_appends_chain_from_genesis_and_the_head_follows(isolated):
    _, factory = isolated
    with factory() as db:
        assert chain_head(db) is None
    first = append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
    second = append_ledger_entry(make_entry(delivery="shadow"), session_factory=factory, budget_ms=5000)
    assert (first.seq, second.seq, first.duplicate) == (1, 2, False)
    with factory() as db:
        assert chain_head(db) == (2, second.record_hash)
        rows = db.query(ResponseLedgerRecord).order_by(ResponseLedgerRecord.seq).all()
        assert rows[0].prev_hash == GENESIS_HASH and rows[1].prev_hash == rows[0].record_hash
        assert json.loads(rows[1].entry)["delivery"] == "shadow"
    check = _check(factory)
    assert check.ok and (check.count, check.first_seq, check.last_seq, check.head_row) == (2, 1, 2, (2, second.record_hash))


def test_idempotent_on_response_id_and_a_changed_entry_conflicts(isolated):
    _, factory = isolated
    entry = make_entry()
    first = append_ledger_entry(entry, session_factory=factory, budget_ms=5000)
    again = append_ledger_entry(entry, session_factory=factory, budget_ms=5000)
    assert again == ledger.AppendedRecord(seq=first.seq, record_hash=first.record_hash, duplicate=True)
    changed = make_entry(entry.response_id, text="A different sentence entirely.")
    with pytest.raises(LedgerConflict):
        append_ledger_entry(changed, session_factory=factory, budget_ms=5000)
    assert _check(factory).count == 1


class _Flaky:
    """Session proxy: the first `failures` commits raise the given error (a lost write race, a lock timeout)."""

    def __init__(self, factory, failures: int, error):
        self.factory, self.failures, self.error, self.attempts = factory, failures, error, 0

    def __call__(self):
        outer = self
        session = self.factory()
        real_commit = session.commit

        def commit():
            outer.attempts += 1
            if outer.attempts <= outer.failures:
                raise outer.error
            return real_commit()

        session.commit = commit
        return session


def test_an_integrity_error_retries_onto_the_head_and_other_errors_fail_at_once(isolated):
    _, factory = isolated
    append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
    flaky = _Flaky(factory, 1, IntegrityError("INSERT", {}, Exception("duplicate seq")))
    appended = append_ledger_entry(make_entry(), session_factory=flaky, budget_ms=5000)
    assert (flaky.attempts, appended.seq) == (2, 2)
    always = _Flaky(factory, 99, IntegrityError("INSERT", {}, Exception("duplicate seq")))
    with pytest.raises(LedgerAppendError):
        append_ledger_entry(make_entry(), session_factory=always, budget_ms=5000)
    # The attempt count is the package's tutor_pipeline.budgets.ledger_append_attempts (PD-11; was a code constant).
    assert always.attempts == get_config_package(Settings()).tutor_pipeline.ledger_append_attempts == 3
    locked = _Flaky(factory, 99, OperationalError("UPDATE", {}, Exception("lock timeout")))
    with pytest.raises(OperationalError):
        append_ledger_entry(make_entry(), session_factory=locked, budget_ms=5000)
    assert locked.attempts == 1  # never retried: the learner's request is not held
    assert _check(factory).ok and _check(factory).count == 2


def test_statements_run_in_the_fixed_order_and_postgres_sets_a_lock_timeout(isolated):
    engine, factory = isolated
    seen: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        seen.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        append_ledger_entry(make_entry(), session_factory=factory, budget_ms=1500)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    order = [
        next(i for i, s in enumerate(seen) if s.startswith("INSERT INTO response_ledger_head")),
        next(i for i, s in enumerate(seen) if s.startswith("SELECT response_ledger_head.seq")),
        next(i for i, s in enumerate(seen) if s.startswith("INSERT INTO response_ledger ")),
        next(i for i, s in enumerate(seen) if s.startswith("UPDATE response_ledger_head")),
    ]
    assert order == sorted(order)
    head_select = seen[order[1]]
    if engine.dialect.name == "postgresql":
        assert head_select.endswith("FOR UPDATE")
        # Review 2026-11-19: statements are bounded too, and both timeouts precede the first read of the attempt.
        first_read = next(i for i, s in enumerate(seen) if s.startswith("SELECT response_ledger.seq"))
        # Review round 3 (D13): idle time inside the transaction is bounded too, so a stalled append frees the head lock.
        for name in ("lock_timeout", "statement_timeout", "idle_in_transaction_session_timeout"):
            timeout = next(s for s in seen if s.startswith(f"SET LOCAL {name}"))
            assert seen.index(timeout) < min(first_read, order[0])
            milliseconds = int(timeout.split("'")[1].removesuffix("ms"))
            assert 0 < milliseconds <= 1500
    else:
        assert "FOR UPDATE" not in head_select and not any(s.startswith("SET LOCAL") for s in seen)


def test_the_appended_event_carries_the_record_hash_and_no_identifier(isolated, caplog):
    _, factory = isolated
    entry = make_entry()
    with caplog.at_level(logging.INFO, logger="qcai.tutor"):
        appended = append_ledger_entry(entry, session_factory=factory, budget_ms=5000)
    (record,) = [r for r in caplog.records if getattr(r, "json_fields", {}).get("event") == "tutor.ledger.appended"]
    assert record.json_fields == {"event": "tutor.ledger.appended", "delivery": "legacy", "seq": appended.seq,
                                  "record_hash": appended.record_hash, "duplicate": False}
    assert entry.response_id not in record.getMessage()


def _legacy(response_id: str | None = None) -> LegacyDelivery:
    return LegacyDelivery(
        response_id=response_id or f"turn-{uuid4()}", decision="abstain", reason="no_approved_span", claims=(), quoted=(), retrieved=None,
        answer_sha256="c" * 64, retrieval_mode="lexical-extractive-lexically-screened", provider="none", model="extractive-lexically-screened",
        corpus_version="corpus-test", index_version="index-test", gate="p1-floor", threshold_version="score-floor-p1-v1", floor=6.0, margin=0.0,
        policy_version="cs595-v1",
    )


def test_record_legacy_delivery_fails_open_and_is_counted(isolated, monkeypatch, caplog):
    _, factory = isolated
    assert record_legacy_delivery(_legacy(), settings=Settings(), session_factory=factory).seq == 1
    before = LEDGER_METRICS.snapshot()

    def broken(*args, **kwargs):
        raise OperationalError("INSERT", {}, Exception("database unavailable"))

    monkeypatch.setattr(ledger, "append_ledger_entry", broken)
    with caplog.at_level(logging.ERROR, logger="qcai.tutor"):
        assert record_legacy_delivery(_legacy(), settings=Settings(), session_factory=factory) is None
    after = LEDGER_METRICS.snapshot()
    assert after["failed"]["legacy"] == before["failed"]["legacy"] + 1 and after["write_stop"] is True
    (failure,) = [r for r in caplog.records if getattr(r, "json_fields", {}).get("event") == "tutor.ledger.append_failed"]
    # Spec 18.8 F11: the failure line also carries its attempt's id (the terminal line of that attempt); nothing else.
    fields = dict(failure.json_fields)
    assert re.fullmatch(r"[0-9a-f]{32}", fields.pop("attempt"))
    assert fields == {"event": "tutor.ledger.append_failed", "delivery": "legacy", "stage": "append", "error": "OperationalError"}


def test_the_learner_never_waits_past_the_budget_for_a_stuck_pool_and_the_late_outcome_is_counted(isolated, caplog):
    # Review 2026-11-19: lock_timeout bounded only lock waits; a saturated pool (checkout waits pool_timeout, 30 s by
    # default) or a slow new connection held every tutor turn. The wait is now bounded as a whole.
    _, factory = isolated
    released = threading.Event()

    def stuck_pool():
        released.wait(10)  # no connection to check out until the test releases it
        raise TimeoutError("QueuePool limit reached (test)")

    settings = Settings(tutor_ledger_append_budget_ms=200)
    before = LEDGER_METRICS.snapshot()["failed"]["legacy"]
    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="qcai.tutor"):
        assert record_legacy_delivery(_legacy(), settings=settings, session_factory=stuck_pool) is None
    waited_ms = (time.monotonic() - started) * 1000
    # The grace is the package's tutor_pipeline.budgets.ledger_wait_grace_ms (PD-11; was a code constant).
    assert waited_ms < 200 + get_config_package(Settings()).tutor_pipeline.ledger_wait_grace_ms + 500, waited_ms
    deferred = [dict(r.json_fields) for r in caplog.records if getattr(r, "json_fields", {}).get("event") == "tutor.ledger.append_deferred"]
    # Spec 18.8 F11: the deferred line names its attempt, whose terminal line follows when the append ends.
    assert len(deferred) == 1 and re.fullmatch(r"[0-9a-f]{32}", deferred[0].pop("attempt"))
    assert deferred == [{"event": "tutor.ledger.append_deferred", "delivery": "legacy", "budget_ms": 200}]
    assert LEDGER_METRICS.snapshot()["failed"]["legacy"] == before  # not yet known
    released.set()
    assert ledger.LEGACY_APPENDS.drain(10)
    assert LEDGER_METRICS.snapshot()["failed"]["legacy"] == before + 1  # counted when it ended
    # A normal append is still synchronous: the record exists when the call returns. A generous budget, so the
    # first append on a fresh database under a loaded machine is not cut off by the 200 ms one (review round 3, D15).
    appended = record_legacy_delivery(_legacy(), settings=Settings(tutor_ledger_append_budget_ms=5000), session_factory=factory)
    assert appended is not None and _check(factory).count == 1


def test_appends_in_flight_are_capped_and_an_append_past_the_cap_fails_at_once(isolated, monkeypatch, caplog):
    _, factory = isolated
    monkeypatch.setattr(ledger, "LEGACY_APPENDS", ledger._LegacyAppender(1, 1))
    released = threading.Event()

    def stuck_pool():
        released.wait(10)
        raise TimeoutError("QueuePool limit reached (test)")

    settings = Settings(tutor_ledger_append_budget_ms=100)
    before = LEDGER_METRICS.snapshot()["failed"]["legacy"]
    assert record_legacy_delivery(_legacy(), settings=settings, session_factory=stuck_pool) is None  # still in flight
    with caplog.at_level(logging.ERROR, logger="qcai.tutor"):
        started = time.monotonic()
        assert record_legacy_delivery(_legacy(), settings=settings, session_factory=factory) is None
        assert time.monotonic() - started < 0.5  # refused at once, never queued
    assert LEDGER_METRICS.snapshot()["failed"]["legacy"] == before + 1
    (failure,) = [r for r in caplog.records if getattr(r, "json_fields", {}).get("event") == "tutor.ledger.append_failed"]
    assert failure.json_fields["error"] == "LedgerAppendError"
    released.set()
    assert ledger.LEGACY_APPENDS.drain(10) and ledger.LEGACY_APPENDS.pending() == 0
    # The slot is free again. Review round 3 (D15): this step waited for a real first append within the 100 ms budget
    # plus the 250 ms grace, which a loaded machine missed (None, "deferred"); it now has a generous budget, so it
    # tests the freed slot, not the wall clock.
    assert record_legacy_delivery(_legacy(), settings=Settings(tutor_ledger_append_budget_ms=5000), session_factory=factory) is not None
    assert LEDGER_METRICS.snapshot()["failed"]["legacy"] == before + 2


def test_verify_dispatches_on_entry_schema(isolated, monkeypatch):
    _, factory = isolated
    append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
    assert _check(factory).ok
    monkeypatch.setattr(ledger, "ENTRY_SCHEMAS", {})
    assert _check(factory).problems == ("seq 1 has an unknown entry_schema",)


def _run_worker(database_url: str, *args: str) -> tuple[int, dict]:
    env = {**os.environ, "DATABASE_URL": database_url, "PYTHONUNBUFFERED": "1"}
    completed = subprocess.run([sys.executable, "-m", "app.workers.response_ledger", *args], cwd=API_ROOT, env=env, capture_output=True,
                               text=True, timeout=120)
    report = next(line for line in completed.stderr.splitlines() if '"job": "response_ledger"' in line)
    return completed.returncode, json.loads(report[report.index("{"):])


def test_the_worker_logs_one_json_line_with_the_head(fresh_database_url, isolated):
    _, factory = isolated
    appended = [append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000) for _ in range(2)]
    returncode, report = _run_worker(fresh_database_url)
    assert returncode == 0
    assert (report["status"], report["records"], report["head_hash"], report["head_row"]) == ("ok", 2, appended[-1].record_hash, [2, appended[-1].record_hash])
    assert report["severity"] == "INFO" and report["problems"] == []
    returncode, report = _run_worker(fresh_database_url, "--expect-head", f"1:{appended[0].record_hash}")
    assert returncode == 0
    returncode, report = _run_worker(fresh_database_url, "--expect-head", f"3:{'f' * 64}")
    assert returncode == 1 and report["problems"] == ["the chain no longer reaches the logged head seq 3"]


def _load_verify_script():
    spec = importlib.util.spec_from_file_location("phase3_verify_ledger", REPO_ROOT / "scripts" / "verify_ledger.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_verify_script_reports_coverage_and_refuses_an_export_inside_the_repository(fresh_database_url, isolated, tmp_path, capsys):
    _, factory = isolated
    since = datetime.now(UTC) - timedelta(minutes=1)
    with factory() as db:
        thread = TutorThread(id=f"thread-{uuid4()}", user_id=f"verify-{uuid4().hex[:8]}", title="t")
        db.add(thread)
        db.flush()
        turns = [f"turn-{uuid4()}" for _ in range(3)]
        for turn_id in turns:
            # Made by a Phase 3 image with the ledger on: each expects a record (spec 18.8 F12).
            db.add(TutorTurn(id=turn_id, thread_id=thread.id, user_id=thread.user_id, resolved_query="q", retrieval_mode="lexical", provider="none",
                             model="m", decision="abstain", decision_reason="no_approved_span", citations=[], claims=[], corpus_version="c",
                             policy_version="p", created_at=datetime.now(UTC), ledger_record_expected=True))
        db.commit()
    for turn_id in turns[:2]:
        record_legacy_delivery(_legacy(turn_id), settings=Settings(), session_factory=factory)
    module = _load_verify_script()
    report_path = tmp_path / "report.json"
    export_path = tmp_path / "export.jsonl"
    code = module.main(["--database-url", fresh_database_url, "--report", str(report_path), "--coverage-since", since.isoformat(),
                        "--export", str(export_path)])
    assert code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert (report["status"], report["records"], report["coverage"]["turns_since"], report["coverage"]["unrecorded"]) == ("ok", 2, 3, 1)
    assert report["exported"] == {"rows": 2} and len(export_path.read_text(encoding="utf-8").splitlines()) == 2
    assert fresh_database_url not in capsys.readouterr().out  # the URL is never printed
    assert module.main(["--database-url", fresh_database_url, "--export", str(REPO_ROOT / "ledger-export.jsonl")]) == 2
    assert not (REPO_ROOT / "ledger-export.jsonl").exists()
    assert module.main(["--database-url", fresh_database_url, "--expect-head", "not-a-head"]) == 2
