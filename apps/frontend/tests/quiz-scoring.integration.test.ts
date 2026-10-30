import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const API_SOURCE = readFileSync(resolve(TEST_DIR, "../src/lib/api.ts"), "utf8").replace(/\r\n/g, "\n");
const QUIZ_PANEL_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/quiz-panel.tsx"), "utf8");

// Plan task 1.2 (E-110): the API scores quiz responses itself, so the browser sends none.
test("a quiz attempt sends the responses and no score", () => {
  const helper = API_SOURCE.slice(API_SOURCE.indexOf("export async function recordQuizAttempt"));
  const body = helper.slice(0, helper.indexOf("\n}\n"));
  assert.match(body, /lesson_slug: lessonSlug,\s+responses,/);
  assert.doesNotMatch(body, /score/);
});

test("the quiz panel shows the score the API recorded", () => {
  assert.match(QUIZ_PANEL_SOURCE, /recordQuizAttempt\(lessonSlug, answers\)/);
  assert.match(QUIZ_PANEL_SOURCE, /Recorded score: \{savedAttempt\.score\}/);
});
