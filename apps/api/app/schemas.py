from datetime import datetime

from pydantic import BaseModel, Field


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
    source_title: str
    source_kind: str
    section_title: str
    excerpt: str
    timestamp_label: str | None = None


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


class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    anchor_type: str | None = None
    anchor_value: str | None = None


class NoteRead(BaseModel):
    id: int
    body: str
    lesson_slug: str
    anchor_type: str | None = None
    anchor_value: str | None = None
    created_at: datetime


class QARequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    lesson_slug: str | None = None
    top_k: int = Field(default=4, ge=1, le=12)


class QAResponse(BaseModel):
    answer: str
    citations: list[Citation]
    retrieval_mode: str


class AnalyticsEventCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=100)
    lesson_slug: str | None = None
    payload: dict = Field(default_factory=dict)


class QuizAttemptCreate(BaseModel):
    lesson_slug: str
    score: int = Field(ge=0)
    responses: dict = Field(default_factory=dict)


class UserProfile(BaseModel):
    user_id: str
    email: str | None
    role: str


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


class ArenaLeaderboardEntry(BaseModel):
    player_id: str
    display_name: str
    xp: int
    matches_played: int
    wins: int
    skill_rating: int
    adaptive_level: int
    win_rate_percent: float
    rank_label: str


class ArenaProfileRead(ArenaLeaderboardEntry):
    recent_form: str


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
    user_id: str
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
