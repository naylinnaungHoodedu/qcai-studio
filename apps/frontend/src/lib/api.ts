import {
  ArenaLeaderboardEntry,
  ArenaProfile,
  AdaptivePath,
  BuilderFeedItem,
  BuilderProfile,
  BuilderScenario,
  BuilderSubmissionResult,
  CourseProgress,
  CourseOverview,
  LearningDashboard,
  LearningPulse,
  LearnerProfile,
  LessonDetail,
  ModuleDetail,
  Note,
  PeerReview,
  ProjectBrief,
  ProjectSubmission,
  QuizAttemptResult,
  QAResponse,
  RealtimeFeedback,
  ReviewQueueItem,
  SearchResult,
  SkillGapReport,
  UserProfile,
} from "@/lib/types";

const SERVER_API_BASE_URL =
  process.env.API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://127.0.0.1:8000";
const CLIENT_API_BASE_URL = "/api/backend";
const DEMO_USER_ID = "demo-learner";
const DEMO_ROLE = "learner";

type FetchOptions = RequestInit & { headers?: HeadersInit };

function applyDemoAuthHeaders(headers: Headers): void {
  if (headers.has("authorization")) {
    headers.delete("x-demo-user");
    headers.delete("x-demo-role");
    return;
  }
  if (!headers.has("x-demo-user")) {
    headers.set("x-demo-user", DEMO_USER_ID);
  }
  if (!headers.has("x-demo-role")) {
    headers.set("x-demo-role", DEMO_ROLE);
  }
}

function resolveApiBaseUrl(): string {
  if (typeof window === "undefined") {
    return SERVER_API_BASE_URL;
  }
  return CLIENT_API_BASE_URL;
}

async function apiFetch<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  applyDemoAuthHeaders(headers);

  const response = await fetch(`${resolveApiBaseUrl()}${path}`, {
    ...options,
    headers,
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function getApiBaseUrl(): string {
  return SERVER_API_BASE_URL;
}

export function getClientApiBaseUrl(): string {
  return CLIENT_API_BASE_URL;
}

export async function fetchCourseOverview(): Promise<CourseOverview> {
  return apiFetch<CourseOverview>("/content/course");
}

export async function fetchCourseProgress(): Promise<CourseProgress> {
  return apiFetch<CourseProgress>("/content/progress");
}

export async function fetchModule(slug: string): Promise<ModuleDetail> {
  return apiFetch<ModuleDetail>(`/content/modules/${slug}`);
}

export async function fetchLesson(slug: string): Promise<LessonDetail> {
  return apiFetch<LessonDetail>(`/content/lessons/${slug}`);
}

export async function fetchLessonNotes(slug: string): Promise<Note[]> {
  return apiFetch<Note[]>(`/content/lessons/${slug}/notes`);
}

export async function createLessonNote(
  slug: string,
  body: string,
  anchorValue?: string,
): Promise<Note> {
  return apiFetch<Note>(`/content/lessons/${slug}/notes`, {
    method: "POST",
    body: JSON.stringify({
      body,
      anchor_type: anchorValue ? "chapter" : null,
      anchor_value: anchorValue ?? null,
    }),
  });
}

export async function askQuestion(
  question: string,
  lessonSlug?: string,
): Promise<QAResponse> {
  return apiFetch<QAResponse>("/qa/ask", {
    method: "POST",
    body: JSON.stringify({
      question,
      lesson_slug: lessonSlug ?? null,
      top_k: 4,
    }),
  });
}

export async function searchContent(
  query: string,
  lessonSlug?: string,
): Promise<SearchResult[]> {
  const params = new URLSearchParams({ query });
  if (lessonSlug) {
    params.set("lesson_slug", lessonSlug);
  }
  return apiFetch<SearchResult[]>(`/search?${params.toString()}`);
}

export async function fetchMe(): Promise<UserProfile> {
  return apiFetch<UserProfile>("/auth/me");
}

export async function postAnalyticsEvent(
  eventType: string,
  lessonSlug?: string,
  payload: Record<string, unknown> = {},
): Promise<void> {
  await apiFetch("/analytics/events", {
    method: "POST",
    body: JSON.stringify({
      event_type: eventType,
      lesson_slug: lessonSlug ?? null,
      payload,
    }),
  });
}

export async function recordQuizAttempt(
  lessonSlug: string,
  score: number,
  responses: Record<string, string>,
): Promise<QuizAttemptResult> {
  return apiFetch<QuizAttemptResult>("/content/quiz-attempts", {
    method: "POST",
    body: JSON.stringify({
      lesson_slug: lessonSlug,
      score,
      responses,
    }),
  });
}

export async function fetchArenaLeaderboard(): Promise<ArenaLeaderboardEntry[]> {
  return apiFetch<ArenaLeaderboardEntry[]>("/arena/leaderboard");
}

export async function fetchArenaProfile(playerId: string): Promise<ArenaProfile> {
  return apiFetch<ArenaProfile>(`/arena/profiles/${playerId}`);
}

export async function fetchBuilderScenarios(): Promise<BuilderScenario[]> {
  return apiFetch<BuilderScenario[]>("/builder/scenarios");
}

export async function fetchBuilderProfile(): Promise<BuilderProfile> {
  return apiFetch<BuilderProfile>("/builder/profile");
}

export async function fetchBuilderFeed(): Promise<BuilderFeedItem[]> {
  return apiFetch<BuilderFeedItem[]>("/builder/feed");
}

export async function submitBuilderScenario(
  scenarioSlug: string,
  placements: Record<string, string>,
): Promise<BuilderSubmissionResult> {
  return apiFetch<BuilderSubmissionResult>("/builder/submit", {
    method: "POST",
    body: JSON.stringify({
      scenario_slug: scenarioSlug,
      placements,
    }),
  });
}

export async function shareBuilderScenario(
  scenarioSlug: string,
  caption: string,
  placements: Record<string, string>,
): Promise<BuilderFeedItem> {
  return apiFetch<BuilderFeedItem>("/builder/share", {
    method: "POST",
    body: JSON.stringify({
      scenario_slug: scenarioSlug,
      caption,
      placements,
    }),
  });
}

export async function fetchLearningDashboard(): Promise<LearningDashboard> {
  return apiFetch<LearningDashboard>("/insights/dashboard");
}

export async function fetchAdaptivePath(): Promise<AdaptivePath> {
  return apiFetch<AdaptivePath>("/insights/path");
}

export async function fetchSkillGapReport(): Promise<SkillGapReport> {
  return apiFetch<SkillGapReport>("/insights/skill-gap");
}

export async function updateLearnerProfile(payload: {
  target_role: string;
  weekly_goal_hours: number;
  preferred_pace: string;
  focus_area?: string | null;
  self_ratings: Record<string, number>;
}): Promise<LearnerProfile> {
  return apiFetch<LearnerProfile>("/insights/profile", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function createLearningCheckIn(payload: {
  motivation_level: number;
  focus_level: number;
  energy_level: number;
  session_minutes: number;
  today_goal?: string;
  blocker?: string;
}): Promise<LearningPulse> {
  return apiFetch<LearningPulse>("/insights/check-ins", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function requestRealtimeFeedback(payload: {
  context_type: string;
  content: string;
  lesson_slug?: string;
  project_slug?: string;
  score?: number;
}): Promise<RealtimeFeedback> {
  return apiFetch<RealtimeFeedback>("/insights/realtime-feedback", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchProjectCatalog(): Promise<ProjectBrief[]> {
  return apiFetch<ProjectBrief[]>("/projects/catalog");
}

export async function fetchMyProjectSubmissions(): Promise<ProjectSubmission[]> {
  return apiFetch<ProjectSubmission[]>("/projects/my-submissions");
}

export async function fetchProjectReviewQueue(): Promise<ReviewQueueItem[]> {
  return apiFetch<ReviewQueueItem[]>("/projects/review-queue");
}

export async function createProjectSubmission(payload: {
  project_slug: string;
  title: string;
  solution_summary: string;
  implementation_notes: string;
  confidence_level: number;
}): Promise<ProjectSubmission> {
  return apiFetch<ProjectSubmission>("/projects/submissions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function submitPeerReview(payload: {
  submission_id: number;
  rubric_scores: Record<string, number>;
  feedback: string;
}): Promise<PeerReview> {
  return apiFetch<PeerReview>("/projects/reviews", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
