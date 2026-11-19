# ADR-005: Abstention gate

## Context

RevB treats weak-evidence abstention as a correct first-class outcome, not a generic error message.

## Decision

`ClaimGate` fails closed. It accepts only answer sentences with adequate overlap to at least one retrieved span; otherwise it emits a transparent `abstain` decision with reason and stores the failed claim bindings.

## Consequences

Coverage may decline, especially with provider-generated prose. This is deliberate: evidence digest/follow-up clarification is preferable to presenting an unsupported answer as grounded. Human evaluation remains the definitive faithfulness measurement.

## Revision 2026-11-19 (Phase 3)

The text above is kept as history.
- **The overlap `ClaimGate` is removed** (plan 3.4: "overlap rebinding removed", R-13). So is its `evidence_digest` fallback. Nothing binds a sentence to whichever retrieved span shares its words.
- **`app/services/claim_gate.py` is now the segment subset checker**, rule `segment-exact-normalised-v1` (plan Phase 3 E: "claim_gate becomes the subset checker"). Every factual segment of a rendered two-pass response must equal a locked claim after whitespace and NFKC normalisation. Every citation must be one of that claim's locked spans. Questions and connectives are typed by the renderer. An unmapped factual sentence makes the pipeline re-render, at most twice (plan 3.7); then it abstains with `subset_check_failed`.
- **Abstention reasons** come from the two-pass pipeline vocabulary (`ABSTENTION_REASONS` in `tutor_pipeline/contracts.py`): the gate's retrieval reasons, plus `corpus_version_mismatch`, `no_quotable_evidence`, `claim_plan_invalid`, `no_claims`, `no_bound_claims`, `subset_check_failed` and `budget_exceeded`. The legacy contained path keeps `no_approved_span`.
- **Delivery.** Learners still receive only the D-19 contained answer. The two-pass pipeline runs in shadow until the Phase 4 exit.
- **Next.** The full rewrite of this ADR, with the V1 checks (V1.3-V1.9) and the sufficiency gate V1.5, is Phase 4 (plan Phase 4 F).
