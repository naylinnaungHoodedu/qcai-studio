import type { EvidencePanelPayload } from "@/lib/types";

// Fixed, conservative copy for the evidence panel (plan Phase 3 task 3.8). Contained answers are quotations matched
// on words, never verified for meaning, so nothing here may describe them as verified or as an explanation.
export const DECISION_TEXT: Record<EvidencePanelPayload["decision"], string> = {
  answer: "Quoted word for word from approved course sources",
  abstain: "No answer: the approved course sources do not cover this",
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

export function spanHref(spanId: string): string {
  return `/api/backend/evidence/spans/${encodeURIComponent(spanId)}`;
}

export type EvidencePanelView = {
  decision: string;
  labels: string[];
  degraded: string[];
  verdict: string;
  spans: Array<{ key: string; label: string; href: string | null }>;
};

export function evidencePanelView(payload: EvidencePanelPayload): EvidencePanelView {
  return {
    decision: DECISION_TEXT[payload.decision],
    labels: payload.labels.map((label) => LABEL_TEXT[label]),
    degraded: payload.degraded.map((mode) => DEGRADED_TEXT[mode]),
    verdict: VERDICT_TEXT[payload.verdict],
    spans: payload.spans.map((span, index) => ({
      key: `${index}-${span.span_id}`,
      label: span.label,
      href: span.resolvable ? spanHref(span.span_id) : null,
    })),
  };
}
