import type { NextRequest } from "next/server";

export const AUTH_TOKEN_COOKIE_NAME = "qcai_auth_token";
export const AUTH_STATE_COOKIE_NAME = "qcai_auth_state";
export const AUTH_VERIFIER_COOKIE_NAME = "qcai_auth_verifier";
export const AUTH_RETURN_TO_COOKIE_NAME = "qcai_auth_return_to";

export type Auth0Settings = {
  domain: string;
  clientId: string;
  audience: string;
  scope: string;
  isConfigured: boolean;
};

export function getAuth0Settings(): Auth0Settings {
  const domain = (process.env.NEXT_PUBLIC_AUTH0_DOMAIN || "")
    .replace(/^https?:\/\//, "")
    .replace(/\/$/, "");
  const clientId = process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID || "";
  const audience = process.env.NEXT_PUBLIC_AUTH0_AUDIENCE || "";
  const scope = process.env.NEXT_PUBLIC_AUTH0_SCOPE || "openid profile email";
  return {
    domain,
    clientId,
    audience,
    scope,
    isConfigured: Boolean(domain && clientId && audience),
  };
}

export function isAuth0Configured(): boolean {
  return getAuth0Settings().isConfigured;
}

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
  const auth0 = getAuth0Settings();
  const url = new URL(`https://${auth0.domain}/authorize`);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", auth0.clientId);
  url.searchParams.set("redirect_uri", `${origin}/auth/callback`);
  url.searchParams.set("scope", auth0.scope);
  url.searchParams.set("audience", auth0.audience);
  url.searchParams.set("state", state);
  url.searchParams.set("code_challenge", challenge);
  url.searchParams.set("code_challenge_method", "S256");
  return url.toString();
}

export function buildAuth0LogoutUrl(origin: string): string {
  const auth0 = getAuth0Settings();
  const url = new URL(`https://${auth0.domain}/v2/logout`);
  url.searchParams.set("client_id", auth0.clientId);
  url.searchParams.set("returnTo", `${origin}/account?auth=signed-out`);
  return url.toString();
}
