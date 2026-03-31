import type { Metadata } from "next";

import { AccountConsole } from "@/components/account-console";
import { isAuth0Configured } from "@/lib/auth";
import { fetchMe } from "@/lib/api";
import { buildPageMetadata } from "@/lib/metadata";


export const metadata: Metadata = buildPageMetadata({
  title: "Account",
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
        <div className="section-heading">
          <p className="eyebrow">Design posture</p>
          <h1>How account safety is handled</h1>
          <p>
            Local account actions continue to use server-side sessions, same-origin CSRF protections, and the same
            public-study boundary that keeps guest browsing separate from reusable account identity.
          </p>
        </div>
        <div className="module-grid">
          <article className="panel">
            <div className="stack">
              <strong>Secure session cookies</strong>
              <p className="muted">
                Local accounts use HTTP-only session cookies instead of exposing raw tokens to the browser.
              </p>
            </div>
          </article>
          <article className="panel">
            <div className="stack">
              <strong>CSRF protection</strong>
              <p className="muted">
                Mutating account actions require the same-origin CSRF flow already used by the guest path.
              </p>
            </div>
          </article>
          <article className="panel">
            <div className="stack">
              <strong>Optional external provider</strong>
              <p className="muted">
                Auth0 remains available as an optional identity layer when deployment configuration enables it.
              </p>
            </div>
          </article>
        </div>
      </section>

      <AccountConsole auth0Configured={isAuth0Configured()} initialUser={user} statusMessage={statusMessage} />
    </div>
  );
}
