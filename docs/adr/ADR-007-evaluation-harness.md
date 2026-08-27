# ADR-007: Evaluation harness

## Context

RevB §§8.1-8.5 require a frozen 120-200 item LQS, ratings protocol, four-arm ablation, Wilson intervals, and paired McNemar comparisons.

## Decision

Keep evaluation code, schema, rubric, manifests, and reports versioned under `evaluation/` and `lqs/`. Keep restricted evidence and participant information external/controlled. Draft validation may run before freeze, but strict validation fails until the required instrument is complete.

## Consequences

The harness is reproducible without publicly redistributing licensed text. RC1 working data can be imported only after a rights/rater review; it is not automatically promoted to a final LQS.
