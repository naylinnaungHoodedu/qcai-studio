from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db_models import (
    GuestLegacyUpgrade, LearnerClaimAudit, LearnerErasureAudit, LearnerGuestRevocation, LearnerSubject,
    PublicWebVital, RateLimitCounter, SecurityEvent, SupportRequest, UserSession,
)
from app.services.erasure import RETENTION_EXEMPT_TABLES, erase_stale_guest_rows
from app.services.guest_sessions import guest_credential_digest
from app.services.learner_record_lock import insert_for


PUBLIC_WEB_VITAL_RETENTION_DAYS = 30
SUPPORT_REQUEST_RETENTION_DAYS = 540
GUEST_STUDY_RETENTION_DAYS = 365
# The security log's DELETE trigger (app.core.schema_upgrades) refuses rows younger than this.
SECURITY_EVENT_RETENTION_DAYS = 365

_GUEST_CREATED_TABLES = (
    "analytics_events", "arena_match_records", "arena_profiles", "builder_runs", "builder_shares",
    "learner_consent_changes", "learner_issued_replicas", "learner_profiles", "learner_record_operations",
    "learner_records", "learner_replicas", "learning_pulses", "notes", "project_submissions", "public_handles",
    "qa_interactions", "quiz_attempts", "tutor_threads", "tutor_turn_idempotency", "learner_assessment_facts",
    "peer_reviews", "tutor_turns", "v3_flags",
)
_RETENTION_CLASSES = {
    **dict.fromkeys(_GUEST_CREATED_TABLES, "guest-created/durable-until-erasure"),
    "guest_legacy_upgrades": "guest-upgrade-age",
    "guest_revocations": "credential-protection",
    "learner_consents": "guest-updated/durable-until-erasure",
    "learner_subjects": "until-erasure",
    "user_accounts": "until-erasure",
    "user_sessions": "session-expiry",
    "v3_claims": "until-erasure",
}


def retention_classes() -> dict[str, str]:
    return dict(_RETENTION_CLASSES)


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
    # Expired rate-limit and lockout windows; an increment restarts an expired row anyway.
    record(
        "rate_limit_counters",
        db.execute(delete(RateLimitCounter).where(RateLimitCounter.expires_at < now.timestamp())).rowcount,
    )
    # Guest study rows in every user-keyed table, with the rows that depend on them.
    cutoff = now - timedelta(days=GUEST_STUDY_RETENTION_DAYS)
    privacy_on = get_settings().learner_privacy == "on"
    bound_guests = select(LearnerSubject.user_id).where(LearnerSubject.provider == "guest") if privacy_on else None
    age_columns = {
        name: "updated_at" if kind == "guest-updated/durable-until-erasure" else "created_at"
        for name, kind in retention_classes().items()
        if name not in RETENTION_EXEMPT_TABLES and (
            kind == "guest-created/durable-until-erasure" or privacy_on and kind == "guest-updated/durable-until-erasure"
        )
    }
    for table, deleted in erase_stale_guest_rows(db, cutoff, age_columns=age_columns, bound_guest_subjects=bound_guests).items():
        record(table, deleted)
    if privacy_on and retention_classes()["guest_legacy_upgrades"] == "guest-upgrade-age":
        # The digest preserves the one-shot property when the raw upgrade row expires.
        stale = list(db.scalars(select(GuestLegacyUpgrade.guest_id).where(GuestLegacyUpgrade.upgraded_at < cutoff)))
        for guest in stale:
            db.execute(insert_for(db)(LearnerGuestRevocation).values(credential_digest=guest_credential_digest(guest))
                       .on_conflict_do_nothing(index_elements=["credential_digest"]))
        if stale:
            record("guest_legacy_upgrades", db.execute(delete(GuestLegacyUpgrade).where(
                GuestLegacyUpgrade.upgraded_at < cutoff,
            )).rowcount)
    if privacy_on:
        audit_cutoff = now - timedelta(days=SECURITY_EVENT_RETENTION_DAYS)
        for model in (LearnerClaimAudit, LearnerErasureAudit):
            record(model.__tablename__, db.execute(delete(model).where(model.created_at < audit_cutoff)).rowcount)
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
    # No rule touches response_ledger or response_ledger_head: plan 12.8 (the retention period) is an open decision,
    # so the ledger is retained (configuration package owner_decisions.PLAN-12.8, DI-45) and its triggers refuse DELETE.
    # A day past the trigger's limit, so a database clock a little behind this one cannot refuse the pass.
    # The newest event always stays, so the chain continues instead of restarting from the genesis hash.
    record(
        "security_events",
        db.execute(
            delete(SecurityEvent).where(
                SecurityEvent.created_at < now - timedelta(days=SECURITY_EVENT_RETENTION_DAYS + 1),
                SecurityEvent.seq < select(func.max(SecurityEvent.seq)).scalar_subquery(),
            )
        ).rowcount,
    )
    db.commit()
    return counts
