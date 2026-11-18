import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// R-16 containment (plan task 1.11, Action 26; Release R1.2): no answer surface, and no public statement about
// Q&A, may call answers "grounded" or "cited". Contained answers quote approved sources or abstain.
const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "../src");
const read = (path: string) => readFileSync(resolve(SRC, path), "utf8");

const ANSWER_SURFACES = [
  "components/qa-panel.tsx",
  "components/teaching-assistant-chat.tsx",
  "lib/public-status.ts",
  "lib/public-course.ts",
  "app/opengraph-image.tsx",
];

test("answer surfaces never call an answer grounded", () => {
  for (const path of ANSWER_SURFACES) {
    assert.doesNotMatch(read(path), /grounded/i, path);
  }
});

test("public descriptions do not promise grounded, cited or model-generated Q&A", () => {
  const about = read("app/about/page.tsx");
  // The whole page, not one phrase: the 2026-11-18 review found a card that the narrower check missed.
  for (const claim of [/grounded Q&?A/i, /grounded intelligence/i, /grounded lexical/i, /citation-first/i, /GPT-[0-9.]+/i, /LangChain/i]) {
    assert.doesNotMatch(about, claim, String(claim));
  }
  assert.doesNotMatch(read("app/opengraph-image.tsx"), /cited Q&/i);
});

test("a withheld history answer is shown as a muted notice", () => {
  assert.match(read("components/qa-panel.tsx"), /item\.withdrawn \? "muted"/);
});
