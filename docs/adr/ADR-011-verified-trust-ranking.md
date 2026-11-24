# ADR-011: Verified-trust ranking and drift control

## Context

Plan Phase 9 asks for "a ranking controller fed only by completed verification outcomes [Evidence E-89]" with the paper's
Table XI defaults, deadband promotion, immediate demotion, a CUSUM drift alarm, re-commissioning on a model change and a
fallback for an empty eligible set (plan Phase 9 A, D). Live routing is an OPEN decision (D-28, hold H11), the freeze
(D-05) holds, only one generator is wired (D-12, hold H6) and no non-fake generate-capable model exists (D-07).

## Decision 2026-11-23 (Phase 9: verified-trust ranking, shadow only)

- One ranking module, `apps/api/app/services/ranking/`, with a pure controller (`controller.apply(state, event)`): every
  input is an append-only, hash-chained `ranking_events` row and every decision a derived row after it, so the state is a
  function of the log (AC-9-8). Arithmetic is Decimal in a fixed local context; the Beta quantile is a 60-step bisection
  over the regularized incomplete beta function; randomness is a seeded sha256 draw. No language model decides a rank.
- Inputs are completed verdicts only: a skip changes only its counter (AC-9-1); y = 1 only for an uncorrected first pass;
  learner feedback feeds F, the quality term, only (AC-9-2).
- Algorithm 1 is evaluated when the ranking scan reads each ledger record; the decisions are recorded, never acted on for
  a learner: static assignment (`extractive-d19-v1`) keeps generating every record. `RANKING` is `off` outside
  development, `shadow` in development, and `on` (live routing) is refused everywhere while D-28 is open.
- Drift: a Bernoulli CUSUM per model and per (model, cluster); an alarm goes through Phase 6's `record_cusum_alarm` (X5),
  holds promotions until its window closes, and never demotes. A model-version change deflates trust by 0.3 and caps the
  model at C until a recorded shadow golden regression passes.
- An empty eligible set abstains and enqueues a V3 item (`ranking_empty_eligible_set`); no pre-verified store exists (DI-83).
- Every parameter is the configuration package v7 `ranking` block (`ranking-params-v1`, provisional, PD-50..PD-59), carried
  into the event log by a `config` event; a replay mismatch stops the ranking until an operator clears it (plan L).

## Consequences

- The controller can be replayed and audited offline; a committed synthetic replay report is checked in CI.
- Nothing a learner sees changes; development shadow records gain no field (the ledger schema is unchanged).
- The ranking runs only when the operator commissions the static generator and runs the scan (no scheduler, DI-125).

## Residuals

Plan Phase 9 M: "[Risk R-23][Risk R-24][Risk R-20][Risk R-47]; residual: silent provider changes."
- Plan Phase 9 A: If ranking does not beat static assignment (H4a), static assignment stays [VBT RevB: p. 19, Sec. X-D,
  Table XVIII, H4a]. Static assignment is the only serving path until D-28 is decided on the E4 report (DI-118).
- Every value is provisional until the E4 data re-estimate it (DI-117); topic clusters are an OPEN decision (DI-116).
- A silent provider change (a model served under an unchanged version) is not detected by the version check; the CUSUM
  is the only defence, and no provider model is registered yet.
- MR-1..MR-3 are not asserted: the switch rate is an engineering measurement on synthetic streams (invariant 9).
