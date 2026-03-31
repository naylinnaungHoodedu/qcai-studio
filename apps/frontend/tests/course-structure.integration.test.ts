import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { COURSE_REFERENCES, OVERVIEW_COURSE_REFERENCES } from "../src/lib/course-references";
import { PRIMARY_NAV_ITEMS } from "../src/lib/navigation";
import { formatModuleLabel, getModuleLabel, getModuleNumber } from "../src/lib/module-labels";
import {
  ABOUT_AUDIENCE_GROUPS,
  ABOUT_LEARNING_PROGRESSION,
  CURRICULUM_ARCHITECTURE_STAGES,
} from "../src/lib/public-course";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const HOME_PAGE_SOURCE = readFileSync(resolve(TEST_DIR, "../src/app/page.tsx"), "utf8");
const MODULES_PAGE_SOURCE = readFileSync(resolve(TEST_DIR, "../src/app/modules/page.tsx"), "utf8");
const MODULE_CARD_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/module-card.tsx"), "utf8");

test("primary navigation follows the requested production order", () => {
  assert.deepEqual(
    PRIMARY_NAV_ITEMS.map((item) => item.label),
    ["Overview", "About", "Modules", "Projects", "Practice", "Simulations", "Account", "Search"],
  );
});

test("module label helpers expand bare numbers into module labels", () => {
  assert.equal(getModuleNumber("nisq-hybrid-workflows"), 1);
  assert.equal(getModuleNumber("quantum-finance-programming"), 11);
  assert.equal(getModuleLabel("hardware-constrained-models"), "Module 8");
  assert.equal(formatModuleLabel(10), "Module 10");
});

test("about page audience and progression sections expose the new content blocks", () => {
  assert.equal(ABOUT_AUDIENCE_GROUPS.length, 4);
  assert.deepEqual(
    ABOUT_AUDIENCE_GROUPS.map((group) => group.title),
    ["Students", "Developers", "Data scientists", "Researchers"],
  );
  assert.equal(ABOUT_LEARNING_PROGRESSION.length, 5);
  assert.deepEqual(
    ABOUT_LEARNING_PROGRESSION.map((step) => step.title),
    ["Foundations", "Algorithms", "Programming", "Applications", "Specialization"],
  );
});

test("overview keeps only the first three bibliography references while the syllabus retains the full list", () => {
  assert.equal(OVERVIEW_COURSE_REFERENCES.length, 3);
  assert.deepEqual(OVERVIEW_COURSE_REFERENCES, COURSE_REFERENCES.slice(0, 3));
  assert.ok(
    !OVERVIEW_COURSE_REFERENCES.some((reference) =>
      reference.includes("Introduction to Hardware-Constrained Learning for Quantum Computing and Artificial Intelligence"),
    ),
  );
});

test("overview no longer renders the what's new section box", () => {
  assert.doesNotMatch(HOME_PAGE_SOURCE, /<p className="eyebrow">What&apos;s new<\/p>/);
  assert.doesNotMatch(HOME_PAGE_SOURCE, /Open full changelog/);
});

test("curriculum architecture is grouped by learning progression rather than original and new splits", () => {
  assert.deepEqual(
    CURRICULUM_ARCHITECTURE_STAGES.map((stage) => stage.title),
    ["Foundations", "Algorithms", "Programming", "Applications", "Specialization"],
  );
  assert.doesNotMatch(MODULES_PAGE_SOURCE, /Original six modules/);
  assert.doesNotMatch(MODULES_PAGE_SOURCE, /Five new hardware-constrained extensions/);
  assert.doesNotMatch(MODULES_PAGE_SOURCE, /Added modules/);
});

test("module cards no longer render grounded source footnotes", () => {
  assert.doesNotMatch(MODULE_CARD_SOURCE, /Grounded in/);
  assert.doesNotMatch(MODULE_CARD_SOURCE, /module-card-footnote/);
});
