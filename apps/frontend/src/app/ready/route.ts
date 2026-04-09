import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
const API_READY_TIMEOUT_MS = 6500;
const API_READY_RETRY_DELAY_MS = 200;
const API_READY_MAX_ATTEMPTS = 2;

const NO_STORE_HEADERS = {
  "Cache-Control": "no-store",
};

function resolveApiBaseUrl(): string | null {
  return process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || null;
}

function buildApiReadyUrl(apiBaseUrl: string): URL {
  const parsed = new URL(apiBaseUrl);
  const normalizedPath = parsed.pathname === "/" ? "" : parsed.pathname.replace(/\/+$/, "");
  parsed.pathname = `${normalizedPath}/ready` || "/ready";
  parsed.search = "";
  parsed.hash = "";
  return parsed;
}

async function probeApiReadiness(apiBaseUrl: string): Promise<{
  apiOrigin: string;
  detail?: string;
  payload?: Record<string, unknown>;
  status: number;
}> {
  const readyUrl = buildApiReadyUrl(apiBaseUrl);
  let transientDetail = "API readiness check could not reach the backend.";

  for (let attempt = 1; attempt <= API_READY_MAX_ATTEMPTS; attempt += 1) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), API_READY_TIMEOUT_MS);

    try {
      const response = await fetch(readyUrl, {
        method: "GET",
        cache: "no-store",
        headers: {
          Accept: "application/json",
        },
        signal: controller.signal,
      });
      let payload: Record<string, unknown> | undefined;
      try {
        payload = (await response.json()) as Record<string, unknown>;
      } catch {
        payload = undefined;
      }

      if (!response.ok || payload?.status !== "ready") {
        return {
          apiOrigin: readyUrl.origin,
          detail:
            typeof payload?.status === "string"
              ? `API readiness check returned ${payload.status}.`
              : `API readiness check returned HTTP ${response.status}.`,
          payload,
          status: 503,
        };
      }

      return {
        apiOrigin: readyUrl.origin,
        payload,
        status: 200,
      };
    } catch (error) {
      transientDetail =
        error instanceof Error && error.name === "AbortError"
          ? "API readiness check timed out."
          : "API readiness check could not reach the backend.";
      if (attempt === API_READY_MAX_ATTEMPTS) {
        return {
          apiOrigin: readyUrl.origin,
          detail: transientDetail,
          status: 503,
        };
      }
      await new Promise((resolve) => setTimeout(resolve, API_READY_RETRY_DELAY_MS));
    } finally {
      clearTimeout(timeout);
    }
  }

  return {
    apiOrigin: readyUrl.origin,
    detail: transientDetail,
    status: 503,
  };
}

async function buildReadinessResponse() {
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
    const { apiOrigin, detail, payload, status } = await probeApiReadiness(apiBaseUrl);
    if (status !== 200) {
      return NextResponse.json(
        {
          status: "degraded",
          detail,
          api_origin: apiOrigin,
          api_status: payload?.status ?? "unavailable",
        },
        {
          status,
          headers: NO_STORE_HEADERS,
        },
      );
    }

    return NextResponse.json(
      {
        status: "ready",
        api_origin: apiOrigin,
        api_status: payload?.status ?? "ready",
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

export async function GET() {
  return buildReadinessResponse();
}

export async function HEAD() {
  const apiBaseUrl = resolveApiBaseUrl();
  try {
    if (!apiBaseUrl) {
      throw new Error("missing API base URL");
    }
    new URL(apiBaseUrl);
  } catch {
    return new NextResponse(null, {
      status: 503,
      headers: NO_STORE_HEADERS,
    });
  }

  const result = await probeApiReadiness(apiBaseUrl);
  return new NextResponse(null, {
    status: result.status,
    headers: NO_STORE_HEADERS,
  });
}
