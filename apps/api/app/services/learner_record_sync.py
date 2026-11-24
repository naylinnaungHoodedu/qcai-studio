"""Subject-scoped replica issuance and transactional client synchronization."""

import json
from uuid import uuid4
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db_models import LearnerIssuedReplica, LearnerRecord, LearnerRecordOperation, LearnerReplica, QuizAttempt
from app.core.phase8_settings import ASSESSMENT_LIMIT, ASSESSMENT_WINDOW_MINUTES, MAX_ISSUED_REPLICAS
from app.schemas import LearnerRecordOperationInput, LearnerRecordRead
from app.services.learner_record import (
    _payload_hash,
    apply_learner_record_operations,
    materialize_record,
)
from app.services.learner_record_lock import lock_learner_write
from app.services.learner_record_metrics import record_signal


SERVER_REPLICA = "server-content-v1"
ASSESSMENT_WINDOW = timedelta(minutes=ASSESSMENT_WINDOW_MINUTES)


def _refuse(reason: str, status: int, detail: str | dict) -> None:
    record_signal("learner.sync.conflict", reason=reason)
    raise HTTPException(status, detail)


def begin_server_assessment(db: Session, user_id: str, lesson_slug: str, *, attempt_owner: str | None = None) -> int:
    """Hold the record lock while checking the quota and reserving the next clock base."""
    lock_learner_record(db, user_id)
    count = db.scalar(
        select(func.count()).select_from(QuizAttempt).where(
            QuizAttempt.user_id == (attempt_owner or user_id),
            QuizAttempt.lesson_slug == lesson_slug,
            QuizAttempt.created_at >= datetime.now(UTC) - ASSESSMENT_WINDOW,
        )
    )
    if count is not None and count >= ASSESSMENT_LIMIT:
        raise HTTPException(429, "Assessment attempt limit reached.",
                            headers={"Retry-After": str(int(ASSESSMENT_WINDOW.total_seconds()))})
    return db.scalar(
        select(LearnerReplica.last_logical_counter).where(
            LearnerReplica.user_id == user_id, LearnerReplica.replica_id == SERVER_REPLICA
        )
    ) or 0


def lock_learner_record(db: Session, user_id: str) -> LearnerRecord:
    """Serialize writers for an existing or first record, until the caller commits."""
    lock_learner_write(db, user_id)
    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else postgres_insert
    db.execute(insert(LearnerRecord).values(user_id=user_id).on_conflict_do_nothing(index_elements=["user_id"]))
    # The same write lock works on both supported databases and leaves the version and timestamp intact.
    db.execute(
        update(LearnerRecord)
        .where(LearnerRecord.user_id == user_id)
        .values(record_version=LearnerRecord.record_version, updated_at=LearnerRecord.updated_at)
        .execution_options(synchronize_session=False)
    )
    record = db.get(LearnerRecord, user_id, populate_existing=True)
    if record is None:
        raise RuntimeError("Learner record unavailable after acquiring its write lock.")
    return record


def issue_learner_replica(db: Session, user_id: str, preferred: str | None = None) -> str:
    lock_learner_record(db, user_id)
    issued = list(db.scalars(
        select(LearnerIssuedReplica).where(
            LearnerIssuedReplica.user_id == user_id, LearnerIssuedReplica.retired.is_(False),
        ).order_by(
            func.coalesce(LearnerIssuedReplica.last_used_at, LearnerIssuedReplica.created_at),
            LearnerIssuedReplica.created_at, LearnerIssuedReplica.replica_id,
        )
    ))
    now = datetime.now(UTC)
    for replica in issued:
        if replica.replica_id == preferred:
            replica.last_used_at = now
            return replica.replica_id
    for replica in issued[:max(0, len(issued) - MAX_ISSUED_REPLICAS + 1)]:
        replica.retired = True
    replica_id = f"replica-{uuid4().hex}"
    db.add(LearnerIssuedReplica(replica_id=replica_id, user_id=user_id, last_used_at=now))
    db.flush()
    return replica_id


def read_existing_learner_record(db: Session, user_id: str) -> LearnerRecordRead:
    record = db.get(LearnerRecord, user_id)
    if record is not None:
        return materialize_record(record)
    return LearnerRecordRead(
        user_id=user_id, record_version=0, mastery={}, completed_item_ids=[],
        attempt_counts={}, cursor=None, preferences={}, version_vector={},
    )


def synchronize_client_operations(
    db: Session,
    user_id: str,
    expected_version: int,
    operations: list[LearnerRecordOperationInput],
) -> tuple[list[dict[str, str]], LearnerRecordRead]:
    """Validate a batch and reuse the existing operation merge in the same transaction."""
    record = lock_learner_record(db, user_id)
    replicas = {
        replica.replica_id: replica for replica in db.scalars(
            select(LearnerIssuedReplica).where(LearnerIssuedReplica.user_id == user_id)
        )
    }
    active = {key for key, replica in replicas.items() if not replica.retired}
    clocks = dict(db.execute(
        select(LearnerReplica.replica_id, LearnerReplica.last_logical_counter)
        .where(LearnerReplica.user_id == user_id, LearnerReplica.replica_id.in_(replicas))
    ).all())
    receipts = {
        row.operation_id: row.payload_hash
        for row in db.scalars(
            select(LearnerRecordOperation).where(
                LearnerRecordOperation.user_id == user_id,
                LearnerRecordOperation.operation_id.in_([op.operation_id for op in operations]),
            )
        )
    }
    expected = record.record_version
    for op in operations:
        if op.replica_id == SERVER_REPLICA or op.operation_id.startswith("quiz-"):
            _refuse("server_namespace_refused", 422, "Server operation namespace is reserved.")
        if op.operation_type == "mastery_set":
            _refuse("client_mastery_refused", 422, "Mastery is recorded by server-scored assessments.")
        if op.replica_id not in replicas or not op.causal_vector.keys() <= replicas.keys():
            _refuse("unissued_replica", 409, "Replica was not issued to this learner.")
        try:
            json.dumps(op.payload, allow_nan=False)
        except ValueError as exc:
            raise HTTPException(422, "Operation payload must contain finite JSON values.") from exc
        digest = _payload_hash(op)
        if op.operation_id in receipts:
            if digest != receipts[op.operation_id]:
                _refuse("payload_mismatch", 409, "Operation ID was replayed with a different payload.")
            continue
        if op.replica_id not in active:
            _refuse("unissued_replica", 409, "Replica was retired.")
        if expected_version != expected:
            _refuse("cas_conflict", 409, {"reason": "cas_conflict", "record_version": expected})
        if op.logical_counter <= clocks.get(op.replica_id, 0):
            _refuse("counter_regressed", 409, "Replica counter must increase for a new operation.")
        if any(counter > clocks.get(replica, 0) for replica, counter in op.causal_vector.items()):
            _refuse("unissued_replica", 409, "Causal vector contains an unobserved counter.")
        clocks[op.replica_id] = op.logical_counter
        receipts[op.operation_id] = digest
        replicas[op.replica_id].last_used_at = datetime.now(UTC)
    unique = {op.operation_id: op for op in operations}
    applied, current = apply_learner_record_operations(db, user_id, list(unique.values()))
    outcomes = {receipt["operation_id"]: receipt["status"] for receipt in applied}
    return [
        {"operation_id": op.operation_id, "status": outcomes.pop(op.operation_id, "duplicate")}
        for op in operations
    ], current
