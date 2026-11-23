# ADR-003: Learner Record synchronization

## Context

RevB §6.1 rejects last-write-wins for completions/attempts/mastery and requires convergence under randomized interleavings.

## Decision

Use append-only idempotent learner-record operations with a logical counter and replica ID. Materialization uses maximum mastery, set-union completions, grow-only per-replica counters, and logical-clock LWW only for cursor/preferences.

## Consequences

The data model and test load are larger than a dashboard aggregate, but stale devices cannot erase a completion. `LearnerRecordOperation` supplies a replayable audit trail.

## Revision 2026-11-23 (Phase 8: server-issued replicas and compare-and-set)

Under PD-201 and `LEARNER_SYNC=on`, a durable principal presents a server-issued replica from `/learner-record/replicas` and an `expected_record_version`. The client and assessment writer serialize under the same learner-record lock. New operations from unissued or retired replicas, stale counters, the reserved server namespace, or client-authored mastery are refused. Exact receipts support replay, including after retirement. The browser preserves operation IDs and retries once after a re-read advances the version. Existing subject bindings survive flag rollback.
