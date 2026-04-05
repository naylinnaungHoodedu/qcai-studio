import { NextRequest, NextResponse } from "next/server";
import { stringifyCookie } from "next/dist/server/web/spec-extension/cookies";

import { getAuthorizationHeaderFromRequest } from "@/lib/auth";
import {
  applyGuestSessionToHeaders,
  resolveGuestSession,
  routeRequiresGuestSession,
  setGuestSessionCookies,
} from "@/lib/guest-session";

const DEFAULT_PRODUCTION_API_BASE_URL = "https://api.qantumlearn.academy";
const LOCAL_DEV_API_BASE_URL = "http://127.0.0.1:8000";
const API_BASE_URL =
  process.env.API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  (process.env.NODE_ENV === "production" ? DEFAULT_PRODUCTION_API_BASE_URL : LOCAL_DEV_API_BASE_URL);
const DEMO_USER_ID = "demo-learner";
const DEMO_ROLE = "learner";
const ENABLE_DEMO_AUTH =
  process.env.ENABLE_DEMO_AUTH != null
    ? process.env.ENABLE_DEMO_AUTH === "true"
    : process.env.NEXT_PUBLIC_ENABLE_DEMO_AUTH != null
      ? process.env.NEXT_PUBLIC_ENABLE_DEMO_AUTH === "true"
      : process.env.NODE_ENV !== "production";
const UPSTREAM_TIMEOUT_MS = 8000;
const NO_STORE_HEADERS = {
  "Cache-Control": "no-store",
};

function buildTargetUrl(pathParts: string[], request: NextRequest): string {
  const base = API_BASE_URL.replace(/\/$/, "");
  const path = pathParts.join("/");
  const url = new URL(`${base}/${path}`);
  url.search = request.nextUrl.search;
  return url.toString();
}

function applyGuestSessionCookiesToResponse(
  response: Response,
  request: NextRequest,
  session: ReturnType<typeof resolveGuestSession> | null,
): Response {
  if (!session) {
    return response;
  }

  const cookieResponse = new NextResponse(null);
  setGuestSessionCookies(cookieResponse, request, session);
  for (const cookie of cookieResponse.cookies.getAll()) {
    response.headers.append("set-cookie", stringifyCookie(cookie));
  }
  return response;
}

function buildUpstreamErrorResponse(
  request: NextRequest,
  method: string,
  error: unknown,
  session: ReturnType<typeof resolveGuestSession> | null,
): Response {
  const isTimeout = error instanceof Error && error.name === "AbortError";
  const status = isTimeout ? 504 : 502;
  const detail = isTimeout
    ? "The frontend proxy timed out while waiting for the API upstream."
    : "The frontend proxy could not reach the API upstream.";
  const response =
    method === "HEAD"
      ? new NextResponse(null, {
          status,
          headers: NO_STORE_HEADERS,
        })
      : NextResponse.json(
          {
            error: isTimeout ? "upstream_timeout" : "upstream_unavailable",
            detail,
          },
          {
            status,
            headers: NO_STORE_HEADERS,
          },
        );
  return applyGuestSessionCookiesToResponse(response, request, session);
}

async function proxyRequest(
  request: NextRequest,
  paramsPromise: Promise<{ path: string[] }>,
): Promise<Response> {
  const { path } = await paramsPromise;
  const normalizedPath = `/${path.join("/")}`;
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("expect");
  const cookieAuthorization = getAuthorizationHeaderFromRequest(request);
  if (cookieAuthorization && !headers.has("authorization")) {
    headers.set("authorization", cookieAuthorization);
  }
  const method = request.method.toUpperCase();
  const hasAuthorization = headers.has("authorization");
  const session =
    !ENABLE_DEMO_AUTH && !hasAuthorization && routeRequiresGuestSession(normalizedPath)
      ? resolveGuestSession(request)
      : null;

  if (session) {
    applyGuestSessionToHeaders(request, headers, session, {
      ensureCsrfHeader: !["GET", "HEAD", "OPTIONS"].includes(method),
    });
  }

  if (!ENABLE_DEMO_AUTH) {
    headers.delete("x-demo-user");
    headers.delete("x-demo-role");
  } else if (hasAuthorization) {
    headers.delete("x-demo-user");
    headers.delete("x-demo-role");
  } else {
    if (!headers.has("x-demo-user")) {
      headers.set("x-demo-user", DEMO_USER_ID);
    }
    if (!headers.has("x-demo-role")) {
      headers.set("x-demo-role", DEMO_ROLE);
    }
  }

  const body =
    method === "GET" || method === "HEAD" ? undefined : await request.text();
  if (!body) {
    headers.delete("content-length");
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);
  let upstream: Response;
  try {
    upstream = await fetch(buildTargetUrl(path, request), {
      method,
      headers,
      body,
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (error) {
    return buildUpstreamErrorResponse(request, method, error, session);
  } finally {
    clearTimeout(timeout);
  }

  const responseHeaders = new Headers(upstream.headers);
  responseHeaders.delete("content-encoding");
  responseHeaders.delete("transfer-encoding");

  const response = new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
  return applyGuestSessionCookiesToResponse(response, request, session);
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, context.params);
}

export async function HEAD(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, context.params);
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, context.params);
}

export async function PUT(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, context.params);
}

export async function PATCH(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, context.params);
}

export async function DELETE(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, context.params);
}
