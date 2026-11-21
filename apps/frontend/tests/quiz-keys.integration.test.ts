import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { feedbackFor, publicQuestions, resultLabel } from "../src/lib/quiz-feedback";
import type { QuizAttemptResult, QuizQuestion } from "../src/lib/types";

// Plan Phase 4 B "keyed answers outside public payloads" (R-42; Phase 4 spec 11, 13.4): no answer key reaches a public
// payload, a page or a client component; the rubric comes only from a saved attempt's feedback.
const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "../src");
const read = (path: string) => readFileSync(resolve(SRC, path), "utf8").replace(/\r\n/g, "\n");

test("the public QuizQuestion type carries no answer and no explanation", () => {
  const type = read("lib/types.ts").match(/export type QuizQuestion = \{([\s\S]*?)\n\};/);
  assert.ok(type, "the QuizQuestion type");
  assert.doesNotMatch(type[1], /\banswer\b|\bexplanation\b/);
  assert.match(type[1], /id: string;[\s\S]*question_type: string;[\s\S]*prompt: string;[\s\S]*choices: string\[\];[\s\S]*difficulty: string;/);
});

test("the quiz panel scores nothing from keys and reveals no rubric before a saved attempt", () => {
  const panel = read("components/quiz-panel.tsx");
  for (const forbidden of [/question\.answer/, /question\.explanation/, /Reveal rubric/, /=== question\.answer/, /Auto-score/, /showResults/]) {
    assert.doesNotMatch(panel, forbidden);
  }
  assert.match(panel, /feedbackFor\(/);
  assert.match(panel, /recordQuizAttempt\(lessonSlug, answers\)/);
  assert.match(panel, /Answer this question and save an attempt to see its rubric\./);
});

test("the saved attempt's result is announced and each question's input names its feedback", () => {
  // WCAG 2.1 4.1.3: the feedback appears only after recordQuizAttempt resolves, so the save result (and a save error)
  // is in a live region that is always rendered, and each input points at its own feedback.
  const panel = read("components/quiz-panel.tsx");
  const region = panel.match(/<div aria-live="polite" role="status">([\s\S]*?)\n      <\/div>/);
  assert.ok(region, "a polite status region");
  assert.match(region[1], /saveError \?/);
  assert.match(region[1], /Saved attempt #\{savedAttempt\.attempt_id\}\. Recorded score: \{savedAttempt\.score\}/);
  assert.match(region[1], /Feedback is shown under each question\./);
  assert.doesNotMatch(panel.replace(region[0], ""), /Saved attempt #|\{saveError\}/);
  assert.match(panel, /const feedbackId = `quiz-feedback-\$\{question\.id\}`;/);
  assert.match(panel, /const describedBy = feedback\.state === "none" \? undefined : feedbackId;/);
  assert.equal((panel.match(/aria-describedby=\{describedBy\}/g) ?? []).length, 2, "the radio inputs and the textarea");
  assert.match(panel, /<div className="quiz-result" id=\{feedbackId\}>/);
  assert.match(panel, /<p className="muted" id=\{feedbackId\}>\s*Answer this question and save an attempt to see its rubric\./);
});

test("the quiz page passes only the public fields to the client component", () => {
  const page = read("app/quiz/[lessonSlug]/page.tsx");
  assert.match(page, /questions=\{publicQuestions\(lesson\.quiz_questions\)\}/);
  assert.doesNotMatch(page, /questions=\{lesson\.quiz_questions\}/);
  assert.match(page, /save an attempt to see the model answers and rubrics/);
});

test("publicQuestions drops the key and explanation of an older API's payload", () => {
  const older = [
    { id: "lesson-quiz-1", question_type: "mcq", prompt: "Which?", choices: ["a", "b"], difficulty: "core", answer: "b", explanation: "because" },
  ] as unknown as Array<QuizQuestion & Record<string, unknown>>;
  const stripped = publicQuestions(older);
  assert.deepEqual(stripped, [{ id: "lesson-quiz-1", question_type: "mcq", prompt: "Which?", choices: ["a", "b"], difficulty: "core" }]);
  assert.ok(!("answer" in stripped[0]) && !("explanation" in stripped[0]));
  assert.doesNotMatch(JSON.stringify(stripped), /because/);
});

test("feedbackFor maps none, unanswered, correct and incorrect, and tolerates an older API", () => {
  const result: QuizAttemptResult = {
    status: "saved",
    attempt_id: 7,
    score: 1,
    feedback: [
      { question_id: "q1", answered: true, correct: true, answer: "Key one", explanation: "Why one" },
      { question_id: "q2", answered: true, correct: false, answer: "Key two", explanation: "Why two" },
      { question_id: "q3", answered: false, correct: null, answer: null, explanation: null },
    ],
  };
  assert.deepEqual(feedbackFor("q1", null), { state: "none" });
  assert.deepEqual(feedbackFor("q1", result), { state: "correct", answer: "Key one", explanation: "Why one" });
  assert.deepEqual(feedbackFor("q2", result), { state: "incorrect", answer: "Key two", explanation: "Why two" });
  assert.deepEqual(feedbackFor("q3", result), { state: "unanswered" });
  assert.deepEqual(feedbackFor("q9", result), { state: "none" });
  const older: QuizAttemptResult = { status: "saved", attempt_id: 8, score: 0 };
  assert.deepEqual(feedbackFor("q1", older), { state: "none" });
});

test("a short answer's result names the exact match; only a choice item is called correct or not", () => {
  // The server's verdict is an exact string match (quiz_keys.score_attempt): for a short answer it says whether the text
  // equals the model answer, never that a sound answer in the learner's own words is wrong.
  const shortAnswer = { choices: [] as string[] };
  const choice = { choices: ["a", "b"] };
  assert.equal(resultLabel(shortAnswer, { state: "correct" }), "Matches the model answer");
  assert.equal(resultLabel(shortAnswer, { state: "incorrect" }), "Does not match the model answer exactly");
  assert.equal(resultLabel(choice, { state: "correct" }), "Correct");
  assert.equal(resultLabel(choice, { state: "incorrect" }), "Not correct");
  for (const question of [shortAnswer, choice]) {
    assert.equal(resultLabel(question, { state: "none" }), null);
    assert.equal(resultLabel(question, { state: "unanswered" }), null);
  }
  const panel = read("components/quiz-panel.tsx");
  assert.match(panel, /const result = resultLabel\(question, feedback\);/);
  assert.match(panel, /\{result \? \(\n\s*<div className="quiz-result" id=\{feedbackId\}>\n\s*<p>\n\s*<strong>\{result\}<\/strong>/);
  assert.doesNotMatch(panel, /"Not correct"|"Correct"/);
  // The final-judgment caveat stays beside the short-answer result.
  assert.match(panel, /Short answers are scored on the server by exact match; use the model answer shown after saving for final judgment\./);
});
