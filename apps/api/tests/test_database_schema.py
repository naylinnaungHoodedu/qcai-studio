"""Schema and start-up checks that run on SQLite here and on PostgreSQL in the api-postgres CI job (task 1.10, R-52)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import Base, engine
from app.core.schema_upgrades import run_schema_upgrades
from app.db_models import ProjectSubmission


API_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fresh_database_url(tmp_path: Path) -> Iterator[str]:
    # An empty database of the session's dialect, so start-up can be watched from nothing.
    session_url = make_url(get_settings().database_url)
    if session_url.get_backend_name() == "sqlite":
        yield f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}"
        return
    name = f"qcai_fresh_{uuid4().hex[:12]}"
    admin = create_engine(session_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        try:
            yield session_url.set(database=name).render_as_string(hide_password=False)
        finally:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        admin.dispose()


@pytest.fixture
def empty_manifest(tmp_path: Path) -> Path:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": "1.0", "items": []}), encoding="utf-8")
    return manifest


@contextmanager
def _probe(database_url: str) -> Iterator[Engine]:
    probe = create_engine(database_url)
    try:
        yield probe
    finally:
        probe.dispose()


def _table_names(bind: Engine) -> set[str]:
    return set(inspect(bind).get_table_names())


def _schema_differences(bind: Engine) -> list:
    with bind.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        return compare_metadata(context, Base.metadata)


def _run_in_api(database_url: str, args: list[str], extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": database_url, "ENVIRONMENT": "development", "PYTHONUNBUFFERED": "1"}
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, *args], cwd=API_ROOT, env=env, capture_output=True, text=True, timeout=180
    )


def _start_up(database_url: str, manifest: Path, *, enforce_governance: bool) -> subprocess.CompletedProcess:
    return _run_in_api(
        database_url,
        ["-c", "from app.main import _initialize_database; _initialize_database()"],
        {"ENFORCE_CORPUS_GOVERNANCE": str(enforce_governance).lower(), "CORPUS_MANIFEST_PATH": str(manifest)},
    )


def test_startup_schema_matches_orm_metadata():
    # The session database was built by start-up (conftest): create_all plus run_schema_upgrades.
    assert _schema_differences(engine) == []


def test_unapproved_corpus_stops_startup_before_any_table_exists(fresh_database_url: str, empty_manifest: Path):
    # BEP-0 boot smoke: start-up used to create and upgrade the schema, then fail closed on the corpus.
    completed = _start_up(fresh_database_url, empty_manifest, enforce_governance=True)

    assert completed.returncode != 0
    assert "CorpusGovernanceError" in completed.stderr
    with _probe(fresh_database_url) as probe:
        assert _table_names(probe) == set()


def test_startup_builds_every_orm_table_and_can_run_again(fresh_database_url: str, empty_manifest: Path):
    for _ in range(2):
        completed = _start_up(fresh_database_url, empty_manifest, enforce_governance=False)
        assert completed.returncode == 0, completed.stderr

    with _probe(fresh_database_url) as probe:
        assert _table_names(probe) == set(Base.metadata.tables)
        assert _schema_differences(probe) == []


def test_schema_upgrade_adds_is_deleted_to_a_legacy_submissions_table(fresh_database_url: str):
    legacy = create_engine(fresh_database_url)
    try:
        Base.metadata.create_all(legacy)
        with Session(legacy) as session:
            row = ProjectSubmission(
                user_id="legacy-user", project_slug="legacy", title="t", solution_summary="s", implementation_notes="n"
            )
            session.add(row)
            session.commit()
            row_id = row.id
        with legacy.begin() as connection:
            connection.exec_driver_sql("DROP INDEX ix_project_submissions_is_deleted")
            connection.exec_driver_sql("ALTER TABLE project_submissions DROP COLUMN is_deleted")

        run_schema_upgrades(legacy)

        columns = {column["name"]: column for column in inspect(legacy).get_columns("project_submissions")}
        assert columns["is_deleted"]["nullable"] is False
        with Session(legacy) as session:
            assert session.get(ProjectSubmission, row_id).is_deleted is False
    finally:
        legacy.dispose()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "No Alembic baseline yet: the first revision assumes tables made by create_all, so the chain cannot "
        "build an empty database. Plan L2171 baselines from a read-only production schema dump (Platform "
        "Owner approval); remove this marker when that revision lands."
    ),
)
def test_alembic_head_builds_the_orm_schema(fresh_database_url: str):
    completed = _run_in_api(fresh_database_url, ["-m", "alembic", "upgrade", "head"])

    assert completed.returncode == 0, completed.stderr[-2000:]
    with _probe(fresh_database_url) as probe:
        assert _schema_differences(probe) == []
