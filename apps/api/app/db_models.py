from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class UserAccount(Base):
    __tablename__ = "user_accounts"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="learner")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class PublicHandle(Base):
    # Random stand-in for a user, guest or Arena player id in public responses; nothing derives it from the id.
    __tablename__ = "public_handles"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    handle: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GuestRevocation(Base):
    # Every token for a revoked guest id is rejected, whenever it was issued.
    __tablename__ = "guest_revocations"

    guest_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    reason: Mapped[str] = mapped_column(String(255))
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GuestLegacyUpgrade(Base):
    # A legacy unsigned guest id is re-issued a signed token at most once.
    __tablename__ = "guest_legacy_upgrades"

    guest_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    upgraded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RateLimitCounter(Base):
    # Fixed-window counters shared by every API instance: the rate limiter and the sign-in lockout (task 1.6).
    # The key is a keyed digest, never a raw principal, email or address.
    __tablename__ = "rate_limit_counters"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[float] = mapped_column(Float, index=True)


class SecurityEvent(Base):
    # Append-only and hash-chained (plan task 1.7); see app.services.security_log. Database triggers refuse
    # UPDATE, and DELETE inside the retention period. No learner id is stored: subject and source are keyed
    # digests, so erasure has nothing to remove here.
    __tablename__ = "security_events"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    outcome: Mapped[str] = mapped_column(String(16))
    actor_role: Mapped[str] = mapped_column(String(32))
    subject_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_user_id_expires_at", "user_id", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String(255), ForeignKey("user_accounts.user_id", ondelete="CASCADE"), index=True)
    session_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (
        Index("ix_notes_user_id_lesson_slug_created_at", "user_id", "lesson_slug", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    lesson_slug: Mapped[str] = mapped_column(String(255), index=True)
    body: Mapped[str] = mapped_column(Text)
    anchor_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    anchor_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    __table_args__ = (
        Index("ix_quiz_attempts_user_id_lesson_slug_created_at", "user_id", "lesson_slug", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    lesson_slug: Mapped[str] = mapped_column(String(255), index=True)
    score: Mapped[int] = mapped_column(Integer)
    responses: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QAInteraction(Base):
    __tablename__ = "qa_interactions"
    __table_args__ = (
        Index("ix_qa_interactions_user_id_lesson_slug_created_at", "user_id", "lesson_slug", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    lesson_slug: Mapped[str | None] = mapped_column(String(255), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    __table_args__ = (
        Index("ix_analytics_events_user_id_event_type", "user_id", "event_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    lesson_slug: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PublicWebVital(Base):
    __tablename__ = "public_web_vitals"
    __table_args__ = (
        Index("ix_public_web_vitals_metric_name_created_at", "metric_name", "created_at"),
        Index("ix_public_web_vitals_path_created_at", "path", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    metric_id: Mapped[str] = mapped_column(String(255), index=True)
    metric_name: Mapped[str] = mapped_column(String(32), index=True)
    path: Mapped[str] = mapped_column(String(255), index=True)
    value: Mapped[float] = mapped_column(Float)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    rating: Mapped[str] = mapped_column(String(32), index=True)
    navigation_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    connection_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class SupportRequest(Base):
    __tablename__ = "support_requests"
    __table_args__ = (
        Index("ix_support_requests_request_type_created_at", "request_type", "created_at"),
        Index("ix_support_requests_email_created_at", "email", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(320), index=True)
    organization: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_type: Mapped[str] = mapped_column(String(64), index=True)
    page_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="received", index=True)
    requester_origin: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ArenaProfile(Base):
    __tablename__ = "arena_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    player_id: Mapped[str] = mapped_column(String(255), index=True, unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    xp: Mapped[int] = mapped_column(Integer, default=0)
    matches_played: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    skill_rating: Mapped[int] = mapped_column(Integer, default=1000)
    adaptive_level: Mapped[int] = mapped_column(Integer, default=2)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ArenaMatchRecord(Base):
    __tablename__ = "arena_match_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    player_id: Mapped[str] = mapped_column(String(255), index=True)
    opponent_id: Mapped[str] = mapped_column(String(255), index=True)
    mode: Mapped[str] = mapped_column(String(50), index=True)
    result: Mapped[str] = mapped_column(String(50), index=True)
    score: Mapped[int] = mapped_column(Integer)
    correct_answers: Mapped[int] = mapped_column(Integer, default=0)
    total_rounds: Mapped[int] = mapped_column(Integer, default=0)
    xp_delta: Mapped[int] = mapped_column(Integer, default=0)
    difficulty_band: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BuilderRun(Base):
    __tablename__ = "builder_runs"
    __table_args__ = (
        Index("ix_builder_runs_user_id_scenario_slug", "user_id", "scenario_slug"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    scenario_slug: Mapped[str] = mapped_column(String(255), index=True)
    placements: Mapped[dict] = mapped_column(JSON)
    correct_slots: Mapped[int] = mapped_column(Integer, default=0)
    total_slots: Mapped[int] = mapped_column(Integer, default=0)
    completion_percent: Mapped[int] = mapped_column(Integer, default=0)
    points_earned: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(50), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BuilderShare(Base):
    __tablename__ = "builder_shares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    scenario_slug: Mapped[str] = mapped_column(String(255), index=True)
    caption: Mapped[str] = mapped_column(Text)
    completion_percent: Mapped[int] = mapped_column(Integer, default=0)
    map_snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LearnerProfile(Base):
    __tablename__ = "learner_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True, unique=True)
    target_role: Mapped[str] = mapped_column(String(255), default="Quantum ML Engineer")
    weekly_goal_hours: Mapped[int] = mapped_column(Integer, default=4)
    preferred_pace: Mapped[str] = mapped_column(String(50), default="balanced")
    focus_area: Mapped[str | None] = mapped_column(String(255), nullable=True)
    self_ratings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class LearningPulse(Base):
    __tablename__ = "learning_pulses"
    __table_args__ = (
        Index("ix_learning_pulses_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    motivation_level: Mapped[int] = mapped_column(Integer, default=3)
    focus_level: Mapped[int] = mapped_column(Integer, default=3)
    energy_level: Mapped[int] = mapped_column(Integer, default=3)
    session_minutes: Mapped[int] = mapped_column(Integer, default=25)
    today_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocker: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectSubmission(Base):
    __tablename__ = "project_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    project_slug: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(255))
    solution_summary: Mapped[str] = mapped_column(Text)
    implementation_notes: Mapped[str] = mapped_column(Text)
    confidence_level: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String(50), index=True, default="submitted")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    ai_feedback_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_recommendations: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class PeerReview(Base):
    __tablename__ = "peer_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    submission_id: Mapped[int] = mapped_column(Integer, ForeignKey("project_submissions.id"), index=True)
    reviewer_user_id: Mapped[str] = mapped_column(String(255), index=True)
    rubric_scores: Mapped[dict] = mapped_column(JSON)
    overall_score: Mapped[float] = mapped_column(Float)
    feedback: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LearnerRecord(Base):
    """Authoritative materialized learner state; derived dashboard progress remains read-only."""

    __tablename__ = "learner_records"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    record_version: Mapped[int] = mapped_column(Integer, default=0)
    mastery: Mapped[dict] = mapped_column(JSON, default=dict)
    completed_items: Mapped[list] = mapped_column(JSON, default=list)
    attempt_counters: Mapped[dict] = mapped_column(JSON, default=dict)
    cursor: Mapped[dict] = mapped_column(JSON, default=dict)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    version_vector: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True
    )


class LearnerReplica(Base):
    __tablename__ = "learner_replicas"
    __table_args__ = (UniqueConstraint("user_id", "replica_id", name="uq_learner_replica_user_replica"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    replica_id: Mapped[str] = mapped_column(String(128), index=True)
    last_logical_counter: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LearnerRecordOperation(Base):
    __tablename__ = "learner_record_operations"
    __table_args__ = (
        UniqueConstraint("user_id", "operation_id", name="uq_learner_record_operation_user_operation"),
        Index("ix_learner_record_operations_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    operation_id: Mapped[str] = mapped_column(String(128), index=True)
    replica_id: Mapped[str] = mapped_column(String(128), index=True)
    logical_counter: Mapped[int] = mapped_column(Integer)
    causal_vector: Mapped[dict] = mapped_column(JSON, default=dict)
    operation_type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TutorThread(Base):
    __tablename__ = "tutor_threads"
    __table_args__ = (Index("ix_tutor_threads_user_id_updated_at", "user_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TutorMessage(Base):
    __tablename__ = "tutor_messages"
    __table_args__ = (Index("ix_tutor_messages_thread_id_created_at", "thread_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), ForeignKey("tutor_threads.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), index=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TutorTurn(Base):
    __tablename__ = "tutor_turns"
    __table_args__ = (Index("ix_tutor_turns_thread_id_created_at", "thread_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), ForeignKey("tutor_threads.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    resolved_query: Mapped[str] = mapped_column(Text)
    retrieval_mode: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(128))
    model: Mapped[str] = mapped_column(String(255))
    decision: Mapped[str] = mapped_column(String(32), index=True)
    decision_reason: Mapped[str] = mapped_column(String(255))
    citations: Mapped[list] = mapped_column(JSON, default=list)
    claims: Mapped[list] = mapped_column(JSON, default=list)
    corpus_version: Mapped[str] = mapped_column(String(255))
    policy_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Phase 3 (spec 18.8 F12): true when the image that created the turn ledgers its delivery (TUTOR_LEDGER_ENABLED
    # on), false under the kill switch, null when an image that keeps no ledger created it (before Phase 3, or during
    # a rollback window). A turn without a ledger record is a lost record only when this is true.
    ledger_record_expected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class TutorTurnIdempotency(Base):
    # POST /tutor/turns Idempotency-Key records (plan 7.3 "mutations carry client keys"; DI-40; Phase 3 spec 7.13). A
    # retried POST with the same key from the same caller returns response_body, the first turn's response, instead of
    # creating a second turn. The key itself is never stored: key_sha256 is its sha256, unique per caller. Past the
    # package's idempotency ttl_hours the key starts a new turn (the expired row is replaced). User-keyed, so erasure
    # deletes these rows and guest retention deletes a guest's with the rest of its data; otherwise a row lives as
    # long as the turn it answers for. The row is claimed (committed, turn_id null) before the turn runs, filled in the
    # turn's own transaction, and released if the turn fails, so two concurrent requests with one key never create
    # two turns. Every fill and release is conditional on the claim's random claim_token (and the fill on the row
    # still having no response), so a request that outlived its lease cannot fill or release another request's claim,
    # even where SQLite reuses a deleted row's id (spec 18.8 F13); AUTOINCREMENT stops that reuse as well.
    __tablename__ = "tutor_turn_idempotency"
    __table_args__ = (
        UniqueConstraint("user_id", "key_sha256", name="uq_tutor_turn_idempotency_user_key"),
        Index("ix_tutor_turn_idempotency_created_at", "created_at"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255))
    key_sha256: Mapped[str] = mapped_column(String(64))
    request_sha256: Mapped[str] = mapped_column(String(64))
    # Null while the first request with this key is still running (a concurrent retry then gets 409).
    turn_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Random per claim (uuid4 hex). Null only on rows an unreleased Phase 3 build made before it existed.
    claim_token: Mapped[str | None] = mapped_column(String(32), nullable=True)


class CorpusSpan(Base):
    # Span identity (plan Phase 2 task 2.2): append-only and text-free, so a stored citation keeps resolving after
    # its span leaves the current corpus (AC-2-3, and AC-12-6 later). Database triggers refuse UPDATE, DELETE and
    # TRUNCATE (schema_upgrades); rows are inserted if missing on (span_id, item_version). No learner data: no
    # column names a person, so erasure and retention never touch it. Only public-plane spans can be stored.
    __tablename__ = "corpus_spans"
    __table_args__ = (
        UniqueConstraint("span_id", "item_version", name="uq_corpus_spans_span_id_item_version"),
        CheckConstraint("plane = 'public'", name="ck_corpus_spans_public_plane"),
        Index("ix_corpus_spans_legacy_key_lexical", "legacy_key_lexical"),
        Index("ix_corpus_spans_legacy_key_semantic", "legacy_key_semantic"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    span_id: Mapped[str] = mapped_column(String(80), index=True)
    scheme: Mapped[str] = mapped_column(String(16))
    item_id: Mapped[str] = mapped_column(String(255), index=True)
    item_version: Mapped[str] = mapped_column(String(64))
    item_kind: Mapped[str] = mapped_column(String(16))
    plane: Mapped[str] = mapped_column(String(16), default="public")
    section_ordinal: Mapped[int] = mapped_column(Integer)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    source_title_hash: Mapped[str] = mapped_column(String(64))
    section_title_hash: Mapped[str] = mapped_column(String(64))
    legacy_key_lexical: Mapped[str] = mapped_column(String(64))
    legacy_key_semantic: Mapped[str] = mapped_column(String(64))
    corpus_version_first_seen: Mapped[str] = mapped_column(String(64))
    registered_by: Mapped[str] = mapped_column(String(32))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResponseLedgerRecord(Base):
    # Append-only, hash-chained provenance record of every tutor response (plan task 3.8, 7.5; R-22). No user id and
    # no learner text: the learner link is tutor_turns (user-keyed, erasable), so after erasure a row stays but is
    # unlinkable. No foreign key to any tutor table, so erasure never reaches it. Triggers refuse UPDATE, DELETE and
    # TRUNCATE (schema_upgrades); an insert must extend the chain. See app.services.ledger.
    __tablename__ = "response_ledger"
    __table_args__ = (
        UniqueConstraint("response_id", name="uq_response_ledger_response_id"),
        CheckConstraint("delivery IN ('shadow', 'delivered', 'legacy')", name="ck_response_ledger_delivery"),
        CheckConstraint("decision IN ('answer', 'abstain')", name="ck_response_ledger_decision"),
        Index("ix_response_ledger_shadowed_response_id", "shadowed_response_id"),
        Index("ix_response_ledger_created_at", "created_at"),
    )

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    response_id: Mapped[str] = mapped_column(String(64))
    delivery: Mapped[str] = mapped_column(String(16))
    decision: Mapped[str] = mapped_column(String(16))
    shadowed_response_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claim_set_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_schema: Mapped[str] = mapped_column(String(32))
    # The canonical JSON of the LedgerEntry: exactly the bytes entry_sha256 hashes (TEXT, so no driver re-encodes it).
    entry: Mapped[str] = mapped_column(Text)
    entry_sha256: Mapped[str] = mapped_column(String(64))
    prev_hash: Mapped[str] = mapped_column(String(64))
    record_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ResponseLedgerHead(Base):
    # The chain head, locked with SELECT ... FOR UPDATE by every append so the chain stays linear, and compared with
    # the last record so a truncated tail is detected. A trigger lets it move forward only, one record at a time.
    __tablename__ = "response_ledger_head"

    chain: Mapped[str] = mapped_column(String(32), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer)
    record_hash: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # When the chain began (informational): written by the first append, never changed by the trigger's rules. It
    # decides nothing about coverage: start-up writes no head, and whether a turn without a record is a lost record is
    # the turn's own ledger_record_expected (ledger.ledger_started_at). Null only on a head written before the column
    # existed (a development database).
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
