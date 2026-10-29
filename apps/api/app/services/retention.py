from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db_models import PublicWebVital, SupportRequest, UserSession
from app.services.erasure import erase_stale_guest_rows


PUBLIC_WEB_VITAL_RETENTION_DAYS = 30
SUPPORT_REQUEST_RETENTION_DAYS = 540
GUEST_STUDY_RETENTION_DAYS = 365


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run_retention_cleanup(db: Session, now: datetime | None = None) -> dict[str, int]:
    """Apply every retention rule once and return the rows deleted per table."""
    now = now or utc_now()
    counts: dict[str, int] = {}

    def record(table: str, deleted: int | None) -> None:
        if deleted:
            counts[table] = counts.get(table, 0) + deleted

    record("user_sessions", db.execute(delete(UserSession).where(UserSession.expires_at < now)).rowcount)
    # Guest study rows in every user-keyed table, with the rows that depend on them.
    for table, deleted in erase_stale_guest_rows(db, now - timedelta(days=GUEST_STUDY_RETENTION_DAYS)).items():
        record(table, deleted)
    record(
        "public_web_vitals",
        db.execute(
            delete(PublicWebVital).where(
                PublicWebVital.created_at < now - timedelta(days=PUBLIC_WEB_VITAL_RETENTION_DAYS)
            )
        ).rowcount,
    )
    record(
        "support_requests",
        db.execute(
            delete(SupportRequest).where(
                SupportRequest.created_at < now - timedelta(days=SUPPORT_REQUEST_RETENTION_DAYS)
            )
        ).rowcount,
    )
    db.commit()
    return counts
