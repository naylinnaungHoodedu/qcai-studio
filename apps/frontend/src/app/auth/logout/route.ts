import { NextRequest, NextResponse } from "next/server";

import {
  AUTH0_IS_CONFIGURED,
  AUTH_RETURN_TO_COOKIE_NAME,
  AUTH_STATE_COOKIE_NAME,
  AUTH_TOKEN_COOKIE_NAME,
  AUTH_VERIFIER_COOKIE_NAME,
  buildAuth0LogoutUrl,
} from "@/lib/auth";

export async function GET(request: NextRequest) {
  const target = AUTH0_IS_CONFIGURED
    ? buildAuth0LogoutUrl(request.nextUrl.origin)
    : `${request.nextUrl.origin}/account?auth=signed-out`;
  const response = NextResponse.redirect(target);
  for (const name of [
    AUTH_TOKEN_COOKIE_NAME,
    AUTH_STATE_COOKIE_NAME,
    AUTH_VERIFIER_COOKIE_NAME,
    AUTH_RETURN_TO_COOKIE_NAME,
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
