import assert from "node:assert/strict";
import test from "node:test";

import { createLearnerRecordOperation, synchronizeLearnerRecord } from "../src/lib/learner-record-sync";

const replica = "replica-" + "a".repeat(32);

test("Phase 8 sync confirms a stored unused replica and follows the observed clock", async (t) => {
  const storage = new Map([
    ["qcai-learner-record-replica", replica],
    ["qcai-learner-record-clock", "7"],
  ]);
  const original = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", { configurable: true, value: { localStorage: {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
  } } });
  t.after(() => {
    if (original) Object.defineProperty(globalThis, "window", original);
    else Reflect.deleteProperty(globalThis, "window");
  });
  let observed = {};
  let issuances = 0;
  t.mock.method(globalThis, "fetch", async (input: string, options?: RequestInit) => {
    if (input.endsWith("/replicas")) {
      issuances += 1;
      assert.deepEqual(JSON.parse(String(options?.body)), { preferred_replica_id: replica });
      return Response.json({ replica_id: replica }, { status: 201 });
    }
    return Response.json({ user_id: "fixture-principal", record_version: 0, version_vector: observed });
  });
  const first = await createLearnerRecordOperation("complete_item", { item_id: "one" });
  assert.deepEqual([first.replica_id, first.logical_counter, first.causal_vector], [replica, 8, {}]);
  observed = { [replica]: 11 };
  const second = await createLearnerRecordOperation("complete_item", { item_id: "two" });
  assert.deepEqual([second.replica_id, second.logical_counter, second.causal_vector], [replica, 12, { [replica]: 11 }]);
  assert.equal(issuances, 1);
});

test("Phase 8 sync sends its expected version and retries once only after that version advances", async (t) => {
  const writes: number[] = [];
  let reads = 0;
  let after = 3;
  const stub = t.mock.method(globalThis, "fetch", async (_input: string, options?: RequestInit) => {
    if (options?.method === "POST") {
      const body = JSON.parse(String(options.body));
      writes.push(body.expected_record_version);
      if (writes.length === 1) return Response.json({ detail: "conflict" }, { status: 409 });
      return Response.json({ receipts: [], record: { record_version: 4 } });
    }
    reads += 1;
    return Response.json({ user_id: "fixture-principal", record_version: reads === 1 ? 2 : after });
  });
  const ops = [{ operation_id: "fixture-operation", replica_id: replica, logical_counter: 1,
                 causal_vector: {}, operation_type: "complete_item" as const, payload: { item_id: "lesson" } }];
  assert.equal((await synchronizeLearnerRecord(ops)).record.record_version, 4);
  assert.deepEqual(writes, [2, 3]);
  writes.length = reads = 0;
  after = 2;
  await assert.rejects(synchronizeLearnerRecord(ops));
  assert.deepEqual(writes, [2]);
  assert.equal(stub.mock.callCount(), 7);
});
