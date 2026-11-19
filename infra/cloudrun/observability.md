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
- `config_package_version` and `config_package_sha256`;
- a `slis` block. It holds citation resolution counts and rate, abstention decisions and rate by reason, the search latency p50 and p95 over the last 1000 decisions, and the start-up drift report.

| Source | Fields | Severity |
|---|---|---|
| Each retrieval (`logger` `qcai.retrieval`, `event: "retrieval.decision"`) | `surface`, `mode`, `gate`, `abstained`, `reason`, `results`, `near_floor`, `top_score`, `latency_ms`, `index_version`, `threshold_version`. **No query text and no identity.** | INFO |
| Citations per Q&A, assistant or tutor response, or per history read that withheld one (`logger` `qcai.citations`, `event: "citations.delivered"`) | `surface`, `delivered`, `dropped_unresolved`, `withheld_unapproved` | INFO, or WARNING when `dropped_unresolved` > 0 |
| A stored citation that no longer resolves (`event: "citations.unresolved_on_read"`) | none | WARNING |
| Manifest drift (`event: "corpus.drift"`) | `item_id` or `drifted`, `details` | WARNING in development; start-up fails in a governed build |
| Semantic index misaligned (`event: "semantic.misaligned"`) | `expected`, `found` | WARNING |
| Configuration package hash mismatch in development (`event: "config_package.hash_mismatch"`) | `path`, `sha256` | WARNING |
| Span registration and citation migration jobs (`qcai.worker`) | `job` (`register_spans` or `migrate_citations`), `status`, counts, `duration_ms` | INFO, or ERROR on failure |

| SLI | Filter (after the API resource clause) | Kind |
|---|---|---|
| Abstention rate | `jsonPayload.event="retrieval.decision"`, ratio of `jsonPayload.abstained=true` | Counter metrics (two) |
| Search p95 | `jsonPayload.event="retrieval.decision"`, value `jsonPayload.latency_ms` | Distribution metric |
| Citation resolution rate (100%) | `jsonPayload.event="citations.unresolved_on_read"` | Alert on any match |
| Duplicate ids (0), manifest drift (0) | `jsonPayload.event="startup" AND (jsonPayload.duplicate_span_ids>0 OR jsonPayload.manifest_drift>0)` | Alert on any match |
| Phase 2 overrides | `jsonPayload.event_type="config.override"`. The details name `retrieval_gate_bm25`, `semantic_retrieval_enabled`, `span_resolver_route_enabled`, `citation_provisional_lift_enabled`, `config_package_path_overridden` or `config_package_hash_unverified`. | Alert on any match |

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
