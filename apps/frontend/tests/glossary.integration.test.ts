import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { CORE_CONCEPTS, GLOSSARY, getGlossaryDefinition } from "../src/lib/glossary";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const HOME_PAGE_SOURCE = readFileSync(resolve(TEST_DIR, "../src/app/page.tsx"), "utf8");

test("core concepts lead with the ideas a newcomer needs, in plain language", () => {
  const terms = CORE_CONCEPTS.map((concept) => concept.term);
  assert.ok(terms.includes("QC+AI"));
  assert.ok(terms.includes("NISQ"));
  for (const concept of CORE_CONCEPTS) {
    assert.ok(concept.plain.length > 20, `${concept.term} needs a real plain definition`);
  }
});

test("glossary resolves heavy jargon terms to jargon-free definitions", () => {
  assert.match(getGlossaryDefinition("NISQ") ?? "", /noisy/i);
  assert.match(getGlossaryDefinition("QUBO") ?? "", /optimiz/i);
  assert.equal(getGlossaryDefinition("not-a-term"), undefined);
  assert.ok(Object.keys(GLOSSARY).length >= 10);
});

test("home page renders the plain-language onboarding explainer", () => {
  assert.match(HOME_PAGE_SOURCE, /New to QC\+AI\?/);
  assert.match(HOME_PAGE_SOURCE, /The whole course in plain language/);
  assert.match(HOME_PAGE_SOURCE, /CORE_CONCEPTS\.map/);
});

test("module cards surface jargon tags through the glossary helper", () => {
  const MODULE_CARD_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/module-card.tsx"), "utf8");
  assert.match(MODULE_CARD_SOURCE, /import \{ GlossaryTerm \}/);
  assert.match(MODULE_CARD_SOURCE, /<GlossaryTerm term=\{tag\}>\{tag\}<\/GlossaryTerm>/);
  assert.ok(getGlossaryDefinition("RL-Q-ALM"));
  assert.ok(getGlossaryDefinition("MLIR"));
});
