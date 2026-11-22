"""Phase 3: the response ledger's chain: appends, the chain check, its guards, export and restore (plan task 3.8, 7.5;
R-22; spec 4.12, 8.2).

C4  no retention or erasure job deletes a ledger row.
D8  a ledger check that overlaps appends reports a sound chain as sound; a record past the head and a missing head are
    still problems.
D13 the in-image worker runs the coverage and export steps; the PostgreSQL append bounds idle time in its transaction.
E6  the first append writes the chain's start and the head keeps it; start-up writes no ledger marker.
E12 an exported ledger restores byte for byte and its logged head still verifies; a tampered export is refused.
F8  a start-up that re-creates the guards never deadlocks a live append and runs no DDL when they are current; a
    deadlock or serialization failure is retried within the budget.
Isolation (spec M17): chain tests use fresh_database_url. No skips: dialect-specific assertions branch inside the test.
Each test fails if its defect comes back; the spec's review history (18.4) names the round behind each group.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core import schema_upgrades
from app.core.config import Settings
from app.core.db import Base
from app.core.schema_upgrades import RESPONSE_LEDGER_FUNCTION_BODIES, RESPONSE_LEDGER_POSTGRES_TRIGGERS, RESPONSE_LEDGER_TRIGGERS, run_schema_upgrades
from app.db_models import ResponseLedgerHead, ResponseLedgerRecord, TutorThread, TutorTurn
from app.services import ledger, retention
from app.services.erasure import user_keyed_tables
from app.services.ledger import (
    GENESIS_HASH,
    LedgerRestoreRefused,
    append_ledger_entry,
    export_ledger,
    ledger_started_at,
    record_hash_for,
    restore_ledger,
    sqlstate,
    verify_response_ledger,
)
from app.services.retention import run_retention_cleanup
from app.services.tutor_pipeline.contracts import sha256_hex
from app.workers import response_ledger as ledger_worker

from tutor_fakes import make_entry


API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]


def fresh_sessions(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False), engine


# =============================================================================================================== C4


def test_c4_no_retention_or_erasure_job_deletes_a_ledger_row(fresh_database_url):
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        old = datetime(2001, 1, 1, tzinfo=UTC)
        for _ in range(3):
            append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000, now=old)
        with factory() as db:
            before = [(row.seq, row.record_hash) for row in db.scalars(select(ResponseLedgerRecord).order_by(ResponseLedgerRecord.seq))]
            head = db.get(ResponseLedgerHead, ledger.CHAIN)
            head_before = (head.seq, head.record_hash)
        with factory() as db:
            run_retention_cleanup(db, now=datetime(2100, 1, 1, tzinfo=UTC))  # every other rule's cutoff is long past
        with factory() as db:
            after = [(row.seq, row.record_hash) for row in db.scalars(select(ResponseLedgerRecord).order_by(ResponseLedgerRecord.seq))]
            head = db.get(ResponseLedgerHead, ledger.CHAIN)
            assert after == before and len(after) == 3 and (head.seq, head.record_hash) == head_before
            assert verify_response_ledger(db).ok
    finally:
        engine.dispose()
    source = inspect.getsource(retention)
    assert "ResponseLedger" not in source.replace("# No rule touches response_ledger", "")
    assert not {"response_ledger", "response_ledger_head"} & {table.name for table in user_keyed_tables()}


# =============================================================================================================== D8


def _appender(database_url: str):
    factory, engine = fresh_sessions(database_url)
    return factory, engine


def test_d8_appends_that_commit_between_the_checks_statements_never_break_a_sound_chain(fresh_database_url):
    factory, engine = fresh_sessions(fresh_database_url)
    writer_factory, writer_engine = _appender(fresh_database_url)
    try:
        for _ in range(3):
            append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
        selects = []

        def append_between_statements(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)
                if len(selects) > 1:  # after the first read, an append commits before every later statement
                    append_ledger_entry(make_entry(), session_factory=writer_factory, budget_ms=5000)

        event.listen(engine, "before_cursor_execute", append_between_statements)
        try:
            with factory() as db:
                check = verify_response_ledger(db)
        finally:
            event.remove(engine, "before_cursor_execute", append_between_statements)
        assert check.ok, check.problems
        assert check.count == 3 and check.head_row[0] == 3 and check.appended_during_check >= 1
        with factory() as db:
            quiet = verify_response_ledger(db)
        assert quiet.ok and quiet.count == 3 + len(selects) - 1 and quiet.appended_during_check == 0
    finally:
        engine.dispose()
        writer_engine.dispose()


def test_d8_checks_under_live_traffic_all_pass(fresh_database_url):
    factory, engine = fresh_sessions(fresh_database_url)
    writer_factory, writer_engine = _appender(fresh_database_url)
    stop = threading.Event()
    errors: list[BaseException] = []

    def traffic():
        while not stop.is_set():
            try:
                append_ledger_entry(make_entry(), session_factory=writer_factory, budget_ms=5000)
            except BaseException as exc:  # noqa: BLE001 - reported below
                errors.append(exc)
                return
            time.sleep(0.005)

    try:
        for _ in range(40):
            append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
        writer = threading.Thread(target=traffic)
        writer.start()
        try:
            results = []
            for _ in range(8):
                with factory() as db:
                    results.append(verify_response_ledger(db))
        finally:
            stop.set()
            writer.join(30)
        assert not errors, errors
        assert all(result.ok for result in results), [result.problems for result in results if not result.ok]
    finally:
        engine.dispose()
        writer_engine.dispose()


def test_d8_a_record_past_the_head_and_a_missing_head_are_still_problems(fresh_database_url):
    from test_phase3_acceptance import guards_lifted

    factory, engine = fresh_sessions(fresh_database_url)
    try:
        appended = [append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000) for _ in range(3)]
        with guards_lifted(engine):
            with engine.begin() as connection:
                connection.execute(text("UPDATE response_ledger_head SET seq = 2, record_hash = :h"), {"h": appended[1].record_hash})
        with factory() as db:
            check = verify_response_ledger(db)
        assert not check.ok and "seq 3 lies past the chain head (seq 2)" in check.problems
        with guards_lifted(engine):
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM response_ledger_head"))
        with factory() as db:
            check = verify_response_ledger(db)
        assert not check.ok and "the chain head is missing" in check.problems
    finally:
        engine.dispose()


# ============================================================================================================== D13


def _worker(database_url: str, *args: str) -> tuple[int, dict | None, str]:
    env = {**os.environ, "DATABASE_URL": database_url, "PYTHONUNBUFFERED": "1"}
    completed = subprocess.run([sys.executable, "-m", "app.workers.response_ledger", *args], cwd=API_ROOT, env=env, capture_output=True,
                               text=True, timeout=120)
    lines = [line for line in completed.stderr.splitlines() if '"job": "response_ledger"' in line]
    return completed.returncode, (json.loads(lines[-1][lines[-1].index("{"):]) if lines else None), completed.stderr


def test_d13_the_in_image_worker_runs_coverage_and_export(fresh_database_url, tmp_path):
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        # Spec 18.12 J5: the turns are older than the 360 s attempt horizon, so the one without a record is unrecorded
        # (a newer one would be pending: its append may still be running).
        since = datetime.now(UTC) - timedelta(hours=1)
        with factory() as db:
            thread = TutorThread(id=f"thread-{uuid4()}", user_id=f"review3-{uuid4().hex[:8]}", title="t")
            db.add(thread)
            db.flush()
            turns = [f"turn-{uuid4()}" for _ in range(2)]
            for turn_id in turns:
                # Made by a Phase 3 image with the ledger on (spec 18.8 F12): each expects a record.
                db.add(TutorTurn(id=turn_id, thread_id=thread.id, user_id=thread.user_id, resolved_query="q", retrieval_mode="lexical", provider="none",
                                 model="m", decision="abstain", decision_reason="no_approved_span", citations=[], claims=[], corpus_version="c",
                                 policy_version="p", created_at=datetime.now(UTC) - timedelta(minutes=10), ledger_record_expected=True))
            db.commit()
        append_ledger_entry(make_entry(turns[0]), session_factory=factory, budget_ms=5000)
        export_path = tmp_path / "ledger-export.jsonl"
        code, report, _ = _worker(fresh_database_url, "--coverage-since", since.isoformat(), "--export", str(export_path))
        assert code == 0 and report["status"] == "ok" and report["records"] == 1
        assert (report["coverage"]["turns_since"], report["coverage"]["unrecorded"], report["coverage"]["pending"]) == (2, 1, 0)
        assert report["exported"] == {"rows": 1} and json.loads(export_path.read_text(encoding="utf-8").splitlines()[0])["response_id"] == turns[0]
        assert fresh_database_url not in json.dumps(report)
        inside = REPO_ROOT / "ledger-export-review3.jsonl"
        code, report, _ = _worker(fresh_database_url, "--export", str(inside))
        assert code == 2 and report["status"] == "usage" and not inside.exists()
        code, report, _ = _worker(fresh_database_url, "--coverage-since", "not-a-time")
        assert code == 2 and report["status"] == "usage"
    finally:
        engine.dispose()


def test_d13_a_postgres_append_that_stalls_holding_the_head_lock_is_ended_by_the_server(fresh_database_url):
    factory, engine = fresh_sessions(fresh_database_url)
    seen: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        seen.append(" ".join(statement.split()))

    try:
        event.listen(engine, "before_cursor_execute", capture)
        try:
            append_ledger_entry(make_entry(), session_factory=factory, budget_ms=1500)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        if engine.dialect.name != "postgresql":
            assert not any(statement.startswith("SET LOCAL") for statement in seen)
            return
        timeout = next(statement for statement in seen if statement.startswith("SET LOCAL idle_in_transaction_session_timeout"))
        first_read = next(index for index, statement in enumerate(seen) if statement.startswith("SELECT response_ledger.seq"))
        assert seen.index(timeout) < first_read and 0 < int(timeout.split("'")[1].removesuffix("ms")) <= 1500
        # A process that stalls after SELECT ... FOR UPDATE: the server ends its session, which frees the head row.
        stalled = []

        def stall_after_the_head_lock(conn, cursor, statement, parameters, context, executemany):
            if "FOR UPDATE" in statement and not stalled:
                stalled.append(1)
                time.sleep(1.5)

        event.listen(engine, "after_cursor_execute", stall_after_the_head_lock)
        try:
            with pytest.raises(Exception):
                append_ledger_entry(make_entry(), session_factory=factory, budget_ms=400, attempts=1)
        finally:
            event.remove(engine, "after_cursor_execute", stall_after_the_head_lock)
        started = time.monotonic()
        other = append_ledger_entry(make_entry(), session_factory=factory, budget_ms=1500)
        assert other.seq == 2 and time.monotonic() - started < 1.5  # the lock was released; the chain did not fork
        with factory() as db:
            assert verify_response_ledger(db).ok
    finally:
        engine.dispose()


# =============================================================================================================== E6


def test_e6_the_first_append_writes_the_start_and_the_head_keeps_it(fresh_database_url):
    # Spec 18.8 F10: start-up writes no marker any more; the first append creates the head with its started_at, and
    # the head may never move it.
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        with factory() as db:
            assert ledger_started_at(db) is None and db.get(ResponseLedgerHead, ledger.CHAIN) is None
        start = datetime(2026, 6, 1, tzinfo=UTC)
        first = append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000, now=start)
        with factory() as db:
            head = db.get(ResponseLedgerHead, ledger.CHAIN)
            assert (head.seq, head.record_hash) == (1, first.record_hash) and ledger_started_at(db) == start
            assert ledger._utc(head.started_at) == start and verify_response_ledger(db).ok
        append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000, now=start + timedelta(hours=1))
        with factory() as db:
            assert ledger_started_at(db) == start
        # The head may not move its start, even on a valid forward step.
        second = make_entry()
        entry = ledger.entry_bytes(second).decode("utf-8")
        digest = sha256_hex(entry.encode("utf-8"))
        with factory() as db:
            last = ledger.chain_head(db)
        at = start + timedelta(hours=2)
        record_hash = record_hash_for(seq=last[0] + 1, created_at=at, prev_hash=last[1], entry_sha256=digest)
        with pytest.raises(Exception, match="moves forward only"):
            with factory() as db:
                db.execute(ledger.insert(ResponseLedgerRecord).values(
                    seq=last[0] + 1, response_id=second.response_id, delivery=second.delivery, decision=second.decision, shadowed_response_id=None,
                    claim_set_hash=None, entry_schema=second.entry_schema, entry=entry, entry_sha256=digest, prev_hash=last[1],
                    record_hash=record_hash, created_at=at))
                db.execute(ledger.update(ResponseLedgerHead).where(ResponseLedgerHead.chain == ledger.CHAIN)
                           .values(seq=last[0] + 1, record_hash=record_hash, updated_at=at, started_at=at))
                db.commit()
    finally:
        engine.dispose()


def test_e6_start_up_writes_no_ledger_marker_whatever_the_setting(monkeypatch, fresh_database_url):
    # Spec 18.8 F10: a revision deployed with no traffic starts while the earlier image still serves every learner, so
    # start-up must not mark the ledger as recording; the first append does, and each turn says what it expects.
    from app import main as main_module

    factory, engine = fresh_sessions(fresh_database_url)
    try:
        monkeypatch.setattr(main_module, "engine", engine)
        monkeypatch.setattr(main_module, "SessionLocal", factory)
        # Only the schema and ledger steps are under test: the corpus checks and the retention run are left out.
        monkeypatch.setattr(main_module, "_check_corpus_before_any_table", lambda: None)
        monkeypatch.setattr(main_module, "run_retention_cleanup", lambda db: None)
        for enabled in (True, False):
            monkeypatch.setattr(main_module, "settings", Settings(tutor_ledger_enabled=enabled))
            main_module._initialize_database()
            with factory() as db:
                assert db.get(ResponseLedgerHead, ledger.CHAIN) is None and ledger_started_at(db) is None
        assert not hasattr(ledger, "mark_ledger_started") and not hasattr(main_module, "mark_ledger_started")
    finally:
        engine.dispose()


# ============================================================================================================== E12


def _drop_and_recreate_the_ledger(engine) -> None:
    tables = [Base.metadata.tables[name] for name in ("response_ledger_head", "response_ledger")]
    Base.metadata.drop_all(engine, tables=tables)
    Base.metadata.create_all(engine, tables=tables)
    run_schema_upgrades(engine)


def test_e12_an_exported_ledger_restores_byte_for_byte_and_its_logged_head_still_verifies(fresh_database_url, tmp_path, monkeypatch):
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        for delivery in ("legacy", "shadow", "legacy"):
            last = append_ledger_entry(make_entry(delivery=delivery), session_factory=factory, budget_ms=5000)
        export = tmp_path / "ledger-export.jsonl"
        with factory() as db:
            assert export_ledger(db, export) == 3
            before = [(row.seq, row.entry, row.entry_sha256, row.prev_hash, row.record_hash) for row in db.scalars(select(ResponseLedgerRecord).order_by(ResponseLedgerRecord.seq))]
        _drop_and_recreate_the_ledger(engine)  # what the allow_ledger_drop downgrade and a re-applied upgrade leave
        with factory() as db:
            assert restore_ledger(db, export) == (3, (3, last.record_hash))
        with factory() as db:
            after = [(row.seq, row.entry, row.entry_sha256, row.prev_hash, row.record_hash) for row in db.scalars(select(ResponseLedgerRecord).order_by(ResponseLedgerRecord.seq))]
            assert after == before
            check = verify_response_ledger(db, expected_head=(3, last.record_hash))
            assert check.ok and check.head_row == (3, last.record_hash)
            # The restored chain keeps its own start: its first record's time.
            assert ledger_started_at(db) == min(ledger._utc(row.created_at) for row in db.scalars(select(ResponseLedgerRecord)))
            with pytest.raises(LedgerRestoreRefused, match="already holds records"):
                restore_ledger(db, export)
        appended = append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
        assert appended.seq == 4  # appends continue the restored chain
        # The in-image worker runs the same restore, then the usual check against the exported head.
        _drop_and_recreate_the_ledger(engine)
        monkeypatch.setattr(ledger_worker, "SessionLocal", factory)
        assert ledger_worker.main(["--restore", str(export), "--expect-head", f"3:{last.record_hash}"]) == 0
        assert ledger_worker.main(["--restore", str(export)]) == 1  # refused: no longer empty
        assert ledger_worker.main(["--restore", str(export), "--export", str(tmp_path / "x.jsonl")]) == 2
    finally:
        engine.dispose()


@pytest.mark.parametrize("tamper", ["entry", "record_hash", "gap", "not_json"])
def test_e12_a_tampered_export_is_refused_and_nothing_is_written(fresh_database_url, tmp_path, tamper):
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        for _ in range(3):
            append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
        export = tmp_path / "ledger-export.jsonl"
        with factory() as db:
            export_ledger(db, export)
        lines = export.read_text(encoding="utf-8").splitlines()
        second = json.loads(lines[1])
        if tamper == "entry":
            second["entry"] = second["entry"].replace("Routing", "Rerouting")
            lines[1] = json.dumps(second)
        elif tamper == "record_hash":
            second["record_hash"] = "f" * 64
            lines[1] = json.dumps(second)
        elif tamper == "gap":
            del lines[1]
        else:
            lines[1] = "{not json"
        export.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _drop_and_recreate_the_ledger(engine)
        with factory() as db:
            with pytest.raises(LedgerRestoreRefused):
                restore_ledger(db, export)
        with factory() as db:
            assert db.scalar(select(ResponseLedgerRecord.seq).limit(1)) is None and ledger.chain_head(db) in (None, (0, GENESIS_HASH))
    finally:
        engine.dispose()


# =============================================================================================================== F8


class _PausingSession(Session):
    """Pauses an append right after it locked the chain head (SELECT ... FOR UPDATE), until released."""

    paused: threading.Event
    resume: threading.Event

    def execute(self, statement, *args, **kwargs):
        result = super().execute(statement, *args, **kwargs)
        if getattr(statement, "_for_update_arg", None) is not None and not self.paused.is_set():
            self.paused.set()
            assert self.resume.wait(30)
        return result


def _waiting_on_a_lock(engine) -> int:
    with engine.connect() as connection:
        return int(connection.exec_driver_sql(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'").scalar() or 0)


def test_f8_a_start_up_that_recreates_the_guards_never_deadlocks_a_live_append(fresh_database_url, monkeypatch):
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        if engine.dialect.name != "postgresql":
            # SQLite serialises writers and has no lock order to get wrong: start-up and appends simply alternate.
            append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
            run_schema_upgrades(engine)
            append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
            with factory() as db:
                assert verify_response_ledger(db).ok
            return
        append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
        paused, resume = threading.Event(), threading.Event()
        pausing = type("Pausing", (_PausingSession,), {"paused": paused, "resume": resume})
        outcome: dict[str, object] = {}

        def append():
            try:
                outcome["append"] = append_ledger_entry(make_entry(), session_factory=sessionmaker(bind=engine, class_=pausing), budget_ms=30000)
            except Exception as exc:  # noqa: BLE001 - reported below
                outcome["append"] = exc

        def start_up():
            try:
                run_schema_upgrades(engine)
                outcome["start_up"] = "ok"
            except Exception as exc:  # noqa: BLE001 - reported below
                outcome["start_up"] = exc

        appender = threading.Thread(target=append)
        appender.start()
        assert paused.wait(30)  # the append holds the chain head
        # A start-up whose guards differ from the catalogs (a new image), so it re-creates them now.
        monkeypatch.setattr(schema_upgrades, "postgres_guard_current", lambda *args: False)
        starter = threading.Thread(target=start_up)
        starter.start()
        deadline = time.monotonic() + 30
        while _waiting_on_a_lock(engine) == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert _waiting_on_a_lock(engine) >= 1  # start-up waits for the head, holding nothing the append needs
        resume.set()
        appender.join(60)
        starter.join(60)
        assert outcome["start_up"] == "ok", outcome
        assert isinstance(outcome["append"], ledger.AppendedRecord) and outcome["append"].seq == 2, outcome
        monkeypatch.undo()
        with factory() as db:
            assert verify_response_ledger(db).ok
    finally:
        engine.dispose()


def test_f8_a_start_up_with_current_guards_runs_no_ddl_and_a_drifted_guard_is_recreated(fresh_database_url):
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        if engine.dialect.name != "postgresql":
            with engine.connect() as connection:
                names = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
            assert set(schema_upgrades.RESPONSE_LEDGER_SQLITE_TRIGGERS) <= names
            return
        assert {(trigger.name, trigger.table) for trigger in RESPONSE_LEDGER_TRIGGERS} == set(RESPONSE_LEDGER_POSTGRES_TRIGGERS)
        append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
        with engine.connect() as connection:
            assert schema_upgrades.postgres_guard_current(connection, RESPONSE_LEDGER_FUNCTION_BODIES, RESPONSE_LEDGER_TRIGGERS)
        # Another session holds what an in-flight append holds: start-up must not wait for it.
        holder = engine.connect()
        transaction = holder.begin()
        holder.exec_driver_sql("LOCK TABLE response_ledger_head, response_ledger IN ROW EXCLUSIVE MODE")
        finished = threading.Event()
        threading.Thread(target=lambda: (run_schema_upgrades(engine), finished.set()), daemon=True).start()
        try:
            assert finished.wait(30), "start-up waited for a lock although its guards were current"
        finally:
            transaction.rollback()
            holder.close()
        # Drift: a changed function body and a disabled trigger are each re-created by the next start.
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE OR REPLACE FUNCTION response_ledger_append_only() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN RETURN NULL; END$$")
            connection.exec_driver_sql("ALTER TABLE response_ledger DISABLE TRIGGER response_ledger_links_to_chain")
        with engine.connect() as connection:
            assert not schema_upgrades.postgres_guard_current(connection, RESPONSE_LEDGER_FUNCTION_BODIES, RESPONSE_LEDGER_TRIGGERS)
        run_schema_upgrades(engine)
        with engine.connect() as connection:
            assert schema_upgrades.postgres_guard_current(connection, RESPONSE_LEDGER_FUNCTION_BODIES, RESPONSE_LEDGER_TRIGGERS)
        with pytest.raises(Exception, match="append-only"):
            with factory() as db:
                db.execute(text("DELETE FROM response_ledger"))
                db.commit()
    finally:
        engine.dispose()


class _Orig(Exception):
    def __init__(self, code: str, *, style: str):
        super().__init__({"C": code, "M": "test"} if style == "pg8000" else "test")
        if style == "psycopg":
            self.sqlstate = code


@pytest.mark.parametrize("style", ["psycopg", "pg8000"])
def test_f8_a_deadlock_or_serialization_failure_is_retried_within_the_budget(fresh_database_url, style):
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        assert sqlstate(OperationalError("SELECT", {}, _Orig("40P01", style=style))) == "40P01"
        for code in ("40P01", "40001"):
            failures = [OperationalError("SELECT", {}, _Orig(code, style=style))]

            class Flaky(Session):
                def execute(self, statement, *args, **kwargs):
                    if failures:
                        raise failures.pop()
                    return super().execute(statement, *args, **kwargs)

            appended = append_ledger_entry(make_entry(), session_factory=sessionmaker(bind=engine, class_=Flaky), budget_ms=5000, attempts=3)
            assert appended.duplicate is False and failures == []
        # Any other database error is still raised at once (fail open quickly).
        other = [OperationalError("SELECT", {}, _Orig("55P03", style=style))]

        class Locked(Session):
            def execute(self, statement, *args, **kwargs):
                if other:
                    raise other.pop()
                return super().execute(statement, *args, **kwargs)

        with pytest.raises(OperationalError):
            append_ledger_entry(make_entry(), session_factory=sessionmaker(bind=engine, class_=Locked), budget_ms=5000, attempts=3)
        with factory() as db:
            assert verify_response_ledger(db).count == 2
    finally:
        engine.dispose()
