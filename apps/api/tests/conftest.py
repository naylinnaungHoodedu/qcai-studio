from collections.abc import Iterator
from datetime import UTC, datetime
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


import network_guard

# No test touches the network (Phase 5 spec 13.2): installed before the application is imported.
network_guard.install()

# Tests write and delete rows, so they never use an ambient DATABASE_URL: only in-memory SQLite, or the
# disposable database named by TEST_DATABASE_URL (the PostgreSQL CI job, task 1.10).
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")

# Keep direct service tests on the same complete in-memory schema as API tests.
from app.core.config import get_settings
from app.main import _initialize_database

_initialize_database()
# Phase 6 (spec 0.1): no test writes a backdated V3 queue item into the shared database; v3_fakes.FIXED_NOW is for fresh
# databases only. The V2 track reads the queue-age stop through its pipeline's database, so one backdated item in the
# shared database would stop every later tier-1 shadow run.
SESSION_STARTED = datetime.now(UTC)


@pytest.fixture(scope="session", autouse=True)
def _the_checkout_stays_unchanged():
    """No test, script or mutation run writes into the repository checkout (Phase 6 spec 0.1): the tree after the
    session equals the tree before it, outside the git store, dependency and build trees and bytecode (a test writes to
    its tmp_path; an export refuses the checkout)."""
    import v3_fakes

    before = v3_fakes.repository_tree()
    yield
    changed = v3_fakes.tree_changes(before, v3_fakes.repository_tree())
    if changed:
        pytest.fail(f"the test session wrote into the repository checkout: {changed[:10]}")


@pytest.fixture(autouse=True)
def _no_network_attempt():
    """Fails the test that tried to reach a non-loopback host, even when the code under test caught the refusal."""
    network_guard.take_blocked()
    yield
    blocked = network_guard.take_blocked()
    if blocked:
        pytest.fail(f"a test tried to touch the network: {blocked[:3]}")


@pytest.fixture(autouse=True)
def _fresh_process_gateway_and_cache():
    """Each test starts with a new process gateway (open, a fresh budget), no shared budget day or stop, and a cold
    evidential cache, process and shared (Phase 5 spec 4.4, 4.5, 4.15): a stop, a spend or a cached verdict never leaks
    from one test into the next."""
    from app.gateway.controls import clear_shared_controls
    from app.gateway.gateway import reset_process_gateway
    from app.services.v2_panel.cache import reset_process_cache

    reset_process_gateway()
    clear_shared_controls()
    reset_process_cache()
    yield
    reset_process_gateway()
    clear_shared_controls()
    reset_process_cache()


def _backdated_items() -> int:
    from sqlalchemy import func, select

    from app.core.db import SessionLocal
    from app.db_models import V3QueueItem

    with SessionLocal() as db:
        return int(db.scalar(select(func.count()).select_from(V3QueueItem).where(V3QueueItem.enqueued_at < SESSION_STARTED)) or 0)


@pytest.fixture(autouse=True)
def _fresh_v3_stop_and_no_backdated_shared_items():
    """Each test reads the V3 stop and the EHMF stop afresh (v3.stop.reset_stop_cache, ehmf.stop.reset_stop_cache) with
    EHMF available (Phase 7 spec 7.3), and fails when it leaves a shared-database queue item enqueued before the session
    started (Phase 6 spec 0.1)."""
    from app.services import ehmf, ranking
    from app.services.ehmf.stop import reset_stop_cache as reset_ehmf_stop_cache
    from app.services.ranking.replay import reset_stop_cache as reset_ranking_stop_cache
    from app.services.v3.stop import reset_stop_cache

    reset_stop_cache()
    reset_ehmf_stop_cache()
    reset_ranking_stop_cache()
    ehmf.EHMF_UNAVAILABLE_REASON = None
    ranking.RANKING_UNAVAILABLE_REASON = None
    before = _backdated_items()
    yield
    reset_stop_cache()
    reset_ehmf_stop_cache()
    reset_ranking_stop_cache()
    ehmf.EHMF_UNAVAILABLE_REASON = None
    ranking.RANKING_UNAVAILABLE_REASON = None
    after = _backdated_items()
    if after > before:
        pytest.fail(f"a test left {after - before} backdated V3 queue item(s) in the shared database; use v3_fakes.fresh_v3_sessions()")


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
