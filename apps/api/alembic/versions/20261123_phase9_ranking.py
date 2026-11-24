"""Phase 9 verified-trust ranking: the ranking event log, scans, states and incumbents (plan Phase 9 E, G; Phase 9 spec 8).

Additive and reversible (expand step, plan 13.3). Four tables, none with a learner identifier, learner text or a foreign
key to a user-keyed table (erasure, plan 10.3, never reaches them):
  ranking_events      the append-only, hash-chained controller log (inputs, derived events, checkpoint/stop/clear_stop)
  ranking_scans       one append-only row per ranking scan (its cursor and counts)
  ranking_states      the derived state cache ("_state" and "<model>|<context>" rows)
  ranking_incumbents  the derived incumbent per context
Start-up's schema upgrades add the triggers (app.core.schema_upgrades._guard_ranking_tables): UPDATE and DELETE on
ranking_events and ranking_scans are refused, and TRUNCATE on PostgreSQL, through Phase 6's v3_append_only(). The
downgrade refuses while ranking_events holds rows (append-only evidence of the controller's decisions, alarms and X5
windows; plan L "alarms retained"), unless run as
    alembic -x allow_ranking_drop=true downgrade 20261123_phase7_ehmf
(an absolute target, never -1; check `alembic current` first) after recording them (python -m app.workers.ranking status).
On PostgreSQL it drops the four triggers, then the indexes, then the four tables, and never drops v3_append_only(). The
image before Phase 9 reads no Phase 9 table, so a digest rollback needs no downgrade.

Revision ID: 20261123_phase9_ranking
Revises: 20261123_phase7_ehmf
Create Date: 2026-11-23
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "20261123_phase9_ranking"
down_revision: Union[str, Sequence[str], None] = "20261123_phase7_ehmf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EVENT_KINDS = ("config", "availability", "model_seen", "model_change", "commission", "recommission_pass", "recommission_fail", "outcome",
               "skipped", "feedback", "hold_release", "tick", "select", "batch", "promote", "demote", "alarm", "hold", "checkpoint",
               "stop", "clear_stop")
POSTGRES_TRIGGERS = (("ranking_events_append_only", "ranking_events"), ("ranking_events_no_truncate", "ranking_events"),
                     ("ranking_scans_append_only", "ranking_scans"), ("ranking_scans_no_truncate", "ranking_scans"))


def upgrade() -> None:
    kinds = ", ".join(f"'{kind}'" for kind in EVENT_KINDS)
    op.create_table(
        "ranking_events",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("context_key", sa.String(length=160), nullable=True),
        sa.Column("model_key", sa.String(length=160), nullable=True),
        sa.Column("ledger_seq", sa.Integer(), nullable=True),
        sa.Column("batch_seq", sa.Integer(), nullable=True),
        sa.Column("input_key", sa.String(length=64), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("prev_sha256", sa.String(length=64), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("v3_event_seq", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(length=32), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"kind IN ({kinds})", name="ck_ranking_events_kind"),
        sa.UniqueConstraint("input_key", name="uq_ranking_events_input"),
        sa.UniqueConstraint("context_key", "batch_seq", name="uq_ranking_events_batch"),
    )
    op.create_index("ix_ranking_events_kind", "ranking_events", ["kind"])
    op.create_index("ix_ranking_events_ledger_seq", "ranking_events", ["ledger_seq"])
    op.create_table(
        "ranking_scans",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        *(sa.Column(name, sa.Integer(), nullable=False) for name in (
            "from_seq", "to_seq", "records", "outcomes", "skipped", "batches", "alarms", "fallbacks")),
        sa.Column("package_version", sa.String(length=32), nullable=False),
        sa.Column("package_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ranking_states",
        sa.Column("state_key", sa.String(length=200), primary_key=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("updated_event_seq", sa.Integer(), nullable=False),
    )
    op.create_table(
        "ranking_incumbents",
        sa.Column("context_key", sa.String(length=160), primary_key=True),
        sa.Column("model_key", sa.String(length=160), nullable=True),
        sa.Column("since_event_seq", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    allow = context.get_x_argument(as_dictionary=True).get("allow_ranking_drop") == "true"
    bind = op.get_bind()
    rows = int(bind.execute(sa.text("SELECT COUNT(*) FROM ranking_events")).scalar() or 0)
    if rows and not allow:
        raise RuntimeError(
            f"ranking_events holds {rows} rows (append-only evidence of the controller's decisions, alarms and X5 windows; plan L "
            "\"alarms retained\"); record them first (python -m app.workers.ranking status), then: "
            "alembic -x allow_ranking_drop=true downgrade 20261123_phase7_ehmf"
        )
    if bind.dialect.name == "postgresql":
        for trigger, table in POSTGRES_TRIGGERS:
            op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
    op.drop_index("ix_ranking_events_ledger_seq", table_name="ranking_events")
    op.drop_index("ix_ranking_events_kind", table_name="ranking_events")
    op.drop_table("ranking_incumbents")
    op.drop_table("ranking_states")
    op.drop_table("ranking_scans")
    op.drop_table("ranking_events")
