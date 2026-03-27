"""improvement batch schema

Revision ID: 25705ed89aa2
Revises: 
Create Date: 2026-03-27 01:32:23.568385

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '25705ed89aa2'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _has_peer_review_submission_fk(inspector: sa.Inspector) -> bool:
    for foreign_key in inspector.get_foreign_keys("peer_reviews"):
        if (
            foreign_key.get("referred_table") == "project_submissions"
            and foreign_key.get("constrained_columns") == ["submission_id"]
        ):
            return True
    return False


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "project_submissions" in inspector.get_table_names():
        if "is_deleted" not in _column_names(inspector, "project_submissions"):
            with op.batch_alter_table("project_submissions") as batch_op:
                batch_op.add_column(
                    sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false())
                )
            with op.batch_alter_table("project_submissions") as batch_op:
                batch_op.alter_column("is_deleted", server_default=None)
            inspector = sa.inspect(bind)

    if "ix_project_submissions_is_deleted" not in _index_names(inspector, "project_submissions"):
        op.create_index(
            "ix_project_submissions_is_deleted",
            "project_submissions",
            ["is_deleted"],
            unique=False,
            if_not_exists=True,
        )

    if "ix_notes_user_id_lesson_slug_created_at" not in _index_names(inspector, "notes"):
        op.create_index(
            "ix_notes_user_id_lesson_slug_created_at",
            "notes",
            ["user_id", "lesson_slug", "created_at"],
            unique=False,
            if_not_exists=True,
        )

    if "ix_quiz_attempts_user_id_lesson_slug_created_at" not in _index_names(inspector, "quiz_attempts"):
        op.create_index(
            "ix_quiz_attempts_user_id_lesson_slug_created_at",
            "quiz_attempts",
            ["user_id", "lesson_slug", "created_at"],
            unique=False,
            if_not_exists=True,
        )

    if "ix_qa_interactions_user_id_lesson_slug_created_at" not in _index_names(inspector, "qa_interactions"):
        op.create_index(
            "ix_qa_interactions_user_id_lesson_slug_created_at",
            "qa_interactions",
            ["user_id", "lesson_slug", "created_at"],
            unique=False,
            if_not_exists=True,
        )

    if "ix_analytics_events_user_id_event_type" not in _index_names(inspector, "analytics_events"):
        op.create_index(
            "ix_analytics_events_user_id_event_type",
            "analytics_events",
            ["user_id", "event_type"],
            unique=False,
            if_not_exists=True,
        )

    if "ix_builder_runs_user_id_scenario_slug" not in _index_names(inspector, "builder_runs"):
        op.create_index(
            "ix_builder_runs_user_id_scenario_slug",
            "builder_runs",
            ["user_id", "scenario_slug"],
            unique=False,
            if_not_exists=True,
        )

    if "ix_learning_pulses_user_id_created_at" not in _index_names(inspector, "learning_pulses"):
        op.create_index(
            "ix_learning_pulses_user_id_created_at",
            "learning_pulses",
            ["user_id", "created_at"],
            unique=False,
            if_not_exists=True,
        )

    if not _has_peer_review_submission_fk(inspector):
        with op.batch_alter_table("peer_reviews", recreate="always") as batch_op:
            batch_op.create_foreign_key(
                "fk_peer_reviews_submission_id_project_submissions",
                "project_submissions",
                ["submission_id"],
                ["id"],
            )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_peer_review_submission_fk(inspector):
        with op.batch_alter_table("peer_reviews", recreate="always") as batch_op:
            batch_op.drop_constraint(
                "fk_peer_reviews_submission_id_project_submissions",
                type_="foreignkey",
            )

    for table_name, index_name in (
        ("learning_pulses", "ix_learning_pulses_user_id_created_at"),
        ("builder_runs", "ix_builder_runs_user_id_scenario_slug"),
        ("analytics_events", "ix_analytics_events_user_id_event_type"),
        ("qa_interactions", "ix_qa_interactions_user_id_lesson_slug_created_at"),
        ("quiz_attempts", "ix_quiz_attempts_user_id_lesson_slug_created_at"),
        ("notes", "ix_notes_user_id_lesson_slug_created_at"),
        ("project_submissions", "ix_project_submissions_is_deleted"),
    ):
        if index_name in _index_names(inspector, table_name):
            op.drop_index(index_name, table_name=table_name)

    if "is_deleted" in _column_names(inspector, "project_submissions"):
        with op.batch_alter_table("project_submissions") as batch_op:
            batch_op.drop_column("is_deleted")
