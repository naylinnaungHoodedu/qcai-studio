# QC+AI Studio: Phase 8 implementation spec

Learner adaptation and privacy-preserving record, upgrade plan lines 1557-1614. The branch was cut at `98f7cc4` and its current integration base is `512b8a6`.

Sections 0-17 describe the behaviour the code has and identify deferred integration work. Section 18 holds one history-table row per review round. This file is LF in every checkout (`.gitattributes`).

## 0. Ground rules, measured facts, readings

Smoke and acceptance checks use synthetic fixtures and run offline under the branch rules and shared-file limits in §0.1. Phase 7 reached main as `512b8a668f6bc95358183c4f173efb0daa44868c` (PR #39) and entered this branch in merge `bf4fe3a`. It contributes package v6, the EHMF stop table and revision, and the golden-set history. Phase 9 reached main as `d366e20980f1e26111ba9f45e95503715ec8564c` (PR #40) and entered this branch in merge `832a431`. Its package v7 adds ranking and the Phase 9 migration beneath Phase 8. Phase 8 ships package v8 and Alembic head `20261123_phase8_learner`. The preceding Phase 6 merge contributes the two user-keyed V3 tables covered by erasure and retention.

Phase 5 added `gateway_budget_days`, `gateway_stops`, and `evidential_cache_entries` to the shared ORM and updated the migration chain. The retrieval engine delegates embedding egress to `app/gateway/embeddings.py`. Its import guard allows the Pinecone index SDK in the retrieval engine. The shared-file rules in §0.1 preserve main-track ownership of the gateway tables and embedding implementation.

The learner-record baseline uses the get-or-create path for reads, rejects changed-payload receipt replays, and advances `record_version` independently of an expected version. The retention worker uses the existing retention service. The acceptance readings are in section 13.

### 0.1 Shared file ownership

The shared-file rules below apply relative to the integration base in §0. The **package bump exception** permits the new package version, its loader rules, and the version pins in existing tests. Its **bump-docstring exception** permits corrections to shipped-version text in designated shared modules and documentation. The **migration-head exception** covers the additive revision, the ledger head constant, and changes needed for existing upgrade and downgrade checks to traverse the new head. Phase 8 adds the readiness fields defined in §10 and the two CI steps in §14.

| Shared area | Permitted edits |
|---|---|
| `core/config.py`, `core/auth.py`, `core/authorization.py` | One learner settings block and validator. Preserve the `AuthUser` fields and the `get_current_user` signature. Place all Phase 8 policies together after the existing learner-record entries. |
| `app/main.py` | Keep existing routers and append Phase 8 readiness fields and configuration-override keys. Phase 8 uses its last in-process planner-stop observation. Phase 7 and Phase 9 retain their EHMF and ranking readiness fields and existing reads. |
| `services/erasure.py`, `services/retention.py`, `workers/retention.py` | Preserve `erase_user(db, user_id)`, `erase_stale_guest_rows(db, cutoff)` and `run_retention_cleanup(db, now=None)`. Every intentional exemption has a documented reason. |
| `app/gateway/**`, `services/v2_panel/**`, `services/v1_checks/**`, `services/teaching_assistant.py` and the evidential pipeline | Keep the verifier and gateway code and contracts under main-track ownership. The bump-docstring exception covers shipped-version text in the designated modules only. The hashes and published schemas stay fixed. |
| `services/ledger.py`, `core/schema_upgrades.py`, and Alembic | Change `SCHEMA_REVISION` and add Phase 8 schema reconciliation and one additive revision after the merge. Keep the earlier revisions and ledger behavior. |
| `core/config_package.py`, `config_package/*`, `scripts/config_package.py` | The package bump adds one version, its loader validation and test pins. Existing version files and schemas remain readable. |
| `services/tutor_orchestrator.py` and the frontend integration | Observe the planner in shadow only. Keep new browser transport separate. Change only the existing learner-record functions and types in the shared frontend client. |
| `.github/workflows/ci.yml`, `test-strategy.md` and `.gitattributes` | Add the predecessor readability and invariance checks to CI. The test strategy appends the Phase 8 acceptance map and corrects the inherited package and head descriptions in place (P2-12-D-03). The attributes file adds the Phase 8 spec's LF rule. |
| `test_phase3_acceptance.py`, `test_response_ledger_migrations.py` | The migration-head exception permits tests to traverse the new revision. The inherited readiness SQL assertion is protected. |
| `test_phase4_acceptance.py`, `test_phase5_acceptance.py` | Only the specified shipped-version pins in the isolated bump. The Phase 5 gateway-stop assertion is protected. The Phase 8 guard pins the unchanged Phase 5 source. |
| `test_phase7_acceptance.py` | The v6 checks read the explicit Phase 7 package. The migration checks follow the Phase 8 head while preserving the Phase 7 downgrade assertions. |
| `test_configuration_overrides.py`, `test_api.py` | The former takes the package-copy docstring and one case per Phase 8 override. The latter permits only the consent fixture for progress aggregation. |
| `docs/architecture/ehmf-change-control.md` | The package bump exception covers the shipped package, the append-only v6 and v7 history prefix, and the ordered rollback instructions. The Phase 7 change-control policy remains the authority. |
| `docs/architecture/phase7-implementation-spec.md`, `docs/evaluation/phase7/README.md` | The bump-docstring exception covers the default path, loader ceiling, golden-run provenance, test version descriptions in 13.2–13.3, and the documented migration sequence. Phase 7 retains its EHMF scope. |
| `AGENTS.md` and the shared records in §12 | Branch coordination uses the repository's agent rules. Versioned records are regenerated with their published tools against clean source. |
| Templates, generated freeze baseline, shared test harness and dependencies | Keep protected templates out of ordinary suite output. Preserve the public-payload golden file, test setup and lockfiles. |

## 1. Conflicts between plan text and fixed decisions

- **H13 and D-27.** Plan L1566 requires a consent model, and L1907 says "a hold stops the named work until its release evidence is filed". The owner authorized isolated engineering under P1-D-18, with the main-track record P2-12-D-04. H13 remains held. DI-300 and DI-301 keep the Phase 1 and 3 prerequisites and the consent decision visible.
- **Baseline and ownership.** The baseline already scores quizzes on the server and runs scheduled retention. The designated learner tables use the bound subject, including assessment facts and issued replicas. Notes, threads, quiz attempts, credentials, and other legacy activity keep the authenticated principal, including the federated subject value where applicable. Export and erasure traverse both keys. Existing bindings remain authoritative through flag rollback. First bind preserves a lone record's version. Identity defaults off in development to preserve the baseline demo and authentication contracts.
- **Revocation and finality.** `guest_sessions.py` uses a domain-separated SHA-256 tombstone in `learner_guest_revocations` so recognition survives signing-key rotation. Guest erasure removes the corresponding raw legacy revocation. Authenticated request writes and both erasure routes serialize on the same principal guard, including writes to legacy tables such as notes and tutor turns. The locked write path rechecks local-account existence, guest revocation, or the retained principal's write epoch. A retained federated account can resume after a fresh request observes the new erasure epoch. The lock refuses earlier observations. Both guard states expire after 365 days of inactivity in every privacy mode. Guest revocation survives guard expiry and flag rollback.
- **Privacy authentication.** Consent, export, and self-service erasure require a verified local session, signed guest credential, or Auth0 token. These routes refuse demo identities. While any Phase 8 flag is active the shared authentication resolver also rejects demo aliases in reserved or existing learner namespaces. Local account deletion requires a local session and password. With privacy enabled, both erasure routes return a verified receipt and persist its digest.
- **Assessment and R-03.** Stage-9 ratings and flags are operational signals. Only server assessment facts feed planner mastery, and the quota counts durable-account attempts by principal and lesson. Guest and demo scoring previews leave the authoritative assessment quota and record untouched. Sequential quiz attempt IDs remain opaque response metadata for a caller's own activity and are not accepted on an ID-addressed cross-learner endpoint.
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

With synchronization enabled, a durable quiz writer acquires the record lock before inserting its attempt. The quota counts the authenticated principal's attempts on the lesson over the preceding 15 minutes and refuses the thirteenth. The writer allocates assessment clocks from the locked server replica and commits the attempt, learner record and assessment fact together. Guest and demo previews record the attempt without entering that quota or record lock. The synchronization-off path preserves the baseline protocol. The planner uses only the dedicated assessment facts for mastery.

The one-shot guest claim retains the account's unique profile, public handle, and duplicate receipt records. It joins convergent learner state before transferring remaining study rows. The guest's consent does not transfer. Transactional claim audit and the stable revocation digest support retry and credential-key rotation without retaining a raw guest credential in the tombstone.

The consent service stores a current row and erasable change history. Analytics checks the grant before writing when privacy is enabled. While any Phase 8 switch is active, the authenticated request session locks the principal before ORM flushes, SQLAlchemy data mutations and row-locking selects. Each later transaction in that request reacquires the lock with the original credential or epoch observation. The dedicated erasure and claim routes keep their own lock ordering. Arena locks verified participants before profile or result writes. Public-handle allocation locks the projected owner and checks for current public activity when the owner's record was erased and later reopened.

With privacy enabled, both erasure routes call the same service to lock the principal, delete its rows, verify zero remaining rows and commit the canonical receipt audit. A waiting writer rechecks local-account existence, guest revocation or the federated epoch after acquiring the lock. A retained federated principal can start fresh activity from a current epoch. The all-off path retains the legacy response and processing rules, with existing guard and binding checks for learner-record operations and local deletion. Scoped NDJSON export omits credential data and counterpart identity fields. The receipt records the active package and registry, and states the scope for backups, support, historical processing, and external providers. Both audit tables and both write-guard states use their 365-day retention rules in every privacy mode.

## 5. Configuration package

Package v8 (8.0.0, SHA-256 `c14d28f110f0ddcf89aab4717ccd5e6555cba15ad6a266468b67b662229d1904`) supersedes Phase 9's v7 (7.0.0, SHA-256 `30c65633a31a5f06d6f985f0bdc62af761171415fd43800ae4c43b4e8c0fd5e6`). It adds the provisional learner settings, `phase8_exit_passed: false`, and D-26 and D-27. The EHMF block, including `config_version.first_package: "6.0.0"`, the `ranking-params-v1` block, and the V3 gold-label schema pin carry forward unchanged.

The loader accepts integer schemas 1 through 8. Its upper bound `LATEST_SCHEMA_VERSION` uses `LEARNER_SCHEMA_VERSION` (8). EHMF checks apply from schema 6 onward, ranking checks from schema 7 onward, and learner checks from schema 8 onward. `EHMF_SCHEMA_VERSION` and `EHMF_FIRST_MAJOR` stay at 6. `RANKING_SCHEMA_VERSION` reads `RANKING_FIRST_MAJOR` (7). DI-317 tracks v7 readability. The golden-set runner appends v8 after the committed v6 and v7 entries. CI verifies that the base history is an unchanged prefix.

The loader compares each engineering sub-block with the code policy. `sync` records the active replica cap, retirement order and retry limits. `assessment` has the attempt limit, window and completion threshold. `planner` has the bands, budget, renderer hand-back and harness levels. `privacy` records NDJSON export, canonical receipt hashing, audit retention and guard retention. The provisional marker, authority, consent version and consent-class policy are validated separately.

## 6. Settings

| Setting (env) | Type / development default | Freeze rationale |
|---|---|---|
| `LEARNER_SYNC` | `off` or `on` / `on` | Gates the new sync and assessment hardening. |
| `LEARNER_PLANNER` | `off`, `shadow`, or `on` / `shadow` | Shadow records choices. `on` requires DI-312 wiring. |
| `LEARNER_IDENTITY` | `off` or `on` / `off` | Isolates subject mapping and claim behavior. Preserve compatibility with the baseline demo fixtures. |
| `LEARNER_PRIVACY` | `off` or `on` / `on` | Gates consent, class-based guest retention, export, and erasure receipts. Audit and guard expiry run in either mode. |

All default to off outside development. Settings reject every non-off value outside development until the shipped, hash-verified configuration package reports the Phase 8 exit. A missing exit value is false. The package loader refuses `phase8_exit_passed=true` while D-27 is open (DI-300). Settings also require ratified D-27 consent for privacy on or planner shadow outside development, even after the exit. While D-27 is open, analytics retains the existing policy under PD-200 and adaptation stays off outside development. Planner on is refused everywhere pending DI-312. The planner consults the shared adaptation-stop row and uses static ordering while it is set. Plan L specifies "Flags for planner and sync. Stop: any harness violation blocks adaptation (never evidence)." CI fails on a harness violation, and an explicit operator harness run records the database stop. DI-319 covers the deferred runtime trigger.

## 7. File-by-file changes

| File | Responsibility |
|---|---|
| `.gitattributes`, `AGENTS.md` | Record LF for the Phase 8 spec and branch-specific coordination rules. The agent file governs this branch. |
| `apps/api/app/core/config.py`, `apps/api/app/core/phase8_settings.py` | Add the learner switches, provisional policy and startup refusals. |
| `apps/api/app/core/auth.py`, `apps/api/app/core/authorization.py` | Preserve core authentication interfaces, add signed-credential privacy admission, and keep the contiguous Phase 8 route-policy block. |
| `apps/api/app/db_models.py`, `apps/api/app/schemas.py` | Define the additive ORM tables and the synchronization and privacy response contracts. |
| `apps/api/app/api/routes/learner_record.py`, `apps/api/app/api/routes/content.py` | Implement issued replicas, guarded synchronization, and trusted assessment facts. |
| `apps/api/app/api/routes/auth.py`, `apps/api/app/api/routes/analytics.py` | Apply the lifecycle and verified-principal consent checks in the existing routers. |
| `apps/api/app/api/routes/arena.py`, `apps/api/app/services/arena_engine.py`, `apps/api/app/services/public_handles.py` | Guard socket profile and result writes for their actual participants and serialize public-handle allocation with erasure. |
| `apps/api/app/services/learner_record.py`, `apps/api/app/services/learner_record_sync.py` | Retain convergent operations and add serialized version checks. |
| `apps/api/app/services/learner_record_identity.py`, `apps/api/app/services/learner_record_lock.py` | Bind identities, claim guest records, and serialize writes with erasure. |
| `apps/api/app/services/learner_record_privacy.py`, `apps/api/app/services/learner_record_metrics.py` | Verify erasure, persist receipt digests, stream caller exports, and emit operational signals. |
| `apps/api/app/services/learner_record_planner.py`, `apps/api/app/services/learner_record_shadow.py`, `apps/api/app/services/tutor_orchestrator.py` | Compute a deterministic plan and observe it in shadow. The shared orchestrator edit is limited to plan selection. |
| `apps/api/app/services/erasure.py`, `apps/api/app/services/retention.py`, `apps/api/app/services/guest_sessions.py`, `apps/api/app/services/local_accounts.py` | Reuse metadata-driven deletion, add retention and durable guest revocation, and integrate verified account deletion. |
| `apps/frontend/src/lib/api.ts`, `apps/frontend/src/lib/learner-record-api.ts`, `apps/frontend/src/lib/learner-record-sync.ts` | Limit the shared client edit to learner records, with replica transport and retry code in separate modules. |
| `apps/api/app/main.py` | Append the Phase 8 readiness fields in §10 and configuration-override keys. |
| `apps/api/app/core/config_package.py`, `apps/api/app/config_package/v8.json`, `apps/api/app/config_package/v8.json.sha256`, `scripts/config_package.py` | The package bump exception in §0.1 adds schema 8, the learner policy and the v7 predecessor hash. |
| `apps/api/app/services/ledger.py`, `apps/api/app/core/schema_upgrades.py`, `apps/api/alembic/versions/20261123_phase8_learner.py` | The migration-head exception in §0.1 adds one revision, the head constant, and the guard-column reconciliation. |
| `.github/workflows/ci.yml` | Append the predecessor readability and invariance checks listed in §14. |
| `docs/evaluation/phase7/package_versions.json`, `docs/evaluation/phase7/golden_run_v1.json` | The golden-set runner writes the v8 record and appends its history entry. |
| `scripts/prove_erasure.py`, `scripts/run_invariance_harness.py`, `docs/evaluation/phase8/README.md`, `docs/evaluation/phase8/erasure_proof_v1.json`, `docs/evaluation/phase8/invariance_harness_report_v1.json` | Provide the synthetic erasure proof, public invariance fixtures, their offline tools and operating notes. |
| `docs/evaluation/phase3/three_plan_replay_v1.json`, `docs/evaluation/phase4/v1_fixture_report_v1.json`, `docs/evaluation/phase5/v2_fixture_report_v1.json`, `docs/evaluation/phase6/v3_residual_report_v1.json` | Regenerate the inherited evaluation records under v8 following §12. |
| `docs/architecture/phase3-implementation-spec.md`, `docs/architecture/phase4-implementation-spec.md`, `docs/architecture/phase5-implementation-spec.md`, `docs/architecture/phase6-implementation-spec.md` | Correct shipped-version, migration and retention descriptions under the shared-file rules in §0.1. |
| `docs/architecture/ehmf-change-control.md` | The package bump exception documents the golden-set procedure for v8, the committed v6 and v7 prefix, and rollback to the prior release. |
| `docs/architecture/phase9-implementation-spec.md`, `docs/evaluation/phase9/ranking_replay_v1.json` | Align the inherited ranking version checks and regenerate the replay with the v8 package pin. |
| `docs/architecture/phase7-implementation-spec.md`, `docs/evaluation/phase7/README.md` | The bump-docstring exception aligns Phase 7's loader, golden-run provenance, test version descriptions, and rollback sequence with the integrated release. |
| `docs/architecture/phase8-implementation-spec.md`, `docs/testing/test-strategy.md` | Record the Phase 8 design and its evidence, and map acceptance criteria to existing tests. |
| `docs/adr/ADR-001-grounding-separation.md`, `docs/adr/ADR-003-learner-record-synchronization.md` | Describe the isolated presentation boundary and add the dated synchronization revision. |
| `docs/security/authorization-matrix.md`, `docs/security/threat-model.md`, `docs/security/consent-schema.md`, `docs/security/consent-record.v1.schema.json`, `docs/security/identity-linking.md` | Regenerate the matrix and document the authorization, consent, retention, and linking contracts. |
| `infra/cloudrun/deployment.md`, `infra/cloudrun/observability.md`, `infra/cloudrun/retention-job.md` | Document the migration-head rollback order and append Phase 8 sections for operations, logging, and retention. |

## 8. Database

Revision `20261123_phase8_learner` follows `20261123_phase9_ranking` and adds the ten Phase 8 tables. The revision accepts ORM-created tables and adds missing epoch and activity columns to the early guard table. Startup initializes those columns for earlier rows without resetting an existing epoch. Downgrade verifies that all Phase 8 tables are empty before removing their schema. Further downgrades cross the separate Phase 9 `allow_ranking_drop` and Phase 7 `allow_ehmf_drop` guards. An image rollback leaves the schema and protection markers intact.

## 9. Routes and request-path behaviour

The existing routers serve replica issuance and synchronization under `/learner-record`, and claim, consent, export, and erasure under `/auth`. Claim requires a durable credential, a verified guest token, matching guest CSRF proof, and a trusted origin. Consent, export, and self-service erasure require a verified local session, signed guest credential, or Auth0 token. These routes refuse demo identities with 403. The shared authentication check also refuses demo aliases for account, guest, subject, or recognized federated IDs on ordinary learner routes and at Arena ticket redemption while any Phase 8 flag is active. Local erasure confirms the password and clears cookies after commit. Guest erasure revokes the credential. Federated erasure covers local application data. Each new endpoint refuses requests when its feature flag is off.

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

The proof's synthetic demo case exercises the erasure service directly. HTTP consent, export, and erasure require verified credentials. The erasure CLI returns 0 for success, 1 for drift, 3 for a failed proof, and 4 for a dirty-tree write.

The inherited reports regenerated for v8 are `docs/evaluation/phase3/three_plan_replay_v1.json`, `docs/evaluation/phase4/v1_fixture_report_v1.json`, `docs/evaluation/phase5/v2_fixture_report_v1.json`, and `docs/evaluation/phase6/v3_residual_report_v1.json`. The Phase 7 golden-set runner regenerates `docs/evaluation/phase7/golden_run_v1.json` and verifies the append-only package history. The ranking runner regenerates `docs/evaluation/phase9/ranking_replay_v1.json` under v8. Section 17 records their provenance and digests.

## 13. Tests

### 13.1 Acceptance map

| Criterion | Regression tests |
|---|---|
| AC-8-1 | `test_learner_record_merges_divergent_replicas_without_losing_completion`, `test_phase8_sync_parallel_replicas_conflict_and_retry_without_losing_updates`, `test_ac_8_1_concurrent_trusted_updates_preserve_each_mastery_value`. These cover same-skill maximum in both merge orders, concurrent client conflict and retry, and concurrent trusted mastery on separate skills. |
| AC-8-2 | `test_phase8_sync_duplicate_receipts_and_monotonic_clock`, `test_phase8_sync_rejects_other_subjects_and_server_operations` |
| AC-8-3 | `test_ac_8_3_three_mastery_levels_yield_identical_claim_set_cited_spans_and_decision` |
| AC-8-4 | `test_ac_8_4_no_evidential_or_verifier_module_imports_a_phase8_module`, `test_ac_8_4_evidential_prompts_and_the_abstention_configuration_hold_zero_learner_state_fields`, `test_ac_8_4_a_learner_value_in_an_evidential_payload_is_detected`, `test_ac_8_4_the_scan_covers_every_phase8_learner_state_field` |
| AC-8-5 | `test_ac_8_5_every_erasure_route_writes_a_verified_receipt`, `test_ac_8_5_erasure_rolls_back_when_a_surviving_row_fails_verification`, `test_plan_f_the_committed_erasure_proof_matches_a_fresh_run`, `test_phase8_export_and_erasure_cover_bound_subject_and_legacy_rows`, `test_phase8_claimed_guest_and_account_erasure_leave_no_keyed_rows`, `test_phase8_erasure_refuses_an_in_flight_subject_rebind`, `test_phase8_erasure_serializes_with_unguarded_and_first_writers`, `test_phase8_a_principal_erased_and_signing_in_again_gets_a_fresh_empty_record`, `test_phase8_erasure_serializes_with_unguarded_and_first_writers_http`, `test_phase8_a_stale_public_projection_cannot_recreate_an_erased_rows_handle`, `test_phase8_a_demo_header_cannot_read_or_change_another_principals_consent` |
| AC-8-6 | `test_a_client_sent_score_is_ignored`, `test_durable_mastery_follows_the_server_score`, `test_phase8_sync_rejects_other_subjects_and_server_operations`, `test_phase8_privacy_http_consent_export_erasure_and_assessment`, `test_phase8_a_demo_header_cannot_consume_another_learners_assessment_quota`, `test_phase8_quiz_previews_do_not_acquire_an_assessment_quota_or_record_lock` |
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

The baseline pins 135 Python and TypeScript modules from Phase 7 commit `512b8a6` and applies the Phase 9 changes from `d366e20` to yield 138 inherited modules. The table lists declarations changed by Phase 8 against that merged base. It also records the renamed checks. The protected Phase 3 and Phase 5 acceptance source remains covered by its separate digest guard.

| Module | Test or fixture | Exception | Change and preserved intent |
|---|---|---|---|
| `apps/frontend/tests/privacy-inventory.integration.test.ts` | `AC-8-7: the privacy page lists exactly the browser-storage keys the code uses` | AC-8-7 inventory coverage | Renamed and replaced `every browser-storage key the code uses is in the privacy page storage inventory, and nothing else`. The exact inventory comparison remains. |
| `apps/frontend/tests/privacy-inventory.integration.test.ts` | `AC-8-7: the privacy page lists exactly the cookies the code sets or reads` | AC-8-7 inventory coverage | Renamed and replaced `every cookie the code sets or reads is in the privacy page cookie inventory, and nothing else`. The exact inventory comparison remains. |
| `test_api.py` | `test_progress_endpoint_aggregates_activity` | Progress fixture in §0.1 | Pins privacy off for this fixture, preserving the existing analytics aggregation check. |
| `test_authorization.py` | `ALLOWED_KINDS` | Route authorization coverage in §0.1 | Adds the verified-principal access rule and runs the same denial checks for excluded demo roles. |
| `test_authorization.py` | `CALLER_READS` | Route authorization coverage in §0.1 | Keeps verified export in the existing cross-caller isolation test. |
| `test_authorization.py` | `MARKER_EXPECTED` | Route authorization coverage in §0.1 | Requires the learner's own export to contain its seeded marker, so the isolation check cannot pass vacuously. |
| `test_authorization.py` | `_actual_access` | Route authorization coverage in §0.1 | Recognizes the new privacy dependency so the route-policy match remains exact. |
| `test_authorization.py` | `_write_everything` | Route authorization coverage in §0.1 | Obtains an issued replica and analytics consent so the fixture stores the owner marker. |
| `test_authorization.py` | `test_a_refused_caller_is_refused` | Route authorization coverage in §0.1 | Enables the development claim route for the denied-principal case. |
| `test_authorization.py` | `test_there_are_negatives_for_every_restricted_access_level` | Route authorization coverage in §0.1 | Requires refusal cases for the verified-principal access level. |
| `test_config_package.py` | `V7_RAW` | Package bump exception in §0.1 | Pins the Phase 9 package as an explicit predecessor and structural-test control. |
| `test_config_package.py` | `_the_unedited_copies_load` | Package bump exception in §0.1 | Confirms every unmodified copy from v4 through v8 loads before testing its refusal cases. |
| `test_config_package.py` | `test_the_shipped_package_validates_and_matches_its_hash` | Package bump exception in §0.1 | Uses the independent v8 ceiling and verifies the v7 predecessor's canonical SHA-256 and inherited EHMF and ranking blocks. |
| `test_config_package.py` | `test_the_v5_edits_v6_changes_are_exactly_the_three_it_makes` | Package bump exception in §0.1 | Checks that the two v5 edits that do not apply above v6 remain inapplicable on both v7 and v8. |
| `test_config_package.py` | `test_the_v6_edits_v7_changes_are_exactly_the_ones_it_makes` | Package bump exception in §0.1 | Reads explicit v7 and preserves Phase 9's comparison against v6, including its V3 gold-label pin. |
| `test_config_package.py` | `test_v4_structural_errors_always_stop_the_load` | Package bump exception in §0.1 | Runs the v4 refusals on v4 through v8. On v5 it replaces the no-op schema assignment with the out-of-range value 9. |
| `test_config_package.py` | `test_v5_structural_errors_always_stop_the_load` | Package bump exception in §0.1 | Runs the v5 refusals on v5 through v8 and retains the exceptions for registry and severity changes. |
| `test_config_package.py` | `test_v6_stays_readable_for_one_release` | Package bump exception in §0.1 | Checks the v6 predecessor hash against explicit v7 and retains the v5, v6 and V3 schema pins. |
| `test_configuration_overrides.py` | `REFUSED_RELAXATIONS` | Readiness and override cases in §0.1 | Adds all five Phase 8 cases without dropping the inherited Phase 7 cases. |
| `test_configuration_overrides.py` | `write_package` | Bump-docstring exception in §0.1 | Names the actual shipped package while the helper still copies the package and its schemas. |
| `test_cs595_increment.py` | `test_learner_record_api_requires_a_durable_session_and_accepts_idempotent_operations` | Synchronization compatibility | Obtains the issued replica and sends the expected version. The durable-session and completion assertions remain. |
| `test_erasure_retention.py` | `_seed_everything` | Metadata-driven erasure coverage | Seeds assessment foreign keys from their parent rows, preserving coverage across all user-keyed tables. |
| `test_erasure_retention.py` | `test_account_deletion_uses_full_erasure` | Local account deletion compatibility | Runs the inherited exemption fixture with privacy off and still requires every non-exempt row to be gone. The verified privacy-on contract is covered under AC-8-5. |
| `test_erasure_retention.py` | `test_retention_removes_stale_guest_rows_in_every_table_and_keeps_the_rest` | Retention compatibility in §0.1 | Preserves stale, fresh and durable coverage and classifies intentionally retained credentials and bindings when privacy is on. |
| `test_malformed_input.py` | `_learner_record_write` | Synchronization compatibility | Acquires a replica only in the guarded mode, preserving the legacy malformed input path. |
| `test_malformed_input.py` | `test_a_learner_record_value_that_cannot_be_stored_is_refused_and_the_record_still_reads` | Synchronization compatibility | Exercises both modes while preserving rejection and the subsequent read. |
| `test_malformed_input.py` | `test_non_finite_preference_follows_the_flagged_backend_contract` | Synchronization compatibility | Renamed and replaced `test_a_non_finite_preference_is_refused_on_postgres_and_never_a_500`. Preserves PostgreSQL refusal and checks that neither mode returns 500. |
| `test_phase3_acceptance.py` | `test_plan_g_the_alembic_revision_is_reversible_and_refuses_to_drop_a_non_empty_ledger` | Migration-head exception in §0.1 | Steps through the Phase 8 head before testing the older downgrade and data-loss refusal. |
| `test_phase4_acceptance.py` | `test_phase4_docs_the_code_texts_name_the_shipped_package` | Package bump exception in §0.1 | Checks shipped v8 package and deployment text. Keeps the protected Phase 9 contracts at their inherited wording and verifies the v6, v7 and v8 tutor schema sets agree. |
| `test_phase4_acceptance.py` | `test_phase4_docs_the_phase3_spec_states_what_phase4_changed` | Package bump exception in §0.1 | Repoints the shipped path, loader ceiling and replay versions to v8 while retaining the inherited package sequence checks. |
| `test_phase6_acceptance.py` | `test_phase6_docs_the_phase_3_rollback_checks_the_stamp_against_the_current_head` | Migration-head exception in §0.1 | Checks the Phase 8 stamp, the absolute downgrade to Phase 9 and both earlier guarded downgrades. |
| `test_phase6_acceptance.py` | `test_plan_g_the_phase_6_revision_is_additive_reversible_and_keeps_its_rows` | Migration-head exception in §0.1 | Traverses the Phase 8, 9 and 7 successors before exercising the original Phase 6 data protection. |
| `test_phase7_acceptance.py` | `test_plan_e_the_phase_7_downgrade_refuses_while_ehmf_stops_holds_rows_and_the_table_refuses_truncate` | Migration-head exception in §0.1 | Downgrades the empty Phase 8 schema first, then exercises the same EHMF table, truncate and downgrade guards. |
| `test_phase7_acceptance.py` | `test_plan_e_the_phase_7_revision_is_additive_reversible_and_keeps_its_rows` | Migration-head exception in §0.1 | Verifies the Phase 7 revision's existing parent and guard under the Phase 8 head. |
| `test_phase9_acceptance.py` | `test_plan_e_the_phase_9_downgrade_refuses_while_ranking_events_holds_rows_and_the_tables_refuse_truncate` | Migration-head exception in §0.1 | Steps down the empty Phase 8 revision before verifying the ranking-data downgrade refusal and the TRUNCATE guards. |
| `test_phase9_acceptance.py` | `test_plan_e_the_phase_9_revision_is_additive_reversible_and_keeps_its_rows` | Migration-head exception in §0.1 | Checks Phase 9 schema and retained rows below the active Phase 8 head. |
| `test_ranking_units.py` | `test_the_ranking_schema_number_is_one_constant_and_no_schema_rule_compares_with_a_literal_number` | Package bump exception in §0.1 | Checks that the ranking floor stays at 7 and reads it from v7 while the shipped schema follows the separate v8 ceiling. |
| `test_response_ledger_migrations.py` | `PHASE8_REVISION` | Migration-head exception in §0.1 | Names the revision used by the inherited stamp and absolute-target cases. |
| `test_response_ledger_migrations.py` | `PHASE8_TABLES` | Migration-head exception in §0.1 | Tracks the ten tables added by the revision for the upgrade and rollback checks. |
| `test_response_ledger_migrations.py` | `test_e10_the_absolute_downgrade_target_is_safe_in_every_stamp_state_the_runbook_allows` | Migration-head exception in §0.1 | Stamps the Phase 8 head, steps through the empty successor, and retains the absolute-target and ledger refusal checks. |
| `test_response_ledger_migrations.py` | `test_f14_the_forward_alembic_step_runs_only_on_a_phase2_stamp` | Migration-head exception in §0.1 | Walks the ordered Phase 3, 5, 6, 7, 9 and 8 upgrades and preserves the Phase 2 stamp and invalid-replay checks. |
| `test_structured_logging.py` | `test_erasure_time_covers_the_erase_and_its_commit_but_not_the_password_check` | Local account deletion compatibility | Pins privacy off for the existing fake clock and still measures the deletion and commit outside password confirmation. |

### 13.4 Phase 8 regression revisions

The quota helper test names the case where principal and subject match. The one-shot claim test names the guest CSRF check and successful retry refusal. The readiness regression exercises the in-process planner-stop observation. The production freeze regression checks all four flags off, byte-identical replies, legacy operation clocks, and zero Phase 8 writes. The migration test upgrades an ORM-created schema with a two-column early guard and existing learner rows. The authenticated HTTP race tests verify that in-flight notes and tutor turns finish before either erasure receipt, or are refused after the erasure epoch changes.

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
| PD-203 | D-05 feature freeze | Phase 8 L L1606: "Flags for planner and sync. Stop: any harness violation blocks adaptation (never evidence)." | Keep all Phase 8 switches off outside development and refuse non-off values before the verified Phase 8 exit. Development defaults are sync on, planner shadow, identity off, and privacy on. Outside development, privacy on and planner shadow also require D-27 ratification. Refuse planner on pending DI-312. | `phase8_settings.py`. |
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
| DI-317 | Remove v7 and its Phase 8 readability check after one release. Blocked by: a production release after the Phase 8 merge, under D-05. The append-only golden-set history retains the v7 entry. | Engineering | Deferred |
| DI-318 | Dedicated counters at runtime evidential contract refusals and `ToolNotVisible` in `tutor_pipeline/contracts.py` and `gateway/tools.py`. Round 1 stopped these changes under rule 12 and the shared-file rule in §0.1. The owner answered the round-2 question by assigning both reserved changes to the main track. The Phase 8 harness and sync signals operate independently. | Engineering (main track) | Handed over |
| DI-319 | Wire the runtime stop-the-line trigger for learner state in an evidential prompt (plan 13.6). Blocked on the shared-file boundary in §0.1 for `tutor_pipeline/contracts.py` and `gateway/tools.py` until the Phase 8 merge. The owner accepted the main-track assignment. CI still fails on harness violations and an explicit operator run sets the shared planner stop. | Engineering (main track) | Handed over |

Plan M: "[Risk R-01][Risk R-08][Risk R-41][Risk R-42][Risk R-51]; residual: backups keep erased rows for a window."

## 17. Verification, work order and exit

### 17.1 Reproduction and current verification

Run Python checks from the repository root, using isolated scratch databases for pytest. Run `python -m pytest -q -m "not release_artifacts" apps/api/tests evaluation/tests` for SQLite and `python -m pytest -q -rxX -m "not release_artifacts" apps/api/tests` once with each PostgreSQL driver. Run the protected-template cases in the last list by ID with `--tb=no -rN -q`. Exclude exactly those IDs from the first run of each leg and include their results in the combined count.

```text
python scripts/config_package.py --check
python scripts/config_package.py --check --path apps/api/app/config_package/v8.json
python scripts/replay_tutor_plans.py --check docs/evaluation/phase3/three_plan_replay_v1.json
python scripts/run_v1_fixtures.py --check docs/evaluation/phase4/v1_fixture_report_v1.json
python scripts/run_v2_fixtures.py --check docs/evaluation/phase5/v2_fixture_report_v1.json
python scripts/run_v3_residual_report.py --check docs/evaluation/phase6/v3_residual_report_v1.json
python scripts/run_golden_set.py --check docs/evaluation/phase7/golden_run_v1.json --base-ref origin/main
python scripts/run_invariance_harness.py --check docs/evaluation/phase8/invariance_harness_report_v1.json
python scripts/prove_erasure.py --check docs/evaluation/phase8/erasure_proof_v1.json
python scripts/run_ranking_replay.py --check docs/evaluation/phase9/ranking_replay_v1.json
```

Repeat the package check for each version from v1 through v7. Run the corpus and question validators, authorization matrix, manifest, abstention calibration, frozen public payload check, source-fidelity check, and repository and Docker-context path scan. Run `npm run lint`, `npm run typecheck`, and `npm run test:integration` in `apps/frontend`.

The reports were generated under package v8 from clean source commit `53abc42d8500263ff0d22ee6a1b0b5df360788ce`. The invariance harness covered 299 public items at three mastery levels, with 148 items showing distinct presentation, zero invariance violations, and zero learner-state fields in the evidential-path scan. The EHMF run resolved all 47 delivered citations across 40 golden-set items. The ranking replay produced byte-identical results on two runs of all seven synthetic scenarios. The erasure proof independently checked six principal and binding cases. These fixtures satisfy the engineering prerequisite in plan 15.2.

| Record | Inputs SHA-256 (record `inputs.sha256`) |
|---|---|
| `docs/evaluation/phase3/three_plan_replay_v1.json` | `c4d5ca207424071354f99d3d997d82d5b0a703f6d50c00fb4c41e2883f1776a0` |
| `docs/evaluation/phase4/v1_fixture_report_v1.json` | `58d0648172ee65243cb23187f8637023fb9eb3a8c7916cd39b8cb01f3d1e9b69` |
| `docs/evaluation/phase5/v2_fixture_report_v1.json` | `0d4a93dfb96f802a2f9533ef5de327d68ca5c71e3e28af7e6fbcd135a2388acd` |
| `docs/evaluation/phase6/v3_residual_report_v1.json` | `717a8563c87abdafa29038fa83a6a3b6684cce7f4f0cc722db86b28c13253427` |
| `docs/evaluation/phase7/golden_run_v1.json` | `c167dd8f33913ae7a43c133dd3992421a6543e7ed53adc3813ae5863e2c3c15d` |
| `docs/evaluation/phase8/invariance_harness_report_v1.json` | `32c649edd7de52e954f67eb8699dcae287a8ce2d5de172e03ea23ecceda73a72` |
| `docs/evaluation/phase9/ranking_replay_v1.json` | `f73f7e836c278d5a3d717186cab6b922d0b95cc55ee0fb14f9cd69a58621bc5a` |

`docs/evaluation/phase8/erasure_proof_v1.json` has record file SHA-256 `551caa3b40c7944b73ac355400947a54886f7d06d718a4b689c3ac4e5cf24204`. The proof has no inputs block.

<!-- Verified test totals -->

### 17.2 Review response checks and exit

Each review response records one status, the fixing commit and test names, and the mutation result for each upheld finding. It gives the merged base, package hash, Alembic ancestry, evidence digests, and reconciled totals. The response check requires these exact field labels.

- Rules that no longer fit
- Dated revision sections appended
- Proposed package pins
- Stopped items

Plan P requires "AC-8-1 to AC-8-7 green; harness in CI." The Phase 8 exit remains held by DI-300, and `phase8_exit_passed` remains false.

## 18. Review history

The rows record the build and each review round in order. Sections 0–17 describe the current implementation. Each review row summarizes the changes and names representative regression tests.

| Round | Commit | Findings fixed (one line each, with their tests) |
|---|---|---|
| Spec (pre-code) | - | Initial design and verification map. |
| Build | `cb142b1` | Settings, synchronization, identity, privacy lifecycle, shadow planner, and engineering evidence. Regression guards include `test_settings_phase8_defaults_and_refusals`, `test_ac_8_1_concurrent_trusted_updates_preserve_each_mastery_value`, `test_phase8_claim_requires_guest_csrf_and_is_one_shot`, `test_plan_f_the_committed_erasure_proof_matches_a_fresh_run`, and `test_plan_p_the_committed_invariance_report_matches_a_fresh_run`. |
| Review 1 | `8c7b7d4` | Route ownership and PD register guards, serialized cutover and erasure, claim and privacy HTTP coverage, active replica lifecycle, measurable invariance, retention, and spec controls. See `test_phase8_route_policies_form_one_block_after_the_learner_record_rows`, `test_phase8_docs_pd_204_states_the_engineering_constants_in_code`, `test_phase8_erasure_refuses_an_in_flight_subject_rebind`, `test_phase8_privacy_http_consent_export_erasure_and_assessment`, and `test_ac_8_4_a_learner_value_in_an_evidential_payload_is_detected`. |
| Review 2 | `cb2a33e`, merge `bf4fe3a`, integration `ef99f9d` | Restored the retention and readiness contracts and verified erasure serialization, retained-principal recovery, expiry, F-3 and trusted mastery. The owner assigned DI-318 to the main track. Phase 7 main `512b8a6` entered through `bf4fe3a`. Package v7 SHA-256 is `adf3aed271aaf2c84c852f2e0169825b9889577d4aa64573ea7066f12c97d1e5`. Alembic `down_revision` is `20261123_phase7_ehmf`. The full rerun on `598ad9d` passed 2,105 on SQLite (+158 from the 1,947 main baseline) and 2,103 on each PostgreSQL driver, including 11 separately run template tests per backend. The SQLite leg included API and evaluation tests. The PostgreSQL legs ran the API tests. Regression guards include `test_phase8_erase_stale_guest_rows_keeps_its_two_argument_signature`, `test_phase8_keeps_protected_acceptance_tests_at_the_phase7_baseline`, `test_phase8_erasure_serializes_with_unguarded_and_first_writers`, `test_phase8_a_principal_erased_and_signing_in_again_gets_a_fresh_empty_record`, `test_phase8_loader_refuses_schema_versions_outside_the_latest_bound`, and `test_phase8_migration_retains_existing_tables_and_refuses_data_loss`. |
| Review 3 | `c466957` | Verified receipts for both erasure routes, checked the privacy freeze and authenticated export and erasure, enforced D-27 and retention policy, and reconciled the shared-file and test records. DI-319 records the hand-over for the runtime stop trigger. See `test_ac_8_5_every_erasure_route_writes_a_verified_receipt`, `test_phase8_a_demo_header_cannot_export_or_erase_another_principal`, `test_freeze_phase8_privacy_requires_d27_even_after_exit`, and `test_phase8_docs_names_the_shared_files_and_changes_to_existing_tests`. |
| Review 4 | `53abc42`, merge `832a431` | Integrated Phase 9 main `d366e20`. Package v8 SHA-256 is `c14d28f110f0ddcf89aab4717ccd5e6555cba15ad6a266468b67b662229d1904`. Alembic `20261123_phase8_learner` follows `20261123_phase9_ranking`. Covered the all-off freeze, derived evidence scan, authenticated write and erasure ordering, early-table upgrade, verified consent, guest/demo scoring, inherited test traceability, verification provenance, D-27 settings, and release instructions. See `test_freeze_phase8_flags_off_learner_record_and_quiz_routes_are_unchanged`, `test_ac_8_4_the_scan_covers_every_phase8_learner_state_field`, `test_phase8_erasure_serializes_with_unguarded_and_first_writers_http`, and `test_phase8_docs_section_17_states_only_the_current_verification`. <!-- Round 4 reconciled totals --> |
