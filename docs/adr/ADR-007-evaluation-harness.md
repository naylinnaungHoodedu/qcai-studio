# ADR-007: Evaluation harness

## Context

RevB §§8.1-8.5 require a frozen 120-200 item LQS, ratings protocol, the seven-arm ablation of Table XV, Wilson intervals, and paired McNemar comparisons with Holm correction.

## Decision

Keep evaluation code, schema, rubric, manifests, and reports versioned under `evaluation/` and `lqs/`. Keep restricted evidence and participant information external/controlled. Draft validation may run before freeze; the strict ULQS freeze check runs only in the research plane and fails until the required instrument is complete.

## Consequences

The harness is reproducible without publicly redistributing licensed text. RC1 working data can be imported only after a rights/rater review; it is not automatically promoted to a final LQS.

## Revision 2026-11-24 (Phase 10)

- The seven Table XV arms (`NR`, `LEX`, `SEM`, `GATE`, `GATE+SV`, `GATE+V1`, `VLOOP`) are data
  (`evaluation/config/arms_v1.json`): GATE's configuration plus a declared ablation, with a parity check (AC-10-2). They
  replace the four A-D arms.
- ULQS v1.0 (`lqs/ulqs-v1.0.schema.json`, `evaluation/qcai_eval/ulqs.py`) replaces the legacy LQS for E1-E4; the strict
  freeze check (`scripts/validate_ulqs.py --freeze`) runs only in the research plane, and public CI validates the
  synthetic fixture (plan 6.1: public CI checks schemas on non-licensed stubs only).
- The runner pins the package, items, catalog, arms and analysis plan by sha256, hashes its seeds and repeats stub and
  recorded runs byte for byte; live and confirmatory runs are refused until their conditions hold (ADR-012).
