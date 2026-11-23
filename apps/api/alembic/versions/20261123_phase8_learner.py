"""Phase 8 learner records, privacy lifecycle, and identifier-free audit controls."""

import sqlalchemy as sa
from alembic import op


revision: str = "20261123_phase8_learner"
down_revision: str = "20261122_phase6_v3_audit"
branch_labels = None
depends_on = None


def phase8_tables() -> tuple[sa.Table, ...]:
    metadata = sa.MetaData()
    sa.Table("quiz_attempts", metadata, sa.Column("id", sa.Integer(), primary_key=True))

    def timestamp(name):
        return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)

    def owner(*, primary_key=False, unique=False, index=False):
        return sa.Column("user_id", sa.String(255), nullable=False, primary_key=primary_key, unique=unique, index=index)

    def table(name, *columns):
        return sa.Table(name, metadata, *columns)

    return (
        table("learner_issued_replicas",
              sa.Column("replica_id", sa.String(128), primary_key=True), owner(index=True), timestamp("created_at"),
              sa.Column("last_used_at", sa.DateTime(timezone=True)), sa.Column("retired", sa.Boolean(), nullable=False)),
        table("learner_write_guards", sa.Column("key_digest", sa.String(64), primary_key=True),
              sa.Column("erased", sa.Boolean(), nullable=False)),
        table("learner_subjects", sa.Column("principal_digest", sa.String(64), primary_key=True), owner(unique=True),
              sa.Column("provider", sa.String(16), nullable=False), timestamp("created_at")),
        table("learner_guest_revocations", sa.Column("credential_digest", sa.String(64), primary_key=True),
              timestamp("revoked_at")),
        table("learner_claim_audits", sa.Column("id", sa.String(64), primary_key=True),
              sa.Column("subject_digest", sa.String(64), nullable=False),
              sa.Column("guest_digest", sa.String(64), nullable=False), sa.Column("transferred", sa.JSON(), nullable=False),
              timestamp("created_at")),
        table("learner_consents", owner(primary_key=True), sa.Column("consent_class", sa.String(16), primary_key=True),
              sa.Column("consent_version", sa.String(32), nullable=False), sa.Column("granted", sa.Boolean(), nullable=False),
              timestamp("updated_at"), sa.Column("source", sa.String(24), nullable=False)),
        table("learner_erasure_audits", sa.Column("id", sa.String(64), primary_key=True),
              sa.Column("receipt_digest", sa.String(64), nullable=False),
              sa.Column("table_set_digest", sa.String(64), nullable=False),
              sa.Column("deleted_total", sa.Integer(), nullable=False), timestamp("created_at")),
        table("learner_consent_changes", sa.Column("id", sa.String(64), primary_key=True), owner(index=True),
              sa.Column("consent_class", sa.String(16), nullable=False),
              sa.Column("consent_version", sa.String(32), nullable=False), sa.Column("granted", sa.Boolean(), nullable=False),
              timestamp("created_at"), sa.Column("source", sa.String(24), nullable=False)),
        table("learner_adaptation_stops", sa.Column("control_id", sa.String(24), primary_key=True),
              sa.Column("reason", sa.String(48), nullable=False), timestamp("stopped_at")),
        table("learner_assessment_facts",
              sa.Column("attempt_id", sa.Integer(), sa.ForeignKey("quiz_attempts.id", ondelete="CASCADE"),
                        primary_key=True, autoincrement=False),
              owner(index=True), sa.Column("lesson_slug", sa.String(255), nullable=False),
              sa.Column("mastery", sa.Float(), nullable=False), timestamp("created_at")),
    )


def upgrade() -> None:
    bind = op.get_bind()
    for table in phase8_tables():
        # Some development databases have already created these tables from ORM metadata.
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    tables = phase8_tables()
    if any(bind.execute(sa.select(1).select_from(table).limit(1)).first() is not None for table in tables):
        raise RuntimeError("Phase 8 tables contain records. Use a digest rollback and retain their schema.")
    for table in reversed(tables):
        table.drop(bind=bind)
