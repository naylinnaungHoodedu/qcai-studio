"""Guest revocation and the bounded legacy-id migration window (plan task 1.1, Action 20)."""

from datetime import datetime, timezone
import hashlib
import logging
import re
import time

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.guest_tokens import guest_csrf_for, issue_guest_token
from app.db_models import (
    ArenaMatchRecord,
    ArenaProfile,
    BuilderShare,
    GuestLegacyUpgrade,
    GuestRevocation,
    ProjectSubmission,
)

LOGGER = logging.getLogger(__name__)
_LEGACY_GUEST_ID_PATTERN = re.compile(r"guest-[0-9a-f-]{8,64}")
_LEGACY_GUEST_CSRF_PATTERN = re.compile(r"[0-9a-f-]{16,128}")


def guest_log_ref(guest_id: str) -> str:
    # Logs carry a hash reference, never the guest id itself.
    return hashlib.sha256(guest_id.encode("utf-8")).hexdigest()[:12]


def is_guest_revoked(db: Session, guest_id: str) -> bool:
    return db.get(GuestRevocation, guest_id) is not None


def revoke_guest(db: Session, guest_id: str, reason: str) -> GuestRevocation:
    revocation = db.get(GuestRevocation, guest_id)
    if revocation is None:
        revocation = GuestRevocation(guest_id=guest_id, reason=reason)
        db.add(revocation)
        db.commit()
        db.refresh(revocation)
    LOGGER.warning("Guest session revoked ref=%s reason=%s", guest_log_ref(guest_id), reason)
    return revocation


def _was_ever_public(db: Session, guest_id: str) -> bool:
    # Before public handles (Action 17) these tables' ids were served publicly, so anyone may know them.
    exposures = (
        select(BuilderShare.id).where(BuilderShare.user_id == guest_id),
        select(ProjectSubmission.id).where(ProjectSubmission.user_id == guest_id),
        select(ArenaProfile.id).where(ArenaProfile.player_id == guest_id),
        select(ArenaMatchRecord.id).where(
            or_(ArenaMatchRecord.player_id == guest_id, ArenaMatchRecord.opponent_id == guest_id)
        ),
    )
    return any(db.scalars(query.limit(1)).first() is not None for query in exposures)


def legacy_upgrade_window_open(settings: Settings, now: datetime | None = None) -> bool:
    until = settings.guest_legacy_upgrade_until
    return until is not None and (now or datetime.now(timezone.utc)) < until


def upgrade_legacy_guest(
    db: Session, settings: Settings, legacy_guest_id: str, legacy_csrf: str
) -> tuple[str, str] | None:
    """Re-issue a signed token for a legacy guest id, or return None for a fresh identity instead."""
    guest_id = legacy_guest_id.strip().lower()
    if not legacy_upgrade_window_open(settings):
        return None
    if not _LEGACY_GUEST_ID_PATTERN.fullmatch(guest_id):
        return None
    if not _LEGACY_GUEST_CSRF_PATTERN.fullmatch(legacy_csrf.strip().lower()):
        return None
    if is_guest_revoked(db, guest_id) or db.get(GuestLegacyUpgrade, guest_id) is not None:
        return None
    if _was_ever_public(db, guest_id):
        # AC-1-12: an id that appeared in a public response cannot become a credential.
        LOGGER.warning("Legacy guest upgrade refused (public id) ref=%s", guest_log_ref(guest_id))
        return None

    db.add(GuestLegacyUpgrade(guest_id=guest_id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    issued_at = int(time.time())
    LOGGER.warning("Legacy guest upgraded ref=%s", guest_log_ref(guest_id))
    return (
        issue_guest_token(settings.guest_token_secret, guest_id, issued_at),
        guest_csrf_for(settings.guest_token_secret, guest_id, issued_at),
    )
