import { createHmac, timingSafeEqual } from "node:crypto";

import { NextRequest, NextResponse } from "next/server";

// Keyed-MAC guest tokens (plan task 1.1, Decision D-09): `g1.<guest_id>.<issued_unix>.<hmac>`.
// The API verifies the same format in apps/api/app/core/guest_tokens.py; keep the two in step.
export const GUEST_TOKEN_COOKIE_NAME = "qcai_guest_token";
export const GUEST_CSRF_COOKIE_NAME = "qcai_guest_csrf";
export const GUEST_CSRF_HEADER = "x-qcai-csrf";
// The unsigned id cookie used before signed tokens; it is no longer a credential and gets cleared.
export const LEGACY_GUEST_COOKIE_NAME = "qcai_guest_id";

const GUEST_TOKEN_VERSION = "g1";
const GUEST_CSRF_LENGTH = 48;
const GUEST_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 365;
const CLOCK_SKEW_SECONDS = 300;
// Matches DEVELOPMENT_GUEST_TOKEN_SECRET in apps/api/app/core/config.py; never used in production.
const DEVELOPMENT_GUEST_TOKEN_SECRET = "qcai-development-only-guest-token-secret";
const COOKIE_MAX_AGE_SECONDS = GUEST_TOKEN_MAX_AGE_SECONDS;
const COOKIE_DOMAIN = process.env.NEXT_PUBLIC_COOKIE_DOMAIN || process.env.COOKIE_DOMAIN;
const GUEST_ID_PATTERN = /^guest-[0-9a-f-]{8,64}$/;
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
  guestToken: string;
  guestCsrf: string;
  createdGuestToken: boolean;
  createdGuestCsrf: boolean;
  clearLegacyGuestCookie: boolean;
};

function signingSecret(): string {
  const secret = process.env.GUEST_TOKEN_SECRET;
  if (secret) {
    return secret;
  }
  if (process.env.NODE_ENV === "production") {
    throw new Error("GUEST_TOKEN_SECRET is required in production.");
  }
  return DEVELOPMENT_GUEST_TOKEN_SECRET;
}

function verificationSecrets(): string[] {
  const previous = process.env.GUEST_TOKEN_PREVIOUS_SECRET;
  return previous ? [signingSecret(), previous] : [signingSecret()];
}

function mac(secret: string, purpose: string, guestId: string, issuedAt: number): string {
  return createHmac("sha256", secret)
    .update(`${GUEST_TOKEN_VERSION}|${purpose}|${guestId}|${issuedAt}`)
    .digest("hex");
}

function sameText(left: string, right: string): boolean {
  const leftBytes = Buffer.from(left);
  const rightBytes = Buffer.from(right);
  return leftBytes.length === rightBytes.length && timingSafeEqual(leftBytes, rightBytes);
}

function csrfFor(secret: string, guestId: string, issuedAt: number): string {
  return mac(secret, "csrf", guestId, issuedAt).slice(0, GUEST_CSRF_LENGTH);
}

export function issueGuestToken(guestId: string, issuedAt: number): { token: string; csrf: string } {
  const secret = signingSecret();
  return {
    token: `${GUEST_TOKEN_VERSION}.${guestId}.${issuedAt}.${mac(secret, "token", guestId, issuedAt)}`,
    csrf: csrfFor(secret, guestId, issuedAt),
  };
}

export function verifyGuestToken(
  token: string | undefined,
  now: number = Math.floor(Date.now() / 1000),
): { guestId: string; csrf: string } | null {
  const parts = token?.trim().split(".") ?? [];
  if (parts.length !== 4 || parts[0] !== GUEST_TOKEN_VERSION) {
    return null;
  }
  const [, guestId, issuedText, signature] = parts;
  if (!GUEST_ID_PATTERN.test(guestId) || !/^\d+$/.test(issuedText)) {
    return null;
  }
  const issuedAt = Number(issuedText);
  if (issuedAt > now + CLOCK_SKEW_SECONDS || now - issuedAt > GUEST_TOKEN_MAX_AGE_SECONDS) {
    return null;
  }
  for (const secret of verificationSecrets()) {
    if (sameText(signature, mac(secret, "token", guestId, issuedAt))) {
      return { guestId, csrf: csrfFor(secret, guestId, issuedAt) };
    }
  }
  return null;
}

function createGuestId(): string {
  return `guest-${crypto.randomUUID().toLowerCase()}`;
}

function replaceCookies(existing: string | null, replacements: Record<string, string>): string {
  const names = new Set(Object.keys(replacements));
  const kept = (existing ?? "")
    .split(";")
    .map((part) => part.trim())
    .filter((part) => part && !names.has(part.split("=")[0]?.trim() ?? ""));
  return [...kept, ...Object.entries(replacements).map(([name, value]) => `${name}=${value}`)].join("; ");
}

export function resolveGuestSession(request: NextRequest): GuestSession {
  const existingToken = request.cookies.get(GUEST_TOKEN_COOKIE_NAME)?.value;
  const existingCsrf = request.cookies.get(GUEST_CSRF_COOKIE_NAME)?.value?.trim().toLowerCase();
  const clearLegacyGuestCookie = request.cookies.has(LEGACY_GUEST_COOKIE_NAME);

  const verified = verifyGuestToken(existingToken);
  if (verified && existingToken) {
    return {
      guestToken: existingToken.trim(),
      guestCsrf: verified.csrf,
      createdGuestToken: false,
      createdGuestCsrf: existingCsrf !== verified.csrf,
      clearLegacyGuestCookie,
    };
  }

  // No valid token (absent, forged, expired or a legacy id cookie): start a fresh guest identity.
  const issued = issueGuestToken(createGuestId(), Math.floor(Date.now() / 1000));
  return {
    guestToken: issued.token,
    guestCsrf: issued.csrf,
    createdGuestToken: true,
    createdGuestCsrf: true,
    clearLegacyGuestCookie,
  };
}

const LEGACY_UPGRADE_TIMEOUT_MS = 3000;

// During the bounded migration window (plan L1108-1110) the API may re-issue a signed token for a
// legacy guest id; it refuses ids that were ever public (AC-1-12). Off unless GUEST_LEGACY_UPGRADE_ENABLED=true.
export async function resolveGuestSessionWithLegacyUpgrade(
  request: NextRequest,
  apiBaseUrl: string,
): Promise<GuestSession> {
  const session = resolveGuestSession(request);
  if (process.env.GUEST_LEGACY_UPGRADE_ENABLED !== "true" || !session.createdGuestToken || !session.clearLegacyGuestCookie) {
    return session;
  }
  const legacyGuestId = request.cookies.get(LEGACY_GUEST_COOKIE_NAME)?.value?.trim().toLowerCase();
  const legacyCsrf = request.cookies.get(GUEST_CSRF_COOKIE_NAME)?.value?.trim().toLowerCase();
  if (!legacyGuestId || !legacyCsrf) {
    return session;
  }

  const headers = new Headers({ "content-type": "application/json" });
  const forwardedFor = request.headers.get("x-forwarded-for");
  if (forwardedFor) {
    headers.set("x-forwarded-for", forwardedFor);
  }
  try {
    const response = await fetch(`${apiBaseUrl.replace(/\/$/, "")}/auth/guest-upgrade`, {
      method: "POST",
      headers,
      body: JSON.stringify({ legacy_guest_id: legacyGuestId, legacy_csrf: legacyCsrf }),
      cache: "no-store",
      signal: AbortSignal.timeout(LEGACY_UPGRADE_TIMEOUT_MS),
    });
    if (!response.ok) {
      return session;
    }
    const payload = (await response.json()) as { upgraded?: boolean; guest_token?: string | null };
    const verified = payload.upgraded ? verifyGuestToken(payload.guest_token ?? undefined) : null;
    if (!verified || verified.guestId !== legacyGuestId || !payload.guest_token) {
      return session;
    }
    return { ...session, guestToken: payload.guest_token, guestCsrf: verified.csrf };
  } catch {
    // Any failure keeps the fresh identity; the upgrade is a convenience, never a requirement.
    return session;
  }
}

export function applyGuestSessionToHeaders(
  request: NextRequest,
  headers: Headers,
  session: GuestSession,
  options: { ensureCsrfHeader?: boolean } = {},
): void {
  const replacements: Record<string, string> = {};
  if (session.createdGuestToken) {
    replacements[GUEST_TOKEN_COOKIE_NAME] = session.guestToken;
  }
  if (session.createdGuestCsrf) {
    replacements[GUEST_CSRF_COOKIE_NAME] = session.guestCsrf;
  }

  const cookieHeader = Object.keys(replacements).length
    ? replaceCookies(request.headers.get("cookie"), replacements)
    : request.headers.get("cookie");
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
  if (!session.createdGuestToken && !session.createdGuestCsrf && !session.clearLegacyGuestCookie) {
    return;
  }

  const secure = request.nextUrl.protocol === "https:" || process.env.NODE_ENV === "production";
  const shared = {
    sameSite: "lax" as const,
    secure,
    path: "/",
    ...(COOKIE_DOMAIN ? { domain: COOKIE_DOMAIN } : {}),
  };

  if (session.createdGuestToken) {
    response.cookies.set({
      name: GUEST_TOKEN_COOKIE_NAME,
      value: session.guestToken,
      httpOnly: true,
      maxAge: COOKIE_MAX_AGE_SECONDS,
      ...shared,
    });
  }
  if (session.createdGuestCsrf) {
    response.cookies.set({
      name: GUEST_CSRF_COOKIE_NAME,
      value: session.guestCsrf,
      httpOnly: false,
      maxAge: COOKIE_MAX_AGE_SECONDS,
      ...shared,
    });
  }
  if (session.clearLegacyGuestCookie) {
    response.cookies.set({ name: LEGACY_GUEST_COOKIE_NAME, value: "", httpOnly: true, maxAge: 0, ...shared });
  }
}

export function routeRequiresGuestSession(path: string): boolean {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return !PUBLIC_API_ROUTE_PATTERNS.some((pattern) => pattern.test(normalizedPath));
}
