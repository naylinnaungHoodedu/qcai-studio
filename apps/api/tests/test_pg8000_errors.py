"""Phase 3: pg8000, production's driver, raises the PEP 249 class psycopg raises for the same SQLSTATE (DI-46; spec 7.19).

C7  a pg8000 server error takes the class psycopg gives its SQLSTATE; other errors and other drivers are left as raised.
M1  production's interface: the Cloud SQL connector connects with pg8000.dbapi.connect, which raises every server error
    as a plain DatabaseError, 23505 included; classify_pg8000_errors gives each mapped SQLSTATE class psycopg's PEP 249
    class, so the ledger's IntegrityError retry fires on a real duplicate key there. A postgresql+pg8000:// URL (CI's
    pg8000 leg) uses the legacy pg8000.connect, which raises other classes.
Each test fails if its defect comes back; the spec's review history (18.4) names the round behind each group.
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import pg8000
import pg8000.dbapi
import pg8000.exceptions
import pg8000.legacy
import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy import exc as sa_exc
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.orm import sessionmaker

from app.core import db as db_module
from app.core.db import Base, SessionLocal
from app.core.db import engine as session_engine
from app.core.schema_upgrades import run_schema_upgrades
from app.db_models import ResponseLedgerRecord
from app.main import _sqlstate as main_sqlstate
from app.services import ledger
from app.services.ledger import append_ledger_entry, verify_response_ledger

from tutor_fakes import make_entry


# The dialect production's engine uses (app.core.db: create_engine(URL.create("postgresql+pg8000"), creator=...)).
PG8000_DIALECT = create_engine(URL.create("postgresql+pg8000"), creator=lambda: None).dialect


def _production_shaped_engine(url: str) -> Engine:
    """On PostgreSQL, an engine built as app.core.db builds production's: URL.create("postgresql+pg8000") with a
    creator whose connections come from pg8000.dbapi.connect, the call the Cloud SQL connector's pg8000 adapter makes
    (with the connector's TLS socket in place of host and port). Elsewhere, the URL's own engine."""
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        return create_engine(url)

    def creator():
        return pg8000.dbapi.connect(parsed.username, host=parsed.host or "localhost", port=parsed.port or 5432,
                                    database=parsed.database, password=parsed.password)

    return create_engine(URL.create("postgresql+pg8000"), creator=creator)


def _legacy_url(url: str) -> str:
    """The same database through a postgresql+pg8000:// URL, as CI's pg8000 leg connects."""
    return make_url(url).set(drivername="postgresql+pg8000").render_as_string(hide_password=False)


# =============================================================================================================== C7


@pytest.mark.parametrize("code, expected", [
    ("23514", sa_exc.IntegrityError), ("23503", sa_exc.IntegrityError), ("23502", sa_exc.IntegrityError),
    ("22P02", sa_exc.DataError), ("22001", sa_exc.DataError),
    ("55P03", sa_exc.OperationalError), ("57014", sa_exc.OperationalError), ("40001", sa_exc.OperationalError),
])
def test_c7_a_pg8000_server_error_takes_the_class_psycopg_gives_its_sqlstate(code, expected):
    import pg8000.dbapi

    original = pg8000.dbapi.ProgrammingError({"S": "ERROR", "C": code, "M": "test"})
    context = SimpleNamespace(dialect=SimpleNamespace(driver="pg8000"), is_disconnect=False, original_exception=original,
                              sqlalchemy_exception=sa_exc.ProgrammingError("SELECT 1", {}, original), statement="SELECT 1", parameters={})
    replaced = db_module.classify_pg8000_errors(context)
    assert type(replaced) is expected and replaced.orig is original and replaced.statement == "SELECT 1"


def test_c7_other_errors_and_other_drivers_are_left_as_raised():
    import pg8000.dbapi

    def context(driver, code, wrapped_class=sa_exc.ProgrammingError, disconnect=False):
        original = pg8000.dbapi.ProgrammingError({"C": code, "M": "test"})
        return SimpleNamespace(dialect=SimpleNamespace(driver=driver), is_disconnect=disconnect, original_exception=original,
                               sqlalchemy_exception=wrapped_class("SELECT 1", {}, original), statement="SELECT 1", parameters={})

    assert db_module.classify_pg8000_errors(context("pg8000", "42601")) is None  # a syntax error stays ProgrammingError
    assert db_module.classify_pg8000_errors(context("pg8000", "23505", sa_exc.IntegrityError)) is None  # already right
    assert db_module.classify_pg8000_errors(context("psycopg", "23514")) is None
    assert db_module.classify_pg8000_errors(context("pg8000", "08006", disconnect=True)) is None


def test_c7_constraint_and_data_errors_are_the_same_class_on_every_driver():
    table = f"hardening_check_{uuid4().hex[:8]}"
    with SessionLocal() as db:
        db.execute(text(f"CREATE TEMP TABLE {table} (value integer CHECK (value > 0))"))
        db.execute(text(f"INSERT INTO {table} VALUES (1)"))
        with pytest.raises(sa_exc.IntegrityError):  # psycopg CheckViolation; pg8000 re-classified from ProgrammingError
            db.execute(text(f"INSERT INTO {table} VALUES (-1)"))
        db.rollback()
        if session_engine.dialect.name == "postgresql":
            with pytest.raises(sa_exc.DataError):
                db.execute(text("SELECT CAST('not a number' AS integer)"))
            db.rollback()
        else:  # SQLite casts leniently; the temp table outlives the rollback of the failed insert there
            db.execute(text(f"DROP TABLE IF EXISTS {table}"))
            db.commit()


# =============================================================================================================== M1


@pytest.mark.parametrize("code, expected", [
    ("23505", sa_exc.IntegrityError), ("23514", sa_exc.IntegrityError), ("23503", sa_exc.IntegrityError),
    ("23502", sa_exc.IntegrityError), ("22P02", sa_exc.DataError), ("22001", sa_exc.DataError),
    ("40P01", sa_exc.OperationalError), ("40001", sa_exc.OperationalError), ("55P03", sa_exc.OperationalError),
    ("57014", sa_exc.OperationalError), ("57P01", sa_exc.OperationalError), ("53300", sa_exc.OperationalError),
])
def test_m1_a_raw_pg8000_database_error_takes_the_class_psycopg_gives_its_sqlstate(code, expected):
    # The class production's interface raises for every server error, wrapped as SQLAlchemy wraps it.
    original = pg8000.exceptions.DatabaseError({"S": "ERROR", "C": code, "M": "test"})
    wrapped = sa_exc.DBAPIError.instance("SELECT 1", {}, original, PG8000_DIALECT.loaded_dbapi.Error, dialect=PG8000_DIALECT)
    assert type(wrapped) is sa_exc.DatabaseError  # what code saw without the listener: no except IntegrityError fired
    context = SimpleNamespace(dialect=PG8000_DIALECT, is_disconnect=False, original_exception=original,
                              sqlalchemy_exception=wrapped, statement="SELECT 1", parameters={})
    replaced = db_module.classify_pg8000_errors(context)
    assert type(replaced) is expected and replaced.orig is original and replaced.statement == "SELECT 1"
    assert ledger.sqlstate(replaced) == code and main_sqlstate(replaced) == code


def test_m1_a_raw_database_error_outside_the_map_keeps_its_class():
    for argument in ({"S": "ERROR", "C": "42601", "M": "syntax"}, {"C": "42P01", "M": "no relation"}, {"C": "XX000"}, "no fields"):
        original = pg8000.exceptions.DatabaseError(argument)
        wrapped = sa_exc.DBAPIError.instance("SELECT 1", {}, original, PG8000_DIALECT.loaded_dbapi.Error, dialect=PG8000_DIALECT)
        context = SimpleNamespace(dialect=PG8000_DIALECT, is_disconnect=False, original_exception=original,
                                  sqlalchemy_exception=wrapped, statement="SELECT 1", parameters={})
        assert type(wrapped) is sa_exc.DatabaseError and db_module.classify_pg8000_errors(context) is None, argument


# Each case: a SQLSTATE, the statements that raise it (the last one raises), and the class psycopg gives it.
SERVER_ERRORS = (
    ("23505", ("INSERT INTO {table} VALUES (1)",), sa_exc.IntegrityError),
    ("23514", ("INSERT INTO {table} VALUES (-1)",), sa_exc.IntegrityError),
    ("22P02", ("SELECT CAST('not a number' AS integer)",), sa_exc.DataError),
    ("57014", ("SET LOCAL statement_timeout = '50ms'", "SELECT pg_sleep(5)"), sa_exc.OperationalError),
    ("42601", ("SELEC 1",), None),  # outside the map: the class SQLAlchemy raised stays
)


def _raw_errors(connection, table: str) -> dict[str, BaseException]:
    """Run every case on a raw DB-API connection; the error each raised, by SQLSTATE. The temp table is the
    connection's own, so each caller names a table no other caller on a pooled connection uses."""
    cursor = connection.cursor()
    cursor.execute(f"CREATE TEMP TABLE {table} (value integer PRIMARY KEY CHECK (value > 0))")
    cursor.execute(f"INSERT INTO {table} VALUES (1)")
    connection.commit()
    raised: dict[str, BaseException] = {}
    for code, statements, _ in SERVER_ERRORS:
        cursor = connection.cursor()
        try:
            for statement in statements:
                cursor.execute(statement.format(table=table))
        except Exception as error:  # noqa: BLE001 - the class is what is checked
            raised[code] = error
        connection.rollback()
    return raised


def _engine_errors(engine: Engine) -> dict[str, sa_exc.DBAPIError]:
    table = "m1_engine_check"
    raised: dict[str, sa_exc.DBAPIError] = {}
    with engine.connect() as connection:
        connection.execute(text(f"CREATE TEMP TABLE {table} (value integer PRIMARY KEY CHECK (value > 0))"))
        connection.execute(text(f"INSERT INTO {table} VALUES (1)"))
        connection.commit()
        for code, statements, _ in SERVER_ERRORS:
            try:
                for statement in statements:
                    connection.execute(text(statement.format(table=table)))
            except sa_exc.DBAPIError as error:
                raised[code] = error
            connection.rollback()
    return raised


def test_m1_production_s_pg8000_interface_raises_plain_database_errors_and_the_engine_gives_psycopg_s_classes(fresh_database_url):
    url = make_url(fresh_database_url)
    if url.get_backend_name() != "postgresql":
        # No pg8000 here: the SQLite engine raises the constraint errors as IntegrityError natively.
        engine = create_engine(fresh_database_url)
        try:
            with engine.connect() as connection:
                connection.execute(text("CREATE TABLE m1_check (value integer PRIMARY KEY CHECK (value > 0))"))
                connection.execute(text("INSERT INTO m1_check VALUES (1)"))
                connection.commit()
                for statement in ("INSERT INTO m1_check VALUES (1)", "INSERT INTO m1_check VALUES (-1)"):
                    with pytest.raises(sa_exc.IntegrityError):
                        connection.execute(text(statement))
                    connection.rollback()
        finally:
            engine.dispose()
        return
    production = _production_shaped_engine(fresh_database_url)
    legacy = create_engine(_legacy_url(fresh_database_url))
    try:
        # The two interfaces: production's engine holds pg8000.dbapi connections, the URL's engine legacy ones.
        with production.connect() as connection:
            assert type(connection.connection.driver_connection) is pg8000.dbapi.Connection
        with legacy.connect() as connection:
            assert type(connection.connection.driver_connection) is pg8000.legacy.Connection
        assert legacy.dialect.loaded_dbapi is pg8000 and pg8000.connect is not pg8000.dbapi.connect

        # Raw, without SQLAlchemy: production's interface raises every server error as a plain DatabaseError.
        raw_connection = production.raw_connection()
        try:
            raw = _raw_errors(raw_connection.driver_connection, "m1_dbapi_check")
        finally:
            raw_connection.close()
        assert set(raw) == {code for code, _, _ in SERVER_ERRORS}
        for code, error in raw.items():
            assert type(error) is pg8000.exceptions.DatabaseError and error.args[0]["C"] == code, (code, type(error))
        # The legacy interface raises IntegrityError for 23505 and ProgrammingError for the other server errors.
        raw_connection = legacy.raw_connection()
        try:
            raw = _raw_errors(raw_connection.driver_connection, "m1_legacy_check")
        finally:
            raw_connection.close()
        assert {code: type(error) for code, error in raw.items()} == {
            "23505": pg8000.IntegrityError, "23514": pg8000.ProgrammingError, "22P02": pg8000.ProgrammingError,
            "57014": pg8000.ProgrammingError, "42601": pg8000.ProgrammingError}

        # Through either engine, with the listener: psycopg's class for every mapped SQLSTATE class.
        for engine, native, unmapped in ((production, pg8000.exceptions.DatabaseError, sa_exc.DatabaseError),
                                         (legacy, None, sa_exc.ProgrammingError)):
            raised = _engine_errors(engine)
            assert set(raised) == {code for code, _, _ in SERVER_ERRORS}
            for code, _, expected in SERVER_ERRORS:
                error = raised[code]
                assert type(error) is (expected or unmapped), (engine.url, code, type(error))
                assert ledger.sqlstate(error) == code and main_sqlstate(error) == code
                if native is not None:
                    assert type(error.orig) is native, (code, type(error.orig))
    finally:
        production.dispose()
        legacy.dispose()


def test_m1_the_ledger_retries_a_real_duplicate_key_on_production_s_pg8000_interface(fresh_database_url):
    engine = _production_shaped_engine(fresh_database_url)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    factory = sessionmaker(bind=engine)
    entry = make_entry()
    rival: list[ledger.AppendedRecord] = []
    originals: list[BaseException] = []
    armed = [True]

    def record_original(context) -> None:
        originals.append(context.original_exception)

    def rival_append(connection, cursor, statement, parameters, context, executemany) -> None:
        # Another writer records the same response after this attempt's response_id read found none and before its
        # head insert, so its record insert raises a real 23505 (uq_response_ledger_response_id) on the database.
        if armed[0] and statement.lstrip().upper().startswith("INSERT INTO RESPONSE_LEDGER_HEAD"):
            armed[0] = False
            rival.append(append_ledger_entry(entry, session_factory=factory, budget_ms=30000, attempts=1))

    event.listen(engine, "handle_error", record_original)
    event.listen(engine, "before_cursor_execute", rival_append)
    try:
        appended = append_ledger_entry(entry, session_factory=factory, budget_ms=30000, attempts=3)
    finally:
        event.remove(engine, "before_cursor_execute", rival_append)
        event.remove(engine, "handle_error", record_original)
    try:
        # The first attempt's insert failed on the duplicate key; the retry found the rival's record.
        assert len(rival) == 1 and not rival[0].duplicate and appended.duplicate
        assert appended.seq == rival[0].seq == 1 and appended.record_hash == rival[0].record_hash
        assert len(originals) == 1
        if engine.dialect.name == "postgresql":
            assert type(originals[0]) is pg8000.exceptions.DatabaseError and ledger.sqlstate(originals[0]) == "23505"
        else:
            assert type(originals[0]) is sqlite3.IntegrityError
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(ResponseLedgerRecord)) == 1
            assert verify_response_ledger(db).ok
    finally:
        engine.dispose()
