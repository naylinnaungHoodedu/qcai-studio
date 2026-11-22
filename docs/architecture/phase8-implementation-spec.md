# QC+AI Studio: Phase 8 implementation spec

Learner adaptation and privacy-preserving record, upgrade plan lines 1557-1614. The working branch starts at `98f7cc4`.

Sections 0-17 describe the behaviour the code has once implemented. During the pre-code stage they specify the proposed behavior and identify pending checks. Section 18 holds one history-table row per review round. This file is LF in every checkout (`.gitattributes`).

## 0. Ground rules, measured facts, readings

Apply the branch rules and the Phase 8 handoff's shared-file restrictions. Keep the development fixtures synthetic and the tests offline. Verify implementation details against the branch baseline. At `98f7cc4`, `read_learner_record` uses the get-or-create path, operation receipts reject a changed payload, and the merge increments `record_version` independently of any expected version. The retention worker calls the existing retention service. The acceptance readings are in section 13.

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

After the Phase 5 integration, extend the shipped package at the next available version with the learner settings, an exit flag set to false, and the decision entries. Preserve the hash chain and prior-version readability. The existing evidence and gateway contract pins continue to control their respective paths.

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

Introduce additive ORM and startup schema changes for the subject, consent, receipt support, and durable adaptation stop as required by the selected models. Preserve discoverability of every subject-keyed table by erasure. Add one reversible Alembic revision after the integration, choosing its parent from the actual merged head. Verify fresh and existing-row paths on SQLite and PostgreSQL, including both PostgreSQL drivers.

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

Reserve PD-200 through PD-205 for consent, compare-and-set, research refusal, freeze settings, engineering parameters, and existing retention classes. Use the handoff's DI-300 through DI-315 assignments for the exit, owner decisions, production evidence and enablement, external providers, backup exposure, human review, assessment limits, planner wiring, and consent UI and disclosures. Populate the complete rows when their implementation and evidence references are available. Plan M: "[Risk R-01][Risk R-08][Risk R-41][Risk R-42][Risk R-51]; residual: backups keep erased rows for a window."

## 17. Verification, work order and exit

Start with the baseline, then implement identity and synchronization, the privacy lifecycle, and the planner and harness. Run offline tests and validators with isolated scratch files. Repeat the applicable SQLite, PostgreSQL, frontend, and integration checks against the final branch after the Phase 5 merge. Plan P: "AC-8-1 to AC-8-7 green; harness in CI." `phase8_exit_passed` stays false while DI-300 remains open.

## 18. Review history

The rows below record what each round fixed, in order. They may describe behaviour that a later round superseded. Sections 0-17 are authoritative after implementation. Each finding is one line naming the tests that fail if its defect comes back.

| Round | Commit | Findings fixed (one line each, with their tests) |
|---|---|---|
| Spec (pre-code) | - | Initial design and verification map. |
