import assert from "node:assert/strict";
import test from "node:test";

import { NextRequest, NextResponse } from "next/server";

import { GET as backendProxyGet } from "../src/app/api/backend/[...path]/route";
import { POST as backendProxyPost } from "../src/app/api/backend/[...path]/route";
import { GET as frontendHealthRoute } from "../src/app/health/route";
import { GET as frontendReadyRoute } from "../src/app/ready/route";
import { GET as authCallbackRoute } from "../src/app/auth/callback/route";
import { GET as authLoginRoute } from "../src/app/auth/login/route";
import { GET as authLogoutRoute } from "../src/app/auth/logout/route";
import { proxy } from "../src/proxy";
import {
  AUTH_CSRF_COOKIE_NAME,
  AUTH_RETURN_TO_COOKIE_NAME,
  AUTH_STATE_COOKIE_NAME,
  AUTH_TOKEN_COOKIE_NAME,
  AUTH_VERIFIER_COOKIE_NAME,
  LOCAL_AUTH_SESSION_COOKIE_NAME,
  resolveAppOrigin,
} from "../src/lib/auth";

const AUTH_ENV_KEYS = [
  "NEXT_PUBLIC_AUTH0_DOMAIN",
  "NEXT_PUBLIC_AUTH0_CLIENT_ID",
  "NEXT_PUBLIC_AUTH0_AUDIENCE",
  "NEXT_PUBLIC_AUTH0_SCOPE",
] as const;

function setAuthEnv() {
  process.env.NEXT_PUBLIC_AUTH0_DOMAIN = "qcai-demo.us.auth0.com";
  process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID = "client-123";
  process.env.NEXT_PUBLIC_AUTH0_AUDIENCE = "https://api.qantumlearn.academy";
  process.env.NEXT_PUBLIC_AUTH0_SCOPE = "openid profile email";
}

function clearAuthEnv() {
  for (const key of AUTH_ENV_KEYS) {
    delete process.env[key];
  }
}

function cookieHeader(cookies: Record<string, string>): string {
  return Object.entries(cookies)
    .map(([key, value]) => `${key}=${encodeURIComponent(value)}`)
    .join("; ");
}

function getSetCookieHeader(response: Response): string {
  const values = response.headers.getSetCookie?.() ?? [];
  return values.join("\n");
}

test("auth login route redirects to account when Auth0 is unavailable", async () => {
  clearAuthEnv();

  const response = await authLoginRoute(new NextRequest("https://qantumlearn.academy/auth/login"));

  assert.equal(response.status, 307);
  assert.equal(response.headers.get("location"), "https://qantumlearn.academy/account?auth=unavailable");
});

test("auth helpers fall back to the configured site origin when the request host is internal", () => {
  const request = new NextRequest("https://0.0.0.0:3000/auth/login");
  assert.equal(resolveAppOrigin(request), "https://qantumlearn.academy");
});

test("auth login route issues PKCE cookies and redirects to Auth0", async () => {
  setAuthEnv();

  const response = await authLoginRoute(
    new NextRequest("https://qantumlearn.academy/auth/login?returnTo=/dashboard"),
  );

  assert.equal(response.status, 307);
  const location = response.headers.get("location");
  assert.ok(location);
  assert.match(location, /^https:\/\/qcai-demo\.us\.auth0\.com\/authorize\?/);
  assert.equal(response.cookies.get(AUTH_RETURN_TO_COOKIE_NAME)?.value, "/dashboard");
  assert.ok(response.cookies.get(AUTH_STATE_COOKIE_NAME)?.value);
  assert.ok(response.cookies.get(AUTH_VERIFIER_COOKIE_NAME)?.value);
});

test("auth callback route exchanges code and stores the access token", async () => {
  setAuthEnv();
  const originalFetch = global.fetch;
  global.fetch = async (input, init) => {
    assert.match(String(input), /^https:\/\/qcai-demo\.us\.auth0\.com\/oauth\/token$/);
    assert.equal(init?.method, "POST");
    return new Response(JSON.stringify({ access_token: "token-abc", expires_in: 900 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  try {
    const request = new NextRequest(
      "https://qantumlearn.academy/auth/callback?code=auth-code&state=expected-state",
      {
        headers: {
          cookie: cookieHeader({
            [AUTH_STATE_COOKIE_NAME]: "expected-state",
            [AUTH_VERIFIER_COOKIE_NAME]: "verifier-token",
            [AUTH_RETURN_TO_COOKIE_NAME]: "/dashboard",
          }),
        },
      },
    );

    const response = await authCallbackRoute(request);

    assert.equal(response.status, 307);
    assert.equal(response.headers.get("location"), "https://qantumlearn.academy/dashboard?auth=signed-in");
    assert.equal(response.cookies.get(AUTH_TOKEN_COOKIE_NAME)?.value, "token-abc");
    const setCookie = getSetCookieHeader(response);
    assert.match(setCookie, new RegExp(`${AUTH_STATE_COOKIE_NAME}=;`));
    assert.match(setCookie, new RegExp(`${AUTH_VERIFIER_COOKIE_NAME}=;`));
  } finally {
    global.fetch = originalFetch;
  }
});

test("auth callback route fails closed when state validation breaks", async () => {
  setAuthEnv();

  const response = await authCallbackRoute(
    new NextRequest("https://qantumlearn.academy/auth/callback?code=auth-code&state=wrong-state", {
      headers: {
        cookie: cookieHeader({
          [AUTH_STATE_COOKIE_NAME]: "expected-state",
          [AUTH_VERIFIER_COOKIE_NAME]: "verifier-token",
          [AUTH_RETURN_TO_COOKIE_NAME]: "/dashboard",
        }),
      },
    }),
  );

  assert.equal(response.status, 307);
  assert.equal(response.headers.get("location"), "https://qantumlearn.academy/account?auth=failed");
});

test("auth logout route clears cookies and redirects to Auth0 logout", async () => {
  setAuthEnv();

  const response = await authLogoutRoute(new NextRequest("https://qantumlearn.academy/auth/logout"));

  assert.equal(response.status, 307);
  assert.match(
    response.headers.get("location") ?? "",
    /^https:\/\/qcai-demo\.us\.auth0\.com\/v2\/logout\?/,
  );
  const setCookie = getSetCookieHeader(response);
  assert.match(setCookie, new RegExp(`${AUTH_TOKEN_COOKIE_NAME}=;`));
  assert.match(setCookie, new RegExp(`${AUTH_STATE_COOKIE_NAME}=;`));
  assert.match(setCookie, new RegExp(`${LOCAL_AUTH_SESSION_COOKIE_NAME}=;`));
  assert.match(setCookie, new RegExp(`${AUTH_CSRF_COOKIE_NAME}=;`));
});

test("proxy adds nonce-based CSP without issuing guest cookies on public pages", async () => {
  const response = proxy(new NextRequest("https://qantumlearn.academy/"));

  const csp = response.headers.get("content-security-policy") ?? "";
  assert.match(csp, /script-src 'self' 'nonce-[^']+'/);
  assert.doesNotMatch(csp, /script-src[^;]*'unsafe-inline'/);
  assert.match(csp, /style-src 'self'/);
  assert.match(csp, /style-src-elem 'self'/);
  assert.match(csp, /style-src-attr 'unsafe-inline'/);
  assert.doesNotMatch(csp, /0\.0\.0\.0:3000/);
  assert.equal(response.headers.get("cross-origin-opener-policy"), "same-origin");
  assert.equal(response.headers.get("cross-origin-resource-policy"), "same-site");
  assert.ok(response.headers.get("x-nonce"));
  assert.equal(response.cookies.get("qcai_guest_id"), undefined);
  assert.equal(response.cookies.get("qcai_guest_csrf"), undefined);
});

test("proxy bootstraps guest cookies for private account pages", async () => {
  const response = proxy(new NextRequest("https://qantumlearn.academy/account"));

  assert.match(response.cookies.get("qcai_guest_id")?.value ?? "", /^guest-/);
  assert.ok(response.cookies.get("qcai_guest_csrf")?.value);
});

test("proxy also bootstraps guest cookies for lesson pages so media assets can stream", async () => {
  const response = proxy(
    new NextRequest("https://qantumlearn.academy/lessons/nisq-reality-overview"),
  );

  assert.match(response.cookies.get("qcai_guest_id")?.value ?? "", /^guest-/);
  assert.ok(response.cookies.get("qcai_guest_csrf")?.value);
});

test("proxy preserves an existing guest session without reissuing cookies", async () => {
  const response = proxy(
    new NextRequest("https://qantumlearn.academy/account", {
      headers: {
        cookie: cookieHeader({
          qcai_guest_id: "guest-123e4567-e89b-12d3-a456-426614174000",
          qcai_guest_csrf: "3b1f2f40-7132-4778-8df5-44c1c5cf6bb0",
        }),
      },
    }),
  );

  assert.equal(response.cookies.get("qcai_guest_id"), undefined);
  assert.equal(response.cookies.get("qcai_guest_csrf"), undefined);
  assert.ok(response.headers.get("x-nonce"));
});

test("asset proxy full GET uses a plain streamed response when guest cookies already exist", async () => {
  const originalFetch = global.fetch;
  const payload = new TextEncoder().encode("video-stream-payload");
  global.fetch = async () =>
    new Response(payload, {
      status: 200,
      headers: {
        "Content-Type": "video/mp4",
        "Content-Length": String(payload.byteLength),
        "Accept-Ranges": "bytes",
      },
    });

  try {
    const response = await backendProxyGet(
      new NextRequest("https://qantumlearn.academy/api/backend/source-assets/by-id/industry-use-cases", {
        headers: {
          cookie: cookieHeader({
            qcai_guest_id: "guest-123e4567-e89b-12d3-a456-426614174000",
            qcai_guest_csrf: "3b1f2f40-7132-4778-8df5-44c1c5cf6bb0",
          }),
        },
      }),
      {
        params: Promise.resolve({ path: ["source-assets", "by-id", "industry-use-cases"] }),
      },
    );

    assert.equal(response.status, 200);
    assert.equal(response.headers.get("content-type"), "video/mp4");
    assert.equal(response.headers.get("content-length"), String(payload.byteLength));
    assert.equal(response.headers.get("accept-ranges"), "bytes");
    assert.equal(response.headers.get("set-cookie"), null);
    assert.equal(response instanceof NextResponse, false);
  } finally {
    global.fetch = originalFetch;
  }
});

test("backend proxy returns a structured bad-gateway response when the upstream is unreachable", async () => {
  const originalFetch = global.fetch;
  global.fetch = async () => {
    throw new TypeError("fetch failed");
  };

  try {
    const response = await backendProxyGet(
      new NextRequest("https://qantumlearn.academy/api/backend/health"),
      {
        params: Promise.resolve({ path: ["health"] }),
      },
    );
    const payload = await response.json();

    assert.equal(response.status, 502);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(payload.error, "upstream_unavailable");
  } finally {
    global.fetch = originalFetch;
  }
});

test("asset proxy retries one transient upstream 500 before returning the media response", async () => {
  const originalFetch = global.fetch;
  const payload = new TextEncoder().encode("video-range-payload");
  let attempts = 0;
  global.fetch = async () => {
    attempts += 1;
    if (attempts === 1) {
      return new Response(JSON.stringify({ detail: "temporary media failure" }), {
        status: 500,
        headers: {
          "Content-Type": "application/json",
        },
      });
    }
    return new Response(payload, {
      status: 206,
      headers: {
        "Content-Type": "video/mp4",
        "Content-Length": String(payload.byteLength),
        "Content-Range": `bytes 0-${payload.byteLength - 1}/${payload.byteLength}`,
        "Accept-Ranges": "bytes",
      },
    });
  };

  try {
    const response = await backendProxyGet(
      new NextRequest("https://qantumlearn.academy/api/backend/source-assets/by-id/industry-use-cases", {
        headers: {
          cookie: cookieHeader({
            qcai_guest_id: "guest-123e4567-e89b-12d3-a456-426614174000",
            qcai_guest_csrf: "3b1f2f40-7132-4778-8df5-44c1c5cf6bb0",
          }),
        },
      }),
      {
        params: Promise.resolve({ path: ["source-assets", "by-id", "industry-use-cases"] }),
      },
    );

    assert.equal(attempts, 2);
    assert.equal(response.status, 206);
    assert.equal(response.headers.get("content-type"), "video/mp4");
    assert.equal(response.headers.get("accept-ranges"), "bytes");
  } finally {
    global.fetch = originalFetch;
  }
});

test("public web-vitals proxy retries one transient upstream timeout before returning accepted", async () => {
  const originalFetch = global.fetch;
  let attempts = 0;
  global.fetch = async () => {
    attempts += 1;
    if (attempts === 1) {
      const error = new Error("timed out");
      error.name = "AbortError";
      throw error;
    }
    return Response.json({ status: "accepted" });
  };

  try {
    const response = await backendProxyPost(
      new NextRequest("https://qantumlearn.academy/api/backend/analytics/public-web-vitals", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          origin: "https://qantumlearn.academy",
        },
        body: JSON.stringify({
          metric_id: "vital-retry",
          metric_name: "LCP",
          path: "/",
          value: 1234,
          rating: "good",
        }),
      }),
      {
        params: Promise.resolve({ path: ["analytics", "public-web-vitals"] }),
      },
    );
    const payload = await response.json();

    assert.equal(attempts, 2);
    assert.equal(response.status, 200);
    assert.equal(payload.status, "accepted");
  } finally {
    global.fetch = originalFetch;
  }
});

test("frontend health route returns a no-store operational payload", async () => {
  const response = frontendHealthRoute();
  const payload = await response.json();

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(payload.status, "ok");
  assert.equal(payload.app, "QC+AI Studio Frontend");
});

test("frontend ready route fails closed when the API base URL is missing", async () => {
  const originalApiBaseUrl = process.env.API_BASE_URL;
  const originalPublicApiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  delete process.env.API_BASE_URL;
  delete process.env.NEXT_PUBLIC_API_BASE_URL;

  try {
    const response = await frontendReadyRoute();
    const payload = await response.json();

    assert.equal(response.status, 503);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(payload.status, "degraded");
  } finally {
    if (originalApiBaseUrl == null) {
      delete process.env.API_BASE_URL;
    } else {
      process.env.API_BASE_URL = originalApiBaseUrl;
    }
    if (originalPublicApiBaseUrl == null) {
      delete process.env.NEXT_PUBLIC_API_BASE_URL;
    } else {
      process.env.NEXT_PUBLIC_API_BASE_URL = originalPublicApiBaseUrl;
    }
  }
});

test("frontend ready route degrades when the backend readiness check cannot be reached", async () => {
  const originalApiBaseUrl = process.env.API_BASE_URL;
  const originalFetch = global.fetch;
  process.env.API_BASE_URL = "https://api.qantumlearn.academy";
  global.fetch = async () => {
    throw new TypeError("fetch failed");
  };

  try {
    const response = await frontendReadyRoute();
    const payload = await response.json();

    assert.equal(response.status, 503);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(payload.status, "degraded");
    assert.equal(payload.api_origin, "https://api.qantumlearn.academy");
    assert.equal(payload.api_status, "unavailable");
  } finally {
    if (originalApiBaseUrl == null) {
      delete process.env.API_BASE_URL;
    } else {
      process.env.API_BASE_URL = originalApiBaseUrl;
    }
    global.fetch = originalFetch;
  }
});

test("frontend ready route reports ready when the backend readiness check succeeds", async () => {
  const originalApiBaseUrl = process.env.API_BASE_URL;
  const originalFetch = global.fetch;
  process.env.API_BASE_URL = "https://api.qantumlearn.academy";
  global.fetch = async (input, init) => {
    assert.equal(String(input), "https://api.qantumlearn.academy/ready");
    assert.equal(init?.method, "GET");
    return new Response(JSON.stringify({ status: "ready", lessons: 12, source_assets: 24 }), {
      status: 200,
      headers: {
        "Content-Type": "application/json",
      },
    });
  };

  try {
    const response = await frontendReadyRoute();
    const payload = await response.json();

    assert.equal(response.status, 200);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(payload.status, "ready");
    assert.equal(payload.api_origin, "https://api.qantumlearn.academy");
    assert.equal(payload.api_status, "ready");
  } finally {
    if (originalApiBaseUrl == null) {
      delete process.env.API_BASE_URL;
    } else {
      process.env.API_BASE_URL = originalApiBaseUrl;
    }
    global.fetch = originalFetch;
  }
});

test("frontend ready route retries one transient timeout before returning ready", async () => {
  const originalApiBaseUrl = process.env.API_BASE_URL;
  const originalFetch = global.fetch;
  let attempts = 0;
  process.env.API_BASE_URL = "https://api.qantumlearn.academy";
  global.fetch = async (input, init) => {
    attempts += 1;
    assert.equal(String(input), "https://api.qantumlearn.academy/ready");
    assert.equal(init?.method, "GET");
    if (attempts === 1) {
      const error = new Error("timed out");
      error.name = "AbortError";
      throw error;
    }
    return new Response(JSON.stringify({ status: "ready", lessons: 12, source_assets: 24 }), {
      status: 200,
      headers: {
        "Content-Type": "application/json",
      },
    });
  };

  try {
    const response = await frontendReadyRoute();
    const payload = await response.json();

    assert.equal(attempts, 2);
    assert.equal(response.status, 200);
    assert.equal(payload.status, "ready");
    assert.equal(payload.api_status, "ready");
  } finally {
    if (originalApiBaseUrl == null) {
      delete process.env.API_BASE_URL;
    } else {
      process.env.API_BASE_URL = originalApiBaseUrl;
    }
    global.fetch = originalFetch;
  }
});
