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

export type QuizQuestion = {
  id: string;
  question_type: string;
  prompt: string;
  choices: string[];
  answer: string;
  explanation: string;
  difficulty: string;
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
    source_title: string;
    source_kind: string;
    section_title: string;
    excerpt: string;
    timestamp_label?: string | null;
  }>;
  retrieval_mode: string;
};

export type QuizAttemptResult = {
  status: string;
  attempt_id: number;
  score: number;
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
