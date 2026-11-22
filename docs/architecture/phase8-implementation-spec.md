# QC+AI Studio: Phase 8 implementation spec

Learner adaptation and privacy-preserving record, upgrade plan lines 1557-1614. The branch was cut at `98f7cc4` and its current integration base is `c34a8c1`.

Sections 0-17 describe the behaviour the code has once implemented. During the pre-code stage they specify the proposed behavior and identify pending checks. Section 18 holds one history-table row per review round. This file is LF in every checkout (`.gitattributes`).

## 0. Ground rules, measured facts, readings

Apply the branch rules and the Phase 8 handoff's shared-file restrictions. Keep smoke and acceptance fixtures synthetic and run verification offline. The verified Phase 5 integration base is `c34a8c1033e86072b8c0129440e42afea64285ee` (PR #37, main CI run 45044415408, reported green by the owner). The shipped package is v4. The current Alembic head is `20261122_phase5_gateway_controls`.

Phase 5 added `gateway_budget_days`, `gateway_stops`, and `evidential_cache_entries` to the shared ORM and updated the migration chain. The retrieval engine delegates embedding egress to `app/gateway/embeddings.py`. Its import guard allows only the Pinecone index SDK exception in the retrieval engine. The handoff's Phase 5 snapshot of untouched database files and its earlier embedding exception no longer describe the integrated code. Phase 8 uses the existing shared-file ownership limits and treats the added gateway tables and embedding implementation as Phase 5-owned.

The learner-record baseline uses the get-or-create path for reads, rejects changed-payload receipt replays, and advances `record_version` independently of an expected version. The retention worker uses the existing retention service. The acceptance readings are in section 13.

## 1. Conflicts between plan text and fixed decisions

The plan identifies D-27's consent model and the Phase 1 and Phase 3 exits as prerequisites. The handoff defines an isolated engineering track while H13 remains held and assigns the record of the deviation to the main track. DI-300 records the unmet exit conditions. The baseline already scores quiz attempts on the server. Phase 8 protects the separate synchronization endpoint against client-authored mastery. Scheduled retention exists and needs lifecycle coverage for the new subject-keyed data. The production schema is unresolved under A-17 and Q-19. DI-312 assigns the versioned planner-to-renderer integration to the main track.

## 2. Architecture

Separate credential verification from subject resolution. An account and a valid guest session may be linked through a one-shot claim with both credentials proved and an auditable outcome. Keep the trusted assessment writer and add a separate client synchronization boundary. Use a deterministic planner over server-held state. Only the pedagogical pass may consume the planner output. Until DI-312 is resolved, evaluate choices in shadow and exercise them in the public-fixture harness through the existing presentation request interface.

## 3. Data shapes

The subject mapping binds a provider principal to a random subject identifier. The synchronization command includes an issued replica, operation identifiers and clocks, and an expected record version. Its result contains operation receipts and the resulting version. Consent records and change history carry version, class, state, time, and source. The planner returns a plan ID, ordered lesson IDs, and a planner version. Erasure receipts carry a random ID, timestamp, consent version, table coverage and zero counts, configuration digest, and scope statements.

The first build adds the following shapes:

| Model | Fields |
|---|---|
| `LearnerIssuedReplica` | `replica_id` (random server-issued string, primary key), `user_id` (indexed erasure key), `created_at` (database timestamp). |
| `LearnerPresentation` | `plan_id` (`concise`, `stepwise`, or `socratic`), `lesson_order` (ordered tuple of lesson identifiers), `planner_version` (`learner-planner-v1`). |
| `LearnerSubject` | `principal_digest` (provider-scoped primary key), `user_id` (random erasure key), `provider`, `created_at`. |
| `LearnerGuestRevocation` | `credential_digest` (primary key), `revoked_at`. |
| `LearnerClaimAudit` | `id`, `subject_digest`, `guest_digest`, `transferred` table counts, `created_at`. |
| `LearnerConsent` | `user_id` and `consent_class` (composite primary key), `consent_version`, `granted`, `updated_at`, `source`. |
| `LearnerConsentChange` | `id`, `user_id`, `consent_class`, `consent_version`, `granted`, `created_at`, `source`. |
| `LearnerErasureAudit` | `id`, `receipt_digest`, `table_set_digest`, `deleted_total`, `created_at`. |
| `LearnerAdaptationStop` | `control_id` (`planner`), `reason`, `stopped_at`. |
| `LearnerAssessmentFact` | `attempt_id` (primary key), `user_id`, `lesson_slug`, `mastery`, `created_at`. |

The client operations service accepts a subject, expected version, and existing operation input models. With synchronization enabled, authenticated GET uses the no-write reader and POST requires an integer `expected_record_version`. Replica issuance returns the random issued identifier. The off mode retains the baseline read and merge behavior.

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

Defer the package bump until after Phase 6 is merged into this branch and the Phase 8 implementation is ready for hand-back. Extend the then-current shipped package at the next free version with the learner settings, an exit flag set to false, and the decision entries. Preserve the hash chain and prior-version readability. The existing evidence and gateway contract pins continue to control their respective paths.

## 6. Settings

| Setting (env) | Type / development default | Freeze rationale |
|---|---|---|
| `LEARNER_SYNC` | `off` or `on` / `on` | Gates the new sync and assessment hardening. |
| `LEARNER_PLANNER` | `off`, `shadow`, or `on` / `shadow` | Shadow records choices. `on` requires DI-312 wiring. |
| `LEARNER_IDENTITY` | `off` or `on` / `off` | Isolates subject mapping and claim behavior. Preserve compatibility with the baseline demo fixtures. |
| `LEARNER_PRIVACY` | `off` or `on` / `on` | Gates consent, retention additions, export, and erasure receipts. |

All default to off outside development. Settings reject every non-off value outside development until the shipped, hash-verified configuration package reports the Phase 8 exit. A missing exit value is false. D-27 independently precludes adaptation outside development. Planner on is refused everywhere pending DI-312. The planner consults the shared adaptation-stop row and uses static ordering while it is set. Plan L: "Flags for planner and sync. Stop: any harness violation blocks adaptation (never evidence)."

## 7. File-by-file changes

Use the existing learner-record and auth routers, a separate `learner_record_*` service family, the current quiz route's trusted write boundary, and the existing erasure and retention services. Limit the orchestrator change to shadow plan selection. Keep the shared-file and package exceptions in handoff section 8.1. Add the evidence, security documentation, and acceptance map alongside their existing phase counterparts.

## 8. Database

Introduce additive ORM models for new Phase 8 tables and preserve discoverability of every subject-keyed table by erasure. Add any required startup registration for columns on existing tables. Defer the one reversible Alembic revision until after Phase 6 lands and the implementation is ready for hand-back. Select its parent from the actual merged head. Verify fresh and existing-row paths on SQLite and PostgreSQL, including both PostgreSQL drivers.

## 9. Routes and request-path behaviour

The existing routers serve replica issuance and synchronization under `/learner-record`, and claim, consent, export, and erasure under `/auth`. Claim requires a durable credential, a verified guest token, matching guest CSRF proof, and a trusted origin. The other privacy operations are caller-scoped. Local erasure confirms the password and clears cookies after commit. Guest erasure revokes the credential. Federated erasure covers local application data. Each new endpoint refuses requests when its feature flag is off.

## 10. Start-up, /ready, logs and SLIs

Settings fail startup on refused values. Durable assessment updates emit an identifier-free event with interaction start, commit time, and record version. Planner shadow choices and degraded outcomes emit identifier-free events. Readiness fields and final observability wiring follow Phase 6. Production F-3 and cloud metrics remain deferred under DI-300 and DI-305.

## 11. Frontend

The dormant synchronization helper obtains a replica from the server, advances its local clock from the observed server clock, and sends the expected record version. On a failed request it re-reads the record and retries once when the version advanced, preserving the batch's operation IDs. It uses the existing two storage keys. Production consent UI and learner-facing privacy-copy changes are tracked separately.

## 12. Fixtures and records

The erasure proof seeds every user-keyed table and its dependent rows for local, guest, federated, and demo synthetic cases. Its stable comparisons cover the control rows, zero-count report, and persisted receipt digest. The separate invariance tool uses the approved public fixtures, three mastery levels, and a fresh evidential cache per level under the Phase 5 shadow gateway. It compares resolved question, retrieval, evidence and thresholds, claim plan, locked and delivered claims, citations, and final outcomes. The typed alignment payload's band is accepted only when it equals the pinned V1 readability constants. The harness fulfills the plan section 15.2 engineering prerequisite. E3 and LQ-1 require separate research evidence.

## 13. Tests

| Criterion | Required coverage |
|---|---|
| AC-8-1 | Two concurrent replicas, conflict retry, and first-insert races preserve the expected mastery join. |
| AC-8-2 | Reject stale or equal counters on new operations and reject foreign replicas. Preserve receipt replay and trusted counter ordering. |
| AC-8-3 | Compare three mastery levels with different presentation choices and invariant delivered claims, citations, and answer decision. |
| AC-8-4 | Scan evidential templates, captured payloads, and configuration. Guard the dependency and tool-visibility boundaries. |
| AC-8-5 | Verify each subject-keyed table and receipt digest while preserving the control subject's rows. |
| AC-8-6 | Verify stored server score and reject client-authored mastery. |
| AC-8-7 | Compare disclosed cookies and storage keys with implementation in both frontend inventory and API acceptance coverage. |

Add authorization, retention, export, failover, stop persistence, migration, and freeze checks as each feature lands. Record the actual test names and regression checks with the build.

| Test module | Coverage implemented |
|---|---|
| `test_phase8_settings.py` | Development and production defaults, pre-exit startup refusal, verified package requirement, D-27, and DI-312. |
| `test_phase8_sync.py` | No INSERT on read, stale and duplicate operations, cross-subject ownership, server namespace, and write conflict with retry. Route and trusted assessment coverage are pending. |
| `test_phase8_planner.py` | Provisional mastery bands, deterministic lesson ordering, and static fallback. The cross-channel invariance harness remains pending. |

## 14. CI changes

Use the existing test jobs first. After integration, add the package readability and harness verification steps at the prescribed locations. Preserve the existing public-payload golden record.

## 15. Docs and evidence

Document subject linking and consent, generate the consent schema and authorization matrix, update the acceptance map and runbooks, and regenerate dependent fixture records once the tree is clean. Record current code behavior in sections 0-17 and review history in section 18.

## 16. Provisional defaults and deferred items

The following defaults are provisional. Implementation locations in this section refer to the code or artifact responsible for enforcing each default when it lands.

| # | Decision | Plan text | Default applied | Where |
|---|---|---|---|---|
| PD-200 | D-27, consent classes and H13 (Product Owner and Principal Investigator) | Plan 18.4 requires consent classes before Phase 8. Plan 9.4 requires the classes as H13 release evidence. | H13 remains held. Version `d27-unresolved-v1` classifies existing processing as unclassified and permits synthetic development grants for adaptation and analytics. Outside development those grants are refused, the planner uses the static order, and the analytics gate is off. Research is refused everywhere. The default establishes no legal basis or toggle-free status. | Consent schema and service, settings, and the future package's `learner` and `owner_decisions.D-27` entries. |
| PD-201 | D-26 compare-and-set (Security Lead) | Plan task 2 requires server-issued replica clocks, monotonic counters, and compare-and-set on `record_version`. | Check the expected version and serialize writes to the learner record. An out-of-date client re-reads and retries. Identical receipts remain idempotent. | Learner-record sync and trusted assessment write path. |
| PD-202 | D-08 research timing and D-14 research data plane (Principal Investigator) | Plan 18.3 offers IRB and OSF before research use. Plan H makes research contingent on IRB. | Apply D-08 option (a). Refuse research grants and research export everywhere. Use synthetic learners and the public fixture for engineering evidence. D-14 remains with DI-09. | Consent service and invariance harness. |
| PD-203 | D-05 feature freeze | Plan L requires planner and sync switches and an adaptation stop on harness violation. | Keep all Phase 8 switches off outside development and refuse non-off values before the verified Phase 8 exit. Development defaults are sync on, planner shadow, identity off, and privacy on. Refuse planner on pending DI-312. | Phase 8 settings and future package flag policy. |
| PD-204 | Engineering parameters (Engineering) | Plan tasks 2, 3, and 6 require clocks, server mastery, a planner, and three synthetic learner levels. | Cap issued replicas at 16 per subject. Use planner thresholds 0.4 and 0.75 and fixture levels 0.1, 0.5, and 0.9. Preserve unfinished course order. Sort completed review lessons by ascending mastery, then descending attempts, then course order. Set the remaining retry budget, attempt limits, and export and receipt encoding with their implementation. | `learner_record_sync.py`, `learner_record_planner.py`, and the future assessment, export, and harness implementation. |
| PD-205 | Retention classes (Engineering and Data Steward) | Plan task 5 requires scheduled retention. P1-D-09 records the 365-day security-event period. | Reuse the existing retention constants and provider-independent account and session rules. Keep the response ledger outside the expiry schedule pending PLAN-12.8. | Retention class register, shared cleanup service, and scheduled worker. |

| # | Item | Who | State |
|---|---|---|---|
| DI-300 | Phase 8 exit. Require AC-8-1 through AC-8-7 and the harness check in a cited green main CI run. Hold `phase8_exit_passed` false pending D-27 and H13, defaults ratification, evidence for A-17, acceptance of the Phase 1 and Phase 3 precondition deviations, and F-3 measured over a production log window. Blocked by: open D-27, owner ratification and acceptance, and production evidence under D-05. | Engineering, Product Owner, Principal Investigator | Open |
| DI-301 | Decide D-27 consent classes and file H13 release evidence. Blocked by: open D-27. | Product Owner, Principal Investigator | Open |
| DI-302 | Ratify PD-200 through PD-205 and any additional Phase 8 provisional defaults. Blocked by: owner ratification. | Owners of the respective decisions | Open |
| DI-303 | Confirm A-17 and Q-19 with authorized table names and row counts before cutover. Blocked by: production access and unresolved Q-19. | Platform Owner, Data Steward | Deferred |
| DI-304 | Enable Phase 8 switches and hardening outside development, including replica enforcement, reserved operation namespace, server counter correction, authenticated subject requirements, and retention coverage. Blocked by: D-05 and DI-300. | Platform Owner | Deferred |
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
| DI-316 | Determine whether independently submitted support requests should be deleted as part of learner erasure. They currently follow their separate retention schedule and carry no learner subject key. Blocked by: owner decision. | Product Owner | Open |

Plan M: "[Risk R-01][Risk R-08][Risk R-41][Risk R-42][Risk R-51]; residual: backups keep erased rows for a window."

## 17. Verification, work order and exit

Start with the baseline, then implement identity and synchronization, the privacy lifecycle, and the planner and harness. Run offline tests and validators with isolated scratch files. Repeat the applicable SQLite, PostgreSQL, frontend, and integration checks against the final branch after the Phase 6 integration. Plan P: "AC-8-1 to AC-8-7 green; harness in CI." `phase8_exit_passed` stays false while DI-300 remains open.

The Phase 5 merged baseline passed 8 separately isolated template tests, 1,593 SQLite tests (2 skipped, 9 deselected, 3 xfailed), and 1,591 tests per PostgreSQL driver (9 deselected, 3 xfailed each). Frontend lint, type checking, and 154 integration tests passed. The existing validators passed, including package v1 through v4, the V2 fixture report, and all 1,192 frozen public payload bodies. The path boundary scan passed. Licensed-passage scanning requires the fingerprint input. The Phase 8 invariance harness and erasure-proof scripts are pending.

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

The Phase 3 replay and Phase 4 and 5 fixture records were regenerated from the clean sync wiring commit. Their respective input digests are `6029c8cec97c131c948da8ba6651cd84e4666cfd6f54ed1b75961b459baec38a`, `4a3d343a6686d56769b672a2581aa6798a9d2a70912d8719e8de882275af975e`, and `c4e31e147608da6fad98ce15f6eb82f89e60f65745b75e451a4fde9769010f24`. Fresh record checks passed and the frozen public payload check matched all 1,192 bodies again.

## 18. Review history

The rows below record what each round fixed, in order. They may describe behaviour that a later round superseded. Sections 0-17 are authoritative after implementation. Each finding is one line naming the tests that fail if its defect comes back.

| Round | Commit | Findings fixed (one line each, with their tests) |
|---|---|---|
| Spec (pre-code) | - | Initial design and verification map. |
| Build | `9d1417c` | Initial settings, read path, sync services, and pure planner, covered by `test_settings_phase8_defaults_and_refusals`, `test_phase8_sync_read_issues_no_insert`, `test_phase8_sync_parallel_replicas_conflict_and_retry_without_losing_updates`, and `test_phase8_planner_uses_the_provisional_mastery_bands`. |
