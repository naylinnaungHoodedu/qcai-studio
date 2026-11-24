"""Phase 7 EHMF: the rising-A/B stops (plan Phase 7 E, L; Phase 7 spec 8).

Additive and reversible (expand step, plan 13.3). One table, ehmf_stops: one row per EHMF rising-A/B stop (the change of
configuration version it follows, the counts that fired it and its audit window); no learner identifier. Start-up's
schema upgrades add the triggers (app.core.schema_upgrades._guard_ehmf_tables): UPDATE, DELETE and TRUNCATE are refused
through Phase 6's v3_append_only(). The downgrade refuses while ehmf_stops holds rows (append-only evidence of a stop and
its X5 window, R-22), unless run as
    alembic -x allow_ehmf_drop=true downgrade 20261122_phase6_v3_audit
(an absolute target, never -1; check `alembic current` first) after recording them
(python -m app.workers.ehmf status logs them). On PostgreSQL it drops the two triggers, then the index, then the table, and
never drops v3_append_only(). The image before Phase 7 reads no Phase 7 table, so a digest rollback needs no downgrade.

Revision ID: 20261123_phase7_ehmf
Revises: 20261122_phase6_v3_audit
Create Date: 2026-11-23
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "20261123_phase7_ehmf"
down_revision: Union[str, Sequence[str], None] = "20261122_phase6_v3_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

POSTGRES_TRIGGERS = (("ehmf_stops_append_only", "ehmf_stops"), ("ehmf_stops_no_truncate", "ehmf_stops"))


def upgrade() -> None:
    op.create_table(
        "ehmf_stops",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("from_config_version", sa.String(length=32), nullable=False),
        sa.Column("to_config_version", sa.String(length=32), nullable=False),
        *(sa.Column(name, sa.Integer(), nullable=False) for name in (
            "change_seq", "detected_seq", "before_claims", "before_ab", "after_claims", "after_ab", "window_deliveries")),
        sa.Column("package_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("from_config_version", "to_config_version", "change_seq", name="uq_ehmf_stops_change"),
    )
    op.create_index("ix_ehmf_stops_to_config_version", "ehmf_stops", ["to_config_version"])


def downgrade() -> None:
    allow = context.get_x_argument(as_dictionary=True).get("allow_ehmf_drop") == "true"
    bind = op.get_bind()
    rows = int(bind.execute(sa.text("SELECT COUNT(*) FROM ehmf_stops")).scalar() or 0)
    if rows and not allow:
        raise RuntimeError(
            f"ehmf_stops holds {rows} rows (append-only evidence of a rising A/B stop and its X5 window, R-22); record them first "
            "(python -m app.workers.ehmf status logs them), then: alembic -x allow_ehmf_drop=true downgrade 20261122_phase6_v3_audit"
        )
    if bind.dialect.name == "postgresql":
        for trigger, table in POSTGRES_TRIGGERS:
            op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
    op.drop_index("ix_ehmf_stops_to_config_version", table_name="ehmf_stops")
    op.drop_table("ehmf_stops")
