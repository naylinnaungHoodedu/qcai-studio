import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const NO_STORE_HEADERS = {
  "Cache-Control": "no-store",
};

function resolveApiBaseUrl(): string | null {
  return process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || null;
}

export function GET() {
  const apiBaseUrl = resolveApiBaseUrl();
  if (!apiBaseUrl) {
    return NextResponse.json(
      {
        status: "degraded",
        detail: "API base URL is not configured.",
      },
      {
        status: 503,
        headers: NO_STORE_HEADERS,
      },
    );
  }

  try {
    const parsed = new URL(apiBaseUrl);
    return NextResponse.json(
      {
        status: "ready",
        api_origin: parsed.origin,
      },
      {
        headers: NO_STORE_HEADERS,
      },
    );
  } catch {
    return NextResponse.json(
      {
        status: "degraded",
        detail: "API base URL is invalid.",
      },
      {
        status: 503,
        headers: NO_STORE_HEADERS,
      },
    );
  }
}

export function HEAD() {
  const apiBaseUrl = resolveApiBaseUrl();
  try {
    if (!apiBaseUrl) {
      throw new Error("missing API base URL");
    }
    new URL(apiBaseUrl);
    return new NextResponse(null, {
      status: 200,
      headers: NO_STORE_HEADERS,
    });
  } catch {
    return new NextResponse(null, {
      status: 503,
      headers: NO_STORE_HEADERS,
    });
  }
}
