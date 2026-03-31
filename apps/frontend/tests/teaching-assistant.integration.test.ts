import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";


const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const APP_SHELL_SOURCE = readFileSync(resolve(TEST_DIR, "../src/components/app-shell.tsx"), "utf8");
const API_SOURCE = readFileSync(resolve(TEST_DIR, "../src/lib/api.ts"), "utf8");
const ASSISTANT_SOURCE = readFileSync(
  resolve(TEST_DIR, "../src/components/teaching-assistant-chat.tsx"),
  "utf8",
);
const GLOBAL_CSS_SOURCE = readFileSync(resolve(TEST_DIR, "../src/app/globals.css"), "utf8");

test("app shell mounts the global teaching assistant widget", () => {
  assert.match(APP_SHELL_SOURCE, /import \{ TeachingAssistantChat \} from "@\/components\/teaching-assistant-chat";/);
  assert.match(APP_SHELL_SOURCE, /<TeachingAssistantChat \/>/);
});

test("frontend API client exposes the teaching assistant chat helper", () => {
  assert.match(API_SOURCE, /export async function chatWithTeachingAssistant/);
  assert.match(API_SOURCE, /apiFetch<AssistantChatResponse>\("\/assistant\/chat"/);
});

test("teaching assistant widget uses page context and renders the expected product copy", () => {
  assert.match(ASSISTANT_SOURCE, /usePathname/);
  assert.match(ASSISTANT_SOURCE, /Quantum Teaching Assistant/);
  assert.match(ASSISTANT_SOURCE, /Online &amp; ready to help/);
  assert.match(ASSISTANT_SOURCE, /chatWithTeachingAssistant/);
  assert.match(ASSISTANT_SOURCE, /page_path: pathname/);
  assert.match(ASSISTANT_SOURCE, /lesson_slug: lessonSlug/);
  assert.match(ASSISTANT_SOURCE, /Ask about quantum computing\.\.\./);
  assert.match(ASSISTANT_SOURCE, /Ask me about qubits, gates, algorithms, or our course materials\./);
});

test("teaching assistant widget removes provider metadata and the old context chrome", () => {
  assert.doesNotMatch(ASSISTANT_SOURCE, /className="assistant-bubble-meta"/);
  assert.doesNotMatch(ASSISTANT_SOURCE, /\{message\.provider\} \| \{message\.model\}/);
  assert.doesNotMatch(ASSISTANT_SOURCE, /assistant-context-row/);
  assert.doesNotMatch(ASSISTANT_SOURCE, /assistant-prompt-row/);
});

test("teaching assistant widget exposes dialog semantics and keyboard-safe controls", () => {
  assert.match(ASSISTANT_SOURCE, /aria-controls="teaching-assistant-panel"/);
  assert.match(ASSISTANT_SOURCE, /id="teaching-assistant-panel"/);
  assert.match(ASSISTANT_SOURCE, /role="dialog"/);
  assert.match(ASSISTANT_SOURCE, /aria-modal="false"/);
  assert.match(ASSISTANT_SOURCE, /role="log"/);
  assert.match(ASSISTANT_SOURCE, /aria-busy=\{isSending\}/);
  assert.match(ASSISTANT_SOURCE, /textareaRef/);
  assert.match(ASSISTANT_SOURCE, /\.focus\(\)/);
  assert.match(ASSISTANT_SOURCE, /event\.key === "Escape"/);
});

test("teaching assistant launcher hides while the drawer is open", () => {
  assert.match(ASSISTANT_SOURCE, /\{!isOpen \? \(/);
  assert.match(ASSISTANT_SOURCE, /onClick=\{openAssistant\}/);
});

test("teaching assistant layout keeps the panel bounded and the transcript scrollable", () => {
  assert.match(
    GLOBAL_CSS_SOURCE,
    /\.assistant-shell\s*\{[\s\S]*display:\s*flex;[\s\S]*align-items:\s*flex-end;[\s\S]*gap:\s*16px;/,
  );
  assert.match(
    GLOBAL_CSS_SOURCE,
    /\.assistant-panel\s*\{[\s\S]*grid-template-rows:\s*auto minmax\(0,\s*1fr\) auto;[\s\S]*overflow:\s*hidden;/,
  );
  assert.match(
    GLOBAL_CSS_SOURCE,
    /\.assistant-transcript-surface\s*\{[\s\S]*min-height:\s*0;/,
  );
  assert.match(
    GLOBAL_CSS_SOURCE,
    /\.assistant-transcript\s*\{[\s\S]*min-height:\s*0;[\s\S]*overflow-y:\s*auto;/,
  );
  assert.match(
    GLOBAL_CSS_SOURCE,
    /\.assistant-compose-input\s*\{[\s\S]*grid-template-columns:\s*minmax\(0,\s*1fr\) auto;/,
  );
  assert.match(
    GLOBAL_CSS_SOURCE,
    /\.assistant-send-button\s*\{[\s\S]*width:\s*48px;[\s\S]*height:\s*48px;/,
  );
  assert.match(
    GLOBAL_CSS_SOURCE,
    /@media \(max-width: 640px\)\s*\{[\s\S]*\.assistant-shell\s*\{[\s\S]*flex-direction:\s*column;/,
  );
  assert.match(
    GLOBAL_CSS_SOURCE,
    /@media \(max-width: 640px\)\s*\{[\s\S]*\.assistant-panel\s*\{[\s\S]*width:\s*min\(100vw - 16px,\s*430px\);/,
  );
});
