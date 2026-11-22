import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  EHMF_TEXT,
  SYNTHETIC_REVIEWERS,
  TRIGGER_TEXT,
  VERDICT_TEXT,
  adjudicationPayload,
  adjudicationReady,
  reviewerHeaders,
  reviewerUiEnabled,
  v3ModeFromReady,
} from "../src/lib/v3-review";

// Phase 6 (plan Phase 6 F "Reviewer UI"; docs/architecture/phase6-implementation-spec.md section 11, 13.4): the V3 reviewer
// console exists only outside production and while the API reports V3 in shadow or on; no navigation names it; it shows
// claim text and shown spans only, never a vote, severity, support share or priority, and no label claims verification.
const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "../src");
const read = (path: string) => readFileSync(resolve(SRC, path), "utf8").replace(/\r\n/g, "\n");

test("the console is enabled outside production only, and V3_REVIEWER_UI=off switches it off", () => {
  assert.equal(reviewerUiEnabled({ NODE_ENV: "production" }), false);
  assert.equal(reviewerUiEnabled({ NODE_ENV: "production", V3_REVIEWER_UI: "on" }), false);
  assert.equal(reviewerUiEnabled({ NODE_ENV: "development" }), true);
  assert.equal(reviewerUiEnabled({ NODE_ENV: "development", V3_REVIEWER_UI: "off" }), false);
});

test("the API's V3 mode maps a missing or off mode to off", () => {
  assert.equal(v3ModeFromReady({ v3_queue: "shadow" }), "shadow");
  assert.equal(v3ModeFromReady({ v3_queue: "on" }), "on");
  for (const payload of [{ v3_queue: "off" }, {}, null, undefined, { v3_queue: "anything" }]) {
    assert.equal(v3ModeFromReady(payload), "off");
  }
});

test("the page is a 404 on either condition, not indexed, and no navigation links it", () => {
  const page = read("app/review/page.tsx");
  assert.match(page, /if \(!reviewerUiEnabled\(process\.env\)\) \{\s*notFound\(\);/);
  assert.match(page, /if \(\(await apiV3Mode\(\)\) === "off"\) \{\s*notFound\(\);/);
  assert.match(page, /index: false/);
  assert.match(page, /catch \{\s*return "off";/);
  for (const path of ["components/primary-nav.tsx", "components/site-footer.tsx", "lib/navigation.ts"]) {
    assert.doesNotMatch(read(path), /\/review\b/, path);
  }
});

test("only the synthetic reviewers get reviewer headers", () => {
  assert.deepEqual([...SYNTHETIC_REVIEWERS], ["reviewer-a", "reviewer-b", "reviewer-c"]);
  assert.deepEqual(reviewerHeaders("reviewer-b"), { "x-demo-user": "synthetic-reviewer-b", "x-demo-role": "reviewer" });
  assert.throws(() => reviewerHeaders("admin"));
  assert.throws(() => reviewerHeaders("someone@example.com"));
});

test("an adjudication payload sorts the labels and nulls a SUPPORTED label's EHMF type", () => {
  const payload = adjudicationPayload(
    [
      { claim_id: "claim-b", verdict: "CONTRADICTED", ehmf_type: "A" },
      { claim_id: "claim-a", verdict: "SUPPORTED", ehmf_type: "C" },
    ],
    null,
    "key-123456",
  );
  assert.deepEqual(payload, {
    client_key: "key-123456",
    claim_labels: [
      { claim_id: "claim-a", verdict: "SUPPORTED", ehmf_type: null },
      { claim_id: "claim-b", verdict: "CONTRADICTED", ehmf_type: "A" },
    ],
    abstention_label: null,
  });
});

test("an adjudication is ready only once every claim and an abstention item's label are chosen explicitly", () => {
  const claims = ["claim-a", "claim-b"];
  const unset = claims.map((claim_id) => ({ claim_id, verdict: null, ehmf_type: null }));
  assert.equal(adjudicationReady(unset, claims, null, false), false);
  const supported = claims.map((claim_id) => ({ claim_id, verdict: "SUPPORTED" as const, ehmf_type: null }));
  assert.equal(adjudicationReady(supported, claims, null, false), true);
  assert.equal(adjudicationReady(supported.slice(0, 1), claims, null, false), false);
  const untyped = [supported[0], { claim_id: "claim-b", verdict: "CONTRADICTED" as const, ehmf_type: null }];
  assert.equal(adjudicationReady(untyped, claims, null, false), false);
  const typed = [supported[0], { claim_id: "claim-b", verdict: "CONTRADICTED" as const, ehmf_type: "A" as const }];
  assert.equal(adjudicationReady(typed, claims, null, false), true);
  assert.equal(adjudicationReady([], [], null, true), false);
  assert.equal(adjudicationReady([], [], "correct", true), true);
});

test("the console pre-fills no label, names every select and keeps one mounted status region", () => {
  const consoleSource = read("components/v3-review-console.tsx");
  assert.doesNotMatch(consoleSource, /verdict: "SUPPORTED"/);
  assert.doesNotMatch(consoleSource, /\? "correct" : null/);
  assert.match(consoleSource, /verdict: null, ehmf_type: null/);
  assert.match(consoleSource, /disabled=\{!ready\}/);
  const selects = consoleSource.match(/<select\b/g) ?? [];
  const labelled = consoleSource.match(/<label\b[^>]*>\s*(Synthetic reviewer|Verdict for claim|Error type for claim|Abstention label)/g) ?? [];
  assert.equal(selects.length, 4);
  assert.equal(labelled.length, selects.length);
  assert.match(consoleSource, /<p className="[^"]*" role="status" aria-live="polite">\s*\{message\}/);
  assert.doesNotMatch(consoleSource, /\{message \? <p/);
  assert.match(consoleSource, /async function open\(item: V3QueueItem\) \{\s*try \{/);
  assert.match(consoleSource, /disabled=\{!draft\[claim\.claim_id\]\?\.verdict \|\| draft\[claim\.claim_id\]\?\.verdict === "SUPPORTED"\}/);
});

test("the review page renders no second main landmark inside the app shell's", () => {
  assert.match(read("components/app-shell.tsx"), /<main id="main-content">/);
  assert.doesNotMatch(read("app/review/page.tsx"), /<main\b/);
});

test("trigger labels say why an item is queued, never which objection type it drew", () => {
  for (const text of Object.values(TRIGGER_TEXT)) {
    assert.doesNotMatch(text, /\btype [A-E]\b|\b[A-E] or [A-E]\b|objected|tier \d/i);
  }
});

test("no label says verified or grounded", () => {
  for (const text of [...Object.values(VERDICT_TEXT), ...Object.values(EHMF_TEXT), ...Object.values(TRIGGER_TEXT)]) {
    assert.doesNotMatch(text, /verified|grounded/i);
  }
  assert.doesNotMatch(read("app/review/page.tsx"), /verified|grounded/i);
});

test("the console shows shown spans only, acts only on reviewable items and names no ranking value", () => {
  const consoleSource = read("components/v3-review-console.tsx");
  assert.match(consoleSource, /\.filter\(\(span\) => span\.shown\)/);
  assert.match(consoleSource, /\{selected\.reviewable \? \(\s*<div className="mt-3 flex gap-2">/);
  assert.doesNotMatch(consoleSource, /severity|support_share|priority|votes|localStorage|sessionStorage|indexedDB/i);
  assert.match(consoleSource, /crypto\.randomUUID\(\)/);
  assert.match(consoleSource, /reviewerHeaders\(reviewer\)/);
});
