import { AUTH_CSRF_COOKIE_NAME, AUTH_CSRF_HEADER } from "@/lib/auth";

export async function issueLearnerRecordReplica(preferredReplica?: string): Promise<{ replica_id: string }> {
  const prefix = `${AUTH_CSRF_COOKIE_NAME}=`;
  const csrf = typeof document === "undefined" ? undefined : document.cookie
    .split(";").map((cookie) => cookie.trim()).find((cookie) => cookie.startsWith(prefix));
  const headers = new Headers({ "Content-Type": "application/json" });
  if (csrf) headers.set(AUTH_CSRF_HEADER, decodeURIComponent(csrf.slice(prefix.length)));
  const response = await fetch("/api/backend/learner-record/replicas", {
    method: "POST", headers, cache: "no-store", body: JSON.stringify({ preferred_replica_id: preferredReplica }),
  });
  if (response.status === 404) throw new Error("Learner record synchronization is disabled.");
  if (!response.ok) throw new Error(`Learner replica request failed: ${response.status}`);
  return response.json();
}
