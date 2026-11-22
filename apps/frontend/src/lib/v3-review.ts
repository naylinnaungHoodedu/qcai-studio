// The V3 reviewer console's pure helpers (plan Phase 6 F "Reviewer UI"; docs/architecture/phase6-implementation-spec.md
// section 11). The console exists only where the frontend runs outside production and the API reports V3 in shadow or on;
// it is never linked from navigation and is not learner-facing. Reviewers are synthetic demo identities (D-18 open).

import type { V3ClaimLabel } from "./types";

export type V3Mode = "off" | "shadow" | "on";

export const SYNTHETIC_REVIEWERS = ["reviewer-a", "reviewer-b", "reviewer-c"] as const;
export type SyntheticReviewer = (typeof SYNTHETIC_REVIEWERS)[number];

// The environment flag that can switch the console off in development too. It is not a cookie or a storage key.
export function reviewerUiEnabled(env: { NODE_ENV?: string; V3_REVIEWER_UI?: string }): boolean {
  return env.NODE_ENV !== "production" && env.V3_REVIEWER_UI !== "off";
}

export function v3ModeFromReady(payload: unknown): V3Mode {
  const mode = (payload as { v3_queue?: unknown } | null | undefined)?.v3_queue;
  return mode === "shadow" || mode === "on" ? mode : "off";
}

export function reviewerHeaders(name: string): Record<string, string> {
  if (!(SYNTHETIC_REVIEWERS as readonly string[]).includes(name)) {
    throw new Error(`Only the synthetic reviewers may review in development: ${SYNTHETIC_REVIEWERS.join(", ")}.`);
  }
  return { "x-demo-user": `synthetic-${name}`, "x-demo-role": "reviewer" };
}

export type AdjudicationPayload = {
  client_key: string;
  claim_labels: V3ClaimLabel[];
  abstention_label: "correct" | "missed_answer" | null;
};

export function adjudicationPayload(
  labels: V3ClaimLabel[],
  abstention: "correct" | "missed_answer" | null,
  clientKey: string,
): AdjudicationPayload {
  const sorted = [...labels]
    .map((label) => ({
      claim_id: label.claim_id,
      verdict: label.verdict,
      ehmf_type: label.verdict === "SUPPORTED" ? null : label.ehmf_type,
    }))
    .sort((left, right) => (left.claim_id < right.claim_id ? -1 : left.claim_id > right.claim_id ? 1 : 0));
  return { client_key: clientKey, claim_labels: sorted, abstention_label: abstention };
}

export const VERDICT_TEXT: Record<V3ClaimLabel["verdict"], string> = {
  SUPPORTED: "The span states the claim",
  CONTRADICTED: "The span states the opposite",
  NOT_ENOUGH_INFO: "The span does not settle it",
};

export const EHMF_TEXT: Record<string, string> = {
  A: "A: unsupported or contradicted content",
  B: "B: a citation that does not support the claim",
  C: "C: a misconception",
  D: "D: a conflict between sources",
  E: "E: presentation",
};

export const TRIGGER_TEXT: Record<string, string> = {
  X1: "X1 critical claim objected at tier 1",
  X2: "X2 type A or B unresolved after two cycles",
  X3: "X3 learner flag",
  X4: "X4 abstention margin",
  X5: "X5 model change or drift alarm audit",
  X6: "X6 random audit",
};
