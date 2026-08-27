"""CS595 durable learner record and persistent grounded Tutor.

Revision ID: 20260827_cs595_increment
Revises: 25705ed89aa2
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260827_cs595_increment"
down_revision: Union[str, Sequence[str], None] = "25705ed89aa2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "learner_records",
        sa.Column("user_id", sa.String(length=255), primary_key=True),
        sa.Column("record_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mastery", sa.JSON(), nullable=False),
        sa.Column("completed_items", sa.JSON(), nullable=False),
        sa.Column("attempt_counters", sa.JSON(), nullable=False),
        sa.Column("cursor", sa.JSON(), nullable=False),
        sa.Column("preferences", sa.JSON(), nullable=False),
        sa.Column("version_vector", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_learner_records_updated_at", "learner_records", ["updated_at"])
    op.create_table(
        "learner_replicas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("replica_id", sa.String(length=128), nullable=False),
        sa.Column("last_logical_counter", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "replica_id", name="uq_learner_replica_user_replica"),
    )
    op.create_index("ix_learner_replicas_user_id", "learner_replicas", ["user_id"])
    op.create_index("ix_learner_replicas_replica_id", "learner_replicas", ["replica_id"])
    op.create_table(
        "learner_record_operations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("operation_id", sa.String(length=128), nullable=False),
        sa.Column("replica_id", sa.String(length=128), nullable=False),
        sa.Column("logical_counter", sa.Integer(), nullable=False),
        sa.Column("causal_vector", sa.JSON(), nullable=False),
        sa.Column("operation_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "operation_id", name="uq_learner_record_operation_user_operation"),
    )
    op.create_index("ix_learner_record_operations_user_id", "learner_record_operations", ["user_id"])
    op.create_index("ix_learner_record_operations_operation_id", "learner_record_operations", ["operation_id"])
    op.create_index("ix_learner_record_operations_replica_id", "learner_record_operations", ["replica_id"])
    op.create_index("ix_learner_record_operations_operation_type", "learner_record_operations", ["operation_type"])
    op.create_index("ix_learner_record_operations_user_id_created_at", "learner_record_operations", ["user_id", "created_at"])
    op.create_table(
        "tutor_threads",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tutor_threads_user_id", "tutor_threads", ["user_id"])
    op.create_index("ix_tutor_threads_user_id_updated_at", "tutor_threads", ["user_id", "updated_at"])
    op.create_table(
        "tutor_messages",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("thread_id", sa.String(length=64), sa.ForeignKey("tutor_threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tutor_messages_thread_id", "tutor_messages", ["thread_id"])
    op.create_index("ix_tutor_messages_role", "tutor_messages", ["role"])
    op.create_index("ix_tutor_messages_thread_id_created_at", "tutor_messages", ["thread_id", "created_at"])
    op.create_table(
        "tutor_turns",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("thread_id", sa.String(length=64), sa.ForeignKey("tutor_threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("resolved_query", sa.Text(), nullable=False),
        sa.Column("retrieval_mode", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("decision_reason", sa.String(length=255), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("claims", sa.JSON(), nullable=False),
        sa.Column("corpus_version", sa.String(length=255), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tutor_turns_thread_id", "tutor_turns", ["thread_id"])
    op.create_index("ix_tutor_turns_user_id", "tutor_turns", ["user_id"])
    op.create_index("ix_tutor_turns_decision", "tutor_turns", ["decision"])
    op.create_index("ix_tutor_turns_thread_id_created_at", "tutor_turns", ["thread_id", "created_at"])


def downgrade() -> None:
    for name in ("ix_tutor_turns_thread_id_created_at", "ix_tutor_turns_decision", "ix_tutor_turns_user_id", "ix_tutor_turns_thread_id"):
        op.drop_index(name, table_name="tutor_turns")
    op.drop_table("tutor_turns")
    for name in ("ix_tutor_messages_thread_id_created_at", "ix_tutor_messages_role", "ix_tutor_messages_thread_id"):
        op.drop_index(name, table_name="tutor_messages")
    op.drop_table("tutor_messages")
    for name in ("ix_tutor_threads_user_id_updated_at", "ix_tutor_threads_user_id"):
        op.drop_index(name, table_name="tutor_threads")
    op.drop_table("tutor_threads")
    for name in (
        "ix_learner_record_operations_user_id_created_at",
        "ix_learner_record_operations_operation_type",
        "ix_learner_record_operations_replica_id",
        "ix_learner_record_operations_operation_id",
        "ix_learner_record_operations_user_id",
    ):
        op.drop_index(name, table_name="learner_record_operations")
    op.drop_table("learner_record_operations")
    for name in ("ix_learner_replicas_replica_id", "ix_learner_replicas_user_id"):
        op.drop_index(name, table_name="learner_replicas")
    op.drop_table("learner_replicas")
    op.drop_index("ix_learner_records_updated_at", table_name="learner_records")
    op.drop_table("learner_records")
