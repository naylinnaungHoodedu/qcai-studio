# Phase 1 SLIs and the alert on overrides, from structured logs (plan Phase 1, item I)

Plan Phase 1, item I: "SLIs: auth failures, erasure time, governance_enforced, CI pass rate; alert on overrides."

The API and its jobs write one JSON object per line to stderr (`app/core/structured_logging.py`). Each line has:
- `severity`, `message`, `logger` and `time`;
- the record's own fields, which the platform keeps as queryable fields under `jsonPayload`.

Before this change the API configured no logging: INFO records were dropped, and warnings reached stderr as bare text.

**Not set up yet.** Creating log-based metrics and alert policies is a cloud write that needs the Platform Owner's approval. Nothing below has been run. The filters are written against the fields the code emits and the tests check. Check them in Logs Explorer against the first deployed revision's logs before creating anything.

## What is logged
| Source | Fields | Severity |
|---|---|---|
| Each recorded security event (`logger` `qcai.security`) | `event_type`, `outcome`, `actor_role`, `seq`, `hash`, `details`. **No subject or source digest**, so no identifier of any kind. | INFO for `success`, WARNING otherwise |
| A security event that could not be written to the database | `event_type`, `outcome`, `recorded: false`, plus the traceback in `message` | ERROR |
| API start-up, once per instance (`qcai.api`) | `event: "startup"`, `environment`, `governance_enforced`, `corpus_version`, `commit` | INFO |
| Retention job (`qcai.worker`) | `job: "retention"`, `status`, `deleted`, `duration_ms` | INFO, or ERROR with the traceback |
| Security-log verify job (`qcai.worker`) | `job: "security_log"`, `status`, `events`, `first_seq`, `last_seq`, `head_hash`, `problems`, `duration_ms` | INFO, or ERROR when broken |

Failure and denial events are capped at 60 a minute per type per instance. Events dropped by the cap are not logged either; the next logged event of that type carries `details.dropped_before`.

### Frontend server
In production the Next.js server writes its console output the same way (`apps/frontend/src/lib/server-log.ts`, installed by `src/instrumentation.ts`):
- each line has `severity`, `message`, `logger: "frontend"` and `time`, plus `digest` when Next.js gave the error one;
- warnings and errors go to stderr, everything else to stdout;
- a stack stays inside its entry, and credentials in a message are masked.

The few lines Next.js prints as it starts (its banner, two addresses, "Ready" and, since 16.4, the next.config timing) stay plain text. Development output is unchanged. No Phase 1 SLI is built from these lines. Two filters may still help, each after `resource.type="cloud_run_revision" AND resource.labels.service_name="qcai-frontend"`:
- `severity>=ERROR` finds server errors;
- `jsonPayload.digest="<digest>"` finds the entry for a digest seen in the browser.

## Filters
All the API filters start with `resource.type="cloud_run_revision" AND resource.labels.service_name="qcai-api"`. The jobs use `resource.type="cloud_run_job"`.

| SLI or alert | Filter (after the resource clause) | Kind |
|---|---|---|
| Auth failures | `jsonPayload.event_type=("auth.login" OR "auth.credential_rejected" OR "auth.lockout") AND jsonPayload.outcome!="success"` | Counter metric |
| Erasure time | `jsonPayload.event_type="account.delete" AND jsonPayload.outcome="success"`, value `jsonPayload.details.duration_ms` | Distribution metric. It times the erase and its commit, not the password check. |
| `governance_enforced` | `jsonPayload.event="startup" AND jsonPayload.governance_enforced=false` | Alert on any match. `/ready` reports the same field. |
| **Alert on overrides** | `jsonPayload.event_type="config.override"` (details name the override, such as `demo_auth_enabled`) | Alert on any match |
| Security events not recorded | `jsonPayload.recorded=false` | Alert on any match |
| Security log chain broken | `jsonPayload.job="security_log" AND jsonPayload.status!="ok"` | Alert on any match |
| Retention job failed | `jsonPayload.job="retention" AND jsonPayload.status="failed"` | Alert on any match |

**CI pass rate** is not in the platform logs. It comes from GitHub Actions: `gh run list --workflow cs595-quality-gates --branch main`.

## Phase 2 SLIs: retrieval and citations (plan Phase 2 I)

Plan Phase 2 I lists five SLIs: "citation resolution rate (100%), duplicate ids (0), abstention rate, search p95, manifest drift (0)".

**Not set up yet.** As above, creating any metric or alert is a cloud write that needs Platform Owner approval.

`/ready` reports, per instance:
- `duplicate_span_ids`, `manifest_drift`, `retrieval_gate`, `index_version`;
- the thresholds in force, which are the active gate's: `threshold_version`, `abstention_floor`, `abstention_margin`, `thresholds_provisional` and `threshold_authority` (P1-D-04 for `p1-floor`), plus the calibrated bm25f-v1 values under `bm25f_v1_calibrated`;
- `semantic_enabled` (effective: on only when this process aligned span-id vectors) and `semantic_setting` (the setting);
- `config_package_version` and `config_package_sha256`;
- a `slis` block. It holds citation resolution counts and rate, abstention decisions and rate by reason, the search latency p50 and p95 over the last 1000 decisions, and the start-up drift report.

| Source | Fields | Severity |
|---|---|---|
| Each retrieval (`logger` `qcai.retrieval`, `event: "retrieval.decision"`) | `surface`, `mode`, `gate`, `abstained`, `reason`, `results`, `near_floor`, `top_score`, `latency_ms`, `index_version`, `threshold_version`. **No query text and no identity.** | INFO |
| Citations per Q&A, assistant or tutor response, or per history read that withheld one (`logger` `qcai.citations`, `event: "citations.delivered"`) | `surface`, `delivered`, `dropped_unresolved`, `withheld_unapproved` | INFO, or WARNING when `dropped_unresolved` > 0 |
| A stored citation that no longer resolves (`event: "citations.unresolved_on_read"`) | none | WARNING |
| Manifest drift (`event: "corpus.drift"`) | `item_id` or `drifted`, `details` | WARNING in development; start-up fails in a governed build |
| Semantic index misaligned (`event: "semantic.misaligned"`) | `expected`, `found` | WARNING |
| Semantic setting on but this process not aligned, at start-up (`event: "semantic.inactive"`) | none | WARNING |
| Recall stop overridden, at start-up (`event: "retrieval.recall_stop_overridden"`) | `items` | WARNING |
| Configuration package hash mismatch in development (`event: "config_package.hash_mismatch"`) | `path`, `sha256` | WARNING |
| Span registration and citation migration jobs (`qcai.worker`) | `job` (`register_spans` or `migrate_citations`), `status`, counts, `duration_ms` | INFO, or ERROR on failure |

| SLI | Filter (after the API resource clause) | Kind |
|---|---|---|
| Abstention rate | `jsonPayload.event="retrieval.decision"`, ratio of `jsonPayload.abstained=true` | Counter metrics (two) |
| Search p95 | `jsonPayload.event="retrieval.decision"`, value `jsonPayload.latency_ms` | Distribution metric |
| Citation resolution rate (100%) | `jsonPayload.event="citations.unresolved_on_read"` | Alert on any match |
| Duplicate ids (0), manifest drift (0) | `jsonPayload.event="startup" AND (jsonPayload.duplicate_span_ids>0 OR jsonPayload.manifest_drift>0)` | Alert on any match |
| Phase 2 overrides | `jsonPayload.event_type="config.override"`. The details name `retrieval_gate_bm25`, `p1_floor_recall_stop_overridden`, `semantic_retrieval_enabled`, `span_resolver_route_enabled`, `citation_provisional_lift_enabled`, `config_package_path_overridden` or `config_package_hash_unverified`. | Alert on any match |

## Creating them (Platform Owner approval each time)
A counter metric, for example:

```bash
gcloud logging metrics create qcai-auth-failures --project naylinnaung \
  --description "Phase 1 SLI: failed or rejected sign-ins and credentials" \
  --log-filter 'resource.type="cloud_run_revision" AND resource.labels.service_name="qcai-api" AND jsonPayload.event_type=("auth.login" OR "auth.credential_rejected" OR "auth.lockout") AND jsonPayload.outcome!="success"'
```

For the distribution metric and the "any match" alerts, use log-based alerting policies in Cloud Monitoring, with a notification channel the Platform Owner chooses. Record each metric and policy created, with its filter, in the Phase 1 evidence.

## Privacy
The mirrored lines carry no learner identifier, digest, address or email. The privacy page says so in the security-event-log row. Platform log retention is set at the hosting layer.

## Phase 3 SLIs: ledger and shadow (plan Phase 3 I)

**Not set up yet.** Creating log-based metrics and alerts is a cloud write (Platform Owner approval each time).

Plan Phase 3 I: "Ledger writes 100% of deliveries; bound-claim ratio; abstention by reason; /ready reports versions".
- `/ready` reports the versions in force: `config_package_version`, `two_pass_tutor` (the effective mode) and `two_pass_tutor_setting`, `phase4_exit_passed`, the `tutor_pipeline` ids, prompt hashes, `subset_check` rule and `budgets` in force (`shadow_ms`, `ledger_append_ms`, and `overridden`, the budgets an environment override changed), and `ledger.status` (`ok` or `unavailable`). `/ready` is public, so it never shows the head's sequence number, the all-time count of tutor responses: that is in the `response_ledger` job line and in each `tutor.ledger.appended` line.
- `/ready` also reports the Phase 3 switches in force: `tutor_ledger_enabled`, `ledger_route_enabled`, `evidence_panel_enabled` and `tutor_turns_route_enabled` (each off outside development except `tutor_ledger_enabled`; a relaxation also logs a `config.override` event, below).
- `/ready` `slis.tutor_ledger` holds the **legacy** deliveries only (a shadow record is a shadow output, AC-3-6; spec 18.7 E15): `attempted`, `appended` and `failed` (`legacy`), `duplicates`, `conflicts`, `legacy_coverage_rate` (appended over attempted legacy deliveries; an attempt is counted once the delivery committed, so a request that rolls back is none, 18.7 E5), `legacy_by_surface` (the same counts and rate for tutor turns and for `/qa/ask` answers, which are ledgered too), `delivered` (what the legacy deliveries were, counted at the attempt whatever the append then did: `decisions` (`answer`, `abstain`), `abstention_rate` and `abstention_by_reason`, in all and `by_surface`; plan I "abstention by reason" over the responses learners got, spec 18.8 F1), `non_public_spans_excluded` (spans the license_class gate kept out of legacy and Q&A records; any non-zero count means an upstream guard failed) and `write_stop` (a legacy write failed or conflicted).
- `/ready` `slis.two_pass_shadow` holds only `scheduled` and `phase2_bound_claim_ratio_baseline` (1.0), which no run's outcome changes (spec 18.6 D9, 18.7 E15). `/ready` is public, and on a quiet instance a learner could compare it before and after a turn: with more fields they read the shadow's decision, reason and claim counts for that turn (D9), and also whether it completed or failed and at which step, whether its ledger append or its license gate failed, and whether it tripped the bound-claim stop (E15). All of those are in each run's log lines (`tutor.two_pass.shadow`, `tutor.two_pass.shadow_failed`, `tutor.ledger.append_failed`, `tutor.evidence.non_public_excluded`), which the log-based SLIs and alerts below aggregate, and in the in-process snapshots, which no route serves (tests only; spec 18.8 F16).
- These are per-instance counters; the log lines below aggregate across instances, and only they measure a stop for the whole service.

All Phase 3 events log on the `qcai.tutor` logger. They carry counts, hashes and enumerations only: no question, claim or rendered text, and no response, turn, thread or message id. The one id, `attempt`, is random per legacy ledger attempt and names nothing else: it pairs an attempt with its terminal line (spec 18.8 F11).

A legacy delivery's abstention reason (`abstention_reason` on `tutor.ledger.attempted`, and on its ledger record) is the retrieval gate's own reason when the gate returned nothing (`no_query_terms`, `no_match`, `insufficient_coverage`, `below_floor`), and `no_approved_span` only when the gate matched passages none of which could be quoted (not approved under D-31, or not verified). The Phase 2 `slis.abstention` counts the gate's decisions, not what was delivered: under D-31 it reads 0% while every delivery abstains with `no_approved_span` (spec 18.8 F1).

| Event | Fields | Severity |
|---|---|---|
| `tutor.ledger.attempted` | `delivery` (`legacy`), `decision` (`answer` or `abstain`), `abstention_reason` (null on an answer), `attempt`; `surface: qa` on a `/qa/ask` answer. One line per committed legacy delivery, logged after its commit and before its append (spec 18.7 E13; decision, reason and attempt since 18.8 F1, F11) | INFO |
| `tutor.ledger.appended` | `delivery`, `seq`, `record_hash`, `duplicate` (the off-database copy of the chain); `attempt` on a legacy line (its attempt's terminal line); `surface: qa` on a `/qa/ask` record (a tutor line has no `surface` field) | INFO |
| `tutor.ledger.append_failed` | `delivery`, `stage`, `error` (class); `attempt` on a legacy line (its attempt's terminal line); `surface: qa` on a `/qa/ask` record | ERROR, a plan L stop |
| `tutor.ledger.append_deferred` | `delivery`, `budget_ms`, `attempt`; `surface: qa` on a `/qa/ask` record (the learner was not held past the budget plus the package's `ledger_wait_grace_ms`, 250 ms). Not terminal: the attempt's `appended` or `append_failed` line follows when the append ends | WARNING |
| `tutor.evidence.non_public_excluded` | `surface` (`two_pass`, `legacy` or `qa`): a span whose derived license class is not public was left out | WARNING; alert on any match (an upstream guard failed) |
| `tutor.ledger.conflict` | `delivery` | ERROR |
| `tutor.two_pass.shadow` | `decision`, `reason`, `proposed` and `bound` (the record's raw counts: `bound` is the locked claims, so merged and budget-skipped claims are in `dropped`), `ratio_proposed` and `ratio_bound` (the plan L ratio terms, as `TwoPassMetrics` and the replay count them: a budget-skipped claim is in neither, a merged claim in both; public `/ready` carries no ratio since 18.7 E15), `dropped`, `attempts`, `plan_id`, `gate`, `latency_ms`, `seq` | INFO |
| `tutor.two_pass.shadow_failed` | `step`, `error` | ERROR |
| `tutor.two_pass.budget_exceeded` | `step`, `elapsed_ms`, `budget_ms` | WARNING |
| `tutor.two_pass.on_downgraded` | none | WARNING, once per process |
| `tutor.two_pass.unavailable` | `reason` | WARNING |
| Security event `ledger.reviewer_read` | `route`, `delivery` (actor role; subject digest) | success |
| Job `response_ledger` (`qcai.worker`) | `status`, `records`, `first_seq`, `last_seq`, `head_hash`, `head_row`, `appended_during_check` (appends that committed while it ran; never a problem), `problems`, `duration_ms`; `coverage` and `exported` when asked | INFO, or ERROR when broken |

| SLI | Filter (after the API resource clause, except the job row) | Kind |
|---|---|---|
| Ledger write failures (0) | `jsonPayload.event="tutor.ledger.append_failed"` (legacy and shadow; `jsonPayload.surface="qa"` for Q&A) | Alert on any match (plan L stop) |
| Ledger coverage (100%) | Every legacy attempt (`jsonPayload.event="tutor.ledger.attempted"`) ends in exactly one terminal line with its `attempt` id, logged when its append ends: `jsonPayload.event="tutor.ledger.appended" AND jsonPayload.delivery="legacy"` (recorded) or `jsonPayload.event="tutor.ledger.append_failed" AND jsonPayload.delivery="legacy"` (lost). Coverage is appended over terminal lines: both terms come from the same line of each attempt, so no window ever splits an attempt from its outcome. Q&A: add `jsonPayload.surface="qa"`; tutor turns: `NOT jsonPayload.surface="qa"`. An attempt with no terminal line (a process that died mid-append) is found by `attempt`: a log query for `attempted` ids with no terminal line after the lag horizon, 60 s (the 1500 ms budget, the 250 ms grace, the pool's 30 s checkout timeout and ingestion), and, for tutor turns, by `--coverage-since` (`unrecorded`, from the turns themselves) | Stop on any legacy `append_failed` line (the ratio is then below 1.0) or any attempt still without a terminal line after the horizon. A deferred append that ends `appended` in a later window is not a stop (spec 18.8 F11; the earlier per-window ratio of `attempted` over `appended` read a delivery that straddled a window boundary as a loss and could hide a real one) |
| Delivered abstention by reason | `jsonPayload.event="tutor.ledger.attempted"`, labels `jsonPayload.decision`, `jsonPayload.abstention_reason` and `jsonPayload.surface` (plan I "abstention by reason" over the responses learners got; spec 18.8 F1). The same counts are in `/ready` `slis.tutor_ledger.delivered`, per instance, and in the ledger rows (`decision`, the entry's `abstention_reason`) | Counter metric |
| Ledger conflicts (0) | `jsonPayload.event="tutor.ledger.conflict"` | Alert on any match |
| Deferred appends | `jsonPayload.event="tutor.ledger.append_deferred"` (ledger latency on the request path; the attempt's terminal line, `appended` or `append_failed`, follows with the same `attempt`) | Alert on any match (investigate); a stop only when its attempt ends `append_failed` or has no terminal line after the horizon (Ledger coverage) |
| Non-public spans excluded (0) | `jsonPayload.event="tutor.evidence.non_public_excluded"`, label `jsonPayload.surface` (an upstream guard failed) | Alert on any match |
| Shadow bound-claim ratio | `jsonPayload.event="tutor.two_pass.shadow"`, sum of `jsonPayload.ratio_bound` over sum of `jsonPayload.ratio_proposed` (never the raw `bound` and `proposed`, which read a merge or a budget overrun as a binding failure) | Counter metrics (two); stop below 1.0 |
| Shadow abstention by reason | `jsonPayload.event="tutor.two_pass.shadow"`, label `jsonPayload.reason` | Counter metric |
| Shadow failures | `jsonPayload.event="tutor.two_pass.shadow_failed"` | Alert on any match |
| Chain integrity | `resource.type="cloud_run_job" AND jsonPayload.job="response_ledger" AND jsonPayload.status!="ok"` (a job line: its own resource clause, not the API's) | Alert on any match |
| Phase 3 overrides | `jsonPayload.event_type="config.override"`. The details name `two_pass_tutor_shadow`, `tutor_ledger_disabled`, `ledger_route_enabled`, `evidence_panel_enabled`, `shadow_budget_overridden` or `ledger_append_budget_overridden`. | Alert on any match |
