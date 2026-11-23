"""Phase 3: the ledger's Alembic revision and the start-up schema upgrades (plan Phase 3 G; spec 8.2-8.3).

E6  a head table from an earlier build gains started_at.
E10 the absolute downgrade target is safe in every stamp state the runbook allows; Alembic connects through the Cloud
    SQL connector in production, and the rollback runbook checks the stamp.
F8  new columns are added outside the guard transaction.
F12 existing tables gain the new columns.
F14 the forward Alembic step runs only on a Phase 2 stamp, and the runbook checks the stamp first.
Phase 5 adds the next revision (20261122_phase5_gateway_controls, the gateway's shared controls) and Phase 6 the one after
it (20261122_phase6_v3_audit, the V3 tables): each path below goes through them, one revision at a time with absolute
targets, as the runbook does.
Isolation (spec M17): migration tests use fresh_database_url. Each test fails if its defect comes back; the spec's
review history (18.4) names the round behind each group.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.core.schema_upgrades import run_schema_upgrades
from app.services.ledger import append_ledger_entry

from tutor_fakes import make_entry


API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
RUNBOOK = (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8")
PHASE2_REVISION = "20261119_phase2_corpus_spans"
PHASE3_REVISION = "20261119_phase3_response_ledger"
PHASE3_TABLES = {"response_ledger", "response_ledger_head", "tutor_turn_idempotency"}
PHASE5_REVISION = "20261122_phase5_gateway_controls"
PHASE5_TABLES = {"gateway_budget_days", "gateway_stops", "evidential_cache_entries"}
PHASE6_REVISION = "20261122_phase6_v3_audit"
PHASE6_TABLES = {"v3_queue_items", "v3_claims", "v3_draws", "v3_gold_labels", "v3_events", "v3_model_versions", "v3_flags", "v3_scans"}
PHASE8_REVISION = "20261123_phase8_learner"
PHASE8_TABLES = {
    "learner_issued_replicas", "learner_write_guards", "learner_subjects", "learner_guest_revocations",
    "learner_claim_audits", "learner_consents", "learner_erasure_audits", "learner_consent_changes",
    "learner_adaptation_stops", "learner_assessment_facts",
}


def fresh_sessions(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False), engine


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": database_url, "ENVIRONMENT": "development", "PYTHONUNBUFFERED": "1"}
    env.pop("CLOUD_SQL_CONNECTION_NAME", None)
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=API_ROOT, env=env, capture_output=True, text=True, timeout=180)


# =============================================================================================================== E6


def test_e6_a_head_table_from_an_earlier_build_gains_started_at(fresh_database_url):
    connect_args = {"check_same_thread": False} if fresh_database_url.startswith("sqlite") else {}
    engine = create_engine(fresh_database_url, connect_args=connect_args)
    try:
        Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables if table.name != "response_ledger_head"])
        stamp = "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME"
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE TABLE response_ledger_head (chain VARCHAR(32) PRIMARY KEY, seq INTEGER NOT NULL, record_hash VARCHAR(64) NOT NULL, "
                f"updated_at {stamp} NOT NULL)")
        run_schema_upgrades(engine)
        assert "started_at" in {column["name"] for column in sa_inspect(engine).get_columns("response_ledger_head")}
        run_schema_upgrades(engine)  # idempotent
    finally:
        engine.dispose()


# ============================================================================================================== E10


def _tables(engine) -> set[str]:
    """The application's tables (Alembic's own version table aside: a refused command may create it empty)."""
    try:
        return set(sa_inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def _stamp(engine) -> list[str]:
    try:
        with engine.connect() as connection:
            if "alembic_version" not in sa_inspect(connection).get_table_names():
                return []
            return [row[0] for row in connection.execute(text("SELECT version_num FROM alembic_version"))]
    finally:
        engine.dispose()


def test_e10_the_absolute_downgrade_target_is_safe_in_every_stamp_state_the_runbook_allows(fresh_database_url):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    downgrade = ("-x", "allow_ledger_drop=true", "downgrade", PHASE2_REVISION)
    factory, engine = fresh_sessions(fresh_database_url)  # create_all plus the schema upgrades, as a Phase 3 deploy does
    try:
        append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
        engine.dispose()
        everything = _tables(engine)
        # No stamp (Alembic never ran): the target is refused and nothing is dropped. "-1" would also fail here.
        refused = _alembic(fresh_database_url, *downgrade)
        assert refused.returncode != 0 and "not a valid downgrade target" in (refused.stdout + refused.stderr)
        assert _tables(engine) == everything and _stamp(engine) == []
        # Stamped at Phase 2 (its job ran, Phase 3's did not): a no-op. "-1" here reversed the Phase 2 revision and
        # dropped corpus_spans while the ledger stayed.
        assert _alembic(fresh_database_url, "stamp", PHASE2_REVISION).returncode == 0
        assert _alembic(fresh_database_url, *downgrade).returncode == 0
        assert _tables(engine) == everything and _stamp(engine) == [PHASE2_REVISION]
        # The runbook's path for a create_all schema: compare it with the models, stamp the head (create_all built the
        # Phase 5 and Phase 6 tables too), then go down one revision at a time: the Phase 6 step drops its own (empty)
        # tables only, then the Phase 5 step its own.
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata) == []
        engine.dispose()
        assert _alembic(fresh_database_url, "stamp", PHASE8_REVISION).returncode == 0
        checked = _alembic(fresh_database_url, "check")  # the runbook's comparison once stamped: nothing pending
        assert checked.returncode == 0 and "No new upgrade operations detected" in (checked.stdout + checked.stderr), checked.stderr[-2000:]
        down = _alembic(fresh_database_url, "downgrade", PHASE6_REVISION)
        assert down.returncode == 0, down.stderr[-2000:]
        assert _tables(engine) == everything - PHASE8_TABLES and _stamp(engine) == [PHASE6_REVISION]
        everything -= PHASE8_TABLES
        down = _alembic(fresh_database_url, "downgrade", PHASE5_REVISION)
        assert down.returncode == 0, down.stderr[-2000:]
        assert _tables(engine) == everything - PHASE6_TABLES and _stamp(engine) == [PHASE5_REVISION]
        down = _alembic(fresh_database_url, "downgrade", PHASE3_REVISION)
        assert down.returncode == 0, down.stderr[-2000:]
        assert _tables(engine) == everything - PHASE5_TABLES - PHASE6_TABLES and _stamp(engine) == [PHASE3_REVISION]
        kept = _alembic(fresh_database_url, "downgrade", PHASE2_REVISION)
        assert kept.returncode != 0 and "export first" in kept.stderr and "app.workers.response_ledger --export" in kept.stderr
        assert _tables(engine) == everything - PHASE5_TABLES - PHASE6_TABLES
        dropped = _alembic(fresh_database_url, *downgrade)
        assert dropped.returncode == 0, dropped.stderr[-2000:]
        assert _tables(engine) == everything - PHASE3_TABLES - PHASE5_TABLES - PHASE6_TABLES and "corpus_spans" in _tables(engine)
        assert _stamp(engine) == [PHASE2_REVISION]
    finally:
        engine.dispose()


def test_e10_alembic_connects_through_the_cloud_sql_connector_and_the_runbook_checks_the_stamp():
    env_source = (API_ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "settings.cloud_sql_connection_name" in env_source and "from app.core.db import engine as connectable" in env_source
    rollback = RUNBOOK.split("**Roll back**", 1)[1]
    assert "alembic current" in rollback and f"downgrade {PHASE2_REVISION}" in rollback and "downgrade -1" not in rollback
    assert "A digest rollback needs no downgrade" in rollback and "alembic check" in rollback
    assert "CLOUD_SQL_CONNECTION_NAME" in rollback


# =============================================================================================================== F8


def test_f8_new_columns_are_added_outside_the_guard_transaction():
    source = (API_ROOT / "app" / "core" / "schema_upgrades.py").read_text(encoding="utf-8")
    run = source.split("def run_schema_upgrades", 1)[1]
    assert run.index("_add_missing_columns(engine)") < run.index("with engine.begin() as connection:")
    assert "lock_timeout" in source.split("def _add_missing_columns", 1)[1].split("def run_schema_upgrades", 1)[0]


# ============================================================================================================== F12


def test_f12_existing_tables_gain_the_new_columns(fresh_database_url):
    connect_args = {"check_same_thread": False} if fresh_database_url.startswith("sqlite") else {}
    engine = create_engine(fresh_database_url, connect_args=connect_args)
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE tutor_turns DROP COLUMN ledger_record_expected")
            connection.exec_driver_sql("ALTER TABLE tutor_turn_idempotency DROP COLUMN claim_token")
        for _ in range(2):  # idempotent
            run_schema_upgrades(engine)
            inspector = sa_inspect(engine)
            assert "ledger_record_expected" in {column["name"] for column in inspector.get_columns("tutor_turns")}
            assert "claim_token" in {column["name"] for column in inspector.get_columns("tutor_turn_idempotency")}
    finally:
        engine.dispose()


# ============================================================================================================== F14


def test_f14_the_forward_alembic_step_runs_only_on_a_phase2_stamp(fresh_database_url):
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        # A Phase 2 database: no Phase 3, 5 or 6 tables and no ledger_record_expected, stamped at the Phase 2 revision.
        Base.metadata.drop_all(engine, tables=[Base.metadata.tables[name] for name in PHASE3_TABLES | PHASE5_TABLES | PHASE6_TABLES | PHASE8_TABLES])
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE tutor_turns DROP COLUMN ledger_record_expected")
        engine.dispose()
        assert _alembic(fresh_database_url, "stamp", PHASE2_REVISION).returncode == 0
        upgraded = _alembic(fresh_database_url, "upgrade", PHASE3_REVISION)  # the runbook's gated step
        assert upgraded.returncode == 0, upgraded.stderr[-2000:]
        assert PHASE3_TABLES <= set(sa_inspect(engine).get_table_names()) and not PHASE5_TABLES & set(sa_inspect(engine).get_table_names())
        engine.dispose()
        upgraded = _alembic(fresh_database_url, "upgrade", PHASE5_REVISION)  # the Phase 5 runbook's gated step
        assert upgraded.returncode == 0, upgraded.stderr[-2000:]
        assert not PHASE6_TABLES & set(sa_inspect(engine).get_table_names())
        engine.dispose()
        upgraded = _alembic(fresh_database_url, "upgrade", PHASE6_REVISION)  # the Phase 6 runbook's gated step
        assert upgraded.returncode == 0, upgraded.stderr[-2000:]
        assert not PHASE8_TABLES & _tables(engine)
        engine.dispose()
        upgraded = _alembic(fresh_database_url, "upgrade", PHASE8_REVISION)
        assert upgraded.returncode == 0, upgraded.stderr[-2000:]
        checked = _alembic(fresh_database_url, "check")
        assert checked.returncode == 0 and "No new upgrade operations detected" in (checked.stdout + checked.stderr), checked.stderr[-2000:]
        assert PHASE3_TABLES | PHASE5_TABLES | PHASE6_TABLES | PHASE8_TABLES <= set(sa_inspect(engine).get_table_names())
        engine.dispose()
        # The same database without a stamp, as create_all leaves one: "upgrade head" replays every revision against
        # tables that exist and fails, which is why the runbook skips the job then.
        assert _alembic(fresh_database_url, "stamp", "base").returncode == 0
        refused = _alembic(fresh_database_url, "upgrade", "head")
        assert refused.returncode != 0
    finally:
        engine.dispose()
    before = RUNBOOK.split("## Phase 3", 1)[1].split("**Before the release:**", 1)[1].split("**Deploy**", 1)[0]
    assert "Check the stamp first" in before and "`alembic current`" in before
    assert f"`alembic upgrade {PHASE3_REVISION}`" in before and before.index("`alembic current`") < before.index(f"`alembic upgrade {PHASE3_REVISION}`")
    assert "(`alembic upgrade head`)" not in before
