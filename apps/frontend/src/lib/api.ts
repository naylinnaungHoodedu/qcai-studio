import {
  ArenaLeaderboardEntry,
  ArenaProfile,
  ArenaStatus,
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
  QAHistoryItem,
  QuizAttemptResult,
  QAResponse,
  RealtimeFeedback,
  ReviewQueueItem,
  SearchResult,
  SkillGapReport,
  UserProfile,
} from "@/lib/types";
import { AUTH_TOKEN_COOKIE_NAME } from "@/lib/auth";

const SERVER_API_BASE_URL =
  process.env.API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://127.0.0.1:8000";
const CLIENT_API_BASE_URL = "/api/backend";
const DEMO_USER_ID = "demo-learner";
const DEMO_ROLE = "learner";
const PUBLIC_REVALIDATE_SECONDS = 300;
const GUEST_CSRF_COOKIE_NAME = "qcai_guest_csrf";
const GUEST_CSRF_HEADER = "x-qcai-csrf";
const ENABLE_DEMO_AUTH =
  process.env.ENABLE_DEMO_AUTH != null
    ? process.env.ENABLE_DEMO_AUTH === "true"
    : process.env.NEXT_PUBLIC_ENABLE_DEMO_AUTH != null
      ? process.env.NEXT_PUBLIC_ENABLE_DEMO_AUTH === "true"
      : process.env.NODE_ENV !== "production";

type FetchOptions = RequestInit & {
  headers?: HeadersInit;
  cacheMode?: "public" | "private";
};

function readCookieValue(name: string): string | null {
  if (typeof document === "undefined") {
    return null;
  }
  const prefix = `${name}=`;
  const match = document.cookie
    .split(";")
    .map((item) => item.trim())
    .find((item) => item.startsWith(prefix));
  if (!match) {
    return null;
  }
  return decodeURIComponent(match.slice(prefix.length));
}

function applyGuestCsrfHeader(headers: Headers): void {
  if (headers.has("authorization") || headers.has(GUEST_CSRF_HEADER)) {
    return;
  }
  const csrfToken = readCookieValue(GUEST_CSRF_COOKIE_NAME);
  if (csrfToken) {
    headers.set(GUEST_CSRF_HEADER, csrfToken);
  }
}

function applyDemoAuthHeaders(headers: Headers): void {
  if (!ENABLE_DEMO_AUTH) {
    headers.delete("x-demo-user");
    headers.delete("x-demo-role");
    return;
  }
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

async function applyServerRequestHeaders(headers: Headers): Promise<void> {
  if (typeof window !== "undefined") {
    applyGuestCsrfHeader(headers);
    return;
  }
  try {
    const { cookies: nextCookies, headers: nextHeaders } = await import("next/headers");
    const requestHeaders = await nextHeaders();
    const cookieHeader = requestHeaders.get("cookie");
    if (cookieHeader && !headers.has("cookie")) {
      headers.set("cookie", cookieHeader);
    }
    const authorization = requestHeaders.get("authorization");
    if (authorization && !headers.has("authorization")) {
      headers.set("authorization", authorization);
    }
    const requestCookies = await nextCookies();
    const authToken = requestCookies.get(AUTH_TOKEN_COOKIE_NAME)?.value?.trim();
    if (authToken && !headers.has("authorization")) {
      headers.set("authorization", `Bearer ${authToken}`);
    }
    const csrfToken = requestCookies.get(GUEST_CSRF_COOKIE_NAME)?.value;
    if (csrfToken && !headers.has(GUEST_CSRF_HEADER)) {
      headers.set(GUEST_CSRF_HEADER, csrfToken);
    }
  } catch {
    // Requests made outside a Next request context do not have incoming headers to forward.
  }
}

async function apiFetch<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const { cacheMode = "private", ...requestOptions } = options;
  const headers = new Headers(requestOptions.headers);
  if (requestOptions.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const isPublicRequest = cacheMode === "public";
  if (!isPublicRequest) {
    await applyServerRequestHeaders(headers);
    applyDemoAuthHeaders(headers);
  }

  const method = (requestOptions.method ?? "GET").toUpperCase();
  const fetchOptions = {
    ...requestOptions,
    headers,
  };
  if (
    cacheMode === "public" &&
    typeof window === "undefined" &&
    (method === "GET" || method === "HEAD")
  ) {
    fetchOptions.next = { revalidate: PUBLIC_REVALIDATE_SECONDS };
  } else {
    fetchOptions.cache = "no-store";
  }

  const response = await fetch(`${resolveApiBaseUrl()}${path}`, fetchOptions);

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
  return apiFetch<CourseOverview>("/content/course", { cacheMode: "public" });
}

export async function fetchCourseProgress(): Promise<CourseProgress> {
  return apiFetch<CourseProgress>("/content/progress");
}

export async function fetchModule(slug: string): Promise<ModuleDetail> {
  return apiFetch<ModuleDetail>(`/content/modules/${slug}`, { cacheMode: "public" });
}

export async function fetchLesson(slug: string): Promise<LessonDetail> {
  return apiFetch<LessonDetail>(`/content/lessons/${slug}`, { cacheMode: "public" });
}

export async function fetchLessonNotes(
  slug: string,
  options: { limit?: number; offset?: number } = {},
): Promise<Note[]> {
  const params = new URLSearchParams();
  if (options.limit) {
    params.set("limit", String(options.limit));
  }
  if (options.offset) {
    params.set("offset", String(options.offset));
  }
  const suffix = params.size ? `?${params.toString()}` : "";
  return apiFetch<Note[]>(`/content/lessons/${slug}/notes${suffix}`);
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

export async function fetchQAHistory(
  lessonSlug?: string,
  options: { limit?: number; offset?: number } = {},
): Promise<QAHistoryItem[]> {
  const params = new URLSearchParams();
  if (lessonSlug) {
    params.set("lesson_slug", lessonSlug);
  }
  if (options.limit) {
    params.set("limit", String(options.limit));
  }
  if (options.offset) {
    params.set("offset", String(options.offset));
  }
  return apiFetch<QAHistoryItem[]>(`/qa/history?${params.toString()}`);
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

export async function fetchArenaStatus(): Promise<ArenaStatus> {
  return apiFetch<ArenaStatus>("/arena/status");
}

export async function fetchBuilderScenarios(): Promise<BuilderScenario[]> {
  return apiFetch<BuilderScenario[]>("/builder/scenarios");
}

export async function fetchBuilderProfile(): Promise<BuilderProfile> {
  return apiFetch<BuilderProfile>("/builder/profile");
}

export async function fetchBuilderFeed(
  options: { limit?: number; offset?: number } = {},
): Promise<BuilderFeedItem[]> {
  const params = new URLSearchParams();
  if (options.limit) {
    params.set("limit", String(options.limit));
  }
  if (options.offset) {
    params.set("offset", String(options.offset));
  }
  const suffix = params.size ? `?${params.toString()}` : "";
  return apiFetch<BuilderFeedItem[]>(`/builder/feed${suffix}`);
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

export async function fetchMyProjectSubmissions(
  options: { limit?: number; offset?: number } = {},
): Promise<ProjectSubmission[]> {
  const params = new URLSearchParams();
  if (options.limit) {
    params.set("limit", String(options.limit));
  }
  if (options.offset) {
    params.set("offset", String(options.offset));
  }
  const suffix = params.size ? `?${params.toString()}` : "";
  return apiFetch<ProjectSubmission[]>(`/projects/my-submissions${suffix}`);
}

export async function fetchProjectReviewQueue(
  options: { limit?: number; offset?: number } = {},
): Promise<ReviewQueueItem[]> {
  const params = new URLSearchParams();
  if (options.limit) {
    params.set("limit", String(options.limit));
  }
  if (options.offset) {
    params.set("offset", String(options.offset));
  }
  const suffix = params.size ? `?${params.toString()}` : "";
  return apiFetch<ReviewQueueItem[]>(`/projects/review-queue${suffix}`);
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

export async function retractProjectSubmission(
  submissionId: number,
): Promise<ProjectSubmission> {
  return apiFetch<ProjectSubmission>(`/projects/submissions/${submissionId}`, {
    method: "DELETE",
  });
}
