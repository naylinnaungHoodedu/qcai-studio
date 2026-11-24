"""Serialize Phase 8 mutations with erasure using stable, identifier-free keys."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.phase8_settings import GUARD_RETENTION_DAYS
from app.db_models import LearnerWriteGuard


@dataclass(frozen=True)
class WriteObservation:
    erasure_epoch: str | None
    observed_at: datetime


def phase8_writes_enabled(settings) -> bool:
    return any(mode not in {None, "off"} for mode in (
        settings.learner_sync, settings.learner_identity, settings.learner_privacy, settings.learner_planner,
    ))


def insert_for(db: Session):
    return sqlite_insert if db.get_bind().dialect.name == "sqlite" else postgres_insert


def guard_key(identifier: str) -> str:
    return sha256(f"qcai-learner-write-v1:{identifier}".encode("utf-8")).hexdigest()


def has_write_guard(db: Session, identifier: str) -> bool:
    return db.get(LearnerWriteGuard, guard_key(identifier)) is not None


def observe_learner_write(db: Session, identifier: str) -> WriteObservation:
    observed_at = datetime.now(UTC)
    epoch = db.scalar(select(LearnerWriteGuard.erasure_epoch).where(LearnerWriteGuard.key_digest == guard_key(identifier)))
    return WriteObservation(epoch, observed_at)


def lock_learner_write(
    db: Session, identifier: str, *, erase: bool = False, observation: WriteObservation | None = None,
) -> None:
    key = guard_key(identifier)
    now = datetime.now(UTC)
    if observation is not None and now - observation.observed_at >= timedelta(days=GUARD_RETENTION_DAYS):
        raise HTTPException(409, "Learner request is no longer current.")
    transaction = db.get_nested_transaction() or db.get_transaction() or db.begin()
    held_transaction, held = db.info.get("learner_write_locks", (None, None))
    if held_transaction is not transaction:
        held = set()
        db.info["learner_write_locks"] = (transaction, held)
    if not erase and key in held:
        return

    # An upsert locks the same guard even during the first write or protected erasure.
    epoch = uuid4().hex if erase else None
    changes = {"last_used_at": now}
    if erase:
        changes.update(erased=True, erasure_epoch=epoch)
    statement = insert_for(db)(LearnerWriteGuard).values(
        key_digest=key, erased=erase, erasure_epoch=epoch, last_used_at=now,
    )
    erased, current_epoch = db.execute(
        statement.on_conflict_do_update(index_elements=["key_digest"], set_=changes)
        .returning(LearnerWriteGuard.erased, LearnerWriteGuard.erasure_epoch)
        .execution_options(populate_existing=True)
    ).one()
    if erase:
        held.discard(key)
        return
    if erased and not (
        observation is not None and current_epoch is not None and observation.erasure_epoch == current_epoch
    ):
        raise HTTPException(409, "Learner record is unavailable.")
    held.add(key)
