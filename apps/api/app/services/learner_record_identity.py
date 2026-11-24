"""Phase 8 credential-to-subject binding and transactional guest claims."""

import hashlib
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import case, delete, or_, select, update
from sqlalchemy.orm import Session

from app.core.safe_input import text_matches
from app.core.client_identity import keyed_digest
from app.core.config import Settings, get_settings
from app.core.guest_tokens import verify_guest_token
from app.db_models import (
    GuestLegacyUpgrade, LearnerClaimAudit, LearnerGuestRevocation, LearnerRecord, LearnerRecordOperation,
    LearnerReplica, LearnerSubject, TutorTurnIdempotency, UserAccount,
)
from app.services.erasure import USER_KEY_COLUMNS, user_keyed_tables
from app.services.guest_sessions import _was_ever_public, guest_credential_digest, is_guest_revoked
from app.services.learner_record import _wins
from app.services.learner_record_lock import WriteObservation, has_write_guard, insert_for, lock_learner_write, phase8_writes_enabled
from app.services.learner_record_sync import lock_learner_record


_LEARNER_TABLES = {
    "learner_records", "learner_replicas", "learner_record_operations", "learner_issued_replicas",
    "learner_assessment_facts",
}
_PRINCIPAL_TABLES = {
    "user_accounts", "user_sessions", "guest_revocations", "guest_legacy_upgrades", "learner_subjects",
    "learner_consents", "learner_consent_changes",
}
_ONE_PER_OWNER = {"public_handles": "user_id", "learner_profiles": "user_id", "arena_profiles": "player_id"}


def principal_digest(provider: str, identifier: str) -> str:
    return hashlib.sha256(f"qcai-principal-v1:{provider}:{identifier}".encode("utf-8")).hexdigest()


def find_subject(db: Session, provider: str, identifier: str) -> str | None:
    binding = db.get(LearnerSubject, principal_digest(provider, identifier))
    return binding.user_id if binding else None


def _merge_numeric(target: dict, source: dict) -> dict:
    return {key: max(target.get(key, 0), source.get(key, 0)) for key in target.keys() | source.keys()}


def _merge_records(db: Session, former: str, target: str) -> int:
    old = db.get(LearnerRecord, former)
    if old is None:
        return 0
    new = db.get(LearnerRecord, target)
    if new is None:
        # Moving the initial record changes its owner key, not the version the caller read.
        old.user_id = target
        db.flush()
        return 1
    new.mastery = _merge_numeric(new.mastery, old.mastery)
    new.completed_items = sorted(set(new.completed_items) | set(old.completed_items))
    new.attempt_counters = {
        key: _merge_numeric(new.attempt_counters.get(key, {}), old.attempt_counters.get(key, {}))
        for key in new.attempt_counters.keys() | old.attempt_counters.keys()
    }
    if _wins(new.cursor, old.cursor.get("logical_counter", 0), old.cursor.get("replica_id", "")):
        new.cursor = dict(old.cursor)
    preferences = dict(new.preferences)
    for key, value in old.preferences.items():
        if _wins(preferences.get(key), value["logical_counter"], value["replica_id"]):
            preferences[key] = value
    new.preferences = preferences
    new.version_vector = _merge_numeric(new.version_vector, old.version_vector)
    new.record_version = max(new.record_version, old.record_version) + 1
    db.delete(old)
    db.flush()
    return 1


def _discard_duplicate_key(db: Session, model, key, former: str, target: str) -> None:
    existing = select(key).where(model.user_id == target)
    db.execute(delete(model).where(model.user_id == former, key.in_(existing)))


def _transfer(db: Session, former: str, target: str, *, learner_only: bool) -> dict[str, int]:
    moved = {}
    if learner_only:
        lock_learner_write(db, target)
        moved["learner_records"] = _merge_records(db, former, target)
        for row in db.scalars(select(LearnerReplica).where(LearnerReplica.user_id == former)):
            existing = db.scalar(select(LearnerReplica).where(
                LearnerReplica.user_id == target, LearnerReplica.replica_id == row.replica_id,
            ))
            if existing is not None:
                existing.last_logical_counter = max(existing.last_logical_counter, row.last_logical_counter)
                db.delete(row)
        db.flush()
        _discard_duplicate_key(db, LearnerRecordOperation, LearnerRecordOperation.operation_id, former, target)
    else:
        _discard_duplicate_key(db, TutorTurnIdempotency, TutorTurnIdempotency.key_sha256, former, target)
    for table in user_keyed_tables():
        name = table.name
        if name in _PRINCIPAL_TABLES or (name in _LEARNER_TABLES) != learner_only or name == "learner_records":
            continue
        if name in _ONE_PER_OWNER:
            owner = table.c[_ONE_PER_OWNER[name]]
            if db.scalar(select(owner).where(owner == target).limit(1)) is not None:
                db.execute(delete(table).where(owner == former))
        columns = [table.c[key] for key in USER_KEY_COLUMNS if key in table.c]
        changes = {column.key: case((column == former, target), else_=column) for column in columns}
        count = db.execute(update(table).where(or_(*(column == former for column in columns))).values(**changes)).rowcount
        if count:
            moved[name] = int(count)
    db.expire_all()
    return moved


def _recheck_principal(db: Session, provider: str, identifier: str) -> None:
    if provider == "local" and db.get(UserAccount, identifier, populate_existing=True) is None:
        raise HTTPException(401, "Authentication required.")
    if provider == "guest" and is_guest_revoked(db, identifier):
        raise HTTPException(401, "Guest session revoked.")


def bind_subject(
    db: Session, provider: str, identifier: str, *, verify_account: bool = False,
    observation: WriteObservation | None = None,
) -> str:
    lock_learner_write(db, identifier, observation=observation if provider in {"auth0", "demo"} else None)
    if verify_account:
        _recheck_principal(db, provider, identifier)
    digest = principal_digest(provider, identifier)
    candidate = f"subj-{uuid4().hex}"
    db.execute(
        insert_for(db)(LearnerSubject).values(principal_digest=digest, user_id=candidate, provider=provider)
        .on_conflict_do_nothing(index_elements=["principal_digest"])
    )
    subject = find_subject(db, provider, identifier)
    if subject is None:
        raise RuntimeError("Learner subject unavailable after binding.")
    if subject == candidate or db.get(LearnerRecord, identifier) is not None:
        _transfer(db, identifier, subject, learner_only=True)
    # Materialize version zero only on a write, and hold this lock across the caller's write.
    lock_learner_record(db, subject)
    return subject


def write_subject(
    db: Session, provider: str, identifier: str, *, bind: bool, guarded: bool,
    observation: WriteObservation | None = None,
) -> str:
    if bind:
        return bind_subject(db, provider, identifier, verify_account=True, observation=observation)
    subject = find_subject(db, provider, identifier)
    if guarded or phase8_writes_enabled(get_settings()) or subject or has_write_guard(db, identifier):
        lock_learner_write(db, identifier, observation=observation if provider in {"auth0", "demo"} else None)
        _recheck_principal(db, provider, identifier)
        # Binding and erasure both use the principal lock.
        subject = find_subject(db, provider, identifier)
        if subject:
            lock_learner_write(db, subject)
    return subject or identifier


def mark_erased_subjects(db: Session, provider: str, identifier: str) -> tuple[str, ...]:
    lock_learner_write(db, identifier, erase=True)
    binding = db.scalar(select(LearnerSubject).where(
        LearnerSubject.principal_digest == principal_digest(provider, identifier),
    ).with_for_update().execution_options(populate_existing=True))
    if binding is None or binding.user_id == identifier:
        return (identifier,)
    lock_learner_write(db, binding.user_id, erase=True)
    return (identifier, binding.user_id)


def claim_guest(
    db: Session, provider: str, identifier: str, token: str | None, csrf: str | None, settings: Settings,
    *, verify_account: bool = False, observation: WriteObservation | None = None,
) -> dict[str, int]:
    guest = verify_guest_token(token, settings)
    if provider not in {"local", "auth0"} or guest is None or not csrf or not text_matches(guest.csrf, csrf):
        raise HTTPException(403, "Guest claim requires both verified credentials.")
    lock_learner_write(db, guest.guest_id)
    digest = guest_credential_digest(guest.guest_id)
    if is_guest_revoked(db, guest.guest_id, include_phase8=True) or _was_ever_public(db, guest.guest_id):
        raise HTTPException(409, "Guest record is unavailable for claim.")
    # Insert the one-shot tombstone in the same transaction as the transfer and its audit.
    accepted = db.scalar(
        insert_for(db)(LearnerGuestRevocation).values(credential_digest=digest)
        .on_conflict_do_nothing(index_elements=["credential_digest"])
        .returning(LearnerGuestRevocation.credential_digest)
    )
    if accepted is None:
        raise HTTPException(409, "Guest record is unavailable for claim.")
    subject = bind_subject(db, provider, identifier, verify_account=verify_account, observation=observation)
    formerly_bound = find_subject(db, "guest", guest.guest_id)
    lock_learner_write(db, guest.guest_id, erase=True)
    if formerly_bound:
        lock_learner_write(db, formerly_bound, erase=True)
    moved = _transfer(db, formerly_bound or guest.guest_id, subject, learner_only=True)
    for table in user_keyed_tables():
        if table.name in {"learner_consents", "learner_consent_changes"}:
            db.execute(delete(table).where(table.c.user_id.in_((guest.guest_id, formerly_bound or guest.guest_id))))
    if formerly_bound:
        for name, count in _transfer(db, guest.guest_id, subject, learner_only=True).items():
            moved[name] = moved.get(name, 0) + count
        db.execute(delete(LearnerSubject).where(LearnerSubject.user_id == formerly_bound))
    moved.update(_transfer(db, guest.guest_id, identifier, learner_only=False))
    db.execute(delete(GuestLegacyUpgrade).where(GuestLegacyUpgrade.guest_id == guest.guest_id))
    db.add(LearnerClaimAudit(
        id=f"claim-{uuid4().hex}", guest_digest=keyed_digest(guest.guest_id, "claim-guest"),
        subject_digest=keyed_digest(subject, "claim-subject"), transferred=moved,
    ))
    db.flush()
    return moved
