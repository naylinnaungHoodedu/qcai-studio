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
  // Spec 18.7 E16: an abstention reports a lexical miss, never a coverage fact nothing checked.
  assert.equal(abstained.decision, "No answer: no approved course passage matched this question closely enough");
  assert.doesNotMatch(abstained.decision, /do not cover|does not cover|not covered/i);
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

// Phase 3 spec 18.7 E17: the panel's links, labels and focus ring keep their contrast on the dark chat bubble, in
// the dark theme and in the opt-in light theme (where the chat stays dark by design).
function hexChannels(hex: string): [number, number, number] {
  const value = hex.replace("#", "");
  return [0, 2, 4].map((at) => parseInt(value.slice(at, at + 2), 16)) as [number, number, number];
}

function luminance([r, g, b]: [number, number, number]): number {
  const linear = (channel: number) => {
    const c = channel / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

function contrast(a: [number, number, number], b: [number, number, number]): number {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}

function over(top: [number, number, number], alpha: number, under: [number, number, number]): [number, number, number] {
  return top.map((channel, index) => Math.round(channel * alpha + under[index] * (1 - alpha))) as [number, number, number];
}

function token(block: string, name: string): string {
  const match = block.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`));
  assert.ok(match, `--${name} in the block`);
  return match[1];
}

test("the panel's links, labels and focus ring keep their contrast on the chat bubble in both themes", () => {
  const css = read("app/globals.css");
  // The bubble: rgba(42, 48, 61, 0.84) over the transcript surface (about rgb(5, 9, 21)).
  assert.match(css, /\.assistant-bubble \{[^}]*background: rgba\(42, 48, 61, 0\.84\)/);
  const bubble = over([42, 48, 61], 0.84, [5, 9, 21]);
  const focus = css.match(/\.assistant-evidence-spans a:focus-visible \{([^}]*)\}/);
  assert.ok(focus, "a focus rule for the panel's links");
  assert.match(focus[1], /outline: 3px solid var\(--accent\)/);
  // The global ring the rule replaces: rgba(15, 118, 110, 0.42), about 1.5:1 on the bubble.
  assert.ok(contrast(over([15, 118, 110], 0.42, bubble), bubble) < 3);
  const darkRoot = css.match(/^:root \{([^}]*)\}/m);
  const lightChat = css.match(/:root\[data-theme="light"\] \.assistant-panel \{([^}]*)\}/);
  assert.ok(darkRoot && lightChat, "the dark tokens, and the chat's tokens in the light theme");
  for (const block of [darkRoot[1], lightChat[1]]) {
    const accent = hexChannels(token(block, "accent"));
    const muted = hexChannels(token(block, "muted"));
    assert.ok(contrast(accent, bubble) >= 4.5, "passage links (0.82rem text) and the focus ring");
    assert.ok(contrast(muted, bubble) >= 4.5, "labels, degraded notes and the verdict");
  }
  assert.equal(token(lightChat[1], "accent"), token(darkRoot[1], "accent"));
  assert.equal(token(lightChat[1], "muted"), token(darkRoot[1], "muted"));
});
