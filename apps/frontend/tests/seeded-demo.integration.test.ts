import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  formatAuditFixtureUserLabel,
  formatBuilderFeedAuthorLabel,
  formatProjectAuthorLabel,
  isSeededAuditFixtureUserId,
  SEEDED_DEMO_DISCLOSURE,
} from "../src/lib/seeded-demo";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const BUILDER_COMPONENT_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/builder-studio.tsx"), "utf8");
const PROJECTS_COMPONENT_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/projects-studio.tsx"), "utf8");
const ARENA_COMPONENT_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/arena-panel.tsx"), "utf8");
const OPERATIONS_GOVERNANCE_SOURCE = readFileSync(
  resolve(TEST_DIR, "../src/lib/operations-governance.ts"),
  "utf8",
);

test("seeded fixture helpers format fixture-ac identities into readable public labels", () => {
  assert.equal(isSeededAuditFixtureUserId("fixture-ac-05"), true);
  assert.equal(formatAuditFixtureUserLabel("fixture-ac-05"), "Audit fixture AC-05");
  assert.equal(formatBuilderFeedAuthorLabel("fixture-ac-05"), "Audit fixture AC-05 | Seeded demo");
  assert.equal(formatProjectAuthorLabel("fixture-ac-03"), "Audit fixture AC-03 | Seeded demo");
  assert.match(SEEDED_DEMO_DISCLOSURE, /fictional audit personas/i);
});

test("projects, builder, and arena surfaces all wire in the shared seeded-demo disclosure", () => {
  assert.match(BUILDER_COMPONENT_SOURCE, /SEEDED_DEMO_DISCLOSURE/);
  assert.match(PROJECTS_COMPONENT_SOURCE, /SEEDED_DEMO_DISCLOSURE/);
  assert.match(ARENA_COMPONENT_SOURCE, /SEEDED_DEMO_DISCLOSURE/);
});

test("public operations copy now documents seeded demo transparency explicitly", () => {
  assert.match(OPERATIONS_GOVERNANCE_SOURCE, /Seeded demo transparency/);
  assert.match(OPERATIONS_GOVERNANCE_SOURCE, /fictional audit personas/);
});
