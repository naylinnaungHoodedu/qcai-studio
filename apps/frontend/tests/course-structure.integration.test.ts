import assert from "node:assert/strict";
import test from "node:test";

import { PRIMARY_NAV_ITEMS } from "../src/lib/navigation";
import { formatModuleLabel, getModuleLabel, getModuleNumber } from "../src/lib/module-labels";
import { ABOUT_AUDIENCE_GROUPS, ABOUT_LEARNING_PROGRESSION } from "../src/lib/public-course";

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
