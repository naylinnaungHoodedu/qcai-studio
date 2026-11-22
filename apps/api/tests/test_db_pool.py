"""A pooled connection whose socket has died is replaced, not surfaced as HTTP 500 (Release R1.3).

On 2026-11-18 at 05:06-05:10Z the API answered 6 requests with 5xx after an idle period: pg8000 reported a dead
TLS socket to Cloud SQL as a raw BrokenPipeError during the pool pre-ping, and SQLAlchemy re-raises anything that
is not a DBAPI disconnect error. These tests reproduce that against a real QueuePool, with a connection wrapper
whose cursor fails at the socket the way pg8000's did.
"""

import logging
import sqlite3

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

from app.core import db as db_module
from app.core.db import POOL_RECYCLE_SECONDS, treat_dead_sockets_as_disconnects
from app.core.structured_logging import FIELDS


class _DeadCursor:
    def execute(self, *args, **kwargs):
        raise BrokenPipeError(32, "Broken pipe")

    def close(self):
        pass


class _Connection:
    """A DBAPI connection that can be made to fail at the socket, like an idle pg8000 connection to Cloud SQL."""

    def __init__(self):
        self._real = sqlite3.connect(":memory:", check_same_thread=False)
        self.dead = False

    def cursor(self, *args, **kwargs):
        return _DeadCursor() if self.dead else self._real.cursor(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


# Every pooled engine a test builds, closed after the test: the engine disposed and every wrapped sqlite3 connection
# closed, so no connection is left for the garbage collector to close during a later test.
_BUILT: list = []


@pytest.fixture(autouse=True)
def _close_pooled_engines():
    yield
    while _BUILT:
        engine, created = _BUILT.pop()
        engine.dispose()
        for connection in created:
            connection._real.close()


def _pooled_engine():
    created: list[_Connection] = []

    def creator():
        connection = _Connection()
        created.append(connection)
        return connection

    engine = create_engine("sqlite://", creator=creator, poolclass=QueuePool, pool_size=1, max_overflow=0, pool_pre_ping=True)
    _BUILT.append((engine, created))
    return engine, created


def _use(engine) -> int:
    with engine.connect() as connection:
        return connection.execute(text("SELECT 1")).scalar_one()


def test_without_the_fix_a_dead_socket_escapes_the_pre_ping():
    # The defect as it was: the pre-ping re-raises the socket error, and the request fails.
    engine, created = _pooled_engine()
    assert _use(engine) == 1
    created[0].dead = True
    with pytest.raises(BrokenPipeError):
        _use(engine)


def test_a_dead_socket_is_replaced_by_a_fresh_connection(caplog):
    engine, created = _pooled_engine()
    treat_dead_sockets_as_disconnects(engine)
    assert _use(engine) == 1
    created[0].dead = True

    with caplog.at_level(logging.WARNING, logger="qcai.db"):
        assert _use(engine) == 1
    (record,) = [r for r in caplog.records if r.name == "qcai.db"]
    assert getattr(record, FIELDS) == {"event": "db.pool.dead_socket", "error": "BrokenPipeError"}
    assert len(created) == 2, "the dead connection was discarded and a new one opened"
    assert _use(engine) == 1 and len(created) == 2, "the replacement is reused"


def test_only_socket_errors_are_treated_as_disconnects():
    engine, _ = _pooled_engine()
    treat_dead_sockets_as_disconnects(engine)

    class _Broken:
        def cursor(self):
            raise ValueError("not a socket problem")

    with pytest.raises(ValueError):
        engine.dialect.do_ping(_Broken())


def test_postgres_engines_recycle_and_tolerate_dead_sockets():
    # Runs for real in CI's PostgreSQL job, where app.core.db builds a PostgreSQL engine.
    engine = db_module.engine
    if engine.dialect.name != "postgresql":
        pytest.skip("the application engine is SQLite in this job")
    assert engine.pool._recycle == POOL_RECYCLE_SECONDS
    assert "do_ping" in vars(engine.dialect), "the pre-ping wrapper is installed"
    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
