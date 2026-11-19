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
- **`app/services/claim_gate.py` is now the segment subset checker**, rule `segment-exact-whitespace-v2` (plan Phase 3 E: "claim_gate becomes the subset checker"). Every factual segment of a rendered two-pass response must name a locked claim and carry that claim's text exactly, whitespace runs aside: the text is never NFKC-folded, so a rendering that turns "x²" into "x2" is an unmapped factual sentence (ADR-001 revision; spec conflict 32). Every citation must be one of that claim's locked spans. A rendering must also show at least one locked claim, and each claim it shows must carry at least one of its own spans; a renderer may leave a claim out, and the ledger records which claims and spans it showed. Questions and connectives are typed by the renderer. A failed check makes the pipeline re-render, at most twice (plan 3.7); then it abstains with `subset_check_failed`.
- **Rule ids.** The first id, `segment-exact-normalised-v1`, compared NFKC-folded text. It was replaced before any release, so no ledger record names it; `segment-exact-whitespace-v2` names the behaviour above, and `package_check` fails when the package names another id (Phase 3 spec 18.6 D4, D7).
- **Abstention reasons** come from the two-pass pipeline vocabulary (`ABSTENTION_REASONS` in `tutor_pipeline/contracts.py`): the gate's retrieval reasons, plus `corpus_version_mismatch`, `no_quotable_evidence`, `claim_plan_invalid`, `no_claims`, `no_bound_claims`, `subset_check_failed` and `budget_exceeded`. The legacy contained path keeps `no_approved_span`.
- **Delivery.** Learners still receive only the D-19 contained answer. The two-pass pipeline runs in shadow until the Phase 4 exit.
- **Next.** The full rewrite of this ADR, with the V1 checks (V1.3-V1.9) and the sufficiency gate V1.5, is Phase 4 (plan Phase 4 F).
