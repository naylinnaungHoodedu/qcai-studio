import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { DECISION_TEXT, DEGRADED_TEXT, LABEL_TEXT, VERDICT_TEXT, evidencePanelView, spanHref } from "../src/lib/evidence-panel";
import type { EvidencePanelPayload } from "../src/lib/types";

// Plan Phase 3 task 3.8: the evidence panel shows the decision, span links, degraded and "lexically screened" labels
// for the contained answer the learner already receives; labels only, never "grounded".
const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "../src");
const read = (path: string) => readFileSync(resolve(SRC, path), "utf8");
const SPAN = `span-${"a".repeat(64)}`;

function payload(overrides: Partial<EvidencePanelPayload> = {}): EvidencePanelPayload {
  return {
    panel_schema: "evidence-panel-v1",
    decision: "answer",
    labels: ["lexically_screened"],
    degraded: ["extractive_only", "retrieval_fallback", "citations_provisional"],
    spans: [{ span_id: SPAN, label: "Routing brief — Depth", resolvable: true }],
    verdict: "no-verdict",
    ...overrides,
  };
}

test("each code maps to its fixed, conservative text", () => {
  const view = evidencePanelView(payload());
  assert.equal(view.decision, "Quoted word for word from approved course sources");
  assert.deepEqual(view.labels, ["Lexically screened: matched on words, not checked for meaning"]);
  assert.deepEqual(view.degraded, [
    "Explanations are switched off; only quotations are shown",
    "Search ran in a reduced mode",
    "Citations are provisional",
  ]);
  assert.equal(view.verdict, "Not yet verified");
  const abstained = evidencePanelView(payload({ decision: "abstain", labels: [], spans: [] }));
  assert.equal(abstained.decision, "No answer: the approved course sources do not cover this");
  assert.deepEqual(abstained.labels, []);
  assert.deepEqual(abstained.spans, []);
});

test("span links point at the resolver route only when it is enabled", () => {
  const linked = evidencePanelView(payload());
  assert.equal(linked.spans[0].href, `/api/backend/evidence/spans/${SPAN}`);
  assert.equal(spanHref("span/../x"), "/api/backend/evidence/spans/span%2F..%2Fx");
  const plain = evidencePanelView(payload({ spans: [{ span_id: SPAN, label: "Routing brief — Depth", resolvable: false }] }));
  assert.equal(plain.spans[0].href, null);
  assert.equal(plain.spans[0].label, "Routing brief — Depth");
});

test("no panel text says grounded", () => {
  const texts = [
    ...Object.values(DECISION_TEXT),
    ...Object.values(LABEL_TEXT),
    ...Object.values(DEGRADED_TEXT),
    ...Object.values(VERDICT_TEXT),
  ];
  for (const text of texts) {
    assert.doesNotMatch(text, /grounded|verified answer/i, text);
  }
  assert.doesNotMatch(read("components/evidence-panel.tsx"), /grounded/i);
  assert.doesNotMatch(read("lib/evidence-panel.ts"), /grounded/i);
});

test("the chat renders the panel only when the API sent one", () => {
  const chat = read("components/teaching-assistant-chat.tsx");
  assert.match(chat, /message\.evidence \? <EvidencePanel/);
  assert.match(chat, /evidence: response\.evidence \?\? null/);
  assert.match(read("components/evidence-panel.tsx"), /aria-label="Evidence for this answer"/);
});

test("the privacy page discloses the tutor response ledger", () => {
  const disclosures = read("lib/privacy-disclosures.ts");
  assert.match(disclosures, /dataClass: "Tutor response ledger"/);
  assert.match(disclosures, /No name, email, account id or question text/);
});
