# V3 trigger registry v1

The escalation triggers, the queue and the audit draw of configuration package v5 (`v3` block; plan Phase 6 F "trigger registry v1"; `docs/architecture/phase6-implementation-spec.md` 3.3, 4.1-4.5, 5.1; PD-32 to PD-37). Every value is provisional and ratified under DI-98. `apps/api/tests/test_phase6_acceptance.py::test_plan_f_the_trigger_registry_document_matches_the_package` compares this page with the package.

Registry `x-triggers-v1`. V-3 counts X1-X4 only; X5 and X6 audits are proof tests (plan 15.3 "V-3 numerator counts X1-X4 only; audits are proof tests [Evidence E-85]."; PD-37).

| Trigger | Rule id | Source in the ledger record | Subject | Holds | V-3 |
|---|---|---|---|---|---|
| X1 | `critical-claim-objection-v1` | a claim whose V2 verdict marks it `critical` (the environment's registry, D-25), at tiers 1, 2 and 3 (plan AC-5-4 "critical claims follow X1 from Phase 6"), that drew a family objection: on its final verdict, or a claim-loop correction cycle that listed it | claim | at tier 1 only (plan task 1 "withheld at tier 1"): never delivered (the runner's sticky hold), withheld until Phase 7 change control; at tier 2 or 3 queued, not held | counted |
| X2 | `v2-exhausted-type-a-b-v1` | a claim escalated `X2` (V2 correction exhausted) whose final verdict has an objecting family verdict of EHMF type A or B | claim | no (the record already abstains it) | counted |
| X3 | `learner-flag-f0-v1` | a learner flag on their own tutor turn (`POST /v3/flags`, development only); F_i = 0, never a verdict | response | no | counted |
| X4 | `v1-5-margin-mark-v1` | the record's V1.5 `near_miss` mark, or V1.5's rule over a legacy record's sufficiency with the package's `v1.v1_5.x4_margin` for its gate | response | no | counted |
| X5 | `model-version-change-or-cusum-alarm-v1` | a model-version change of a known model key (the registry's verifiers, a record's verifier, generator or V1.3 checker) or a CUSUM alarm (`cusum-alarm-v1`, Phase 9's statistic): the next 1500 learner deliveries are drawn at 1/5 | response (the drawn delivery) | no | proof test |
| X6 | `seeded-sha256-bernoulli-v1` | the seeded audit draw at 1/20 over learner deliveries | response | no | proof test |

**Queue reasons without a trigger** (queued, not counted in V-3), each read from the record's own V3 intent: `v1_3_flag` (under `MODEL_GATEWAY=on` the V2 aggregate drops it once a vote completes; a V2-shadow record keeps Phase 4's D-20 intent, so its V1.3-withheld claims are queued), `v1_8_misconception`, `v2_correction_exhausted` (an exhausted claim without an A or B objection) and `v2_degraded_withheld`. A record's X4 mark is its response item, never a claim reason.

**Items.** One item per (ledger record, claim) or per record. A later trigger merges into an open item; on a closed item it is recorded and the item is not reopened. An item's exposure is its record's: an item created before the scan drew its record (an X3 flag) is raised to the record's full count when the scan draws it.

## Priority

Rule `severity-exposure-one-minus-k-v1`: priority = severity x exposure x (1 - K), in exact rationals; ties by enqueue time, then item id. The EHMF weights are plan 6.3's, which "await expert elicitation" (bound while D-06 is open; PD-34).

| Weight | Value |
|---|---|
| A | 1.0 |
| B | 1.0 |
| C | 0.6 |
| D | 0.6 |
| E | 0.4 |
| unknown | 1.0 |
| disclosed_conflict | 0.0 |

- Severity: the largest weight among an item's EHMF types (V2 objections and non-pass V1 results; a disclosed V1.7 conflict weighs 0), `unknown` when none is known.
- Exposure, rule `learner-deliveries-of-claim-set-v1`: the learner deliveries the scan considered whose claim-set key equals the record's (rule `sorted-claim-ids-sha256-v1`: the sha256 of the record's sorted claim ids), up to the record, at least 1; 1 for a shadow or abstention record.
- K, rule `panel-support-share-v1`: the claim's V2 panel support share (families voting SUPPORTED over members), the mean over a response's claims, 0 without a panel vote.

## Draw

Rule `seeded-sha256-bernoulli-v1`, seed `qcai-x6-v1`: a delivery is drawn at rate num/den when the first 8 bytes of sha256("x6-draw-v1|seed|response_id") as an integer u satisfy u x den < num x 2^64. X6 at 1/20; while an X5 window is open, 1/5 (below 1/20 is X6, between 1/20 and 1/5 is X5); a window covers the 1500 learner deliveries after its event. Every learner delivery (legacy or delivered) is considered once, at its first scan; deliveries before the ledger are not auditable. The seed is public by design: the key is the response id the server mints at delivery (`turn-{uuid4()}`, `qa-{uuid4()}`), so knowing the seed lets no caller choose which deliveries are audited.

## Workflow, SLO and stop

- States queued, claimed (a live 1800 s lease), adjudicated, applied. 1/10 of items get an independent second review (double review 1/10, rule `seeded-sha256-bernoulli-v1` on the item id, purpose `double-review-v1`; operator policy under D-06); a disagreeing pair goes to a third reviewer. No reviewer reviews an item twice and no adjudicator applies it. Applying exports the final label as recalibration input and releases nothing (Phase 7 change control, DI-93).
- Queue-age SLO 259200 s (72 hours). The stop holds when the oldest open item is older than the SLO at every 3600 s sample of the last 172800 s (two days): tier 1 runs pre-verified-only (with no pre-verified source, every tier-1 claim is withheld). The queue-age alert's measure is the p90 (DI-95).
- V-3 at most 1/10 over a rolling 7-day window; the residual bound is the Wilson 95% upper bound over X6-audited answer deliveries per UTC month. Both are report only.
