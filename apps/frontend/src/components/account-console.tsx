"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { deleteAccount, loginAccount, logoutAccount, registerAccount } from "@/lib/api";
import type { UserProfile } from "@/lib/types";


type AccountConsoleProps = {
  initialUser: UserProfile | null;
  auth0Configured: boolean;
  statusMessage: string | null;
};

function isGuestUser(user: UserProfile | null): boolean {
  return Boolean(
    !user ||
      user.auth_provider === "guest" ||
      user.user_id.startsWith("guest-") ||
      user.user_id === "demo-learner",
  );
}

function describeIdentity(user: UserProfile | null): string {
  if (!user) {
    return "No authenticated or guest identity was resolved for this request.";
  }
  if (isGuestUser(user)) {
    return "Guest session in this browser";
  }
  if (user.auth_provider === "auth0") {
    return "External identity provider session";
  }
  if (user.auth_provider === "local") {
    return "Local QC+AI Studio account";
  }
  return "Authenticated learner session";
}

function formatError(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return "The account action did not complete cleanly. Retry the request.";
}

export function AccountConsole({ initialUser, auth0Configured, statusMessage }: AccountConsoleProps) {
  const router = useRouter();
  const [registerEmail, setRegisterEmail] = useState("");
  const [registerPassword, setRegisterPassword] = useState("");
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [deletePassword, setDeletePassword] = useState("");
  const [message, setMessage] = useState(statusMessage ?? "");
  const [errorMessage, setErrorMessage] = useState("");
  const [isPending, startTransition] = useTransition();

  const guestUser = isGuestUser(initialUser);
  const localUser = initialUser?.auth_provider === "local";

  function refreshPage(nextMessage: string) {
    setMessage(nextMessage);
    setErrorMessage("");
    router.refresh();
  }

  function runAction(action: () => Promise<string>) {
    setErrorMessage("");
    startTransition(() => {
      void (async () => {
        try {
          const nextMessage = await action();
          refreshPage(nextMessage);
        } catch (error) {
          setErrorMessage(formatError(error));
        }
      })();
    });
  }

  return (
    <div className="page-stack">
      {message ? <div className="success-banner">{message}</div> : null}
      {errorMessage ? <div className="error-banner">{errorMessage}</div> : null}

      <div className="two-column-grid account-grid">
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Current session</p>
              <h2>Identity and controls</h2>
            </div>
          </div>
          <div className="stack">
            <article className="citation-card">
              <strong>{describeIdentity(initialUser)}</strong>
              <p className="muted">{initialUser?.email ?? initialUser?.user_id ?? "Anonymous request"}</p>
              <p>
                {guestUser
                  ? "Guest activity is browser-bound. Create an account or sign in to keep a reusable identity."
                  : "Your learner activity now resolves against a stable account identity for this browser session."}
              </p>
            </article>

            {localUser ? (
              <div className="stack">
                <div className="button-row">
                  <button
                    className="secondary-button"
                    disabled={isPending}
                    onClick={() =>
                      runAction(async () => {
                        await logoutAccount();
                        return "You signed out of the local account session.";
                      })
                    }
                    type="button"
                  >
                    Sign out
                  </button>
                  <Link className="secondary-button" href="/dashboard">
                    Open dashboard
                  </Link>
                </div>

                <form
                  className="account-form danger-panel"
                  onSubmit={(event) => {
                    event.preventDefault();
                    runAction(async () => {
                      await deleteAccount(deletePassword);
                      setDeletePassword("");
                      return "Your account and learner records were deleted from this deployment.";
                    });
                  }}
                >
                  <label>
                    <span>Confirm password to delete this account</span>
                    <input
                      autoComplete="current-password"
                      minLength={1}
                      onChange={(event) => setDeletePassword(event.target.value)}
                      required
                      type="password"
                      value={deletePassword}
                    />
                  </label>
                  <button className="secondary-button destructive-button" disabled={isPending} type="submit">
                    Delete user account
                  </button>
                </form>
              </div>
            ) : (
              <div className="button-row">
                <Link className="secondary-button" href="/dashboard">
                  Continue studying
                </Link>
                {auth0Configured ? (
                  <a className="secondary-button" href="/auth/login?returnTo=/account">
                    External sign-in
                  </a>
                ) : null}
              </div>
            )}
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Account system</p>
              <h2>{guestUser ? "Create or access an account" : "Provider details"}</h2>
            </div>
          </div>
          {guestUser ? (
            <div className="stack">
              <form
                className="account-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  runAction(async () => {
                    await registerAccount(registerEmail, registerPassword);
                    setRegisterEmail("");
                    setRegisterPassword("");
                    return "Your account was created and this browser is now signed in.";
                  });
                }}
              >
                <label>
                  <span>Create account with email</span>
                  <input
                    autoComplete="email"
                    onChange={(event) => setRegisterEmail(event.target.value)}
                    required
                    type="email"
                    value={registerEmail}
                  />
                </label>
                <label>
                  <span>Password</span>
                  <input
                    autoComplete="new-password"
                    minLength={10}
                    onChange={(event) => setRegisterPassword(event.target.value)}
                    required
                    type="password"
                    value={registerPassword}
                  />
                </label>
                <button className="primary-button" disabled={isPending} type="submit">
                  Create account
                </button>
              </form>

              <form
                className="account-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  runAction(async () => {
                    await loginAccount(loginEmail, loginPassword);
                    setLoginEmail("");
                    setLoginPassword("");
                    return "You are now signed in with a persistent account session.";
                  });
                }}
              >
                <label>
                  <span>Sign in email</span>
                  <input
                    autoComplete="email"
                    onChange={(event) => setLoginEmail(event.target.value)}
                    required
                    type="email"
                    value={loginEmail}
                  />
                </label>
                <label>
                  <span>Password</span>
                  <input
                    autoComplete="current-password"
                    onChange={(event) => setLoginPassword(event.target.value)}
                    required
                    type="password"
                    value={loginPassword}
                  />
                </label>
                <button className="secondary-button" disabled={isPending} type="submit">
                  Sign in
                </button>
              </form>

              {auth0Configured ? (
                <article className="citation-card">
                  <strong>External provider is also available</strong>
                  <p className="muted">
                    Auth0 remains optional for deployments that need delegated identity instead of local email and
                    password management.
                  </p>
                  <div className="button-row">
                    <a className="secondary-button" href="/auth/login?returnTo=/account">
                      Sign in with Auth0
                    </a>
                  </div>
                </article>
              ) : (
                <article className="citation-card">
                  <strong>First-party account path is active</strong>
                  <p className="muted">
                    This deployment no longer depends on external client-side auth configuration for account creation,
                    login, logout, or deletion.
                  </p>
                </article>
              )}
            </div>
          ) : (
            <div className="stack">
              <article className="citation-card">
                <strong>Provider</strong>
                <p className="muted">{initialUser?.auth_provider ?? "unknown"}</p>
                <p>
                  {localUser
                    ? "This browser is signed in through the local QC+AI Studio account system backed by a server-side session."
                    : "This browser is using an external identity provider session. Sign-out remains available, but deletion is handled by the upstream provider."}
                </p>
              </article>
              {!localUser ? (
                <div className="button-row">
                  <a className="secondary-button" href="/auth/logout">
                    Sign out
                  </a>
                </div>
              ) : null}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
