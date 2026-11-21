"""Phase 3, twelfth review round (2026-11-20; Phase 3 spec 18.4, review history, round 12). Each test fails if its
defect comes back.

M1  production's pg8000 interface. The Cloud SQL connector connects with pg8000.dbapi.connect, which raises every
    server error as a plain DatabaseError, 23505 included; classify_pg8000_errors gives each mapped SQLSTATE class
    psycopg's PEP 249 class, so the ledger's IntegrityError retry fires on a real duplicate key there. A
    postgresql+pg8000:// URL (CI's pg8000 leg) uses the legacy pg8000.connect, which raises other classes. Spec 7.19,
    14 and 16, the app.core.db comment, the CI comment and the test strategy say so (the register's DI-46 row is
    checked by the evidence package's own 00_meta/check_records.py).
M2  spec 0.2 M24 lists v1.json's keys and owner decisions and names every owner decision package v2 adds (D-19, D-12,
    PLAN-3.3, PLAN-12.8), as 5.1 does; every line that says what v2 adds to owner_decisions names all four.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
import re
import sqlite3
from types import SimpleNamespace

import google.cloud.sql.connector.connector as connector_module
import google.cloud.sql.connector.pg8000 as connector_pg8000
import pg8000
import pg8000.dbapi
import pg8000.exceptions
import pg8000.legacy
import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy import exc as sa_exc
from sqlalchemy.dialects.postgresql.pg8000 import PGDialect_pg8000
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.orm import sessionmaker

from app.core import db as db_module
from app.core.db import Base
from app.core.schema_upgrades import run_schema_upgrades
from app.db_models import ResponseLedgerRecord
from app.main import _sqlstate as main_sqlstate
from app.services import ledger
from app.services.ledger import append_ledger_entry, verify_response_ledger
from tutor_fakes import make_entry

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
SPEC = (REPO_ROOT / "docs" / "architecture" / "phase3-implementation-spec.md").read_text(encoding="utf-8")
AUTHORITATIVE_SPEC = SPEC.split("## 18. Implementation record", 1)[0]
STRATEGY = (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
CI = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
V1_RAW = json.loads((API_ROOT / "app" / "config_package" / "v1.json").read_text(encoding="utf-8"))
V2_RAW = json.loads((API_ROOT / "app" / "config_package" / "v2.json").read_text(encoding="utf-8"))
# The dialect production's engine uses (app.core.db: create_engine(URL.create("postgresql+pg8000"), creator=...)).
PG8000_DIALECT = create_engine(URL.create("postgresql+pg8000"), creator=lambda: None).dialect


def _section(title: str, end: str) -> str:
    return SPEC.split(title, 1)[1].split(end, 1)[0]


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


# ============================================================================================================ M1


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


def test_m1_the_records_state_production_s_pg8000_interface_and_ci_s():
    # What the records state, read from the installed code: the connector's pg8000 adapter calls pg8000.dbapi.connect,
    # the connector uses that adapter for "pg8000", and app.core.db asks the connector for pg8000 on production's
    # engine; a postgresql+pg8000:// URL loads the pg8000 module, whose connect is the legacy interface.
    assert "pg8000.dbapi.connect(" in inspect.getsource(connector_pg8000.connect)
    assert '"pg8000": pg8000.connect' in inspect.getsource(connector_module)
    db_source = inspect.getsource(db_module)
    assert 'connector.connect(connection_name, "pg8000"' in db_source
    assert 'create_engine(URL.create("postgresql+pg8000"), creator=get_cloud_sql_connection' in db_source
    assert PGDialect_pg8000.import_dbapi() is pg8000 and "Connection(" in inspect.getsource(pg8000.connect)

    entry = _section("### 7.19 MOD `app/core/db.py`", "### 7.20")
    bullet = next(line for line in entry.splitlines() if line.startswith("- **pg8000's two interfaces raise different classes**"))
    for needed in ("`pg8000.dbapi.connect`", "plain `DatabaseError`, 23505 included", "legacy `pg8000.connect`",
                   "CI's pg8000 leg", "does not reproduce production's classes", "`test_m1_*`"):
        assert needed in bullet, needed
    comment = db_source.split("_SQLSTATE_CLASSES: dict", 1)[0].rsplit("\n\n", 1)[1]
    for needed in ("pg8000.dbapi.connect", "plain DatabaseError, 23505 included", "legacy pg8000.connect", "CI's pg8000 leg"):
        assert needed in comment, needed
    ci_comment = CI.split("  api-postgres-driver:", 1)[0].rsplit("\n\n", 1)[1]
    spec_14 = next(line for line in _section("## 14.", "## 15.").splitlines() if line.startswith("- `api-postgres-driver` runs"))
    spec_16 = next(line for line in _section("## 16.", "## 17.").splitlines() if line.startswith("| DI-46 |"))
    strategy = next(line for line in STRATEGY.splitlines() if "once with psycopg and once with pg8000" in line)
    # The register's DI-46 row and the evidence package's texts are checked by its 00_meta/check_records.py (check_m1_*).
    records = {"ci": ci_comment, "spec 14": spec_14, "spec 16": spec_16, "test strategy": strategy}
    for name, record in records.items():
        assert "pg8000.dbapi.connect" in record and "legacy pg8000.connect" in record.replace("`", "") and "test_m1_*" in record, name
    # No record says pg8000 raises IntegrityError only for 23505, or that pg8000 itself raises ProgrammingError for
    # every other server error, without naming the interface.
    texts = {"spec": SPEC, "test strategy": STRATEGY, "ci": CI, "app/core/db.py": db_source}
    for name, body in texts.items():
        assert not re.search(r"IntegrityError`? only for 23505", body), name
        assert "pg8000 (the production driver) raises" not in body, name


# ============================================================================================================ M2


def _row(fact: str) -> list[str]:
    line = next(line for line in AUTHORITATIVE_SPEC.splitlines() if line.startswith(f"| {fact} |"))
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _added_names(line: str) -> list[str]:
    tail = line.split(" adds ", 1)[1]
    sentence = re.split(r"\.(?:\s|$)|\(| \|", tail, maxsplit=1)[0]
    return re.findall(r"`([A-Z][A-Z0-9.-]+)`", sentence)


def test_m2_spec_0_2_m24_lists_v1_s_keys_and_names_every_owner_decision_v2_adds():
    _, fact, consequence = _row("M24")
    assert re.search(r"top-level keys: `([^`]+)`", fact).group(1).split(", ") == list(V1_RAW)
    assert re.search(r"`owner_decisions` holds `([^`]+)`", fact).group(1).split(", ") == list(V1_RAW["owner_decisions"])
    # "v2 keeps every v1 block"; "keeps those four unchanged and adds" the rest.
    assert consequence.startswith("v2 keeps every v1 block") and set(V1_RAW) <= set(V2_RAW)
    assert "keeps those four unchanged" in consequence and len(V1_RAW["owner_decisions"]) == 4
    assert all(V2_RAW["owner_decisions"][name] == value for name, value in V1_RAW["owner_decisions"].items())
    added = set(V2_RAW["owner_decisions"]) - set(V1_RAW["owner_decisions"])
    assert set(_added_names(consequence)) == added == {"D-19", "D-12", "PLAN-3.3", "PLAN-12.8"}
    # 5.1's blocks copied unchanged are unchanged, and the blocks it changes differ.
    bullet = next(line for line in _section("### 5.1 File", "### 5.2").splitlines() if line.startswith("- Blocks copied unchanged:"))
    unchanged = re.findall(r"`([a-z_]+)`", bullet.split(". ", 1)[0])
    assert unchanged and all(V2_RAW[name] == V1_RAW[name] for name in unchanged)
    assert {name for name in V1_RAW if V1_RAW[name] != V2_RAW[name]} == {"package_version", "schema_version", "phase", "abstention", "owner_decisions"}


def test_m2_every_line_that_says_what_v2_adds_to_owner_decisions_names_all_four():
    added = set(V2_RAW["owner_decisions"]) - set(V1_RAW["owner_decisions"])
    # The phase record's lines are checked by the evidence package's 00_meta/check_records.py (check_m2_*).
    texts = {"spec 0-17": AUTHORITATIVE_SPEC, "test strategy": STRATEGY}
    checked = 0
    for name, body in texts.items():
        for line in body.splitlines():
            if "owner_decisions" in line and " adds " in line:
                assert set(_added_names(line)) == added, (name, line[:80])
                checked += 1
    assert checked >= 2  # M24 and 5.1
    assert "adds D-19 and D-12" not in AUTHORITATIVE_SPEC
