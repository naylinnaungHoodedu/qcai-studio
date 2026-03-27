import { NextRequest, NextResponse } from "next/server";

import {
  applyGuestSessionToHeaders,
  resolveGuestSession,
  setGuestSessionCookies,
} from "@/lib/guest-session";

export function proxy(request: NextRequest) {
  const session = resolveGuestSession(request);
  if (!session.createdGuestId && !session.createdGuestCsrf) {
    return NextResponse.next();
  }

  const requestHeaders = new Headers(request.headers);
  applyGuestSessionToHeaders(request, requestHeaders, session);

  const response = NextResponse.next({
    request: {
      headers: requestHeaders,
    },
  });
  setGuestSessionCookies(response, request, session);
  return response;
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/projects/:path*",
  ],
};
