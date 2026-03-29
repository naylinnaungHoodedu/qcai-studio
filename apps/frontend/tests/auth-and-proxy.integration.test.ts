import assert from "node:assert/strict";
import test from "node:test";

import { NextRequest } from "next/server";

import { GET as authCallbackRoute } from "../src/app/auth/callback/route";
import { GET as authLoginRoute } from "../src/app/auth/login/route";
import { GET as authLogoutRoute } from "../src/app/auth/logout/route";
import { proxy } from "../src/proxy";
import {
  AUTH_RETURN_TO_COOKIE_NAME,
  AUTH_STATE_COOKIE_NAME,
  AUTH_TOKEN_COOKIE_NAME,
  AUTH_VERIFIER_COOKIE_NAME,
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
});

test("proxy adds nonce-based CSP without issuing guest cookies on public pages", async () => {
  const response = proxy(new NextRequest("https://qantumlearn.academy/"));

  const csp = response.headers.get("content-security-policy") ?? "";
  assert.match(csp, /script-src 'self' 'nonce-[^']+'/);
  assert.doesNotMatch(csp, /script-src[^;]*'unsafe-inline'/);
  assert.doesNotMatch(csp, /0\.0\.0\.0:3000/);
  assert.ok(response.headers.get("x-nonce"));
  assert.equal(response.cookies.get("qcai_guest_id"), undefined);
  assert.equal(response.cookies.get("qcai_guest_csrf"), undefined);
});

test("proxy bootstraps guest cookies for private account pages", async () => {
  const response = proxy(new NextRequest("https://qantumlearn.academy/account"));

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
