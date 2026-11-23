import { LearnerRecordOperation } from "@/lib/types";
import { fetchLearnerRecord, postLearnerRecordOperations } from "@/lib/api";
import { issueLearnerRecordReplica } from "@/lib/learner-record-api";

const REPLICA_STORAGE_KEY = "qcai-learner-record-replica";
const CLOCK_STORAGE_KEY = "qcai-learner-record-clock";
const pendingReplicas = new Map<string, Promise<string>>();

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

export async function createLearnerRecordOperation(
  operationType: LearnerRecordOperation["operation_type"],
  payload: Record<string, unknown>,
): Promise<LearnerRecordOperation> {
  const record = await fetchLearnerRecord();
  let pending = pendingReplicas.get(record.user_id);
  if (!pending) {
    const storedReplica = safeRead(REPLICA_STORAGE_KEY);
    const preferred = storedReplica && /^replica-[a-f0-9]{32}$/.test(storedReplica) ? storedReplica : undefined;
    pending = issueLearnerRecordReplica(preferred).then(({ replica_id }) => {
      if (storedReplica !== replica_id) safeWrite(CLOCK_STORAGE_KEY, "0");
      safeWrite(REPLICA_STORAGE_KEY, replica_id);
      return replica_id;
    }).catch((error) => {
      pendingReplicas.delete(record.user_id);
      throw error;
    });
    pendingReplicas.set(record.user_id, pending);
  }
  const replicaId = await pending;
  const observed = record.version_vector[replicaId] ?? 0;
  const stored = safeRead(REPLICA_STORAGE_KEY) === replicaId ? Number(safeRead(CLOCK_STORAGE_KEY) ?? "0") : 0;
  const logicalCounter = Math.max(observed, Number.isSafeInteger(stored) ? stored : 0) + 1;
  safeWrite(CLOCK_STORAGE_KEY, String(logicalCounter));
  return {
    operation_id: `op-${crypto.randomUUID()}`,
    replica_id: replicaId,
    logical_counter: logicalCounter,
    causal_vector: observed ? { [replicaId]: observed } : {},
    operation_type: operationType,
    payload,
  };
}

export async function synchronizeLearnerRecord(operations: LearnerRecordOperation[]) {
  const before = await fetchLearnerRecord();
  try {
    return await postLearnerRecordOperations(operations, before.record_version);
  } catch (error) {
    const current = await fetchLearnerRecord();
    if (current.user_id !== before.user_id || current.record_version <= before.record_version) throw error;
    return postLearnerRecordOperations(operations, current.record_version);
  }
}
