import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function source(path: string): string {
  return readFileSync(resolve(root, path), "utf8");
}

test("client API exposes persistent Tutor and durable Learner Record contracts", () => {
  const api = source("src/lib/api.ts");
  const types = source("src/lib/types.ts");

  assert.match(api, /fetchTutorThreads/);
  assert.match(api, /fetchTutorThread/);
  assert.match(api, /postLearnerRecordOperations/);
  assert.match(api, /thread_id: payload\.thread_id/);
  assert.match(types, /export type LearnerRecordOperation/);
  assert.match(types, /decision\?: "answer" \| "abstain" \| "clarify"/);
});

test("Tutor UI resumes the latest persisted thread and reports grounding decisions", () => {
  const component = source("src/components/teaching-assistant-chat.tsx");

  assert.match(component, /fetchTutorThreads\(\)/);
  assert.match(component, /fetchTutorThread\(latest\.id\)/);
  assert.match(component, /thread_id: threadId/);
  assert.match(component, /grounding_decision/);
  assert.match(component, /evidence is not strong enough to answer/);
});

test("Learner-record client operations carry replica and logical-clock metadata", () => {
  const sync = source("src/lib/learner-record-sync.ts");

  assert.match(sync, /qcai-learner-record-replica/);
  assert.match(sync, /logical_counter/);
  assert.match(sync, /causal_vector/);
  assert.match(sync, /operation_id/);
});
