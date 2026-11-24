from dataclasses import dataclass

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


# Columns added to tables that may already exist (create_all never alters a table), each in its own short
# transaction before the main one: an ALTER takes an ACCESS EXCLUSIVE lock, and taken inside the main transaction it
# would be held across every guard below, so a request that locks the same tables in another order could deadlock
# with start-up (spec 18.8 F8). On PostgreSQL each waits at most COLUMN_LOCK_TIMEOUT_MS for its lock; past that the
# start-up attempt fails and _initialize_database retries it.
COLUMN_LOCK_TIMEOUT_MS = 5000
ADDED_COLUMNS = (
    # Whether a tutor turn expects a ledger record (spec 18.8 F12); null for turns an earlier image created.
    ("tutor_turns", "ledger_record_expected", "BOOLEAN"),
    # The claim token of an Idempotency-Key claim (spec 18.8 F13); tables made by an unreleased Phase 3 build lack it.
    ("tutor_turn_idempotency", "claim_token", "VARCHAR(32)"),
)


def _add_missing_columns(engine: Engine) -> None:
    for table, column, column_type in ADDED_COLUMNS:
        with engine.begin() as connection:
            inspector = inspect(connection)
            if table not in set(inspector.get_table_names()):
                continue
            if column in {existing["name"] for existing in inspector.get_columns(table)}:
                continue
            if connection.dialect.name == "postgresql":
                connection.exec_driver_sql(f"SET LOCAL lock_timeout = '{int(COLUMN_LOCK_TIMEOUT_MS)}ms'")
                connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {column_type}")
            else:
                connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def run_schema_upgrades(engine: Engine) -> None:
    _add_missing_columns(engine)
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
            head_columns = {column["name"] for column in inspector.get_columns("response_ledger_head")}
            if "started_at" not in head_columns:
                # A head table made before the ledger start marker existed (an unreleased Phase 3 build; spec 18.7 E6).
                column_type = "TIMESTAMP WITH TIME ZONE" if connection.dialect.name == "postgresql" else "DATETIME"
                connection.exec_driver_sql(f"ALTER TABLE response_ledger_head ADD COLUMN started_at {column_type}")
            _guard_response_ledger(connection)
        if set(V3_GUARDED_TABLES) <= tables:
            _guard_v3_tables(connection)
            if "ehmf_stops" in tables:
                _guard_ehmf_tables(connection)
            if set(RANKING_APPEND_ONLY_TABLES) <= tables:
                _guard_ranking_tables(connection)


def _guard_security_events(connection: Connection) -> None:
    # The security log is append-only (task 1.7): no UPDATE, no TRUNCATE, and DELETE only of rows past the
    # retention period. Checked on every start and re-created when not current (on PostgreSQL only then, spec 18.8
    # F8; SQLite re-creates its triggers each start), so a changed retention period takes effect: the function body
    # then differs from the catalog's.
    # No '%' in these statements: psycopg would read it as a parameter marker.
    days = int(SECURITY_EVENT_RETENTION_DAYS)
    if connection.dialect.name == "postgresql":
        _postgres_guard(
            connection,
            functions={
                "security_events_append_only": (
                    "\n"
                    "BEGIN\n"
                    "    IF TG_OP = 'DELETE' THEN\n"
                    f"        IF OLD.created_at < now() - interval '{days} days' THEN\n"
                    "            RETURN OLD;\n"
                    "        END IF;\n"
                    "    END IF;\n"
                    "    RAISE EXCEPTION USING MESSAGE = 'security_events is append-only: ' || TG_OP || ' refused';\n"
                    "END\n"
                ),
            },
            triggers=(
                Trigger("security_events_append_only", "security_events", ("UPDATE", "DELETE"), "ROW", "security_events_append_only"),
                Trigger("security_events_no_truncate", "security_events", ("TRUNCATE",), "STATEMENT", "security_events_append_only"),
            ),
            lock_order=("security_events",),
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
    # Checked on every start and re-created when not current, like the security-log guard (spec 18.8 F8). No '%' in
    # these statements (psycopg parameters).
    if connection.dialect.name == "postgresql":
        _postgres_guard(
            connection,
            functions={
                "corpus_spans_append_only": (
                    "\n"
                    "BEGIN\n"
                    "    RAISE EXCEPTION USING MESSAGE = 'corpus_spans is append-only: ' || TG_OP || ' refused';\n"
                    "END\n"
                ),
            },
            triggers=(
                Trigger("corpus_spans_append_only", "corpus_spans", ("UPDATE", "DELETE"), "ROW", "corpus_spans_append_only"),
                Trigger("corpus_spans_no_truncate", "corpus_spans", ("TRUNCATE",), "STATEMENT", "corpus_spans_append_only"),
            ),
            lock_order=("corpus_spans",),
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


@dataclass(frozen=True)
class Trigger:
    """One PostgreSQL trigger: BEFORE <events> ON <table> FOR EACH <level> EXECUTE FUNCTION <function>()."""

    name: str
    table: str
    events: tuple[str, ...]
    level: str
    function: str

    @property
    def statement(self) -> str:
        return (f"CREATE OR REPLACE TRIGGER {self.name} BEFORE {' OR '.join(self.events)} ON {self.table} "
                f"FOR EACH {self.level} EXECUTE FUNCTION {self.function}()")

    @property
    def tgtype(self) -> int:
        # pg_trigger.tgtype bits (PostgreSQL's TRIGGER_TYPE_*): ROW 1, BEFORE 2, INSERT 4, DELETE 8, UPDATE 16,
        # TRUNCATE 32.
        bits = {"INSERT": 4, "DELETE": 8, "UPDATE": 16, "TRUNCATE": 32}
        return (1 if self.level == "ROW" else 0) + 2 + sum(bits[event] for event in self.events)


def _quoted(names) -> str:
    # Constant identifiers of this module only (never input), as SQL string literals.
    return ", ".join(f"'{name}'" for name in sorted(names))


def postgres_guard_current(connection: Connection, functions: dict[str, str], triggers: tuple[Trigger, ...]) -> bool:
    """True when every guard function has exactly this body (plpgsql, no arguments, returns trigger) and every trigger
    exists on its table, enabled, unconditional, with these events, level and function. Catalog reads only: no lock
    on any table."""
    found = connection.exec_driver_sql(
        "SELECT p.proname, p.prosrc FROM pg_catalog.pg_proc p "
        "JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace "
        "JOIN pg_catalog.pg_language l ON l.oid = p.prolang "
        "WHERE n.nspname = current_schema() AND l.lanname = 'plpgsql' AND p.pronargs = 0 "
        "AND p.prorettype = 'pg_catalog.trigger'::pg_catalog.regtype "
        f"AND p.proname IN ({_quoted(functions)})"
    ).all()
    if {(row[0], row[1]) for row in found} != set(functions.items()) or len(found) != len(functions):
        return False
    present = connection.exec_driver_sql(
        "SELECT t.tgname, c.relname, p.proname, t.tgtype, t.tgenabled::text, t.tgqual IS NULL, t.tgnargs "
        "FROM pg_catalog.pg_trigger t "
        "JOIN pg_catalog.pg_class c ON c.oid = t.tgrelid "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_catalog.pg_proc p ON p.oid = t.tgfoid "
        f"WHERE NOT t.tgisinternal AND n.nspname = current_schema() AND t.tgname IN ({_quoted(t.name for t in triggers)})"
    ).all()
    expected = {(t.name, t.table, t.function, t.tgtype, "O", True, 0) for t in triggers}
    return {tuple(row) for row in present} == expected and len(present) == len(triggers)


def _postgres_guard(connection: Connection, *, functions: dict[str, str], triggers: tuple[Trigger, ...], lock_order: tuple[str, ...]) -> bool:
    """Create or replace the guard functions and triggers, unless they are already current (spec 18.8 F8).

    CREATE OR REPLACE TRIGGER takes a SHARE ROW EXCLUSIVE lock on its table until start-up commits. Taken on every
    start, and in another order than the writers take theirs, it deadlocked a live ledger append: the append locks
    response_ledger_head, then response_ledger; the guard locked response_ledger first. So the guard now runs no DDL
    when the catalogs already hold exactly these definitions, and otherwise first locks its tables in lock_order, the
    writers' own order, then replaces them. Returns True when it ran the DDL."""
    if postgres_guard_current(connection, functions, triggers):
        return False
    connection.exec_driver_sql(f"LOCK TABLE {', '.join(lock_order)} IN SHARE ROW EXCLUSIVE MODE")
    for name, body in functions.items():
        connection.exec_driver_sql(f"CREATE OR REPLACE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $${body}$$")
    for trigger in triggers:
        connection.exec_driver_sql(trigger.statement)
        # A disabled trigger is a drift too; under the lock already held, enabling it takes no further lock.
        connection.exec_driver_sql(f"ALTER TABLE {trigger.table} ENABLE TRIGGER {trigger.name}")
    return True


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


RESPONSE_LEDGER_FUNCTION_BODIES = {
    "response_ledger_append_only": (
        "\n"
        "BEGIN\n"
        "    RAISE EXCEPTION USING MESSAGE = 'response_ledger is append-only: ' || TG_OP || ' refused';\n"
        "END\n"
    ),
    "response_ledger_links_to_chain": (
        "\n"
        "DECLARE last_seq integer; last_hash text;\n"
        "BEGIN\n"
        "    SELECT seq, record_hash INTO last_seq, last_hash FROM response_ledger ORDER BY seq DESC LIMIT 1;\n"
        "    IF last_seq IS NULL THEN last_seq := 0; last_hash := repeat('0', 64); END IF;\n"
        "    IF NEW.seq <> last_seq + 1 OR NEW.prev_hash <> last_hash THEN\n"
        "        RAISE EXCEPTION USING MESSAGE = 'response_ledger appends must extend the chain';\n"
        "    END IF;\n"
        "    RETURN NEW;\n"
        "END\n"
    ),
    "response_ledger_head_forward_only": (
        "\n"
        "BEGIN\n"
        "    IF TG_OP <> 'UPDATE' THEN\n"
        "        RAISE EXCEPTION USING MESSAGE = 'response_ledger_head moves forward only: ' || TG_OP || ' refused';\n"
        "    END IF;\n"
        "    IF NEW.chain = OLD.chain AND NEW.seq = OLD.seq + 1 AND NEW.started_at IS NOT DISTINCT FROM OLD.started_at\n"
        "       AND EXISTS (SELECT 1 FROM response_ledger WHERE seq = NEW.seq AND record_hash = NEW.record_hash) THEN\n"
        "        RETURN NEW;\n"
        "    END IF;\n"
        "    RAISE EXCEPTION USING MESSAGE = 'response_ledger_head moves forward only: ' || TG_OP || ' refused';\n"
        "END\n"
    ),
}
RESPONSE_LEDGER_TRIGGERS = (
    Trigger("response_ledger_head_forward_only", "response_ledger_head", ("UPDATE", "DELETE"), "ROW", "response_ledger_head_forward_only"),
    Trigger("response_ledger_head_no_truncate", "response_ledger_head", ("TRUNCATE",), "STATEMENT", "response_ledger_head_forward_only"),
    Trigger("response_ledger_append_only", "response_ledger", ("UPDATE", "DELETE"), "ROW", "response_ledger_append_only"),
    Trigger("response_ledger_no_truncate", "response_ledger", ("TRUNCATE",), "STATEMENT", "response_ledger_append_only"),
    Trigger("response_ledger_links_to_chain", "response_ledger", ("INSERT",), "ROW", "response_ledger_links_to_chain"),
)


def _guard_response_ledger(connection: Connection) -> None:
    # The tutor response ledger is append-only and hash-chained (plan task 3.8, R-22): a record is never updated,
    # deleted or truncated; an insert must extend the chain (seq = last + 1, prev_hash = the last record_hash); the
    # head row moves forward one committed record at a time, keeps its started_at (spec 18.7 E6) and is never deleted
    # or truncated. Checked on every start, like the other guards, and re-created only when not current, with the two
    # tables locked head first, the append's own order (spec 18.8 F8). No '%' in these statements (psycopg and pg8000
    # parameter markers).
    if connection.dialect.name == "postgresql":
        _postgres_guard(
            connection,
            functions=RESPONSE_LEDGER_FUNCTION_BODIES,
            triggers=RESPONSE_LEDGER_TRIGGERS,
            # The append's order: head first, then the records (ledger.append_ledger_entry).
            lock_order=("response_ledger_head", "response_ledger"),
        )
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
            "WHEN NEW.seq != OLD.seq + 1 OR NEW.chain != OLD.chain OR NEW.started_at IS NOT OLD.started_at "
            "OR NOT EXISTS (SELECT 1 FROM response_ledger WHERE seq = NEW.seq AND record_hash = NEW.record_hash) "
            "BEGIN SELECT RAISE(ABORT, 'response_ledger_head moves forward only: UPDATE refused'); END",
            "CREATE TRIGGER response_ledger_head_no_delete BEFORE DELETE ON response_ledger_head "
            "BEGIN SELECT RAISE(ABORT, 'response_ledger_head moves forward only: DELETE refused'); END",
        ):
            connection.exec_driver_sql(statement)


# The V3 tables (Phase 6 spec 8): the gold store, the draws, the X5 events, the model versions seen and the scan log are
# append-only (UPDATE, DELETE and TRUNCATE refused); a gold insert must extend its chain (the response ledger's rule);
# the queue keeps every item (DELETE and TRUNCATE refused) and moves it forward only: an UPDATE keeps the item's
# identity, sets each closing column once, never lowers its exposure or round, never clears held, never drops a
# trigger, reason or EHMF type, and moves state queued -> adjudicated -> applied only (the workflow's own writes:
# queue.upsert_item, refresh_exposure, adjudicate, apply_item). The two user-keyed tables (v3_claims, v3_flags) have no
# trigger, so erasure deletes their rows.
V3_APPEND_ONLY_TABLES = ("v3_model_versions", "v3_events", "v3_draws", "v3_gold_labels", "v3_scans")
V3_GUARDED_TABLES = ("v3_model_versions", "v3_events", "v3_draws", "v3_queue_items", "v3_gold_labels", "v3_scans")
V3_QUEUE_FIXED_COLUMNS = ("item_id", "ledger_seq", "claim_key", "subject", "record_kind", "response_digest", "k", "double_review",
                          "enqueued_at", "package_version", "package_sha256")
V3_QUEUE_WRITE_ONCE_COLUMNS = ("closed_at", "final_gold_seq", "applied_at", "applied_by_digest", "applied_client_key")
V3_QUEUE_RISING_COLUMNS = ("exposure", "review_round")
V3_QUEUE_STATE_MOVES = (("queued", "adjudicated"), ("adjudicated", "applied"))


def _v3_queue_sets() -> dict[str, tuple[str, ...]]:
    # The comma-joined set columns and their vocabularies (queue.join writes sorted, comma-joined members).
    from app.services.ehmf.vocabulary import EHMF_TYPES
    from app.services.v3.rules import QUEUE_REASONS_V7, TRIGGERS

    # Every queue reason any package names (QUEUE_REASONS_V7 holds Phase 6's four and the ranking fallback's).
    return {"triggers": TRIGGERS, "reasons": QUEUE_REASONS_V7, "ehmf_types": EHMF_TYPES}


def _v3_queue_forward_only_postgres() -> str:
    """The conditions under which an UPDATE of v3_queue_items is a forward move (PostgreSQL)."""
    moves = " OR ".join(f"(OLD.state = '{old}' AND NEW.state = '{new}')" for old, new in V3_QUEUE_STATE_MOVES)
    return "\n       AND ".join((
        *(f"NEW.{column} IS NOT DISTINCT FROM OLD.{column}" for column in V3_QUEUE_FIXED_COLUMNS),
        *(f"(OLD.{column} IS NULL OR NEW.{column} IS NOT DISTINCT FROM OLD.{column})" for column in V3_QUEUE_WRITE_ONCE_COLUMNS),
        *(f"NEW.{column} >= OLD.{column}" for column in V3_QUEUE_RISING_COLUMNS),
        "(NEW.held OR NOT OLD.held)",
        f"(NEW.state = OLD.state OR {moves})",
        *(f"string_to_array(NEW.{column}, ',') @> string_to_array(OLD.{column}, ',')" for column in _v3_queue_sets()),
    ))


def _v3_queue_backward_sqlite() -> str:
    """The conditions under which an UPDATE of v3_queue_items is refused (SQLite; the sets over their vocabularies)."""
    moves = " OR ".join(f"(OLD.state = '{old}' AND NEW.state = '{new}')" for old, new in V3_QUEUE_STATE_MOVES)
    return " OR ".join((
        *(f"NEW.{column} IS NOT OLD.{column}" for column in V3_QUEUE_FIXED_COLUMNS),
        *(f"(OLD.{column} IS NOT NULL AND NEW.{column} IS NOT OLD.{column})" for column in V3_QUEUE_WRITE_ONCE_COLUMNS),
        *(f"NEW.{column} < OLD.{column}" for column in V3_QUEUE_RISING_COLUMNS),
        "(OLD.held AND NOT NEW.held)",
        f"NOT (NEW.state = OLD.state OR {moves})",
        *(f"(instr(',' || OLD.{column} || ',', ',{member},') > 0 AND instr(',' || NEW.{column} || ',', ',{member},') = 0)"
          for column, members in _v3_queue_sets().items() for member in members),
    ))
V3_FUNCTION_BODIES = {
    "v3_append_only": (
        "\n"
        "BEGIN\n"
        "    RAISE EXCEPTION USING MESSAGE = TG_TABLE_NAME || ' is append-only: ' || TG_OP || ' refused';\n"
        "END\n"
    ),
    "v3_gold_links_to_chain": (
        "\n"
        "DECLARE last_seq integer; last_hash text;\n"
        "BEGIN\n"
        "    SELECT seq, record_hash INTO last_seq, last_hash FROM v3_gold_labels ORDER BY seq DESC LIMIT 1;\n"
        "    IF last_seq IS NULL THEN last_seq := 0; last_hash := repeat('0', 64); END IF;\n"
        "    IF NEW.seq <> last_seq + 1 OR NEW.prev_hash <> last_hash THEN\n"
        "        RAISE EXCEPTION USING MESSAGE = 'v3_gold_labels appends must extend the chain';\n"
        "    END IF;\n"
        "    RETURN NEW;\n"
        "END\n"
    ),
    "v3_queue_items_keep": (
        "\n"
        "BEGIN\n"
        "    IF TG_OP <> 'UPDATE' THEN\n"
        "        RAISE EXCEPTION USING MESSAGE = 'v3_queue_items keeps every item: ' || TG_OP || ' refused';\n"
        "    END IF;\n"
        f"    IF {_v3_queue_forward_only_postgres()} THEN\n"
        "        RETURN NEW;\n"
        "    END IF;\n"
        "    RAISE EXCEPTION USING MESSAGE = 'v3_queue_items moves forward only: UPDATE refused';\n"
        "END\n"
    ),
}
V3_TRIGGERS = (
    *(Trigger(f"{table}_append_only", table, ("UPDATE", "DELETE"), "ROW", "v3_append_only") for table in V3_APPEND_ONLY_TABLES),
    *(Trigger(f"{table}_no_truncate", table, ("TRUNCATE",), "STATEMENT", "v3_append_only") for table in V3_APPEND_ONLY_TABLES),
    Trigger("v3_gold_labels_links_to_chain", "v3_gold_labels", ("INSERT",), "ROW", "v3_gold_links_to_chain"),
    Trigger("v3_queue_items_keep", "v3_queue_items", ("UPDATE", "DELETE"), "ROW", "v3_queue_items_keep"),
    Trigger("v3_queue_items_no_truncate", "v3_queue_items", ("TRUNCATE",), "STATEMENT", "v3_queue_items_keep"),
)
V3_SQLITE_TRIGGERS = (
    *(f"{table}_no_update" for table in V3_APPEND_ONLY_TABLES),
    *(f"{table}_no_delete" for table in V3_APPEND_ONLY_TABLES),
    "v3_gold_labels_links_to_chain",
    "v3_queue_items_no_delete",
    "v3_queue_items_forward_only",
)


# The EHMF stops (Phase 7 spec 8): append-only, through Phase 6's v3_append_only() (created with the V3 guards, which
# run first). Checked on every start and re-created only when not current; no '%' in these statements.
EHMF_TRIGGERS = (
    Trigger("ehmf_stops_append_only", "ehmf_stops", ("UPDATE", "DELETE"), "ROW", "v3_append_only"),
    Trigger("ehmf_stops_no_truncate", "ehmf_stops", ("TRUNCATE",), "STATEMENT", "v3_append_only"),
)
EHMF_SQLITE_TRIGGERS = ("ehmf_stops_no_update", "ehmf_stops_no_delete")


def _guard_ehmf_tables(connection: Connection) -> None:
    if connection.dialect.name == "postgresql":
        _postgres_guard(connection, functions={"v3_append_only": V3_FUNCTION_BODIES["v3_append_only"]}, triggers=EHMF_TRIGGERS,
                        lock_order=("ehmf_stops",))
        return
    if connection.dialect.name == "sqlite":
        for name in EHMF_SQLITE_TRIGGERS:
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
        connection.exec_driver_sql("CREATE TRIGGER ehmf_stops_no_update BEFORE UPDATE ON ehmf_stops "
                                   "BEGIN SELECT RAISE(ABORT, 'ehmf_stops is append-only: UPDATE refused'); END")
        connection.exec_driver_sql("CREATE TRIGGER ehmf_stops_no_delete BEFORE DELETE ON ehmf_stops "
                                   "BEGIN SELECT RAISE(ABORT, 'ehmf_stops is append-only: DELETE refused'); END")


# The ranking event log and scan rows (Phase 9 spec 8.1): append-only, through Phase 6's v3_append_only() (created with
# the V3 guards, which run first). ranking_states and ranking_incumbents are derived caches every scan rewrites.
RANKING_APPEND_ONLY_TABLES = ("ranking_events", "ranking_scans")
RANKING_TRIGGERS = (
    *(Trigger(f"{table}_append_only", table, ("UPDATE", "DELETE"), "ROW", "v3_append_only") for table in RANKING_APPEND_ONLY_TABLES),
    *(Trigger(f"{table}_no_truncate", table, ("TRUNCATE",), "STATEMENT", "v3_append_only") for table in RANKING_APPEND_ONLY_TABLES),
)
RANKING_SQLITE_TRIGGERS = (*(f"{table}_no_update" for table in RANKING_APPEND_ONLY_TABLES),
                           *(f"{table}_no_delete" for table in RANKING_APPEND_ONLY_TABLES))


def _guard_ranking_tables(connection: Connection) -> None:
    if connection.dialect.name == "postgresql":
        _postgres_guard(connection, functions={"v3_append_only": V3_FUNCTION_BODIES["v3_append_only"]}, triggers=RANKING_TRIGGERS,
                        lock_order=RANKING_APPEND_ONLY_TABLES)
        return
    if connection.dialect.name == "sqlite":
        for name in RANKING_SQLITE_TRIGGERS:
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
        for table in RANKING_APPEND_ONLY_TABLES:
            connection.exec_driver_sql(f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
                                       f"BEGIN SELECT RAISE(ABORT, '{table} is append-only: UPDATE refused'); END")
            connection.exec_driver_sql(f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
                                       f"BEGIN SELECT RAISE(ABORT, '{table} is append-only: DELETE refused'); END")


def _guard_v3_tables(connection: Connection) -> None:
    # Checked on every start and re-created only when not current, with the tables locked in the writers' order (the
    # scan: model versions, events, draws, queue items, its scan row; an adjudication: queue items, then the gold store;
    # spec 18.8 F8 of Phase 3). No '%' in these statements (psycopg and pg8000 parameter markers).
    if connection.dialect.name == "postgresql":
        _postgres_guard(connection, functions=V3_FUNCTION_BODIES, triggers=V3_TRIGGERS, lock_order=V3_GUARDED_TABLES)
        return
    if connection.dialect.name == "sqlite":
        for name in V3_SQLITE_TRIGGERS:
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
        for table in V3_APPEND_ONLY_TABLES:
            connection.exec_driver_sql(f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
                                       f"BEGIN SELECT RAISE(ABORT, '{table} is append-only: UPDATE refused'); END")
            connection.exec_driver_sql(f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
                                       f"BEGIN SELECT RAISE(ABORT, '{table} is append-only: DELETE refused'); END")
        connection.exec_driver_sql(
            "CREATE TRIGGER v3_gold_labels_links_to_chain BEFORE INSERT ON v3_gold_labels "
            "WHEN NEW.seq != (SELECT COALESCE(MAX(seq), 0) + 1 FROM v3_gold_labels) "
            f"OR NEW.prev_hash != COALESCE((SELECT record_hash FROM v3_gold_labels ORDER BY seq DESC LIMIT 1), '{GENESIS}') "
            "BEGIN SELECT RAISE(ABORT, 'v3_gold_labels appends must extend the chain'); END")
        connection.exec_driver_sql("CREATE TRIGGER v3_queue_items_no_delete BEFORE DELETE ON v3_queue_items "
                                   "BEGIN SELECT RAISE(ABORT, 'v3_queue_items keeps every item: DELETE refused'); END")
        connection.exec_driver_sql(f"CREATE TRIGGER v3_queue_items_forward_only BEFORE UPDATE ON v3_queue_items WHEN {_v3_queue_backward_sqlite()} "
                                   "BEGIN SELECT RAISE(ABORT, 'v3_queue_items moves forward only: UPDATE refused'); END")
