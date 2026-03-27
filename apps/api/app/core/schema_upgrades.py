from sqlalchemy import Engine, inspect


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
                connection.exec_driver_sql(
                    "ALTER TABLE project_submissions ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT 0"
                )

        for statement in INDEX_STATEMENTS:
            connection.exec_driver_sql(statement)
