import {
  AuthAction,
  AssistantChatMessage,
  AssistantChatResponse,
  AuthSession,
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
  PublicWebVitalSummary,
  ProjectBrief,
  ProjectSubmission,
  QAHistoryItem,
  QuizAttemptResult,
  QAResponse,
  RealtimeFeedback,
  ReviewQueueItem,
  SearchResult,
  ServiceHealth,
  SkillGapReport,
  SupportRequestReceipt,
  UserProfile,
} from "@/lib/types";
import { normalizeAssistantHistory } from "@/lib/assistant-chat";
import { describeApiError } from "@/lib/api-errors";
import { AUTH_CSRF_COOKIE_NAME, AUTH_CSRF_HEADER, AUTH_TOKEN_COOKIE_NAME } from "@/lib/auth";

const DEFAULT_PRODUCTION_API_BASE_URL = "https://api.qantumlearn.academy";
const LOCAL_DEV_API_BASE_URL = "http://127.0.0.1:8000";
const SERVER_API_BASE_URL =
  process.env.API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  (process.env.NODE_ENV === "production" ? DEFAULT_PRODUCTION_API_BASE_URL : LOCAL_DEV_API_BASE_URL);
const CLIENT_API_BASE_URL = "/api/backend";
const DEMO_USER_ID = "demo-learner";
const DEMO_ROLE = "learner";
const PUBLIC_REVALIDATE_SECONDS = 300;
const GUEST_CSRF_COOKIE_NAME = "qcai_guest_csrf";
const PUBLIC_WEB_VITAL_RETRY_DELAY_MS = 250;
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

function applyCsrfHeader(headers: Headers): void {
  if (headers.has("authorization") || headers.has(AUTH_CSRF_HEADER)) {
    return;
  }
  const csrfToken = readCookieValue(AUTH_CSRF_COOKIE_NAME) || readCookieValue(GUEST_CSRF_COOKIE_NAME);
  if (csrfToken) {
    headers.set(AUTH_CSRF_HEADER, csrfToken);
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
    applyCsrfHeader(headers);
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
    const csrfToken =
      requestCookies.get(AUTH_CSRF_COOKIE_NAME)?.value ||
      requestCookies.get(GUEST_CSRF_COOKIE_NAME)?.value;
    if (csrfToken && !headers.has(AUTH_CSRF_HEADER)) {
      headers.set(AUTH_CSRF_HEADER, csrfToken);
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
  const method = (requestOptions.method ?? "GET").toUpperCase();
  const isPublicRequest = cacheMode === "public";
  const isSafeMethod = method === "GET" || method === "HEAD" || method === "OPTIONS";
  if (!isPublicRequest || !isSafeMethod) {
    await applyServerRequestHeaders(headers);
  }
  if (!isPublicRequest) {
    applyDemoAuthHeaders(headers);
  }

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
    let detail =
      describeApiError(response.status, response.headers, {}) || `API request failed: ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown; error?: unknown };
      const describedError = describeApiError(response.status, response.headers, payload);
      if (describedError) {
        detail = describedError;
      }
    } catch {
      // Keep the status-based fallback when the error body is not JSON.
    }
    throw new Error(detail);
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

export async function chatWithTeachingAssistant(payload: {
  message: string;
  lesson_slug?: string | null;
  page_path?: string | null;
  history?: AssistantChatMessage[];
  top_k?: number;
}): Promise<AssistantChatResponse> {
  return apiFetch<AssistantChatResponse>("/assistant/chat", {
    method: "POST",
    body: JSON.stringify({
      message: payload.message,
      lesson_slug: payload.lesson_slug ?? null,
      page_path: payload.page_path ?? null,
      history: normalizeAssistantHistory(payload.history ?? []),
      top_k: payload.top_k ?? 4,
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

export async function registerAccount(email: string, password: string): Promise<AuthSession> {
  return apiFetch<AuthSession>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function loginAccount(email: string, password: string): Promise<AuthSession> {
  return apiFetch<AuthSession>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function logoutAccount(): Promise<AuthAction> {
  return apiFetch<AuthAction>("/auth/logout", {
    method: "POST",
  });
}

export async function deleteAccount(password: string): Promise<AuthAction> {
  return apiFetch<AuthAction>("/auth/account", {
    method: "DELETE",
    body: JSON.stringify({ password }),
  });
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

export async function postPublicWebVital(payload: {
  metric_id: string;
  metric_name: string;
  path: string;
  value: number;
  delta?: number | null;
  rating: string;
  navigation_type?: string | null;
  connection_type?: string | null;
}): Promise<void> {
  const isRetryableTelemetryError = (error: unknown): boolean => {
    if (!(error instanceof Error)) {
      return false;
    }
    const message = error.message.toLowerCase();
    return (
      message.includes("timed out") ||
      message.includes("could not reach") ||
      message.includes("upstream_timeout") ||
      message.includes("upstream_unavailable") ||
      message.includes("api request failed: 502") ||
      message.includes("api request failed: 503") ||
      message.includes("api request failed: 504")
    );
  };

  for (let attempt = 1; attempt <= 2; attempt += 1) {
    try {
      await apiFetch("/analytics/public-web-vitals", {
        method: "POST",
        cacheMode: "public",
        keepalive: true,
        body: JSON.stringify(payload),
      });
      return;
    } catch (error) {
      if (attempt === 2 || !isRetryableTelemetryError(error)) {
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, PUBLIC_WEB_VITAL_RETRY_DELAY_MS));
    }
  }
}

export async function fetchPublicWebVitalsSummary(): Promise<PublicWebVitalSummary> {
  return apiFetch<PublicWebVitalSummary>("/analytics/public-web-vitals/summary", {
    cacheMode: "public",
  });
}

export async function fetchServiceHealth(): Promise<ServiceHealth> {
  return apiFetch<ServiceHealth>("/health", { cacheMode: "public" });
}

export async function submitSupportRequest(payload: {
  name: string;
  email: string;
  organization?: string | null;
  request_type: string;
  page_url?: string | null;
  message: string;
  website?: string | null;
}): Promise<SupportRequestReceipt> {
  return apiFetch<SupportRequestReceipt>("/support/requests", {
    method: "POST",
    cacheMode: "public",
    body: JSON.stringify(payload),
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
