import { NextRequest, NextResponse } from "next/server";

import {
  applyGuestSessionToHeaders,
  resolveGuestSession,
  setGuestSessionCookies,
} from "@/lib/guest-session";

const IS_PRODUCTION = process.env.NODE_ENV === "production";
const PRIVATE_PAGE_PREFIXES = ["/account", "/builder", "/dashboard", "/projects"];

function createNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

function buildConnectSources(): string {
  const connectSources = new Set(["'self'"]);
  if (!IS_PRODUCTION) {
    connectSources.add("http://127.0.0.1:*");
    connectSources.add("http://localhost:*");
  }

  const candidateOrigins = [process.env.API_BASE_URL, process.env.NEXT_PUBLIC_API_BASE_URL];

  for (const candidate of candidateOrigins) {
    if (!candidate) {
      continue;
    }
    try {
      const parsed = new URL(candidate);
      if (
        IS_PRODUCTION &&
        ["0.0.0.0", "127.0.0.1", "localhost"].includes(parsed.hostname)
      ) {
        continue;
      }
      connectSources.add(parsed.origin);
      connectSources.add(`${parsed.protocol === "https:" ? "wss:" : "ws:"}//${parsed.host}`);
    } catch {
      // Ignore invalid deployment-time URLs and keep the safer defaults.
    }
  }

  return Array.from(connectSources).join(" ");
}

function buildContentSecurityPolicy(request: NextRequest, nonce: string): string {
  const scriptSources = ["'self'", `'nonce-${nonce}'`, "'strict-dynamic'"];
  if (!IS_PRODUCTION) {
    scriptSources.push("'unsafe-eval'");
  }

  return [
    "default-src 'self'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "object-src 'none'",
    "img-src 'self' data: blob:",
    "media-src 'self' blob:",
    "style-src 'self' 'unsafe-inline'",
    `script-src ${scriptSources.join(" ")}`,
    `connect-src ${buildConnectSources()}`,
  ].join("; ");
}

function pageRequiresGuestBootstrap(pathname: string): boolean {
  return PRIVATE_PAGE_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

export function proxy(request: NextRequest) {
  const nonce = createNonce();
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);

  const session = pageRequiresGuestBootstrap(request.nextUrl.pathname) ? resolveGuestSession(request) : null;
  if (session) {
    applyGuestSessionToHeaders(request, requestHeaders, session);
  }

  const response = NextResponse.next({
    request: {
      headers: requestHeaders,
    },
  });
  response.headers.set("Content-Security-Policy", buildContentSecurityPolicy(request, nonce));
  response.headers.set("x-nonce", nonce);

  if (session) {
    setGuestSessionCookies(response, request, session);
  }
  return response;
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml|.*\\.(?:css|gif|ico|jpeg|jpg|js|map|mp4|pdf|png|svg|txt|webp|xml)$).*)",
  ],
};
