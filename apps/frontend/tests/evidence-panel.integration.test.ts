import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { DECISION_TEXT, DEGRADED_TEXT, LABEL_TEXT, VERDICT_TEXT, evidencePanelView, spanHref } from "../src/lib/evidence-panel";
import { routeRequiresGuestSession } from "../src/lib/guest-session";
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
  // The API's label is kept; the panel adds the passage's position (review round 3, spec 18.6 D14).
  assert.equal(plain.spans[0].label, "Passage 1: Routing brief — Depth");
});

test("two passages of one section get distinct link text, and links look like links (WCAG 2.4.4)", () => {
  const other = `span-${"b".repeat(64)}`;
  const view = evidencePanelView(
    payload({
      spans: [
        { span_id: SPAN, label: "Routing brief — Depth", resolvable: true },
        { span_id: other, label: "Routing brief — Depth", resolvable: true },
      ],
    }),
  );
  assert.deepEqual(
    view.spans.map((span) => span.label),
    ["Passage 1: Routing brief — Depth", "Passage 2: Routing brief — Depth"],
  );
  assert.notEqual(view.spans[0].href, view.spans[1].href);
  const css = read("app/globals.css");
  const rule = css.match(/\.assistant-evidence-spans a \{([^}]*)\}/);
  assert.ok(rule, "a link rule for the panel's passages");
  assert.match(rule[1], /text-decoration: underline/);
  assert.match(rule[1], /color: var\(--accent\)/);
});

test("each panel is a group, not a region landmark repeated once per answer", () => {
  const panel = read("components/evidence-panel.tsx");
  assert.match(panel, /role="group" aria-label="Evidence for this answer"/);
  assert.doesNotMatch(panel, /<section/);
});

test("a span link never mints a guest session, and only a well-formed span id is public (DI-44)", () => {
  // The proxy strips its /api/backend prefix; the API reads no credential on either span route.
  const proxied = spanHref(SPAN).replace(/^\/api\/backend/, "");
  assert.equal(proxied, `/evidence/spans/${SPAN}`);
  assert.equal(routeRequiresGuestSession(proxied), false);
  assert.equal(routeRequiresGuestSession(`/spans/${SPAN}`), false);
  for (const path of [
    `/evidence/spans/${SPAN.toUpperCase()}`,
    `/evidence/spans/span-${"a".repeat(63)}`,
    `/evidence/spans/${SPAN}/extra`,
    "/evidence/spans/span%2F..%2Fx",
    `/ledger/responses/turn-${"0".repeat(8)}`,
    "/tutor/turns",
    "/qa/ask",
  ]) {
    assert.equal(routeRequiresGuestSession(path), true, path);
  }
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
  // What a legacy record really holds: the whole matched set with scores and offsets, not only the quotations;
  // and what a shadow record adds (the resolver's source message ids).
  assert.match(disclosures, /which course passages the search matched for your question, with their match scores and positions/);
  assert.match(disclosures, /the ids of the tutor messages your question was taken from/);
  // /qa/ask answers are ledgered too (DI-39). Their records hold no id that names the learner, but they can be matched
  // to the learner's Q&A history while it is kept (the same answer, moments apart): review round 3, spec 18.6 D10.
  assert.match(disclosures, /each answer to a question asked in a lesson's Q&A panel/);
  assert.match(disclosures, /A Q&A answer's record has no id that names you, but while your Q&A history is kept it can be matched to it/);
  assert.doesNotMatch(disclosures, /not linked to you at all|never were/);
  // Only the deletion paths that exist: account deletion, and guest retention cleanup (no "tutor history" deletion).
  assert.match(disclosures, /Deleting your account deletes your tutor turns and your Q&A history/);
  assert.match(disclosures, /for a guest, automatic retention cleanup does the same for history older than one year/);
  assert.doesNotMatch(disclosures, /tutor history/);
});
