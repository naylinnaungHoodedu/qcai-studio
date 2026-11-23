# Phase 6 evaluation records

`v3_residual_report_v1.json` is the V3 residual report (plan Phase 6 F "residual report"; AC-6-2, AC-6-5; `docs/architecture/phase6-implementation-spec.md` 12.1). It is **synthetic telemetry, not research results**: plan Phase 6 H says "audit counts are telemetry, not research results". HR-3's study form ("Wilson upper bound <=3% on residual error in the study's V3 audit") is Phase 10's; this record shows the deployment form's arithmetic (plan 15.3 "monthly Wilson bound from the 5% draw") on synthetic deliveries.

**Scenario.** The template is the legacy ledger entry of the contained answer to in-domain fixture query 0 (`apps/api/tests/data/score_floor_queries.json`) under the public-payload capture's configuration b (ENVIRONMENT=production, governance on, a temporary manifest approving every public-plane, bound item: the p1-floor gate); the script asserts it is an answer that records its gate score, is not X4-marked and cites only spans a reviewer is shown. 6070 copies, `turn-{UUID(int=i)}` for i = 1..6070, are appended to an in-memory ledger and scanned with `V3_QUEUE=shadow` in development: the seeded draw (`seeded-sha256-bernoulli-v1`, seed `qcai-x6-v1`, 1/20) draws 300 (inside Bin(6070, 0.05)'s 99% band, 261-348), and a same-seed replay draws the same ids. Synthetic reviewers adjudicate every X6 item with every claim SUPPORTED (the double-review items get a second, agreeing review by another synthetic reviewer) and a third applies them. The Wilson 95% upper bound of 0 errors in 300 audited answers is 0.012642971224546034, below 0.013 (AC-6-5), and the API's Wilson interval equals the evaluation harness's (`harness_equal`). The gold chain verifies and no ledger row changes.

**Reproduce.**

```
python scripts/run_v3_residual_report.py --check docs/evaluation/phase6/v3_residual_report_v1.json
python scripts/run_v3_residual_report.py --write docs/evaluation/phase6/v3_residual_report_v1.json   # a clean tree, or --allow-dirty
```

`--check` compares the record with a fresh run, `created_at`, `commit`, `inputs` and `gold.head_record_hash` aside, and the record's `inputs` (the LF sha256 of every imported repository module) with the checkout. The gold head hash covers keyed digests, which depend on the guest-token secret, so it is informational; `gold.verified` is compared. Exit codes: 0 pass, 1 drift, 3 a stop, 4 a dirty tree on `--write`. CI runs the check in `api-and-evaluation`.
