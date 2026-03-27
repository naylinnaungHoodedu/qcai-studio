import { NextRequest } from "next/server";

const API_BASE_URL =
  process.env.API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://127.0.0.1:8000";
const DEMO_USER_ID = "demo-learner";
const DEMO_ROLE = "learner";

function buildTargetUrl(pathParts: string[], request: NextRequest): string {
  const base = API_BASE_URL.replace(/\/$/, "");
  const path = pathParts.join("/");
  const url = new URL(`${base}/${path}`);
  url.search = request.nextUrl.search;
  return url.toString();
}

async function proxyRequest(
  request: NextRequest,
  paramsPromise: Promise<{ path: string[] }>,
): Promise<Response> {
  const { path } = await paramsPromise;
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("expect");
  if (headers.has("authorization")) {
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

  const method = request.method.toUpperCase();
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

  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
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
