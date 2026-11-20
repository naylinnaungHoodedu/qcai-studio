"""Phase 2 span identity: the append-only, text-free corpus_spans table (plan Phase 2 task 2.2).

Additive and reversible (expand step, plan 11.6). The append-only triggers come from app.core.schema_upgrades, which
checks them at each API start and re-creates them when not current, so the downgrade drops them with the table. The chain still cannot build an empty
database (test_alembic_head_builds_the_orm_schema stays a strict xfail until the production baseline lands).

Revision ID: 20261119_phase2_corpus_spans
Revises: 20260827_cs595_increment
Create Date: 2026-11-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261119_phase2_corpus_spans"
down_revision: Union[str, Sequence[str], None] = "20260827_cs595_increment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "corpus_spans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("span_id", sa.String(length=80), nullable=False),
        sa.Column("scheme", sa.String(length=16), nullable=False),
        sa.Column("item_id", sa.String(length=255), nullable=False),
        sa.Column("item_version", sa.String(length=64), nullable=False),
        sa.Column("item_kind", sa.String(length=16), nullable=False),
        sa.Column("plane", sa.String(length=16), nullable=False),
        sa.Column("section_ordinal", sa.Integer(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_title_hash", sa.String(length=64), nullable=False),
        sa.Column("section_title_hash", sa.String(length=64), nullable=False),
        sa.Column("legacy_key_lexical", sa.String(length=64), nullable=False),
        sa.Column("legacy_key_semantic", sa.String(length=64), nullable=False),
        sa.Column("corpus_version_first_seen", sa.String(length=64), nullable=False),
        sa.Column("registered_by", sa.String(length=32), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("span_id", "item_version", name="uq_corpus_spans_span_id_item_version"),
        sa.CheckConstraint("plane = 'public'", name="ck_corpus_spans_public_plane"),
    )
    op.create_index("ix_corpus_spans_span_id", "corpus_spans", ["span_id"])
    op.create_index("ix_corpus_spans_item_id", "corpus_spans", ["item_id"])
    op.create_index("ix_corpus_spans_legacy_key_lexical", "corpus_spans", ["legacy_key_lexical"])
    op.create_index("ix_corpus_spans_legacy_key_semantic", "corpus_spans", ["legacy_key_semantic"])


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS corpus_spans_append_only ON corpus_spans")
        op.execute("DROP TRIGGER IF EXISTS corpus_spans_no_truncate ON corpus_spans")
        op.execute("DROP FUNCTION IF EXISTS corpus_spans_append_only()")
    op.drop_index("ix_corpus_spans_legacy_key_semantic", table_name="corpus_spans")
    op.drop_index("ix_corpus_spans_legacy_key_lexical", table_name="corpus_spans")
    op.drop_index("ix_corpus_spans_item_id", table_name="corpus_spans")
    op.drop_index("ix_corpus_spans_span_id", table_name="corpus_spans")
    op.drop_table("corpus_spans")
