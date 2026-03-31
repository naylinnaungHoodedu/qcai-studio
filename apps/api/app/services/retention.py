from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.db_models import (
    AnalyticsEvent,
    ArenaMatchRecord,
    ArenaProfile,
    BuilderRun,
    BuilderShare,
    LearnerProfile,
    LearningPulse,
    Note,
    PeerReview,
    ProjectSubmission,
    PublicWebVital,
    QAInteraction,
    QuizAttempt,
    SupportRequest,
    UserSession,
)


PUBLIC_WEB_VITAL_RETENTION_DAYS = 30
SUPPORT_REQUEST_RETENTION_DAYS = 540
GUEST_STUDY_RETENTION_DAYS = 365


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run_retention_cleanup(db: Session) -> None:
    now = utc_now()
    guest_cutoff = now - timedelta(days=GUEST_STUDY_RETENTION_DAYS)
    stale_guest_submission_ids = list(
        db.scalars(
            select(ProjectSubmission.id).where(
                ProjectSubmission.user_id.like("guest-%"),
                ProjectSubmission.created_at < guest_cutoff,
            )
        )
    )

    db.execute(delete(UserSession).where(UserSession.expires_at < now))
    db.execute(
        delete(Note).where(
            Note.user_id.like("guest-%"),
            Note.created_at < guest_cutoff,
        )
    )
    db.execute(
        delete(QuizAttempt).where(
            QuizAttempt.user_id.like("guest-%"),
            QuizAttempt.created_at < guest_cutoff,
        )
    )
    db.execute(
        delete(QAInteraction).where(
            QAInteraction.user_id.like("guest-%"),
            QAInteraction.created_at < guest_cutoff,
        )
    )
    db.execute(
        delete(AnalyticsEvent).where(
            AnalyticsEvent.user_id.like("guest-%"),
            AnalyticsEvent.created_at < guest_cutoff,
        )
    )
    db.execute(
        delete(BuilderRun).where(
            BuilderRun.user_id.like("guest-%"),
            BuilderRun.created_at < guest_cutoff,
        )
    )
    db.execute(
        delete(BuilderShare).where(
            BuilderShare.user_id.like("guest-%"),
            BuilderShare.created_at < guest_cutoff,
        )
    )
    db.execute(
        delete(LearningPulse).where(
            LearningPulse.user_id.like("guest-%"),
            LearningPulse.created_at < guest_cutoff,
        )
    )
    db.execute(
        delete(LearnerProfile).where(
            LearnerProfile.user_id.like("guest-%"),
            LearnerProfile.created_at < guest_cutoff,
        )
    )
    if stale_guest_submission_ids:
        db.execute(delete(PeerReview).where(PeerReview.submission_id.in_(stale_guest_submission_ids)))
    db.execute(
        delete(PeerReview).where(
            PeerReview.reviewer_user_id.like("guest-%"),
            PeerReview.created_at < guest_cutoff,
        )
    )
    db.execute(
        delete(ProjectSubmission).where(
            ProjectSubmission.user_id.like("guest-%"),
            ProjectSubmission.created_at < guest_cutoff,
        )
    )
    db.execute(
        delete(ArenaProfile).where(
            ArenaProfile.player_id.like("guest-%"),
            ArenaProfile.created_at < guest_cutoff,
        )
    )
    db.execute(
        delete(ArenaMatchRecord).where(
            or_(
                ArenaMatchRecord.player_id.like("guest-%"),
                ArenaMatchRecord.opponent_id.like("guest-%"),
            ),
            ArenaMatchRecord.created_at < guest_cutoff,
        )
    )
    db.execute(
        delete(PublicWebVital).where(
            PublicWebVital.created_at < now - timedelta(days=PUBLIC_WEB_VITAL_RETENTION_DAYS)
        )
    )
    db.execute(
        delete(SupportRequest).where(
            SupportRequest.created_at < now - timedelta(days=SUPPORT_REQUEST_RETENTION_DAYS)
        )
    )
    db.commit()
