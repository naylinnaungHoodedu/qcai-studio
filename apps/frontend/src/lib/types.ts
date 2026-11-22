export type SourceAsset = {
  id: string;
  title: string;
  kind: string;
  filename: string;
  size_bytes?: number | null;
  download_url?: string | null;
  description?: string | null;
};

export type ModuleSummary = {
  slug: string;
  title: string;
  summary: string;
  learning_goals: string[];
  lesson_slugs: string[];
  source_highlights: string[];
};

export type CourseOverview = {
  id: string;
  title: string;
  summary: string;
  modules: ModuleSummary[];
  source_assets: SourceAsset[];
};

export type LessonSection = {
  id: string;
  source_title: string;
  heading: string;
  summary: string;
  excerpt: string;
  topics: string[];
};

export type RelatedLesson = {
  slug: string;
  title: string;
  summary: string;
  module_slug: string;
  reason: string;
};

export type VideoChapter = {
  id: string;
  title: string;
  timestamp_start: number;
  timestamp_end: number;
  summary: string;
  transcript_excerpt?: string | null;
  transcript_status: string;
};

export type Flashcard = {
  id: string;
  difficulty: string;
  prompt: string;
  answer: string;
  card_type: string;
};

// A public quiz question carries no answer key and no explanation (plan Phase 4 B; R-42): the model answer and rubric
// come only from a saved attempt's feedback (QuizAttemptResult.feedback).
export type QuizQuestion = {
  id: string;
  question_type: string;
  prompt: string;
  choices: string[];
  difficulty: string;
};

export type QuizFeedback = {
  question_id: string;
  answered: boolean;
  correct: boolean | null;
  answer: string | null;
  explanation: string | null;
};

export type LessonDetail = {
  slug: string;
  module_slug: string;
  title: string;
  summary: string;
  key_ideas: string[];
  key_notes: string[];
  formulas: string[];
  learner_questions: string[];
  sections: LessonSection[];
  source_assets: SourceAsset[];
  video_asset?: SourceAsset | null;
  chapters: VideoChapter[];
  flashcards: Flashcard[];
  quiz_questions: QuizQuestion[];
  related_lessons: RelatedLesson[];
};

export type SearchResult = {
  chunk_id: string;
  title: string;
  source_kind: string;
  source_title: string;
  excerpt: string;
  lesson_slug?: string | null;
  score: number;
  timestamp_label?: string | null;
};

export type Note = {
  id: number;
  body: string;
  lesson_slug: string;
  anchor_type?: string | null;
  anchor_value?: string | null;
  created_at: string;
};

export type QAResponse = {
  answer: string;
  citations: Array<{
    chunk_id: string;
    span_id?: string | null;
    corpus_version?: string | null;
    content_hash?: string | null;
    source_title: string;
    source_kind: string;
    section_title: string;
    excerpt: string;
    timestamp_label?: string | null;
    source_filename?: string | null;
    provisional?: boolean;
  }>;
  retrieval_mode: string;
  // Phase 3 (task 3.8; E-46 names the Q&A citation cards): sent only when EVIDENCE_PANEL_ENABLED (development).
  evidence?: EvidencePanelPayload | null;
};

export type QAHistoryItem = {
  id: number;
  lesson_slug?: string | null;
  question: string;
  answer: string;
  citations: Array<{
    chunk_id: string;
    span_id?: string | null;
    corpus_version?: string | null;
    content_hash?: string | null;
    source_title: string;
    source_kind: string;
    section_title: string;
    excerpt: string;
    timestamp_label?: string | null;
    source_filename?: string | null;
    provisional?: boolean;
  }>;
  created_at: string;
  // The stored answer predates containment and is withheld (R-16).
  withdrawn?: boolean;
  // Phase 4 (V1.7, AC-4-6): present only when the stored answer's quoted passages disagree.
  conflicts?: EvidenceConflictPayload[] | null;
};

export type AssistantChatMessage = {
  role: "user" | "assistant";
  content: string;
};

export type AssistantChatResponse = {
  answer: string;
  citations: Array<{
    chunk_id: string;
    span_id?: string | null;
    corpus_version?: string | null;
    content_hash?: string | null;
    source_title: string;
    source_kind: string;
    section_title: string;
    excerpt: string;
    timestamp_label?: string | null;
    source_filename?: string | null;
    provisional?: boolean;
  }>;
  retrieval_mode: string;
  provider: string;
  model: string;
  grounded: boolean;
  thread_id?: string | null;
  turn_id?: string | null;
  decision?: "answer" | "abstain" | "clarify";
  decision_reason?: string | null;
  claims?: Array<{
    text: string;
    cited_span_ids: string[];
    supported: boolean;
  }>;
  // Phase 3 (task 3.8): present only when the API enables the evidence panel (development by default).
  evidence?: EvidencePanelPayload | null;
};

// The evidence panel of a contained tutor answer: labels only, never a "verified" claim (plan Phase 3 task 3.8).
export type EvidencePanelPayload = {
  panel_schema: "evidence-panel-v1";
  decision: "answer" | "abstain";
  labels: Array<"lexically_screened">;
  degraded: Array<"extractive_only" | "retrieval_fallback" | "citations_provisional">;
  spans: Array<{ span_id: string; label: string; resolvable: boolean }>;
  verdict: "no-verdict";
  // Phase 4 (V1.7): present only when quoted passages disagree; passages are 1-based positions in spans.
  conflicts?: EvidenceConflictPayload[] | null;
};

// Phase 4 (V1.7): two quoted passages of one answer that may disagree; passages are the answer's 1-based quotation
// positions ([1], [2], ... in its text, and the panel's spans).
export type EvidenceConflictPayload = {
  kind: "version_of_same_asset" | "number_disagreement" | "negation_disagreement";
  passages: number[];
};

export type TutorThread = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type TutorThreadDetail = TutorThread & {
  messages: Array<{
    id: string;
    role: "user" | "assistant";
    content: string;
    created_at: string;
    // A stored tutor reply that predates containment is withheld (R-16).
    withdrawn?: boolean;
    // Phase 4 (V1.7, AC-4-6): present only on a stored reply whose quoted passages disagree.
    conflicts?: EvidenceConflictPayload[] | null;
  }>;
};

export type LearnerRecord = {
  user_id: string;
  record_version: number;
  mastery: Record<string, number>;
  completed_item_ids: string[];
  attempt_counts: Record<string, number>;
  cursor?: string | null;
  preferences: Record<string, unknown>;
  version_vector: Record<string, number>;
};

export type LearnerRecordOperation = {
  operation_id: string;
  replica_id: string;
  logical_counter: number;
  causal_vector: Record<string, number>;
  operation_type: "mastery_set" | "complete_item" | "increment_attempt" | "set_cursor" | "set_preference";
  payload: Record<string, unknown>;
};

export type QuizAttemptResult = {
  status: string;
  attempt_id: number;
  score: number;
  // Absent from an API older than Phase 4.
  feedback?: QuizFeedback[];
};

export type QuizAttemptSummary = {
  id: number;
  lesson_slug: string;
  score: number;
  created_at: string;
};

export type ModuleDetail = {
  module: ModuleSummary;
  lessons: LessonDetail[];
};

export type UserProfile = {
  user_id: string;
  email?: string | null;
  role: string;
  auth_provider?: string;
  can_delete_account?: boolean;
};

export type AuthSession = {
  status: string;
  user: UserProfile;
};

export type AuthAction = {
  status: string;
};

export type SupportRequestReceipt = {
  status: string;
  ticket_id: string;
  request_type: string;
  response_target: string;
  created_at: string;
};

export type PublicWebVitalSummaryItem = {
  metric_name: string;
  sample_count: number;
  average_value: number;
  p75_value: number;
  good_rate_percent: number;
};

export type PublicWebVitalSummary = {
  status: string;
  total_samples: number;
  monitored_paths: string[];
  last_sample_at?: string | null;
  metrics: PublicWebVitalSummaryItem[];
};

export type LessonProgress = {
  lesson_slug: string;
  lesson_title: string;
  module_slug: string;
  status: string;
  visited: boolean;
  note_count: number;
  quiz_attempts: number;
  qa_questions: number;
  analytics_events: number;
  best_score?: number | null;
  best_score_percent?: number | null;
};

export type ModuleProgress = {
  module_slug: string;
  module_title: string;
  status: string;
  total_lessons: number;
  visited_lessons: number;
  completed_lessons: number;
  progress_percent: number;
  average_score_percent?: number | null;
};

export type CourseProgress = {
  user_id: string;
  total_lessons: number;
  visited_lessons: number;
  completed_lessons: number;
  progress_percent: number;
  modules: ModuleProgress[];
  lessons: LessonProgress[];
  recent_notes: Note[];
  recent_quiz_attempts: QuizAttemptSummary[];
};

export type ArenaLeaderboardEntry = {
  public_handle: string;
  display_name: string;
  xp: number;
  matches_played: number;
  wins: number;
  skill_rating: number;
  adaptive_level: number;
  win_rate_percent: number;
  rank_label: string;
};

export type ArenaProfile = ArenaLeaderboardEntry & {
  recent_form: string;
};

// A short-lived, single-use credential for the Arena socket, offered as a WebSocket subprotocol.
export type ArenaTicket = {
  ticket: string;
  protocol: string;
  expires_in: number;
};

export type ArenaStatus = {
  enabled?: boolean;
  queue_size: number;
  active_matches: number;
  connected_players: number;
};

export type BuilderNode = {
  id: string;
  label: string;
  description: string;
  color: string;
};

export type BuilderSlot = {
  id: string;
  label: string;
  description: string;
  x: number;
  y: number;
};

export type BuilderConnection = {
  from_slot: string;
  to_slot: string;
};

export type BuilderScenario = {
  slug: string;
  title: string;
  domain: string;
  summary: string;
  unlock_order: number;
  points_reward: number;
  nodes: BuilderNode[];
  slots: BuilderSlot[];
  connections: BuilderConnection[];
  unlocked: boolean;
  completed: boolean;
  best_completion_percent: number;
};

export type BuilderProfile = {
  user_id: string;
  total_points: number;
  current_streak: number;
  completion_percent: number;
  completed_scenarios: number;
  unlocked_scenarios: number;
  badges: string[];
  next_challenge_slug?: string | null;
};

export type BuilderFeedItem = {
  id: number;
  public_handle: string;
  scenario_slug: string;
  scenario_title: string;
  caption: string;
  completion_percent: number;
  created_at: string;
};

export type BuilderSubmissionResult = {
  scenario_slug: string;
  completion_percent: number;
  correct_slots: number;
  total_slots: number;
  points_earned: number;
  unlocked_next_slug?: string | null;
  completed: boolean;
  incorrect_slots: string[];
  current_streak: number;
  badges: string[];
};

export type LearnerProfile = {
  user_id: string;
  target_role: string;
  weekly_goal_hours: number;
  preferred_pace: string;
  focus_area?: string | null;
  self_ratings: Record<string, number>;
};

export type LearningPulse = {
  id: number;
  motivation_level: number;
  focus_level: number;
  energy_level: number;
  session_minutes: number;
  today_goal?: string | null;
  blocker?: string | null;
  created_at: string;
};

export type ActivityPoint = {
  label: string;
  date: string;
  events: number;
  focus_level?: number | null;
  motivation_level?: number | null;
};

export type HeatmapPoint = {
  date: string;
  events: number;
  intensity: number;
  goal_minutes?: number | null;
};

export type DashboardMetrics = {
  progress_percent: number;
  motivation_score: number;
  focus_score: number;
  momentum_score: number;
  consistency_score: number;
  active_streak_days: number;
  weekly_goal_hours: number;
  weekly_goal_progress_percent: number;
  completed_lessons: number;
  projects_submitted: number;
  peer_reviews_completed: number;
};

export type ModuleInsight = {
  module_slug: string;
  module_title: string;
  mastery_percent: number;
  confidence_label: string;
  risk_flag?: string | null;
  recommendation: string;
};

export type RecommendationCard = {
  title: string;
  summary: string;
  href: string;
  recommendation_type: string;
  reason: string;
  urgency: string;
};

export type RealtimeFeedback = {
  summary: string;
  signal: string;
  confidence_label: string;
  recommended_actions: string[];
  suggested_resources: RecommendationCard[];
};

export type LearningDashboard = {
  profile: LearnerProfile;
  metrics: DashboardMetrics;
  activity: ActivityPoint[];
  heatmap: HeatmapPoint[];
  pulses: LearningPulse[];
  module_insights: ModuleInsight[];
  recommendations: RecommendationCard[];
  coach_feedback: RealtimeFeedback;
};

export type AdaptivePathStep = {
  step_number: number;
  title: string;
  summary: string;
  href: string;
  recommendation_type: string;
  estimated_minutes: number;
  intensity: string;
  reason: string;
};

export type AdaptivePath = {
  target_role: string;
  pace_mode: string;
  adaptation_summary: string;
  steps: AdaptivePathStep[];
};

export type SkillGapItem = {
  skill_id: string;
  label: string;
  current_level: number;
  target_level: number;
  gap: number;
  evidence: string;
  recommended_actions: string[];
};

export type SkillGapReport = {
  target_role: string;
  role_summary: string;
  readiness_percent: number;
  strengths: string[];
  gaps: SkillGapItem[];
  recommendations: RecommendationCard[];
};

export type ProjectRubricCriterion = {
  id: string;
  label: string;
  description: string;
};

export type ProjectBrief = {
  slug: string;
  title: string;
  summary: string;
  difficulty: string;
  estimated_hours: number;
  deliverable: string;
  linked_lessons: string[];
  rubric: ProjectRubricCriterion[];
  submitted_count: number;
  peer_reviews_received: number;
};

export type ProjectSubmission = {
  id: number;
  project_slug: string;
  project_title: string;
  title: string;
  solution_summary: string;
  implementation_notes: string;
  confidence_level: number;
  status: string;
  ai_feedback_summary?: string | null;
  ai_recommendations: string[];
  average_peer_score?: number | null;
  review_count: number;
  created_at: string;
};

export type ReviewQueueItem = {
  submission_id: number;
  project_slug: string;
  project_title: string;
  title: string;
  author_handle: string;
  solution_summary: string;
  implementation_notes: string;
  rubric: ProjectRubricCriterion[];
};

export type PeerReview = {
  id: number;
  submission_id: number;
  reviewer_user_id: string;
  overall_score: number;
  feedback: string;
  created_at: string;
};

export type ServiceHealth = {
  status: string;
  app: string;
};

// Phase 6 V3 reviewer console (docs/architecture/phase6-implementation-spec.md section 11): the API's reviewer views only.
// A view holds claim text and public, quotable span text, span ids and a keyed digest: no learner identifier, vote,
// severity, support share or priority.
export type V3SpanView = {
  span_id: string;
  shown: boolean;
  text: string | null;
};

export type V3ClaimView = {
  claim_id: string;
  text: string | null;
  spans: V3SpanView[];
};

export type V3QueueItem = {
  item_id: string;
  subject: "claim" | "response";
  record_kind: "delivery" | "shadow";
  decision: "answer" | "abstain";
  triggers: string[];
  reasons: string[];
  held: boolean;
  state: "queued" | "claimed" | "adjudicated" | "applied";
  review_round: number;
  double_review: boolean;
  reviewable: boolean;
  enqueued_at: string;
  age_s: number;
  response_digest: string;
  claims: V3ClaimView[];
  final_gold_seq?: number | null;
};

export type V3ClaimLabel = {
  claim_id: string;
  verdict: "SUPPORTED" | "CONTRADICTED" | "NOT_ENOUGH_INFO";
  ehmf_type: "A" | "B" | "C" | "D" | "E" | null;
};

export type V3ScanResult = {
  from_seq: number;
  to_seq: number;
  records: number;
  deliveries: number;
  drawn_x6: number;
  drawn_x5: number;
  items_created: number;
  items_updated: number;
  model_changes: number;
  unparsed: number;
  done: boolean;
};

export type V3Metrics = {
  escalation_share: { deliveries: number; escalated: number; share: string; max: string; above_max: boolean; counted: string[] };
  queue: { open: number; claimed: number; age_p90_s: number | null; age_max_s: number | null; slo_s: number; above_slo: boolean };
  draws: { considered: number; x6: number; x5: number; x6_rate: string };
  double_review: { pairs: number; agreeing: number; agreement: string };
  gold: { rows: number; head_seq: number; claims_labelled: number; dawid_skene_minimum: number };
};
