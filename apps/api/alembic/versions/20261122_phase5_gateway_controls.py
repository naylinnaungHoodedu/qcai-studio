"""Phase 5 gateway controls: the shared daily budget, the durable gateway stop and the shared evidential cache
(plan Phase 5 tasks 5.7 and 5.10, L; plan 7.5 "shared verdict cache and rate-limit store"; Phase 5 spec 8).

Additive and reversible (expand step, plan 13.3). The three tables hold no learner data and no evidence: a registry's
spend per UTC day (gateway_budget_days), a registry's stop and its reason (gateway_stops), and claim plans and verdicts
under keyed digests (evidential_cache_entries). The downgrade drops them: the image before Phase 5 reads none of them,
and dropping gateway_stops also drops a recorded stop, so set MODEL_GATEWAY=off on the service before a rollback past
this revision (infra/cloudrun/deployment.md, Phase 5). Downgrade with an absolute target, never -1:
    alembic downgrade 20261119_phase3_response_ledger
The chain still cannot build an empty database (test_alembic_head_builds_the_orm_schema stays a strict xfail until the
production baseline lands).

Revision ID: 20261122_phase5_gateway_controls
Revises: 20261119_phase3_response_ledger
Create Date: 2026-11-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261122_phase5_gateway_controls"
down_revision: Union[str, Sequence[str], None] = "20261119_phase3_response_ledger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gateway_budget_days",
        sa.Column("registry", sa.String(length=32), primary_key=True),
        sa.Column("day", sa.String(length=10), primary_key=True),
        sa.Column("spent", sa.Integer(), nullable=False),
        sa.Column("alerted", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "gateway_stops",
        sa.Column("registry", sa.String(length=32), primary_key=True),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "evidential_cache_entries",
        sa.Column("kind", sa.String(length=16), primary_key=True),
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("used_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_evidential_cache_entries_used_at", "evidential_cache_entries", ["used_at"])


def downgrade() -> None:
    op.drop_index("ix_evidential_cache_entries_used_at", table_name="evidential_cache_entries")
    op.drop_table("evidential_cache_entries")
    op.drop_table("gateway_stops")
    op.drop_table("gateway_budget_days")
