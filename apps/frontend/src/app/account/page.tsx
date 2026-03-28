import type { Metadata } from "next";
import Link from "next/link";

import { isAuth0Configured } from "@/lib/auth";
import { fetchMe } from "@/lib/api";
import { buildPageMetadata } from "@/lib/metadata";

export const metadata: Metadata = buildPageMetadata({
  title: "Account",
  description:
    "Review the current guest or authenticated learner session and access the Auth0 sign-in path when client configuration is available.",
  path: "/account",
  index: false,
});

type AccountPageProps = {
  searchParams: Promise<{ auth?: string }>;
};

function describeAuthState(status: string | null): string | null {
  if (status === "signed-in") {
    return "You are now connected to an authenticated account. Future activity in this browser will use that identity.";
  }
  if (status === "signed-out") {
    return "You signed out of the authenticated account and are back on a local guest-session path.";
  }
  if (status === "failed") {
    return "Auth0 login did not complete cleanly. Retry the sign-in flow or continue as a guest.";
  }
  if (status === "unavailable") {
    return "This deployment does not currently expose client-side Auth0 configuration, so sign-in is unavailable here.";
  }
  return null;
}

function isGuestUser(userId: string | undefined): boolean {
  return Boolean(userId && (userId.startsWith("guest-") || userId === "demo-learner"));
}

export default async function AccountPage({ searchParams }: AccountPageProps) {
  const { auth } = await searchParams;
  const statusMessage = describeAuthState(auth ?? null);
  const user = await fetchMe().catch(() => null);
  const guestUser = isGuestUser(user?.user_id);
  const auth0Configured = isAuth0Configured();

  return (
    <div className="page-stack">
      <section className="section-block">
        <p className="eyebrow">Account access</p>
        <h1>Guest sessions and authenticated access</h1>
        <p className="hero-text">
          Guest activity works immediately in the current browser, but it does not follow you across devices.
          Authenticated access is the path to persistent identity when Auth0 client configuration is available.
        </p>
      </section>

      <div className="two-column-grid">
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Current session</p>
              <h2>Status</h2>
            </div>
          </div>
          {statusMessage ? <p className="muted">{statusMessage}</p> : null}
          {user ? (
            <div className="stack">
              <article className="citation-card">
                <strong>{guestUser ? "Guest session" : "Authenticated account"}</strong>
                <p className="muted">{guestUser ? "Device-local identity" : user.email ?? user.user_id}</p>
                <p>
                  {guestUser
                    ? "Notes, progress, quizzes, and other learner activity are tied to this browser session and will not automatically sync elsewhere."
                    : "Private learner data can now resolve against the authenticated identity for this browser session."}
                </p>
              </article>
              <div className="button-row">
                {guestUser ? (
                  <Link className="secondary-button" href="/dashboard">
                    Continue as guest
                  </Link>
                ) : (
                  <a className="secondary-button" href="/auth/logout">
                    Sign out
                  </a>
                )}
              </div>
            </div>
          ) : (
            <p className="muted">The account endpoint could not be loaded for this request.</p>
          )}
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Auth0</p>
              <h2>Sign in</h2>
            </div>
          </div>
          <p className="muted">
            The backend already accepts Auth0-issued bearer tokens. This UI now exposes the account entry point instead of hiding the authenticated path behind backend-only wiring.
          </p>
          <div className="stack">
            {auth0Configured ? (
              <div className="button-row">
                <a className="primary-button" href="/auth/login?returnTo=/account">
                  Sign in with Auth0
                </a>
                <a className="secondary-button" href="/auth/logout">
                  Clear auth session
                </a>
              </div>
            ) : (
              <div className="stack">
                <button className="primary-button" disabled type="button">
                  Sign in with Auth0
                </button>
                <p className="muted">
                  Client-side Auth0 variables are not configured for this deployment yet, so the authenticated login button is visible but inactive.
                </p>
              </div>
            )}
            <article className="citation-card">
              <strong>What changes after sign-in</strong>
              <p>
                Authenticated API requests can resolve against a stable identity instead of a guest cookie, which is the foundation for cross-browser and cross-device continuity.
              </p>
            </article>
          </div>
        </section>
      </div>
    </div>
  );
}
