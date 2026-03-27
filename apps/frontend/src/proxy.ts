import { NextRequest, NextResponse } from "next/server";

const GUEST_COOKIE_NAME = "qcai_guest_id";
const GUEST_CSRF_COOKIE_NAME = "qcai_guest_csrf";
const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365;
const COOKIE_DOMAIN = process.env.NEXT_PUBLIC_COOKIE_DOMAIN || process.env.COOKIE_DOMAIN;

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

export function proxy(request: NextRequest) {
  const existingGuestId = request.cookies.get(GUEST_COOKIE_NAME)?.value;
  const existingGuestCsrf = request.cookies.get(GUEST_CSRF_COOKIE_NAME)?.value;
  if (existingGuestId && existingGuestCsrf) {
    return NextResponse.next();
  }

  const guestId = existingGuestId || createGuestId();
  const guestCsrf = existingGuestCsrf || createGuestCsrfToken();
  const requestHeaders = new Headers(request.headers);
  let cookieHeader = request.headers.get("cookie") ?? "";
  if (!existingGuestId) {
    cookieHeader = appendCookieHeader(cookieHeader, `${GUEST_COOKIE_NAME}=${guestId}`);
  }
  if (!existingGuestCsrf) {
    cookieHeader = appendCookieHeader(cookieHeader, `${GUEST_CSRF_COOKIE_NAME}=${guestCsrf}`);
  }
  requestHeaders.set("cookie", cookieHeader);

  const response = NextResponse.next({
    request: {
      headers: requestHeaders,
    },
  });

  response.cookies.set({
    name: GUEST_COOKIE_NAME,
    value: guestId,
    httpOnly: true,
    sameSite: "lax",
    secure: request.nextUrl.protocol === "https:" || process.env.NODE_ENV === "production",
    path: "/",
    maxAge: COOKIE_MAX_AGE_SECONDS,
    ...(COOKIE_DOMAIN ? { domain: COOKIE_DOMAIN } : {}),
  });
  response.cookies.set({
    name: GUEST_CSRF_COOKIE_NAME,
    value: guestCsrf,
    httpOnly: false,
    sameSite: "lax",
    secure: request.nextUrl.protocol === "https:" || process.env.NODE_ENV === "production",
    path: "/",
    maxAge: COOKIE_MAX_AGE_SECONDS,
    ...(COOKIE_DOMAIN ? { domain: COOKIE_DOMAIN } : {}),
  });

  return response;
}

export const config = {
  matcher: ["/((?!api/backend|_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml).*)"],
};
