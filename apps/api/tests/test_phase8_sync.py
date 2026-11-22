"""Phase 8 service tests for issued replicas, retries, and write ordering."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db_models import Base, LearnerIssuedReplica, LearnerRecord, LearnerRecordOperation, LearnerReplica, QuizAttempt
from app.schemas import LearnerRecordOperationInput
from app.services.learner_record import apply_learner_record_operations
from app.services.learner_record_sync import (
    MAX_ISSUED_REPLICAS,
    ASSESSMENT_LIMIT,
    SERVER_REPLICA,
    begin_server_assessment,
    issue_learner_replica,
    lock_learner_record,
    read_existing_learner_record,
    synchronize_client_operations,
)


@pytest.fixture()
def sync_engine(fresh_database_url):
    engine = create_engine(fresh_database_url)
    tables = [
        model.__table__
        for model in (LearnerRecord, LearnerReplica, LearnerRecordOperation, LearnerIssuedReplica, QuizAttempt)
    ]
    try:
        Base.metadata.create_all(engine, tables=tables)
        yield engine
    finally:
        engine.dispose()


def complete(replica_id, counter, item):
    return LearnerRecordOperationInput(
        replica_id=replica_id,
        logical_counter=counter,
        operation_id=f"op-{uuid4().hex}",
        operation_type="complete_item",
        payload={"item_id": item},
    )


def test_phase8_sync_read_issues_no_insert(sync_engine):
    statements = []

    @event.listens_for(sync_engine, "before_cursor_execute")
    def record_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split()[0].upper())

    with Session(sync_engine) as db:
        result = read_existing_learner_record(db, f"subj-{uuid4().hex}")

    assert result.record_version == 0
    assert statements == ["SELECT"]


def test_phase8_sync_duplicate_receipts_and_monotonic_clock(sync_engine):
    subject = f"subj-{uuid4().hex}"
    with Session(sync_engine, autoflush=False) as db:
        replica = issue_learner_replica(db, subject)
        db.commit()
        op = complete(replica, 2, "lesson-one")
        receipts, current = synchronize_client_operations(db, subject, 0, [op, op])
        db.commit()
        assert [receipt["status"] for receipt in receipts] == ["applied", "duplicate"]
        assert current.record_version == 1
        replay, current = synchronize_client_operations(db, subject, 0, [op])
        assert replay[0]["status"] == "duplicate"
        assert current.record_version == 1
        db.rollback()
        for counter in (1, 2):
            with pytest.raises(HTTPException, match="counter must increase"):
                synchronize_client_operations(db, subject, 1, [complete(replica, counter, "lesson-two")])
            db.rollback()
        with pytest.raises(HTTPException, match="different payload"):
            changed = op.model_copy(update={"payload": {"item_id": "lesson-two"}})
            synchronize_client_operations(db, subject, 1, [changed])


def test_phase8_sync_rejects_other_subjects_and_server_operations(sync_engine):
    subject, other = (f"subj-{uuid4().hex}" for _ in range(2))
    with Session(sync_engine, autoflush=False) as db:
        owned = issue_learner_replica(db, subject)
        foreign = issue_learner_replica(db, other)
        db.commit()

        attempts = [
            (complete(foreign, 1, "lesson"), "not issued"),
            (complete(owned, 1, "lesson").model_copy(update={"causal_vector": {foreign: 1}}), "not issued"),
            (complete("server-content-v1", 1, "lesson"), "namespace"),
            (complete(owned, 1, "lesson").model_copy(update={"operation_id": "quiz-reserved"}), "namespace"),
            (complete(owned, 1, "lesson").model_copy(update={"operation_type": "mastery_set"}), "server-scored"),
        ]
        for op, message in attempts:
            with pytest.raises(HTTPException, match=message):
                synchronize_client_operations(db, subject, 0, [op])
            db.rollback()
        assert read_existing_learner_record(db, subject).record_version == 0


def test_phase8_sync_parallel_replicas_conflict_and_retry_without_losing_updates(sync_engine):
    subject = f"subj-{uuid4().hex}"
    with Session(sync_engine) as db:
        first = issue_learner_replica(db, subject)
        second = issue_learner_replica(db, subject)
        db.commit()
    barrier = Barrier(2, timeout=10)

    def write(op):
        with Session(sync_engine, autoflush=False) as db:
            barrier.wait()
            try:
                synchronize_client_operations(db, subject, 0, [op])
                db.commit()
                return False
            except HTTPException as exc:
                db.rollback()
                assert exc.status_code == 409
                assert exc.detail == {"reason": "cas_conflict", "record_version": 1}
                synchronize_client_operations(db, subject, 1, [op])
                db.commit()
                return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        retried = list(pool.map(write, [complete(first, 1, "one"), complete(second, 1, "two")]))
    assert sorted(retried) == [False, True]
    with Session(sync_engine) as db:
        result = read_existing_learner_record(db, subject)
    assert result.record_version == 2
    assert result.completed_item_ids == ["one", "two"]


def test_phase8_sync_parallel_first_writes_create_one_record(sync_engine):
    subject = f"subj-{uuid4().hex}"
    barrier = Barrier(2, timeout=10)

    def first_write(_):
        with Session(sync_engine, autoflush=False) as db:
            barrier.wait()
            record = lock_learner_record(db, subject)
            result = record.record_version
            db.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(first_write, range(2))) == [0, 0]
    with Session(sync_engine) as db:
        assert db.query(LearnerRecord).filter_by(user_id=subject).count() == 1


def test_phase8_sync_limits_replica_issuance_per_subject(sync_engine):
    subject, other = (f"subj-{uuid4().hex}" for _ in range(2))
    with Session(sync_engine, autoflush=False) as db:
        issued = {issue_learner_replica(db, subject) for _ in range(MAX_ISSUED_REPLICAS)}
        db.commit()
        assert len(issued) == MAX_ISSUED_REPLICAS
        with pytest.raises(HTTPException, match="replica limit"):
            issue_learner_replica(db, subject)
        db.rollback()
        assert issue_learner_replica(db, other) not in issued


def test_phase8_assessment_quota_and_server_clock_are_subject_scoped(sync_engine):
    subject, other = (f"subj-{uuid4().hex}" for _ in range(2))
    with Session(sync_engine, autoflush=False) as db:
        for index in range(ASSESSMENT_LIMIT):
            assert begin_server_assessment(db, subject, "lesson") == index
            replica = db.query(LearnerReplica).filter_by(user_id=subject, replica_id=SERVER_REPLICA).one_or_none()
            if replica is None:
                replica = LearnerReplica(user_id=subject, replica_id=SERVER_REPLICA)
                db.add(replica)
            replica.last_logical_counter = index + 1
            db.add(QuizAttempt(user_id=subject, lesson_slug="lesson", score=0, responses={}))
            db.commit()
        with pytest.raises(HTTPException, match="attempt limit") as refused:
            begin_server_assessment(db, subject, "lesson")
        assert refused.value.status_code == 429
        db.rollback()
        assert begin_server_assessment(db, other, "lesson") == 0
        assert begin_server_assessment(db, subject, "other-lesson") == ASSESSMENT_LIMIT


def test_ac_8_1_concurrent_trusted_updates_preserve_each_mastery_value(sync_engine):
    subject = f"subj-{uuid4().hex}"
    barrier = Barrier(2, timeout=10)

    def apply(item):
        lesson, mastery = item
        with Session(sync_engine, autoflush=False) as db:
            barrier.wait()
            counter = begin_server_assessment(db, subject, lesson) + 1
            operation = LearnerRecordOperationInput(
                operation_id=f"quiz-v2-{uuid4().hex}", replica_id=SERVER_REPLICA,
                logical_counter=counter, operation_type="mastery_set",
                payload={"skill_id": f"lesson:{lesson}", "value": mastery},
            )
            apply_learner_record_operations(db, subject, [operation])
            db.commit()
            return counter

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(apply, [("first", 0.2), ("second", 0.9)])) == [1, 2]
    with Session(sync_engine) as db:
        assert read_existing_learner_record(db, subject).mastery == {"lesson:first": 0.2, "lesson:second": 0.9}
