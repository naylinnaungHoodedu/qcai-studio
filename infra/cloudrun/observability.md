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
| **Alert on overrides** | `jsonPayload.event_type="config.override"` (details name the override: `demo_auth_enabled` or `corpus_governance_disabled`; the Phase 2, 3, 4, 5 and 6 rows below name theirs) | Alert on any match |
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
| Semantic setting on but retrieval lexical, at start-up (`event: "semantic.inactive"`) | `reason`: `egress_not_opted_in`, `provider_open`, `unpinned`, `no_budget`, `gateway_stopped`, `not_configured` or `learner_text` (the last check, plan H's bar on the learner's query text, so no embedder is ever given) when the model gateway gives no embedder (Phase 5 spec 4.19), `not_configured` when the vector index is not configured, else `not_aligned` | WARNING |
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
- `/ready` reports the versions in force: `config_package_version`, `two_pass_tutor` (the effective mode) and `two_pass_tutor_setting`, `phase4_exit_passed`, the `tutor_pipeline` ids, prompt hashes, `subset_check` rule, `legacy` pins (the legacy contained path's ids and containment rule hash, which every legacy record stamps) and `budgets` in force (`shadow_ms`, `ledger_append_ms`, and `overridden`, the budgets an environment override changed), and `ledger.status` (`ok` or `unavailable`). `/ready` is public, so it never shows the head's sequence number, the all-time count of tutor responses: that is in the `response_ledger` job line and in each `tutor.ledger.appended` line.
- `/ready` also reports the Phase 3 switches in force: `tutor_ledger_enabled`, `ledger_route_enabled`, `evidence_panel_enabled` and `tutor_turns_route_enabled` (each off outside development except `tutor_ledger_enabled`; a relaxation also logs a `config.override` event, below).
- `/ready` `slis.tutor_ledger` holds the **legacy** deliveries only (a shadow record is a shadow output, AC-3-6; spec 18.7 E15): `attempted`, `appended` and `failed` (`legacy`), `duplicates`, `conflicts`, `legacy_coverage_rate` (appended over attempted legacy deliveries; an attempt is counted once the delivery committed, so a request that rolls back is none, 18.7 E5), `legacy_by_surface` (the same counts and rate for tutor turns and for `/qa/ask` answers, which are ledgered too), `delivered` (what the legacy deliveries were, counted at the attempt whatever the append then did: `decisions` (`answer`, `abstain`), `abstention_rate` and `abstention_by_reason`, in all and `by_surface`; plan I "abstention by reason" over the responses learners got, spec 18.8 F1), `non_public_spans_excluded` (spans the license_class gate kept out of legacy and Q&A records; any non-zero count means an upstream guard failed) and `write_stop` (a legacy write failed or conflicted).
- `/ready` `slis.two_pass_shadow` holds only `scheduled` and `phase2_bound_claim_ratio_baseline` (1.0), which no run's outcome changes. `/ready` is public, and on a quiet instance a learner comparing it before and after a turn would otherwise read that turn's shadow outcome (AC-3-6): its decision, reason and claim counts, whether it completed or failed and at which step, whether its ledger append or its license gate failed, and whether it tripped the bound-claim stop. All of those are in each run's log lines (`tutor.two_pass.shadow`, `tutor.two_pass.shadow_failed`, `tutor.ledger.append_failed`, `tutor.evidence.non_public_excluded`), which the log-based SLIs and alerts below aggregate, and in the in-process snapshots, which no route serves (tests only).
- These are per-instance counters; the log lines below aggregate across instances, and only they measure a stop for the whole service.

All Phase 3 events log on the `qcai.tutor` logger. They carry counts, hashes and enumerations only: no question, claim or rendered text, and no response, turn, thread or message id. The one id, `attempt`, is random per legacy ledger attempt and names nothing else: it pairs an attempt with its terminal line (spec 18.8 F11).

A legacy delivery's abstention reason (`abstention_reason` on `tutor.ledger.attempted`, and on its ledger record) is the retrieval gate's own reason when the gate returned nothing (`no_query_terms`, `no_match`, `insufficient_coverage`, `below_floor`), and otherwise `no_approved_span`: either the gate matched passages none of which could be quoted (not approved under D-31, or not verified), or the Phase 4 legacy guard withheld a contained answer (a V1.1 or V1.2 failure, or V1.7 `conflict_withheld`: quotations that conflict where no evidence panel shows them, or under the package's conflict policy `v1.v1_7.on_conflict` `withhold`) and the learner got today's abstention. The two share the reason; `tutor.v1.legacy_guard_withheld` (`check_id`, `reason_code`, `surface`) counts the guard's (Phase 4 below). The Phase 2 `slis.abstention` counts the gate's decisions, not what was delivered: under D-31 it reads 0% while every delivery abstains with `no_approved_span` (spec 18.8 F1).

| Event | Fields | Severity |
|---|---|---|
| `tutor.ledger.attempted` | `delivery` (`legacy`), `decision` (`answer` or `abstain`), `abstention_reason` (null on an answer), `attempt`; `surface: qa` on a `/qa/ask` answer. One line per committed legacy delivery, logged after its commit and before its append | INFO |
| `tutor.ledger.appended` | `delivery`, `seq`, `record_hash`, `duplicate` (the off-database copy of the chain); `attempt` on a legacy line (its attempt's terminal line); `surface: qa` on a `/qa/ask` record (a tutor line has no `surface` field) | INFO |
| `tutor.ledger.append_failed` | `delivery`, `stage`, `error` (class); `attempt` on a legacy line (its attempt's terminal line); `surface: qa` on a `/qa/ask` record | ERROR, a plan L stop |
| `tutor.ledger.append_deferred` | `delivery`, `budget_ms`, `attempt`; `surface: qa` on a `/qa/ask` record (the learner was not held past the budget plus the package's `ledger_wait_grace_ms`, 250 ms). Not terminal: the attempt's `appended` or `append_failed` line follows when the append ends | WARNING |
| `tutor.evidence.non_public_excluded` | `surface` (`two_pass`, `legacy` or `qa`): a span whose derived license class is not public was left out | WARNING; alert on any match (an upstream guard failed) |
| `tutor.ledger.conflict` | `delivery` | ERROR |
| `tutor.two_pass.shadow` | `decision`, `reason`, `proposed` and `bound` (the record's raw counts: `bound` is the locked claims, so merged and budget-skipped claims are in `dropped`), `ratio_proposed` and `ratio_bound` (the plan L ratio terms, as `TwoPassMetrics` and the replay count them: a budget-skipped claim is in neither, a merged or duplicate claim in both; public `/ready` carries no ratio), `dropped`, `attempts`, `plan_id`, `gate`, `latency_ms`, `seq`. Under `V1_PIPELINE=enforce` (the development default) the record is V1's (Phase 4 below): `reason` may be a V1 abstention reason, `decision` `answer` means only that V1 passed (delivery is `tutor.v1.run` `final`), and the counts are V1's (each claim of a candidate V1.1 hard-failed is in `dropped` as `unresolvable_citation`, in `ratio_proposed` and not in `ratio_bound`) | INFO |
| `tutor.two_pass.shadow_failed` | `step`, `error` | ERROR |
| `tutor.two_pass.render_failed` | `step` (`render` or `subset_check`), `render_attempt`, `error` (class): a render attempt raised. The run goes on; when every attempt raised it abstains with `render_failed`, never `subset_check_failed` (spec 18.12 J3) | ERROR |
| `tutor.two_pass.budget_exceeded` | `step`, `elapsed_ms`, `budget_ms`: the record's own composition overran its budget (Phase 3's, or V1's under `V1_PIPELINE=enforce`); a shadow-mode V1 track that overruns after the record's decision logs `tutor.v1.budget_exceeded` instead (Phase 4) | WARNING |
| `tutor.two_pass.on_downgraded` | none | WARNING, once per process |
| `tutor.two_pass.unavailable` | `reason` | WARNING |
| Security event `ledger.reviewer_read` | `route`, `delivery` (actor role; subject digest) | success |
| `db.connect.timeout` (`qcai.db`) | `timeout_s`, `slot_free` (false when no connect slot came free): a new Cloud SQL connection outlived the 30 s bound `app.core.db` enforces | WARNING |
| `db.connect.keepalive_unset` (`qcai.db`) | `option`, `error`: a new Cloud SQL connection's socket could not be reached (`no_socket`) or refused a keepalive option, so a read whose peer is gone is not bounded on that connection; the connection is kept | WARNING |
| Job `response_ledger` (`qcai.worker`) | `status`, `records`, `first_seq`, `last_seq`, `head_hash`, `head_row`, `appended_during_check` (appends that committed while it ran; never a problem), `problems`, `duration_ms`; `coverage` (with `horizon_s`, `settled_before` and `pending`, spec 18.12 J5), `exported` and `provenance` (`--check-provenance`: `records`, `checked`, `other_package`, `problem_count`, `problems`) when asked | INFO, or ERROR when broken or on a provenance mismatch (`status` `provenance_mismatch`) |

| SLI | Filter (after the API resource clause, except the job row) | Kind |
|---|---|---|
| Ledger write failures (0) | `jsonPayload.event="tutor.ledger.append_failed"` (legacy and shadow; `jsonPayload.surface="qa"` for Q&A) | Alert on any match (plan L stop) |
| Ledger coverage (100%) | Every legacy attempt (`jsonPayload.event="tutor.ledger.attempted"`) ends in exactly one terminal line with its `attempt` id, logged when its append ends: `jsonPayload.event="tutor.ledger.appended" AND jsonPayload.delivery="legacy"` (recorded) or `jsonPayload.event="tutor.ledger.append_failed" AND jsonPayload.delivery="legacy"` (lost). Coverage is appended over terminal lines: both terms come from the same line of each attempt, so no window ever splits an attempt from its outcome. Q&A: add `jsonPayload.surface="qa"`; tutor turns: `NOT jsonPayload.surface="qa"`. An attempt with no terminal line (a process that died mid-append) is found by `attempt`: a log query for `attempted` ids with no terminal line after the horizon, and, for tutor turns, by `--coverage-since` (`unrecorded`, from the turns themselves: a turn older than the horizon with no record; a newer one is `pending`, its append possibly still running, spec 18.12 J5). The horizon is 360 s (`ledger.attempt_horizon_s`, spec 18.12 J6): one append's connection wait (the pool's 30 s checkout timeout and the 30 s connect bound that `app.core.db` enforces on a new Cloud SQL connection, which the connector itself does not bound) and its six statements, each bounded by the 1500 ms budget, after retries that all ended within the budget; up to four such appends in turn (16 in flight on 4 workers, so an append can wait behind three rounds); and 60 s for ingestion and the turn's own commit, rounded up to whole minutes. It holds only while the instance keeps its CPU after the response (always-on CPU allocation). With request-based CPU allocation a queued or running append goes on only when the instance next has CPU, so no horizon bounds it (DI-48) | Stop on any legacy `append_failed` line (the ratio is then below 1.0). With always-on CPU allocation, or while the allocation is not yet read and recorded (DI-48), also stop on any attempt still without a terminal line after the horizon, and on `--coverage-since` `unrecorded` above 0, even if an `appended` line follows later: the horizon counts every wait the code bounds, so a later one means an open database connection stopped answering; a deferred append that ends `appended` within the horizon is not a stop. When the database host or the network to it is gone, the TCP keepalive `app.core.db` sets on each Cloud SQL connection ends that read within 60 s of the connection's last traffic, so the terminal line comes by the 840 s dead-peer horizon (`ledger.dead_peer_horizon_s`); an attempt still without one then is held by a server that keeps its connection up and never replies, which nothing in the code ends, and the runbook replaces the instance (deployment.md, Phase 3). With request-based CPU allocation recorded, an attempt without a terminal line after the horizon, or an `unrecorded` turn, is investigated: rerun `--coverage-since` with the same `since` once the instance that served it has stopped (Python runs the queued appends before the process exits); a turn still `unrecorded` then is a stop, and an attempt that ended `appended`, in any window, is not (spec 4.12) |
| Delivered abstention by reason | `jsonPayload.event="tutor.ledger.attempted"`, labels `jsonPayload.decision`, `jsonPayload.abstention_reason` and `jsonPayload.surface` (plan I "abstention by reason" over the responses learners got; spec 18.8 F1). The same counts are in `/ready` `slis.tutor_ledger.delivered`, per instance, and in the ledger rows (`decision`, the entry's `abstention_reason`). `no_approved_span` holds the legacy guard's withholdings too: subtract the `tutor.v1.legacy_guard_withheld` count (by `surface`) to read the approval and verification gaps alone | Counter metric |
| Ledger conflicts (0) | `jsonPayload.event="tutor.ledger.conflict"` | Alert on any match |
| Deferred appends | `jsonPayload.event="tutor.ledger.append_deferred"` (ledger latency on the request path; the attempt's terminal line, `appended` or `append_failed`, follows with the same `attempt`) | Alert on any match (investigate); a stop only when its attempt ends `append_failed`, or, with always-on CPU allocation or none recorded yet, has no terminal line after the 360 s horizon (Ledger coverage; spec 18.12 J6) |
| Non-public spans excluded (0) | `jsonPayload.event="tutor.evidence.non_public_excluded"`, label `jsonPayload.surface` (an upstream guard failed) | Alert on any match |
| Shadow bound-claim ratio | `jsonPayload.event="tutor.two_pass.shadow"`, sum of `jsonPayload.ratio_bound` over sum of `jsonPayload.ratio_proposed` (never the raw `bound` and `proposed`, which read a merge, a duplicate or a budget overrun as a binding failure) | Counter metrics (two); stop below 1.0 |
| Shadow abstention by reason | `jsonPayload.event="tutor.two_pass.shadow"`, label `jsonPayload.reason` (`contracts.ABSTENTION_REASONS`, and under `V1_PIPELINE=enforce` also `contracts.V1_ABSTENTION_REASONS`: `unresolvable_citation`, `checker_unavailable`, `keyed_answer_leak`, `readability_out_of_band`, `response_envelope_invalid`; a record with `decision` `answer` may still deliver nothing, which `tutor.v1.run` `final` says. An empty envelope reads `no_quotable_evidence` when no bundle span is quotable, an approval gap under D-31, and `no_whole_sentence` when the quotable spans hold no whole document sentence, the recall residual of the whole-sentence binding rule. `subset_check_failed` means every checked rendering was refused, `render_failed` that every render attempt raised) | Counter metric |
| Shadow failures | `jsonPayload.event="tutor.two_pass.shadow_failed"` | Alert on any match |
| Shadow render faults | `jsonPayload.event="tutor.two_pass.render_failed"`, labels `jsonPayload.step` and `jsonPayload.error` (a render attempt raised in the renderer or in the subset check; the run went on, and abstains with `render_failed` when every attempt raised; spec 18.12 J3) | Alert on any match (a renderer or checker defect, never a learner input) |
| Database connect timeouts | `jsonPayload.event="db.connect.timeout"` (a new Cloud SQL connection outlived its 30 s bound) | Alert on any match (investigate connectivity to Cloud SQL) |
| Database keepalive not set | `jsonPayload.event="db.connect.keepalive_unset"`, labels `jsonPayload.option` and `jsonPayload.error` | Alert on any match (the dead-peer bound is missing on those connections) |
| Chain integrity | `resource.type="cloud_run_job" AND jsonPayload.job="response_ledger" AND jsonPayload.status!="ok"` (a job line: its own resource clause, not the API's) | Alert on any match |
| Phase 3 overrides | `jsonPayload.event_type="config.override"`. The details name `two_pass_tutor_shadow`, `tutor_ledger_disabled`, `ledger_route_enabled`, `evidence_panel_enabled`, `shadow_budget_overridden` or `ledger_append_budget_overridden`. | Alert on any match |

## Phase 4 SLIs: V1 (plan Phase 4 I)

**Not set up yet.** Creating log-based metrics and alerts is a cloud write (Platform Owner approval each time; DI-62). Production runs no V1 track while `TWO_PASS_TUTOR` is off, so the V1 run SLIs have data only where the shadow runs (development today; DI-32).

Plan Phase 4 I: "Citation resolution 100%; hard-fail rate per check; V1.3 flag rate; V1 p95 (95th-percentile) latency."
- `/ready` reports the V1 values in force, never a run's outcome: `v1_pipeline` and `v1_pipeline_setting`, and `v1` (the rules version and hash, the checker hosting and model id, the misconception library version, entry count and hash, the fixture set hash, the regeneration limits, the readability band, the X4 margins, the stop floors and p95 budget, the quiz-feedback rule, `provisional`, `available` and `legacy_guard`). `slis` has no V1 block (AC-3-6). `v1_pipeline` is the mode the two-pass shadow pipeline's V1 track runs in (`off` when the start-up check found a problem, else the setting); it acts only while `TWO_PASS_TUTOR` is not `off`, so production reports `shadow` while it runs no V1 track. `v1.available` false means the start-up check found a problem, which only a development build with governance off survives.
- In process (tests only; no route serves it), `V1_METRICS.detail_snapshot()`: runs by mode, finals, outcomes per check, the hard-fail rate per check (runs with a hard fail over runs where the check ran), the resolution of delivered citations, the V1.3 flag rate and unavailable runs, a latency histogram with its nearest-rank p95 over the last 1024 runs against the package budget, disagreements with the Phase 3 decision and with the legacy decision, V3 intents, and the legacy guard's checked and withheld counts per surface and its withholdings per check (V1.1, V1.2, V1.7).

All Phase 4 events log on the `qcai.tutor` logger with enumerations, counts and hashes only: no question, claim or rendered text, and no response, turn, thread or message id.

| Event | Fields | Log-based metric or alert |
|---|---|---|
| `tutor.v1.run` | `mode`, `final`, `final_reason`, `hard_fail`, `generation_attempts`, `render_attempts`, `cycle_count`, `outcomes` (check, outcome, count of results), `withheld_claims` (the claims whose verdict is withhold, for any reason: V1.3, V1.8, a withheld V1.7 conflict or a V1.6 omission), `v3_intents`, `disclosure`, `latency_ms`, `gate` | Hard-fail rate per check: runs whose `outcomes.<check>.hard_fail` is above 0, over the runs whose `outcomes` has `<check>` (spec 10.3, as `V1_METRICS` and the fixture report's `hard_fail_runs` count it: a run whose three attempts each hard-failed is one hard-failed run); V1.3 flag rate: the sum of `outcomes.V1.3.flag` over the sum of `outcomes.V1.3.flag` and `outcomes.V1.3.pass` (V1.3's claim-level results, as `V1_METRICS` `v1_3.flag_rate` and the fixture report's `v1_3_flag_rate` count them; never `withheld_claims`); a distribution metric on `latency_ms` and an alert when its p95 exceeds the package's `v1.stop.v1_p95_latency_ms` (250 ms; a plan L stop) |
| `tutor.v1.disagreement` | `with` (`phase3` or `legacy`), `v1_outcome`, `reference` | A counter by `with`; plan G's disagreement log |
| `tutor.v1.checker_unavailable` | `cause` (`timeout` or `error`), `error` | An alert on any line once a checker is hosted (DI-54) |
| `tutor.v1.legacy_guard_withheld` | `check_id`, `reason_code`, `surface` | An alert on any line with `check_id` V1.1 or V1.2: the guard withheld a contained answer (an upstream defect). A counter by `surface` for V1.7 (`conflict_withheld`): an answer quoting conflicting passages, withheld because no evidence panel shows the conflict or the package's conflict policy (`v1.v1_7.on_conflict`) is `withhold`. The learner gets today's abstention, so `tutor.ledger.attempted` names it `no_approved_span` (Phase 3 above): this line is what tells a guard withholding from an approval or verification gap |
| `tutor.v1.unavailable` | `reason` | An alert on any line: the package's v1 block disagrees with the code (a development build with governance off only; every other build does not start, whatever its governance setting) |
| `tutor.v1.budget_exceeded` | `step` (`generate`, `bind` or `render`), `elapsed_ms`, `budget_ms`: in `shadow` mode, the V1 track that runs after the record's Phase 3 decision overran the shadow budget; the record itself did not, and its verdict abstains with `budget_exceeded` | A counter by `step` (V1 latency on top of the Phase 3 composition) |
| Security event `config.override` | the details name `v1_pipeline_enforce`: V1 deciding the shadow record outside development, which settings refuse before the Phase 4 exit (a line means a package claiming the exit) | An alert on any line |

Citation resolution (V-1, "100% of delivered citations resolve") is measured over delivered V1 verdicts; none exists before the Phase 4 exit, so the measure has no production input yet. Operating the answer-rate stop (plan L) on traffic needs labelled in-domain traffic; until then it is the fixture runner's check in CI.

## Phase 5 SLIs: gateway and V2 (plan Phase 5 I)

**Not set up yet.** Creating log-based metrics and alerts is a cloud write (Platform Owner approval each time; DI-80). Production runs no V2 panel while `TWO_PASS_TUTOR` and `MODEL_GATEWAY` are off, and its registry is empty with a budget of 0, so the SLIs below have no production input yet.

Plan Phase 5 I: "Verification completion, time degraded, p95 per stage, cost per response; alert at 80% of budget."
- `/ready` reports the gateway's values in force, never a run's outcome: `model_gateway` (the effective mode) and `model_gateway_setting`, `phase5_exit_passed`, and `gateway` (version, registry, members, the embedding entry's provider, model id and version, `state`, the daily budget, the tool contract version, the panel's size, weights, routing table and tier rule, `available`). `/ready` is public, so the stop's reason and the operator's switches (egress opt-ins, kill switch, disabled adapters) are never on it: the reason is in the `gateway.stopped` line and the stop command's status line. At a stop, once, `gateway.state` changes and `model_gateway` (the effective mode) turns `off`; nothing else changes for the life of the process. A stop is shared: every instance that builds a gateway adopts the registry's stop, and a stopped instance stays stopped until it is replaced, even after an operator clears the stored stop (the runbook's Phase 5 stop conditions). A process whose V2 mode is off by its settings (`MODEL_GATEWAY` off) builds no gateway and reads no stop, so its `/ready` says `state` `open` while a stop may be recorded; `python -m app.workers.gateway_stop` reads the stored stops.
- In process (tests only; no route serves it), `V2_METRICS.detail_snapshot()` and `GATEWAY_METRICS.snapshot()` (Phase 5 spec 10.3).

The Phase 5 events log on `qcai.gateway` (the `gateway.*` events) or `qcai.tutor` (the `tutor.*` events), the start-up line `gateway.retired_setting` (on `qcai.gateway`) included. The exceptions are the operator's `gateway.stop_status` (on `qcai.worker`) and the API's start-up line `semantic.inactive` (on `qcai.api`); the security events `gateway.stopped` and `gateway.stop_cleared` log on `qcai.security`, with `event_type`, as every security event does. Each holds enumerations, counts, adapter ids, registry names, stop times and hashes only: no question, claim or rendered text, and no learner, response, turn, thread or message id. The metrics and alerts below select on `jsonPayload.event` (a security event's on `jsonPayload.event_type`), whatever the logger.

| SLI or event | Log-based metric or alert |
|---|---|
| Verification completion | `jsonPayload.event="tutor.v2.run"`: the share of lines with `completed=true` among those with `passed_v1=true`. A response is completed when every V2-eligible claim got a completed vote (pass or fail) and, when a claim passed, the alignment item was judged; a response with a withheld claim (REDUCED-1 tiers 1-2, ZERO, a kill switch, a stop, the shadow budget) or an unjudged alignment item is not, so an outage lowers the share. In process, `V2_METRICS` reports `completed` and `withheld` apart |
| Time in each degraded mode | A log-based metric counts lines, not time: `tutor.v2.run` lines with `panel_reached=true` counted by `panel_mode` per minute (the worst mode the response's panel ran in; ZERO with no member), so a minute with a line below `FULL` is degraded time. A line with `panel_reached=false` (a V1 hard fail or abstention, which makes no gateway call) has `panel_mode` null and says nothing about the panel. `tutor.v2.degraded` (`mode`, `eligible`) is logged once per response when its panel is built below FULL; a member lost later in the response shows only in `panel_mode`. In process, `V2_METRICS` `time_in_mode_s` gives wall seconds: the clock moves only on a response that reached the panel |
| p95 per stage | `gateway.call` `latency_ms` by `adapter_id` (the gateway call) and `tutor.v2.run` `latency_ms` (the panel), each a distribution metric at the 95th percentile. The correction cycle's p95 is in process only (`V2_METRICS` `latency_ms.correction`); no log line carries it |
| Cost per response | `tutor.v2.run` `cost_units` (fake units in development), a distribution metric |
| The 80% budget event | `jsonPayload.event="gateway.budget_alert"` (`share` 4/5, `daily_units`, `spent`): an alert on any line |
| A stop | `gateway.stopped` (`reason`: `payload_violation`, `secret_in_logs` or `budget_breach`, the last also for a call that reported a cost above its reservation; `origin` `instance` for the stopping instance, with the security event `gateway.stopped`, or `shared` for one that adopted the registry's stop): an alert on any line; every instance's V2 mode is off for the rest of its life: after the cause is fixed an operator clears the stored stop and a new revision resumes |
| The stop not shared, or not read | `gateway.stop_unshared` (`reason`: only that instance is stopped) and `gateway.stop_unread` (the shared stop could not be read): an alert on any line |
| The budget's store unavailable | `gateway.budget_unavailable` (the shared daily budget could not be read or written: the member is ineligible or its call refused, nothing is sent and nothing stops): an alert on any line |
| The cache's store unavailable | `tutor.v2.cache_unavailable` (`operation` `get`, `put` or `evict`: a miss or a skipped write; calls rise and every record stays complete): a counter |
| The operator's stop command | `gateway.stop_status` (`stops`, `cleared`) and, for a clear, the security event `gateway.stop_cleared`: an alert on any clear |
| A refused call | `gateway.call` with `outcome=refused` (the gateway refused it before the adapter: stopped, a payload violation or a budget breach; `latency_ms` 0, `cost_units` 0): a counter |
| A failed call | `gateway.call_failed` (`adapter_id`, `kind`, `status`): a counter by `kind` (`kind` `error` is an adapter that raised anything but an adapter error) |
| Egress refused | `gateway.egress_refused` (`provider`, `adapter_id`, `consumer`): an alert on any line (`consumer` `gateway`: a non-fake member without its D-23 opt-in; `consumer` `semantic-retrieval`: `SEMANTIC_RETRIEVAL_ENABLED` without `openai-embeddings` in `MODEL_EGRESS_PROVIDERS`, so retrieval stays lexical; the API process's start-up line `semantic.inactive` names the `reason`, `egress_not_opted_in`) |
| The V2 shadow budget | `tutor.v2.budget_exceeded` (`step` `verify`, `elapsed_ms`, `budget_ms`): a counter; the rest of that response runs in ZERO |
| `on` downgraded | `tutor.v2.on_downgraded`: an alert on any line (`MODEL_GATEWAY=on` with V1 in shadow, which Settings refuse; defence in depth) |
| A retired setting | `gateway.retired_setting` (`names`): an alert on any line until DI-81 removes the variables |
| Disagreement | `tutor.v2.disagreement` (`v1_final`, `v2_would`): a counter (plan G's shadow dual-run) |
| Unavailable | `tutor.v2.unavailable` (`reason`): an alert on any line |
| Security event `config.override` | the details name `model_gateway_shadow` (the V2 shadow outside development), `model_gateway_on` (refused outside development before the Phase 5 exit; a line means a package claiming the exit) or `model_egress_opt_in` (an environment naming a provider in `MODEL_EGRESS_PROVIDERS`): an alert on any line |

## Phase 6 SLIs: V3 (plan Phase 6 I)

**Not set up yet** (DI-95). Creating log-based metrics and alerts is a cloud write (Platform Owner approval each time).

Plan Phase 6 I: "Escalation share (V-3 <= 10% is a Table XVII gate, EG/OT per Section 15 [Evidence E-105]; production SLO [Decision D-06]); queue age p90 alert [Risk R-40]." The SLIs are reported, per database, by the reviewer-only `GET /v3/metrics` and the worker's `python -m app.workers.v3_queue status` line (`v3.status`), never by the public `/ready`, which carries the static V3 values only (`v3_queue`, `v3_queue_setting`, `phase6_exit_passed`, `v3`). **Outside development the worker's line is the only source** while D-18 is open: `GET /v3/metrics` refuses every caller there (401 without a credential; otherwise 403 and `authz.denied`, `required` `role:reviewer` or `reviewer_pool:D-18`). The line is logged only when `status` runs, so the queue-age alert needs a schedule: DI-95 defines a Cloud Run job running `status` hourly (the stop's sample interval) and, wherever `V3_QUEUE` is not off, `scan --until-done` before it, owned by the Platform Owner (not created; a cloud write). Ratios are `k/n` strings. Every value below is report only and provisional (PD-37; D-06 open):
- **Escalation share (V-3):** learner deliveries the scan considered in the last 7 days with an item whose triggers include X1-X4 (audits X5 and X6 are proof tests, plan 15.3), over those deliveries; a shadow record's item counts on the delivery it shadowed. At most 1/10.
- **Queue age:** the open items' age p90 (nearest rank; the alert's measure, plan I) and the oldest open item's age (the stop's measure) against the 72-hour SLO.
- **Draws:** deliveries considered, drawn X6 (1/20) and X5 (1/5 inside an X5 window), and the deliveries that are not auditable, each class apart: the pre-ledger deliveries of plan G (`tutor_turns` from an image that keeps no ledger, `qa_before_ledger`), the turns created while the ledger kill switch was off (`ledger_disabled`), lost appends (`lost_records`, a Phase 3 plan L stop) and appends still inside the coverage horizon (`pending`).
- **Double-review agreement:** round-2 pairs and how many agreed with round 1.
- **Residual bound:** the Wilson 95% upper bound of residual error over X6-audited answer deliveries, per UTC month (plan 15.3 "HR-3 deployment form: monthly Wilson bound from the 5% draw"). While no answer is audited (every deployment today), `wilson95` is null and `no_audited_answers` true: no evidence, never a bound of 0.
- **Gold rows, the stop and the X5 windows.**

The service events log on `qcai.v3`, the V2 track's on `qcai.tutor`, the worker's on `qcai.worker` and the security events on `qcai.security`. They carry enumerations, counts, item ids, model keys, seq numbers and hashes only: no response, turn, thread, message or user id and no text.

| SLI or event | Log-based metric or alert |
|---|---|
| V-3 escalation share | `GET /v3/metrics`, or `jsonPayload.event="v3.status"` field `escalation_share` (`share` `m/n`, `max` 1/10, `above_max`): report only |
| Queue age p90 and oldest age | `jsonPayload.event="v3.status"`, fields `queue.age_p90_s` and `queue.age_max_s` against `queue.slo_s`: an alert on `age_p90_s` above the SLO (plan I, R-40; DI-95) |
| Draws | `jsonPayload.event="v3.scan"` (INFO; `from_seq`, `to_seq`, `records`, `deliveries`, `drawn_x6`, `drawn_x5`, `items_created`, `items_updated`, `model_changes`, `unparsed`, `done`): counter metrics of `drawn_x6` and `drawn_x5` over `deliveries` |
| Double-review agreement | `jsonPayload.event="v3.adjudicated"` (INFO; `item_id`, `review_round`, `subject`, `state`, `agreement` in round 2 only) with `review_round=2`, labelled by `agreement`: report only |
| Residual bound | `jsonPayload.event="v3.status"` field `residual.by_month` (the monthly Wilson 95% upper bound; empty, with `residual.wilson95` null and `residual.no_audited_answers` true, while nothing is audited): report only |
| The V3 stop | `v3.stop` (`active`, `reason` `clear`, `queue_age` or `unreadable`, `window_s`, `slo_s`; WARNING when active, INFO when clear) with `active=true`, or `v3.stop_unread` (WARNING, no fields: the queue could not be read, so tier 1 is withheld): an alert on any line |
| The tier-1 stop path | `tutor.v2.v3_stop` (on `qcai.tutor`; WARNING; `tier`, `policy` `pre_verified_only`): a tier-1 shadow run under the stop, a counter |
| X5 events | `v3.x5_event` (WARNING; `kind` `model_change` or `cusum_alarm`, `model_key`, `from_version`, `to_version` or `stream`): an alert on any line (the audit rate is 1/5 for the next 1500 deliveries) |
| A trigger on a closed item | `v3.trigger_after_close` (INFO; `item_id`, `triggers`): recorded, never reopened; a counter |
| Applied labels and the gold chain | `v3.applied` (INFO; `item_id`, `final_gold_seq`; never for a repeated client key, so the counter counts distinct applies) and `v3.gold_appended` (INFO; `seq`, `record_hash`, the off-database copy of the gold chain): counters; `v3.gold_verified` (on `qcai.worker`; `count`, `head_seq`, `head_hash`, `problem_count`, `problems`) from `python -m app.workers.v3_queue verify-gold`: an alert on `problem_count` above 0 |
| Learner flags | `v3.flag_recorded` (INFO; `duplicate`): a counter (development only) |
| V3 unavailable | `v3.unavailable` (WARNING; `reason`, start-up: a package v5 v3 problem, so the V3 mode stays off): an alert on any line |
| Worker status | `v3.status` (on `qcai.worker`; INFO; `mode` and the SLIs): the only SLI source outside development (DI-95's hourly job) |
| Worker scans and exports | `v3.scan_finished` (on `qcai.worker`; INFO; `scans`, `last`), `v3.scan_refused` (WARNING; `reason` `v3_off`), `v3.gold_exported` (INFO; `count`, `applied_only`) and `v3.gold_export_refused` (WARNING; a path inside the application tree or the repository checkout): counters |
| The V3 stop unreadable | `v3.stop_unread` (WARNING): see the V3 stop row |
| Reviewer actions | security events `v3.queue_read`, `v3.scan_run`, `v3.item_read`, `v3.item_claimed`, `v3.item_adjudicated`, `v3.item_applied` and `v3.metrics_read` (on `qcai.security`; outcome success; `route` and the call's counts or item id, the actor role and the subject digest): counters |
| Reviewer refusals | security event `authz.denied` (on `qcai.security`; outcome denied; `route`, `required` `role:reviewer`, or `reviewer_pool:D-18` outside development while D-18 is open, `provider`): a counter |
| Security event `config.override` | the details name `v3_queue_shadow` (the V3 queue in shadow outside development) or `v3_queue_on` (refused outside development before the Phase 6 exit; a line means a package claiming the exit): an alert on any line |

## Phase 8 SLIs: learner record and privacy

`/ready` reports the four configured learner switches and `phase8_exit_passed`. In development `learner_slis.planner_stop_observed` shows the last local observation of the shared stop, along with process counters. The planner checks the authoritative stop during its own work. Readiness issues no Phase 8 database query.

- F-3 uses `learner.record.updated` with interaction start and commit time. Keep the production measure on the DI-305 evidence path until authorized.
- `learner.sync.conflict` records the reason from version, counter, ownership, replay, and untrusted-write checks. `learner.harness.violation` records failed engineering invariants and the CLI exits with the stop status.
- `learner.erasure` uses the security log for password refusal, committed deletion counts and `duration_ms`. Claim and export events carry digests and counts only. `analytics.consent_withheld` measures withheld events without recording their contents.
- Outside development, `learner_sync_on`, `learner_identity_on`, `learner_privacy_on`, `learner_planner_shadow`, and `learner_planner_on` are recognized `config.override` details.

| Phase 8 SLI | Log filter and value | Measure |
|---|---|---|
| Erasure time | `(jsonPayload.event_type="account.delete" OR jsonPayload.event_type="learner.erasure") AND jsonPayload.outcome="success"`, value `jsonPayload.details.duration_ms` | Phase 1 distribution extended to Phase 8. Both routes time from erasure start through commit, after password confirmation where applicable. |
