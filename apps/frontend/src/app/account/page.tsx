import type { Metadata } from "next";

import { AccountConsole } from "@/components/account-console";
import { isAuth0Configured } from "@/lib/auth";
import { fetchMe } from "@/lib/api";
import { buildPageMetadata } from "@/lib/metadata";


export const metadata: Metadata = buildPageMetadata({
  title: "Account Access",
  description:
    "Create a local QC+AI Studio account, sign in, sign out, inspect the current session, or delete the active user account.",
  path: "/account",
  index: false,
});

type AccountPageProps = {
  searchParams: Promise<{ auth?: string }>;
};

function describeAuthState(status: string | null): string | null {
  if (status === "signed-in") {
    return "You are now connected to an authenticated account session.";
  }
  if (status === "signed-out") {
    return "The current account session was signed out.";
  }
  if (status === "failed") {
    return "The external sign-in flow did not complete cleanly.";
  }
  if (status === "unavailable") {
    return "This deployment is using the built-in account system because client-side Auth0 configuration is unavailable here.";
  }
  return null;
}

export default async function AccountPage({ searchParams }: AccountPageProps) {
  const { auth } = await searchParams;
  const statusMessage = describeAuthState(auth ?? null);
  const user = await fetchMe().catch(() => null);

  return (
    <div className="page-stack">
      <section className="section-block">
        <p className="eyebrow">Account access</p>
        <h1>Create, sign in, sign out, and delete user accounts without leaving the live platform.</h1>
        <p className="hero-text">
          QC+AI Studio now supports a first-party user account system in addition to the guest path. Guest study
          remains available immediately, while local accounts add reusable identity, persistent browser sessions, and
          explicit account-deletion controls.
        </p>
      </section>

      <div className="two-column-grid">
        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Lifecycle</p>
              <h2>What this deployment supports</h2>
            </div>
          </div>
          <div className="stack">
            <article className="citation-card">
              <strong>Create account</strong>
              <p className="muted">Register directly on the platform with email and password.</p>
            </article>
            <article className="citation-card">
              <strong>Login and logout</strong>
              <p className="muted">Session cookies are stored server-side and can be revoked on sign-out.</p>
            </article>
            <article className="citation-card">
              <strong>Delete user account</strong>
              <p className="muted">
                Locally managed accounts can be hard-deleted together with learner data tied to that account identity.
              </p>
            </article>
          </div>
        </article>

        <article className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Design posture</p>
              <h2>How account safety is handled</h2>
            </div>
          </div>
          <div className="stack">
            <article className="citation-card">
              <strong>Secure session cookies</strong>
              <p className="muted">Local accounts use HTTP-only session cookies instead of exposing raw tokens to the browser.</p>
            </article>
            <article className="citation-card">
              <strong>CSRF protection</strong>
              <p className="muted">Mutating account actions require the same-origin CSRF flow already used by the guest path.</p>
            </article>
            <article className="citation-card">
              <strong>Optional external provider</strong>
              <p className="muted">Auth0 remains available as an optional identity layer when deployment configuration enables it.</p>
            </article>
          </div>
        </article>
      </div>

      <AccountConsole auth0Configured={isAuth0Configured()} initialUser={user} statusMessage={statusMessage} />
    </div>
  );
}
