import { NextRequest, NextResponse } from "next/server";

import {
  AUTH_CSRF_COOKIE_NAME,
  AUTH_RETURN_TO_COOKIE_NAME,
  AUTH_STATE_COOKIE_NAME,
  AUTH_TOKEN_COOKIE_NAME,
  AUTH_VERIFIER_COOKIE_NAME,
  LOCAL_AUTH_SESSION_COOKIE_NAME,
  buildAuth0LogoutUrl,
  isAuth0Configured,
  resolveAppOrigin,
} from "@/lib/auth";

export async function GET(request: NextRequest) {
  const appOrigin = resolveAppOrigin(request);
  const target = isAuth0Configured()
    ? buildAuth0LogoutUrl(appOrigin)
    : `${appOrigin}/account?auth=signed-out`;
  const response = NextResponse.redirect(target);
  for (const name of [
    AUTH_TOKEN_COOKIE_NAME,
    AUTH_STATE_COOKIE_NAME,
    AUTH_VERIFIER_COOKIE_NAME,
    AUTH_RETURN_TO_COOKIE_NAME,
    LOCAL_AUTH_SESSION_COOKIE_NAME,
    AUTH_CSRF_COOKIE_NAME,
  ]) {
    response.cookies.set({
      name,
      value: "",
      path: "/",
      maxAge: 0,
    });
  }
  return response;
}
