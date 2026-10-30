from collections.abc import Iterator
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


# Tests write and delete rows, so they never use an ambient DATABASE_URL: only in-memory SQLite, or the
# disposable database named by TEST_DATABASE_URL (the PostgreSQL CI job, task 1.10).
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")

# Keep direct service tests on the same complete in-memory schema as API tests.
from app.core.config import get_settings
from app.main import _initialize_database

_initialize_database()


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


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "release_artifacts: needs packaged dist/release bundles; runs only in the release-artifacts CI job",
    )
