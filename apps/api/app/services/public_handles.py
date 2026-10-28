from collections.abc import Iterable
import re
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db_models import PublicHandle

# Seeded audit personas are fictional and already listed on the public audit-fixtures page.
PUBLIC_FIXTURE_ID_PATTERN = re.compile(r"fixture-ac-\d{2}", re.IGNORECASE)


def _new_handle() -> str:
    return f"learner-{secrets.token_hex(6)}"


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
