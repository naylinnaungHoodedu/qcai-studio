"""Serialize Phase 8 mutations with erasure using stable, identifier-free keys."""

from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db_models import LearnerWriteGuard


def insert_for(db: Session):
    return sqlite_insert if db.get_bind().dialect.name == "sqlite" else postgres_insert


def guard_key(identifier: str) -> str:
    return sha256(f"qcai-learner-write-v1:{identifier}".encode("utf-8")).hexdigest()


def has_write_guard(db: Session, identifier: str) -> bool:
    return db.get(LearnerWriteGuard, guard_key(identifier)) is not None


def lock_learner_write(db: Session, identifier: str, *, erase: bool = False) -> None:
    key = guard_key(identifier)
    db.execute(insert_for(db)(LearnerWriteGuard).values(key_digest=key, erased=False)
               .on_conflict_do_nothing(index_elements=["key_digest"]))
    # UPDATE acquires the write lock on both backends, including for a key with no study row.
    erased = db.scalar(
        update(LearnerWriteGuard).where(LearnerWriteGuard.key_digest == key)
        .values(erased=True if erase else LearnerWriteGuard.erased).returning(LearnerWriteGuard.erased)
    )
    if erased and not erase:
        raise HTTPException(409, "Learner record is unavailable.")
