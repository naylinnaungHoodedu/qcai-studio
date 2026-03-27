import { createHash, randomBytes } from "crypto";

import { NextRequest, NextResponse } from "next/server";

import {
  AUTH0_IS_CONFIGURED,
  AUTH_RETURN_TO_COOKIE_NAME,
  AUTH_STATE_COOKIE_NAME,
  AUTH_VERIFIER_COOKIE_NAME,
  buildAuth0AuthorizeUrl,
  isSecureCookieRequest,
  sanitizeReturnTo,
} from "@/lib/auth";

function toBase64Url(value: Buffer): string {
  return value.toString("base64url");
}

export async function GET(request: NextRequest) {
  if (!AUTH0_IS_CONFIGURED) {
    return NextResponse.redirect(new URL("/account?auth=unavailable", request.url));
  }

  const returnTo = sanitizeReturnTo(request.nextUrl.searchParams.get("returnTo"));
  const state = crypto.randomUUID();
  const verifier = toBase64Url(randomBytes(32));
  const challenge = toBase64Url(createHash("sha256").update(verifier).digest());
  const secure = isSecureCookieRequest(request);

  const response = NextResponse.redirect(
    buildAuth0AuthorizeUrl(request.nextUrl.origin, state, challenge),
  );
  response.cookies.set({
    name: AUTH_STATE_COOKIE_NAME,
    value: state,
    httpOnly: true,
    sameSite: "lax",
    secure,
    path: "/",
    maxAge: 600,
  });
  response.cookies.set({
    name: AUTH_VERIFIER_COOKIE_NAME,
    value: verifier,
    httpOnly: true,
    sameSite: "lax",
    secure,
    path: "/",
    maxAge: 600,
  });
  response.cookies.set({
    name: AUTH_RETURN_TO_COOKIE_NAME,
    value: returnTo,
    httpOnly: true,
    sameSite: "lax",
    secure,
    path: "/",
    maxAge: 600,
  });
  return response;
}
