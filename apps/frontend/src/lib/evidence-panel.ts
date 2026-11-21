import type { EvidencePanelPayload } from "@/lib/types";

// Fixed, conservative copy for the evidence panel (plan Phase 3 task 3.8). Contained answers are quotations matched
// on words, never verified for meaning, so nothing here may describe them as verified or as an explanation.
// An abstention says only what the lexical gate found: no approved passage matched closely enough. It never says the
// sources do not cover the topic, which nothing checks (a floor miss, or no approved asset at all under D-31;
// Phase 3 spec 18.7 E16); the learner-facing abstention text says the same ("I can't answer this from the approved
// course sources").
export const DECISION_TEXT: Record<EvidencePanelPayload["decision"], string> = {
  answer: "Quoted word for word from approved course sources",
  abstain: "No answer: no approved course passage matched this question closely enough",
};

export const LABEL_TEXT: Record<EvidencePanelPayload["labels"][number], string> = {
  lexically_screened: "Lexically screened: matched on words, not checked for meaning",
};

export const DEGRADED_TEXT: Record<EvidencePanelPayload["degraded"][number], string> = {
  extractive_only: "Explanations are switched off; only quotations are shown",
  retrieval_fallback: "Search ran in a reduced mode",
  citations_provisional: "Citations are provisional",
};

export const VERDICT_TEXT: Record<EvidencePanelPayload["verdict"], string> = {
  "no-verdict": "Not yet verified",
};

// Phase 4 (V1.7): the quoted passages that may disagree, labelled; the panel adds no claim of its own.
type ConflictKind = NonNullable<EvidencePanelPayload["conflicts"]>[number]["kind"];
export const CONFLICT_TEXT: Record<ConflictKind, string> = {
  version_of_same_asset: "Passages {a} and {b} come from different versions of one source; they may disagree",
  number_disagreement: "Passages {a} and {b} give different figures for what looks like the same point",
  negation_disagreement: "Passages {a} and {b} may say opposite things",
};

export function conflictText(kind: ConflictKind, passages: number[]): string {
  const [a, b] = passages;
  return CONFLICT_TEXT[kind].replace("{a}", String(a)).replace("{b}", String(b));
}

export function spanHref(spanId: string): string {
  return `/api/backend/evidence/spans/${encodeURIComponent(spanId)}`;
}

export type EvidencePanelView = {
  decision: string;
  labels: string[];
  degraded: string[];
  verdict: string;
  spans: Array<{ key: string; label: string; href: string | null }>;
  conflicts: string[];
};

export function evidencePanelView(payload: EvidencePanelPayload): EvidencePanelView {
  return {
    decision: DECISION_TEXT[payload.decision],
    labels: payload.labels.map((label) => LABEL_TEXT[label]),
    degraded: payload.degraded.map((mode) => DEGRADED_TEXT[mode]),
    verdict: VERDICT_TEXT[payload.verdict],
    spans: payload.spans.map((span, index) => ({
      key: `${index}-${span.span_id}`,
      label: `Passage ${index + 1}: ${span.label}`,
      href: span.resolvable ? spanHref(span.span_id) : null,
    })),
    conflicts: (payload.conflicts ?? []).map((conflict) => conflictText(conflict.kind, conflict.passages)),
  };
}
