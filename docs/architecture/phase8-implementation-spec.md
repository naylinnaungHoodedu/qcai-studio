# QC+AI Studio: Phase 8 implementation spec

Learner adaptation and privacy-preserving record, upgrade plan lines 1557-1614. The branch was cut at `98f7cc4` and its current integration base is `31343c8`.

Sections 0-17 describe the behaviour the code has and identify deferred integration work. Section 18 holds one history-table row per review round. This file is LF in every checkout (`.gitattributes`).

## 0. Ground rules, measured facts, readings

Smoke and acceptance checks use synthetic fixtures and run offline under the branch rules and shared-file limits in §0.1. The verified Phase 6 integration base is `31343c86c23007cec227b38413e0e53140f714a5` (PR #38, main CI run 45180967316, reported green by the owner). The branch ships package v6 and Alembic head `20261123_phase8_learner`. Phase 6 added package v5, migration `20261122_phase6_v3_audit`, and the user-keyed `v3_claims` and `v3_flags` tables. Their erasure and retention scope is explicit.

Phase 5 added `gateway_budget_days`, `gateway_stops`, and `evidential_cache_entries` to the shared ORM and updated the migration chain. The retrieval engine delegates embedding egress to `app/gateway/embeddings.py`. Its import guard allows only the Pinecone index SDK exception in the retrieval engine. The handoff's Phase 5 snapshot of untouched database files and its earlier embedding exception no longer describe the integrated code. Phase 8 uses the existing shared-file ownership limits and treats the added gateway tables and embedding implementation as Phase 5-owned.

The learner-record baseline uses the get-or-create path for reads, rejects changed-payload receipt replays, and advances `record_version` independently of an expected version. The retention worker uses the existing retention service. The acceptance readings are in section 13.

### 0.1 Shared file ownership

The §8.1 boundaries apply to the following files and entry points.

| Shared area | Permitted edits |
|---|---|
| `core/config.py`, `core/auth.py`, `core/authorization.py` | One learner settings block and validator. Preserve the `AuthUser` fields and the `get_current_user` signature. Place all Phase 8 policies together after the existing learner-record entries. |
| `app/main.py` | Keep existing routers and add readiness fields and configuration-override keys after the main integration. Phase 8 readiness uses in-process state and issues no database query. |
| `services/erasure.py`, `services/retention.py`, `workers/retention.py` | Preserve `erase_user(db, user_id)`, `erase_stale_guest_rows(db, cutoff)` and `run_retention_cleanup(db, now=None)`. Every intentional exemption has a documented reason. |
| `app/gateway/**`, `services/v2_panel/**`, `services/v1_checks/**`, `services/teaching_assistant.py` and the evidential pipeline | Keep the verifier and gateway code and contracts under main-track ownership. The bump-docstring exception covers shipped-version text in the designated modules only. The hashes and published schemas stay fixed. |
| `services/ledger.py`, `core/schema_upgrades.py`, and Alembic | Change `SCHEMA_REVISION` and add Phase 8 schema reconciliation and one additive revision after the merge. Keep the earlier revisions and ledger behavior. |
| `core/config_package.py`, `config_package/*`, `scripts/config_package.py` | The package bump adds one version, its loader validation and test pins. Existing version files and schemas remain readable. |
| `services/tutor_orchestrator.py` and the frontend integration | Observe the planner in shadow only. Keep new browser transport separate. Change only the existing learner-record functions and types in the shared frontend client. |
| `.github/workflows/ci.yml`, `test-strategy.md` and `.gitattributes` | Add the predecessor readability and invariance checks to CI. Test strategy and attributes take append-only Phase 8 sections, with the duplicate merged exit paragraph removed under R2-07. |
| `test_phase3_acceptance.py`, `test_response_ledger_migrations.py` | Only §7.5 migration-head generalisation. The inherited readiness SQL assertion is protected. |
| `test_phase4_acceptance.py`, `test_phase5_acceptance.py` | Only the specified shipped-version pins in the isolated bump. The Phase 5 gateway-stop assertion is protected. The Phase 8 guard pins the unchanged Phase 5 source. |
| `test_configuration_overrides.py`, `test_api.py` | The former takes the package-copy docstring and one case per Phase 8 override. The latter permits only the consent fixture for progress aggregation. |
| Templates, generated freeze baseline, shared test harness and dependencies | Keep protected templates out of ordinary suite output. Preserve the public-payload golden file, test setup and lockfiles. |

## 1. Conflicts between plan text and fixed decisions

- **H13 and D-27.** Plan L1566 requires a consent model, and L1907 says "a hold stops the named work until its release evidence is filed". The owner authorized isolated engineering under P1-D-18, with the main-track record P2-12-D-04. H13 remains held. DI-300 and DI-301 keep the Phase 1 and 3 prerequisites and the consent decision visible.
- **Baseline and ownership.** The baseline already scores quizzes on the server and runs scheduled retention. The designated learner tables use the bound subject, including assessment facts and issued replicas. Notes, threads, quiz attempts, credentials, and other legacy activity keep the authenticated principal, including the federated subject value where applicable. Export and erasure traverse both keys. Existing bindings remain authoritative through flag rollback. First bind preserves a lone record's version. Identity defaults off in development to preserve the baseline demo and authentication contracts.
- **Revocation and finality.** `guest_sessions.py` uses a domain-separated SHA-256 tombstone in `learner_guest_revocations` so recognition survives signing-key rotation. Guest erasure removes the corresponding raw legacy revocation. The first managed writer and both erasure routes serialize on the same principal guard. The locked path rechecks local and guest credentials. Retained federated and explicit demo principals can resume after a fresh request observes the new erasure epoch. Earlier observations are refused under the lock. Both guard states expire after 365 days of inactivity. Guest revocation survives guard expiry and flag rollback.
- **Assessment and R-03.** Stage-9 ratings and flags are operational signals. Only server assessment facts feed planner mastery, and the quota counts attempts by authenticated principal and lesson. Sequential quiz attempt IDs remain opaque response metadata for a caller's own activity and are not accepted on an ID-addressed cross-learner endpoint.
- **Consent and retention.** Plan L938 ties `consent_version` to analytics admission and `retention_class` to automatic cleanup. With privacy off, `erase_stale_guest_rows(db, cutoff)` selects timestamped guest-prefixed rows by `created_at`, matching Phase 6. Privacy on selects the class-specific age rules and recognizes bound guests. Durable rows stay until erasure unless a specific expiry applies. PD-200 controls provisional grants. P2-12-D-05 keeps the 540-day rule for independently submitted support requests, even when the address matches a deleted account. DI-316 is closed. A-17 and Q-19 remain unresolved.
- **Method and test layout.** The harness feeds plan IDs from the pure planner using synthetic mastery values and the existing presentation request seam. It uses public two-pass engineering fixtures. Research designs remain governed by D-08 and DI-312 covers live presentation wiring. The document guard compares section 3's table with the ORM's columns, and the acceptance map resolves tests across feature-specific modules.
- **Shadow timing.** The planner issues set-based reads within a savepoint. PostgreSQL bounds each statement and restores the prior budget. Work exceeding 150 ms is recorded as degraded and the existing shadow job proceeds. The elapsed budget also detects slow local work after it returns.
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

## 4. Algorithms

- Issued replicas belong to a subject. Existing receipts are evaluated before stale clocks. New operations validate replica ownership, monotonicity and causal-vector scope. A conflict-tolerant insert and one transaction handle first writes and version checks without a server retry.
- Assessment counters and facts commit with the server-scored attempt. The client writer refuses client mastery and server-owned operation or replica identifiers.
- The planner selects lesson order and style from trusted assessment facts and attempt state. The default plan and static order cover unavailability and absent adaptation consent.
- Erasure follows metadata-derived, child-first table coverage and persists the canonical receipt digest and coverage summary. The guest revocation digest survives signing-key rotation. The receipt states the local data scope and available processor and backup information.

In `learner_record_sync.py`, a conflict-tolerant insert creates the record when needed. A version-preserving row update acquires the transaction's write lock, then the service checks the expected version and reads the subject's issued replicas. All new operations have strictly increasing clocks and known causal counters. Identical operations in the same batch generate one applied receipt followed by duplicate receipts. A replay containing only known operations can recover its receipts after the record advances. The read-only entry point returns a version-zero record for a missing subject without issuing an insert.

The planner maps the mean finite course-local server mastery below 0.4 to stepwise, from 0.4 through values below 0.75 to concise, and from 0.75 to socratic. It keeps unfinished lessons in course order and applies PD-204 to the review order. With adaptation disabled or no valid course mastery, it returns the configured default plan and static order. Any eventual caller must source mastery from trusted assessment evidence.

With synchronization enabled, the quiz writer acquires the record lock before inserting the attempt. The quota counts the authenticated principal's attempts on that lesson over the preceding 15 minutes and refuses the thirteenth. Durable writers allocate assessment clocks from the locked server replica and commit the attempt, learner record and assessment fact together. Preview identities record the attempt without writing mastery. The synchronization-off path preserves the baseline protocol. The planner uses only the dedicated assessment facts for mastery.

The one-shot guest claim retains the account's unique profile, public handle, and duplicate receipt records. It joins convergent learner state before transferring remaining study rows. The guest's consent does not transfer. Transactional claim audit and the stable revocation digest support retry and credential-key rotation without retaining a raw guest credential in the tombstone.

The consent service stores a current row and erasable change history. Analytics checks the grant before writing when privacy is enabled. Managed write paths serialize on the principal guard while Phase 8 flags are active, including when synchronization is off. An existing guard or binding also preserves serialization on rollback. Both erasure routes publish a new epoch in their deletion transaction. Durable local and guest credentials are rechecked after the lock. Retained principals resume only when their request observes the current epoch. Scoped NDJSON export omits credential data and counterpart identity fields. The erasure receipt verifies the deletion scope and records the active package and registry, including the exclusions for backups, support, historical processing, and external identity providers.

## 5. Configuration package

Package v6 (6.0.0) supersedes v5 (5.0.0, SHA-256 `ed91a98f8f3cca200e2164381da966ce9ec8f8a2de2120d2c2fc6fd77e9b2e68`). It adds the provisional learner settings, `phase8_exit_passed: false`, and the D-26 and D-27 entries. V5's D-08 and all prior decision entries are preserved. The evidence, gateway, and V3 contract pins carry forward. DI-317 identifies the v5 readability step. Phase 7 must renumber if Phase 8 merges first, and Phase 8 must renumber if Phase 7 takes v6 on main first.

The loader compares each engineering sub-block with the code policy. `sync` records the active replica cap, retirement order and retry limits. `assessment` has the attempt limit, window and completion threshold. `planner` has the bands, budget, renderer hand-back and harness levels. `privacy` records NDJSON export, canonical receipt hashing, audit retention and guard retention. The provisional marker, authority, consent version and consent-class policy are validated separately.

## 6. Settings

| Setting (env) | Type / development default | Freeze rationale |
|---|---|---|
| `LEARNER_SYNC` | `off` or `on` / `on` | Gates the new sync and assessment hardening. |
| `LEARNER_PLANNER` | `off`, `shadow`, or `on` / `shadow` | Shadow records choices. `on` requires DI-312 wiring. |
| `LEARNER_IDENTITY` | `off` or `on` / `off` | Isolates subject mapping and claim behavior. Preserve compatibility with the baseline demo fixtures. |
| `LEARNER_PRIVACY` | `off` or `on` / `on` | Gates consent, retention additions, export, and erasure receipts. |

All default to off outside development. Settings reject every non-off value outside development until the shipped, hash-verified configuration package reports the Phase 8 exit. A missing exit value is false. D-27 independently precludes adaptation outside development. Planner on is refused everywhere pending DI-312. The planner consults the shared adaptation-stop row and uses static ordering while it is set. Plan L: "Flags for planner and sync. Stop: any harness violation blocks adaptation (never evidence)."

## 7. File-by-file changes

| File | Responsibility |
|---|---|
| `core/config.py`, `core/phase8_settings.py` | Flag anchors, provisional defaults, and package-gated startup refusals. |
| `core/auth.py`, `core/authorization.py` | Bearer subject validation and the contiguous authorization block. |
| `db_models.py`, `schemas.py` | Additive ORM models and public contracts. |
| `api/routes/learner_record.py`, `api/routes/content.py` | Guarded writes, issued replicas, and server assessment facts. |
| `api/routes/auth.py`, `api/routes/analytics.py` | Claim, consent, export, erasure, and consent admission. |
| `services/learner_record.py`, `services/learner_record_sync.py` | Convergent operations and serialized version checks. |
| `services/learner_record_identity.py`, `services/learner_record_lock.py` | Stable bindings, guest claim, and write finality. |
| `services/learner_record_privacy.py`, `services/learner_record_metrics.py` | Lifecycle and identifier-free signals. |
| `services/learner_record_planner.py`, `services/learner_record_shadow.py`, `services/tutor_orchestrator.py` | Pure planner, policy and stop enforcement, and shadow observation only. |
| `services/erasure.py`, `services/retention.py`, `services/guest_sessions.py`, `services/local_accounts.py` | Metadata coverage, class-based expiry, stable revocation, and compatibility with account deletion. |
| `src/lib/api.ts`, `src/lib/learner-record-api.ts`, `src/lib/learner-record-sync.ts` | Existing versioned writer, replica transport, and offline-safe clock and retry behavior. |
| `app/main.py` | §8.3(c) adds the Phase 8 settings, last observed stop and configuration override keys. |
| `core/config_package.py`, `config_package/v6.json` and its sidecar, `scripts/config_package.py` | The §7.4 exception adds schema 6 validation and the predecessor hash. |
| `services/ledger.py`, `core/schema_upgrades.py`, `alembic/versions/20261123_phase8_learner.py` | §7.5 advances `SCHEMA_REVISION` and adds the additive migration and reconciliation for early guard tables. |
| `services/tutor_followups.py`, `tutor_pipeline/__init__.py`, `tutor_pipeline/contracts.py`, `tutor_pipeline/package_check.py` | Shipped-version text under the §7.4 bump-docstring exception. |
| `.github/workflows/ci.yml` | §7.4 keeps v5 readable and §8.3(g) checks the invariance report. |
| `scripts/prove_erasure.py`, `scripts/run_invariance_harness.py` | Phase 8 owns the independent proof and the public fixture replay. The checks run offline. |
| `docs/architecture/phase3-implementation-spec.md`, `docs/architecture/phase4-implementation-spec.md`, `docs/architecture/phase5-implementation-spec.md`, `docs/architecture/phase6-implementation-spec.md` | The §7.4 and §7.5 exceptions update shipped-version and migration references. R2-02 restores the Phase 3 readiness boundary. |
| `docs/adr/ADR-001-grounding-separation.md`, `docs/adr/ADR-003-learner-record-synchronization.md` | Describe the implemented presentation boundary and add the dated synchronization record. |
| `docs/security/authorization-matrix.md`, `docs/security/threat-model.md` | Regenerate the route matrix from policy and document the D-26 controls. |
| `infra/cloudrun/deployment.md`, `infra/cloudrun/observability.md`, `infra/cloudrun/retention-job.md` | Record the §7.5 rollback step and add the Phase 8 operator sections for startup, signals, and cleanup. |
| `docs/testing/test-strategy.md` and `.gitattributes` | Append this phase's acceptance map and LF spec entry. Round 2 removes a duplicate inherited exit paragraph. |

## 8. Database

Revision `20261123_phase8_learner` follows `20261122_phase6_v3_audit` and adds the ten Phase 8 tables. The revision accepts ORM-created tables and adds missing epoch and activity columns to the early guard table. Startup initializes those columns for earlier rows without resetting an existing epoch. Downgrade verifies that all Phase 8 tables are empty before removing their schema. An image rollback leaves the schema and protection markers intact.

## 9. Routes and request-path behaviour

The existing routers serve replica issuance and synchronization under `/learner-record`, and claim, consent, export, and erasure under `/auth`. Claim requires a durable credential, a verified guest token, matching guest CSRF proof, and a trusted origin. The other privacy operations are caller-scoped. Local erasure confirms the password and clears cookies after commit. Guest erasure revokes the credential. Federated erasure covers local application data. Each new endpoint refuses requests when its feature flag is off.

Replica issuance returns 201. Record reads and applied or duplicate writes return 200. A version conflict returns 409 with `reason: cas_conflict` and the current `record_version`. Invalid inputs, untrusted mastery, reserved operations and nonfinite JSON return 422. Invalid replica ownership, retirement, clocks and changed replays return 409. New routes return 404 with their flags off. Claim proof failures return 403, unavailable guests return 409, and success returns 200. Consent returns 200 or 409 for an unavailable grant. Export returns 200 with no-store NDJSON. Erasure returns 200 with a receipt or 401 for refused password confirmation. Assessment quota refusal returns 429 with Retry-After 900.

Claim uses `guest_legacy_upgrade_rate_limit` (default 5/hour). Erasure uses `auth_login_rate_limit` (default 10/minute) and requires a trusted origin for every provider. Both routes return 429 when their corresponding limit is exceeded. The shared unauthenticated demo identity is refused with 403. A stale write observation is refused with 409.

## 10. Start-up, /ready, logs and SLIs

Settings fail startup on refused values. Phase 8 records the following signals:

| Event | Fields |
|---|---|
| `learner.record.updated` | `interaction_started_at`, `record_committed_at`, `record_version`. |
| `learner.record.committed` | Process count of durable assessment-record commits. |
| `learner.sync.conflict` | Reason and process count. Reasons are `cas_conflict`, `counter_regressed`, `unissued_replica`, `payload_mismatch`, `client_mastery_refused`, and `server_namespace_refused`. |
| `learner.planner.shadow` | `plan_id`. |
| `learner.planner.degraded` | Exception type. |
| `analytics.consent_withheld` | Process count of withheld analytics writes. |
| `learner.harness.violation` | Invariance or evidential-state reason and process count. |
| `learner.harness.stop`, `learner.harness.clear` | Explicit local stop or clearance, with the reason. |
| `learner.export` | Digest-only security event for an authorized export. |
| `learner.erasure` | Digest-only security event with refusal status or deleted row total and `duration_ms`. Successful events feed the Phase 1 erasure-time distribution. |
| `subject.claimed`, `subject.claim_refused` | Claim outcome and transferred-row total on success. |

Readiness reports `phase8_exit_passed`, the configured modes and development-only `learner_slis`. It issues no new database read. The planner reads the shared stop at its own boundary. The development gauge `planner_stop_observed` reflects the most recent local observation, while the configured planner mode remains visible. The operator keys are `learner_sync_on`, `learner_identity_on`, `learner_privacy_on`, `learner_planner_shadow`, and `learner_planner_on`. The owner assigned the reserved verifier and tool counters to the main track under DI-318. Production F-3 and cloud metrics remain deferred under DI-300 and DI-305.

## 11. Frontend

The dormant synchronization helper obtains a replica from the server, advances its local clock from the observed server clock, and sends the expected record version. On a failed request it re-reads the record and retries once when the version advanced, preserving the batch's operation IDs. It uses the existing two storage keys. Production consent UI and learner-facing privacy-copy changes are tracked separately.

## 12. Fixtures and records

The erasure proof seeds user-keyed and dependent rows for local, guest, federated, demo, bound local, and claimed local synthetic cases. It queries survivors independently of the receipt and checks the control rows and persisted digest. The invariance tool runs three mastery levels and fresh evidential caches with the shadow gateway. It records actual rendered variation and compares resolved question, retrieval, thresholds, envelopes, non-alignment verifier payloads, evidence, claim plans, locked and delivered claims, citations, and final outcomes. Alignment keeps the pinned V1 readability constants. The CLI accepts a JSON selection of the approved public fixtures and the two-pass design. E3 and LQ-1 require separate research evidence.

## 13. Tests

### 13.1 Acceptance map

| Criterion | Regression tests |
|---|---|
| AC-8-1 | `test_learner_record_merges_divergent_replicas_without_losing_completion`, `test_phase8_sync_parallel_replicas_conflict_and_retry_without_losing_updates`, `test_ac_8_1_concurrent_trusted_updates_preserve_each_mastery_value`. These cover same-skill maximum in both merge orders, concurrent client conflict and retry, and concurrent trusted mastery on separate skills. |
| AC-8-2 | `test_phase8_sync_duplicate_receipts_and_monotonic_clock`, `test_phase8_sync_rejects_other_subjects_and_server_operations` |
| AC-8-3 | `test_ac_8_3_three_mastery_levels_yield_identical_claim_set_cited_spans_and_decision` |
| AC-8-4 | `test_ac_8_4_no_evidential_or_verifier_module_imports_a_phase8_module`, `test_ac_8_4_evidential_prompts_and_the_abstention_configuration_hold_zero_learner_state_fields`, `test_ac_8_4_a_learner_value_in_an_evidential_payload_is_detected` |
| AC-8-5 | `test_plan_f_the_committed_erasure_proof_matches_a_fresh_run`, `test_phase8_export_and_erasure_cover_bound_subject_and_legacy_rows`, `test_phase8_claimed_guest_and_account_erasure_leave_no_keyed_rows`, `test_phase8_erasure_refuses_an_in_flight_subject_rebind`, `test_phase8_erasure_serializes_with_unguarded_and_first_writers`, `test_phase8_a_principal_erased_and_signing_in_again_gets_a_fresh_empty_record` |
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

| Module | Test or fixture | Exception | Change and preserved intent |
|---|---|---|---|
| `test_api.py` | `test_progress_endpoint_aggregates_activity` | §8.1 progress fixture | Pins privacy off for this fixture, preserving the existing analytics aggregation check. |
| `test_authorization.py` | `test_a_refused_caller_is_refused` | §8.1 authorization coverage | Enables the development claim route for the denied-principal case. |
| `test_authorization.py` | `_write_everything` | §8.1 authorization coverage | Obtains an issued replica and analytics consent so the fixture stores the owner marker. |
| `test_authorization.py` | `test_no_caller_scoped_read_returns_another_learners_data` | §8.1 authorization coverage | Requires the marker in the owner's export and still excludes it from a different learner's responses. |
| `test_config_package.py` | `test_the_shipped_package_validates_and_matches_its_hash` | §7.4 bump | Pins v6 and schema 6 as shipped while retaining the hash, gateway and audit checks. |
| `test_config_package.py` | `test_v4_structural_errors_always_stop_the_load` | §7.4 bump | Checks v4, v5 and v6, choosing the unsupported schema 7 mutation where schema 5 is now supported. |
| `test_config_package.py` | `test_v4_stays_readable_for_one_release` | §7.4 bump | Checks the v4 digest against v5's predecessor instead of v6's, preserving v4 readability. |
| `test_config_package.py` | `test_v5_keeps_every_v4_value_but_the_listed_changes` | §7.4 bump | Reads the explicit v5 fixture to preserve the v4-to-v5 change assertions. |
| `test_config_package.py` | `test_v5_structural_errors_always_stop_the_load` | §7.4 bump | Runs v5 refusals against both v5 and v6 and uses an actually unsupported schema number. |
| `test_configuration_overrides.py` | `write_package` | §7.4 bump docstring | Names the actual shipped package while the helper still copies the package and its schemas. |
| `test_configuration_overrides.py` | `test_c2_each_refused_relaxation_is_refused_and_still_recorded_under_its_own_key` | §8.3(c) override cases | Adds inherited parametrizations for the five Phase 8 keys. Each case still tests refusal and the corresponding audit key. |
| `test_cs595_increment.py` | `test_learner_record_api_requires_a_durable_session_and_accepts_idempotent_operations` | §8.1 sync contract | Obtains the issued replica and sends the expected version. The durable-session and completion assertions remain. |
| `test_erasure_retention.py` | `_seed_everything` | §8.1 metadata coverage | Seeds assessment foreign keys from their parent rows, preserving coverage across all user-keyed tables. |
| `test_erasure_retention.py` | `test_retention_removes_stale_guest_rows_in_every_table_and_keeps_the_rest` | §8.1 retention compatibility | Preserves stale, fresh and durable coverage and classifies intentionally retained credentials and bindings when privacy is on. |
| `test_malformed_input.py` | `_learner_record_write` | §8.1 sync contract | Acquires a replica only in the guarded mode, preserving the legacy malformed input path. |
| `test_malformed_input.py` | `test_a_learner_record_value_that_cannot_be_stored_is_refused_and_the_record_still_reads` | §8.1 sync contract | Exercises both modes while preserving rejection and the subsequent read. |
| `test_malformed_input.py` | `test_non_finite_preference_follows_the_flagged_backend_contract` | §8.1 sync contract | Separately pins the legacy backend-specific result and uniform guarded validation. |
| `test_phase3_acceptance.py` | `test_plan_g_the_alembic_revision_is_reversible_and_refuses_to_drop_a_non_empty_ledger` | §7.5 migration | Steps through the Phase 8 head before testing the older downgrade and data-loss refusal. |
| `test_phase3_acceptance.py` | `test_plan_i_ready_reports_versions_ledger_head_and_two_pass_mode` | R2-02 restored protected text | Round 1 widened the allowed queries. Round 2 restores the Phase 6 source and uses in-process observation for Phase 8 readiness. |
| `test_phase4_acceptance.py` | `test_phase4_docs_the_phase3_spec_states_what_phase4_changed` | §7.4 bump | Repoints the shipped name, schema tuple and fixture-version pins to v6 while preserving the text and fixture checks. |
| `test_phase4_acceptance.py` | `test_phase4_docs_the_code_texts_name_the_shipped_package` | §7.4 bump | Repoints the module text and inherited schema sets to v6 while retaining the Phase 4 and Phase 5 constraints. |
| `test_phase5_acceptance.py` | `test_phase5_docs_the_runbooks_and_registers_state_the_gateway_s_operations_exactly` | R2-02 restored protected text | Round 1 widened the pinned readiness phrase. Round 2 restores the inherited test and its gateway-only query scope. |
| `test_phase6_acceptance.py` | `test_plan_g_the_phase_6_revision_is_additive_reversible_and_keeps_its_rows` | §7.5 migration | Checks the v6-era descendant and unwinds the empty Phase 8 schema before exercising the V3 retention guards. |
| `test_phase6_acceptance.py` | `test_plan_i_ready_reports_package_v5_and_the_v3_fields_and_no_count` | §7.4 version pin and R2-02 restoration | The historical name says v5. The test checks the shipped package dynamically (v6 here) and retains the V3 assertions and gateway-only SQL allow-list. |
| `test_phase6_acceptance.py` | `test_phase6_docs_the_phase_3_rollback_checks_the_stamp_against_the_current_head` | §7.5 migration | Checks the Phase 8 head and absolute Phase 6 rollback step while retaining the earlier rollback and data-protection checks. |
| `test_response_ledger_migrations.py` | `test_e10_the_absolute_downgrade_target_is_safe_in_every_stamp_state_the_runbook_allows` | §7.5 migration | Stamps the Phase 8 head, steps through the empty successor, and retains the absolute-target and ledger refusal checks. |
| `test_response_ledger_migrations.py` | `test_f14_the_forward_alembic_step_runs_only_on_a_phase2_stamp` | §7.5 migration | Checks the ordered Phase 3, 5, 6 and 8 upgrades without changing the Phase 2 stamp and invalid-replay assertions. |
| `apps/frontend/tests/privacy-inventory.integration.test.ts` | `AC-8-7: the privacy page lists exactly the cookies the code sets or reads` | §8.1 inventory coverage | Names AC-8-7 explicitly and preserves the exact cookie comparison. |
| `apps/frontend/tests/privacy-inventory.integration.test.ts` | `AC-8-7: the privacy page lists exactly the browser-storage keys the code uses` | §8.1 inventory coverage | Names AC-8-7 explicitly and preserves the exact storage-key comparison. |
| `test_phase8_sync.py` | `test_phase8_assessment_quota_and_server_clock_when_principal_equals_subject` | R2-09 | Renamed the helper-level case to state when principal and subject match. The bound-account HTTP test guards the distinction. |
| `test_phase8_identity.py` | `test_phase8_claim_requires_guest_csrf_and_is_one_shot` | R2-28 | Renamed the one-shot and missing-CSRF test. Separate tests exercise forged and revoked credentials. |
| `test_phase8_evidence.py` | `test_phase8_readiness_reports_the_last_stop_observation_without_querying` | R2-02 | Replaces the SQL-based expectation with a query-free observation test. |

## 14. CI changes

The API and evaluation job checks v5 readability and the committed invariance report. Its existing pytest step verifies the erasure proof. PostgreSQL jobs verify the API suite with both drivers. The existing public-payload golden record remains the freeze boundary.

## 15. Docs and evidence

Subject linking and consent have security documentation, with a generated consent record schema. ADR-001 records the evidential and pedagogical boundary. ADR-003 has the dated Phase 8 synchronization revision, and the threat model names the D-26 controls. The authorization matrix, acceptance map, and retention runbook cover the new interfaces. Evidence records are generated from a clean build. The proposal to pin the consent schema remains for main-track review.

## 16. Provisional defaults and deferred items

### 16.1 Provisional defaults

The defaults are provisional. Each row names the code or artifact that enforces it.

| # | Decision | Plan text | Default applied | Where |
|---|---|---|---|---|
| PD-200 | D-27, consent classes and H13 (Product Owner and Principal Investigator) | 18.4 L3017: "- D-27 OPEN DECISION: consent classes before Phase 8 [Risk R-09]. PO, PI." 9.4 L1924: "\| H13  \| Consent [Decision D-27]       \| P8 start                       \| Consent classes        \|". | H13 remains held. Version `d27-unresolved-v1` classifies existing processing as unclassified and permits synthetic development grants for adaptation and analytics. Outside development those grants are refused, the planner uses the static order, and the analytics gate is off. Research is refused everywhere. The default establishes no legal basis or toggle-free status. | `learner_record_privacy.py`, `consent-schema.md`, `phase8_settings.py`. |
| PD-201 | D-26 compare-and-set (Security Lead) | Phase 8 D L1573: "2) Server-issued replica clocks, monotonic counters, compare-and-set on record_version [Decision D-26]." | Check the expected version and serialize writes to the learner record. An out-of-date client re-reads and retries. Identical receipts remain idempotent. | `learner_record_sync.py` and the trusted assessment write path. |
| PD-202 | D-08 research timing and D-14 research data plane (Principal Investigator) | 18.3 L2987: "D-08 \|IRB and OSF timing (PI)             \|(a) before research use; (b) fixtures     \|No Phase 10 [Assumption A-10]" and L2988: "     \|                                    \|first                                     \|". | Apply D-08 option (a). Refuse research grants and research export everywhere. Use synthetic learners and the public fixture for engineering evidence. D-14 remains with DI-09. | `learner_record_privacy.py`, `run_invariance_harness.py`. |
| PD-203 | D-05 feature freeze | Phase 8 L L1606: "Flags for planner and sync. Stop: any harness violation blocks adaptation (never evidence)." | Keep all Phase 8 switches off outside development and refuse non-off values before the verified Phase 8 exit. Development defaults are sync on, planner shadow, identity off, and privacy on. Refuse planner on pending DI-312. | `phase8_settings.py`. |
| PD-204 | Engineering parameters (Engineering) | Phase 8 D L1574: "3) Mastery from server-scored assessments [Risk R-42]; planner (Loop 2) [Evidence E-74]." Phase 8 D L1577: "5) Consent record, scheduled retention, export, erasure across all providers with receipt [Risk R-08]." | Cap active replicas at 16 per subject. Confirm a preferred active replica, including one without an applied operation, or retire least-recently-used replicas to make room while preserving their clock and receipt history. Allow 12 attempts per principal and lesson per 15 minutes, then return 429 with Retry-After 900. CAS returns 409 with the current version and no server retry. The browser re-reads and retries once if the same principal's version advanced. The planner uses per-lesson maximum assessed mastery, completion at 0.7, a 150 ms shadow budget, bands at 0.4 and 0.75, and harness levels 0.1, 0.5, and 0.9. Preserve unfinished course order. Order completed review by ascending mastery, descending attempt count, then course order. Export streams NDJSON with credential tables withheld. The receipt contains a random ID, UTC time, consent version, zero counts, table-set SHA-256, package version and SHA-256, gateway registry, and scope. The audit holds the canonical receipt digest, table-set digest, and deleted count. | `learner_record_sync.py`, `learner-record-sync.ts`, `learner_record_planner.py`, `learner_record_shadow.py`, `learner_record_privacy.py`, `run_invariance_harness.py`. |
| PD-205 | Retention classes (Engineering and Data Steward) | Phase 8 D L1577: "5) Consent record, scheduled retention, export, erasure across all providers with receipt [Risk R-08]." | Privacy off uses the inherited guest-prefixed created_at rule. Privacy on uses class ages and bound guests, expires guest consent from updated_at, retires legacy upgrade records into stable revocation digests, and applies 365-day audit and write-guard cleanup. Both guard states age from last_used_at, and stale observations share that maximum lifetime. Sessions follow their own expiry. The response ledger remains outside the expiry schedule pending PLAN-12.8. | `retention.py`, `consent-schema.md`, the scheduled retention worker. |

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
| DI-317 | Remove v5 and its readability check after one release. Blocked by: a production release after the Phase 8 merge, under D-05. | Engineering | Deferred |
| DI-318 | Dedicated counters at runtime evidential contract refusals and `ToolNotVisible` in `tutor_pipeline/contracts.py` and `gateway/tools.py`. Round 1 stopped these changes under rule 12 and §8.1. The owner answered the round-2 question by assigning both reserved changes to the main track. The Phase 8 harness and sync signals operate independently. | Engineering (main track) | Handed over |

Plan M: "[Risk R-01][Risk R-08][Risk R-41][Risk R-42][Risk R-51]; residual: backups keep erased rows for a window."

## 17. Verification, work order and exit

Start with the baseline, then implement identity and synchronization, the privacy lifecycle, and the planner and harness. Run offline tests and validators with isolated scratch files. Repeat the applicable SQLite, PostgreSQL, frontend, and integration checks against the final branch after the Phase 6 integration. Plan P: "AC-8-1 to AC-8-7 green; harness in CI." `phase8_exit_passed` stays false while DI-300 remains open.

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

The integration merged Phase 6 in `45eb393` and used package v5 and revision `20261122_phase6_v3_audit` as predecessors. The full §9.1 runs cover this integrated tree. DI-300 remains open.

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

The full §9.1 checklist passed on `b8a423b`. Frontend lint, type checking, and 167 integration tests passed. Local PostgreSQL used an isolated PostgreSQL 17 cluster, and CI uses PostgreSQL 16.

| Local leg | Main test paths | Passed | Skipped | Deselected | Expected failures | Template tests passed separately | Combined passed |
|---|---|---:|---:|---:|---:|---:|---:|
| SQLite | `apps/api/tests evaluation/tests` | 2002 | 2 | 11 | 3 | 10 | 2012 |
| PostgreSQL psycopg | `apps/api/tests` | 2000 | 0 | 11 | 3 | 10 | 2010 |
| PostgreSQL pg8000 | `apps/api/tests` | 2000 | 0 | 11 | 3 | 10 | 2010 |

The separate runs used exactly the ten template-reading IDs listed in §§17 and 17.1, each on all three backends. The remaining deselection is the release-only test named in §17.1. The SQLite leg includes four evaluation tests and skips two PostgreSQL-specific cases, which accounts for its two additional passes. Each combined total is 24 higher than its round 1 total.

All 21 local validator invocations passed, including v1 through v6 readability, the authorization matrix, the corpus and recall checks, draft LQS, manifest and calibration, the six evidence records, and all 1,192 frozen public response bodies. The repository and Docker-context path checks passed. Licensed-passage coverage requires the fingerprint input, and CI runs the dependency audits and built-image boundary scan.

## 18. Review history

The rows record the build and each review round in order. Sections 0–17 describe the current implementation. Each review row summarizes the changes and names representative regression tests.

| Round | Commit | Findings fixed (one line each, with their tests) |
|---|---|---|
| Spec (pre-code) | - | Initial design and verification map. |
| Build | `cb142b1` | Settings, synchronization, identity, privacy lifecycle, shadow planner, and engineering evidence. Regression guards include `test_settings_phase8_defaults_and_refusals`, `test_ac_8_1_concurrent_trusted_updates_preserve_each_mastery_value`, `test_phase8_claim_requires_guest_csrf_and_is_one_shot`, `test_plan_f_the_committed_erasure_proof_matches_a_fresh_run`, and `test_plan_p_the_committed_invariance_report_matches_a_fresh_run`. |
| Review 1 | `8c7b7d4` | Route ownership and PD register guards, serialized cutover and erasure, claim and privacy HTTP coverage, active replica lifecycle, measurable invariance, retention, and spec controls. See `test_phase8_route_policies_form_one_block_after_the_learner_record_rows`, `test_phase8_docs_pd_204_states_the_engineering_constants_in_code`, `test_phase8_erasure_refuses_an_in_flight_subject_rebind`, `test_phase8_privacy_http_consent_export_erasure_and_assessment`, and `test_ac_8_4_a_learner_value_in_an_evidential_payload_is_detected`. |
| Review 2 | `cb2a33e` | Restored the §8.1 retention and readiness contracts. Verified erasure serialization, retained-principal recovery, guard expiry, F-3, trusted mastery, package-code equality, and documentation traceability. The owner assigned DI-318 to the main track. See `test_phase8_erase_stale_guest_rows_keeps_its_two_argument_signature`, `test_phase8_keeps_protected_acceptance_tests_at_the_phase6_baseline`, `test_phase8_erasure_serializes_with_unguarded_and_first_writers`, and `test_phase8_a_principal_erased_and_signing_in_again_gets_a_fresh_empty_record`. |
