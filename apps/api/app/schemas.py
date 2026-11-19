from datetime import datetime
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_serializer


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SourceAsset(BaseModel):
    id: str
    title: str
    kind: str
    filename: str
    size_bytes: int | None = None
    download_url: str | None = None
    description: str | None = None


class Citation(BaseModel):
    chunk_id: str
    span_id: str | None = None
    corpus_version: str | None = None
    content_hash: str | None = None
    source_title: str
    source_kind: str
    section_title: str
    excerpt: str
    timestamp_label: str | None = None
    source_filename: str | None = None
    # AC-1-13: every citation is provisional until the provisional marker is lifted for resolved citations (plan
    # Phase 2 G), which CITATION_PROVISIONAL_LIFT_ENABLED gates (off by default; services/provenance.py).
    provisional: bool = True
    # Citation v2 (Phase 2 spec 2.3). The schema is read from citation_schema, never from the id form: v1 and v2
    # span ids share the span-<64 hex> shape. A v0 or v1 dict reads back as legacy_unresolved and provisional.
    # For v2, content_hash is the sha256 of the FULL span text (v1 hashed the displayed excerpt).
    citation_schema: int = 1
    item_id: str | None = None
    item_version: str | None = None
    start: int | None = None
    end: int | None = None
    resolution: Literal["resolved", "legacy_unresolved"] = "legacy_unresolved"
    migration_status: Literal["native", "migrated", "legacy_unresolved"] | None = None
    # excerpt_no_match | excerpt_ambiguous | chapter_summary_excluded | missing_excerpt | invalid_shape |
    # not_resolvable_on_read
    unresolved_reason: str | None = None
    legacy_chunk_id: str | None = None
    legacy_span_id: str | None = None
    near_floor: bool = False
    # "unverified historical reference" on every legacy_unresolved citation (plan 11.2).
    label: str | None = None


class SpanResolution(BaseModel):
    """GET /spans/{span_id} (task 2.4): span metadata; the excerpt only for a servable span, which D-31 makes none."""

    span_id: str
    scheme: str
    item_id: str
    item_version: str
    kind: str
    plane: str
    section_ordinal: int
    start: int
    end: int
    content_hash: str
    servable: bool
    current: bool
    registered: bool
    corpus_version_first_seen: str | None = None
    corpus_version: str
    excerpt: str | None = None
    # Phase 3 (plan 7.3 "public license_class only"): a resolvable span is public-plane, so its class is public.
    license_class: Literal["public"] = "public"


class VideoChapter(BaseModel):
    id: str
    title: str
    timestamp_start: int
    timestamp_end: int
    summary: str
    transcript_excerpt: str | None = None
    transcript_status: str = "chapter_summary_only"


class LessonSection(BaseModel):
    id: str
    source_title: str
    heading: str
    summary: str
    excerpt: str
    topics: list[str] = Field(default_factory=list)


class RelatedLessonSummary(BaseModel):
    slug: str
    title: str
    summary: str
    module_slug: str
    reason: str


class Flashcard(BaseModel):
    id: str
    difficulty: str
    prompt: str
    answer: str
    card_type: str


class QuizQuestion(BaseModel):
    id: str
    question_type: str
    prompt: str
    choices: list[str] = Field(default_factory=list)
    answer: str
    explanation: str
    difficulty: str


class LessonDetail(BaseModel):
    slug: str
    module_slug: str
    title: str
    summary: str
    key_ideas: list[str]
    key_notes: list[str]
    formulas: list[str]
    learner_questions: list[str]
    sections: list[LessonSection]
    source_assets: list[SourceAsset]
    video_asset: SourceAsset | None = None
    chapters: list[VideoChapter] = Field(default_factory=list)
    flashcards: list[Flashcard] = Field(default_factory=list)
    quiz_questions: list[QuizQuestion] = Field(default_factory=list)
    related_lessons: list[RelatedLessonSummary] = Field(default_factory=list)


class ModuleSummary(BaseModel):
    slug: str
    title: str
    summary: str
    learning_goals: list[str]
    lesson_slugs: list[str]
    source_highlights: list[str]


class CourseOverview(BaseModel):
    id: str
    title: str
    summary: str
    modules: list[ModuleSummary]
    source_assets: list[SourceAsset]


class SearchResult(BaseModel):
    chunk_id: str
    title: str
    source_kind: str
    source_title: str
    excerpt: str
    lesson_slug: str | None = None
    score: float
    timestamp_label: str | None = None
    source_filename: str | None = None
    # Phase 2 (spec 2.4): chunk_id equals span_id; lesson_slugs lists every lesson the span is bound to.
    span_id: str | None = None
    item_id: str | None = None
    item_version: str | None = None
    start: int | None = None
    end: int | None = None
    content_hash: str | None = None
    lesson_slugs: list[str] = Field(default_factory=list)
    # Within the abstention margin above the floor (bm25f-v1 only): the later X4 trigger.
    near_floor: bool = False


class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    # Bounded like their columns (notes.anchor_type String(50), anchor_value String(255)). A constrained field also
    # refuses a lone surrogate with 422 instead of letting it reach the database driver (Release R1.1).
    anchor_type: str | None = Field(default=None, max_length=50)
    anchor_value: str | None = Field(default=None, max_length=255)


class NoteRead(BaseModel):
    id: int
    body: str
    lesson_slug: str
    anchor_type: str | None = None
    anchor_value: str | None = None
    created_at: datetime


class QARequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    lesson_slug: str | None = Field(default=None, max_length=255)
    top_k: int = Field(default=4, ge=1, le=12)


class QAResponse(BaseModel):
    answer: str
    citations: list[Citation]
    retrieval_mode: str
    decision: Literal["answer", "abstain"] = "answer"
    grounded: bool = False


class QAHistoryItem(BaseModel):
    id: int
    lesson_slug: str | None = None
    question: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    created_at: datetime
    # True when the stored answer predates containment and is withheld (R-16; app/services/answer_history.py).
    withdrawn: bool = False


ASSISTANT_HISTORY_MAX_MESSAGES = 8
ASSISTANT_HISTORY_MESSAGE_MAX_LENGTH = 4000


class AssistantChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message content cannot be empty.")
        return normalized[:ASSISTANT_HISTORY_MESSAGE_MAX_LENGTH]


class AssistantChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = Field(default=None, min_length=8, max_length=64)
    lesson_slug: str | None = Field(default=None, max_length=255)
    page_path: str | None = Field(default=None, max_length=255)
    history: list[AssistantChatMessage] = Field(default_factory=list)
    top_k: int = Field(default=4, ge=1, le=8)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message cannot be empty.")
        return normalized

    @field_validator("page_path")
    @classmethod
    def validate_page_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if not normalized.startswith("/"):
            raise ValueError("Page path must start with '/'.")
        return normalized[:255]

    @field_validator("history")
    @classmethod
    def validate_history(cls, value: list[AssistantChatMessage]) -> list[AssistantChatMessage]:
        return value[-ASSISTANT_HISTORY_MAX_MESSAGES:]


class EvidenceSpanLink(BaseModel):
    span_id: str
    label: str
    # True when GET /evidence/spans/{span_id} is enabled (SPAN_RESOLVER_ROUTE_ENABLED); otherwise a plain label.
    resolvable: bool


class EvidencePanel(BaseModel):
    """The evidence panel of a tutor answer (plan task 3.8): labels only, for the contained answer the learner
    already receives. Never "grounded"; never anything from the two-pass shadow."""

    panel_schema: Literal["evidence-panel-v1"] = "evidence-panel-v1"
    decision: Literal["answer", "abstain"]
    labels: list[Literal["lexically_screened"]] = Field(default_factory=list)
    degraded: list[Literal["extractive_only", "retrieval_fallback", "citations_provisional"]] = Field(default_factory=list)
    spans: list[EvidenceSpanLink] = Field(default_factory=list)
    verdict: Literal["no-verdict"] = "no-verdict"


class AssistantChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    retrieval_mode: str
    provider: str
    model: str
    grounded: bool = True
    thread_id: str | None = None
    turn_id: str | None = None
    decision: Literal["answer", "abstain", "clarify"] = "answer"
    decision_reason: str | None = None
    claims: list["GroundedClaim"] = Field(default_factory=list)
    # Phase 3 (task 3.8): present only when EVIDENCE_PANEL_ENABLED (development by default). When absent the key is
    # omitted, so production bodies keep today's keys and values (spec conflict 28).
    evidence: EvidencePanel | None = None
    # Never serialised: the turn's ledger and shadow follow-ups, and the retrieval behind a contained answer.
    _followups: Any = PrivateAttr(default=None)
    _retrieval: Any = PrivateAttr(default=None)

    @model_serializer(mode="wrap")
    def _omit_absent_evidence(self, handler) -> dict[str, Any]:
        data = handler(self)
        if isinstance(data, dict) and self.evidence is None:
            data.pop("evidence", None)
        return data


class TutorTurnRequest(BaseModel):
    """POST /tutor/turns (plan 7.3). No learner-state field is accepted (AC-3-1 at the API boundary)."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = Field(default=None, min_length=8, max_length=64)
    lesson_slug: str | None = Field(default=None, max_length=255)
    # A presentation hint for the two-pass renderer only; it never reaches retrieval or the evidential pass.
    presentation_plan: Literal["concise", "stepwise", "socratic"] | None = None

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message cannot be empty.")
        return normalized


class TutorTurnResponse(AssistantChatResponse):
    # Phase 3 delivers the legacy contained answer only; Phase 4 adds "delivered" behind V1 (AC-3-6).
    delivery: Literal["legacy"] = "legacy"


class LedgerClaimRead(BaseModel):
    claim_id: str
    text: str
    span_ids: list[str]


class LedgerRecordRead(BaseModel):
    response_id: str
    delivery: str
    decision: str
    abstention_reason: str | None = None
    created_at: datetime
    claim_set_hash: str | None = None
    span_ids: list[str] = Field(default_factory=list)
    claims: list[LedgerClaimRead] = Field(default_factory=list)
    retrieval: dict[str, Any] = Field(default_factory=dict)
    presentation: dict[str, Any] | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    versions: dict[str, Any] = Field(default_factory=dict)
    resolved_question: dict[str, Any] | None = None
    # Reviewers only (None for owners, so a learner never learns chain position or traffic volume).
    seq: int | None = None
    prev_hash: str | None = None
    record_hash: str | None = None
    entry_sha256: str | None = None
    shadowed_response_id: str | None = None


class LedgerResponseRead(BaseModel):
    response_id: str
    # Plan Phase 3 G: "legacy turns marked no-verdict"; no V1-V3 verdict exists before Phase 4.
    verdict: Literal["no-verdict"] = "no-verdict"
    recorded: bool
    legacy_turn: bool
    record: LedgerRecordRead | None = None


class GroundedClaim(BaseModel):
    text: str
    cited_span_ids: list[str] = Field(default_factory=list)
    supported: bool


class TutorThreadCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class TutorThreadRead(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class TutorMessageRead(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    # True when a stored tutor reply predates containment and is withheld (R-16).
    withdrawn: bool = False


class TutorThreadDetail(TutorThreadRead):
    messages: list[TutorMessageRead] = Field(default_factory=list)


class LearnerRecordOperationInput(BaseModel):
    operation_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    replica_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    logical_counter: int = Field(ge=1, le=2_000_000_000)
    causal_vector: dict[str, int] = Field(default_factory=dict)
    operation_type: Literal["mastery_set", "complete_item", "increment_attempt", "set_cursor", "set_preference"]
    payload: dict = Field(default_factory=dict)

    @field_validator("causal_vector")
    @classmethod
    def validate_causal_vector(cls, value: dict[str, int]) -> dict[str, int]:
        if len(value) > 128:
            raise ValueError("Causal vector is too large.")
        if any(not key or len(key) > 128 or not isinstance(counter, int) or counter < 0 for key, counter in value.items()):
            raise ValueError("Causal vectors require non-negative replica counters.")
        return value


class LearnerRecordOperationsRequest(BaseModel):
    operations: list[LearnerRecordOperationInput] = Field(min_length=1, max_length=100)


class LearnerRecordOperationReceipt(BaseModel):
    operation_id: str
    status: Literal["applied", "duplicate"]


class LearnerRecordRead(BaseModel):
    user_id: str
    record_version: int
    mastery: dict[str, float] = Field(default_factory=dict)
    completed_item_ids: list[str] = Field(default_factory=list)
    attempt_counts: dict[str, int] = Field(default_factory=dict)
    cursor: str | None = None
    preferences: dict = Field(default_factory=dict)
    version_vector: dict[str, int] = Field(default_factory=dict)


class LearnerRecordOperationsResponse(BaseModel):
    receipts: list[LearnerRecordOperationReceipt]
    record: LearnerRecordRead


class AnalyticsEventCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=100)
    lesson_slug: str | None = Field(default=None, max_length=255)
    payload: dict = Field(default_factory=dict)


class PublicWebVitalCreate(BaseModel):
    metric_id: str = Field(min_length=1, max_length=255)
    metric_name: str = Field(min_length=1, max_length=32)
    path: str = Field(min_length=1, max_length=255)
    value: float = Field(ge=0)
    delta: float | None = Field(default=None, ge=0)
    rating: str = Field(min_length=1, max_length=32)
    navigation_type: str | None = Field(default=None, max_length=64)
    connection_type: str | None = Field(default=None, max_length=64)

    @field_validator("metric_name")
    @classmethod
    def validate_metric_name(cls, value: str) -> str:
        normalized = value.strip().upper()
        allowed = {"CLS", "FCP", "FID", "INP", "LCP", "TTFB"}
        if normalized not in allowed:
            raise ValueError("Unsupported web-vitals metric.")
        return normalized

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("/"):
            raise ValueError("Path must start with '/'.")
        return normalized

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"good", "needs-improvement", "poor"}:
            raise ValueError("Unsupported web-vitals rating.")
        return normalized


class PublicWebVitalSummaryItem(BaseModel):
    metric_name: str
    sample_count: int
    average_value: float
    p75_value: float
    good_rate_percent: float


class PublicWebVitalSummaryRead(BaseModel):
    status: str
    total_samples: int
    monitored_paths: list[str] = Field(default_factory=list)
    last_sample_at: datetime | None = None
    metrics: list[PublicWebVitalSummaryItem] = Field(default_factory=list)


class PublicWebVitalReceipt(BaseModel):
    status: str


class SupportRequestCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    organization: str | None = Field(default=None, max_length=255)
    request_type: str = Field(min_length=1, max_length=64)
    page_url: str | None = Field(default=None, max_length=512)
    message: str = Field(min_length=20, max_length=4000)
    website: str | None = Field(default=None, max_length=255)

    @field_validator("email")
    @classmethod
    def validate_support_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("Enter a valid email address.")
        return normalized

    @field_validator("name", "request_type")
    @classmethod
    def validate_trimmed_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("This field cannot be empty.")
        return normalized

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 20:
            raise ValueError("Message must be at least 20 characters.")
        return normalized

    @field_validator("organization", "page_url", "website")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SupportRequestRead(BaseModel):
    status: str
    ticket_id: str
    request_type: str
    response_target: str
    created_at: datetime


class QuizAttemptCreate(BaseModel):
    # No score: the server scores `responses` against the lesson's answer key (task 1.2). A client that
    # still sends one has it ignored.
    lesson_slug: str = Field(max_length=200)
    responses: dict[str, Any] = Field(default_factory=dict, max_length=100)


class UserProfile(BaseModel):
    user_id: str
    email: str | None
    role: str
    auth_provider: str = "guest"
    can_delete_account: bool = False


class LocalAccountRegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("Enter a valid email address.")
        return normalized


class LocalAccountLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("Enter a valid email address.")
        return normalized


class LocalAccountDeleteRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class AuthSessionRead(BaseModel):
    status: str
    user: UserProfile


class AuthActionRead(BaseModel):
    status: str


class GuestUpgradeRequest(BaseModel):
    legacy_guest_id: str = Field(max_length=80)
    legacy_csrf: str = Field(max_length=160)


class GuestUpgradeRead(BaseModel):
    upgraded: bool
    guest_token: str | None = None
    csrf: str | None = None


class GuestRevocationCreate(BaseModel):
    guest_id: str = Field(pattern=r"^guest-[0-9a-f-]{8,64}$")
    reason: str = Field(min_length=3, max_length=255)


class GuestRevocationRead(BaseModel):
    status: str
    revoked_at: datetime


class QuizAttemptRead(BaseModel):
    id: int
    lesson_slug: str
    score: int
    created_at: datetime


class LessonProgress(BaseModel):
    lesson_slug: str
    lesson_title: str
    module_slug: str
    status: str
    visited: bool
    note_count: int
    quiz_attempts: int
    qa_questions: int
    analytics_events: int
    best_score: int | None = None
    best_score_percent: float | None = None


class ModuleProgress(BaseModel):
    module_slug: str
    module_title: str
    status: str
    total_lessons: int
    visited_lessons: int
    completed_lessons: int
    progress_percent: int
    average_score_percent: float | None = None


class CourseProgress(BaseModel):
    user_id: str
    total_lessons: int
    visited_lessons: int
    completed_lessons: int
    progress_percent: int
    modules: list[ModuleProgress]
    lessons: list[LessonProgress]
    recent_notes: list[NoteRead]
    recent_quiz_attempts: list[QuizAttemptRead]


class ArenaStanding(BaseModel):
    display_name: str
    xp: int
    matches_played: int
    wins: int
    skill_rating: int
    adaptive_level: int
    win_rate_percent: float
    rank_label: str


class ArenaLeaderboardEntry(ArenaStanding):
    public_handle: str


class ArenaProfileRead(ArenaStanding):
    public_handle: str
    recent_form: str


class ArenaTicketRead(BaseModel):
    ticket: str
    protocol: str
    expires_in: int


class BuilderNode(BaseModel):
    id: str
    label: str
    description: str
    color: str


class BuilderSlot(BaseModel):
    id: str
    label: str
    description: str
    x: int
    y: int


class BuilderConnection(BaseModel):
    from_slot: str
    to_slot: str


class BuilderScenario(BaseModel):
    slug: str
    title: str
    domain: str
    summary: str
    unlock_order: int
    points_reward: int
    nodes: list[BuilderNode]
    slots: list[BuilderSlot]
    connections: list[BuilderConnection]
    unlocked: bool = False
    completed: bool = False
    best_completion_percent: int = 0


class BuilderProfile(BaseModel):
    user_id: str
    total_points: int
    current_streak: int
    completion_percent: int
    completed_scenarios: int
    unlocked_scenarios: int
    badges: list[str]
    next_challenge_slug: str | None = None


class BuilderFeedItem(BaseModel):
    id: int
    public_handle: str
    scenario_slug: str
    scenario_title: str
    caption: str
    completion_percent: int
    created_at: datetime


class BuilderSubmissionCreate(BaseModel):
    scenario_slug: str
    placements: dict[str, str] = Field(default_factory=dict)


class BuilderSubmissionResult(BaseModel):
    scenario_slug: str
    completion_percent: int
    correct_slots: int
    total_slots: int
    points_earned: int
    unlocked_next_slug: str | None = None
    completed: bool
    incorrect_slots: list[str] = Field(default_factory=list)
    current_streak: int
    badges: list[str]


class BuilderShareCreate(BaseModel):
    scenario_slug: str
    caption: str = Field(min_length=1, max_length=280)
    placements: dict[str, str] = Field(default_factory=dict)


class LearnerProfileRead(BaseModel):
    user_id: str
    target_role: str
    weekly_goal_hours: int
    preferred_pace: str
    focus_area: str | None = None
    self_ratings: dict[str, int] = Field(default_factory=dict)


class LearnerProfileUpdate(BaseModel):
    target_role: str = Field(min_length=1, max_length=255)
    weekly_goal_hours: int = Field(default=4, ge=1, le=40)
    preferred_pace: str = Field(default="balanced", min_length=1, max_length=50)
    focus_area: str | None = Field(default=None, max_length=255)
    self_ratings: dict[str, int] = Field(default_factory=dict)


class LearningPulseCreate(BaseModel):
    motivation_level: int = Field(ge=1, le=5)
    focus_level: int = Field(ge=1, le=5)
    energy_level: int = Field(ge=1, le=5)
    session_minutes: int = Field(default=25, ge=10, le=240)
    today_goal: str | None = Field(default=None, max_length=280)
    blocker: str | None = Field(default=None, max_length=280)


class LearningPulseRead(BaseModel):
    id: int
    motivation_level: int
    focus_level: int
    energy_level: int
    session_minutes: int
    today_goal: str | None = None
    blocker: str | None = None
    created_at: datetime


class ActivityPoint(BaseModel):
    label: str
    date: str
    events: int
    focus_level: float | None = None
    motivation_level: float | None = None


class HeatmapPoint(BaseModel):
    date: str
    events: int
    intensity: int
    goal_minutes: int | None = None


class DashboardMetrics(BaseModel):
    progress_percent: int
    motivation_score: int
    focus_score: int
    momentum_score: int
    consistency_score: int
    active_streak_days: int
    weekly_goal_hours: int
    weekly_goal_progress_percent: int
    completed_lessons: int
    projects_submitted: int
    peer_reviews_completed: int


class ModuleInsight(BaseModel):
    module_slug: str
    module_title: str
    mastery_percent: int
    confidence_label: str
    risk_flag: str | None = None
    recommendation: str


class RecommendationCard(BaseModel):
    title: str
    summary: str
    href: str
    recommendation_type: str
    reason: str
    urgency: str


class AdaptivePathStep(BaseModel):
    step_number: int
    title: str
    summary: str
    href: str
    recommendation_type: str
    estimated_minutes: int
    intensity: str
    reason: str


class AdaptivePathRead(BaseModel):
    target_role: str
    pace_mode: str
    adaptation_summary: str
    steps: list[AdaptivePathStep]


class SkillGapItem(BaseModel):
    skill_id: str
    label: str
    current_level: float
    target_level: float
    gap: float
    evidence: str
    recommended_actions: list[str] = Field(default_factory=list)


class SkillGapReportRead(BaseModel):
    target_role: str
    role_summary: str
    readiness_percent: int
    strengths: list[str] = Field(default_factory=list)
    gaps: list[SkillGapItem]
    recommendations: list[RecommendationCard]


class RealtimeFeedbackRequest(BaseModel):
    context_type: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=8000)
    lesson_slug: str | None = None
    project_slug: str | None = None
    score: int | None = Field(default=None, ge=0, le=100)


class RealtimeFeedbackResponse(BaseModel):
    summary: str
    signal: str
    confidence_label: str
    recommended_actions: list[str] = Field(default_factory=list)
    suggested_resources: list[RecommendationCard] = Field(default_factory=list)


class LearningDashboardRead(BaseModel):
    profile: LearnerProfileRead
    metrics: DashboardMetrics
    activity: list[ActivityPoint]
    heatmap: list[HeatmapPoint] = Field(default_factory=list)
    pulses: list[LearningPulseRead]
    module_insights: list[ModuleInsight]
    recommendations: list[RecommendationCard]
    coach_feedback: RealtimeFeedbackResponse


class ArenaStatusRead(BaseModel):
    enabled: bool
    queue_size: int
    active_matches: int
    connected_players: int


class ProjectRubricCriterion(BaseModel):
    id: str
    label: str
    description: str


class ProjectBrief(BaseModel):
    slug: str
    title: str
    summary: str
    difficulty: str
    estimated_hours: int
    deliverable: str
    linked_lessons: list[str] = Field(default_factory=list)
    rubric: list[ProjectRubricCriterion] = Field(default_factory=list)
    submitted_count: int = 0
    peer_reviews_received: int = 0


class ProjectSubmissionCreate(BaseModel):
    project_slug: str
    title: str = Field(min_length=1, max_length=255)
    solution_summary: str = Field(min_length=80, max_length=8000)
    implementation_notes: str = Field(min_length=40, max_length=8000)
    confidence_level: int = Field(default=3, ge=1, le=5)


class ProjectSubmissionRead(BaseModel):
    id: int
    project_slug: str
    project_title: str
    title: str
    solution_summary: str
    implementation_notes: str
    confidence_level: int
    status: str
    ai_feedback_summary: str | None = None
    ai_recommendations: list[str] = Field(default_factory=list)
    average_peer_score: float | None = None
    review_count: int = 0
    created_at: datetime


class ReviewQueueItem(BaseModel):
    submission_id: int
    project_slug: str
    project_title: str
    title: str
    author_handle: str
    solution_summary: str
    implementation_notes: str
    rubric: list[ProjectRubricCriterion] = Field(default_factory=list)


class PeerReviewCreate(BaseModel):
    submission_id: int = Field(ge=1, le=2_147_483_647)  # project_submissions.id is a 32-bit INTEGER
    rubric_scores: dict[str, int] = Field(default_factory=dict)
    feedback: str = Field(min_length=20, max_length=4000)


class PeerReviewRead(BaseModel):
    id: int
    submission_id: int
    reviewer_user_id: str
    overall_score: float
    feedback: str
    created_at: datetime
