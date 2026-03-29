import { NextRequest, NextResponse } from "next/server";

import { getAuthorizationHeaderFromRequest } from "@/lib/auth";
import {
  applyGuestSessionToHeaders,
  resolveGuestSession,
  routeRequiresGuestSession,
  setGuestSessionCookies,
} from "@/lib/guest-session";

const API_BASE_URL =
  process.env.API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://127.0.0.1:8000";
const DEMO_USER_ID = "demo-learner";
const DEMO_ROLE = "learner";

function isDemoAuthEnabled(): boolean {
  return process.env.ENABLE_DEMO_AUTH != null
    ? process.env.ENABLE_DEMO_AUTH === "true"
    : process.env.NEXT_PUBLIC_ENABLE_DEMO_AUTH != null
      ? process.env.NEXT_PUBLIC_ENABLE_DEMO_AUTH === "true"
      : process.env.NODE_ENV !== "production";
}

function buildTargetUrl(pathParts: string[], request: NextRequest): string {
  const base = API_BASE_URL.replace(/\/$/, "");
  const path = pathParts.join("/");
  const url = new URL(`${base}/${path}`);
  url.search = request.nextUrl.search;
  return url.toString();
}

function isSourceAssetRequest(pathParts: string[]): boolean {
  return pathParts[0] === "source-assets";
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
  const demoAuthEnabled = isDemoAuthEnabled();
  const hasAuthorization = headers.has("authorization");
  const session =
    !demoAuthEnabled && !hasAuthorization && routeRequiresGuestSession(normalizedPath)
      ? resolveGuestSession(request)
      : null;

  if (session) {
    applyGuestSessionToHeaders(request, headers, session, {
      ensureCsrfHeader: !["GET", "HEAD", "OPTIONS"].includes(method),
    });
  }

  // Source assets (videos, PDFs) must be proxied — NOT redirected — so that
  // authentication cookies scoped to qantumlearn.academy are forwarded as
  // server-side headers to api.qantumlearn.academy.  A browser-side redirect
  // would lose those cookies, sending an unauthenticated request that causes
  // the backend to return 401 (which the global exception handler re-maps to
  // 500, making videos fail with a playback error in the UI).
  //
  // For range-request video streaming we forward the Range header and echo
  // back the 206 Partial Content response so the HTML5 video element can seek.

  if (!demoAuthEnabled) {
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

  const upstream = await fetch(buildTargetUrl(path, request), {
    method,
    headers,
    body,
    cache: "no-store",
  });

  const responseHeaders = new Headers(upstream.headers);
  responseHeaders.delete("content-encoding");
  responseHeaders.delete("transfer-encoding");

  const response = new NextResponse(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
  if (session) {
    setGuestSessionCookies(response, request, session);
  }
  return response;
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
