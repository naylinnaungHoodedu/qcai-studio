from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
from uuid import uuid4

from fastapi import HTTPException, status
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
    QAInteraction,
    QuizAttempt,
    UserAccount,
    UserSession,
)


AUTH_SESSION_COOKIE_NAME = "qcai_session_token"
AUTH_CSRF_COOKIE_NAME = "qcai_auth_csrf"
AUTH_CSRF_HEADER = "x-qcai-csrf"
AUTH_SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PASSWORD_HASH_NAME = "sha256"
_PASSWORD_HASH_ITERATIONS = 240_000


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if not _EMAIL_PATTERN.fullmatch(email):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Enter a valid email address.")
    return email


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        _PASSWORD_HASH_NAME,
        password.encode("utf-8"),
        bytes.fromhex(salt),
        _PASSWORD_HASH_ITERATIONS,
    )
    return f"pbkdf2_{_PASSWORD_HASH_NAME}${_PASSWORD_HASH_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, iteration_text, salt, digest = stored_hash.split("$", 3)
    except ValueError:
        return False
    if scheme != f"pbkdf2_{_PASSWORD_HASH_NAME}":
        return False
    try:
        iterations = int(iteration_text)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac(
        _PASSWORD_HASH_NAME,
        password.encode("utf-8"),
        bytes.fromhex(salt),
        iterations,
    ).hex()
    return hmac.compare_digest(candidate, digest)


def register_local_account(db: Session, email: str, password: str) -> UserAccount:
    normalized_email = normalize_email(email)
    existing = db.scalars(select(UserAccount).where(UserAccount.email == normalized_email)).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with that email already exists.")
    account = UserAccount(
        user_id=f"acct-{uuid4()}",
        email=normalized_email,
        password_hash=hash_password(password),
        role="learner",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def authenticate_local_account(db: Session, email: str, password: str) -> UserAccount:
    normalized_email = normalize_email(email)
    account = db.scalars(select(UserAccount).where(UserAccount.email == normalized_email)).first()
    if not account or not verify_password(password, account.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    return account


def create_local_session(db: Session, user_id: str) -> tuple[str, str, datetime]:
    session_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(24)
    expires_at = utc_now() + timedelta(seconds=AUTH_SESSION_MAX_AGE_SECONDS)
    db.add(
        UserSession(
            user_id=user_id,
            session_token_hash=hash_session_token(session_token),
            expires_at=expires_at,
        )
    )
    db.commit()
    return session_token, csrf_token, expires_at


def resolve_local_account_from_session(db: Session, session_token: str | None) -> UserAccount | None:
    if not session_token:
        return None
    session = db.scalars(
        select(UserSession).where(UserSession.session_token_hash == hash_session_token(session_token))
    ).first()
    if not session:
        return None
    if normalize_timestamp(session.expires_at) <= utc_now():
        db.delete(session)
        db.commit()
        return None
    return db.scalars(select(UserAccount).where(UserAccount.user_id == session.user_id)).first()


def revoke_local_session(db: Session, session_token: str | None) -> None:
    if not session_token:
        return
    db.execute(delete(UserSession).where(UserSession.session_token_hash == hash_session_token(session_token)))
    db.commit()


def delete_local_account(db: Session, user_id: str, password: str) -> None:
    account = db.scalars(select(UserAccount).where(UserAccount.user_id == user_id)).first()
    if not account or not verify_password(password, account.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Password confirmation failed.")

    submission_ids = list(
        db.scalars(select(ProjectSubmission.id).where(ProjectSubmission.user_id == user_id))
    )

    if submission_ids:
        db.execute(delete(PeerReview).where(PeerReview.submission_id.in_(submission_ids)))

    db.execute(delete(PeerReview).where(PeerReview.reviewer_user_id == user_id))
    db.execute(delete(ProjectSubmission).where(ProjectSubmission.user_id == user_id))
    db.execute(delete(LearningPulse).where(LearningPulse.user_id == user_id))
    db.execute(delete(LearnerProfile).where(LearnerProfile.user_id == user_id))
    db.execute(delete(BuilderShare).where(BuilderShare.user_id == user_id))
    db.execute(delete(BuilderRun).where(BuilderRun.user_id == user_id))
    db.execute(delete(AnalyticsEvent).where(AnalyticsEvent.user_id == user_id))
    db.execute(delete(QAInteraction).where(QAInteraction.user_id == user_id))
    db.execute(delete(QuizAttempt).where(QuizAttempt.user_id == user_id))
    db.execute(delete(Note).where(Note.user_id == user_id))
    db.execute(delete(ArenaProfile).where(ArenaProfile.player_id == user_id))
    db.execute(delete(ArenaMatchRecord).where(or_(ArenaMatchRecord.player_id == user_id, ArenaMatchRecord.opponent_id == user_id)))
    db.execute(delete(UserSession).where(UserSession.user_id == user_id))
    db.execute(delete(UserAccount).where(UserAccount.user_id == user_id))
    db.commit()
