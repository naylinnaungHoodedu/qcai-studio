# QC+AI Studio: Phase 8 implementation spec

Learner adaptation and privacy-preserving record, upgrade plan lines 1557-1614. The branch was cut at `98f7cc4` and its current integration base is `512b8a6`.

Sections 0-17 describe the behaviour the code has and identify deferred integration work. Section 18 holds one history-table row per review round. This file is LF in every checkout (`.gitattributes`).

## 0. Ground rules, measured facts, readings

Smoke and acceptance checks use synthetic fixtures and run offline under the branch rules and shared-file limits in §0.1. Phase 7 reached main as `512b8a668f6bc95358183c4f173efb0daa44868c` (PR #39) and entered this branch in merge `bf4fe3a`. It contributes package v6, the EHMF stop table and revision, and the golden-set history. Phase 8 ships package v7 and Alembic head `20261123_phase8_learner`. The preceding Phase 6 merge contributes the two user-keyed V3 tables covered by erasure and retention.

Phase 5 added `gateway_budget_days`, `gateway_stops`, and `evidential_cache_entries` to the shared ORM and updated the migration chain. The retrieval engine delegates embedding egress to `app/gateway/embeddings.py`. Its import guard allows the Pinecone index SDK in the retrieval engine. The shared-file rules in §0.1 preserve main-track ownership of the gateway tables and embedding implementation.

The learner-record baseline uses the get-or-create path for reads, rejects changed-payload receipt replays, and advances `record_version` independently of an expected version. The retention worker uses the existing retention service. The acceptance readings are in section 13.

### 0.1 Shared file ownership

The shared-file rules below apply relative to the integration base in §0. The **package bump exception** permits the new package version, its loader rules, and the version pins in existing tests. Its **bump-docstring exception** permits corrections to shipped-version text in designated shared modules and documentation. The **migration-head exception** covers the additive revision, the ledger head constant, and changes needed for existing upgrade and downgrade checks to traverse the new head. Phase 8 adds the readiness fields defined in §10 and the two CI steps in §14.

| Shared area | Permitted edits |
|---|---|
| `core/config.py`, `core/auth.py`, `core/authorization.py` | One learner settings block and validator. Preserve the `AuthUser` fields and the `get_current_user` signature. Place all Phase 8 policies together after the existing learner-record entries. |
| `app/main.py` | Keep existing routers and append Phase 8 readiness fields and configuration-override keys. Phase 8 uses its last in-process planner-stop observation. Phase 7 retains its own EHMF readiness fields and stop read. |
| `services/erasure.py`, `services/retention.py`, `workers/retention.py` | Preserve `erase_user(db, user_id)`, `erase_stale_guest_rows(db, cutoff)` and `run_retention_cleanup(db, now=None)`. Every intentional exemption has a documented reason. |
| `app/gateway/**`, `services/v2_panel/**`, `services/v1_checks/**`, `services/teaching_assistant.py` and the evidential pipeline | Keep the verifier and gateway code and contracts under main-track ownership. The bump-docstring exception covers shipped-version text in the designated modules only. The hashes and published schemas stay fixed. |
| `services/ledger.py`, `core/schema_upgrades.py`, and Alembic | Change `SCHEMA_REVISION` and add Phase 8 schema reconciliation and one additive revision after the merge. Keep the earlier revisions and ledger behavior. |
| `core/config_package.py`, `config_package/*`, `scripts/config_package.py` | The package bump adds one version, its loader validation and test pins. Existing version files and schemas remain readable. |
| `services/tutor_orchestrator.py` and the frontend integration | Observe the planner in shadow only. Keep new browser transport separate. Change only the existing learner-record functions and types in the shared frontend client. |
| `.github/workflows/ci.yml`, `test-strategy.md` and `.gitattributes` | Add the predecessor readability and invariance checks to CI. Test strategy and attributes take append-only Phase 8 sections, with the duplicate merged exit paragraph removed under R2-07. |
| `test_phase3_acceptance.py`, `test_response_ledger_migrations.py` | The migration-head exception permits tests to traverse the new revision. The inherited readiness SQL assertion is protected. |
| `test_phase4_acceptance.py`, `test_phase5_acceptance.py` | Only the specified shipped-version pins in the isolated bump. The Phase 5 gateway-stop assertion is protected. The Phase 8 guard pins the unchanged Phase 5 source. |
| `test_phase7_acceptance.py` | The v6 checks read the explicit Phase 7 package. The migration checks follow the Phase 8 head while preserving the Phase 7 downgrade assertions. |
| `test_configuration_overrides.py`, `test_api.py` | The former takes the package-copy docstring and one case per Phase 8 override. The latter permits only the consent fixture for progress aggregation. |
| `docs/architecture/ehmf-change-control.md` | The package bump exception covers the shipped package, the append-only v6 history prefix, and the ordered rollback instructions. The Phase 7 change-control policy remains the authority. |
| `docs/architecture/phase7-implementation-spec.md`, `docs/evaluation/phase7/README.md` | The bump-docstring exception covers the default path, loader ceiling, golden-run provenance, and documented migration sequence. Phase 7 retains its EHMF scope. |
| `AGENTS.md` and the shared records in §12 | Branch coordination uses the repository's agent rules. Versioned records are regenerated with their published tools against clean source. |
| Templates, generated freeze baseline, shared test harness and dependencies | Keep protected templates out of ordinary suite output. Preserve the public-payload golden file, test setup and lockfiles. |

## 1. Conflicts between plan text and fixed decisions

- **H13 and D-27.** Plan L1566 requires a consent model, and L1907 says "a hold stops the named work until its release evidence is filed". The owner authorized isolated engineering under P1-D-18, with the main-track record P2-12-D-04. H13 remains held. DI-300 and DI-301 keep the Phase 1 and 3 prerequisites and the consent decision visible.
- **Baseline and ownership.** The baseline already scores quizzes on the server and runs scheduled retention. The designated learner tables use the bound subject, including assessment facts and issued replicas. Notes, threads, quiz attempts, credentials, and other legacy activity keep the authenticated principal, including the federated subject value where applicable. Export and erasure traverse both keys. Existing bindings remain authoritative through flag rollback. First bind preserves a lone record's version. Identity defaults off in development to preserve the baseline demo and authentication contracts.
- **Revocation and finality.** `guest_sessions.py` uses a domain-separated SHA-256 tombstone in `learner_guest_revocations` so recognition survives signing-key rotation. Guest erasure removes the corresponding raw legacy revocation. The first managed writer and both erasure routes serialize on the same principal guard. The locked write path rechecks local and guest credentials. A retained federated account can resume after a fresh request observes the new erasure epoch. The lock refuses earlier observations. Both guard states expire after 365 days of inactivity in every privacy mode. Guest revocation survives guard expiry and flag rollback.
- **Privacy authentication.** Export and self-service erasure require a verified local session, signed guest credential, or Auth0 token. Both refuse all demo identities. Local account deletion requires a local session and password. With privacy enabled, both erasure routes return a verified receipt and persist its digest.
- **Assessment and R-03.** Stage-9 ratings and flags are operational signals. Only server assessment facts feed planner mastery, and the quota counts attempts by authenticated principal and lesson. Sequential quiz attempt IDs remain opaque response metadata for a caller's own activity and are not accepted on an ID-addressed cross-learner endpoint.
- **Consent and retention.** Plan L938 ties `consent_version` to analytics admission and `retention_class` to automatic cleanup. With privacy off, `erase_stale_guest_rows(db, cutoff)` selects timestamped guest-prefixed rows by `created_at`, matching Phase 6. Privacy on selects the class-specific age rules and recognizes bound guests. Durable rows stay until erasure unless a specific expiry applies. PD-200 controls provisional grants. The audit and write-guard retention rules apply in every privacy mode. P2-12-D-05 keeps the 540-day rule for independently submitted support requests, even when the address matches a deleted account. DI-316 is closed. A-17 and Q-19 remain unresolved.
- **Method and test layout.** The harness feeds plan IDs from the pure planner using synthetic mastery values and the existing presentation request seam. It uses public two-pass engineering fixtures. Research designs remain governed by D-08 and DI-312 covers live presentation wiring. The document guard compares section 3's table with the ORM's columns, and the acceptance map resolves tests across feature-specific modules.
- **Shadow timing.** The planner issues set-based reads within a savepoint. PostgreSQL bounds each statement and restores the prior budget. Work exceeding 150 ms is recorded as degraded and the existing shadow job proceeds. The elapsed budget also detects slow local work after it returns.
- **Planner fallback signals.** Flag-off, no-consent, and held-stop fallbacks preserve the static ordering. Degraded logs report failures and budget overruns so routine policy choices do not generate fault alerts. With the flag off, the planner emits no call or signal. In shadow mode, consent and stop fallbacks appear as ordinary observations.
- **Adaptation stop.** Only an explicit operator harness run with `--stop-sqlite` sets the shared planner stop. A failing CI harness blocks the build. The runtime stop-the-line trigger for learner state in an evidential prompt (plan 13.6) awaits main-track wiring under DI-319.
- **Readiness and shared tests.** The integration exposes the configured planner mode and the process's last observation of the stop. The authoritative check stays in the planner. This meets the Phase 8 readiness requirement without adding SQL or changing the protected Phase 3 and Phase 5 assertions.

## 2. Architecture

Separate credential verification from subject resolution. An account and a valid guest session may be linked through a one-shot claim with both credentials proved and an auditable outcome. Keep the trusted assessment writer and add a separate client synchronization boundary. Use a deterministic planner over server-held state. Only the pedagogical pass may consume the planner output. Until DI-312 is resolved, evaluate choices in shadow and exercise them in the public-fixture harness through the existing presentation request interface.

## 3. Data shapes

The subject mapping binds a provider principal to a random subject identifier. The synchronization command includes an issued replica, operation identifiers and clocks, and an expected record version. Its result contains operation receipts and the resulting version. Consent records and change history carry version, class, state, time, and source. The planner returns a plan ID, ordered lesson IDs, and a planner version. Erasure receipts carry a random ID, timestamp, consent version, table coverage and zero counts, configuration digest, and scope statements.

The first build adds the following shapes:

| Model | Fields |
|---|---|
| `LearnerIssuedReplica` | `replica_id` (random server-issued string, primary key), `user_id` (indexed erasure key), `created_at`, `last_used_at`, `retired`. |
| `LearnerWriteGuard` | `key_digest` (primary key), `erased`, `erasure_epoch`, `last_used_at`. |
| `LearnerPresentation` | `plan_id` (`concise`, `stepwise`, or `socratic`), `lesson_order` (ordered tuple of lesson identifiers), `planner_version` (`learner-planner-v1`). |
| `LearnerSubject` | `principal_digest` (provider-scoped primary key), `user_id` (random erasure key), `provider`, `created_at`. |
| `LearnerGuestRevocation` | `credential_digest` (primary key), `revoked_at`. |
| `LearnerClaimAudit` | `id`, `subject_digest`, `guest_digest`, `transferred` table counts, `created_at`. |
| `LearnerConsent` | `user_id` and `consent_class` (composite primary key), `consent_version`, `granted`, `updated_at`, `source`. |
| `LearnerConsentChange` | `id`, `user_id`, `consent_class`, `consent_version`, `granted`, `created_at`, `source`. |
| `LearnerErasureAudit` | `id`, `receipt_digest`, `table_set_digest`, `deleted_total`, `created_at`. |
| `LearnerAdaptationStop` | `control_id` (the planner key), `reason`, `stopped_at`. |
| `LearnerAssessmentFact` | `attempt_id` (primary key), `user_id`, `lesson_slug`, `mastery`, `created_at`. |

The client operations service accepts a subject, expected version, and existing operation input models. With synchronization enabled, authenticated GET uses the no-write reader and POST requires an integer `expected_record_version`. Issuance confirms a preferred active replica or allocates a new one. Off mode retains baseline protocol and resolves an existing subject binding.

`LocalAccountDeleteRead` holds `status` and an optional `receipt`. The receipt matches the standalone self-service erasure response. The server omits that field when privacy is off.

## 4. Algorithms

- Issued replicas belong to a subject. Existing receipts are evaluated before stale clocks. New operations validate replica ownership, monotonicity and causal-vector scope. A conflict-tolerant insert and one transaction handle first writes and version checks without a server retry.
- Assessment counters and facts commit with the server-scored attempt. The client writer refuses client mastery and server-owned operation or replica identifiers.
- The planner selects lesson order and style from trusted assessment facts and attempt state. The default plan and static order cover unavailability and absent adaptation consent.
- Erasure follows metadata-derived, child-first table coverage and persists the canonical receipt digest and coverage summary. The guest revocation digest survives signing-key rotation. The receipt states the local data scope and available processor and backup information.

In `learner_record_sync.py`, a conflict-tolerant insert creates the record when needed. A version-preserving row update acquires the transaction's write lock, then the service checks the expected version and reads the subject's issued replicas. All new operations have strictly increasing clocks and known causal counters. Identical operations in the same batch generate one applied receipt followed by duplicate receipts. A replay containing only known operations can recover its receipts after the record advances. The read-only entry point returns a version-zero record for a missing subject without issuing an insert.

The planner maps the mean finite course-local server mastery below 0.4 to stepwise, from 0.4 through values below 0.75 to concise, and from 0.75 to socratic. It keeps unfinished lessons in course order and applies PD-204 to the review order. With adaptation disabled or no valid course mastery, it returns the configured default plan and static order. Any eventual caller must source mastery from trusted assessment evidence.

With synchronization enabled, the quiz writer acquires the record lock before inserting the attempt. The quota counts the authenticated principal's attempts on that lesson over the preceding 15 minutes and refuses the thirteenth. Durable writers allocate assessment clocks from the locked server replica and commit the attempt, learner record and assessment fact together. Preview identities record the attempt without writing mastery. The synchronization-off path preserves the baseline protocol. The planner uses only the dedicated assessment facts for mastery.

The one-shot guest claim retains the account's unique profile, public handle, and duplicate receipt records. It joins convergent learner state before transferring remaining study rows. The guest's consent does not transfer. Transactional claim audit and the stable revocation digest support retry and credential-key rotation without retaining a raw guest credential in the tombstone.

The consent service stores a current row and erasable change history. Analytics checks the grant before writing when privacy is enabled. Managed write paths serialize on the principal guard while Phase 8 flags are active, including when synchronization is off. An existing guard or binding also preserves serialization on rollback. With privacy enabled, both erasure routes call the same service to lock the principal, delete its rows, verify zero remaining rows and commit the canonical receipt audit. The locked write path rechecks local and guest credentials after erasure. A retained federated principal resumes after its request observes the current epoch. Scoped NDJSON export omits credential data and counterpart identity fields. The receipt records the active package and registry, and states the scope for backups, support, historical processing, and external providers. Both audit tables and both write-guard states use their 365-day retention rules in every privacy mode.

## 5. Configuration package

Package v7 (7.0.0, SHA-256 `adf3aed271aaf2c84c852f2e0169825b9889577d4aa64573ea7066f12c97d1e5`) supersedes Phase 7's v6 (6.0.0, SHA-256 `cd16a12360b01b1250fdbb339da4c71701828197cd8dcd2629a6a9a34a3d5327`). It adds the provisional learner settings, `phase8_exit_passed: false`, and D-26 and D-27. All inherited decisions and contract pins carry forward. The EHMF block is identical in v6 and v7, including `config_version.first_package: "6.0.0"`.

The loader accepts integer schemas 1 through 7. It uses a separate upper bound from `EHMF_SCHEMA_VERSION` so EHMF checks apply from schema 6 onward and learner checks begin at schema 7. `EHMF_SCHEMA_VERSION` and `EHMF_FIRST_MAJOR` both equal 6. DI-317 tracks v6 readability. The golden-set runner appends v7 after the committed v6 history entry, and CI enforces the base branch's unchanged prefix.

The loader compares each engineering sub-block with the code policy. `sync` records the active replica cap, retirement order and retry limits. `assessment` has the attempt limit, window and completion threshold. `planner` has the bands, budget, renderer hand-back and harness levels. `privacy` records NDJSON export, canonical receipt hashing, audit retention and guard retention. The provisional marker, authority, consent version and consent-class policy are validated separately.

## 6. Settings

| Setting (env) | Type / development default | Freeze rationale |
|---|---|---|
| `LEARNER_SYNC` | `off` or `on` / `on` | Gates the new sync and assessment hardening. |
| `LEARNER_PLANNER` | `off`, `shadow`, or `on` / `shadow` | Shadow records choices. `on` requires DI-312 wiring. |
| `LEARNER_IDENTITY` | `off` or `on` / `off` | Isolates subject mapping and claim behavior. Preserve compatibility with the baseline demo fixtures. |
| `LEARNER_PRIVACY` | `off` or `on` / `on` | Gates consent, class-based guest retention, export, and erasure receipts. Audit and guard expiry run in either mode. |

All default to off outside development. Settings reject every non-off value outside development until the shipped, hash-verified configuration package reports the Phase 8 exit. A missing exit value is false. The package loader refuses `phase8_exit_passed=true` while D-27 is open (DI-300). Settings independently refuse `LEARNER_PRIVACY=on` outside development while D-27 is open, so analytics retains the existing policy under PD-200. Adaptation stays off outside development with provisional consent. Planner on is refused everywhere pending DI-312. The planner consults the shared adaptation-stop row and uses static ordering while it is set. Plan L specifies "Flags for planner and sync. Stop: any harness violation blocks adaptation (never evidence)." CI fails on a harness violation, and an explicit operator harness run records the database stop. DI-319 covers the deferred runtime trigger.

## 7. File-by-file changes

| File | Responsibility |
|---|---|
| `.gitattributes`, `AGENTS.md` | Record LF for the Phase 8 spec and branch-specific coordination rules. The agent file governs this branch. |
| `apps/api/app/core/config.py`, `apps/api/app/core/phase8_settings.py` | Add the learner switches, provisional policy and startup refusals. |
| `apps/api/app/core/auth.py`, `apps/api/app/core/authorization.py` | Preserve core authentication interfaces, add signed-credential privacy admission, and keep the contiguous Phase 8 route-policy block. |
| `apps/api/app/db_models.py`, `apps/api/app/schemas.py` | Define the additive ORM tables and the synchronization and privacy response contracts. |
| `apps/api/app/api/routes/learner_record.py`, `apps/api/app/api/routes/content.py` | Implement issued replicas, guarded synchronization, and trusted assessment facts. |
| `apps/api/app/api/routes/auth.py`, `apps/api/app/api/routes/analytics.py` | Apply the lifecycle and consent checks in the existing routers. |
| `apps/api/app/services/learner_record.py`, `apps/api/app/services/learner_record_sync.py` | Retain convergent operations and add serialized version checks. |
| `apps/api/app/services/learner_record_identity.py`, `apps/api/app/services/learner_record_lock.py` | Bind identities, claim guest records, and serialize writes with erasure. |
| `apps/api/app/services/learner_record_privacy.py`, `apps/api/app/services/learner_record_metrics.py` | Verify erasure, persist receipt digests, stream caller exports, and emit operational signals. |
| `apps/api/app/services/learner_record_planner.py`, `apps/api/app/services/learner_record_shadow.py`, `apps/api/app/services/tutor_orchestrator.py` | Compute a deterministic plan and observe it in shadow. The shared orchestrator edit is limited to plan selection. |
| `apps/api/app/services/erasure.py`, `apps/api/app/services/retention.py`, `apps/api/app/services/guest_sessions.py`, `apps/api/app/services/local_accounts.py` | Reuse metadata-driven deletion, add retention and durable guest revocation, and integrate verified account deletion. |
| `apps/frontend/src/lib/api.ts`, `apps/frontend/src/lib/learner-record-api.ts`, `apps/frontend/src/lib/learner-record-sync.ts` | Limit the shared client edit to learner records, with replica transport and retry code in separate modules. |
| `apps/api/app/main.py` | Append the Phase 8 readiness fields in §10 and configuration-override keys. |
| `apps/api/app/core/config_package.py`, `apps/api/app/config_package/v7.json`, `apps/api/app/config_package/v7.json.sha256`, `scripts/config_package.py` | The package bump exception in §0.1 adds schema 7, the learner policy and the v6 predecessor hash. |
| `apps/api/app/services/ledger.py`, `apps/api/app/core/schema_upgrades.py`, `apps/api/alembic/versions/20261123_phase8_learner.py` | The migration-head exception in §0.1 adds one revision, the head constant, and the guard-column reconciliation. |
| `apps/api/app/services/tutor_followups.py`, `apps/api/app/services/tutor_pipeline/__init__.py`, `apps/api/app/services/tutor_pipeline/contracts.py`, `apps/api/app/services/tutor_pipeline/package_check.py` | The bump-docstring exception in §0.1 covers only the shipped-version sentences carried in the v7 integration. |
| `.github/workflows/ci.yml` | Append the predecessor readability and invariance checks listed in §14. |
| `scripts/run_golden_set.py`, `docs/evaluation/phase7/package_versions.json`, `docs/evaluation/phase7/golden_run_v1.json` | The package bump exception updates the runner's shipped-package description. The runner generates the v7 record and appends its history entry. |
| `scripts/prove_erasure.py`, `scripts/run_invariance_harness.py`, `docs/evaluation/phase8/README.md`, `docs/evaluation/phase8/erasure_proof_v1.json`, `docs/evaluation/phase8/invariance_harness_report_v1.json` | Provide the synthetic erasure proof, public invariance fixtures, their offline tools and operating notes. |
| `docs/evaluation/phase3/three_plan_replay_v1.json`, `docs/evaluation/phase4/v1_fixture_report_v1.json`, `docs/evaluation/phase5/v2_fixture_report_v1.json`, `docs/evaluation/phase6/v3_residual_report_v1.json` | Regenerate the inherited evaluation records under v7 following §12. |
| `docs/architecture/phase3-implementation-spec.md`, `docs/architecture/phase4-implementation-spec.md`, `docs/architecture/phase5-implementation-spec.md`, `docs/architecture/phase6-implementation-spec.md` | Correct shipped-version, migration and retention descriptions under the shared-file rules in §0.1. |
| `docs/architecture/ehmf-change-control.md` | The package bump exception documents the golden-set procedure for v7, the committed v6 prefix, and rollback to the prior release. |
| `docs/architecture/phase7-implementation-spec.md`, `docs/evaluation/phase7/README.md` | The bump-docstring exception aligns Phase 7's loader, golden-run provenance and rollback descriptions with the integrated release. |
| `docs/architecture/phase8-implementation-spec.md`, `docs/testing/test-strategy.md` | Record the Phase 8 design and its evidence, and map acceptance criteria to existing tests. |
| `docs/adr/ADR-001-grounding-separation.md`, `docs/adr/ADR-003-learner-record-synchronization.md` | Describe the isolated presentation boundary and add the dated synchronization revision. |
| `docs/security/authorization-matrix.md`, `docs/security/threat-model.md`, `docs/security/consent-schema.md`, `docs/security/consent-record.v1.schema.json`, `docs/security/identity-linking.md` | Regenerate the matrix and document the authorization, consent, retention, and linking contracts. |
| `infra/cloudrun/deployment.md`, `infra/cloudrun/observability.md`, `infra/cloudrun/retention-job.md` | Document the migration-head rollback order and append Phase 8 sections for operations, logging, and retention. |

## 8. Database

Revision `20261123_phase8_learner` follows `20261123_phase7_ehmf` and adds the ten Phase 8 tables. The revision accepts ORM-created tables and adds missing epoch and activity columns to the early guard table. Startup initializes those columns for earlier rows without resetting an existing epoch. Downgrade verifies that all Phase 8 tables are empty before removing their schema. A further downgrade crosses the separate Phase 7 `allow_ehmf_drop` guard. An image rollback leaves the schema and protection markers intact.

## 9. Routes and request-path behaviour

The existing routers serve replica issuance and synchronization under `/learner-record`, and claim, consent, export, and erasure under `/auth`. Claim requires a durable credential, a verified guest token, matching guest CSRF proof, and a trusted origin. Export and self-service erasure require a verified local session, signed guest credential, or Auth0 token. Both refuse all demo identities with 403. Local erasure confirms the password and clears cookies after commit. Guest erasure revokes the credential. Federated erasure covers local application data. Each new endpoint refuses requests when its feature flag is off.

Replica issuance returns 201. Record reads and applied or duplicate writes return 200. A version conflict returns 409 with `reason: cas_conflict` and the current `record_version`. Invalid inputs, untrusted mastery, reserved operations and nonfinite JSON return 422. Invalid replica ownership, retirement, clocks and changed replays return 409. New routes return 404 with their flags off. Claim proof failures return 403, unavailable guests return 409, and success returns 200. Consent returns 200 or 409 for an unavailable grant. Export returns 200 with no-store NDJSON. With privacy on, `POST /auth/learner-erasure` returns the verified receipt directly and `DELETE /auth/account` includes it under `receipt` alongside `status`. Both responses use `Cache-Control: no-store`, and refused password confirmation returns 401. With privacy off, account deletion returns the original `{"status":"deleted"}` body. Assessment quota refusal returns 429 with Retry-After 900.

Claim uses `guest_legacy_upgrade_rate_limit` (default 5/hour). Self-service erasure uses `auth_login_rate_limit` (default 10/minute) and requires a trusted origin for every provider. Both routes return 429 when their corresponding limit is exceeded. A stale write observation is refused with 409.

## 10. Start-up, /ready, logs and SLIs

Settings fail startup on refused values. Phase 8 records the following signals:

| Event | Fields |
|---|---|
| `learner.record.updated` | `interaction_started_at`, `record_committed_at`, `record_version`. |
| `learner.record.committed` | Process count of durable assessment-record commits. |
| `learner.sync.conflict` | Reason and process count. Reasons are `cas_conflict`, `counter_regressed`, `unissued_replica`, `payload_mismatch`, `client_mastery_refused`, and `server_namespace_refused`. |
| `learner.planner.shadow` | `plan_id`. |
| `learner.planner.degraded` | Exception type for a planner fault or budget overrun. Flag-off skips the planner. No-consent and held-stop fallbacks retain the ordinary shadow observation. |
| `analytics.consent_withheld` | Process count of withheld analytics writes. |
| `learner.harness.violation` | Invariance or evidential-state reason and process count. |
| `learner.harness.stop`, `learner.harness.clear` | Explicit local stop or clearance, with the reason. |
| `learner.export` | Digest-only security event for an authorized export. |
| `learner.erasure` | Digest-only security event with refusal status or deleted row total and `duration_ms`. Successful events feed the Phase 1 erasure-time distribution. |
| `account.delete` | Legacy local-deletion event with the same duration coverage. Verified receipts and their hashes stay in the response and receipt audit, respectively. |
| `subject.claimed`, `subject.claim_refused` | Claim outcome and transferred-row total on success. |

Readiness reports `phase8_exit_passed`, the configured modes and development-only `learner_slis`. It issues no new database read. The planner reads the shared stop at its own boundary. The development gauge `planner_stop_observed` reflects the most recent local observation, while the configured planner mode remains visible. The operator keys are `learner_sync_on`, `learner_identity_on`, `learner_privacy_on`, `learner_planner_shadow`, and `learner_planner_on`. The owner assigned the reserved verifier and tool counters to the main track under DI-318. Production F-3 and cloud metrics remain deferred under DI-300 and DI-305.

## 11. Frontend

The dormant synchronization helper obtains a replica from the server, advances its local clock from the observed server clock, and sends the expected record version. On a failed request it re-reads the record and retries once when the version advanced, preserving the batch's operation IDs. It uses the existing two storage keys. Production consent UI and learner-facing privacy-copy changes are tracked separately.

## 12. Fixtures and records

The erasure proof seeds user-keyed and dependent rows for local, guest, federated, demo, bound local, and claimed local synthetic cases. It queries survivors independently of the receipt and checks the control rows and persisted digest. The invariance tool runs three mastery levels and fresh evidential caches with the shadow gateway. It records actual rendered variation and compares resolved question, retrieval, thresholds, envelopes, non-alignment verifier payloads, evidence, claim plans, locked and delivered claims, citations, and final outcomes. Alignment keeps the pinned V1 readability constants. The CLI accepts a JSON selection of the approved public fixtures and the two-pass design. E3 and LQ-1 require separate research evidence.

The proof's synthetic demo case exercises the erasure service directly. HTTP export and erasure still require verified credentials.

The inherited reports regenerated for v7 are `docs/evaluation/phase3/three_plan_replay_v1.json`, `docs/evaluation/phase4/v1_fixture_report_v1.json`, `docs/evaluation/phase5/v2_fixture_report_v1.json`, and `docs/evaluation/phase6/v3_residual_report_v1.json`. The Phase 7 golden-set runner regenerates `docs/evaluation/phase7/golden_run_v1.json` and verifies the append-only package history. Section 17 records their provenance and digests.

## 13. Tests

### 13.1 Acceptance map

| Criterion | Regression tests |
|---|---|
| AC-8-1 | `test_learner_record_merges_divergent_replicas_without_losing_completion`, `test_phase8_sync_parallel_replicas_conflict_and_retry_without_losing_updates`, `test_ac_8_1_concurrent_trusted_updates_preserve_each_mastery_value`. These cover same-skill maximum in both merge orders, concurrent client conflict and retry, and concurrent trusted mastery on separate skills. |
| AC-8-2 | `test_phase8_sync_duplicate_receipts_and_monotonic_clock`, `test_phase8_sync_rejects_other_subjects_and_server_operations` |
| AC-8-3 | `test_ac_8_3_three_mastery_levels_yield_identical_claim_set_cited_spans_and_decision` |
| AC-8-4 | `test_ac_8_4_no_evidential_or_verifier_module_imports_a_phase8_module`, `test_ac_8_4_evidential_prompts_and_the_abstention_configuration_hold_zero_learner_state_fields`, `test_ac_8_4_a_learner_value_in_an_evidential_payload_is_detected` |
| AC-8-5 | `test_ac_8_5_every_erasure_route_writes_a_verified_receipt`, `test_ac_8_5_erasure_rolls_back_when_a_surviving_row_fails_verification`, `test_plan_f_the_committed_erasure_proof_matches_a_fresh_run`, `test_phase8_export_and_erasure_cover_bound_subject_and_legacy_rows`, `test_phase8_claimed_guest_and_account_erasure_leave_no_keyed_rows`, `test_phase8_erasure_refuses_an_in_flight_subject_rebind`, `test_phase8_erasure_serializes_with_unguarded_and_first_writers`, `test_phase8_a_principal_erased_and_signing_in_again_gets_a_fresh_empty_record` |
| AC-8-6 | `test_a_client_sent_score_is_ignored`, `test_durable_mastery_follows_the_server_score`, `test_phase8_sync_rejects_other_subjects_and_server_operations`, `test_phase8_privacy_http_consent_export_erasure_and_assessment` |
| AC-8-7 | `test_ac_8_7_the_privacy_inventory_equals_the_cookies_and_storage_keys_in_code` |

### 13.2 Module coverage

| Test module | Coverage implemented |
|---|---|
| `test_phase8_settings.py` | Development and production defaults, pre-exit startup refusal, verified package requirement, D-27, and DI-312. |
| `test_phase8_sync.py` | No INSERT on read, stale and duplicate operations, cross-subject ownership, server namespace, compare-and-set retry, bounded quota and replica issuance, and concurrent trusted mastery updates. |
| `test_phase8_planner.py` | Provisional mastery bands, deterministic lesson ordering, and static fallback. |
| `test_phase8_identity.py` | Provider-scoped subject continuity, guest proof requirements, claim transfer, revocation, and the audit record. |
| `test_phase8_privacy.py` | Consent denial and research refusal, mapped and legacy export, cross-subject isolation, transactional erasure, and receipt verification across principal types. |
| `test_phase8_evidence.py` | Invariance, F-2 import isolation, report checks, consent schema, retention map, disclosure inventory, and adaptation stop persistence. |
| `test_phase8_routes.py` | HTTP coverage of flag-off behavior, version-preserving cutover, and the principal privacy lifecycle. |
| `test_phase8_docs.py` | Spec, decision and test-map guards. |

### 13.3 Changes to existing tests

The table records top-level test functions and assignments that differ from the Phase 7 baseline `512b8a6`. The baseline checks still protect the unchanged Phase 3 readiness function, Phase 5 acceptance file, Phase 6 readiness function, and v4 and v5 readability assertions.

| Module | Test or fixture | Exception | Change and preserved intent |
|---|---|---|---|
| `apps/frontend/tests/privacy-inventory.integration.test.ts` | `AC-8-7: the privacy page lists exactly the browser-storage keys the code uses` | AC-8-7 inventory coverage | Renamed and replaced `every browser-storage key the code uses is in the privacy page storage inventory, and nothing else`. The exact inventory comparison remains. |
| `apps/frontend/tests/privacy-inventory.integration.test.ts` | `AC-8-7: the privacy page lists exactly the cookies the code sets or reads` | AC-8-7 inventory coverage | Renamed and replaced `every cookie the code sets or reads is in the privacy page cookie inventory, and nothing else`. The exact inventory comparison remains. |
| `test_api.py` | `test_progress_endpoint_aggregates_activity` | Progress fixture in §0.1 | Pins privacy off for this fixture, preserving the existing analytics aggregation check. |
| `test_authorization.py` | `_actual_access` | Route authorization coverage in §0.1 | Recognizes the new privacy dependency so the route-policy match remains exact. |
| `test_authorization.py` | `_write_everything` | Route authorization coverage in §0.1 | Obtains an issued replica and analytics consent so the fixture stores the owner marker. |
| `test_authorization.py` | `ALLOWED_KINDS` | Route authorization coverage in §0.1 | Adds the verified-principal access rule and runs the same denial checks for excluded demo roles. |
| `test_authorization.py` | `CALLER_READS` | Route authorization coverage in §0.1 | Keeps verified export in the existing cross-caller isolation test. |
| `test_authorization.py` | `MARKER_EXPECTED` | Route authorization coverage in §0.1 | Requires the learner's own export to contain its seeded marker, so the isolation check cannot pass vacuously. |
| `test_authorization.py` | `test_a_refused_caller_is_refused` | Route authorization coverage in §0.1 | Enables the development claim route for the denied-principal case. |
| `test_authorization.py` | `test_there_are_negatives_for_every_restricted_access_level` | Route authorization coverage in §0.1 | Requires refusal cases for the verified-principal access level. |
| `test_config_package.py` | `_the_unedited_copies_load` | Package bump exception in §0.1 | Adds the v6 control and keeps the pre-mutation load checks for later schemas. |
| `test_config_package.py` | `_v5_edit_applies_to_v6` | Package bump exception in §0.1 | Reads the explicit v6 payload to keep the exceptions tied to the Phase 7 changes. |
| `test_config_package.py` | `test_the_shipped_package_validates_and_matches_its_hash` | Package bump exception in §0.1 | Checks the shipped schema and v6 predecessor hash while retaining the gateway, audit, and EHMF checks. |
| `test_config_package.py` | `test_the_v5_edits_v6_changes_are_exactly_the_three_it_makes` | Package bump exception in §0.1 | Reads the explicit v6 package to retain the original Phase 7 comparison. |
| `test_config_package.py` | `test_v4_structural_errors_always_stop_the_load` | Package bump exception in §0.1 | Checks v4 through v7 and uses schema 8 in place of the no-op schema assignment on v5. |
| `test_config_package.py` | `test_v5_structural_errors_always_stop_the_load` | Package bump exception in §0.1 | Runs v5 refusals across v5, v6 and v7 while preserving the Phase 7 exceptions for changed values. |
| `test_config_package.py` | `V6_RAW` | Package bump exception in §0.1 | Reads the Phase 7 package explicitly as the comparison baseline. |
| `test_configuration_overrides.py` | `REFUSED_RELAXATIONS` | Readiness and override cases in §0.1 | Adds all five Phase 8 cases without dropping the inherited Phase 7 cases. |
| `test_configuration_overrides.py` | `write_package` | Bump-docstring exception in §0.1 | Names the actual shipped package while the helper still copies the package and its schemas. |
| `test_cs595_increment.py` | `test_learner_record_api_requires_a_durable_session_and_accepts_idempotent_operations` | Synchronization compatibility | Obtains the issued replica and sends the expected version. The durable-session and completion assertions remain. |
| `test_ehmf_units.py` | `test_the_phase_7_package_number_is_read_from_one_constant_per_side` | Package bump exception in §0.1 | Pins the first EHMF version to the explicit Phase 7 package and checks the independent ceiling against the shipped package. |
| `test_erasure_retention.py` | `_seed_everything` | Metadata-driven erasure coverage | Seeds assessment foreign keys from their parent rows, preserving coverage across all user-keyed tables. |
| `test_erasure_retention.py` | `test_account_deletion_uses_full_erasure` | Local account deletion compatibility | Runs the inherited exemption fixture with privacy off and still requires every non-exempt row to be gone. The verified privacy-on contract is covered under AC-8-5. |
| `test_erasure_retention.py` | `test_retention_removes_stale_guest_rows_in_every_table_and_keeps_the_rest` | Retention compatibility in §0.1 | Preserves stale, fresh and durable coverage and classifies intentionally retained credentials and bindings when privacy is on. |
| `test_malformed_input.py` | `_learner_record_write` | Synchronization compatibility | Acquires a replica only in the guarded mode, preserving the legacy malformed input path. |
| `test_malformed_input.py` | `test_a_learner_record_value_that_cannot_be_stored_is_refused_and_the_record_still_reads` | Synchronization compatibility | Exercises both modes while preserving rejection and the subsequent read. |
| `test_malformed_input.py` | `test_non_finite_preference_follows_the_flagged_backend_contract` | Synchronization compatibility | Renamed and replaced `test_a_non_finite_preference_is_refused_on_postgres_and_never_a_500`. Preserves PostgreSQL refusal and checks that neither mode returns 500. |
| `test_phase3_acceptance.py` | `test_plan_g_the_alembic_revision_is_reversible_and_refuses_to_drop_a_non_empty_ledger` | Migration-head exception in §0.1 | Steps through the Phase 8 head before testing the older downgrade and data-loss refusal. |
| `test_phase4_acceptance.py` | `test_phase4_docs_the_code_texts_name_the_shipped_package` | Package bump exception in §0.1 | Repoints the module text to v7 and checks that v7 retains v6's schema set and earlier pins. |
| `test_phase4_acceptance.py` | `test_phase4_docs_the_phase3_spec_states_what_phase4_changed` | Package bump exception in §0.1 | Repoints the package, independent loader ceiling and fixture-version pins to v7 while preserving their checks. |
| `test_phase6_acceptance.py` | `test_phase6_docs_the_phase_3_rollback_checks_the_stamp_against_the_current_head` | Migration-head exception in §0.1 | Checks the Phase 8 stamp and the absolute rollback to Phase 7 while retaining the EHMF, V3 and ledger safeguards. |
| `test_phase6_acceptance.py` | `test_plan_g_the_phase_6_revision_is_additive_reversible_and_keeps_its_rows` | Migration-head exception in §0.1 | Checks the Phase 8 head and the Phase 7 and 6 parents, then unwinds the empty Phase 8 schema before the V3 retention guards. |
| `test_phase7_acceptance.py` | `test_ac_7_6_a_same_version_edit_hidden_by_editing_the_history_fails_the_ci_check_against_the_base` | Package bump exception in §0.1 | Keeps the earlier entries in the scratch history so the check isolates a same-version hash rewrite. The separate removal and reordering checks are retained. |
| `test_phase7_acceptance.py` | `test_plan_e_the_phase_7_downgrade_refuses_while_ehmf_stops_holds_rows_and_the_table_refuses_truncate` | Migration-head exception in §0.1 | Downgrades the empty Phase 8 schema first, then exercises the same EHMF table, truncate and downgrade guards. |
| `test_phase7_acceptance.py` | `test_plan_e_the_phase_7_revision_is_additive_reversible_and_keeps_its_rows` | Migration-head exception in §0.1 | Verifies the Phase 7 revision's existing parent and guard under the Phase 8 head. |
| `test_phase7_acceptance.py` | `test_plan_g_v5_stays_readable_and_v6_parses_v1_to_v4_records` | Package bump exception in §0.1 | Exercises the first EHMF package at explicit v6 and checks the shipped v7 carries the same EHMF contract. |
| `test_response_ledger_migrations.py` | `PHASE8_REVISION` | Migration-head exception in §0.1 | Names the revision used by the inherited stamp and absolute-target cases. |
| `test_response_ledger_migrations.py` | `PHASE8_TABLES` | Migration-head exception in §0.1 | Tracks the ten tables added by the revision for the upgrade and rollback checks. |
| `test_response_ledger_migrations.py` | `test_e10_the_absolute_downgrade_target_is_safe_in_every_stamp_state_the_runbook_allows` | Migration-head exception in §0.1 | Stamps the Phase 8 head, steps through the empty successor, and retains the absolute-target and ledger refusal checks. |
| `test_response_ledger_migrations.py` | `test_f14_the_forward_alembic_step_runs_only_on_a_phase2_stamp` | Migration-head exception in §0.1 | Checks the ordered Phase 3, 5, 6, 7 and 8 upgrades while retaining the Phase 2 stamp and invalid-replay assertions. |
| `test_structured_logging.py` | `test_erasure_time_covers_the_erase_and_its_commit_but_not_the_password_check` | Local account deletion compatibility | Pins privacy off for the existing fake clock and still measures the deletion and commit outside password confirmation. |

### 13.4 Phase 8 regression revisions

The quota helper test names the case where principal and subject match. The one-shot claim test names the guest CSRF check and successful retry refusal. The readiness regression exercises the in-process planner-stop observation. The newer erasure and demo-credential regressions cover the two verified erasure routes and replace the development demo-erasure case.

## 14. CI changes

The API and evaluation job checks v6 readability, the v7 golden-set record against the base branch, and the committed invariance report. Its existing pytest step verifies the erasure proof. PostgreSQL jobs verify the API suite with both drivers. The existing public-payload golden record remains the freeze boundary.

## 15. Docs and evidence

Subject linking and consent have security documentation, with a generated consent record schema. ADR-001 records the evidential and pedagogical boundary. ADR-003 has the dated Phase 8 synchronization revision, and the threat model names the D-26 controls. The authorization matrix, acceptance map, and retention runbook cover the new interfaces. Evidence records are generated from a clean build. The proposal to pin the consent schema remains for main-track review.

## 16. Provisional defaults and deferred items

### 16.1 Provisional defaults

The defaults are provisional. Each row names the code or artifact that enforces it.

| # | Decision | Plan text | Default applied | Where |
|---|---|---|---|---|
| PD-200 | D-27, consent classes and H13 (Product Owner and Principal Investigator) | 18.4 L3017: "- D-27 OPEN DECISION: consent classes before Phase 8 [Risk R-09]. PO, PI." 9.4 L1924: "\| H13  \| Consent [Decision D-27]       \| P8 start                       \| Consent classes        \|". | H13 remains held. Version `d27-unresolved-v1` classifies existing processing as unclassified and permits synthetic development grants for adaptation and analytics. While D-27 is open, the loader refuses a passed Phase 8 exit. Outside development the settings refuse `LEARNER_PRIVACY=on`, analytics retains the existing policy, and the planner uses static order. Research is refused everywhere. The default establishes no legal basis or toggle-free status. | `learner_record_privacy.py`, `consent-schema.md`, `phase8_settings.py`. |
| PD-201 | D-26 compare-and-set (Security Lead) | Phase 8 D L1573: "2) Server-issued replica clocks, monotonic counters, compare-and-set on record_version [Decision D-26]." | Check the expected version and serialize writes to the learner record. An out-of-date client re-reads and retries. Identical receipts remain idempotent. | `learner_record_sync.py` and the trusted assessment write path. |
| PD-202 | D-08 research timing and D-14 research data plane (Principal Investigator) | 18.3 L2987: "D-08 \|IRB and OSF timing (PI)             \|(a) before research use; (b) fixtures     \|No Phase 10 [Assumption A-10]" and L2988: "     \|                                    \|first                                     \|". | Apply D-08 option (a). Refuse research grants and research export everywhere. Use synthetic learners and the public fixture for engineering evidence. D-14 remains with DI-09. | `learner_record_privacy.py`, `run_invariance_harness.py`. |
| PD-203 | D-05 feature freeze | Phase 8 L L1606: "Flags for planner and sync. Stop: any harness violation blocks adaptation (never evidence)." | Keep all Phase 8 switches off outside development and refuse non-off values before the verified Phase 8 exit. Development defaults are sync on, planner shadow, identity off, and privacy on. Refuse planner on pending DI-312. | `phase8_settings.py`. |
| PD-204 | Engineering parameters (Engineering) | Phase 8 D L1574: "3) Mastery from server-scored assessments [Risk R-42]; planner (Loop 2) [Evidence E-74]." Phase 8 D L1577: "5) Consent record, scheduled retention, export, erasure across all providers with receipt [Risk R-08]." | Cap active replicas at 16 per subject. Confirm a preferred active replica, including one without an applied operation, or retire least-recently-used replicas to make room while preserving their clock and receipt history. Allow 12 attempts per principal and lesson per 15 minutes, then return 429 with Retry-After 900. CAS returns 409 with the current version and no server retry. The browser re-reads and retries once if the same principal's version advanced. The planner uses per-lesson maximum assessed mastery, completion at 0.7, a 150 ms shadow budget, bands at 0.4 and 0.75, and harness levels 0.1, 0.5, and 0.9. Preserve unfinished course order. Order completed review by ascending mastery, descending attempt count, then course order. Export streams NDJSON with credential tables withheld. The receipt contains a random ID, UTC time, consent version, zero counts, table-set SHA-256, package version and SHA-256, gateway registry, and scope. The audit holds the canonical receipt digest, table-set digest, and deleted count. | `learner_record_sync.py`, `learner-record-sync.ts`, `learner_record_planner.py`, `learner_record_shadow.py`, `learner_record_privacy.py`, `run_invariance_harness.py`. |
| PD-205 | Retention classes (Engineering and Data Steward) | Phase 8 D L1577: "5) Consent record, scheduled retention, export, erasure across all providers with receipt [Risk R-08]." | Privacy off uses the inherited guest-prefixed created_at rule. Privacy on uses class ages and bound guests, expires guest consent from updated_at, and retires legacy upgrade records into stable revocation digests. In every privacy mode the cleanup uses the package policy's 365-day audit and write-guard periods. Both guard states age from last_used_at, and stale observations share that maximum lifetime. Sessions follow their own expiry. The response ledger remains outside the expiry schedule pending PLAN-12.8. | `retention.py`, `consent-schema.md`, the scheduled retention worker. |

### 16.2 Deferred items

| # | Item | Who | State |
|---|---|---|---|
| DI-300 | Phase 8 exit. Require AC-8-1 through AC-8-7 and the invariance-harness step in a cited green main CI run. Hold `phase8_exit_passed` false pending D-27 and H13 (DI-301), defaults ratification (DI-302), A-17 (DI-303), and acceptance of the Phase 1 (DI-01, DI-02) and Phase 3 (DI-58) deviations under P1-D-18 and P2-12-D-04. F-3 requires a production log window under plan 15.2 and 20.1(b)2 (DI-305). No owner acceptance is recorded. Blocked by: open D-27, owner ratification and acceptance, network access for the A-17 schema and F-3 log reads, and production deploy under D-05 for F-3. | Engineering, Product Owner, Principal Investigator | Open |
| DI-301 | Decide D-27 consent classes and file H13 release evidence. Blocked by: open D-27. | Product Owner, Principal Investigator | Open |
| DI-302 | Ratify PD-200 through PD-205 and any additional Phase 8 provisional defaults. Blocked by: owner ratification. | Owners of the respective decisions | Open |
| DI-303 | Confirm A-17 and Q-19 with authorized table names and row counts before cutover. Blocked by: production access and unresolved Q-19. | Platform Owner, Data Steward | Deferred |
| DI-304 | Enable Phase 8 switches outside development, including the no-write reader, replica issuance and retirement, version and monotonic counter checks, finite-JSON refusal, reserved server namespace, server counter and assessment facts, quota, principal binding and missing-sub refusal, guest proof, consent gate, export and scoped erasure with receipt, retention classes, and the shadow planner. Blocked by: learner-facing enablement under D-05 and the Phase 8 exit in DI-300. | Platform Owner | Deferred |
| DI-305 | Add production F-3, conflict, and invariance metrics and alerts. Blocked by: cloud writes and production F-3 evidence under DI-300. | Platform Owner | Deferred |
| DI-306 | Delete the federated account at the identity provider. Platform erasure covers locally managed rows. Blocked by: a credentialed external write and the Phase 5 egress and shared-file boundaries. | Security Lead | Deferred |
| DI-307 | Establish provider-side erasure and retention for approved model providers. Blocked by: open D-07 and D-12 and unresolved Q-09. | Product Owner, Principal Investigator | Deferred |
| DI-308 | Determine whether historical processors received learner text. Blocked by: open D-12, unresolved Q-09, and production access. | Security Lead | Deferred |
| DI-309 | Verify and disclose the backup retention window. Blocked by: unresolved Q-03, authorized cloud evidence, and D-05 for learner-facing disclosure. | Platform Owner | Deferred |
| DI-310 | Obtain role reviews and two-person consent and configuration review with recorded access. Blocked by: open D-18 and the single-maintainer assumption A-9. | Security Lead, ML Engineer, Data Steward | Deferred |
| DI-311 | Apply the assessment attempt limit in production and address DI-65's outstanding rubric and assessment changes. Blocked by: D-05 and ratification of the PD-21 feedback rule. | Content Owner, Product Owner | Deferred |
| DI-312 | Connect the planner to the renderer under a new versioned tool contract and package pin. Until then `LEARNER_PLANNER=on` is refused. Blocked by: the shared-file boundary for tool schema, gateway output, and package pin. | Engineering (main track) | Handed over |
| DI-313 | Build the learner-facing consent UI after class approval. Blocked by: open D-27 and D-05. | Product Owner, Principal Investigator | Deferred |
| DI-314 | Publish approved consent-class disclosure. AC-8-7 covers the cookie and storage inventory. Blocked by: open D-27 and D-05. | Product Owner, Principal Investigator | Deferred |
| DI-315 | Re-review R-51 at the Phase 8 exit. Production carries the existing client mastery path until `LEARNER_SYNC` is enabled. Blocked by: open D-24, D-05, and DI-300. | Product Owner | Open |
| DI-316 | Closed 2026-11-22 by owner decision P2-12-D-05 following the rule-12 question. Account erasure keeps independently submitted support requests on the 540-day rule. `services/learner_record_privacy.py` and `services/erasure.py` record and enforce that scope. | Product Owner | Closed |
| DI-317 | Remove v6 and its readability check after one release. Blocked by: a production release after the Phase 8 merge, under D-05. The append-only golden-set history retains the v6 entry. | Engineering | Deferred |
| DI-318 | Dedicated counters at runtime evidential contract refusals and `ToolNotVisible` in `tutor_pipeline/contracts.py` and `gateway/tools.py`. Round 1 stopped these changes under rule 12 and the shared-file rule in §0.1. The owner answered the round-2 question by assigning both reserved changes to the main track. The Phase 8 harness and sync signals operate independently. | Engineering (main track) | Handed over |
| DI-319 | Wire the runtime stop-the-line trigger for learner state in an evidential prompt (plan 13.6). Blocked by the shared-file rule in §0.1 reserving `tutor_pipeline/contracts.py` and `gateway/tools.py` for the main track. CI still fails on harness violations and an explicit operator run sets the shared planner stop. | Engineering (main track) | Handed over |

Plan M: "[Risk R-01][Risk R-08][Risk R-41][Risk R-42][Risk R-51]; residual: backups keep erased rows for a window."

## 17. Verification, work order and exit

The build covers identity and synchronization, the privacy lifecycle, and the planner and invariance harness. Verification uses offline tests, local database legs, and isolated scratch files. Plan P: "AC-8-1 to AC-8-7 green; harness in CI." `phase8_exit_passed` stays false while DI-300 remains open.

The Phase 5 merged baseline passed 8 separately isolated template tests, 1,593 SQLite tests (2 skipped, 9 deselected, 3 xfailed), and 1,591 tests per PostgreSQL driver (9 deselected, 3 xfailed each). Frontend lint, type checking, and 154 integration tests passed. The existing validators passed, including package v1 through v4, the V2 fixture report, and all 1,192 frozen public payload bodies. The path boundary scan passed. Licensed-passage scanning requires the fingerprint input. The two Phase 8 validators were added after this baseline run.

The first build passed 43 targeted tests on each database backend, including the Phase 8 modules and existing learner-record, erasure, and gateway egress tests. The freeze, planner threshold, and version-conflict tests failed under their respective in-process mutations. The setup install reported 11 moderate npm advisories. Package and lock files retain the integrated versions.

The merged SQLite leg ran `apps/api/tests evaluation/tests`. Both PostgreSQL legs ran `apps/api/tests` only, matching the workflow's path. Each leg excluded the eight template-reading cases below and the release-job-only `test_deployment_artifacts.py::test_release_artifacts_exist_and_describe_seeded_demo_transparency`. The template cases were separately run on SQLite with `--tb=no -rN -q` and all eight passed. Thus SQLite reconciles to 1,601 and the API-only PostgreSQL inventory reconciles to 1,599 per driver. Including the four cases in `evaluation/tests/test_evaluators.py` would produce 1,603. The reported main PostgreSQL total matches that combined inventory, although the checked-in workflow uses the API-only path.

- `test_deployment_artifacts.py::test_k8s_database_url_moves_to_secret_example`
- `test_deployment_artifacts.py::test_api_cloud_run_example_disables_demo_auth_and_documents_secret_injection`
- `test_phase3_docs.py::test_i5_the_registers_and_spec_sections_6_and_16_say_what_the_code_does`
- `test_phase3_docs.py::test_k3_the_authoritative_text_states_the_current_code_only`
- `test_phase4_acceptance.py::test_phase4_docs_state_the_learner_path_v1_7_rule_wherever_they_name_it`
- `test_phase4_acceptance.py::test_phase4_docs_the_code_texts_name_the_shipped_package`
- `test_phase5_acceptance.py::test_plan_e_the_legacy_provider_code_is_retired_and_no_production_path_reached_it`
- `test_phase5_acceptance.py::test_phase5_docs_the_runbooks_and_registers_state_the_gateway_s_operations_exactly`

Sync wiring verification ran four API modules, `test_phase8_sync.py`, `test_cs595_increment.py`, `test_authorization.py`, and `test_malformed_input.py`, with 154 passed per SQLite, psycopg, and pg8000. This targeted selection has no template or release-artifact tests. Frontend lint, type checking and all 154 integration tests passed.

The inherited records and the two Phase 8 reports were generated from clean integration commit `cabe561`. The invariance report covers 299 public items, three mastery levels, 148 items with distinct rendered presentations, zero evidence differences, and zero learner-state fields. The erasure proof verifies four principal types plus bound and claimed accounts.

| Record | Input SHA-256 |
|---|---|
| Phase 3 tutor replay | `d9a1b3041ad7c831c5ed51fdf67202b44387c99de0040d0ca9affdf6278a8245` |
| Phase 4 V1 fixtures | `beeec26464c9fa2dfc1b9b9848eab50829eddd21f165b63d456a661bd1b83a16` |
| Phase 5 V2 fixtures | `a2b2db1843bc5224a8dd96fa5370877058d9b28415eee7fc525a37fe086a9d88` |
| Phase 6 V3 residual proof | `f5eda7c4322ed95f3e3a3a017783343ee3ad7f2136cfd0dadb08b9722f03d671` |
| Phase 8 invariance | `0151605d3720dd5ba5c0514b35656c0fe3f1f26b180e4e52c90ef188834c410b` |

The erasure proof deliberately omits module hashes. Each scenario pins its table set and verifies the corresponding receipt digest in the scratch database.

The final pre-integration lifecycle run passed 222 tests per backend on SQLite, PostgreSQL with psycopg, and PostgreSQL with pg8000. Each leg ran these eight files under `apps/api/tests`: `test_phase8_identity.py`, `test_phase8_privacy.py`, `test_phase8_sync.py`, `test_phase8_evidence.py`, `test_authorization.py`, `test_erasure_retention.py`, `test_api.py`, and `test_gateway_egress_guard.py`. This selection had no deselections. An earlier 219-case run deselected only `test_plan_f_the_committed_erasure_proof_matches_a_fresh_run` until the report was generated. The final run includes that test and two additional report/schema checks. The eight named template cases passed separately on SQLite. Ten Python-source guards and the three Phase 3-5 test-map guards passed separately. The boundary path scan passed.

The integration merged Phase 6 in `45eb393` and used package v5 and revision `20261122_phase6_v3_audit` as predecessors. The full local verification runs cover this integrated tree. DI-300 remains open.

### 17.1 Round 1 integrated verification

The source and evidence tree tested was `1779690`. Frontend lint, type checking, and 167 integration tests passed. The first database runs hit the checkout-integrity guard because concurrent TypeScript compilation wrote its incremental cache. The full database reruns below completed successfully after all frontend commands finished. PostgreSQL used the isolated UTF-8 PostgreSQL 17 cluster with a fresh database for each driver. Branch CI uses PostgreSQL 16.

| Local leg | Main test paths | Passed | Skipped | Deselected | Expected failures | Template tests passed separately | Combined passed |
|---|---|---:|---:|---:|---:|---:|---:|
| SQLite | `apps/api/tests evaluation/tests` | 1978 | 2 | 11 | 3 | 10 | 1988 |
| PostgreSQL psycopg | `apps/api/tests` | 1976 | 0 | 11 | 3 | 10 | 1986 |
| PostgreSQL pg8000 | `apps/api/tests` | 1976 | 0 | 11 | 3 | 10 | 1986 |

The eleven deselections are precisely the eight template tests listed above, two Phase 6 template tests, and `test_deployment_artifacts.py::test_release_artifacts_exist_and_describe_seeded_demo_transparency` under the release-only marker. The two Phase 6 IDs are `test_phase6_acceptance.py::test_phase6_docs_quote_the_plan_and_state_the_current_rules` and `test_phase6_acceptance.py::test_phase6_docs_state_what_each_caller_of_a_v3_route_gets`. All ten template tests passed by ID with `--tb=no -rN -q` on every backend. The SQLite selection has four evaluation tests and two database-specific skips. The PostgreSQL jobs use the API-only selection, which accounts for the two-test difference in combined passes.

Package v1 through v6 checks, authorization matrix, manifest and calibration, public corpus and recall controls, draft LQS, all six evidence reports, all 1,192 frozen public payloads, and the repository and Docker-context path boundary checks passed. Licensed-passage scanning requires its fingerprint input. The built-image scan and dependency audits are CI checks. The previously recorded 11 moderate npm advisories carry forward without dependency changes.

Forty process-local Python mutation cases and one frontend mutation case produced the failures their regressions are intended to catch. The isolated mutation runs made no source changes. DI-318 records the remaining shared-file stop under R1-07. The engineering harness and local evidence do not pass the formal Phase 8 exit.

### 17.2 Round 2 evidence and verification

All six reports were regenerated from clean source commit `cb2a33e`. The invariance harness ran 299 public fixture items at three synthetic mastery levels in the two-pass design. It found zero violations and zero learner-state fields and produced 148 items with distinct rendered presentations. This satisfies the engineering prerequisite for plan 15.2 (LQ-1). The erasure proof verifies six synthetic scenarios without module-hash inputs.

| Record | SHA-256 |
|---|---|
| Phase 3 tutor replay | `1054690f43ba5b5cbb8c6427137bcd47f8d44da2c136e8af7aa725fe03b7632b` |
| Phase 4 V1 fixtures | `7b5c93d1843af9fb14de728c4f05c0ed79e201349b06f946e7d76c27f1b165b3` |
| Phase 5 V2 fixtures | `0852723b6e43f43ded0664253970361abd5c51f869fa2efdeddb7ccf4ef71d3d` |
| Phase 6 V3 residual report | `05321c90b7563d7a7347f1df7eff088cc3010eeeafee932a8ffc54fe22f87e68` |
| Phase 8 invariance | `dd2d2921445429a66480b00decb3bf652fb54b7228f68584760da2ea50b35602` |
| Phase 8 erasure proof (report content) | `551caa3b40c7944b73ac355400947a54886f7d06d718a4b689c3ac4e5cf24204` |

The regression checks detected 43 process-local mutations. The checks exercised the original retention signature and readiness constraints, erasure races and post-erasure recovery, quota scope, event fields, trusted mastery, package policy, and drift in the spec and runbooks. A separate hand-back check verifies the required response fields.

The full local checklist passed on `b8a423b`. Frontend lint, type checking, and 167 integration tests passed. Local PostgreSQL used an isolated PostgreSQL 17 cluster, and CI uses PostgreSQL 16.

| Local leg | Main test paths | Passed | Skipped | Deselected | Expected failures | Template tests passed separately | Combined passed |
|---|---|---:|---:|---:|---:|---:|---:|
| SQLite | `apps/api/tests evaluation/tests` | 2002 | 2 | 11 | 3 | 10 | 2012 |
| PostgreSQL psycopg | `apps/api/tests` | 2000 | 0 | 11 | 3 | 10 | 2010 |
| PostgreSQL pg8000 | `apps/api/tests` | 2000 | 0 | 11 | 3 | 10 | 2010 |

The separate runs used exactly the ten template-reading IDs listed in §§17 and 17.1, each on all three backends. The remaining deselection is the release-only test named in §17.1. The SQLite leg includes four evaluation tests and skips two PostgreSQL-specific cases, which accounts for its two additional passes. Each combined total is 24 higher than its round 1 total.

All 21 local validator invocations passed, including v1 through v6 readability, the authorization matrix, the corpus and recall checks, draft LQS, manifest and calibration, the six evidence records, and all 1,192 frozen public response bodies. The repository and Docker-context path checks passed. Licensed-passage coverage requires the fingerprint input, and CI runs the dependency audits and built-image boundary scan.

### 17.3 Round 2 integration with Phase 7

Merge `bf4fe3a` brings in main `512b8a6`. The clean integration source `ef99f9d` generated the six engineering reports below and the v7 golden-set record. The golden-set run passed all 40 items and resolved 47 of 47 delivered citations. The runner appended v7 after the v6 record from main, and the v7 record pins the package version and hash. The invariance harness ran 299 public items at three mastery levels, with 148 distinct renderings, zero violations, and zero learner-state fields. The erasure proof regenerated byte for byte.

| Record | SHA-256 |
|---|---|
| Phase 7 golden-set inputs | `c1917c132b5cb9e7621eef9e7686c802054893dafedd5a36d067b5bf2fafc873` |
| Phase 3 tutor replay | `f63c0aae1c4aa05f56c7bf1ef371c864bd1f02581b5ed3e1291fe1c4cfc8acc6` |
| Phase 4 V1 fixtures | `b78aace6ecc72cbb1ed29ad76580542b3509ec9007eba2deb12bb403a41ae0e8` |
| Phase 5 V2 fixtures | `1db8cde16314289c93bbb8972c18f8c6b4eb778844d0071b006acd59de10210c` |
| Phase 6 V3 residual report | `9439b95371f9a9fcae0b867269ab563c1115e0db76bbf8bd45e50cad75baac4b` |
| Phase 8 invariance | `7af91871e7b2e35c896679baa8083d04544e0d089e3622115ac6f7f1e941232d` |
| Phase 8 erasure proof (report content) | `551caa3b40c7944b73ac355400947a54886f7d06d718a4b689c3ac4e5cf24204` |

The merged regression set detected 47 process-local mutations, including the 43 round-2 cases and four loader-ceiling and EHMF-version cases.

The full local rerun on clean commit `598ad9d` passed after two inherited Phase 7 test fixtures were adapted to v7 and the Phase 3 planner description was restored. The compatibility commit changes tests and documentation. Frontend lint, type checking, and 167 integration tests passed. Isolated PostgreSQL 17 supplied both local driver legs. CI uses PostgreSQL 16.

| Local leg | Main test paths | Passed | Skipped | Deselected | Expected failures | Template tests passed separately | Combined passed |
|---|---|---:|---:|---:|---:|---:|---:|
| SQLite | `apps/api/tests evaluation/tests` | 2094 | 2 | 12 | 3 | 11 | 2105 |
| PostgreSQL psycopg | `apps/api/tests` | 2092 | 0 | 12 | 3 | 11 | 2103 |
| PostgreSQL pg8000 | `apps/api/tests` | 2092 | 0 | 12 | 3 | 11 | 2103 |

The eleven separately run IDs are the ten in §§17 and 17.1 plus `test_phase7_acceptance.py::test_phase7_docs_quote_the_plan_and_state_the_current_rules`. The remaining deselection is the single release-only case from §17.1. The SQLite total is 158 above Phase 7 main `512b8a6` (1,947 passed, 2 skipped, 1 deselected, 3 xfailed). The two extra SQLite passes relative to either PostgreSQL leg come from four evaluation tests and two PostgreSQL-specific skips on SQLite.

All 24 local validator runs passed, including packages v1–v7, the golden-set check with `--base-ref origin/main`, and all 1,192 frozen public response bodies. The source-fidelity check confirms the existing three mismatches under DI-105. Repository and Docker-context path checks passed. Licensed-passage coverage requires the fingerprint input. Dependency audits and the built-image scan run in CI.

### 17.4 Round 3 verification

The seven reports were regenerated from clean source commit `c466957` under package v7. The Phase 7 golden-set run covers 40 items and resolves all delivered citations. The runner verified the committed v6 history prefix and the existing v7 pin. The Phase 8 invariance run covers 299 public items at three mastery levels with zero violations and zero evidential learner-state fields. The independent erasure proof regenerated byte for byte.

| Record | SHA-256 |
|---|---|
| Phase 3 tutor replay | `fba78dce0e712f67341a2c9a40a9b9128ff7695e8e78d5b7c1abfe7b3e4703e1` |
| Phase 4 V1 fixtures | `4d8e7a13aee994f9aaa94364702cf4ddd47e561c9c34d4ed0c73ec51ee38790f` |
| Phase 5 V2 fixtures | `b210b4dd24e1bf1290a070dd24f9d6d45049dffd09994b33edb15e0706deaada` |
| Phase 6 V3 residual report | `b9beb5f8d25fd7f139fc5fd093ed155ea6317ab00d897b687bc2c2cae71a9347` |
| Phase 8 invariance harness | `1daac5f9df43efe30b1d54a75ab7df810f3f7854e87fa783d88935a872a6b3b0` |
| Phase 8 erasure proof | `551caa3b40c7944b73ac355400947a54886f7d06d718a4b689c3ac4e5cf24204` (report content) |
| Phase 7 EHMF golden set | `2aeec9f6effc1f7cea75772f62e430c5a64462325a668ca5c94b5fb17c7fb4cc` |

The focused erasure checks passed on SQLite, psycopg, and pg8000. The regression tests detected 30 process-local reverts covering all 14 upheld findings.

The full local checklist passed on `e10b802`. Frontend lint, type checking, and 167 integration tests passed. Both PostgreSQL driver legs used the isolated local PostgreSQL 17 cluster. CI uses PostgreSQL 16.

| Local leg | Main test paths | Passed | Skipped | Deselected | Expected failures | Template tests passed separately | Combined passed |
|---|---|---:|---:|---:|---:|---:|---:|
| SQLite | `apps/api/tests evaluation/tests` | 2120 | 2 | 12 | 3 | 11 | 2131 |
| PostgreSQL psycopg | `apps/api/tests` | 2118 | 0 | 12 | 3 | 11 | 2129 |
| PostgreSQL pg8000 | `apps/api/tests` | 2118 | 0 | 12 | 3 | 11 | 2129 |

The eleven template-reading IDs listed in §17.3 passed separately on each backend. The single release-only test is the remaining exclusion after the runs are combined. SQLite includes four evaluation tests and skips two PostgreSQL-specific cases. Each backend gained 26 passes over round 2. The combined SQLite count is 184 higher than the Phase 7 main baseline of 1,947.

All 24 local validators passed, including packages v1 through v7, the base-ref EHMF golden-set check, and all 1,192 frozen public response bodies. The source-fidelity check confirms the three recorded mismatches under DI-105. The repository and Docker-context path checks passed. Licensed-passage scanning requires fingerprint input, and CI runs the dependency audits and built-image boundary scan.

## 18. Review history

The rows record the build and each review round in order. Sections 0–17 describe the current implementation. Each review row summarizes the changes and names representative regression tests.

| Round | Commit | Findings fixed (one line each, with their tests) |
|---|---|---|
| Spec (pre-code) | - | Initial design and verification map. |
| Build | `cb142b1` | Settings, synchronization, identity, privacy lifecycle, shadow planner, and engineering evidence. Regression guards include `test_settings_phase8_defaults_and_refusals`, `test_ac_8_1_concurrent_trusted_updates_preserve_each_mastery_value`, `test_phase8_claim_requires_guest_csrf_and_is_one_shot`, `test_plan_f_the_committed_erasure_proof_matches_a_fresh_run`, and `test_plan_p_the_committed_invariance_report_matches_a_fresh_run`. |
| Review 1 | `8c7b7d4` | Route ownership and PD register guards, serialized cutover and erasure, claim and privacy HTTP coverage, active replica lifecycle, measurable invariance, retention, and spec controls. See `test_phase8_route_policies_form_one_block_after_the_learner_record_rows`, `test_phase8_docs_pd_204_states_the_engineering_constants_in_code`, `test_phase8_erasure_refuses_an_in_flight_subject_rebind`, `test_phase8_privacy_http_consent_export_erasure_and_assessment`, and `test_ac_8_4_a_learner_value_in_an_evidential_payload_is_detected`. |
| Review 2 | `cb2a33e`, merge `bf4fe3a`, integration `ef99f9d` | Restored the retention and readiness contracts and verified erasure serialization, retained-principal recovery, expiry, F-3 and trusted mastery. The owner assigned DI-318 to the main track. Phase 7 main `512b8a6` entered through `bf4fe3a`. Package v7 SHA-256 is `adf3aed271aaf2c84c852f2e0169825b9889577d4aa64573ea7066f12c97d1e5`. Alembic `down_revision` is `20261123_phase7_ehmf`. The full rerun on `598ad9d` passed 2,105 on SQLite (+158 from the 1,947 main baseline) and 2,103 on each PostgreSQL driver, including 11 separately run template tests per backend. See §17.3 for paths and counts. Regression guards include `test_phase8_erase_stale_guest_rows_keeps_its_two_argument_signature`, `test_phase8_keeps_protected_acceptance_tests_at_the_phase7_baseline`, `test_phase8_erasure_serializes_with_unguarded_and_first_writers`, `test_phase8_a_principal_erased_and_signing_in_again_gets_a_fresh_empty_record`, `test_phase8_loader_refuses_schema_versions_outside_the_latest_bound`, and `test_phase8_migration_retains_existing_tables_and_refuses_data_loss`. |
| Review 3 | `c466957` | Verified receipts for both erasure routes, checked the privacy freeze and authenticated export and erasure, enforced D-27 and retention policy, and reconciled the shared-file and test records. DI-319 records the hand-over for the runtime stop trigger. See `test_ac_8_5_every_erasure_route_writes_a_verified_receipt`, `test_phase8_a_demo_header_cannot_export_or_erase_another_principal`, `test_freeze_phase8_privacy_requires_d27_even_after_exit`, and `test_phase8_docs_names_the_shared_files_and_changes_to_existing_tests`. |
