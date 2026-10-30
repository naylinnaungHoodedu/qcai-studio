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
