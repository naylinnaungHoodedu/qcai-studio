"""Phase 6 V3 audit: the queue, the reviewers' round records, the audit draw, the gold store, the X5 events, the model
versions seen, the learner flags and the scan log (plan Phase 6 G "Additive Alembic revisions"; Phase 6 spec 8).

Additive and reversible (expand step, plan 13.3). No table holds learner text or a private-plane span; v3_claims and
v3_flags hold a person's id as user_id, which erasure removes (app.services.erasure), and the gold store holds keyed
digests only. Start-up's schema upgrades add the triggers (app.core.schema_upgrades._guard_v3_tables): the gold store,
the draws, the events, the model versions and the scan log refuse UPDATE, DELETE and TRUNCATE, a gold insert must
extend its chain, and the queue refuses DELETE and TRUNCATE. The downgrade refuses while v3_gold_labels, v3_queue_items
or v3_flags holds rows (append-only evidence, R-22; the queue and the flags carry F_i and the holds' queue), unless run
as
    alembic -x allow_v3_drop=true downgrade 20261122_phase5_gateway_controls
(an absolute target, never -1; check `alembic current` first) after
`python -m app.workers.v3_queue export-gold --all --path <path outside the application tree>`. The image before
Phase 6 reads none of these tables, so a digest rollback needs no downgrade. The chain still cannot build an empty
database (test_alembic_head_builds_the_orm_schema stays a strict xfail until the production baseline lands).

Revision ID: 20261122_phase6_v3_audit
Revises: 20261122_phase5_gateway_controls
Create Date: 2026-11-22
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "20261122_phase6_v3_audit"
down_revision: Union[str, Sequence[str], None] = "20261122_phase5_gateway_controls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APPEND_ONLY_TABLES = ("v3_model_versions", "v3_events", "v3_draws", "v3_gold_labels", "v3_scans")
POSTGRES_TRIGGERS = (
    *((f"{table}_append_only", table) for table in APPEND_ONLY_TABLES),
    *((f"{table}_no_truncate", table) for table in APPEND_ONLY_TABLES),
    ("v3_gold_labels_links_to_chain", "v3_gold_labels"),
    ("v3_queue_items_keep", "v3_queue_items"),
    ("v3_queue_items_no_truncate", "v3_queue_items"),
)
POSTGRES_FUNCTIONS = ("v3_append_only", "v3_gold_links_to_chain", "v3_queue_items_keep")
KEPT_TABLES = ("v3_gold_labels", "v3_queue_items", "v3_flags")


def upgrade() -> None:
    timestamp = sa.DateTime(timezone=True)
    op.create_table(
        "v3_queue_items",
        sa.Column("item_id", sa.String(length=32), primary_key=True),
        sa.Column("ledger_seq", sa.Integer(), nullable=False),
        sa.Column("claim_key", sa.String(length=48), nullable=False),
        sa.Column("subject", sa.String(length=16), nullable=False),
        sa.Column("record_kind", sa.String(length=16), nullable=False),
        sa.Column("response_digest", sa.String(length=32), nullable=False),
        sa.Column("triggers", sa.String(length=32), nullable=False),
        sa.Column("reasons", sa.String(length=128), nullable=False),
        sa.Column("ehmf_types", sa.String(length=16), nullable=False),
        sa.Column("held", sa.Boolean(), nullable=False),
        sa.Column("severity", sa.Float(), nullable=False),
        sa.Column("exposure", sa.Integer(), nullable=False),
        sa.Column("k", sa.Float(), nullable=False),
        sa.Column("priority", sa.Float(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("review_round", sa.Integer(), nullable=False),
        sa.Column("double_review", sa.Boolean(), nullable=False),
        sa.Column("enqueued_at", timestamp, nullable=False),
        sa.Column("closed_at", timestamp, nullable=True),
        sa.Column("final_gold_seq", sa.Integer(), nullable=True),
        sa.Column("applied_at", timestamp, nullable=True),
        sa.Column("applied_by_digest", sa.String(length=32), nullable=True),
        sa.Column("applied_client_key", sa.String(length=64), nullable=True),
        sa.Column("package_version", sa.String(length=32), nullable=False),
        sa.Column("package_sha256", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("ledger_seq", "claim_key", name="uq_v3_queue_items_subject"),
        sa.CheckConstraint("subject IN ('claim', 'response')", name="ck_v3_queue_items_subject"),
        sa.CheckConstraint("state IN ('queued', 'adjudicated', 'applied')", name="ck_v3_queue_items_state"),
    )
    op.create_index("ix_v3_queue_items_state_priority", "v3_queue_items", ["state", "priority"])
    op.create_index("ix_v3_queue_items_enqueued_at", "v3_queue_items", ["enqueued_at"])
    op.create_index("ix_v3_queue_items_closed_at", "v3_queue_items", ["closed_at"])
    op.create_table(
        "v3_claims",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("item_id", sa.String(length=32), nullable=False),
        sa.Column("review_round", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("claimed_at", timestamp, nullable=False),
        sa.Column("lease_expires_at", timestamp, nullable=False),
        sa.Column("adjudicated_at", timestamp, nullable=True),
        sa.UniqueConstraint("item_id", "review_round", name="uq_v3_claims_item_round"),
    )
    op.create_index("ix_v3_claims_user_id", "v3_claims", ["user_id"])
    op.create_table(
        "v3_draws",
        sa.Column("ledger_seq", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("delivered_at", timestamp, nullable=False),
        sa.Column("claim_set_key", sa.String(length=64), nullable=True),
        sa.Column("rate_numerator", sa.Integer(), nullable=False),
        sa.Column("rate_denominator", sa.Integer(), nullable=False),
        sa.Column("x5_active", sa.Boolean(), nullable=False),
        sa.Column("drawn", sa.String(length=2), nullable=True),
        sa.Column("rule", sa.String(length=48), nullable=False),
        sa.Column("package_sha256", sa.String(length=64), nullable=False),
        sa.Column("considered_at", timestamp, nullable=False),
    )
    op.create_index("ix_v3_draws_delivered_at", "v3_draws", ["delivered_at"])
    op.create_index("ix_v3_draws_claim_set_key", "v3_draws", ["claim_set_key"])
    op.create_table(
        "v3_gold_labels",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("item_id", sa.String(length=32), nullable=False),
        sa.Column("review_round", sa.Integer(), nullable=False),
        sa.Column("actor_role", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("reviewer_digest", sa.String(length=32), nullable=False),
        sa.Column("entry", sa.Text(), nullable=False),
        sa.Column("entry_sha256", sa.String(length=64), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("record_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.UniqueConstraint("item_id", "review_round", name="uq_v3_gold_labels_item_round"),
    )
    op.create_index("ix_v3_gold_labels_item_id", "v3_gold_labels", ["item_id"])
    op.create_index("ix_v3_gold_labels_reviewer_digest", "v3_gold_labels", ["reviewer_digest"])
    op.create_table(
        "v3_events",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("from_ledger_seq", sa.Integer(), nullable=False),
        sa.Column("window_deliveries", sa.Integer(), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.CheckConstraint("kind IN ('model_change', 'cusum_alarm')", name="ck_v3_events_kind"),
    )
    op.create_table(
        "v3_model_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("model_key", sa.String(length=255), nullable=False),
        sa.Column("model_version", sa.String(length=255), nullable=False),
        sa.Column("first_seen_seq", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("seen_at", timestamp, nullable=False),
    )
    op.create_index("ix_v3_model_versions_model_key", "v3_model_versions", ["model_key"])
    op.create_table(
        "v3_flags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("ledger_seq", sa.Integer(), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.UniqueConstraint("user_id", "ledger_seq", name="uq_v3_flags_user_record"),
    )
    op.create_index("ix_v3_flags_user_id", "v3_flags", ["user_id"])
    op.create_index("ix_v3_flags_ledger_seq", "v3_flags", ["ledger_seq"])
    op.create_table(
        "v3_scans",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        *(sa.Column(name, sa.Integer(), nullable=False) for name in (
            "from_seq", "to_seq", "records", "deliveries", "drawn_x6", "drawn_x5", "items_created", "items_updated", "model_changes", "unparsed")),
        sa.Column("package_version", sa.String(length=32), nullable=False),
        sa.Column("package_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
    )


def downgrade() -> None:
    allow = context.get_x_argument(as_dictionary=True).get("allow_v3_drop") == "true"
    bind = op.get_bind()
    counts = {table: int(bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0) for table in KEPT_TABLES}
    if any(counts.values()) and not allow:
        held = ", ".join(f"{table} holds {count} rows" for table, count in counts.items())
        raise RuntimeError(
            f"{held} (append-only evidence, R-22; the queue and learner flags carry F_i and the holds' queue); export first with "
            "python -m app.workers.v3_queue export-gold --all --path <path outside the application tree>, then: "
            "alembic -x allow_v3_drop=true downgrade 20261122_phase5_gateway_controls"
        )
    if bind.dialect.name == "postgresql":
        for trigger, table in POSTGRES_TRIGGERS:
            op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        for function in POSTGRES_FUNCTIONS:
            op.execute(f"DROP FUNCTION IF EXISTS {function}()")
    op.drop_table("v3_scans")
    op.drop_index("ix_v3_flags_ledger_seq", table_name="v3_flags")
    op.drop_index("ix_v3_flags_user_id", table_name="v3_flags")
    op.drop_table("v3_flags")
    op.drop_index("ix_v3_model_versions_model_key", table_name="v3_model_versions")
    op.drop_table("v3_model_versions")
    op.drop_table("v3_events")
    op.drop_index("ix_v3_gold_labels_reviewer_digest", table_name="v3_gold_labels")
    op.drop_index("ix_v3_gold_labels_item_id", table_name="v3_gold_labels")
    op.drop_table("v3_gold_labels")
    op.drop_index("ix_v3_draws_claim_set_key", table_name="v3_draws")
    op.drop_index("ix_v3_draws_delivered_at", table_name="v3_draws")
    op.drop_table("v3_draws")
    op.drop_index("ix_v3_claims_user_id", table_name="v3_claims")
    op.drop_table("v3_claims")
    op.drop_index("ix_v3_queue_items_closed_at", table_name="v3_queue_items")
    op.drop_index("ix_v3_queue_items_enqueued_at", table_name="v3_queue_items")
    op.drop_index("ix_v3_queue_items_state_priority", table_name="v3_queue_items")
    op.drop_table("v3_queue_items")
