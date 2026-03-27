import type { NextRequest } from "next/server";

export const AUTH_TOKEN_COOKIE_NAME = "qcai_auth_token";
export const AUTH_STATE_COOKIE_NAME = "qcai_auth_state";
export const AUTH_VERIFIER_COOKIE_NAME = "qcai_auth_verifier";
export const AUTH_RETURN_TO_COOKIE_NAME = "qcai_auth_return_to";

export const AUTH0_DOMAIN = (process.env.NEXT_PUBLIC_AUTH0_DOMAIN || "")
  .replace(/^https?:\/\//, "")
  .replace(/\/$/, "");
export const AUTH0_CLIENT_ID = process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID || "";
export const AUTH0_AUDIENCE = process.env.NEXT_PUBLIC_AUTH0_AUDIENCE || "";
export const AUTH0_SCOPE = process.env.NEXT_PUBLIC_AUTH0_SCOPE || "openid profile email";
export const AUTH0_IS_CONFIGURED = Boolean(AUTH0_DOMAIN && AUTH0_CLIENT_ID && AUTH0_AUDIENCE);

export function sanitizeReturnTo(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) {
    return "/account";
  }
  return value;
}

export function isSecureCookieRequest(request: NextRequest): boolean {
  return request.nextUrl.protocol === "https:" || process.env.NODE_ENV === "production";
}

export function getAuthorizationHeaderFromRequest(
  request: Pick<NextRequest, "cookies">,
): string | null {
  const token = request.cookies.get(AUTH_TOKEN_COOKIE_NAME)?.value?.trim();
  return token ? `Bearer ${token}` : null;
}

export function buildAuth0AuthorizeUrl(origin: string, state: string, challenge: string): string {
  const url = new URL(`https://${AUTH0_DOMAIN}/authorize`);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", AUTH0_CLIENT_ID);
  url.searchParams.set("redirect_uri", `${origin}/auth/callback`);
  url.searchParams.set("scope", AUTH0_SCOPE);
  url.searchParams.set("audience", AUTH0_AUDIENCE);
  url.searchParams.set("state", state);
  url.searchParams.set("code_challenge", challenge);
  url.searchParams.set("code_challenge_method", "S256");
  return url.toString();
}

export function buildAuth0LogoutUrl(origin: string): string {
  const url = new URL(`https://${AUTH0_DOMAIN}/v2/logout`);
  url.searchParams.set("client_id", AUTH0_CLIENT_ID);
  url.searchParams.set("returnTo", `${origin}/account?auth=signed-out`);
  return url.toString();
}
