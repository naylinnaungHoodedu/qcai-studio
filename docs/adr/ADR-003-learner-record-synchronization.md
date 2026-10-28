# ADR-003: Learner Record synchronization

## Context

RevB §6.1 rejects last-write-wins for completions/attempts/mastery and requires convergence under randomized interleavings.

## Decision

Use append-only idempotent learner-record operations with a logical counter and replica ID. Materialization uses maximum mastery, set-union completions, grow-only per-replica counters, and logical-clock LWW only for cursor/preferences.

## Consequences

The data model and test load are larger than a dashboard aggregate, but stale devices cannot erase a completion. `LearnerRecordOperation` supplies a replayable audit trail.
