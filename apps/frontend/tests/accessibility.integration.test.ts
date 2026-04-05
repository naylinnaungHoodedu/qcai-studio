import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const BUILDER_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/builder-studio.tsx"), "utf8");
const VIDEO_PANEL_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/video-panel.tsx"), "utf8");
const NOTES_PANEL_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/notes-panel.tsx"), "utf8");
const SEARCH_PAGE_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/search-page.tsx"), "utf8");
const QA_PANEL_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/qa-panel.tsx"), "utf8");
const QUIZ_PANEL_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/quiz-panel.tsx"), "utf8");
const ARENA_PANEL_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/arena-panel.tsx"), "utf8");
const PROJECTS_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/projects-studio.tsx"), "utf8");
const DASHBOARD_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/learning-dashboard.tsx"), "utf8");

test("public study inputs expose explicit accessible labels", () => {
  assert.match(NOTES_PANEL_SOURCE, /aria-label="Lesson note"/);
  assert.match(SEARCH_PAGE_SOURCE, /aria-label="Search query"/);
  assert.match(QA_PANEL_SOURCE, /aria-label="Question for this lesson"/);
  assert.match(QUIZ_PANEL_SOURCE, /aria-label=\{`Answer for question \$\{index \+ 1\}: \$\{question\.prompt\}`\}/);
  assert.match(ARENA_PANEL_SOURCE, /aria-label="Code answer"/);
});

test("builder, dashboard, and project workspaces label authored text fields", () => {
  assert.match(BUILDER_SOURCE, /aria-label="Caption for the shared learning map"/);
  assert.match(PROJECTS_SOURCE, /aria-label="Submission title"/);
  assert.match(PROJECTS_SOURCE, /aria-label="Solution summary"/);
  assert.match(PROJECTS_SOURCE, /aria-label="Implementation notes"/);
  assert.match(PROJECTS_SOURCE, /aria-label="Peer review feedback"/);
  assert.match(DASHBOARD_SOURCE, /aria-label="Most important outcome for this session"/);
  assert.match(DASHBOARD_SOURCE, /aria-label="Current blocker"/);
  assert.match(DASHBOARD_SOURCE, /aria-label="Prompt for the AI coach"/);
});

test("builder slot names include the visible slot content and transcript segments use native list semantics", () => {
  assert.match(BUILDER_SOURCE, /aria-label=\{`\$\{slot\.label\}\. \$\{slot\.description\}\. \$\{slotStatusText\}`\}/);
  assert.match(VIDEO_PANEL_SOURCE, /<ol className="transcript-list">/);
  assert.match(VIDEO_PANEL_SOURCE, /<li key=\{chapter\.id\}>/);
  assert.doesNotMatch(VIDEO_PANEL_SOURCE, /role="list"/);
});
