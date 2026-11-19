"""Phase 3 tutor response ledger: the append-only, hash-chained response_ledger and its chain head (plan Phase 3
task 3.8, G; R-22).

Additive and reversible (expand step, plan 13.3). The append-only and chain triggers are re-created on every API
start by app.core.schema_upgrades, so the downgrade drops them with the tables. Append-only evidence is never
dropped by accident: the downgrade refuses while response_ledger holds rows, unless run as
    alembic -x allow_ledger_drop=true downgrade -1
after `python scripts/verify_ledger.py --export <path outside the repository>`. The chain still cannot build an
empty database (test_alembic_head_builds_the_orm_schema stays a strict xfail until the production baseline lands).

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
    )


def downgrade() -> None:
    allow = context.get_x_argument(as_dictionary=True).get("allow_ledger_drop") == "true"
    rows = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM response_ledger")).scalar() or 0
    if rows and not allow:
        raise RuntimeError(
            f"response_ledger holds {rows} rows (append-only evidence, R-22); export first with scripts/verify_ledger.py "
            "--export, then: alembic -x allow_ledger_drop=true downgrade -1"
        )
    if op.get_bind().dialect.name == "postgresql":
        for trigger, table in POSTGRES_TRIGGERS:
            op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        for function in POSTGRES_FUNCTIONS:
            op.execute(f"DROP FUNCTION IF EXISTS {function}()")
    op.drop_index("ix_response_ledger_created_at", table_name="response_ledger")
    op.drop_index("ix_response_ledger_shadowed_response_id", table_name="response_ledger")
    op.drop_table("response_ledger_head")
    op.drop_table("response_ledger")
