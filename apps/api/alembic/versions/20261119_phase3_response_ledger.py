"""Phase 3 tutor response ledger: the append-only, hash-chained response_ledger and its chain head (plan Phase 3
task 3.8, G; R-22), and tutor_turn_idempotency, the Idempotency-Key records of POST /tutor/turns (plan 7.3
"mutations carry client keys"; DI-40). This revision had not been applied anywhere when the second table was added
(Phase 3 is unmerged), so the head stays 20261119_phase3_response_ledger (ledger.SCHEMA_REVISION).

Additive and reversible (expand step, plan 13.3). The append-only and chain triggers come from app.core.schema_upgrades,
which checks them at each API start and re-creates them only when they are not current, so the downgrade drops
them with the tables. Append-only evidence is never
dropped by accident: the downgrade refuses while response_ledger holds rows, unless run as
    alembic -x allow_ledger_drop=true downgrade 20261119_phase2_corpus_spans
(an absolute target, never -1: a database built by create_all may carry no stamp, or a Phase 2 one, and -1 would
then fail or reverse the Phase 2 revision instead; check `alembic current` first) after
`python -m app.workers.response_ledger --export <path outside the application tree>`, the in-image worker that
connects as the API does (infra/cloudrun/deployment.md, Phase 3). Dropping the tables ends the R-22 record in the
database; `python -m app.workers.response_ledger --restore <that path>` re-inserts it once the revision is applied
again (spec 18.7 E9, E10, E12). The chain still cannot build an empty database (test_alembic_head_builds_the_orm_schema
stays a strict xfail until the production baseline lands). The chain head's started_at (spec 18.7 E6), and
tutor_turns.ledger_record_expected and tutor_turn_idempotency.claim_token (spec 18.8 F12, F13), were added before
this revision was applied anywhere; app.core.schema_upgrades adds the two columns to tables that already exist.
The downgrade drops ledger_record_expected too: turns made before it then read as made by an image that keeps no
ledger, so run `--coverage-since` before the downgrade and keep its counts with the release evidence.

Revision ID: 20261119_phase3_response_ledger
Revises: 20261119_phase2_corpus_spans
Create Date: 2026-11-19
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "20261119_phase3_response_ledger"
down_revision: Union[str, Sequence[str], None] = "20261119_phase2_corpus_spans"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

POSTGRES_TRIGGERS = (
    ("response_ledger_append_only", "response_ledger"),
    ("response_ledger_no_truncate", "response_ledger"),
    ("response_ledger_links_to_chain", "response_ledger"),
    ("response_ledger_head_forward_only", "response_ledger_head"),
    ("response_ledger_head_no_truncate", "response_ledger_head"),
)
POSTGRES_FUNCTIONS = ("response_ledger_append_only", "response_ledger_links_to_chain", "response_ledger_head_forward_only")


def upgrade() -> None:
    op.create_table(
        "response_ledger",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("response_id", sa.String(length=64), nullable=False),
        sa.Column("delivery", sa.String(length=16), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("shadowed_response_id", sa.String(length=64), nullable=True),
        sa.Column("claim_set_hash", sa.String(length=64), nullable=True),
        sa.Column("entry_schema", sa.String(length=32), nullable=False),
        sa.Column("entry", sa.Text(), nullable=False),
        sa.Column("entry_sha256", sa.String(length=64), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("record_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("response_id", name="uq_response_ledger_response_id"),
        sa.CheckConstraint("delivery IN ('shadow', 'delivered', 'legacy')", name="ck_response_ledger_delivery"),
        sa.CheckConstraint("decision IN ('answer', 'abstain')", name="ck_response_ledger_decision"),
    )
    op.create_index("ix_response_ledger_shadowed_response_id", "response_ledger", ["shadowed_response_id"])
    op.create_index("ix_response_ledger_created_at", "response_ledger", ["created_at"])
    op.create_table(
        "response_ledger_head",
        sa.Column("chain", sa.String(length=32), primary_key=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("record_hash", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    # A turn says whether it expects a ledger record (spec 18.8 F12): null on every turn made before this revision.
    op.add_column("tutor_turns", sa.Column("ledger_record_expected", sa.Boolean(), nullable=True))
    op.create_table(
        "tutor_turn_idempotency",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("key_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("turn_id", sa.String(length=64), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_token", sa.String(length=32), nullable=True),
        sa.UniqueConstraint("user_id", "key_sha256", name="uq_tutor_turn_idempotency_user_key"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_tutor_turn_idempotency_created_at", "tutor_turn_idempotency", ["created_at"])


def downgrade() -> None:
    allow = context.get_x_argument(as_dictionary=True).get("allow_ledger_drop") == "true"
    rows = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM response_ledger")).scalar() or 0
    if rows and not allow:
        raise RuntimeError(
            f"response_ledger holds {rows} rows (append-only evidence, R-22); export first with "
            "python -m app.workers.response_ledger --export <path outside the application tree>, then: "
            "alembic -x allow_ledger_drop=true downgrade 20261119_phase2_corpus_spans"
        )
    if op.get_bind().dialect.name == "postgresql":
        for trigger, table in POSTGRES_TRIGGERS:
            op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        for function in POSTGRES_FUNCTIONS:
            op.execute(f"DROP FUNCTION IF EXISTS {function}()")
    op.drop_index("ix_tutor_turn_idempotency_created_at", table_name="tutor_turn_idempotency")
    op.drop_table("tutor_turn_idempotency")
    with op.batch_alter_table("tutor_turns") as batch:
        batch.drop_column("ledger_record_expected")
    op.drop_index("ix_response_ledger_created_at", table_name="response_ledger")
    op.drop_index("ix_response_ledger_shadowed_response_id", table_name="response_ledger")
    op.drop_table("response_ledger_head")
    op.drop_table("response_ledger")
