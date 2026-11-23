# QC+AI Studio: Phase 8 implementation spec

Learner adaptation and privacy-preserving record, upgrade plan lines 1557-1614. The branch was cut at `98f7cc4` and its current integration base is `31343c8`.

Sections 0-17 describe the behaviour the code has and identify deferred integration work. Section 18 holds one history-table row per review round. This file is LF in every checkout (`.gitattributes`).

## 0. Ground rules, measured facts, readings

Apply the branch rules and the Phase 8 handoff's shared-file restrictions. Keep smoke and acceptance fixtures synthetic and run verification offline. The verified Phase 6 integration base is `31343c86c23007cec227b38413e0e53140f714a5` (PR #38, main CI run 45180967316, reported green by the owner). The branch ships package v6 and Alembic head `20261123_phase8_learner`. Phase 6 added package v5, migration `20261122_phase6_v3_audit`, and the user-keyed `v3_claims` and `v3_flags` tables. Their erasure and retention scope is explicit.

Phase 5 added `gateway_budget_days`, `gateway_stops`, and `evidential_cache_entries` to the shared ORM and updated the migration chain. The retrieval engine delegates embedding egress to `app/gateway/embeddings.py`. Its import guard allows only the Pinecone index SDK exception in the retrieval engine. The handoff's Phase 5 snapshot of untouched database files and its earlier embedding exception no longer describe the integrated code. Phase 8 uses the existing shared-file ownership limits and treats the added gateway tables and embedding implementation as Phase 5-owned.

The learner-record baseline uses the get-or-create path for reads, rejects changed-payload receipt replays, and advances `record_version` independently of an expected version. The retention worker uses the existing retention service. The acceptance readings are in section 13.

### 0.1 Shared file ownership

Phase 8 keeps route policies in one block after the existing learner-record entries. New browser transport lives in its own module. The shared API client changes only its existing learner-record operations function. The orchestrator handles observation in the shadow branch. The gateway, V1/V2/V3, evidential pipeline, frozen payload record, pinned schemas and secrets stay within their existing ownership. The package bump and reversible migration use the narrowly scoped integration exceptions in handoff §8.1. Production enablement requires the owner decisions and DI-300 evidence.

## 1. Conflicts between plan text and fixed decisions

- **H13 and D-27.** Plan L1566 requires a consent model, and L1907 says "a hold stops the named work until its release evidence is filed". The owner authorized isolated engineering under P1-D-18, with the main-track record P2-12-D-04. H13 remains held. DI-300 and DI-301 keep the Phase 1 and 3 prerequisites and the consent decision visible.
- **Baseline and ownership.** The baseline already scores quizzes on the server and runs scheduled retention. The designated learner tables use the bound subject, including assessment facts and issued replicas. Notes, threads, quiz attempts, credentials, and other legacy activity keep the authenticated principal, including the federated subject value where applicable. Export and erasure traverse both keys. Existing bindings remain authoritative through flag rollback. First bind preserves a lone record's version. Identity defaults off in development to preserve the baseline demo and authentication contracts.
- **Revocation and finality.** `guest_sessions.py` uses a domain-separated SHA-256 tombstone in `learner_guest_revocations` so recognition survives signing-key rotation. Guest erasure removes the corresponding raw legacy revocation. `learner_record_lock.py` persists digest-only write guards and refuses an erased key after a waiting transaction acquires its lock. Identifiers of self-erased or claimed guests stay revoked through rollback.
- **Assessment and R-03.** Stage-9 ratings and flags are operational signals. Only server assessment facts feed planner mastery, and the quota counts attempts by authenticated principal and lesson. Sequential quiz attempt IDs remain opaque response metadata for a caller's own activity and are not accepted on an ID-addressed cross-learner endpoint.
- **Consent and retention.** Plan L938 ties `consent_version` to analytics admission and `retention_class` to automatic cleanup. Durable rows stay until erasure unless a specific expiry applies. PD-200 controls provisional grants. P2-12-D-05 records the owner's decision to keep the 540-day rule for independently submitted support requests, even when the address matches a deleted account. DI-316 is closed. A-17 and Q-19 remain unresolved.
- **Method and test layout.** The harness feeds plan IDs from the pure planner using synthetic mastery values and the existing presentation request seam. It uses public two-pass engineering fixtures. Research designs remain governed by D-08 and DI-312 covers live presentation wiring. The document guard compares section 3's table with the ORM's columns, and the acceptance map resolves tests across feature-specific modules.
- **Shadow timing.** The planner issues set-based reads within a savepoint. PostgreSQL bounds each statement and restores the prior budget. Work exceeding 150 ms is recorded as degraded and the existing shadow job proceeds. The elapsed budget also detects slow local work after it returns.

## 2. Architecture

Separate credential verification from subject resolution. An account and a valid guest session may be linked through a one-shot claim with both credentials proved and an auditable outcome. Keep the trusted assessment writer and add a separate client synchronization boundary. Use a deterministic planner over server-held state. Only the pedagogical pass may consume the planner output. Until DI-312 is resolved, evaluate choices in shadow and exercise them in the public-fixture harness through the existing presentation request interface.

## 3. Data shapes

The subject mapping binds a provider principal to a random subject identifier. The synchronization command includes an issued replica, operation identifiers and clocks, and an expected record version. Its result contains operation receipts and the resulting version. Consent records and change history carry version, class, state, time, and source. The planner returns a plan ID, ordered lesson IDs, and a planner version. Erasure receipts carry a random ID, timestamp, consent version, table coverage and zero counts, configuration digest, and scope statements.

The first build adds the following shapes:

| Model | Fields |
|---|---|
| `LearnerIssuedReplica` | `replica_id` (random server-issued string, primary key), `user_id` (indexed erasure key), `created_at`, `last_used_at`, `retired`. |
| `LearnerWriteGuard` | `key_digest` (primary key), `erased`. |
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

- Bind replicas to the subject. Resolve existing receipts before rejecting a stale clock, so a repeated request can recover a prior outcome. Validate new operations' replica ownership, monotonicity, and causal-vector scope. Serialize the version check and record, receipt, and clock updates in one transaction. Resolve first-insert races with a bounded retry or conflict response.
- Preserve server-scored mastery and merge semantics. Choose assessment-operation counters under the same transaction as the attempt. Refuse client mastery operations and server-owned operation and replica identifiers.
- Select lesson order and style from server mastery, completion, and attempt state. Use static course order when the planner is unavailable or adaptation consent is absent.
- Erase through metadata-derived, child-first table coverage. Resolve the guest revocation representation against rotation and legacy-upgrade tests before wiring identity. Persist the canonical receipt digest and coverage summary in the durable audit path. A receipt describes local data scope and the information available about processors and backups.

In `learner_record_sync.py`, a conflict-tolerant insert creates the record when needed. A version-preserving row update acquires the transaction's write lock, then the service checks the expected version and reads the subject's issued replicas. All new operations have strictly increasing clocks and known causal counters. Identical operations in the same batch generate one applied receipt followed by duplicate receipts. A replay containing only known operations can recover its receipts after the record advances. The read-only entry point returns a version-zero record for a missing subject without issuing an insert.

The planner maps the mean finite course-local server mastery below 0.4 to stepwise, from 0.4 through values below 0.75 to concise, and from 0.75 to socratic. It keeps unfinished lessons in course order and applies PD-204 to the review order. With adaptation disabled or no valid course mastery, it returns the configured default plan and static order. Any eventual caller must source mastery from trusted assessment evidence.

With synchronization enabled, acquire the record lock before inserting the attempt. Count the subject's attempts on that lesson over the preceding 15 minutes and refuse the thirteenth. For a durable writer, allocate assessment clocks from the locked server replica and keep the attempt, learner record, and assessment fact in the same transaction. Preview identities record the attempt and take the quota lock without writing mastery. The synchronization-off path retains its baseline behavior. The planner reads mastery from the dedicated assessment-fact table. Legacy materialized mastery and operation identifiers alone are insufficient evidence of provenance.

The one-shot guest claim retains the account's unique profile, public handle, and duplicate receipt records. It joins convergent learner state before transferring remaining study rows. The guest's consent does not transfer. Transactional claim audit and the stable revocation digest support retry and credential-key rotation without retaining a raw guest credential in the tombstone.

The consent service stores a current row and erasable change history. Analytics grant is checked before writing when privacy is enabled. Scoped NDJSON export omits credential data and counterpart identity fields. Erasure locks both identifiers, deletes their local rows and dependencies, verifies zero counts, and appends the receipt digest in the same transaction. The receipt reports the active package and its registry. Backup, support, historical processing, and external identity-provider scope stay explicit.

## 5. Configuration package

Package v6 (6.0.0) supersedes v5 (5.0.0, SHA-256 `ed91a98f8f3cca200e2164381da966ce9ec8f8a2de2120d2c2fc6fd77e9b2e68`). It adds the provisional learner settings, `phase8_exit_passed: false`, and the D-26 and D-27 entries. V5's D-08 and all prior decision entries are preserved. The evidence, gateway, and V3 contract pins carry forward. DI-317 identifies the v5 readability step. Phase 7 must renumber if Phase 8 merges first, and Phase 8 must renumber if Phase 7 takes v6 on main first.

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

## 8. Database

Revision `20261123_phase8_learner` follows `20261122_phase6_v3_audit` and adds the ten Phase 8 tables. Upgrade accepts tables already built from matching ORM metadata. Downgrade verifies that Phase 8 tables are empty before removing the schema. An image rollback leaves the database and protection markers intact. Verify fresh and existing-row paths on SQLite and both PostgreSQL drivers.

## 9. Routes and request-path behaviour

The existing routers serve replica issuance and synchronization under `/learner-record`, and claim, consent, export, and erasure under `/auth`. Claim requires a durable credential, a verified guest token, matching guest CSRF proof, and a trusted origin. The other privacy operations are caller-scoped. Local erasure confirms the password and clears cookies after commit. Guest erasure revokes the credential. Federated erasure covers local application data. Each new endpoint refuses requests when its feature flag is off.

Replica issuance returns 201. Record reads and applied or duplicate writes return 200. A version conflict returns 409 with `reason: cas_conflict` and the current `record_version`. Invalid inputs, untrusted mastery, reserved operations and nonfinite JSON return 422. Invalid replica ownership, retirement, clocks and changed replays return 409. New routes return 404 with their flags off. Claim proof failures return 403, unavailable guests return 409, and success returns 200. Consent returns 200 or 409 for an unavailable grant. Export returns 200 with no-store NDJSON. Erasure returns 200 with a receipt or 401 for refused password confirmation. Assessment quota refusal returns 429 with Retry-After 900.

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
| `learner.erasure` | Digest-only security event with refusal status or deleted row total. |
| `subject.claimed`, `subject.claim_refused` | Claim outcome and transferred-row total on success. |

Readiness appends `phase8_exit_passed`, each learner setting and effective value, and development-only `learner_slis`. The only new readiness query reads the shared adaptation stop when the planner is enabled. The operator keys are `learner_sync_on`, `learner_identity_on`, `learner_privacy_on`, `learner_planner_shadow`, and `learner_planner_on`. Runtime evidence and tool handling stays within the existing gateway and verifier boundaries. DI-318 tracks dedicated runtime refusal counters. Production F-3 and cloud metrics remain deferred under DI-300 and DI-305.

## 11. Frontend

The dormant synchronization helper obtains a replica from the server, advances its local clock from the observed server clock, and sends the expected record version. On a failed request it re-reads the record and retries once when the version advanced, preserving the batch's operation IDs. It uses the existing two storage keys. Production consent UI and learner-facing privacy-copy changes are tracked separately.

## 12. Fixtures and records

The erasure proof seeds user-keyed and dependent rows for local, guest, federated, demo, bound local, and claimed local synthetic cases. It queries survivors independently of the receipt and checks the control rows and persisted digest. The invariance tool runs three mastery levels and fresh evidential caches with the shadow gateway. It records actual rendered variation and compares resolved question, retrieval, thresholds, envelopes, non-alignment verifier payloads, evidence, claim plans, locked and delivered claims, citations, and final outcomes. Alignment keeps the pinned V1 readability constants. The CLI accepts a JSON selection of the approved public fixtures and the two-pass design. E3 and LQ-1 require separate research evidence.

## 13. Tests

| Criterion | Required coverage |
|---|---|
| AC-8-1 | Two concurrent replicas, conflict retry, and first-insert races preserve the expected mastery join. |
| AC-8-2 | Reject stale or equal counters on new operations and reject foreign replicas. Preserve receipt replay and trusted counter ordering. |
| AC-8-3 | Compare three mastery levels with different presentation choices and invariant delivered claims, citations, and answer decision. |
| AC-8-4 | Scan evidential templates, captured payloads, and configuration. Guard learner-module imports. The versioned learner-tool integration belongs to DI-312. |
| AC-8-5 | Verify each subject-keyed table and receipt digest while preserving the control subject's rows. |
| AC-8-6 | `test_a_client_sent_score_is_ignored` and `test_durable_mastery_follows_the_server_score` verify server scoring. `test_phase8_sync_rejects_other_subjects_and_server_operations` verifies rejection of client mastery. |
| AC-8-7 | Compare disclosed cookies and storage keys with implementation in both frontend inventory and API acceptance coverage. |

Add authorization, retention, export, failover, stop persistence, migration, and freeze checks as each feature lands. Record the actual test names and regression checks with the build.

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

| Test | Change and preserved intent |
|---|---|
| `test_progress_endpoint_aggregates_activity` | Keeps the baseline aggregation path by pinning the privacy gate off in this one fixture. |
| `test_a_refused_caller_is_refused` | Activates the development claim route before checking a denied principal. |
| `test_no_caller_scoped_read_returns_another_learners_data` | Grants analytics and uses issued replicas so the owner marker reaches both storage and the scoped export. |
| `test_learner_record_api_requires_a_durable_session_and_accepts_idempotent_operations` | Acquires an issued replica and sets the expected version in the test request. |
| `test_retention_removes_stale_guest_rows_in_every_table_and_keeps_the_rest` | Preserves the stale-guest test while asserting dedicated account, session, and binding rules. |
| `test_a_learner_record_value_that_cannot_be_stored_is_refused_and_the_record_still_reads` | Exercises the finite server-side validation in both modes. |
| `test_non_finite_preference_follows_the_flagged_backend_contract` | Pins both legacy database-specific behavior and uniform sync-on validation. |

## 14. CI changes

The API and evaluation job checks v5 readability and the committed invariance report. Its existing pytest step verifies the erasure proof. PostgreSQL jobs verify the API suite with both drivers. The existing public-payload golden record remains the freeze boundary.

## 15. Docs and evidence

Subject linking and consent have security documentation, with a generated consent record schema. ADR-001 records the evidential and pedagogical boundary. ADR-003 has the dated Phase 8 synchronization revision, and the threat model names the D-26 controls. The authorization matrix, acceptance map, and retention runbook cover the new interfaces. Evidence records are generated from a clean build. The proposal to pin the consent schema remains for main-track review.

## 16. Provisional defaults and deferred items

### 16.1 Provisional defaults

The following defaults are provisional. Implementation locations in this section refer to the code or artifact responsible for enforcing each default when it lands.

| # | Decision | Plan text | Default applied | Where |
|---|---|---|---|---|
| PD-200 | D-27, consent classes and H13 (Product Owner and Principal Investigator) | 18.4 L3017: "D-27 OPEN DECISION: consent classes before Phase 8 [Risk R-09]. PO, PI." 9.4 L1924: "H13 \| Consent [Decision D-27] \| P8 start \| Consent classes". | H13 remains held. Version `d27-unresolved-v1` classifies existing processing as unclassified and permits synthetic development grants for adaptation and analytics. Outside development those grants are refused, the planner uses the static order, and the analytics gate is off. Research is refused everywhere. The default establishes no legal basis or toggle-free status. | `learner_record_privacy.py`, `consent-schema.md`, `phase8_settings.py`. |
| PD-201 | D-26 compare-and-set (Security Lead) | Phase 8 D L1573: "2) Server-issued replica clocks, monotonic counters, compare-and-set on record_version [Decision D-26]." | Check the expected version and serialize writes to the learner record. An out-of-date client re-reads and retries. Identical receipts remain idempotent. | `learner_record_sync.py` and the trusted assessment write path. |
| PD-202 | D-08 research timing and D-14 research data plane (Principal Investigator) | 18.3 L2987: "(a) before research use; (b) fixtures" and L2988: "first". | Apply D-08 option (a). Refuse research grants and research export everywhere. Use synthetic learners and the public fixture for engineering evidence. D-14 remains with DI-09. | `learner_record_privacy.py`, `run_invariance_harness.py`. |
| PD-203 | D-05 feature freeze | Phase 8 L L1606: "Flags for planner and sync. Stop: any harness violation blocks adaptation (never evidence)." | Keep all Phase 8 switches off outside development and refuse non-off values before the verified Phase 8 exit. Development defaults are sync on, planner shadow, identity off, and privacy on. Refuse planner on pending DI-312. | `phase8_settings.py`. |
| PD-204 | Engineering parameters (Engineering) | Phase 8 D L1574: "3) Mastery from server-scored assessments [Risk R-42]; planner (Loop 2) [E-74]." Phase 8 D L1577: "5) Consent record, scheduled retention, export, erasure across all providers with receipt [Risk R-08]." | Cap active replicas at 16 per subject. Confirm a preferred active replica, including one without an applied operation, or retire least-recently-used replicas to make room while preserving their clock and receipt history. Allow 12 attempts per principal and lesson per 15 minutes, then return 429 with Retry-After 900. CAS returns 409 with the current version and no server retry. The browser re-reads and retries once if the same principal's version advanced. The planner uses per-lesson maximum assessed mastery, completion at 0.7, a 150 ms shadow budget, bands at 0.4 and 0.75, and harness levels 0.1, 0.5, and 0.9. Preserve unfinished course order. Order completed review by ascending mastery, descending attempt count, then course order. Export streams NDJSON with credential tables withheld. The receipt contains a random ID, UTC time, consent version, zero counts, table-set SHA-256, package version and SHA-256, gateway registry, and scope. The audit holds the canonical receipt digest, table-set digest, and deleted count. | `learner_record_sync.py`, `learner-record-sync.ts`, `learner_record_planner.py`, `learner_record_shadow.py`, `learner_record_privacy.py`, `run_invariance_harness.py`. |
| PD-205 | Retention classes (Engineering and Data Steward) | Phase 8 D L1577: "5) Consent record, scheduled retention, export, erasure across all providers with receipt [Risk R-08]." | Reuse the existing retention constants and provider-independent account and session rules. Keep the response ledger outside the expiry schedule pending PLAN-12.8. | `retention.py`, `consent-schema.md`, the scheduled retention worker. |

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
| DI-318 | Dedicated counters at runtime evidential contract refusals and `ToolNotVisible` in `tutor_pipeline/contracts.py` and `gateway/tools.py`. The isolated harness and sync signals are implemented. Stopped under rule 12 and §8.1, which reserve these shared paths. | Engineering (main track) | Stopped |

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

## 18. Review history

The rows below record what each round fixed, in order. They may describe behaviour that a later round superseded. Sections 0-17 are authoritative after implementation. Each finding is one line naming the tests that fail if its defect comes back.

| Round | Commit | Findings fixed (one line each, with their tests) |
|---|---|---|
| Spec (pre-code) | - | Initial design and verification map. |
| Build | `cb142b1` | Settings, synchronization, identity, privacy lifecycle, shadow planner, and engineering evidence. Regression guards include `test_settings_phase8_defaults_and_refusals`, `test_ac_8_1_concurrent_trusted_updates_preserve_each_mastery_value`, `test_plan_j_a_forged_or_revoked_guest_token_cannot_claim`, `test_plan_f_the_committed_erasure_proof_matches_a_fresh_run`, and `test_plan_p_the_committed_invariance_report_matches_a_fresh_run`. |
| Review 1 | `8c7b7d4` | Route ownership and PD register guards, serialized cutover and erasure, claim and privacy HTTP coverage, active replica lifecycle, measurable invariance, retention, and spec controls. See `test_phase8_route_policies_form_one_block_after_the_learner_record_rows`, `test_phase8_docs_pd_204_states_the_engineering_constants_in_code`, `test_phase8_erasure_refuses_an_in_flight_subject_rebind`, `test_phase8_privacy_http_consent_export_erasure_and_assessment`, and `test_ac_8_4_a_learner_value_in_an_evidential_payload_is_detected`. |
