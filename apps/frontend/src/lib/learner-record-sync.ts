import { LearnerRecordOperation } from "@/lib/types";

const REPLICA_STORAGE_KEY = "qcai-learner-record-replica";
const CLOCK_STORAGE_KEY = "qcai-learner-record-clock";

function safeRead(key: string): string | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeWrite(key: string, value: string): void {
  try {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(key, value);
    }
  } catch {
    // Private browsing or disabled storage leaves the server API usable.
  }
}

export function getLearnerRecordReplicaId(): string {
  const existing = safeRead(REPLICA_STORAGE_KEY);
  if (existing && /^[A-Za-z0-9_.:-]{8,128}$/.test(existing)) {
    return existing;
  }
  const replicaId = `browser-${crypto.randomUUID()}`;
  safeWrite(REPLICA_STORAGE_KEY, replicaId);
  return replicaId;
}

export function nextLearnerRecordClock(): number {
  const current = Number.parseInt(safeRead(CLOCK_STORAGE_KEY) ?? "0", 10);
  const next = Number.isFinite(current) ? Math.max(0, current) + 1 : 1;
  safeWrite(CLOCK_STORAGE_KEY, String(next));
  return next;
}

export function createLearnerRecordOperation(
  operationType: LearnerRecordOperation["operation_type"],
  payload: Record<string, unknown>,
): LearnerRecordOperation {
  const replicaId = getLearnerRecordReplicaId();
  const logicalCounter = nextLearnerRecordClock();
  return {
    operation_id: `op-${crypto.randomUUID()}`,
    replica_id: replicaId,
    logical_counter: logicalCounter,
    causal_vector: { [replicaId]: logicalCounter - 1 },
    operation_type: operationType,
    payload,
  };
}
