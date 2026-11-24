from collections.abc import Iterable
import re
import secrets

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db_models import ArenaProfile, BuilderShare, LearnerWriteGuard, ProjectSubmission, PublicHandle
from app.services.learner_record_lock import guard_key, lock_learner_write, phase8_writes_enabled

# Seeded audit personas are fictional and already listed on the public audit-fixtures page.
PUBLIC_FIXTURE_ID_PATTERN = re.compile(r"fixture-ac-\d{2}", re.IGNORECASE)


def _new_handle() -> str:
    return f"learner-{secrets.token_hex(6)}"


def _lock_projection(db: Session, user_id: str) -> None:
    writer = db.info.get("learner_writer")
    if writer is not None and writer.identifier == user_id:
        writer.lock(db)
        return
    lock_learner_write(db, user_id)
    guard = db.get(LearnerWriteGuard, guard_key(user_id), populate_existing=True)
    if guard.erasure_epoch is not None:
        # A retained principal may have reopened their write guard while a public read still holds erased rows.
        visible = or_(
            select(ArenaProfile.id).where(ArenaProfile.player_id == user_id).exists(),
            select(BuilderShare.id).where(BuilderShare.user_id == user_id).exists(),
            select(ProjectSubmission.id).where(ProjectSubmission.user_id == user_id).exists(),
        )
        if not db.scalar(select(visible)):
            raise HTTPException(409, "Public learner activity is no longer available.")


def public_handles(db: Session, user_ids: Iterable[str], *, retry: bool = True) -> dict[str, str]:
    """Map internal ids to stable public handles, assigning a random handle on first use."""
    wanted = set(user_ids)
    handles = {user_id: user_id for user_id in wanted if PUBLIC_FIXTURE_ID_PATTERN.fullmatch(user_id)}
    missing = wanted - handles.keys()
    if not missing:
        return handles

    for row in db.scalars(select(PublicHandle).where(PublicHandle.user_id.in_(missing))):
        handles[row.user_id] = row.handle
    missing = wanted - handles.keys()
    if not missing:
        return handles

    if phase8_writes_enabled(get_settings()):
        for user_id in sorted(missing):
            _lock_projection(db, user_id)
    created = {user_id: _new_handle() for user_id in sorted(missing)}
    db.add_all(PublicHandle(user_id=user_id, handle=handle) for user_id, handle in created.items())
    try:
        db.commit()
    except IntegrityError:
        # A concurrent request assigned a handle first; read the stored ones instead, once.
        db.rollback()
        if not retry:
            raise
        return public_handles(db, wanted, retry=False)
    handles.update(created)
    return handles


def public_handle(db: Session, user_id: str) -> str:
    return public_handles(db, [user_id])[user_id]
