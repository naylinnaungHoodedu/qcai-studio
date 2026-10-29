import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Table, Text, create_engine, select

from app.core.db import Base, SessionLocal
from app.db_models import UserAccount
from app.services.erasure import ERASURE_EXEMPT_TABLES, USER_KEY_COLUMNS, erase_user, user_keyed_tables
from app.services.local_accounts import delete_local_account, register_local_account
from app.services.retention import GUEST_STUDY_RETENTION_DAYS, run_retention_cleanup

API_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone.utc)
PASSWORD = "S3cureQuantumPath"


def _covered_tables() -> list[Table]:
    """User-keyed tables plus every table that hangs off one of them by a foreign key."""
    covered = {table.name for table in user_keyed_tables()}
    for table in Base.metadata.sorted_tables:
        if any(foreign_key.column.table.name in covered for foreign_key in table.foreign_keys):
            covered.add(table.name)
    return [table for table in Base.metadata.sorted_tables if table.name in covered]


def _value(column, user_id: str, created_at: datetime):
    kind = column.type
    if isinstance(kind, DateTime):
        # created_at carries the age under test; other timestamps (expiry, updates) stay in the future.
        return created_at if column.name == "created_at" else NOW + timedelta(days=1)
    if isinstance(kind, Boolean):
        return False
    if isinstance(kind, Integer):
        return 1
    if isinstance(kind, Float):
        return 1.0
    if isinstance(kind, JSON):
        return {}
    if isinstance(kind, (String, Text)):
        value = f"{column.name}-{uuid4().hex}"
        return value[: kind.length] if getattr(kind, "length", None) else value
    raise AssertionError(f"no seed value for {column.table.name}.{column.name} ({kind!r})")


def _seed_everything(db, user_id: str, created_at: datetime = NOW, existing: dict[str, dict] | None = None) -> dict[str, dict]:
    """Insert one row per covered table for `user_id` (reusing `existing` rows); return each row's values."""
    rows: dict[str, dict] = dict(existing or {})
    for table in _covered_tables():
        if table.name in rows:
            continue
        values = {}
        for column in table.columns:
            if column.primary_key and isinstance(column.type, Integer):
                continue
            if column.name in USER_KEY_COLUMNS:
                values[column.name] = user_id
            elif column.foreign_keys:
                foreign_key = next(iter(column.foreign_keys))
                values[column.name] = rows[foreign_key.column.table.name][foreign_key.column.name]
            else:
                values[column.name] = _value(column, user_id, created_at)
        result = db.execute(table.insert().values(**values))
        values.update(dict(zip([column.name for column in table.primary_key.columns], result.inserted_primary_key)))
        rows[table.name] = values
    return rows


def _surviving(db, rows: dict[str, dict]) -> set[str]:
    survivors = set()
    for table in _covered_tables():
        key = table.primary_key.columns
        condition = [column == rows[table.name][column.name] for column in key]
        if db.execute(select(*key).where(*condition)).first() is not None:
            survivors.add(table.name)
    return survivors


def test_every_identity_like_column_is_a_registered_user_key():
    # Guards the registry: a new identity column with a different name would escape erasure.
    pattern = re.compile(r"(user|player|guest|author|opponent|reviewer|learner|account)[a-z_]*_id$")
    unregistered = {
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if pattern.search(column.name) and column.name not in USER_KEY_COLUMNS
    }
    assert unregistered == set()
    assert set(ERASURE_EXEMPT_TABLES) == {"guest_revocations"}


@pytest.mark.parametrize(
    "user_id",
    [f"acct-{uuid4()}", f"guest-{uuid4()}", f"auth0|{uuid4().hex}", f"demo-{uuid4().hex[:8]}"],
    ids=["local-account", "guest", "auth0", "demo"],
)
def test_erasure_leaves_zero_rows_in_every_user_keyed_table(user_id):
    # AC-1-2, for every identity provider; another learner's rows must survive.
    other_id = f"guest-{uuid4()}"
    with SessionLocal() as db:
        erased_rows = _seed_everything(db, user_id)
        other_rows = _seed_everything(db, other_id)
        db.commit()

        counts = erase_user(db, user_id)
        db.commit()

        assert _surviving(db, erased_rows) == set(ERASURE_EXEMPT_TABLES)
        assert _surviving(db, other_rows) == {table.name for table in _covered_tables()}
    assert {"learner_records", "tutor_threads", "tutor_messages", "tutor_turns", "public_handles"} <= set(counts)


def test_account_deletion_uses_full_erasure():
    email = f"erasure-{uuid4().hex[:8]}@qcai.local"
    with SessionLocal() as db:
        account = register_local_account(db, email, PASSWORD)
        user_id = account.user_id
        rows = _seed_everything(db, user_id, existing={"user_accounts": {"user_id": user_id}})
        db.commit()

        delete_local_account(db, user_id, PASSWORD)

        assert _surviving(db, rows) == set(ERASURE_EXEMPT_TABLES)
        assert db.scalars(select(UserAccount).where(UserAccount.email == email)).first() is None


def test_retention_removes_stale_guest_rows_in_every_table_and_keeps_the_rest():
    stale = NOW - timedelta(days=GUEST_STUDY_RETENTION_DAYS + 30)
    stale_guest, fresh_guest, old_account = f"guest-{uuid4()}", f"guest-{uuid4()}", f"acct-{uuid4()}"
    with SessionLocal() as db:
        stale_rows = _seed_everything(db, stale_guest, created_at=stale)
        fresh_rows = _seed_everything(db, fresh_guest)
        account_rows = _seed_everything(db, old_account, created_at=stale)
        db.commit()

        counts = run_retention_cleanup(db, now=NOW)

        timestamped = {table.name for table in _covered_tables() if "created_at" in table.c}
        everything = {table.name for table in _covered_tables()}
        assert _surviving(db, stale_rows) == everything - timestamped
        assert _surviving(db, fresh_rows) == everything
        assert _surviving(db, account_rows) == everything
    assert {"tutor_threads", "tutor_messages", "notes"} <= set(counts)


def _run_retention_job(database_url: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": database_url, "PYTHONUNBUFFERED": "1"}
    return subprocess.run(
        [sys.executable, "-m", "app.workers.retention"],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_retention_job_logs_counts_and_exits_zero(tmp_path: Path):
    database_url = f"sqlite:///{(tmp_path / 'retention.db').as_posix()}"
    Base.metadata.create_all(create_engine(database_url))

    completed = _run_retention_job(database_url)

    assert completed.returncode == 0, completed.stderr
    assert '"job": "retention"' in completed.stderr and '"status": "ok"' in completed.stderr


def test_retention_job_fails_loudly(tmp_path: Path):
    # An empty database (no tables) makes the pass fail; the job must not report success.
    completed = _run_retention_job(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")

    assert completed.returncode == 1
    assert '"status": "failed"' in completed.stderr
