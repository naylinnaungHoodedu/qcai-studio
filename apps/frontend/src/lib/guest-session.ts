import { NextRequest, NextResponse } from "next/server";

export const GUEST_COOKIE_NAME = "qcai_guest_id";
export const GUEST_CSRF_COOKIE_NAME = "qcai_guest_csrf";
export const GUEST_CSRF_HEADER = "x-qcai-csrf";

const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365;
const COOKIE_DOMAIN = process.env.NEXT_PUBLIC_COOKIE_DOMAIN || process.env.COOKIE_DOMAIN;
const GUEST_ID_PATTERN = /^guest-[0-9a-f-]{8,64}$/;
const GUEST_CSRF_PATTERN = /^[0-9a-f-]{16,128}$/;
const PUBLIC_API_ROUTE_PATTERNS = [
  /^\/health$/,
  /^\/ready$/,
  /^\/content\/course$/,
  /^\/content\/modules\/[^/]+$/,
  /^\/content\/lessons\/[^/]+$/,
  /^\/search$/,
  /^\/analytics\/public-web-vitals$/,
  /^\/analytics\/public-web-vitals\/summary$/,
  /^\/support\/requests$/,
];

export type GuestSession = {
  guestId: string;
  guestCsrf: string;
  createdGuestId: boolean;
  createdGuestCsrf: boolean;
};

function createGuestId(): string {
  return `guest-${crypto.randomUUID().toLowerCase()}`;
}

function createGuestCsrfToken(): string {
  return crypto.randomUUID().toLowerCase();
}

function appendCookieHeader(existing: string | null, cookie: string): string {
  if (!existing) {
    return cookie;
  }
  return `${existing}; ${cookie}`;
}

function isValidGuestId(value: string | undefined): value is string {
  return Boolean(value && GUEST_ID_PATTERN.test(value));
}

function isValidGuestCsrf(value: string | undefined): value is string {
  return Boolean(value && GUEST_CSRF_PATTERN.test(value));
}

export function resolveGuestSession(request: NextRequest): GuestSession {
  const existingGuestId = request.cookies.get(GUEST_COOKIE_NAME)?.value?.trim().toLowerCase();
  const existingGuestCsrf = request.cookies.get(GUEST_CSRF_COOKIE_NAME)?.value?.trim().toLowerCase();

  const guestIdIsValid = isValidGuestId(existingGuestId);
  const guestCsrfIsValid = guestIdIsValid && isValidGuestCsrf(existingGuestCsrf);

  return {
    guestId: guestIdIsValid ? existingGuestId : createGuestId(),
    guestCsrf: guestCsrfIsValid ? existingGuestCsrf : createGuestCsrfToken(),
    createdGuestId: !guestIdIsValid,
    createdGuestCsrf: !guestCsrfIsValid,
  };
}

export function applyGuestSessionToHeaders(
  request: NextRequest,
  headers: Headers,
  session: GuestSession,
  options: { ensureCsrfHeader?: boolean } = {},
): void {
  let cookieHeader = request.headers.get("cookie");

  if (session.createdGuestId) {
    cookieHeader = appendCookieHeader(cookieHeader, `${GUEST_COOKIE_NAME}=${session.guestId}`);
  }
  if (session.createdGuestCsrf) {
    cookieHeader = appendCookieHeader(cookieHeader, `${GUEST_CSRF_COOKIE_NAME}=${session.guestCsrf}`);
  }

  if (cookieHeader) {
    headers.set("cookie", cookieHeader);
  }
  if (options.ensureCsrfHeader && !headers.has(GUEST_CSRF_HEADER)) {
    headers.set(GUEST_CSRF_HEADER, session.guestCsrf);
  }
}

export function setGuestSessionCookies(
  response: NextResponse,
  request: NextRequest,
  session: GuestSession,
): void {
  if (!session.createdGuestId && !session.createdGuestCsrf) {
    return;
  }

  const secure = request.nextUrl.protocol === "https:" || process.env.NODE_ENV === "production";

  if (session.createdGuestId) {
    response.cookies.set({
      name: GUEST_COOKIE_NAME,
      value: session.guestId,
      httpOnly: true,
      sameSite: "lax",
      secure,
      path: "/",
      maxAge: COOKIE_MAX_AGE_SECONDS,
      ...(COOKIE_DOMAIN ? { domain: COOKIE_DOMAIN } : {}),
    });
  }
  if (session.createdGuestCsrf) {
    response.cookies.set({
      name: GUEST_CSRF_COOKIE_NAME,
      value: session.guestCsrf,
      httpOnly: false,
      sameSite: "lax",
      secure,
      path: "/",
      maxAge: COOKIE_MAX_AGE_SECONDS,
      ...(COOKIE_DOMAIN ? { domain: COOKIE_DOMAIN } : {}),
    });
  }
}

export function routeRequiresGuestSession(path: string): boolean {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return !PUBLIC_API_ROUTE_PATTERNS.some((pattern) => pattern.test(normalizedPath));
}
