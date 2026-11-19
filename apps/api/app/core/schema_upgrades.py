from sqlalchemy import Connection, Engine, inspect

from app.services.retention import SECURITY_EVENT_RETENTION_DAYS


INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS ix_notes_user_id_lesson_slug_created_at ON notes (user_id, lesson_slug, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_quiz_attempts_user_id_lesson_slug_created_at ON quiz_attempts (user_id, lesson_slug, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_qa_interactions_user_id_lesson_slug_created_at ON qa_interactions (user_id, lesson_slug, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_analytics_events_user_id_event_type ON analytics_events (user_id, event_type)",
    "CREATE INDEX IF NOT EXISTS ix_builder_runs_user_id_scenario_slug ON builder_runs (user_id, scenario_slug)",
    "CREATE INDEX IF NOT EXISTS ix_learning_pulses_user_id_created_at ON learning_pulses (user_id, created_at)",
]


def run_schema_upgrades(engine: Engine) -> None:
    with engine.begin() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        if "project_submissions" in tables:
            submission_columns = {column["name"] for column in inspector.get_columns("project_submissions")}
            if "is_deleted" not in submission_columns:
                # FALSE, not 0: PostgreSQL rejects an integer default on a boolean column; SQLite accepts both.
                connection.exec_driver_sql(
                    "ALTER TABLE project_submissions ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT FALSE"
                )

        for statement in INDEX_STATEMENTS:
            connection.exec_driver_sql(statement)

        if "security_events" in tables:
            _guard_security_events(connection)
        if "corpus_spans" in tables:
            _guard_corpus_spans(connection)
        if {"response_ledger", "response_ledger_head"} <= tables:
            _guard_response_ledger(connection)


def _guard_security_events(connection: Connection) -> None:
    # The security log is append-only (task 1.7): no UPDATE, no TRUNCATE, and DELETE only of rows past the
    # retention period. Re-created on every start, so a changed retention period takes effect.
    # No '%' in these statements: psycopg would read it as a parameter marker.
    days = int(SECURITY_EVENT_RETENTION_DAYS)
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION security_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$\n"
            "BEGIN\n"
            "    IF TG_OP = 'DELETE' THEN\n"
            f"        IF OLD.created_at < now() - interval '{days} days' THEN\n"
            "            RETURN OLD;\n"
            "        END IF;\n"
            "    END IF;\n"
            "    RAISE EXCEPTION USING MESSAGE = 'security_events is append-only: ' || TG_OP || ' refused';\n"
            "END\n"
            "$$"
        )
        connection.exec_driver_sql(
            "CREATE OR REPLACE TRIGGER security_events_append_only BEFORE UPDATE OR DELETE ON security_events "
            "FOR EACH ROW EXECUTE FUNCTION security_events_append_only()"
        )
        connection.exec_driver_sql(
            "CREATE OR REPLACE TRIGGER security_events_no_truncate BEFORE TRUNCATE ON security_events "
            "FOR EACH STATEMENT EXECUTE FUNCTION security_events_append_only()"
        )
        return
    if connection.dialect.name == "sqlite":
        # SQLite stores these timestamps as UTC text, which sorts like the time it names.
        for statement in (
            "DROP TRIGGER IF EXISTS security_events_no_update",
            "CREATE TRIGGER security_events_no_update BEFORE UPDATE ON security_events "
            "BEGIN SELECT RAISE(ABORT, 'security_events is append-only: UPDATE refused'); END",
            "DROP TRIGGER IF EXISTS security_events_retention_delete",
            "CREATE TRIGGER security_events_retention_delete BEFORE DELETE ON security_events "
            f"WHEN OLD.created_at >= datetime('now', '-{days} days') "
            "BEGIN SELECT RAISE(ABORT, 'security_events is append-only: DELETE refused inside the retention period'); END",
        ):
            connection.exec_driver_sql(statement)


def _guard_corpus_spans(connection: Connection) -> None:
    # Span identity is append-only (plan Phase 2 task 2.2): stored citations must keep resolving, so a span row is
    # never updated, deleted or truncated. Inserts use ON CONFLICT DO NOTHING, which fires no UPDATE trigger.
    # Re-created on every start, like the security-log guard. No '%' in these statements (psycopg parameters).
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION corpus_spans_append_only() RETURNS trigger LANGUAGE plpgsql AS $$\n"
            "BEGIN\n"
            "    RAISE EXCEPTION USING MESSAGE = 'corpus_spans is append-only: ' || TG_OP || ' refused';\n"
            "END\n"
            "$$"
        )
        connection.exec_driver_sql(
            "CREATE OR REPLACE TRIGGER corpus_spans_append_only BEFORE UPDATE OR DELETE ON corpus_spans "
            "FOR EACH ROW EXECUTE FUNCTION corpus_spans_append_only()"
        )
        connection.exec_driver_sql(
            "CREATE OR REPLACE TRIGGER corpus_spans_no_truncate BEFORE TRUNCATE ON corpus_spans "
            "FOR EACH STATEMENT EXECUTE FUNCTION corpus_spans_append_only()"
        )
        return
    if connection.dialect.name == "sqlite":
        for statement in (
            "DROP TRIGGER IF EXISTS corpus_spans_no_update",
            "CREATE TRIGGER corpus_spans_no_update BEFORE UPDATE ON corpus_spans "
            "BEGIN SELECT RAISE(ABORT, 'corpus_spans is append-only: UPDATE refused'); END",
            "DROP TRIGGER IF EXISTS corpus_spans_no_delete",
            "CREATE TRIGGER corpus_spans_no_delete BEFORE DELETE ON corpus_spans "
            "BEGIN SELECT RAISE(ABORT, 'corpus_spans is append-only: DELETE refused'); END",
        ):
            connection.exec_driver_sql(statement)


GENESIS = "0" * 64
RESPONSE_LEDGER_SQLITE_TRIGGERS = (
    "response_ledger_no_update",
    "response_ledger_no_delete",
    "response_ledger_links_to_chain",
    "response_ledger_head_forward_only",
    "response_ledger_head_no_delete",
)
RESPONSE_LEDGER_POSTGRES_TRIGGERS = (
    ("response_ledger_append_only", "response_ledger"),
    ("response_ledger_no_truncate", "response_ledger"),
    ("response_ledger_links_to_chain", "response_ledger"),
    ("response_ledger_head_forward_only", "response_ledger_head"),
    ("response_ledger_head_no_truncate", "response_ledger_head"),
)
RESPONSE_LEDGER_POSTGRES_FUNCTIONS = (
    "response_ledger_append_only",
    "response_ledger_links_to_chain",
    "response_ledger_head_forward_only",
)


def _guard_response_ledger(connection: Connection) -> None:
    # The tutor response ledger is append-only and hash-chained (plan task 3.8, R-22): a record is never updated,
    # deleted or truncated; an insert must extend the chain (seq = last + 1, prev_hash = the last record_hash); the
    # head row moves forward one committed record at a time and is never deleted or truncated. Re-created on every
    # start, like the other guards. No '%' in these statements (psycopg and pg8000 parameter markers).
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION response_ledger_append_only() RETURNS trigger LANGUAGE plpgsql AS $$\n"
            "BEGIN\n"
            "    RAISE EXCEPTION USING MESSAGE = 'response_ledger is append-only: ' || TG_OP || ' refused';\n"
            "END\n"
            "$$"
        )
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION response_ledger_links_to_chain() RETURNS trigger LANGUAGE plpgsql AS $$\n"
            "DECLARE last_seq integer; last_hash text;\n"
            "BEGIN\n"
            "    SELECT seq, record_hash INTO last_seq, last_hash FROM response_ledger ORDER BY seq DESC LIMIT 1;\n"
            "    IF last_seq IS NULL THEN last_seq := 0; last_hash := repeat('0', 64); END IF;\n"
            "    IF NEW.seq <> last_seq + 1 OR NEW.prev_hash <> last_hash THEN\n"
            "        RAISE EXCEPTION USING MESSAGE = 'response_ledger appends must extend the chain';\n"
            "    END IF;\n"
            "    RETURN NEW;\n"
            "END\n"
            "$$"
        )
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION response_ledger_head_forward_only() RETURNS trigger LANGUAGE plpgsql AS $$\n"
            "BEGIN\n"
            "    IF TG_OP <> 'UPDATE' THEN\n"
            "        RAISE EXCEPTION USING MESSAGE = 'response_ledger_head moves forward only: ' || TG_OP || ' refused';\n"
            "    END IF;\n"
            "    IF NEW.chain = OLD.chain AND NEW.seq = OLD.seq + 1\n"
            "       AND EXISTS (SELECT 1 FROM response_ledger WHERE seq = NEW.seq AND record_hash = NEW.record_hash) THEN\n"
            "        RETURN NEW;\n"
            "    END IF;\n"
            "    RAISE EXCEPTION USING MESSAGE = 'response_ledger_head moves forward only: ' || TG_OP || ' refused';\n"
            "END\n"
            "$$"
        )
        for statement in (
            "CREATE OR REPLACE TRIGGER response_ledger_append_only BEFORE UPDATE OR DELETE ON response_ledger "
            "FOR EACH ROW EXECUTE FUNCTION response_ledger_append_only()",
            "CREATE OR REPLACE TRIGGER response_ledger_no_truncate BEFORE TRUNCATE ON response_ledger "
            "FOR EACH STATEMENT EXECUTE FUNCTION response_ledger_append_only()",
            "CREATE OR REPLACE TRIGGER response_ledger_links_to_chain BEFORE INSERT ON response_ledger "
            "FOR EACH ROW EXECUTE FUNCTION response_ledger_links_to_chain()",
            "CREATE OR REPLACE TRIGGER response_ledger_head_forward_only BEFORE UPDATE OR DELETE ON response_ledger_head "
            "FOR EACH ROW EXECUTE FUNCTION response_ledger_head_forward_only()",
            "CREATE OR REPLACE TRIGGER response_ledger_head_no_truncate BEFORE TRUNCATE ON response_ledger_head "
            "FOR EACH STATEMENT EXECUTE FUNCTION response_ledger_head_forward_only()",
        ):
            connection.exec_driver_sql(statement)
        return
    if connection.dialect.name == "sqlite":
        for name in RESPONSE_LEDGER_SQLITE_TRIGGERS:
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
        for statement in (
            "CREATE TRIGGER response_ledger_no_update BEFORE UPDATE ON response_ledger "
            "BEGIN SELECT RAISE(ABORT, 'response_ledger is append-only: UPDATE refused'); END",
            "CREATE TRIGGER response_ledger_no_delete BEFORE DELETE ON response_ledger "
            "BEGIN SELECT RAISE(ABORT, 'response_ledger is append-only: DELETE refused'); END",
            "CREATE TRIGGER response_ledger_links_to_chain BEFORE INSERT ON response_ledger "
            "WHEN NEW.seq != (SELECT COALESCE(MAX(seq), 0) + 1 FROM response_ledger) "
            f"OR NEW.prev_hash != COALESCE((SELECT record_hash FROM response_ledger ORDER BY seq DESC LIMIT 1), '{GENESIS}') "
            "BEGIN SELECT RAISE(ABORT, 'response_ledger appends must extend the chain'); END",
            "CREATE TRIGGER response_ledger_head_forward_only BEFORE UPDATE ON response_ledger_head "
            "WHEN NEW.seq != OLD.seq + 1 OR NEW.chain != OLD.chain "
            "OR NOT EXISTS (SELECT 1 FROM response_ledger WHERE seq = NEW.seq AND record_hash = NEW.record_hash) "
            "BEGIN SELECT RAISE(ABORT, 'response_ledger_head moves forward only: UPDATE refused'); END",
            "CREATE TRIGGER response_ledger_head_no_delete BEFORE DELETE ON response_ledger_head "
            "BEGIN SELECT RAISE(ABORT, 'response_ledger_head moves forward only: DELETE refused'); END",
        ):
            connection.exec_driver_sql(statement)
