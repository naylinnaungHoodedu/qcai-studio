import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { LEARNING_MODES } from "../src/lib/learning-modes";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const readSource = (relativePath: string) => readFileSync(resolve(TEST_DIR, relativePath), "utf8");

test("the four interactive surfaces are each explained with what + when", () => {
  const modes = LEARNING_MODES.map((mode) => mode.mode);
  assert.deepEqual(modes, ["Learn", "Practice", "Play", "Build"]);

  const surfaces = LEARNING_MODES.map((mode) => mode.surface);
  assert.deepEqual(surfaces, ["Lessons", "Simulations", "Arena", "Builder"]);

  for (const mode of LEARNING_MODES) {
    assert.ok(mode.what.length > 20, `${mode.mode} needs a real "what it is" line`);
    assert.ok(mode.when.length > 20, `${mode.mode} needs a real "when to use it" line`);
    assert.match(mode.href, /^\//, `${mode.mode} must link somewhere in-app`);
  }
});

test("the modes guide is wired into both home and simulations pages", () => {
  const homeSource = readSource("../src/app/page.tsx");
  const simulationsSource = readSource("../src/app/simulations/page.tsx");

  for (const source of [homeSource, simulationsSource]) {
    assert.match(source, /import \{ LearningModesGuide \}/);
    assert.match(source, /<LearningModesGuide \/>/);
  }
});

test("arena options expose their 1-4 keyboard shortcut visibly", () => {
  const arenaSource = readSource("../src/components/arena-panel.tsx");
  assert.match(arenaSource, /press 1-4 to select/);
  assert.match(arenaSource, /arena-choice-key/);
  assert.match(arenaSource, /\{index \+ 1\}/);
});
