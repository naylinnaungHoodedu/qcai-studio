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

The subject mapping binds a provider principal to a random subject identifier. The synchronization command includes an issued replica, operation identifiers and clocks, and an expected record version. Its result contains operation receipts and the resulting version. Consent records and change history carry version, class, state, time, and source. The planner returns a plan ID, ordered lesson IDs, and a planner version. Erasure receipts carry a random ID, timestamp, consent version, table coverage and zero counts, configuration digest, and scope statements. Concrete models and their field listings will be pinned as the interfaces are implemented.

## 4. Algorithms

- Bind replicas to the subject. Resolve existing receipts before rejecting a stale clock, so a repeated request can recover a prior outcome. Validate new operations' replica ownership, monotonicity, and causal-vector scope. Serialize the version check and record, receipt, and clock updates in one transaction. Resolve first-insert races with a bounded retry or conflict response.
- Preserve server-scored mastery and merge semantics. Choose assessment-operation counters under the same transaction as the attempt. Refuse client mastery operations and server-owned operation and replica identifiers.
- Select lesson order and style from server mastery, completion, and attempt state. Use static course order when the planner is unavailable or adaptation consent is absent.
- Erase through metadata-derived, child-first table coverage. Resolve the guest revocation representation against rotation and legacy-upgrade tests before wiring identity. Persist the canonical receipt digest and coverage summary in the durable audit path. A receipt describes local data scope and the information available about processors and backups.

## 5. Configuration package

Defer the package bump until after Phase 6 is merged into this branch and the Phase 8 implementation is ready for hand-back. Extend the then-current shipped package at the next free version with the learner settings, an exit flag set to false, and the decision entries. Preserve the hash chain and prior-version readability. The existing evidence and gateway contract pins continue to control their respective paths.

## 6. Settings

| Setting (env) | Type / development default | Freeze rationale |
|---|---|---|
| `LEARNER_SYNC` | `off` or `on` / `on` | Gates the new sync and assessment hardening. |
| `LEARNER_PLANNER` | `off`, `shadow`, or `on` / `shadow` | Shadow records choices. `on` requires DI-312 wiring. |
| `LEARNER_IDENTITY` | `off` or `on` / `off` | Isolates subject mapping and claim behavior. Preserve compatibility with the baseline demo fixtures. |
| `LEARNER_PRIVACY` | `off` or `on` / `on` | Gates consent, retention additions, export, and erasure receipts. |

All are off outside development. Refuse every non-off setting outside development while the verified configuration package's `phase8_exit_passed` is false. Enforce the separate D-27 restriction for adaptation. Persist a shared adaptation stop across processes and restarts. Plan L: "Flags for planner and sync. Stop: any harness violation blocks adaptation (never evidence)."

## 7. File-by-file changes

Use the existing learner-record and auth routers, a separate `learner_record_*` service family, the current quiz route's trusted write boundary, and the existing erasure and retention services. Limit the orchestrator change to shadow plan selection. Keep the shared-file and package exceptions in handoff section 8.1. Add the evidence, security documentation, and acceptance map alongside their existing phase counterparts.

## 8. Database

Introduce additive ORM models for new Phase 8 tables and preserve discoverability of every subject-keyed table by erasure. Add any required startup registration for columns on existing tables. Defer the one reversible Alembic revision until after Phase 6 lands and the implementation is ready for hand-back. Select its parent from the actual merged head. Verify fresh and existing-row paths on SQLite and PostgreSQL, including both PostgreSQL drivers.

## 9. Routes and request-path behaviour

Use existing routers for claim, replica issuance, synchronization, consent, export, and erasure. Apply caller or resource-owner authorization as appropriate. An identifier belonging to a different subject resolves as missing. Reject an unapproved grant. Disable new routes under the release freeze and keep enabled development processing within the relevant flag and authorization checks.

## 10. Start-up, /ready, logs and SLIs

Validate settings and fail startup on refused values. Count sync conflicts and invariance violations. Capture interaction start and record commit timing without learner identifiers. Add readiness fields after the integration. Production F-3 and cloud metrics remain deferred under DI-300 and DI-305.

## 11. Frontend

Update the existing dormant synchronization helper for issued replicas, version conflicts, and retry. Keep its storage-key inventory. Production consent UI and learner-facing privacy-copy changes are tracked separately.

## 12. Fixtures and records

Generate the erasure proof and the invariance report from synthetic or approved public data. The harness compares query, evidence, claim plan, threshold state, delivered claims, cited spans, and answer decision at three mastery levels. Require variation in at least one presentation and fail on any evidential difference. The harness fulfills the plan section 15.2 engineering prerequisite. E3 and LQ-1 require separate research evidence.

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
| PD-204 | Engineering parameters (Engineering) | Plan tasks 2, 3, and 6 require clocks, server mastery, a planner, and three synthetic learner levels. | Use planner thresholds 0.4 and 0.75 and fixture levels 0.1, 0.5, and 0.9. Preserve unfinished course order. Sort completed review lessons by ascending mastery, then descending attempts, then course order. Resolve the replica cap, retry budget, attempt limits, and export and receipt encoding with their implementation. | Planner constants and the future sync, assessment, export, and harness implementation. |
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

Plan M: "[Risk R-01][Risk R-08][Risk R-41][Risk R-42][Risk R-51]; residual: backups keep erased rows for a window."

## 17. Verification, work order and exit

Start with the baseline, then implement identity and synchronization, the privacy lifecycle, and the planner and harness. Run offline tests and validators with isolated scratch files. Repeat the applicable SQLite, PostgreSQL, frontend, and integration checks against the final branch after the Phase 5 merge. Plan P: "AC-8-1 to AC-8-7 green; harness in CI." `phase8_exit_passed` stays false while DI-300 remains open.

## 18. Review history

The rows below record what each round fixed, in order. They may describe behaviour that a later round superseded. Sections 0-17 are authoritative after implementation. Each finding is one line naming the tests that fail if its defect comes back.

| Round | Commit | Findings fixed (one line each, with their tests) |
|---|---|---|
| Spec (pre-code) | - | Initial design and verification map. |
