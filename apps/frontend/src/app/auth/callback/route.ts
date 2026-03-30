import { NextRequest, NextResponse } from "next/server";

import {
  AUTH_RETURN_TO_COOKIE_NAME,
  AUTH_STATE_COOKIE_NAME,
  AUTH_TOKEN_COOKIE_NAME,
  AUTH_VERIFIER_COOKIE_NAME,
  getAuth0Settings,
  isAuth0Configured,
  resolveAppOrigin,
  isSecureCookieRequest,
  sanitizeReturnTo,
} from "@/lib/auth";

function clearEphemeralCookies(response: NextResponse) {
  for (const name of [AUTH_STATE_COOKIE_NAME, AUTH_VERIFIER_COOKIE_NAME, AUTH_RETURN_TO_COOKIE_NAME]) {
    response.cookies.set({ name, value: "", path: "/", maxAge: 0 });
  }
}

function redirectToAccount(request: NextRequest, status: string) {
  return NextResponse.redirect(new URL(`/account?auth=${status}`, resolveAppOrigin(request)));
}

export async function GET(request: NextRequest) {
  const appOrigin = resolveAppOrigin(request);
  if (!isAuth0Configured()) {
    return redirectToAccount(request, "unavailable");
  }
  const auth0 = getAuth0Settings();

  const code = request.nextUrl.searchParams.get("code");
  const state = request.nextUrl.searchParams.get("state");
  const expectedState = request.cookies.get(AUTH_STATE_COOKIE_NAME)?.value;
  const verifier = request.cookies.get(AUTH_VERIFIER_COOKIE_NAME)?.value;
  const returnTo = sanitizeReturnTo(request.cookies.get(AUTH_RETURN_TO_COOKIE_NAME)?.value);

  if (!code || !state || !expectedState || state !== expectedState || !verifier) {
    const response = redirectToAccount(request, "failed");
    clearEphemeralCookies(response);
    return response;
  }

  const tokenResponse = await fetch(`https://${auth0.domain}/oauth/token`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      grant_type: "authorization_code",
      client_id: auth0.clientId,
      code_verifier: verifier,
      code,
      redirect_uri: `${appOrigin}/auth/callback`,
      audience: auth0.audience,
    }),
    cache: "no-store",
  });

  if (!tokenResponse.ok) {
    const response = redirectToAccount(request, "failed");
    clearEphemeralCookies(response);
    return response;
  }

  const payload = (await tokenResponse.json()) as { access_token?: string; expires_in?: number };
  if (!payload.access_token) {
    const response = redirectToAccount(request, "failed");
    clearEphemeralCookies(response);
    return response;
  }

  const secure = isSecureCookieRequest(request);
  const redirectUrl = new URL(returnTo, appOrigin);
  redirectUrl.searchParams.set("auth", "signed-in");
  const response = NextResponse.redirect(redirectUrl);
  response.cookies.set({
    name: AUTH_TOKEN_COOKIE_NAME,
    value: payload.access_token,
    httpOnly: true,
    sameSite: "lax",
    secure,
    path: "/",
    maxAge: payload.expires_in ?? 3600,
  });
  clearEphemeralCookies(response);
  return response;
}
