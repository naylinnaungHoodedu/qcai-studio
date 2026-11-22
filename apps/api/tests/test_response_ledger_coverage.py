"""Phase 3: ledger coverage counts every turn once: recorded, pending or unrecorded (plan Phase 3 I; spec 4.12, 7.15,
7.16).

F12 the worker splits unrecorded turns by what they expected.
J5  a turn whose append may still be running is pending, not a lost record, until the attempt horizon has passed.
J6  the attempt horizon is derived from the code's own terms, the append queue included.
Each test fails if its defect comes back; the spec's review history (18.4) names the round behind each group.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import inspect
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.core.db import Base
from app.core.schema_upgrades import run_schema_upgrades
from app.db_models import TutorThread, TutorTurn
from app.services import ledger
from app.services.ledger import LegacyDelivery, append_ledger_entry, ledger_coverage, record_legacy_delivery

from tutor_fakes import make_entry


API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
PACKAGE = get_config_package(Settings())
PARAMS = PACKAGE.tutor_pipeline


def fresh_sessions(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False), engine


def _turn(db: Session, thread: TutorThread, *, expected: bool | None, age: timedelta = timedelta(0)) -> str:
    turn_id = f"turn-{uuid4()}"
    db.add(TutorTurn(id=turn_id, thread_id=thread.id, user_id=thread.user_id, resolved_query="q", retrieval_mode="lexical", provider="none",
                     model="m", decision="abstain", decision_reason="no_approved_span", citations=[], claims=[], corpus_version="c",
                     policy_version="p", created_at=datetime.now(UTC) - age, ledger_record_expected=expected))
    return turn_id


def _sessions(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False), engine


# ============================================================================================================== F12


def test_f12_the_worker_splits_unrecorded_turns_by_what_they_expected(fresh_database_url):
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        # Spec 18.12 J5: a turn without its record counts as unrecorded only once it is older than the attempt horizon
        # (a newer one is pending), so these turns are 10 minutes old, past the 360 s horizon.
        since = datetime.now(UTC) - timedelta(hours=1)
        with factory() as db:
            thread = TutorThread(id=f"thread-{uuid4()}", user_id=f"review5-{uuid4().hex[:8]}", title="t")
            db.add(thread)
            db.flush()
            recorded = _turn(db, thread, expected=True, age=timedelta(minutes=10))
            for expected in (True, None, False):
                _turn(db, thread, expected=expected, age=timedelta(minutes=10))
            db.commit()
        append_ledger_entry(make_entry(recorded), session_factory=factory, budget_ms=5000)
        with factory() as db:
            coverage = ledger_coverage(db, since)
        assert (coverage["turns_since"], coverage["unrecorded"], coverage["not_expected_earlier_image"], coverage["ledger_disabled"]) == (4, 1, 1, 1)
    finally:
        engine.dispose()


# =============================================================================================================== J5


def _legacy(response_id: str) -> LegacyDelivery:
    return LegacyDelivery(
        response_id=response_id, decision="abstain", reason="no_approved_span", claims=(), quoted=(), retrieved=None,
        answer_sha256="c" * 64, retrieval_mode="lexical-extractive-lexically-screened", provider="none", model="extractive-lexically-screened",
        corpus_version="corpus-test", index_version="index-test", gate="p1-floor", threshold_version="score-floor-p1-v1", floor=6.0, margin=0.0,
        policy_version="cs595-v1",
    )


def _add_turn(db, thread: TutorThread, *, age: timedelta = timedelta(0), expected: bool | None = True) -> str:
    turn_id = f"turn-{uuid4()}"
    db.add(TutorTurn(id=turn_id, thread_id=thread.id, user_id=thread.user_id, resolved_query="q", retrieval_mode="lexical", provider="none",
                     model="m", decision="abstain", decision_reason="no_approved_span", citations=[], claims=[], corpus_version="c",
                     policy_version="p", created_at=datetime.now(UTC) - age, ledger_record_expected=expected))
    return turn_id


def _worker(database_url: str, *args: str) -> tuple[int, dict | None]:
    env = {**os.environ, "DATABASE_URL": database_url, "PYTHONUNBUFFERED": "1"}
    completed = subprocess.run([sys.executable, "-m", "app.workers.response_ledger", *args], cwd=API_ROOT, env=env, capture_output=True,
                               text=True, timeout=120)
    lines = [line for line in completed.stderr.splitlines() if '"job": "response_ledger"' in line]
    return completed.returncode, (json.loads(lines[-1][lines[-1].index("{"):]) if lines else None)


def test_j5_a_turn_whose_append_is_still_running_is_pending_not_unrecorded(fresh_database_url, monkeypatch):
    factory, engine = _sessions(fresh_database_url)
    released = threading.Event()
    real_append = ledger.append_ledger_entry

    def held_open(entry, **kwargs):
        assert released.wait(30)  # the append is in flight (as a slow pool checkout would hold it)
        return real_append(entry, **{**kwargs, "budget_ms": 5000})

    monkeypatch.setattr(ledger, "append_ledger_entry", held_open)
    try:
        since = datetime.now(UTC) - timedelta(minutes=1)
        with factory() as db:
            thread = TutorThread(id=f"thread-{uuid4()}", user_id=f"review9-{uuid4().hex[:8]}", title="t")
            db.add(thread)
            db.flush()
            turn_id = _add_turn(db, thread)
            db.commit()  # the turn commits first; its append runs after the commit
        # The request stops waiting (deferred); the append is still running when the coverage check reads the turn.
        assert record_legacy_delivery(_legacy(turn_id), settings=Settings(tutor_ledger_append_budget_ms=100), session_factory=factory) is None
        with factory() as db:
            during = ledger_coverage(db, since)
        assert (during["turns_since"], during["unrecorded"], during["pending"], during["horizon_s"]) == (1, 0, 1, 360)
        code, report = _worker(fresh_database_url, "--coverage-since", since.isoformat())
        assert code == 0 and (report["coverage"]["unrecorded"], report["coverage"]["pending"]) == (0, 1)
        released.set()
        assert ledger.LEGACY_APPENDS.drain(30)
        with factory() as db:
            after = ledger_coverage(db, since)
            # Recorded: neither pending nor unrecorded, whatever the horizon.
            assert (after["unrecorded"], after["pending"]) == (0, 0) and ledger.verify_response_ledger(db).count == 1
            assert (ledger_coverage(db, since, horizon_s=0)["unrecorded"], ledger_coverage(db, since, horizon_s=0)["pending"]) == (0, 0)
    finally:
        released.set()
        engine.dispose()


def test_j5_a_turn_older_than_the_horizon_without_its_record_is_still_a_lost_record(fresh_database_url, tmp_path):
    factory, engine = _sessions(fresh_database_url)
    try:
        since = datetime.now(UTC) - timedelta(hours=1)
        with factory() as db:
            thread = TutorThread(id=f"thread-{uuid4()}", user_id=f"review9-{uuid4().hex[:8]}", title="t")
            db.add(thread)
            db.flush()
            old = _add_turn(db, thread, age=timedelta(minutes=10))
            new = _add_turn(db, thread)
            db.commit()
        with factory() as db:
            coverage = ledger_coverage(db, since)
            assert (coverage["unrecorded"], coverage["pending"]) == (1, 1)  # the old turn is lost, the new one may be running
            settled = datetime.fromisoformat(coverage["settled_before"])
            assert abs((datetime.now(UTC) - settled).total_seconds() - 360) < 30
            # Later, past the horizon, the new turn is counted too; horizon 0 counts every turn at once.
            assert ledger_coverage(db, since, now=datetime.now(UTC) + timedelta(seconds=361))["unrecorded"] == 2
            assert (ledger_coverage(db, since, horizon_s=0)["unrecorded"], ledger_coverage(db, since, horizon_s=0)["pending"]) == (2, 0)
            with pytest.raises(ValueError):
                ledger_coverage(db, since, horizon_s=-1)
        code, report = _worker(fresh_database_url, "--coverage-since", since.isoformat(), "--coverage-horizon-s", "0")
        assert code == 0 and (report["coverage"]["unrecorded"], report["coverage"]["pending"], report["coverage"]["horizon_s"]) == (2, 0, 0)
        code, report = _worker(fresh_database_url, "--coverage-since", since.isoformat(), "--coverage-horizon-s", "-5")
        assert code == 2 and report["status"] == "usage"
        # The development script shares ledger_coverage and takes the same option.
        import importlib.util

        spec = importlib.util.spec_from_file_location("phase3_review9_verify", REPO_ROOT / "scripts" / "verify_ledger.py")
        verify = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verify)
        report_path = tmp_path / "coverage.json"
        assert verify.main(["--database-url", fresh_database_url, "--report", str(report_path), "--coverage-since", since.isoformat()]) == 0
        block = json.loads(report_path.read_text(encoding="utf-8"))["coverage"]
        assert (block["unrecorded"], block["pending"], block["horizon_s"]) == (1, 1, 360)
        assert verify.main(["--database-url", fresh_database_url, "--coverage-since", since.isoformat(), "--coverage-horizon-s", "-1"]) == 2
        assert {old, new}  # both turns exist; neither has a record
    finally:
        engine.dispose()


# =============================================================================================================== J6


def test_j6_the_attempt_horizon_is_derived_from_the_code_s_own_terms():
    per_append = ledger.POOL_CHECKOUT_TIMEOUT_S + ledger.CONNECT_TIMEOUT_S + (ledger.ATTEMPT_STATEMENTS + 1) * PARAMS.ledger_append_budget_ms / 1000
    rounds = math.ceil(PARAMS.ledger_append_max_in_flight / PARAMS.ledger_append_workers)
    assert (per_append, rounds) == (70.5, 4)
    assert ledger.attempt_horizon_s(PARAMS, PARAMS.ledger_append_budget_ms) == 60 * math.ceil((rounds * per_append + ledger.HORIZON_MARGIN_S) / 60) == 360
    assert ledger.coverage_horizon_s(Settings()) == 360
    assert ledger.coverage_horizon_s(Settings(tutor_ledger_append_budget_ms=5000)) > 360  # follows the budget in force
    # A smaller worker pool, or more appends in flight, lengthens it.
    assert ledger.attempt_horizon_s(SimpleNamespace(ledger_append_max_in_flight=16, ledger_append_workers=1), 1500) > 360
    # The pool's checkout timeout is the library default the code keeps; the connect bound is the one app.core.db
    # enforces (round 10, K2: the connector's own timeout never bounded a new connection).
    db_source = (API_ROOT / "app" / "core" / "db.py").read_text(encoding="utf-8")
    assert "pool_timeout" not in db_source
    assert inspect.signature(QueuePool.__init__).parameters["timeout"].default == ledger.POOL_CHECKOUT_TIMEOUT_S
    from app.core.db import CONNECT_TIMEOUT_S, cloud_sql_creator

    assert ledger.CONNECT_TIMEOUT_S == CONNECT_TIMEOUT_S == inspect.signature(cloud_sql_creator).parameters["timeout_s"].default == 30


def test_j6_an_append_attempt_runs_the_statements_the_horizon_counts(fresh_database_url):
    factory, engine = _sessions(fresh_database_url)
    statements: list[str] = []
    try:
        append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)  # the head row exists; the engine is warm
        event.listen(engine, "before_cursor_execute", lambda conn, cursor, statement, *args: statements.append(statement))
        append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
        set_locals = [statement for statement in statements if statement.startswith("SET LOCAL")]
        assert len(set_locals) == (3 if engine.dialect.name == "postgresql" else 0)
        # The commit is the sixth statement: it is not a cursor execute.
        assert len(statements) - len(set_locals) == ledger.ATTEMPT_STATEMENTS - 1, statements
    finally:
        engine.dispose()


def test_j6_queued_appends_end_within_the_rounds_the_horizon_counts():
    appender = ledger._LegacyAppender(2, 4)
    hold = 0.3
    started = time.monotonic()
    ends: list[float] = []
    lock = threading.Lock()

    def task():
        time.sleep(hold)
        with lock:
            ends.append(time.monotonic() - started)

    futures = [appender.submit(task, workers=2, max_in_flight=4) for _ in range(4)]
    assert all(future is not None for future in futures)
    assert appender.submit(task, workers=2, max_in_flight=4) is None  # past max_in_flight: refused at once, never queued
    assert appender.drain(10)
    rounds = math.ceil(4 / 2)  # attempt_horizon_s's rounds for 4 in flight on 2 workers
    assert ledger.attempt_horizon_s(SimpleNamespace(ledger_append_max_in_flight=4, ledger_append_workers=2), 1500) == 60 * math.ceil((rounds * 70.5 + 60) / 60)
    ends.sort()
    assert ends[-1] >= (rounds - 0.5) * hold  # the last two waited a round in the queue: the term the 60 s horizon left out
    assert ends[-1] <= rounds * hold + 2.0
