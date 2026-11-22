# QC+AI Studio — Phase 6 Implementation Spec
## V3 audit and adjudication operations (plan L1439-1498)

- **Repository:** `D:\QC_AI_Studio\Codex_Webapp_QC_AI_Studio`.
- **Branch:** `phase6/v3-audit`, cut from `origin/main` `c34a8c1` (Phase 5 merged, PR #37; tree identical to `8aa4ff1`).
- **Plan:** `D:\QC_AI_Studio\QC_AI_Studio_Ultimate_Software_Upgrade_Plan.txt`. Plan locations used here:
  - The Phase 6 block: L1439-1498.
  - The 6.3 coverage rows: L700-722. The CUSUM rows: L742-748.
  - The loops: L853-862.
  - VerificationVerdict and AuditEvent: L894-906.
  - 7.5: L916-928. 7.7: L940-958. 7.8: L960-982.
  - 9.4 holds: L1904-1926 (H4, H10).
  - 13.6: L2365-2384. 13.7: L2386-2405.
  - 15: L2593-2632, L2660-2668 and L2704-2724.
  - 16.1: L2736-2742.
  - 18.3/18.4: L2978-3026.
- **Fixed decisions:** E1-E16 (`BEP-2-12/00_meta/workflows/p6/p6_design.txt`). Every one is implemented, and section 1 lists each refinement.

Sections 0-17 describe the behaviour the code has. They are authoritative and are kept current in place (P2-12-D-03). Section 18 holds one history-table row per review round. This file is LF in every checkout (`.gitattributes`).

---

## 0. Ground rules, measured facts, readings

### 0.1 Binding constraints (Phase 5 0.1, unchanged, plus Phase 6's)

**Git and files**
- Stay on the branch: no branch switch, no `git stash`, no push, no history rewrite, no git-config change.
- Commit messages end with a blank line, then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Temporary files go only to the scratchpad. Nothing is written to the repository root. Check `git status --short` after every script run.

**Forbidden reads and calls**
- Never open `infra/cloudrun/*.env.yaml`, `apps/frontend/.env.local`, `apps/api/.env.example` or any `.env*` file. A recursive search over `infra/` uses `git grep`.
- No cloud, gcloud, gh, provider or LLM call, and no deploy.
- No test touches the network: `apps/api/tests/network_guard.py` enforces this.

**Freeze (D-05, P1-D-18)**
- Outside development, `V3_QUEUE` is `off` and every learner-facing path behaves as Phase 5's.
- The learner flag route answers 404 outside development whatever `V3_QUEUE` says (4.7).
- The public-payload golden must pass unchanged and is never re-written: `scripts/capture_public_payloads.py --check apps/api/tests/data/phase4_public_payloads_v1.json`.
- Phase 6 adds no learner-facing control, banner or text outside development.
- `/ready` is an operations route. It gains static V3 fields in every environment (10.2), as Phase 5 added the gateway fields.

**Privacy (E10, E4)**
- No learner identifier goes into any V3 queue item, gold row, report or log line. This covers user ids, emails, turn, thread, message, shadow and qa- ids, learner text and private-plane spans.
- Queue items and gold rows hold the following only:
  - claim ids and span ids;
  - public, quotable claim and span text (views only; gold rows hold text hashes);
  - keyed digests (`app.core.client_identity.keyed_digest`) of response ids and reviewer ids, as pseudonymous evidence (no control compares them, 4.5);
  - ledger sequence numbers.
- Two tables hold a person's id, both named `user_id` so that the metadata-driven erasure removes them: `v3_claims` (a reviewer's lease and round record) and `v3_flags` (a learner's flag). No `erasure.py` edit is made (E16).
- No new source literal starts with `qcai_`. The frontend environment flag is `V3_REVIEWER_UI` (11).

**Tests**
- No existing test or guard is weakened, and no new skip or xfail is added.
- A changed test keeps its intent, and its commit message says why.
- Each fix is mutation-checked: revert it, see the test fail, restore it byte for byte.
- AC tests go in `test_phase6_acceptance.py`. Other tests go in the feature module.
- No test reads outside the repository: plan quotes are literal strings in the tests.
- Security events are read ordered by `seq`, and a test that counts denials uses a fresh event cap (`monkeypatch.setattr(security_log, "_caps", security_log._Caps())`, M6).
- Every engine a test creates is disposed (`test_every_engine_a_test_creates_is_disposed`).
- No test writes a backdated queue item into the shared test database. `v3_fakes.FIXED_NOW` is used only with fresh databases (`v3_fakes.fresh_v3_sessions()`). Items seeded into the shared database use the real clock. A `conftest.py` autouse guard fails any test that leaves a shared-database queue item enqueued before the session started (4.10: the V2 track reads the stop through its pipeline's database).

**Doc-text guards Phase 6 text must pass**
- The Phase 3 NARRATIVE regex (`test_phase3_docs.py::test_k3_the_authoritative_text_states_the_current_code_only`).
- The section-3 field tests of Phases 3-5, which hold because Phase 6 changes no field of a class those sections list.
- The Phase 4 and 5 doc tests named in 13.3, changed with their texts.

### 0.2 Measured facts (on the branch at `c34a8c1`, 2026-11-22)

**M1. Baseline.**
- SQLite: 1601 passed, 2 skipped, 1 deselected, 3 xfailed.
- PostgreSQL 17: 1603 passed, 1 deselected, 3 xfailed, under both psycopg and pg8000.
- Frontend: lint, typecheck and 154 integration tests pass.
- Main CI run 45044415408 was green on every job.
- `BEP-2-12/00_meta/check_records.py` passes 32 of 32.

**M2. What the ledger already records for V3.**
- The Phase 4 record type `V3Intent` has `queue "pending_v3"`, `reasons ⊆ {v1_3_flag, v1_8_misconception, x4_margin}`, `trigger: "X4" | None` and `gold_label_id: None` (typed `None`: no record can carry a gold label).
- The Phase 5 record type `V3IntentV2` adds the reasons `v2_correction_exhausted` (with `escalation: "X2"`) and `v2_degraded_withheld`.
- `ledger.pending_v3_intents` reads these intents, read-only.
- `V2ClaimVerdict` carries `tier`, `members`, `votes[]` (each with `ehmf_type` exactly when it objects, NOT_ENOUGH_INFO included), `objections`, `outcome`, `critical` and `cycle` (the correction cycle of its last tally).
- `V2Block.corrections[i].failed_claim_ids` lists the claims that failed each correction cycle; an alignment item's re-render (after the claim loop) lists the claims its rendering showed.
- Production writes only `legacy` records: `ledger-entry-v1`, `verification: null`, with a `retrieval.sufficiency`. Shadow records (v2 or v3) exist in development only.
- `build_legacy_entry` writes `claim_set_hash=None` on every legacy record. Only shadow records carry a claim-set hash.

**M3. Critical claims at the branch base.**
- `v2_panel/tiers.critical_for(claim_id, package)` was membership of `v2.correction.critical_registry`.
- The loader refuses a non-empty registry while D-25 is open, so `critical` was always false.
- `v1_checks/runner.py` `_run_v2` runs the correction loop, and `_correction_plan` revises every content-failing claim through the generator's optional `revise`.
- A revised claim gets a new content-addressed id. The record then no longer holds the original claim's verdict (`test_a_revised_claim_is_a_new_candidate_judged_by_v1_from_the_start_and_delivered_when_it_passes`).
- A member that fails a call leaves the panel for the rest of the response. A claim judged again (a correction cycle) is re-tallied from the remaining members' cached pairs (`track.py` `_judge`). The tier-1 rule is `1oo3` in FULL and `1oo2` in REDUCED-2. So a tier-1 claim that failed on one member's objection passes in the next cycle when that member has left the panel.

**M4. V1.5 and the X4 margin.**
- `check_v1_5(sufficiency, x4_margin=)` marks `near_miss` when `score is None or score < floor + x4_margin`.
- The shipped margins are `bm25f-v1` 2.4 and `p1-floor` 0.0. The production gate is `p1-floor`, so a production legacy delivery that records its gate score is never X4-marked. One without a score is marked, which is V1.5's conservative rule.
- In development (bm25f-v1), in-domain fixture query 139 is the one query of `score_floor_queries.json` that V1.5 marks.

**M5. Roles.**
- Roles are free strings. They come from the Auth0 claim (`roles[0]`), the local account (`user_accounts.role`, always `"learner"` at registration) or the demo header (development default).
- `require_role(*roles)` records `authz.denied` with `{"route", "required": "role:<sorted roles>", "provider"}` and returns 403.
- `LEDGER_READER_ROLES = ("reviewer",)`. No in-app grant of any role exists.
- `test_authorization.py` maps dependency role sets to access levels (`_actual_access`) and enumerates refused `(route, kind)` pairs.
- `enforce_guest_request_protection` (`main.py`) refuses a cookie-authenticated mutation without a trusted Origin and the CSRF header before routing. It records `request.forbidden`, not `authz.denied`.

**M6. The security log** is append-only, hash-chained, and 365-day retention.
- Each event type with a `denied` or `failure` outcome is capped at 60 per minute per instance.
- An HTTP access-log table does not exist. The security log is the platform's access record.
- `keyed_digest(value, purpose)` keys an HMAC with `get_settings().guest_token_secret`. `guest_token_previous_secret` exists, so the key rotates by design, and a digest made before a rotation never equals one made after.

**M7. Erasure.**
- `erasure.user_keyed_tables()` finds tables with a `USER_KEY_COLUMNS` column (`user_id`, `reviewer_user_id`, `player_id`, `opponent_id`, `guest_id`).
- `test_every_identity_like_column_is_a_registered_user_key` refuses any column matching `(user|player|guest|author|opponent|reviewer|learner|account)[a-z_]*_id$` that is not registered. A `reviewer_digest` column passes it.
- `_seed_everything` seeds one row per covered table, skipping integer primary keys. It needs every foreign key to point at another covered table, so `v3_claims` has no foreign key and a single integer primary key.
- `erase_stale_guest_rows` applies only to tables with `created_at`.

**M8. Wilson.**
- `evaluation/qcai_eval/statistics.wilson_interval` (z = 1.959963984540054) is not in the API image, which copies `apps/api/app` only.
- `app/services/citation_migration.wilson_interval` is the API's copy. It is held equal to the harness by `test_citation_migration.py::test_the_wilson_interval_equals_the_evaluation_harness`.
- Measured values for 0/300: upper 0.012642971224546034; lower 8.673617379884035e-19.
- The closed form z²/(300 + z²) evaluates to 0.012642971224546036. It equals the harness upper to within 2e-18, not bit for bit.
- Measured upper bounds for 1/300 and 3/300: 0.018636693694531237 and 0.02898349336233983.

**M9. The draw, measured with rule `seeded-sha256-bernoulli-v1`.** A key is drawn when `int.from_bytes(sha256(f"x6-draw-v1|{seed}|{response_id}").digest()[:8], "big") · den < num · 2^64`.
- With seed `qcai-x6-v1` over the 1000 synthetic ids `turn-{UUID(int=i)}`, i = 1..1000: 47 are drawn at 1/20 and 192 at 1/5. The 1/20 set is a subset of the 1/5 set.
- 2000 other seeds `seed-0..seed-1999` drew counts in [33, 69] for 99.05% of seeds.
- The exact 0.5% and 99.5% quantiles of Bin(1000, 0.05) are 33 and 69, and P(33 ≤ X ≤ 69) = 0.9929 (the AC-6-2 band).
- The first 6070 ids give exactly 300 draws. Bin(6070, 0.05)'s 99% band is 261-348.
- At the 1/20 boundary u = floor(2^64 / 20), u / 2^64 rounds to exactly 0.05 as a float, so only an integer comparison draws it.

**M10. Development pipeline, tier-1 contexts.**
- With `MODEL_GATEWAY` off, the in-domain fixture queries 9, 16, 23, 30, 43, 56, 63 and 70 of `score_floor_queries.json` are assessment contexts (tier 1). Query 56 abstains.
- Query 30 ("Explain how the authored Module 4 document connects expressive bottlenecks across compression, language, and explanation.") locks `claim-5986f3f1a2e538431cad1eba9de377a7`, `claim-f7a69a03bf419134f7104233b637aed6` and `claim-71143cadf24a121f65b59a75a9b9ec53`, each on one span.
- No other fixture query and no question string quoted in any test module locks any of these three claims. In contrast, claims of queries 9 (MULTI_CLAIM), 16, 23, 43, 63 and 70 are shared with up to 12 other queries.

**M11. Speed.** 1000 `append_ledger_entry` calls on in-memory SQLite take 1.62 s; the residual report runs in about 22 s.

**M12. `/ready` is public.**
- Its static part (`_build_fields()`) never reports a count (Phase 3: the ledger head is "traffic volume").
- `test_plan_i_ready_reports_package_v4_and_the_gateway_state_and_no_per_run_outcome` and the Phase 4 /ready test assert `_build_fields()` is unchanged after a chat.
- `test_plan_i_ready_reports_versions_ledger_head_and_two_pass_mode` asserts that `_build_fields()` makes no statements other than `SELECT gateway_stops.reason ...`.

**M13. Alembic.**
- The head at the branch base is `20261122_phase5_gateway_controls`, and `alembic_version.version_num` is VARCHAR(32).
- The Phase 3 revision's downgrade refuses a non-empty ledger unless `-x allow_ledger_drop=true`.
- `test_response_ledger_migrations.py` (e10, f14) and `test_phase3_acceptance.py::test_plan_g_the_alembic_revision_is_reversible_and_refuses_to_drop_a_non_empty_ledger` step through each revision.

**M14. Package v4.**
- Package 4.0.0, schema 4, sha256 `9cb984081c89c6f0d3b44cc36b38d3332383b76038734b4e21983d319c23408c`, created 2026-11-21, status provisional.
- `owner_decisions` holds D-06 `{"state": "open", "path": ..., "record": "DI-52"}` and D-25 `{"state": "open", "registry": [], "record": "PD-29"}`, and no D-18, D-08 or D-14.
- `v2.correction.critical_registry` is `[]`.

**M15. Tests and texts that pin the shipped package.**
- `test_config_package.py` (`RAW` = the default package; `test_v4_*`).
- `test_phase4_acceptance.py`'s doc tests over the Phase 3 spec's 5.2 lines and test lines, the loader regex, the report shape and the code texts.
- `test_phase5_acceptance.py`'s `/ready` test and the Phase 4 spec's loader line.
- Texts: `ledger.py`, `tutor_followups.py`, `tutor_pipeline/contracts.py`, `package_check.py` and `__init__.py`, `scripts/config_package.py`, the Phase 3 and Phase 4 specs' 5.2 lines, the env example and `deployment.md`.
- The records `docs/evaluation/phase3/three_plan_replay_v1.json`, `phase4/v1_fixture_report_v1.json` and `phase5/v2_fixture_report_v1.json` carry the package version and the module hashes (`inputs`), so every package bump re-writes them.
- BEP: `check_p5_build_the_phase_record_states_the_exit_not_passed_and_lists_every_open_item` and `check_p5_build_the_plan_holds_the_text_the_v4_package_quotes` read v4.json explicitly (E15).

**M16. Frontend.**
- Next 16, with integration tests run by `tsx --test tests/**/*.test.ts` (source-level and pure).
- The backend proxy (`src/app/api/backend/[...path]/route.ts`) passes `x-demo-user`/`x-demo-role` through when demo auth is on (development default).
- `primary-nav.tsx` holds the navigation.

**M17. The test database is shared across tests**, the PostgreSQL CI database included. Append-only tables cannot be cleaned, so V3 service tests use fresh databases. Route tests read a fresh database through a `get_db` override, or seed their own items with the real clock and assert on them only.

**M18. Plan text Phase 6 must meet beyond its block.**
- 7.7: "SLIs (citation resolution, verification completion, abstention, escalation share, queue age, residual error) derive from ledger rows".
- 7.4: "AuditEvent {prev_hash, hash, actor_role, action, payload_digest} is append-only [Risk R-22]" and "v3 {trigger (X1-X6), gold_label_id}".
- 7.3: "mutations carry client keys".
- 13.6: "a sustained CUSUM alarm (X5) also stops the line; paper: audit 5% -> 20%, promotions held".
- 15.3: "V-3 numerator counts X1-X4 only; audits are proof tests [Evidence E-85]." and "HR-3 deployment form: monthly Wilson bound from the 5% draw [Evidence E-85]."
- 16.1: "the X6 auditor MUST NOT audit their own change [Risk R-35]".
- 9.4: H4 "Staffing [Decision D-18] | P6 pool; P11 start | Capacity statement"; H10 "IRB/OSF [Decision D-08] | P6 experts; P10, P12 cohorts | IRB letter; OSF DOI".

**M19. Scripts that build their own database.**
- `scripts/run_v2_fixtures.py` creates its own in-memory engine (`create_all`, `run_schema_upgrades`) and passes `session_factory=env.sessions` to `TwoPassPipeline`.
- Its process-global `SessionLocal` points at a separate in-memory database with no tables.

**M20. The API image** copies `apps/api/app` only, so `apps/api/tests/` (and `score_floor_queries.json`) does not exist there.

**M21. Ledger JSON field names.** The JSON schemas of `ENTRY_SCHEMAS` hold a property `rating` (`AlignmentVote.rating`, the verifier's 1-5 alignment rating) and `contains_learner_state`. They hold no `f_i`, `feedback`, `flag` or `learner_*` rating field.

### 0.3 Readings

- **R-a. Delivery.** A ledger record with `delivery` `legacy` or `delivered`, which is what a learner received. Abstentions count. A `shadow` record is never a delivery; the delivery it shadows is the record of its `shadowed_response_id`.
- **R-b. Withheld.** Never delivered, and held by V3 until a release that Phase 7 change control decides (DI-93). Phase 6 releases nothing. A held claim's record keeps the finals Phase 4 or Phase 5 gave it: under `on`, `abstain` with X2 (or `withhold` when V2 withheld it); under shadow, Phase 4's.
- **R-c. Objection.** A family verdict other than SUPPORTED (Phase 5 R-c). NOT_ENOUGH_INFO objects.
- **R-d. Audit.** An X6- or X5-drawn delivery adjudicated by a reviewer. Audits are proof tests and are not counted in V-3.
- **R-e. Access log.** The security log (M6). A refusal is `authz.denied`; a reviewer read or action is a `v3.*` security event.
- **R-f. Reviewer.** A principal whose role is `reviewer`, the closed role of 4.12, admitted by `reviewer_admitted` (development, or a staffed pool). No other role reaches a reviewer route.
- **R-g. Applied.** A final gold label accepted into the recalibration input (the export). It edits no ledger row and no verdict, and releases nothing.
- **R-h. Modes.**

| `V3_QUEUE` effective | What runs | Learner effect |
|---|---|---|
| `off` (default outside development) | Nothing: no scan, no draw, no item, no flag intake (the flag route answers 404). The reviewer routes answer 404 only to an admitted reviewer (development), after the role and pool checks, which refuse every other caller with 403 and `authz.denied` (outside development every caller while D-18 is open). The holds (pure, 4.9) and the stop (computed from the stored queue, 4.10) are unchanged. | none |
| `shadow` (default in development) | Scan, triggers, queue, draw, gold store, workflow, reviewer routes, metrics; the flag intake in development only | none (shadow pipeline only) |
| `on` (development only before the Phase 6 exit) | The same as `shadow`; delivery-path consumption is DI-97 | none |

---

## 1. Conflicts between plan text and the fixed decisions, with resolutions

Each resolution is a refinement. None reverses a fixed decision.

1. **X1 "withheld at tier 1" against Phase 5's `on` record and E1.**
   - Plan text: AC-6-1 "then X1 fires and it is withheld".
   - Under Phase 5's `on`, a tier-1 claim with one objection fails 1oo3 and goes through correction (M3). A revising generator would replace it, losing its objection from the record. A member that leaves the panel later in the response turns the claim's next tally into a 1oo2 pass, and the claim would then be delivered.
   - E1: triggers are pure functions over the records.
   - **Resolution:** X1 reads the record's `critical`, `tier` and objections (4.1), and "withheld" is R-b: a V3 hold (4.9). One runner refinement, a sticky hold (4.13), keeps the objection in the ledger and the claim undelivered.
   - Under `on`, a claim the V2 track marks critical at tier 1 that fails in any cycle is held for the rest of the response:
     - it is never given to `revise`;
     - it stays pending in every later cycle, even when a later tally passes;
     - after the last cycle it ends `abstain` with X2, or `withhold` when its last outcome is V2-withheld.
   - Its verdict, objection (in `corrections[i].failed_claim_ids`) and `critical: true` stay in the record.
   - No ledger schema changes and no Phase 5 record rule changes. `critical_for` reads package v5's per-environment registry (4.13).
   - **The tier-2 and tier-3 case.** Plan AC-5-4 reads "Given one objection, then a tier-1 claim fails and a tier-2 claim passes (non-critical claims; critical claims follow X1 from Phase 6 [Decision D-25])", and task 1 "X1 critical-claim objection (registry [Decision D-25]; withheld at tier 1)". So the tier-2 pass rule covers non-critical claims only, a critical claim with an objection follows X1 at any tier, and the claim is withheld at tier 1. **Resolution:** X1 fires on a critical claim's objection at tiers 1, 2 and 3 (`v3.triggers.x1.tiers`), so the item is queued and counted in V-3; it is held (`held`, `holds.withheld_claim_ids`, the runner's sticky hold) at tier 1 only (`withhold_tier` 1). A critical tier-2 claim with one objection still passes 2oo3 under `on` (Phase 5's tier rule is unchanged), so its record may deliver it while its X1 item waits for a reviewer. This is dormant today: development's synthetic registry holds tier-1 claims only, and every other registry is empty while D-25 is open (PD-33).
2. **The gold store's plane.**
   - Plan text: 6.1 L627-628 "Private plane: ULQS, E1-E4, HR-*, LQ-*, UE-* and the V3 gold store run only in the private research data plane [Decision D-14] [Assumption A-13]; fixtures, gold labels and licensed spans MUST NOT enter the public repository, CI artifacts, logs or releases (invariant 8)"; 6.3 L719-720 "reviewer UI, RBAC, private-plane gold store -> 6 (D-18, R-49)" (the cell joined across its two lines); and 7.5 "research (licensed extractions, ULQS, gold labels [Assumption A-13])".
   - Against them, 15 L2593-2594: "(a) F-1 to F-3, V-1, V-3 and deployment-form HR-3 are measured in staging and production ("Prod") on the public 12 DOCX + 12 MP4 corpus only". The deployment form of HR-3 is "monthly Wilson bound from the 5% draw" (15.3), which needs production-plane labels of the 5% draw. The plan contradicts itself: the gold store that L627-628 places in the research plane is the one deployment-form HR-3 needs in production.
   - E10 limits the production plane to labels about public-corpus spans.
   - **Resolution:** the two forms get two stores. The Phase 6 gold store is the deployment form's: access-restricted ("private": reviewer routes and workers only, no public route) in the production database, holding labels about public-corpus deliveries only (a reviewer sees public, quotable spans only, 4.14; under D-31 none is quotable, so nothing is reviewable there today). L627-628's research-plane gold store (study-form HR-3, E1-E4) is not built: it waits for D-14 (DI-94).
   - L627-628's "MUST NOT enter the public repository, CI artifacts, logs or releases" holds for the production-plane labels too: no public route returns one, the logs carry seq numbers and hashes only (10.3), the export refuses the application tree and the repository checkout (4.6), and the committed residual report holds counts only (12.1).
   - Research-plane labelling is a plan non-goal ("Non-goals: Dawid-Skene before 200 gold claims [Evidence E-84]; research labelling.") and waits for D-14 and D-08 (DI-94).
3. **Plan 15.3 "X6 draws or X5-elevated audits in the 10%?"** **Resolution:** the plan's RECOMMENDATION "V-3 numerator counts X1-X4 only; audits are proof tests [Evidence E-85]." applies provisionally (PD-37); ratification is DI-98.
4. **13.6 "a sustained CUSUM alarm (X5) also stops the line"** against E1, which gives the CUSUM statistic to Phase 9. **Resolution:**
   - Phase 6 defines the alarm contract (`cusum-alarm-v1`, 3.1) and records alarms (4.8), and an alarm raises the audit rate.
   - The statistic, the meaning of "sustained", the stop-the-line and "promotions held" (L746) are Phase 9's (DI-96).
5. **AC-6-7 "an access-log entry".** No HTTP access-log table exists (M6). **Resolution:** R-e.
   - The refusal is one `authz.denied` security event with `{"route", "required", "provider"}`, mirrored to the platform logs.
   - The 60-per-minute cap (M6) applies in production. The AC test uses a fresh cap and a guest that passes the CSRF guard (M5), so the refusal is the reviewer gate's.
6. **Exposure and K** have no plan definition (E2), and legacy records carry no claim-set hash (M2). **Resolution:** PD-34.
   - Exposure is the number of considered learner deliveries (v3_draws rows) whose claim-set key equals the record's, up to its seq, and at least 1. The key is the sha256 of the record's sorted claim ids (`sorted-claim-ids-sha256-v1`). Exposure is 1 for a shadow or abstention record.
   - Exposure belongs to the record: an item created before the scan drew its record (an X3 flag) is raised to the record's full count when the scan draws it (4.3), so the order in which a flag and the scan reach a record never changes an item's priority.
   - K is the V2 panel's support share, 0 without a panel vote.
7. **E4 "the role grant is refused there"**, against the code base, which has no in-app role grant (M5). **Resolution:** the refusal acts at use.
   - `reviewer_admitted(settings)` (4.12) is false outside development while D-18 is open, whatever role a token or header carries.
   - `require_reviewer` refuses such callers on every V3 route. The ledger route's reviewer branch reads them as owners.
   - No grant tool is added. Provisioning is DI-91, together with DI-38.
8. **Plan I SLIs and "queue age p90 alert [Risk R-40]"** against public `/ready` and no cloud write (M12). **Resolution:**
   - `/ready` gains static V3 fields only.
   - The SLIs are on the reviewer-only `GET /v3/metrics`, in the worker's `status` line and in structured log events.
   - The alert policy and the log-based metrics are DI-95.
9. **Plan L "Stop ... limits tier 1 to pre-verified content"** with no pre-verified content (PD-30, DI-83) and no delivered two-pass path (DI-85). **Resolution:**
   - The stop is computed state (4.10).
   - While it holds, the V2 track applies Phase 5's `pre_verified_only` kill-switch path to tier-1 responses (4.13): no call, every claim withheld in ZERO, and under `on` abstain and queue. The record names `kill_switch: "pre_verified_only"`, and `tutor.v2.v3_stop` names the cause.
   - Tier 2 and 3 are unaffected. It never releases anything.
10. **What `on` adds.** E6 copies Phase 5's switch. Phase 6 has no delivered path. **Resolution:** `on` runs as `shadow` does, and the delivery-path consumption is DI-97.
11. **X2 "Type A/B unresolved after two cycles"** against Phase 5's X2 marking of every exhausted claim (Phase 5 conflict 6). **Resolution (E1):**
    - The X2 trigger needs the recorded X2 escalation and an objecting family verdict of EHMF type A or B.
    - Every other exhausted claim is still queued, with reason `v2_correction_exhausted` and no X trigger, and is not counted in V-3.
12. **"10% double review" with one maintainer (A-9, E-63).** An independent second review needs a second reviewer. **Resolution:** a double-review item stays queued until another reviewer adjudicates it. With fewer than two reviewers it never closes and stays held (plan J). This needs no code beyond 4.5.
13. **Plan 7.3 "mutations carry client keys".** **Resolution:**
    - Adjudication and apply carry a `client_key`.
    - A flag is idempotent per learner and turn.
    - A claim is idempotent for its lease holder (4.5).
14. **Plan G "pre-ledger deliveries reported as non-auditable"** with no per-delivery id for Q&A before the ledger. **Resolution:** counts only (4.11). The pre-ledger deliveries are the tutor turns an image that keeps no ledger created (`ledger_record_expected` null) and the Q&A interactions created before `ledger_started_at`. The other deliveries without a record are reported apart, because they are not pre-ledger: turns created while the ledger kill switch was off, lost appends (a Phase 3 plan L stop) and appends still inside the coverage horizon. None is ever drawn.
15. **E5 "Use evaluation/qcai_eval/statistics.py wilson_interval"** against the image layout (M8). **Resolution:**
    - The API computes the bound with `citation_migration.wilson_interval`, which an existing test keeps equal to the harness.
    - The residual report script imports the harness itself and records `harness_equal: true`.
    - `statistics.py` is unchanged.
16. **Plan E "reviewer route (frontend)" under the freeze.** **Resolution:**
    - `/review` renders only when the frontend runs outside production (`NODE_ENV`) and the API's `/ready` reports `v3_queue` not `off`; otherwise it returns 404.
    - No navigation link exists, and the page is `noindex` (11).
17. **Plan F "runbook".** **Resolution:** a `## Phase 6: V3 audit and adjudication (runbook)` section in `infra/cloudrun/deployment.md` and a Phase 6 SLI section in `observability.md`, the Phase 5 pattern.
18. **AC-6-2 "1,000 synthetic deliveries".** **Resolution:** legacy ledger records `turn-{UUID(int=i)}`, i = 1..1000, appended through `append_ledger_entry`. The shipped seed draws 47 (M9).
19. **AC-6-5's bound.** **Resolution:**
    - z = 1.959963984540054 (the harness) gives an upper bound of 0.012642971224546034 for 0 of 300 (M8).
    - The test asserts exact equality with the harness and the inequality below 0.013.
    - It checks the closed form z²/(300 + z²) with `math.isclose(rel_tol=1e-12)`, because the two floating-point evaluations differ in the last bit.
20. **E8 "the draw record and any reviewer-assignment tables" and the user_id rule.** **Resolution:**
    - A reviewer's leases and round records (`v3_claims.user_id`) and learner flags (`v3_flags.user_id`) are erased with the person.
    - Erasing a reviewer's live lease returns the item to `queued`.
    - Erasing a reviewer's round record leaves the gold row's `reviewer_digest` as the pseudonymous record (DI-99).
    - Erasing a learner's flag keeps F_i, which the X3 item carries (4.7).
    - The gold store's `reviewer_digest` is a keyed digest, not a `user_id`. The store must not be erased (append-only evidence, R-22), and a `user_id` column there would make every erasure fail on the append-only trigger.
21. **Plan B: "research use waits for IRB/OSF [Decision D-08], research environment only [Decision D-15]."** **Resolution:** Phase 6 has no research use and no research environment; the gap is DI-94.
22. **E3 "hash-chained or otherwise tamper-evident".** **Resolution:**
    - A hash chain follows the security log's pattern: a PostgreSQL advisory lock, seq retry, and triggers that refuse UPDATE, DELETE and TRUNCATE and require every insert to extend the chain.
    - Every append logs its seq and record hash as an off-database copy. No head table is used, as in the security log.
    - No restore path exists. Gold rows are written by adjudication only, and the export (4.6) is the archive.
23. **Plan L861-862 "V3 ordering severity x exposure x (1 - K) are built for study, pending confirmation".** **Resolution:** a versioned, provisional `v3.priority` block (PD-34), with the plan's 6.3 weights bound while D-06 is open.
24. **The registers' rule "never edit other phases' rows"** against P2-12-D-03 (current text) for DI-38 (reviewer provisioning) and DI-56 (V3 consumption of the intents). **Resolution:** the binding task rule wins.
    - Those rows stay as written.
    - The Phase 6 rows DI-91 and the BEP phase record say what Phase 6 built against them.
    - E15's DI-74 edit is the one sanctioned exception.
25. **Plan 7.4 "v3 {trigger (X1-X6), gold_label_id}"** against the append-only ledger, whose `V3Intent.gold_label_id` is typed `None` (M2), and AC-6-4 "no ledger row changes". **Resolution:** a verdict's v3 is the ledger intent joined with the V3 state keyed on `(ledger_seq, claim id)`. The item's `triggers` are its X1-X6 triggers, and the item's `final_gold_seq` is its gold label id. `GET /v3/items/{item_id}` and the gold export carry both. The ledger record is never rewritten.
26. **The stop's measure.** Plan L reads "queue age above SLO for two days"; plan I reads "queue age p90 alert [Risk R-40]". **Resolution:**
    - The stop measures the age of the oldest open item at every hourly sample (PD-37).
    - The oldest age is never below the p90, so this is strictly more conservative. Newly enqueued items (learner flags, the 5% draw) cannot dilute it.
    - The SLIs report the p90 (the alert's measure) and the oldest age (4.11).
27. **Plan H "Reviewers see public-corpus spans only"** against an item whose claim text is hidden (a span that is not public or not quotable under D-31, or a record that does not parse). **Resolution:** such an item is `reviewable: false`. It cannot be claimed or adjudicated (`not_reviewable`), so no label is written blind. It stays queued and held (plan J).
28. **Plan 16.1 "the X6 auditor MUST NOT audit their own change [Risk R-35]"** against keyed digests that rotate with the guest secret (M6). **Resolution:** the independence and apply rules read the user-keyed round records in `v3_claims` (4.5), never a digest. A rotation therefore never readmits a reviewer to an item they reviewed. The gold rows keep `reviewer_digest` as evidence.
29. **X1's "a correction cycle that listed it"** against the alignment item's re-render, which lists the claims its rendering showed (M2), not claims that drew an objection. **Resolution:** X1 reads the claim-loop corrections only: a correction whose `cycle` is at most the judged verdicts' own `cycle` (the claim loop's last tally). An alignment re-render comes after it, numbered higher, and is never read as an objection.
30. **Reviewability needs the corpus in force.** `claim_item` and `adjudicate` refuse an unreviewable item (conflict 27), which needs the span registry and the corpus registry. **Resolution:** both take `store` and `corpus_registry` keywords (default: the process course store and the settings' corpus registry), as `item_view` does; the routes pass the process store and registry, and the residual report passes the capture configuration's.
31. **AC-6-3 through `GET /v3/queue` over the shared database**, where another test's items (synthetic deliveries share one claim set, so their exposure grows) can outrank the seeded ones past the page limit. **Resolution:** the AC-6-3 route check reads a fresh database through a `get_db` override, as every queue-route test does (M17); the security events stay in the shared database.

---

## 2. Architecture

```
ledger rows (append-only, Phase 3) ──► V3 scan (worker `scan`, or POST /v3/scan; advisory lock; cursor = max v3_scans.to_seq)
   per record, in seq order:
     validate with ENTRY_SCHEMAS[entry_schema]          (unknown schema or invalid: counted `unparsed`; drawn if a delivery)
     model sightings (votes, generator, checker; registry members once per scan) ─► x5_model_changes ─► v3_events, v3_model_versions
     triggers.evaluate(entry):  X1 claims, X2 claims, X4 response, queue reasons per claim  ─► ItemSpecs
     delivery? ─► draw_trigger(seed, response_id, x5_active) ─► v3_draws (PK ledger_seq: exactly once; claim-set key) ─► X6 | X5 response ItemSpec
               ─► refresh_exposure (an item already on the record, an X3 flag's, gets the record's full exposure)
     ItemSpecs ─► queue.upsert_item (row locked; merge into the item of (ledger_seq, claim_key); priority = severity × exposure × (1 − K))
   append v3_scans row
learner flag (POST /v3/flags, own tutor turn; development only) ─► v3_flags (user_id) ─► X3 response item on the turn's legacy record (F_i = 0)
CUSUM alarm (Phase 9) ─► events.record_cusum_alarm ─► v3_events (X5 window: the next 1500 learner deliveries at 1/5)
reviewer (role `reviewer`; admitted in development only while D-18 is open)
   GET /v3/queue ─► claim a reviewable item (30-min lease; v3_claims row per round) ─► adjudicate (one gold row, hash-chained; no ledger row changes)
        └─ double review (1/10 of items): a second round by another reviewer; disagreement: a third round by a third ─► adjudicated
   apply (a reviewer with no round on the item) ─► applied (recalibration input export; releases nothing; Phase 7 decides, DI-93)
holds.withheld_claim_ids(entry)   pure: tier-1 X1 claims ∪ claims the record withholds with a V3 intent; nothing releases them
stop.stop_state(queue history)    the oldest open item older than the SLO at every hourly sample of the last 48 h
   └─ V2 track (shadow pipeline; read through the pipeline's own database): tier-1 response ─► pre_verified_only path (no call; withheld; abstain and queue under `on`)
```

**Where each AC is enforced**

| AC | Mechanism | Primary tests (13.1) |
|---|---|---|
| AC-6-1 | `triggers.x1_claims` and `x1_held_claims`; `critical_for` over v5 `v3.critical_claims`; the runner's sticky hold of a critical tier-1 claim; `holds.withheld_claim_ids`; item `held` | 1, 2, 23 |
| AC-6-2 | `draw.draw_trigger` (seeded, deterministic); `v3_draws` PK `ledger_seq` and its append-only trigger | 3; `test_v3_draw.py` |
| AC-6-3 | `priority.priority` (exact rationals); `priority.exposure_for` (claim-set key); `queue.list_queue` order | 4; `test_v3_priority.py` |
| AC-6-4 | `queue.adjudicate` (one transaction: one gold row, no ledger write); the gold chain triggers; `UNIQUE (item_id, review_round)` | 5; `test_v3_gold_store.py` |
| AC-6-5 | `residual.wilson_upper` over X6-audited answer deliveries | 6; the residual report |
| AC-6-6 | `feedback.record_flag`; `feedback.f_i`; no ledger write | 7 |
| AC-6-7 | `require_reviewer` (role first, then the D-18 gate); `authz.denied` | 8 |

---

## 3. Data shapes

The Python blocks below are valid Python (`...` bodies), so the section-3 doc test (13.1 test 27) parses them and compares each class's fields with `apps/api/app/services/v3/contracts.py` (3.1) and with the modules 3.2 names, and each 3.3 assignment with `rules.py`. `Contract` is `tutor_pipeline.contracts.Contract` (frozen, `extra="forbid"`). `CLAIM_ID`, `SPAN_ID` and `HEX64` are that module's patterns.

### 3.1 V3 contracts (`apps/api/app/services/v3/contracts.py`)

```python
ITEM_ID = r"^v3i-[0-9a-f]{24}$"
DIGEST = r"^[0-9a-f]{32}$"
CLIENT_KEY = r"^[A-Za-z0-9_-]{8,64}$"
UTC_TIME = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$"
Trigger = Literal["X1", "X2", "X3", "X4", "X5", "X6"]
QueueReason = Literal["v1_3_flag", "v1_8_misconception", "v2_correction_exhausted", "v2_degraded_withheld"]


class ClaimLabel(Contract):
    claim_id: str = Field(pattern=CLAIM_ID)
    verdict: Literal["SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_INFO"]
    ehmf_type: Literal["A", "B", "C", "D", "E"] | None = None


class AdjudicationRequest(Contract):
    client_key: str = Field(pattern=CLIENT_KEY)
    claim_labels: tuple[ClaimLabel, ...] = Field(default=(), max_length=20)
    abstention_label: Literal["correct", "missed_answer"] | None = None


class ApplyRequest(Contract):
    client_key: str = Field(pattern=CLIENT_KEY)


class FlagRequest(Contract):
    response_id: str = Field(pattern=r"^turn-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class GoldClaim(Contract):
    claim_id: str = Field(pattern=CLAIM_ID)
    span_ids: tuple[str, ...] = Field(min_length=1, max_length=12)
    text_sha256: str = Field(pattern=HEX64)


class GoldLabel(Contract):
    gold_schema: Literal["v3-gold-label-v1"] = "v3-gold-label-v1"
    item_id: str = Field(pattern=ITEM_ID)
    review_round: int = Field(ge=1, le=3)
    subject: Literal["claim", "response"]
    triggers: tuple[Trigger, ...] = Field(max_length=6)
    reasons: tuple[QueueReason, ...] = Field(max_length=4)
    ledger_seq: int = Field(ge=1)
    response_digest: str = Field(pattern=DIGEST)
    delivery_digest: str = Field(pattern=DIGEST)
    delivered_answer: bool
    claims: tuple[GoldClaim, ...] = Field(max_length=20)
    claim_labels: tuple[ClaimLabel, ...] = Field(max_length=20)
    abstention_label: Literal["correct", "missed_answer"] | None
    residual_error: bool
    reviewer_digest: str = Field(pattern=DIGEST)
    client_key: str = Field(pattern=CLIENT_KEY)
    package_version: str
    package_sha256: str = Field(pattern=HEX64)
    adjudicated_at: str = Field(pattern=UTC_TIME)


class CusumAlarm(Contract):
    alarm_schema: Literal["cusum-alarm-v1"] = "cusum-alarm-v1"
    stream: str = Field(pattern=r"^[a-z0-9][a-z0-9:._-]{0,95}$")
    p0: float = Field(gt=0, lt=1)
    p1: float = Field(gt=0, lt=1)
    h: float = Field(gt=0)
    statistic: float = Field(ge=0)
    observations: int = Field(ge=1)
    raised_at: str = Field(pattern=UTC_TIME)
    source: Literal["phase9-cusum", "synthetic-test"]


class SpanView(Contract):
    span_id: str = Field(pattern=SPAN_ID)
    shown: bool
    text: str | None


class ClaimView(Contract):
    claim_id: str = Field(pattern=CLAIM_ID)
    text: str | None
    spans: tuple[SpanView, ...] = Field(min_length=1, max_length=12)


class QueueItemView(Contract):
    item_id: str = Field(pattern=ITEM_ID)
    subject: Literal["claim", "response"]
    record_kind: Literal["delivery", "shadow"]
    decision: Literal["answer", "abstain"]
    triggers: tuple[Trigger, ...]
    reasons: tuple[QueueReason, ...]
    held: bool
    state: Literal["queued", "claimed", "adjudicated", "applied"]
    review_round: int = Field(ge=1, le=3)
    double_review: bool
    reviewable: bool
    enqueued_at: str = Field(pattern=UTC_TIME)
    age_s: int = Field(ge=0)
    response_digest: str = Field(pattern=DIGEST)
    claims: tuple[ClaimView, ...] = Field(max_length=20)
```

**Validators.** Each failure raises `ValueError`.
- `ClaimLabel`: `(ehmf_type is None) == (verdict == "SUPPORTED")`.
- `AdjudicationRequest`: claim labels are sorted by `claim_id` and unique.
- `GoldLabel`:
  - triggers and reasons are sorted and unique, and their union is non-empty;
  - `claim_labels`' claim ids equal `claims`' claim ids, in the same order;
  - `subject == "claim"` implies exactly one claim and `abstention_label is None`;
  - `residual_error == (delivered_answer and any(label.verdict != "SUPPORTED" for label in claim_labels))`.
- `CusumAlarm`: `p0 < p1` and `statistic >= h`, because an alarm is the statistic crossing h.
- `SpanView`: `text` is set iff `shown`.
- `ClaimView`: `text is None` when any span is not shown.
- `QueueItemView`: `reviewable` implies every claim's `text` is set.
- `V3_SCHEMA_MODELS = {"V3GoldLabel": GoldLabel, "V3CusumAlarm": CusumAlarm}` names the two contracts package v5 pins (5.1).

The reviewer's view holds no severity, exposure, support share or priority (4.14). The queue's order carries the rank.

### 3.2 Runtime types (dataclasses; `triggers.py`, `scan.py`, `stop.py`)

```python
@dataclass(frozen=True)
class ItemSpec:
    claim_key: str                      # a claim id, or "" for the response
    subject: Literal["claim", "response"]
    triggers: frozenset[str]
    reasons: frozenset[str]
    ehmf_types: frozenset[str]          # the types severity reads (4.3)
    k: Fraction
    held: bool                          # an X1 claim at tier 1 (x1_held_claims)


@dataclass(frozen=True)
class ModelChange:
    model_key: str                      # "verifier:<model_id>", "generator:<generator_id>", "checker:V1.3"
    from_version: str
    to_version: str


@dataclass(frozen=True)
class RecordTriggers:
    record_kind: Literal["delivery", "shadow"]
    items: tuple[ItemSpec, ...]
    sightings: tuple[tuple[str, str], ...]    # sorted (model_key, model_version)


@dataclass(frozen=True)
class ScanResult:
    from_seq: int
    to_seq: int
    records: int
    deliveries: int
    drawn_x6: int
    drawn_x5: int
    items_created: int
    items_updated: int
    model_changes: int
    unparsed: int
    done: bool                          # no record past to_seq when the scan ended


@dataclass(frozen=True)
class StopState:
    active: bool
    reason: Literal["clear", "queue_age", "unreadable"]
    window_s: int
    slo_s: int
    samples: int
    open_items: int
    oldest_age_s: int
```

`queue.py` raises `V3NotFound` (a missing item, or a flag's turn that is missing or someone else's), `V3Busy` (a write the database kept refusing within the attempts, HTTP 503) and `V3Conflict(reason)`. The reason is one of `CONFLICTS = ("claimed_by_another", "not_claimed", "lease_expired", "independent_review_required", "already_adjudicated", "not_adjudicated", "adjudicator_cannot_apply", "labels_do_not_match_subject", "not_recorded_yet", "not_reviewable")`. `queue.Lease(item_id, review_round, lease_expires_at)` is a claim's result, `queue.Adjudicated(gold_seq, record_hash, duplicate, review_round, state)` an adjudication's and `queue.Applied(final_gold_seq, duplicate)` an apply's. `__init__.V3Off` is raised when the mode is off (`v3.require_on`).

### 3.3 The vocabulary (`apps/api/app/services/v3/rules.py`, standard library only)

```python
V3_VERSION = "v3-audit-v1"
TRIGGERS = ("X1", "X2", "X3", "X4", "X5", "X6")
TRIGGER_REGISTRY_VERSION = "x-triggers-v1"
TRIGGER_RULES = {"X1": "critical-claim-objection-v1", "X2": "v2-exhausted-type-a-b-v1", "X3": "learner-flag-f0-v1",
                 "X4": "v1-5-margin-mark-v1", "X5": "model-version-change-or-cusum-alarm-v1", "X6": "seeded-sha256-bernoulli-v1"}
X1_TIERS = (1, 2, 3)                              # X1 fires at every tier (AC-5-4; conflict 1)
X1_WITHHOLD_TIER = 1                              # and holds at tier 1 only (task 1 "withheld at tier 1")
V3_COUNTED = ("X1", "X2", "X3", "X4")            # plan 15.3 (PD-37)
QUEUE_REASONS = ("v1_3_flag", "v1_8_misconception", "v2_correction_exhausted", "v2_degraded_withheld")
X2_TYPES = ("A", "B")
SUBJECTS = ("claim", "response")
STORED_STATES = ("queued", "adjudicated", "applied")      # "claimed" = queued with a live lease for the current round
WORKFLOW_STATES = ("queued", "claimed", "adjudicated", "applied")
VERDICTS = ("SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_INFO")
EHMF_TYPES = ("A", "B", "C", "D", "E")
ABSTENTION_LABELS = ("correct", "missed_answer")
MAX_ROUNDS = 3
DRAW_RULE = "seeded-sha256-bernoulli-v1"
DRAW_PURPOSE, DOUBLE_REVIEW_PURPOSE = "x6-draw-v1", "double-review-v1"
DELIVERIES = ("delivered", "legacy")
PRIORITY_RULE, EXPOSURE_RULE, K_RULE = "severity-exposure-one-minus-k-v1", "learner-deliveries-of-claim-set-v1", "panel-support-share-v1"
CLAIM_SET_KEY_RULE = "sorted-claim-ids-sha256-v1"
TIE_BREAK = ("enqueued_at", "item_id")
PLAN_SEVERITY = {"A": "1.0", "B": "1.0", "C": "0.6", "D": "0.6", "E": "0.4"}   # plan L682, as decimal strings (exact Fractions)
GOLD_SCHEMA, GOLD_CHAIN = "v3-gold-label-v1", "v3-gold"
GOLD_RECORD_HASH_RULE = "sha256(canonical{chain,seq,created_at,prev_hash,entry_sha256})-v1"
GOLD_GENESIS = "0" * 64
STOP_POLICY = "pre_verified_only"
STOP_MEASURE = "oldest-open-item-age-v1"
REVIEWER_ROLE = "reviewer"
```

---

## 4. Algorithms

### 4.1 Triggers (`v3/triggers.py`; pure over a validated ledger entry; one unit test per trigger, plan J)

- **X1 `x1_claims(entry) -> frozenset[str]`.**
  - A claim fires when its recorded `v2` is set with `critical is True`, at any tier (`X1_TIERS`, conflict 1), and it drew at least one objection in the response: `v2.objections >= 1` on its final verdict, or its id is in `verification.v2.corrections[i].failed_claim_ids` for a claim-loop cycle `i` (a correction whose `cycle` is at most the judged verdicts' `cycle`; conflict 29).
  - `x1_held_claims(entry)` is the X1 claims whose `v2.tier == X1_WITHHOLD_TIER` (1): the claims X1 withholds ("withheld at tier 1"). An X1 claim at tier 2 or 3 is queued and counted, not held.
  - Records with no V2 verdict (v1 and v2 records, legacy) never fire. A V1.3 flag is not a verifier objection. A record that ends in a V1 decision after a correction cycle carries no V2 verdict (Phase 5 rule 1). No claim of such a record is delivered, so X1 does not fire there.
- **X2 `x2_claims(entry)`.** A claim fires when its `v3.escalation == "X2"` and the EHMF types of its final verdict's objecting family verdicts (`voting.objection_types` over `v2.votes`, imported inside the function) include A or B.
- **X3 `x3_fires(flags: int) -> bool`** is `flags >= 1`, over the record's stored flags: `feedback.record_flag` asks it after storing a flag (4.7).
- **X4 `x4_fires(entry, *, x4_margin: Mapping[str, float]) -> bool`.**
  - With `entry.verification` (v2 or v3): any `verification.checks` entry with `check_id == "V1.5"` and `reason_code == "near_miss"`. This is the V1.5 mark, and is exactly when the record's intents carry `x4_margin` (a test asserts the agreement).
  - Otherwise (legacy and v1 records): `sufficiency = entry.retrieval.sufficiency`. The trigger fires when it is not `None`, its gate is in `x4_margin`, and `check_v1_5(sufficiency, x4_margin=x4_margin[gate]).reason_code == "near_miss"`, reusing Phase 4's function.
  - `x4_margin` is the package in force's `v1.x4_margin`.
- **X5 sightings and changes.**
  - `record_sightings(entry)` is the sorted set of:
    - `("verifier:" + vote.verifier_model_id, vote.verifier_model_version)` for every V2 claim vote and alignment vote;
    - `("generator:" + versions.generator_id, provenance.generator_model_id)` when `generator_id` is set;
    - `("checker:V1.3", provenance.v1_3_checker_model_id)` when that field exists and is set.
  - `registry_sightings(registry)` is `("verifier:" + spec.model_id, spec.model_version)` for `registry.verifiers()`.
  - `x5_model_changes(known: Mapping[str, str], sightings) -> tuple[ModelChange, ...]` returns a change for each sighting whose key is known with another version. An unknown key is a first sighting, not a change. While the store holds no row at all, every sighting is a baseline. Versions that alternate (two registries during a rolling deploy) give one change per alternation: more audits, never fewer. The scan passes each sighting through it (`scan._sightings`, 4.4), so this function is the rule the scan runs.
  - `x5_active(windows, seq) -> bool` is true when any open window `(from_seq, remaining)` has `from_seq < seq` and `remaining > 0`.
- **X6 (4.2).**
- **Queue reasons `queue_reasons(verdict) -> frozenset[str]`** reads the verdict's own `v3` intent and keeps each reason in `QUEUE_REASONS` that it carries: `v1_3_flag`, `v1_8_misconception`, `v2_degraded_withheld` and `v2_correction_exhausted`.
  - Phase 5's "after Phase 5, flags route to V2" holds under `MODEL_GATEWAY=on`, where the V2 aggregate drops `v1_3_flag` from the intent once a vote completes, so such a claim is not queued for it. A V2-shadow record keeps Phase 4's finals and intents (Phase 5 4.10), so a V1.3-flagged claim it withholds (D-20: "withheld ... and queued for V3") is queued, as `holds.withheld_claim_ids` says it is held.
  - `x4_margin` is the X4 response item, not a claim reason.
- **`evaluate(entry, *, x4_margin) -> RecordTriggers`.**
  - `record_kind` is `"shadow"` for a shadow record, else `"delivery"`.
  - For each verdict, it emits a claim `ItemSpec` when `triggers := ({"X1"} if in x1) | ({"X2"} if in x2)` or `reasons` is non-empty. Its `ehmf_types` are `claim_types(verdict)`, its `k` is `support_share(verdict.v2)` and `held` is whether the claim is in `x1_held_claims(entry)`.
  - When `x4_fires`, it emits a response `ItemSpec` with `triggers {"X4"}`, `ehmf_types = response_types(entry) | {"A"}` (V1.5's EHMF) and `k = response_k(entry)`.
  - X3, X5 and X6 response items come from 4.7 and 4.2 (`response_spec(entry, trigger)`) and merge into the same `(ledger_seq, "")` item.
- **Type helpers.**
  - `claim_types(verdict)` is the objecting family verdicts' EHMF types, plus the `ehmf_types` of every `verdict.v1` result whose outcome is not `pass`, except a V1.7 `conflict_disclosed` result (weight 0: plan Phase 7 A "D 0.6 (0 when disclosed)").
  - `response_types(entry)` is the union over verdicts, plus non-`pass` response-level `verification.checks`, with the same exception.

### 4.2 The draw (`v3/draw.py`; AC-6-2, PD-35)

```python
def u64(purpose: str, seed: str, key: str) -> int:            # int.from_bytes(sha256(f"{purpose}|{seed}|{key}".encode()).digest()[:8], "big")
    ...


def bernoulli(purpose: str, seed: str, key: str, rate: Fraction) -> bool:   # u64(...) * rate.denominator < rate.numerator * 2**64
    ...


def draw_trigger(seed: str, response_id: str, *, base: Fraction, elevated: Fraction, x5_active: bool) -> str | None:
    ...   # u < base -> "X6"; else x5_active and u < elevated -> "X5"; else None   (u = u64(DRAW_PURPOSE, seed, response_id))


def claim_set_key(entry: Any) -> str | None:
    ...   # sha256("\n".join(sorted({claim.claim_id for claim in entry.claims}))) for an answer; None for an abstention
```

- **Integers only.** No float takes part in the decision (M9's boundary). The 1/20 set is a subset of the 1/5 set, so raising the rate never undraws a delivery.
- **Each delivery is considered exactly once**, at the first scan that reads its record:
  - `v3_draws` has PK `ledger_seq` and is inserted with ON CONFLICT DO NOTHING;
  - its append-only trigger refuses UPDATE and DELETE;
  - a re-scan or a later X5 window never redraws it;
  - the row stores the rate used, `x5_active` and the record's claim-set key (a parsed answer; null otherwise).
- **Replay.** The draw depends only on `(seed, response_id, rate)`. A same-seed replay over the same deliveries draws the same ids.
- **Pre-ledger deliveries** have no record and are never drawn (4.11).

### 4.3 Priority (`v3/priority.py`; AC-6-3, PD-34)

```python
def severity(types: Iterable[str], weights: Mapping[str, Fraction]) -> Fraction: ...   # max(weights[t] for t in types) if types else weights["unknown"]
def support_share(v2: Any) -> Fraction: ...       # (len(members) - objections) / len(members); 0 when v2 is None, members empty or outcome "withheld"
def response_k(entry: Any) -> Fraction: ...       # mean of support_share over verdicts with a non-zero-member v2; 0 when none
def exposure_for(db: Session, record: Any, key: str | None) -> int: ...
def priority(severity: Fraction, exposure: int, k: Fraction) -> Fraction: ...           # severity * exposure * (1 - k)
```

- `exposure_for` is 1 for a shadow record, an abstention and a record whose key is None.
- Otherwise it is `max(1, COUNT(*))` of `v3_draws` rows with `claim_set_key = key` and `ledger_seq <= record.seq` (index `ix_v3_draws_claim_set_key`).
- The scan inserts a record's draw before its items, so the count includes the record itself. The scan considers records in seq order, so once it has drawn a record every earlier delivery has been considered and the count is final.
- An item is created with `exposure_for` at that moment. An X3 item created before the scan drew its record counts only the deliveries considered so far (at least 1), so the scan, right after it inserts the record's draw, calls `queue.refresh_exposure(db, record_row=, entry=, package=)`: every item of the record whose stored exposure is below the record's count is raised to it, with its priority recomputed from its types and K. The final exposure and priority are therefore the record's, whichever path created the item first.
- Items store `float(priority)`, `float(severity)` and `float(k)`. With the small denominators these rules give (weights in fifths, a share's members at most 3, a mean over at most 20 claims), distinct exact priorities never collide as floats; a merge recovers K exactly (`Fraction(k).limit_denominator(10**6)`).
- `list_queue` orders by `priority DESC, enqueued_at ASC, item_id ASC` (`TIE_BREAK`). A merge recomputes severity from the union of types; K and exposure belong to the record (exposure changes only through `refresh_exposure`).

### 4.4 The scan (`v3/scan.py`)

```python
def run_scan(*, settings: Settings, package: ConfigPackage, session_factory=SessionLocal, now: datetime | None = None, limit: int = 500) -> ScanResult:
    ...
```

The scan raises `V3Off` when `v3.mode(...) == "off"`. One transaction (`_scan_once`) does the following; on SQLite a "database is locked" error (two writers that both began deferred transactions) retries the whole transaction, at most `queue.ATTEMPTS` (5) times, then raises `V3Busy`:
1. On PostgreSQL, `SELECT pg_advisory_xact_lock(V3_SCAN_LOCK_KEY)` (`7_401_206`).
2. Read `cursor = COALESCE(MAX(v3_scans.to_seq), 0)` and up to `limit` `response_ledger` rows with `seq > cursor`, ordered by seq.
3. Load `known`: the latest `v3_model_versions` row per `model_key`, by id.
4. Load the open X5 windows: each `v3_events` row gives `remaining = window_deliveries - (number of v3_draws rows with ledger_seq > from_ledger_seq)`.
5. Compare the registry's sightings (`registry_for(package, settings)`). `_sightings` passes each sighting whose version differs from the known one through `triggers.x5_model_changes`: each change inserts a `model_change` event with `from_ledger_seq = cursor` and the package's window, plus a `v3_model_versions` row (source `registry`). An unknown key inserts a row with no event.
6. For each row, in seq order:
   1. Validate it with `ENTRY_SCHEMAS[row.entry_schema].model_validate_json(row.entry)`. An unknown `entry_schema` or a validation failure counts `unparsed`, skips the triggers, and still draws a delivery (with a null claim-set key).
   2. Record the sightings (`from_ledger_seq = row.seq`; source `record`).
   3. `evaluate` the entry.
   4. If `row.delivery in DELIVERIES`:
      - `x5 = x5_active(windows, row.seq)`, and the rate is `x5_rate if x5 else base`;
      - insert the `v3_draws` row;
      - if it was inserted and `x5` is true, decrement every window counted for it (in memory);
      - when it is drawn, add a response `ItemSpec` for `"X6"`/`"X5"` (`k = response_k`, types `response_types`);
      - `queue.refresh_exposure` raises any item already on the record to the record's exposure (4.3).
   5. Upsert each spec (4.5).
7. Insert the `v3_scans` row (`from_seq`, `to_seq` = the last row read or the cursor, the counts, and the package version and sha256), commit, and log `v3.scan`.

**Write order** is model versions and events, then draws, then queue items, then the scan row. This is the guard's lock order (8). `done` is false when the batch was full. `scan_until_done(...)` repeats `run_scan` until `done` (the worker's `--until-done`, the residual report).

### 4.5 Queue and workflow (`v3/queue.py`; plan task 3; PD-36)

**Item identity.**
- `item_id_for(ledger_seq, claim_key) = "v3i-" + sha256(f"{ledger_seq}|{claim_key}")[:24]`, deterministic.
- `upsert_item(db, *, record_row, spec, entry, package, now) -> tuple[str, bool]` inserts a new item (INSERT ... ON CONFLICT DO NOTHING on the item id):
  - `state "queued"`, `review_round 1`;
  - `double_review = bernoulli(DOUBLE_REVIEW_PURPOSE, seed, item_id, 1/10)`;
  - `response_digest = keyed_digest(record.response_id, "v3-response")`;
  - severity, exposure, K, priority, `held`, triggers, reasons and types; the package version and sha256.
- An existing item is read with `with_for_update()` on PostgreSQL. It gets the unions of triggers, reasons, types and `held`, with severity and priority recomputed. The UPDATE names only those columns, never `state`, `review_round`, `closed_at` or `final_gold_seq`, so a concurrent adjudication is never undone.
- On an item whose state is not `queued`, the triggers and reasons are still recorded. The item is not reopened, and `v3.trigger_after_close` is logged.

**Reviewability** (`reviewable(item, entry, *, store, corpus_registry)`). An item is `reviewable` when the following hold:
- its subject record parses and holds the item's claim;
- every claim it covers is shown, which means every span is public and quotable (4.14);
- a response item on an abstention with no claims is reviewable.

An item that is not reviewable cannot be claimed or adjudicated (`not_reviewable`, HTTP 409), so it stays queued and its holds stay in force. `claim_item` and `adjudicate` take `store` and `corpus_registry` keywords, defaulting to the process course store and the settings' corpus registry (conflict 30).

**Rounds and leases (`v3_claims`, user-keyed).** One row per item and round: `user_id`, `claimed_at`, `lease_expires_at` and `adjudicated_at` (null while the row is a lease). `UNIQUE (item_id, review_round)`.

`claim_item(db, item_id, *, user_id, now, package, store=None, corpus_registry=None) -> Lease` runs in one transaction. On PostgreSQL the item row is read `with_for_update()`.
- The item's state must be `queued`; otherwise `already_adjudicated`.
- The item must be reviewable; otherwise `not_reviewable`.
- A row of the item with `adjudicated_at` set and this `user_id` is `independent_review_required`.
- For the current round's row:
  - a live lease held by another user is `claimed_by_another`;
  - the holder's own live lease is returned (idempotent);
  - an expired lease is deleted.
- Otherwise a row is inserted: `review_round` = the item's round, and `lease_expires_at = now + lease_s`.
- An IntegrityError (two claims of one round) retries the transaction, and the retry sees the other lease.
- "Claimed" is derived (`workflow_state`): queued with a live lease for the current round. An expired lease puts the item back to `queued` with no write.

**Adjudication.** `adjudicate(db, item_id, request: AdjudicationRequest, *, user_id, now, package, store=None, corpus_registry=None) -> Adjudicated` runs in one transaction, with the item row locked:
1. A gold row of this item whose entry has this `client_key`, for a round whose `v3_claims` row is this user's, is returned with `duplicate=True`.
2. The item's state must be `queued` (`already_adjudicated`). The user's lease for the current round must exist (`not_claimed`) and be live (`lease_expired`).
3. The subject record is read by `ledger_seq` and validated. The item must be reviewable (`not_reviewable`). For a claim item, the labels must be exactly that one claim. For a response item, they must be every recorded claim, and `abstention_label` is set iff the record's `decision == "abstain"`. Otherwise `labels_do_not_match_subject` (HTTP 422).
4. The `GoldLabel` is built:
   - `delivered_answer = record.delivery in DELIVERIES and record.decision == "answer"`;
   - `delivery_digest = keyed_digest(<the delivery's response id>, "v3-response")`, the delivery being the record itself, or the record named by its `shadowed_response_id`;
   - `claims` carry `text_sha256 = sha256(claim.text)`;
   - `adjudicated_at` is the ISO UTC time;
   - plus `reviewer_digest = keyed_digest(user_id, "v3-reviewer")`, the client key and the package.
5. `gold.append_gold(db, entry, now=now)` runs (4.6), the round's `v3_claims` row gets `adjudicated_at = now` (it is kept as the round's record), and the state moves on:
   - the first round without double review: `adjudicated`;
   - the first round with double review: the second round, `queued`;
   - a second round that agrees with the first (equal `claim_labels` and `abstention_label`): `adjudicated`;
   - a second round that disagrees: the third round, `queued`;
   - the third round: `adjudicated`.
   - When the item becomes `adjudicated`, `closed_at = now` and `final_gold_seq` = this row.
6. The transaction commits, and `v3.gold_appended` and `v3.adjudicated` are logged.

An IntegrityError, a serialization failure or a deadlock (40001, 40P01), or a SQLite "database is locked" or "busy" error (`queue.sqlite_busy`: no SQLSTATE; two writers that both began deferred transactions, as two reviewers claiming at once do), retries the whole transaction, at most 5 attempts (`ATTEMPTS`). Every V3 mutation retries this way (claim, adjudicate, apply, the flag). When the attempts are spent it raises `V3Busy`, which the routes answer 503 (`{"detail": "busy"}`, `Retry-After: 1`). `UNIQUE (item_id, review_round)` on the gold store refuses a second row for a round.

**Apply.** `apply_item(db, item_id, request: ApplyRequest, *, user_id, now) -> Applied(final_gold_seq, duplicate)`, with the item row locked:
- Already applied with the same `client_key`: idempotent, `duplicate` true; it writes nothing and logs no `v3.applied` (as a duplicate adjudication logs no `v3.adjudicated`), so the counters count distinct actions.
- The state must be `adjudicated` (`not_adjudicated`).
- A user with an adjudicated `v3_claims` row on the item gets `adjudicator_cannot_apply`.
- Otherwise: `state = "applied"`, `applied_at = now`, `applied_by_digest`, `applied_client_key = request.client_key`. It writes no gold row and no ledger row, and changes no hold.

**Listing.** `list_queue(db, *, state=None, limit=50, now, item_ids=None)` returns rows in queue order; `state` None is queued with claimed.

**Independence never reads a digest.** Keyed digests rotate with the guest secret (M6). The rules above compare `user_id` values in `v3_claims`, so a rotation readmits no one. Erasing a reviewer removes their rows. Their live leases free their items, and their adjudicated rounds leave the gold rows' digests as the record (DI-99).

**Blind review.** Item views never show votes, objection types, support shares, severities, priorities, finals or another round's labels (4.14). They do show the item's triggers and reasons, which say why it is queued and so disclose that an objection exists (X1, X2, `v2_correction_exhausted`) or that V1 flagged it, but never which family objected, a vote's verdict or the EHMF type it named. X2's rule implies only that some objection was of type A or B; the console's trigger labels do not spell even that out (11).

### 4.6 Gold store (`v3/gold.py`; E3, R-22, AuditEvent)

```python
def gold_hash_for(*, seq: int, created_at: datetime, prev_hash: str, entry_sha256: str) -> str: ...
#   sha256(canonical {"chain": "v3-gold", "seq", "created_at" (ISO UTC, microseconds, Z), "prev_hash", "entry_sha256"})
def append_gold(db: Session, entry: GoldLabel, *, now: datetime) -> tuple[int, str]: ...     # inside the caller's transaction
def verify_gold_store(db: Session, *, expected_head: tuple[int, str] | None = None) -> GoldCheck: ...
def export_gold(db: Session, path: Path, *, applied_only: bool = True) -> int: ...
```

**Append.**
- On PostgreSQL, `pg_advisory_xact_lock(V3_GOLD_LOCK_KEY)` (`7_401_207`) runs first.
- It reads the last row, sets `seq = last + 1` and `prev_hash = last.record_hash` (or `GOLD_GENESIS`), and inserts with these columns:
  - `entry` = the canonical JSON (`ledger_canonical`) and `entry_sha256`;
  - `actor_role "reviewer"`, `action "adjudicate"`, `reviewer_digest`, `review_round` and `record_hash`.
- The row carries plan 7.4's AuditEvent fields: `prev_hash`, `hash`, `actor_role`, `action`, `payload_digest` = `entry_sha256`.
- After commit the caller logs `v3.gold_appended` with `seq` and `record_hash`, the off-database copy.

**Verify.** The chain is walked in seq order. A problem is recorded for each of:
- the first seq is not 1, or it does not chain from genesis;
- a gap;
- a broken `prev_hash`;
- an `entry_sha256` or `record_hash` mismatch;
- a non-canonical entry, or one that fails `GoldLabel`, or columns that disagree with it;
- the expected head is not reached.

**Export.** One JSON line per row (`seq`, `record_hash`, `entry`, `created_at`), the applied items' final rows only unless `--all`. The path must lie outside the application tree (`apps/api/app`) and outside the repository checkout (`refused_export_roots`: the first parent of `gold.py` holding a `.git` entry; the image has none), so a gold label cannot be written where it could be committed (plan L627-628, conflict 2); a refusal writes nothing. No import or restore path exists: gold rows are written by adjudication only. The export holds `ledger_seq` and keyed digests of response ids (pseudonymous, learner-linked), so it is kept under the runbook's handling rule (15).

### 4.7 Learner flags and F_i (`v3/feedback.py`; AC-6-6, invariant 5, PD-39)

```python
def record_flag(db: Session, *, user_id: str, response_id: str, settings: Settings, package: ConfigPackage, now: datetime) -> tuple[int, bool]: ...
#   returns (ledger_seq, duplicate)
def f_i(db: Session, ledger_seq: int) -> float | None: ...   # 0.0 when an item on that record has trigger X3, else None
```

`record_flag` raises `V3Off` when the mode is off or the environment is not development (the flag intake is development-only until DI-97, which adds its privacy disclosure).
- The `TutorTurn` must exist and have `user_id == user_id`; otherwise `V3NotFound` (404, the same for missing and other).
- Its legacy ledger record (`response_id` = the turn id) must exist. Without one, `not_recorded_yet` (409) when `turn.ledger_record_expected is True`, else `V3NotFound` (a pre-ledger turn is not auditable).
- An insert into `v3_flags (user_id, ledger_seq, created_at)` hitting `UNIQUE (user_id, ledger_seq)` is a duplicate (no new item trigger).
- Otherwise, once `triggers.x3_fires` holds for the record's stored flags (their count), it upserts the record's response item with trigger `X3` (types from `response_types`, `k = response_k`).
- It writes no ledger row and changes no verdict, and logs `v3.flag_recorded` (`duplicate`; no id).
- F_i survives the learner's erasure, because it lives on the X3 item, which holds no learner id.

### 4.8 X5 events and the CUSUM interface (`v3/events.py`; DI-96)

```python
def record_cusum_alarm(alarm: CusumAlarm, *, settings: Settings, package: ConfigPackage, session_factory=SessionLocal, now: datetime | None = None) -> int: ...
```

- It refuses `source == "synthetic-test"` outside development (`ValueError`).
- It inserts `v3_events(kind "cusum_alarm", payload = canonical JSON of the alarm, from_ledger_seq = the ledger head seq or 0, window_deliveries = package v3 window)` and logs `v3.x5_event` (`kind`, `stream`) at WARNING. It returns the event seq.
- It records the alarm whatever the V3 mode: the next scan applies the window.
- Phase 9 calls it, and Phase 6 tests call it with synthetic alarms.
- `scan.record_model_change` (used by 4.4) inserts a `model_change` event with payload `{model_key, from_version, to_version, source}` and logs `v3.x5_event`.

### 4.9 Holds (`v3/holds.py`; R-b, plan J, plan L)

```python
def withheld_claim_ids(entry: Any) -> frozenset[str]: ...   # x1_held_claims(entry) ∪ {verdict.claim_id | verdict.final == "withhold" and verdict.v3 is not None}
def released(item: Any) -> bool: ...                        # always False in Phase 6 (release is Phase 7 change control, DI-93)
```

Both are pure over the immutable record and independent of the V3 mode and of the queue table. Disabling V3, deleting a queue row (refused by its trigger), an applied label or the passing of time never shrinks the set. They are the API the delivered path must consult (DI-97). Under `on`, the sticky hold (4.13) keeps every tier-1 X1 claim's final away from `deliver`, so the set and the record's finals agree. The holds and the queue agree too: the scan queues every claim the set names (its tier-1 X1 item, or its intent's queue reasons, 4.1), and a test checks it over V2-shadow records.

### 4.10 The stop (`v3/stop.py`; plan L, PD-37)

```python
def stop_state(db: Session, package: ConfigPackage, *, now: datetime) -> StopState: ...
def tier1_withheld(settings: Settings, package: ConfigPackage, *, now: datetime | None = None, session_factory=SessionLocal) -> bool: ...
def reset_stop_cache() -> None: ...
```

**`stop_state`.**
- `W = slo.stop_window_s` (172800), `step = slo.stop_sample_s` (3600), `slo = slo.queue_age_slo_s` (259200).
- It reads `enqueued_at, closed_at` of items with `enqueued_at <= now AND (closed_at IS NULL OR closed_at > now - W)`.
- It takes 49 samples, `s = now - W + i·step` for i = 0..W/step. At sample s the open set is the items with `enqueued_at <= s` and (`closed_at` null or `> s`), and the measure is the age of the oldest open item, `s - min(enqueued_at)` (`STOP_MEASURE`).
- The stop is active (`queue_age`) iff every sample has an open item older than `slo`. `oldest_age_s` is the measure at `now`.

**`tier1_withheld`.**
- False when the package has no v3 block.
- Otherwise it is `stop_state` over `session_factory`'s database, whatever the mode: an aged queue stays a stop after V3 is switched off.
- An exception yields True (`unreadable`) and logs `v3.stop_unread` (WARNING).
- The result is cached per process and per session factory for `slo.stop_refresh_s` (60 s). An active first value, and every change of value, logs `v3.stop` (`active`, `reason`, `window_s`, `slo_s`), at WARNING when active and INFO when clear.
- It never releases anything: its only effect is 4.13.
- `reset_stop_cache` is the test seam, called by the `conftest.py` autouse fixture.

**Development.** With V3 in shadow and no adjudication, the stop trips 120 h after the first item nobody closes (72 h SLO plus 48 h). From then on Phase 5's tier-1 V2 shadow runs pre-verified-only. Items cannot be deleted and `V3_QUEUE=off` does not clear the stop. Adjudicating the open items (the synthetic reviewers) or a fresh database clears it (runbook, 15).

**Outside development** under the `V3_QUEUE=shadow` override (which DI-92's staging audit cycle needs), the scan creates items that nobody can close while D-18 is open: no reviewer is admitted (4.12), and an item citing a span that is not quotable (D-31) is not reviewable. The stop therefore trips 120 h after the first such item and stays; only adjudication by an admitted reviewer clears it, and no operator clear or acknowledge path exists (the stop is "operator policy, set under Decision D-06"; DI-103). It acts on the shadow pipeline's tier 1 only. The runbook warns before the override is set.

### 4.11 Metrics and residual (`v3/metrics.py`, `v3/residual.py`; plan I, AC-6-5; E9)

```python
def wilson_upper(errors: int, audited: int) -> float | None: ...   # citation_migration.wilson_interval(errors, audited)["upper"]; None when audited is 0
def wilson95(errors: int, audited: int) -> dict | None: ...         # {"lower", "upper"}; None when audited is 0
def residual(db: Session, package: ConfigPackage) -> dict: ...
def non_auditable(db: Session, *, now: datetime | None = None) -> dict: ...
def slis(db: Session, package: ConfigPackage, *, now: datetime) -> dict: ...
```

**`residual`** (in `residual.py`, with `wilson_upper`).
- Population: items with `"X6" in triggers` whose `final_gold_seq` entry has `delivered_answer` true.
- `errors` is the count of those whose final label has `residual_error`.
- Result: `{"audited", "errors", "wilson95": {"lower", "upper"} | null, "no_audited_answers", "by_month": [{"month": "YYYY-MM", "audited", "errors", "upper"}], "report_only": true, "evidence_class": "telemetry, not research results (plan Phase 6 H)"}`. The month is the delivery's `v3_draws.delivered_at` (UTC).
- **An empty population is no evidence.** With no audited answer (every deployment today: V3 off, no reviewer, and nothing reviewable under D-31; an audited abstention is not an answer), `wilson95` is null and `no_audited_answers` true, never an upper bound of 0 that would read as a perfect residual. A month bucket exists only with an audited answer, and `wilson_upper` of an empty bucket would be null too. This is the codebase's rule for an empty population (`citation_migration._totals`).

**`non_auditable`.** The learner deliveries without a ledger record, which the scan can never draw, each class apart, from `ledger_coverage(db, since=1970-01-01, now=now)` at its default horizon (conflict 14):
- `tutor_turns`: the pre-ledger tutor turns (plan G), `not_expected_earlier_image`: an image that keeps no ledger created them;
- `qa_before_ledger`: the pre-ledger Q&A answers, the `qa_interactions` count with `created_at < ledger_started_at(db)` (all while the ledger holds no record);
- `ledger_disabled`: turns created while the ledger kill switch was off;
- `lost_records`: `unrecorded`, turns that expected a record and have none past the horizon (lost appends, a Phase 3 plan L stop), which are not pre-ledger deliveries;
- `pending`: turns inside the horizon whose append may still be running; a later read settles them.

**`slis`** reports the following (window = `slo.window_days`):
- `escalation_share {"deliveries", "escalated", "share": "m/n", "max": "1/10", "above_max", "counted": ["X1","X2","X3","X4"], "window_days"}`.
  - Deliveries are the `v3_draws` rows with `delivered_at` in the window: the deliveries the scan has considered.
  - Escalated are the distinct ones of those whose `ledger_seq` is the delivery seq of some item with a counted trigger. An item's delivery seq is its record's seq for a delivery. For a shadow record it is the seq of the record whose `response_id` is its `shadowed_response_id` (unique index), skipped when that record is absent. It is resolved at read time from ledger seqs, never from a digest.
- `queue {"open", "claimed", "age_p90_s", "age_max_s", "slo_s", "above_slo"}` (nearest-rank p90; `above_slo` compares the p90).
- `draws {"considered", "x6", "x5", "x6_rate": "k/n", "non_auditable": non_auditable(db, now=now)}`.
- `double_review {"pairs", "agreeing", "agreement": "k/n"}`.
- `residual` (the block above).
- `gold {"rows", "head_seq", "claims_labelled", "dawid_skene_minimum": 200}`.
- `stop` (`StopState` as a dict).
- `x5 {"active", "events"}`.

Ratios are strings `"k/n"` so no float rounding is published.

### 4.12 The reviewer gate (`apps/api/app/core/reviewer_access.py`; AC-6-7, D-18, PD-38)

```python
def reviewer_admitted(settings: Settings) -> bool: ...
def require_reviewer(request: Request, user: AuthUser = Depends(_require_reviewer_role), settings: Settings = Depends(get_settings)) -> AuthUser: ...
```

1. The role check is the sub-dependency `_require_reviewer_role = require_role("reviewer")`. A caller whose role is not `reviewer` gets its `authz.denied` (`required "role:reviewer"`) and 403 `"Role '<role>' cannot access this resource."`. Its `allowed_roles` (`{"reviewer"}`) is what the authorization matrix reads.
2. `reviewer_admitted(settings)` is true in development. Elsewhere it is true only when the package (`get_config_package(settings)`) has a v3 block whose `v3.reviewer_pool` is not `"unstaffed"`. When it is false, `require_reviewer` records `authz.denied` with `required "reviewer_pool:D-18"` (through `record_security_event`, the same fields as `_record_denial`) and raises 403 `"No reviewer is admitted outside development while the reviewer pool (D-18) is unstaffed."`.

The role check comes first, so a guest gets 403 in every environment. `app/core/auth.py` is not edited (E16).

**The ledger route.** In `GET /ledger/responses/{response_id}`, the reviewer branch requires `user.role in LEDGER_READER_ROLES and reviewer_admitted(settings)`. A reviewer the gate refuses reads as an owner reader, so outside development, while D-18 is open, no reviewer-role caller reads another learner's or a shadow record even under a `LEDGER_ROUTE_ENABLED` override. The behaviour in development is unchanged.

**The closed role set.**
- `authorization.ROLES = ("learner", "instructor", "admin", "reviewer")`. A guest principal has role `learner`.
- `test_authorization.py` asserts that every route's dependency role set is a subset of `ROLES`.
- `LEDGER_READER_ROLES` stays `("reviewer",)`.

### 4.13 V2 integration (`v2_panel/tiers.py`, `v2_panel/track.py`, `v1_checks/runner.py`, `tutor_pipeline/pipeline.py`)

**`critical_for(claim_id, package, *, environment: str) -> bool`.**
- With `package.v3`: membership of `package.v3.critical_registry_for(environment.lower())`, which is that environment's registry, else `default`.
- Without a v3 block: membership of `v2.critical_registry` (v4 behaviour).
- The track passes `environment=self.settings.environment`.

**The sticky hold under `on` (conflict 1).** In `V1Track._run_v2`'s loop:
- After each consult: `held |= {c for c in outcome.failing() if outcome.claims[c].critical and outcome.claims[c].tier == 1}`. `held` accumulates over the response's cycles.
- `pending = failing ∪ {c ∈ held | outcome.claims[c].outcome == "pass"}`. The loop ends early only when `pending` is empty. At `MAX_CORRECTION_CYCLES`, `exhausted = pending`.
- `content` and `presentation` exclude every claim in `held`, so `_correction_plan` never receives a held claim. The cycle's `failed_claim_ids` are `sorted(pending)`, and its `kind` is `"revise"` when `content` or `pending ∩ held` is non-empty (a held claim is re-verified unchanged), else `"re_render"`.
- A held claim is re-verified unchanged and ends in one of two ways:
  - `abstain` with X2 (it is in `exhausted`), even when a later tally passes because its objector left the panel;
  - `withhold` with `v2_degraded_withheld` when its last outcome is V2-withheld (REDUCED-1 or ZERO). A withheld claim is never put in `exhausted`.
- Phase 5's record rules hold unchanged: an X2 escalation follows the last cycle, and a withheld outcome is withheld and queued.

**The stop on tier 1 (conflict 9).**
- `TwoPassPipeline(..., v3_stop: Callable[[], bool] | None = None)` passes `self._v3_stop` to `V2Track(..., v3_stop=...)`. Without an injected callable it is `v3.stop.tier1_withheld(settings, package, session_factory=self.session_factory)`: the stop is read from the pipeline's own database (M19).
- In `V2Track.consult`, at the response's first consult (`self.consults == 1`), after `tier = tier_for(...)`: if `tier == 1` and `self.v3_stop()`, then:
  - `self.kill_switch = "pre_verified_only"`, `self.members = []`, `self.start_members = ()`;
  - log `tutor.v2.v3_stop` (WARNING, `tier`, `policy`) once per response.
- Every claim is then withheld in ZERO with no call. In `on` the record abstains with `v2_kill_switch`; in `shadow` the Phase 4 finals stay (Phase 5 4.10).
- A V2 mode of `off` builds no track and reads no stop.

### 4.14 Reviewer views (`v3/views.py`; plan H, E-95)

```python
def item_view(db: Session, row: Any, *, store: Any, corpus_registry: Any, now: datetime) -> QueueItemView: ...
```

- The view reads the subject record's claims. A record that does not parse gives no claims and `reviewable: false`.
- For each span: `record = store.span_registry.get(span_id)`. It is `shown` iff `record is not None and record.plane == "public" and contained_answers.span_is_quotable(record, corpus_registry)`, and then `text` is the record's text (`queue.span_shown`).
- A claim's `text` is set iff all its spans are shown. `reviewable` follows 4.5.
- The view carries no response, turn, thread, message or user id, no email, no learner text, no rendered text, no vote, objection type, severity, exposure, support share, priority, final, other-round label or `ledger_seq`. It carries the item's `triggers` and `reasons`, which disclose why the item is queued (4.5, "Blind review").
- `state` is `"claimed"` when the current round has a live lease.
- `record_kind` and `decision` come from the record.

### 4.15 Mode, start-up and the worker

**`v3.mode(settings, package)`** is `"off"` when `package.v3 is None`, when `v3.V3_UNAVAILABLE_REASON` is set, or when `settings.v3_queue == "off"`; else the setting. `v3.require_on` raises `V3Off` when it is off.

**`main._check_v3_package(package)`** runs after `_check_gateway_package`:
- No v3 block: the reason is `None` (mode off).
- `check_v3_package(package, structural=False)` problems stop a governed build when `V3_QUEUE != off` (`ConfigPackageError("v3: …")`). Otherwise they set the reason and log `v3.unavailable` (WARNING).

**`check_v3_package(package, *, structural)`** checks:
- the two committed schema files exist and their canonical sha256 equals the pins;
- `TRIGGER_RULES`, `QUEUE_REASONS`, `V3_COUNTED`, the priority, exposure, claim-set key, K, draw, gold and stop ids equal the code's;
- with `structural=True` (tests and `config_package.py --check`):
  - every development registry entry's fixture path exists under the repository (the image has no `apps/api/tests/`, M20);
  - each committed schema equals `model_json_schema()` of its model.

**`python -m app.workers.v3_queue`** (in-image; logger `qcai.worker`). Exit 0 on success, 1 when a check fails, 2 on usage or a refusal.
- `scan [--limit N] [--until-done]` (refused when the mode is off): logs `v3.scan_finished` (`scans`, `last`), or `v3.scan_refused` (`reason`) with exit 2.
- `status`: logs `v3.status` with the mode, `slis` and the stop. Outside development it is the only SLI source while D-18 is open (`GET /v3/metrics` refuses every caller there); its schedule is DI-95.
- `verify-gold [--expect-head SEQ:HASH]`: logs `v3.gold_verified` with the count, the head and the problems.
- `export-gold --path P [--all]`: logs `v3.gold_exported` (`count`, `applied_only`), or `v3.gold_export_refused` with exit 2 for a path inside the application tree or the repository checkout.

---

## 5. Configuration package v5 (`apps/api/app/config_package/v5.json`)

### 5.1 File

**v5 is a copy of v4 with these changes:**
- `package_version "5.0.0"`, `schema_version 5`, `phase "6"`, `created "2026-11-22"`.
- `supersedes {"package_version": "4.0.0", "sha256": "9cb984081c89c6f0d3b44cc36b38d3332383b76038734b4e21983d319c23408c", "readable_until": "the release after the Phase 6 merge"}`.
- Every v4 block is unchanged except `flag_policy`, `owner_decisions` and the new `v3` block.
- `v2.correction.critical_registry` stays `[]`, and for schema 5 the loader requires it empty: `v3.critical_claims` supersedes it, and `critical_for` reads `v3.critical_claims`.
- No `tutor_pipeline` schema changes and no ledger change.
- `x1`: X1 fires at `tiers` 1, 2 and 3 (conflict 1); `withholds`, `revision` "never" and the sticky `hold` apply at `withhold_tier` 1 only.

```json
"v3": {
  "version": "v3-audit-v1", "provisional": true, "status": "provisional",
  "authority": "PD-32, PD-33, PD-34, PD-35, PD-36, PD-37, PD-38, PD-39 (ratified under DI-98); plan Phase 6 (L1439-1498)",
  "triggers": {"version": "x-triggers-v1", "provisional": true, "record": "PD-32",
               "rules": {"X1": "critical-claim-objection-v1", "X2": "v2-exhausted-type-a-b-v1", "X3": "learner-flag-f0-v1",
                         "X4": "v1-5-margin-mark-v1", "X5": "model-version-change-or-cusum-alarm-v1", "X6": "seeded-sha256-bernoulli-v1"},
               "x1": {"tiers": [1, 2, 3], "min_objections": 1, "withhold_tier": 1, "withholds": true, "revision": "never",
                      "hold": "sticky_for_the_response"},
               "x2": {"ehmf_types": ["A", "B"]}, "x4": {"margin_source": "v1.v1_5.x4_margin"},
               "x5": {"audit_rate": {"numerator": 1, "denominator": 5}, "window_deliveries": 1500, "sources": ["cusum_alarm", "model_change"]},
               "counted": ["X1", "X2", "X3", "X4"],
               "queue_reasons": ["v1_3_flag", "v1_8_misconception", "v2_correction_exhausted", "v2_degraded_withheld"]},
  "priority": {"provisional": true, "record": "PD-34", "provisional_until": "expert elicitation (plan 6.3; D-06, DI-98)",
               "rule": "severity-exposure-one-minus-k-v1",
               "severity": {"A": 1.0, "B": 1.0, "C": 0.6, "D": 0.6, "E": 0.4, "unknown": 1.0, "disclosed_conflict": 0.0},
               "exposure_rule": "learner-deliveries-of-claim-set-v1", "claim_set_key_rule": "sorted-claim-ids-sha256-v1",
               "k_rule": "panel-support-share-v1", "tie_break": ["enqueued_at", "item_id"]},
  "draw": {"provisional": true, "record": "PD-35", "rule": "seeded-sha256-bernoulli-v1", "seed": "qcai-x6-v1",
           "rate": {"numerator": 1, "denominator": 20}, "population": ["delivered", "legacy"], "considered": "once_at_first_scan",
           "pre_ledger": "non_auditable"},
  "workflow": {"provisional": true, "record": "PD-36", "states": ["queued", "claimed", "adjudicated", "applied"], "lease_s": 1800,
               "double_review": {"rate": {"numerator": 1, "denominator": 10}, "rule": "seeded-sha256-bernoulli-v1", "operator_policy": "D-06"},
               "max_rounds": 3, "disagreement": "third_reviewer", "self_review": "refused", "apply_by": "another_reviewer",
               "independence": "user_keyed_round_records",
               "blind_to": ["finals", "other_rounds", "votes", "objection_types", "support_share", "severity", "priority"],
               "unreviewable": "stays_queued", "applies_to_ledger": false, "releases_withheld": false,
               "recalibration": "phase7_change_control", "closed_item_trigger": "recorded_not_reopened"},
  "gold_store": {"chain": "v3-gold", "schema": "v3-gold-label-v1",
                 "record_hash_rule": "sha256(canonical{chain,seq,created_at,prev_hash,entry_sha256})-v1", "append_only": true,
                 "restore": "none", "plane": "production_public_spans_only"},
  "critical_claims": {"provisional": true, "record": "PD-33; DI-90", "fixture": "apps/api/tests/data/score_floor_queries.json",
                      "registries": {"development": {"synthetic": true, "claims": [
                                        {"claim_id": "claim-5986f3f1a2e538431cad1eba9de377a7", "query_index": 30},
                                        {"claim_id": "claim-f7a69a03bf419134f7104233b637aed6", "query_index": 30},
                                        {"claim_id": "claim-71143cadf24a121f65b59a75a9b9ec53", "query_index": 30}]},
                                     "staging": {"claims": []}, "production": {"claims": []}, "default": {"claims": []}}},
  "slo": {"provisional": true, "record": "PD-37", "provisional_until": "D-06 (DI-98)", "queue_age_slo_s": 259200,
          "stop_measure": "oldest_open_item_age", "stop_window_s": 172800, "stop_sample_s": 3600, "stop_tier1": "pre_verified_only",
          "stop_refresh_s": 60, "unreadable": "stop", "alert_measure": "queue_age_p90",
          "escalation_share_max": {"numerator": 1, "denominator": 10}, "window_days": 7, "report_only": true},
  "residual": {"statistic": "wilson95_upper", "population": "x6_audited_answer_deliveries", "period": "utc_month", "report_only": true},
  "reviewers": {"provisional": true, "record": "PD-38", "role": "reviewer", "pool": "unstaffed",
                "outside_development": "refused_while_d18_open", "development": "synthetic_demo_only", "sees": "public_quotable_spans_only",
                "flag_intake": "development_only"},
  "schemas": {"V3GoldLabel": {"version": "v3-gold-label-v1", "path": "schemas/v3-gold-label.v1.schema.json", "sha256": "<canonical sha256>"},
              "V3CusumAlarm": {"version": "cusum-alarm-v1", "path": "schemas/v3-cusum-alarm.v1.schema.json", "sha256": "<canonical sha256>"}}
}
```

**`flag_policy` adds:**
- `"v3_queue": {"values": ["off", "shadow", "on"], "default_development": "shadow", "default_elsewhere": "off", "on_requires": "phase6_exit_passed", "on_outside_development": "refused_before_exit", "disable": "releases_nothing", "authority": "plan Phase 6 L; 13.6; PD-38"}`.
- `"phase6_exit_passed": false`, `"phase6_exit_evidence": null`.
- `authority` appends: "; PD-38 for v3_queue and phase6_exit_passed: the Phase 6 switch (plan Phase 6 L; 13.6), an engineering default recorded provisional with PD-38 and ratified with it (DI-98)".

**`owner_decisions` changes:**
- D-25 becomes `{"state": "open", "registry": [], "development_registry": "v3.critical_claims.registries.development (synthetic)", "text": "critical-claim registry triggering X1 [Evidence E-86]. PI.", "record": "PD-29, PD-33; DI-90"}`.
- D-06 adds `"operator_values": ["v3.slo", "v3.workflow.double_review"]` and `record` becomes `"DI-52; PD-36, PD-37; DI-98"`.
- New: D-18 `{"state": "open", "option": null, "reviewer_pool": "unstaffed", "hold": "H4 blocks the P6 pool; P11 start", "applied": "no reviewer is admitted outside development; development reviewers are synthetic demo identities", "ratified": false, "record": "PD-38; DI-91"}`.
- New: D-08 `{"state": "open", "hold": "H10 blocks the P6 experts; P10, P12 cohorts", "applied": "no research use of V3 labels", "record": "DI-94"}`.
- New: D-14 `{"state": "open", "applied": "no research data plane: production-plane gold labels about public-corpus spans only; research labelling is a Phase 6 non-goal", "record": "DI-94"}`.

**New files:** `v5.json.sha256`, `schemas/v3-gold-label.v1.schema.json` and `schemas/v3-cusum-alarm.v1.schema.json`. `v4.json`, `v3.json`, `v2.json`, `v1.json`, their sidecars and every existing schema file are byte-unchanged in content.

### 5.2 Loader (`app/core/config_package.py`)

**Paths and versions.**
- `DEFAULT_PACKAGE_PATH = PACKAGE_DIRECTORY / "v5.json"`; `V4_PACKAGE_PATH` is added.
- `schema_version in (1, 2, 3, 4, 5)`; the message becomes "'schema_version' must be 1, 2, 3, 4 or 5". Every `>= 4` rule applies to 5.
- `ConfigPackage` gains `v3: "V3Params | None" = None`.
- `FlagPolicy` gains `phase6_exit_passed: bool = False` and `phase6_exit_evidence: str | None = None`.

**`V3Params`** (frozen dataclass):
- `version`, `trigger_registry_version`, `trigger_rules`, `counted`, `queue_reasons`, `x1_tiers`, `x1_withhold_tier`, `x2_types`;
- `x5_rate: Fraction`, `x5_window_deliveries`, `severity: Mapping[str, Fraction]`;
- `priority_rule`, `exposure_rule`, `claim_set_key_rule`, `k_rule`, `tie_break`;
- `draw_rule`, `draw_seed`, `draw_rate: Fraction`, `population`;
- `lease_s`, `double_review_rate: Fraction`, `max_rounds`;
- `gold_chain`, `gold_schema`, `gold_record_hash_rule`;
- `critical_registries: Mapping[str, tuple[str, ...]]`, `critical_fixture`;
- `queue_age_slo_s`, `stop_measure`, `stop_window_s`, `stop_sample_s`, `stop_refresh_s`, `stop_tier1`;
- `escalation_share_max: Fraction`, `window_days`, `reviewer_pool`;
- `schemas: Mapping[str, SchemaPin]`;
- the method `critical_registry_for(environment) -> tuple[str, ...]`.

**`_parse_v3(raw, *, decisions, v2)` refuses** (every refusal is structural):
- An unmarked provisional block: `v3` and each of `triggers`, `priority`, `draw`, `workflow`, `critical_claims`, `slo` and `reviewers`.
- A `version` other than `V3_VERSION`.
- Triggers:
  - a trigger version or rule map other than the code's (`TRIGGER_REGISTRY_VERSION`, `TRIGGER_RULES`);
  - `x1` other than `tiers` [1, 2, 3], `min_objections` 1, `withhold_tier` 1, `withholds` true, `revision` "never", `hold` "sticky_for_the_response";
  - `x2.ehmf_types` other than `["A","B"]`;
  - `x4.margin_source` other than `v1.v1_5.x4_margin`;
  - an `x5.audit_rate` other than 1/5 (plan "audit 20%"), or a `window_deliveries` outside 1..1000000;
  - while D-06 is open, `counted` other than `V3_COUNTED`;
  - `queue_reasons` other than `QUEUE_REASONS`.
- Priority:
  - rule ids other than the code's (`PRIORITY_RULE`, `EXPOSURE_RULE`, `CLAIM_SET_KEY_RULE`, `K_RULE`);
  - severity keys other than A-E, `unknown` and `disclosed_conflict`, or a weight outside [0, 1];
  - while D-06 is open, A-E weights other than the plan's 6.3 values (`PLAN_SEVERITY`), or `disclosed_conflict` other than 0;
  - a `tie_break` other than `TIE_BREAK`.
- Draw:
  - a rule other than `DRAW_RULE`;
  - a seed not matching `^[a-z0-9][a-z0-9-]{0,63}$`;
  - a rate other than 1/20 (plan "X6 = 5%");
  - a population other than `["delivered", "legacy"]`.
- Workflow:
  - states other than `WORKFLOW_STATES`;
  - `lease_s` outside 60..86400;
  - while D-06 is open, a double-review rate other than 1/10;
  - `max_rounds` other than 3;
  - `self_review` not "refused", `apply_by` not "another_reviewer", `independence` not "user_keyed_round_records", `unreviewable` not "stays_queued", `applies_to_ledger` or `releases_withheld` not false, `recalibration` not "phase7_change_control";
  - a `blind_to` that omits any of the seven listed values.
- Gold store: a chain, schema or record-hash rule other than the code's, `append_only` not true, or `restore` not "none".
- Critical claims:
  - registry names other than {development, staging, production, default};
  - a claim id not matching `CLAIM_ID`, or a duplicate;
  - a non-empty non-development registry while D-25 is open;
  - a non-empty development registry not marked `synthetic: true`;
  - an entry without a non-negative `query_index`;
  - a `fixture` that is absolute or holds `..`.
- For schema 5, a non-empty `v2.correction.critical_registry` (superseded by `v3.critical_claims`).
- SLO:
  - `queue_age_slo_s` outside 3600..2592000;
  - `stop_measure` other than `oldest_open_item_age`, or `alert_measure` other than `queue_age_p90`;
  - `stop_window_s` other than 172800 (plan "two days");
  - a `stop_sample_s` outside 60..86400 or not dividing the window;
  - `stop_tier1` other than `pre_verified_only`;
  - `stop_refresh_s` outside 1..3600;
  - `unreadable` other than `stop`;
  - `escalation_share_max` other than 1/10 (plan "V-3 <= 10%");
  - `window_days` outside 1..90;
  - `report_only` not true.
- Residual: values other than those shown in 5.1.
- Reviewers: `role` other than `reviewer`; `flag_intake` other than `development_only` while D-05's freeze holds; while D-18 is open, `pool` other than `unstaffed` or `outside_development` other than `refused_while_d18_open`.
- `schemas` naming other contracts than `V3_SCHEMA_MODELS`, or a malformed pin.
- A missing owner decision object among D-06, D-08, D-14, D-18 and D-25.

**`_parse_flag_policy` (schema 5)** adds:
- `v3_queue`'s values and defaults must equal `V3_QUEUE_DEFAULT_DEVELOPMENT` and `V3_QUEUE_DEFAULT_ELSEWHERE`, with `on_requires` `phase6_exit_passed` and `disable` `releases_nothing`;
- `authority` must name PD-38 and DI-98;
- `phase6_exit_passed` must be a boolean, and true needs a `phase6_exit_evidence` string.

### 5.3 Scripts (`scripts/config_package.py`)

- The default path is v5, and the module docstring names "the shipped package v5; v4, v3, v2 and v1 stay readable".
- `--check` for schema 5 also runs `check_v3_package(package, structural=True)` and prints a V3 summary: the trigger registry, the draw rate, the double review, the registry sizes per environment and `phase6_exit_passed`.
- `--rehash` for schema 5 also recomputes the two v3 schema pins.
- `--write-schemas` for v5 writes the two v3 schemas. The v4 schema files come out byte-identical in content.

---

## 6. Settings (`app/core/config.py`)

| Setting (env) | Type / default | Freeze rationale |
|---|---|---|
| `V3_QUEUE` | `Literal["off", "shadow", "on"] \| None = None`; `None` means `V3_QUEUE_DEFAULT_DEVELOPMENT` ("shadow") in development and `V3_QUEUE_DEFAULT_ELSEWHERE` ("off") elsewhere; v5 `flag_policy.v3_queue` must name both | E6, plan L. Off outside development: no scan, no draw, no item; the reviewer routes refuse every caller there with 403 (the role, then the D-18 pool), and answer 404 only to an admitted reviewer in development. Shadow outside development is a configuration override (`config.override` key `v3_queue_shadow`) that changes no learner path: the flag route stays 404 there and no reviewer is admitted (D-18). |
| `V3_FLAG_RATE_LIMIT` | `str = "10/minute"` | PD-38 (an engineering parameter like PD-11's rate limits); the flag route exists only in development where `V3_QUEUE` is not off |

**Validator additions** (after the `model_gateway` block):
- `if self.v3_queue is None: self.v3_queue = V3_QUEUE_DEFAULT_DEVELOPMENT if development else V3_QUEUE_DEFAULT_ELSEWHERE`.
- `if not development and self.v3_queue == "on": self._refuse_v3_queue_on_before_phase_6_exit()`. It reads the package lazily. It raises "V3_QUEUE=on is refused outside development before the Phase 6 exit (configuration package flag_policy.phase6_exit_passed is false; plan Phase 6 L, P). Use off or shadow." It also refuses unless the package is the shipped, hash-verified one.

**`main._record_configuration_overrides`** adds `("v3_queue_shadow", settings.v3_queue == "shadow")` and `("v3_queue_on", settings.v3_queue == "on")`.

**`infra/cloudrun/api-production.env.example.yaml`** adds a Phase 6 comment block and `V3_QUEUE: "off"`. The comment says that `on` is refused before the exit, that reviewers are refused outside development while D-18 is open, and that the flag intake is development-only.

---

## 7. File-by-file changes

### 7.1 NEW `apps/api/app/services/v3/`

| Module | Contents |
|---|---|
| `__init__.py` | Docstring (the triggers, the queue and workflow, the gold store, the holds; V3 only in development by default; nothing reaches a learner; the import rule); `V3_UNAVAILABLE_REASON`; `V3Off`; `mode()`; `require_on()`; lazy re-exports |
| `rules.py` | 3.3 |
| `contracts.py` | 3.1; `V3_SCHEMA_MODELS` |
| `triggers.py` | 4.1: `x1_claims`, `x2_claims`, `x3_fires`, `x4_fires`, `record_sightings`, `registry_sightings`, `x5_model_changes`, `x5_active`, `queue_reasons`, `claim_types`, `response_types`, `evaluate`, `response_spec`; `ItemSpec`, `ModelChange`, `RecordTriggers` |
| `draw.py` | 4.2, `claim_set_key` |
| `priority.py` | 4.3 |
| `scan.py` | 4.4: `run_scan`, `scan_until_done`, `record_model_change`, `ScanResult`, `V3_SCAN_LOCK_KEY` |
| `queue.py` | 4.5: `item_id_for`, `upsert_item`, `list_queue`, `get_item`, `reviewable`, `span_shown`, `workflow_state`, `claim_item`, `adjudicate`, `apply_item`, `Lease`, `Adjudicated`, `V3NotFound`, `V3Conflict`, `CONFLICTS` |
| `gold.py` | 4.6: `gold_hash_for`, `append_gold`, `verify_gold_store`, `GoldCheck`, `export_gold`, `V3_GOLD_LOCK_KEY` |
| `feedback.py` | 4.7 |
| `events.py` | 4.8 |
| `holds.py` | 4.9 |
| `stop.py` | 4.10 |
| `metrics.py`, `residual.py` | 4.11 |
| `views.py` | 4.14 |
| `package_check.py` | 4.15 `check_v3_package` |

**Import rule:**
- No module under `app/services/v3/` imports `learner_record`, `learner_progress`, `learning_intelligence`, `microlearning`, `app.core.auth`, `app.api.routes.*`, `answer_history` or `retrieval_legacy_p1`.
- Neither `v3/stop.py` nor `v3/triggers.py` imports `app.services.v2_panel` or the gateway at module level, so `v2_panel/track.py` and the pipeline may import `v3.stop` lazily. `triggers.py` imports `v2_panel.voting` inside `family_objection_types` only.
- The service events log on `qcai.v3`.

### 7.2 NEW elsewhere

| File | Contents |
|---|---|
| `apps/api/app/core/reviewer_access.py` | 4.12 `reviewer_admitted`, `require_reviewer` |
| `apps/api/app/api/routes/v3.py` | Section 9: router prefix `/v3`, every route `Cache-Control: no-store`, security events, `flag_intake_open` |
| `apps/api/app/workers/v3_queue.py` | 4.15 |
| `apps/api/alembic/versions/20261122_phase6_v3_audit.py` | Section 8 |
| `apps/api/app/config_package/v5.json`, `v5.json.sha256`, `schemas/v3-gold-label.v1.schema.json`, `schemas/v3-cusum-alarm.v1.schema.json` | Section 5 |
| `scripts/run_v3_residual_report.py` | 12.1 |
| `docs/evaluation/phase6/v3_residual_report_v1.json`, `docs/evaluation/phase6/README.md` | 12.1 |
| `docs/architecture/phase6-implementation-spec.md` | This spec (LF) |
| `docs/architecture/v3-trigger-registry.md` | Plan F "trigger registry v1". A table of X1-X6 gives each trigger's rule id, its source in the record, its subject, whether it holds and whether V-3 counts it. It then gives the queue reasons, the priority weights and rules, the claim-set key, the draw rule, rates and window, the double-review rate and the SLO and stop values. Test 19 compares it with the package. |
| `docs/adr/ADR-009-v3-audit-and-adjudication.md` | 15 |
| Frontend files | Section 11 |
| Tests | Section 13 |

### 7.3 MOD

| File | Change |
|---|---|
| `app/db_models.py` | The eight models of section 8, each with a comment naming its rule (append-only, user-keyed, no learner data) |
| `app/core/schema_upgrades.py` | `_guard_v3_tables(connection)`, called when the six guarded V3 tables exist (8) |
| `app/core/config.py` | Section 6; `V3_QUEUE_DEFAULT_DEVELOPMENT = "shadow"`, `V3_QUEUE_DEFAULT_ELSEWHERE = "off"` |
| `app/core/config_package.py` | 5.2; a `# --- package v5 (Phase 6)` section; module docstring (the shipped package v5) |
| `app/core/authorization.py` | `ROLES`; `REVIEWER = "reviewer"` access level (`"A verified principal whose role is reviewer; outside development no caller is admitted while the reviewer pool (D-18) is unstaffed."`); the eight policies of section 9; the ledger route's note gains "outside development while the reviewer pool (D-18) is unstaffed, a reviewer reads as an owner" |
| `app/api/routes/ledger.py` | 4.12: the reviewer branch also needs `reviewer_admitted(settings)`; docstring |
| `app/main.py` | `ROUTERS` adds `v3.router` after `ledger.router`; `_check_v3_package`; `/ready` 10.2; overrides (6) |
| `app/services/ledger.py` | `SCHEMA_REVISION = "20261122_phase6_v3_audit"`; module docstring budget line adds "v5 from the Phase 6 release"; `pending_v3_intents` docstring: "A read-only helper; the Phase 6 scan reads the records itself (app.services.v3.scan)" |
| `app/services/v2_panel/tiers.py` | 4.13 `critical_for`; docstring |
| `app/services/v2_panel/track.py` | 4.13 (`critical_for(..., environment=)`; `v3_stop`; the tier-1 stop path at the first consult); docstring |
| `app/services/v1_checks/runner.py` | 4.13: the sticky hold of a critical tier-1 claim; the docstring's `on` paragraph |
| `app/services/v1_checks/v1_5_abstention.py` | Docstring: "A mark is the X4 trigger (app.services.v3.triggers.x4_fires)" |
| `app/services/tutor_pipeline/pipeline.py` | The `v3_stop=None` constructor keyword and `_v3_stop`, passed to `V2Track`; the default reads through `self.session_factory` |
| `app/services/tutor_pipeline/contracts.py`, `package_check.py`, `__init__.py`, `app/services/tutor_followups.py` | Docstrings name "v5 since Phase 6" where they named the shipped package, keeping the v4 history clause |
| `alembic/versions/20261122_phase5_gateway_controls.py` | Docstring: `20261122_phase6_v3_audit` follows it |
| `scripts/config_package.py` | 5.3 |
| `.github/workflows/ci.yml` | Section 14 |
| `.gitattributes` | `docs/architecture/phase6-implementation-spec.md text eol=lf` |
| `infra/cloudrun/api-production.env.example.yaml`, `deployment.md`, `observability.md` | 6, 15 |
| `docs/security/authorization-matrix.md` | Regenerated by `scripts/authorization_matrix.py` |
| `docs/testing/test-strategy.md` | The E15 edit (17); `## Phase 6 acceptance map (plan Phase 6 K)` |
| Phase 3, 4 and 5 specs, ADR-006, ADR-008 | 7.4 |
| `apps/api/tests/conftest.py` | The autouse fixture also calls `v3.stop.reset_stop_cache()` before and after each test, and fails a test that leaves a shared-database queue item enqueued before the session started (0.1) |
| Records | 12.2 |

### 7.4 Text that describes the code (P2-12-D-03; edited in place)

Each line naming the shipped package gains the v5 clause, keeping its v2/v3/v4 history (M15):
- the Phase 3 spec's 5.2 constants (`.../v5.json` with Phase 6) and parsing line ("and 5 since Phase 6"), its report shape and test lines ("5.0.0 for Phase 6's v5");
- the Phase 4 spec's 5.2 lines (`v5.json` with Phase 6; "4 since Phase 5 and 5 since Phase 6");
- the env example and `deployment.md` ("v5 from the Phase 6 release").

The Phase 5 spec:
- R-e: "D-25 is OPEN. Outside development the registry is empty, so no claim is critical there; development holds Phase 6's synthetic registry (Phase 6 spec PD-33). The X1 trigger and the sticky hold of a critical tier-1 claim are Phase 6's."
- 4.8's `critical_for` sentence.
- The E15 texts (17).

The Phase 3 spec's ledger-route paragraph (section 9) names the D-18 gate of the reviewer branch (4.12).

ADR-006 and ADR-008 get appended revisions (15).

---

## 8. Database

**One revision**, `20261122_phase6_v3_audit` (24 characters), after `20261122_phase5_gateway_controls`. `ledger.SCHEMA_REVISION` names it. `create_all` builds the same tables at start-up.

| Table | Columns (types) | Keys and indexes | Rule |
|---|---|---|---|
| `v3_queue_items` | `item_id` String(32), `ledger_seq` Integer, `claim_key` String(48), `subject` String(16), `record_kind` String(16), `response_digest` String(32), `triggers` String(32), `reasons` String(128), `ehmf_types` String(16), `held` Boolean, `severity` Float, `exposure` Integer, `k` Float, `priority` Float, `state` String(16), `review_round` Integer, `double_review` Boolean, `enqueued_at` DateTime(tz), `closed_at` DateTime(tz) null, `final_gold_seq` Integer null, `applied_at` DateTime(tz) null, `applied_by_digest` String(32) null, `applied_client_key` String(64) null, `package_version` String(32), `package_sha256` String(64) | PK `item_id`; `uq_v3_queue_items_subject (ledger_seq, claim_key)`; `ck_v3_queue_items_subject`; `ck_v3_queue_items_state` (stored states); `ix_v3_queue_items_state_priority`, `ix_v3_queue_items_enqueued_at`, `ix_v3_queue_items_closed_at` | DELETE and TRUNCATE refused; UPDATE allowed |
| `v3_claims` | `id` Integer PK, `item_id` String(32), `review_round` Integer, `user_id` String(255), `claimed_at` DateTime(tz), `lease_expires_at` DateTime(tz), `adjudicated_at` DateTime(tz) null | `uq_v3_claims_item_round (item_id, review_round)`; `ix_v3_claims_user_id`; no foreign key (M7) | user-keyed: erasure deletes a reviewer's leases and round records |
| `v3_draws` | `ledger_seq` Integer (autoincrement off), `delivered_at` DateTime(tz), `claim_set_key` String(64) null, `rate_numerator` Integer, `rate_denominator` Integer, `x5_active` Boolean, `drawn` String(2) null, `rule` String(48), `package_sha256` String(64), `considered_at` DateTime(tz) | PK `ledger_seq`; `ix_v3_draws_delivered_at`, `ix_v3_draws_claim_set_key` | append-only |
| `v3_gold_labels` | `seq` Integer (autoincrement off), `item_id` String(32), `review_round` Integer, `actor_role` String(32), `action` String(16), `reviewer_digest` String(32), `entry` Text, `entry_sha256` String(64), `prev_hash` String(64), `record_hash` String(64), `created_at` DateTime(tz) | PK `seq`; `uq_v3_gold_labels_item_round (item_id, review_round)`; `ix_v3_gold_labels_item_id`, `ix_v3_gold_labels_reviewer_digest` | append-only; an insert must extend the chain |
| `v3_events` | `seq` Integer PK, `kind` String(16), `payload` Text, `from_ledger_seq` Integer, `window_deliveries` Integer, `created_at` DateTime(tz) | `ck_v3_events_kind ('model_change','cusum_alarm')` | append-only |
| `v3_model_versions` | `id` Integer PK, `model_key` String(255), `model_version` String(255), `first_seen_seq` Integer, `source` String(16), `seen_at` DateTime(tz) | `ix_v3_model_versions_model_key` | append-only |
| `v3_flags` | `id` Integer PK, `user_id` String(255), `ledger_seq` Integer, `created_at` DateTime(tz) | `uq_v3_flags_user_record (user_id, ledger_seq)`; `ix_v3_flags_user_id`, `ix_v3_flags_ledger_seq` | user-keyed: erasure and guest retention delete it |
| `v3_scans` | `seq` Integer PK, `from_seq`, `to_seq`, `records`, `deliveries`, `drawn_x6`, `drawn_x5`, `items_created`, `items_updated`, `model_changes`, `unparsed` (Integer), `package_version` String(32), `package_sha256` String(64), `created_at` DateTime(tz) | — | append-only |

**Guards** (`schema_upgrades._guard_v3_tables`; checked on every start and re-created only when not current, Phase 3 spec 18.8 F8; no `%` in the SQL).

PostgreSQL functions:
- `v3_append_only()`: `RAISE EXCEPTION USING MESSAGE = TG_TABLE_NAME || ' is append-only: ' || TG_OP || ' refused'`.
- `v3_gold_links_to_chain()`: the ledger's link rule, with genesis `repeat('0', 64)` and the message "v3_gold_labels appends must extend the chain".
- `v3_queue_items_keep()`: refuses DELETE and TRUNCATE with the message "v3_queue_items keeps every item: ' || TG_OP || ' refused".

PostgreSQL triggers (`Trigger` dataclass):
- `<table>_append_only`, ROW, UPDATE and DELETE;
- `<table>_no_truncate`, STATEMENT, TRUNCATE, on each append-only table;
- `v3_gold_labels_links_to_chain`, ROW, INSERT;
- `v3_queue_items_keep`, ROW, DELETE;
- `v3_queue_items_no_truncate`, STATEMENT, TRUNCATE.

The lock order is the writers' order (4.4, 4.5): `("v3_model_versions", "v3_events", "v3_draws", "v3_queue_items", "v3_gold_labels", "v3_scans")`.

SQLite uses `BEFORE UPDATE`/`BEFORE DELETE ... RAISE(ABORT, ...)` per table (`<table>_no_update`, `<table>_no_delete`, `v3_queue_items_no_delete`), plus a gold `BEFORE INSERT ... WHEN NEW.seq != (SELECT COALESCE(MAX(seq),0)+1 ...) OR NEW.prev_hash != COALESCE((SELECT record_hash ... ORDER BY seq DESC LIMIT 1), '<genesis>')`.

**Downgrade.**
- It refuses while `v3_gold_labels`, `v3_queue_items` or `v3_flags` holds rows, unless run as `alembic -x allow_v3_drop=true downgrade 20261122_phase5_gateway_controls`. The message names each table's row count ("<table> holds N rows") and reads: "... (append-only evidence, R-22; the queue and learner flags carry F_i and the holds' queue); export first with python -m app.workers.v3_queue export-gold --all --path <path outside the application tree>, then: alembic -x allow_v3_drop=true downgrade 20261122_phase5_gateway_controls".
- On PostgreSQL it drops the V3 triggers and functions, then the indexes and tables.
- A digest rollback needs no downgrade, because the earlier image reads none of the tables.

**Erasure.** Of the eight tables, `v3_claims` and `v3_flags` are user-keyed (`user_id`), so `erasure.user_keyed_tables()` finds them. Each has a single integer primary key, so `_seed_everything` seeds them. No append-only table has a `USER_KEY_COLUMNS` column. `erasure.py` and `retention.py` are unchanged (E16).

**Drivers.**
- Every statement runs on SQLite and on PostgreSQL under psycopg and pg8000.
- Filters compare plain columns. No JSON operator is used; triggers and reasons are parsed in Python.
- An insert that must know whether it wrote its row (a draw, a queue item, a flag) is `INSERT ... ON CONFLICT DO NOTHING RETURNING <key>`, never `rowcount`: psycopg reports rowcount -1 for such an insert into a table with an autoincrement key (as `span_store` records).
- Server errors under pg8000 arrive through `app.core.db.classify_pg8000_errors`. The retry loops catch `IntegrityError` and SQLSTATE 40001/40P01 as `ledger.sqlstate` reads them.

**Start-up DDL.** Start-up's `create_all` and `run_schema_upgrades` create the eight tables and the V3 functions and triggers, as they did for Phase 5's gateway tables. No start-up row write is added.

---

## 9. Routes (`app/api/routes/v3.py`; every reviewer route uses `Depends(require_reviewer)`; the flag route uses `Depends(get_current_user)`)

| Method, path | Access, ownership (matrix) | Behaviour |
|---|---|---|
| `POST /v3/flags` | `principal`, `owner` | 404 unless `flag_intake_open(settings)` (development, and the mode not off). Body `FlagRequest`. 200 `{"status": "recorded", "f_i": 0.0, "duplicate": bool}`; 404 for a missing, another learner's or a pre-ledger turn; 409 `not_recorded_yet`; 503 `busy`; rate limit `V3_FLAG_RATE_LIMIT` (scope `v3-flag`). Changes no verdict and no ledger row. |
| `GET /v3/queue?state=&limit=` | `reviewer`, `none` | 404 when off. `{"items": [QueueItemView], "order": ["priority desc", "enqueued_at", "item_id"]}` (limit 1-100, default 50; state one of `WORKFLOW_STATES`, default `queued` with `claimed`). Security event `v3.queue_read` (success; `route`, `count`). |
| `POST /v3/scan` | `reviewer`, `none` | 404 when off. One `run_scan` (limit 500); `ScanResult` as JSON; 503 `busy`. Security event `v3.scan_run` (counts). |
| `GET /v3/items/{item_id}` | `reviewer`, `none` | 404 when off or missing (an id not matching `ITEM_ID` is 404). `QueueItemView`, plus `"final_gold_seq"` (the gold label id, conflict 25). Security event `v3.item_read`. |
| `POST /v3/items/{item_id}/claim` | `reviewer`, `none` | `{"item_id", "state": "claimed", "review_round", "lease_expires_at"}`; 409 with the conflict reason (`not_reviewable` included); 503 `busy`. Security event `v3.item_claimed`. |
| `POST /v3/items/{item_id}/adjudicate` | `reviewer`, `none` | Body `AdjudicationRequest`. `{"item_id", "gold_seq", "record_hash", "review_round", "state", "duplicate"}`; 409 or 422; 503 `busy`. Security event `v3.item_adjudicated` (`item_id`, `review_round`, `duplicate`). |
| `POST /v3/items/{item_id}/apply` | `reviewer`, `none` | Body `ApplyRequest`. `{"item_id", "state": "applied", "final_gold_seq", "duplicate"}`; 409; 503 `busy`. Security event `v3.item_applied` (`item_id`, `duplicate`). |
| `GET /v3/metrics` | `reviewer`, `none` | `slis(db, package, now)`. Security event `v3.metrics_read`. |

**Policy notes** (matrix text):
- Each reviewer route's note (`authorization.V3_REVIEWER_NOTE`) reads: "Reviewer role only (403 and authz.denied for any other role, in every environment); outside development every caller gets 403 and authz.denied while the reviewer pool (D-18) is unstaffed. An admitted reviewer gets 404 unless V3_QUEUE is shadow or on (development only by default). Claim text, public quotable span text, span ids and keyed digests only, never a learner identifier; a successful call is a v3.* security event."
- `require_reviewer` is a dependency, so it runs before the body's `_off(settings)` check: with `V3_QUEUE=off` a non-reviewer still gets 403 and `authz.denied` in every environment, and outside development every caller does. Only an admitted reviewer (development) sees the 404.
- The flag route's note reads: "404 outside development, and unless V3_QUEUE is shadow or on. The caller's own tutor turn only: another learner's, a missing and a pre-ledger turn get the same 404. Sets F_i = 0 and queues the response (X3); changes no verdict and no ledger row. Rate-limited."

A successful reviewer call records one `v3.*` security event and a refusal by the role or pool gate one `authz.denied`; a 404, 409, 422 or 503 outcome records none. Every security event carries `actor_role` (the user's role), `subject = user.user_id` (stored as a keyed digest) and `route` (the template). `GET /ledger/responses/{response_id}` keeps its shape. Only its reviewer branch gains the D-18 gate (4.12).

---

## 10. Start-up, `/ready`, logs and SLIs

### 10.1 Start-up

The check order is `_check_v1_package`, `_check_gateway_package`, `_check_v3_package` (4.15), the tutor pipeline check, then the manifest, all before any table. `_check_v3_package` reads only the package, the committed files beside it and code values. It never reads `apps/api/tests/`, so it passes from the image layout (M20). No start-up row write is added (8, "Start-up DDL").

### 10.2 `/ready` (`_build_fields()`; static; no database read)

```json
"v3_queue": "off|shadow|on", "v3_queue_setting": "off|shadow|on", "phase6_exit_passed": false,
"v3": {"version": "v3-audit-v1", "trigger_registry": "x-triggers-v1", "triggers": ["X1","X2","X3","X4","X5","X6"],
       "draw": {"rule": "seeded-sha256-bernoulli-v1", "rate": "1/20", "x5_rate": "1/5", "x5_window_deliveries": 1500},
       "double_review": "1/10", "queue_age_slo_s": 259200, "stop_window_s": 172800, "stop_measure": "oldest_open_item_age",
       "critical_registry": {"environment": "development|staging|production|default", "entries": 3},
       "reviewer_pool": "unstaffed", "gold_schema": "v3-gold-label-v1", "provisional": true, "available": true}
```

- `v3` is `null` for a package without a v3 block.
- `/ready` reports no per-run count, stop state, seed, queue depth or gold head, because `/ready` is public (M12). `critical_registry.entries` is the size of a package value.
- `config_package_version` reports 5.0.0.

### 10.3 Log events (enumerations, counts, item ids, model keys, seq numbers and hashes only)

| Event | Logger | Fields | Severity |
|---|---|---|---|
| `v3.scan` | `qcai.v3` | `from_seq`, `to_seq`, `records`, `deliveries`, `drawn_x6`, `drawn_x5`, `items_created`, `items_updated`, `model_changes`, `unparsed`, `done` | INFO |
| `v3.trigger_after_close` | `qcai.v3` | `item_id`, `triggers` | INFO |
| `v3.adjudicated` | `qcai.v3` | `item_id`, `review_round`, `subject`, `state`, `agreement` (second round only); not for a duplicate | INFO |
| `v3.applied` | `qcai.v3` | `item_id`, `final_gold_seq`; not for a duplicate | INFO |
| `v3.gold_appended` | `qcai.v3` | `seq`, `record_hash` | INFO |
| `v3.x5_event` | `qcai.v3` | `kind`, `model_key`, `from_version`, `to_version` or `stream` | WARNING |
| `v3.flag_recorded` | `qcai.v3` | `duplicate` | INFO |
| `v3.stop` | `qcai.v3` | `active`, `reason`, `window_s`, `slo_s` | WARNING when active, INFO when clear |
| `v3.stop_unread` | `qcai.v3` | — | WARNING |
| `v3.unavailable` | `qcai.v3` | `reason` (start-up) | WARNING |
| `tutor.v2.v3_stop` | `qcai.tutor` | `tier`, `policy` | WARNING |
| `v3.status`, `v3.gold_verified`, `v3.scan_finished`, `v3.gold_exported` | `qcai.worker` | `mode` and the SLIs; `count`, `head_seq`, `head_hash`, `problem_count`, `problems`; `scans`, `last` (the last `ScanResult`); `count`, `applied_only` | INFO |
| `v3.scan_refused`, `v3.gold_export_refused` | `qcai.worker` | `reason` (`v3_off`); — (a path inside the application tree or the repository checkout) | WARNING |

The security events `v3.queue_read`, `v3.scan_run`, `v3.item_read`, `v3.item_claimed`, `v3.item_adjudicated`, `v3.item_applied`, `v3.metrics_read` and `authz.denied` log on `qcai.security`.

### 10.4 SLIs (plan I; E9)

`slis` (4.11) on `GET /v3/metrics` and the worker's `status`:
- the escalation share V-3 (X1-X4 numerator; at most 1/10, report only);
- queue depth, age p90 (the alert's measure) and oldest age against the SLO;
- draw counts and rate, and the non-auditable deliveries;
- double-review agreement;
- the residual bound by month;
- gold rows;
- the stop;
- X5 windows.

`GET /v3/metrics` is reviewer-only, so outside development, while D-18 is open, it refuses every caller (4.12) and the worker's `status` line is the only SLI source. That line is logged only when `python -m app.workers.v3_queue status` runs, so the queue-age p90 alert (plan I, R-40) needs a scheduled job: DI-95 defines it (a Cloud Run job running `status` hourly, the stop's sample interval, and `scan --until-done` before it wherever `V3_QUEUE` is not off). No alert policy, dashboard or schedule is created (a cloud write under D-05; DI-95).

---

## 11. Frontend (reviewer UI, plan F; development only)

- **`src/lib/v3-review.ts`** holds pure helpers:
  - `reviewerUiEnabled(env: {NODE_ENV?: string; V3_REVIEWER_UI?: string})` is true iff `NODE_ENV !== "production"` and `V3_REVIEWER_UI !== "off"`;
  - `v3ModeFromReady(payload)` returns `payload.v3_queue` when it is `"shadow"` or `"on"`, else `"off"`;
  - `SYNTHETIC_REVIEWERS = ["reviewer-a", "reviewer-b", "reviewer-c"]`;
  - `reviewerHeaders(name)` returns `{"x-demo-user": "synthetic-" + name, "x-demo-role": "reviewer"}` and throws for a name outside the list;
  - `adjudicationPayload(labels, abstention, clientKey)` sorts the labels and nulls the EHMF type of a SUPPORTED label;
  - `adjudicationReady(labels, claimIds, abstention, needsAbstention)` is true iff every claim has an explicit verdict, each verdict other than SUPPORTED names its EHMF type, and an abstention item has an explicit abstention label (`DraftLabel` allows a null verdict while drafting);
  - `VERDICT_TEXT`, `EHMF_TEXT` and `TRIGGER_TEXT` hold fixed labels. No label says "verified" or "grounded", and the trigger labels are neutral ("X1 critical claim escalated", "X2 unresolved after two correction cycles"): none names an objection type or a tier.
- **`src/app/review/page.tsx`** (server component, `dynamic = "force-dynamic"`, `buildPageMetadata({..., index: false})`):
  - `notFound()` unless `reviewerUiEnabled(process.env)`;
  - and unless the API's `/ready` (`getApiBaseUrl()`, a 2 s timeout, any failure meaning off) gives `v3ModeFromReady(...) !== "off"`;
  - then it renders `<V3ReviewConsole />` inside a labelled `<section>`: the root layout's app shell renders the page's one `<main>` landmark.
- **`src/components/v3-review-console.tsx`** (client):
  - a synthetic reviewer selector;
  - Scan and Refresh buttons (Refresh loads the queue);
  - the queue list, in the API's order (rank, triggers, held, age, state, reviewable);
  - the item detail (claim text and shown spans only).
  - It offers Claim and Adjudicate only for reviewable items. The adjudication form gives each claim a verdict select and an EHMF select, each with a visible label naming the claim ("Verdict for claim N", "Error type for claim N"), plus the labelled abstention select and a `crypto.randomUUID()` client key. Apply follows.
  - Nothing is pre-filled: every adjudication select (verdict, EHMF type, abstention) starts on a disabled placeholder, the EHMF select is disabled until a verdict other than SUPPORTED is chosen, and Adjudicate is disabled until `adjudicationReady`, so a default never becomes an append-only label.
  - The status line is a `role="status"` live region that is always mounted; a failed item read shows its message there.
  - It calls `/api/backend/v3/...` with `reviewerHeaders`.
  - It never shows a vote, severity, support share, priority, final or other round, and it uses no browser storage.
- **`src/lib/types.ts`** adds `V3QueueItem`, `V3ClaimView`, `V3SpanView`, `V3ClaimLabel`, `V3ScanResult` and `V3Metrics`.
- No change to `primary-nav.tsx`, `site-footer.tsx` or any learner page.

---

## 12. Records

### 12.1 `scripts/run_v3_residual_report.py` (plan F "residual report"; AC-6-5)

```
python scripts/run_v3_residual_report.py --write docs/evaluation/phase6/v3_residual_report_v1.json [--allow-dirty]
python scripts/run_v3_residual_report.py --check docs/evaluation/phase6/v3_residual_report_v1.json
```

**Setup.**
- As a command, it sets `DATABASE_URL` to in-memory SQLite before any app import, and raises the `qcai.tutor` and `qcai.v3` loggers to WARNING.
- Its `run()` builds its own engine (StaticPool; `create_all` and `run_schema_upgrades`). It passes that session factory to every call (`append_ledger_entry`, `scan_until_done`, the queue functions), so a test can call it in-process.
- It uses `Settings(environment="development", v3_queue="shadow")`.
- The clock is injected: delivery `i` is at 2026-11-01T00:00:00Z plus `i` seconds, and each action at 2026-11-20T00:00:00Z plus `n` seconds.
- The script refuses `lqs/` paths. It writes only the report.

**Deliveries.**
- The template is the legacy entry `ledger.build_legacy_entry(response._ledger)` of `QAEngine.ask` on in-domain fixture query 0. It is built under the capture script's configuration (b): ENVIRONMENT=production, governance on, and a temporary manifest approving every public-plane, bound item, which gives the p1-floor gate.
- The script asserts the template:
  - is an answer;
  - records its gate score;
  - is not X4-marked (`x4_fires` false under the package's margins);
  - cites only spans a reviewer is shown (the capture store and registry, which the queue calls receive, conflict 30).
- If any assertion fails, it exits 3.
- 6070 copies differ only in `response_id = f"turn-{UUID(int=i)}"` (the claims' `response_id` updated). They are appended through `append_ledger_entry`.

**Run.**
1. `scan_until_done` (limit 1000). This must give 6070 `v3_draws` rows, 300 drawn X6 (M9) and 0 X5.
2. A replay through `draw.draw_trigger` over the same ids must give an identical set.
3. Every X6 item is claimed and adjudicated by `synthetic-reviewer-a` with every claim SUPPORTED.
4. Each double-review item is adjudicated again by `synthetic-reviewer-b` with the same labels.
5. Every item is applied by `synthetic-reviewer-c`.
6. `verify_gold_store` and `verify_response_ledger` run, and the ledger rows' `(seq, entry_sha256, record_hash)` must equal those before the adjudications.

**Report.**

```json
{"report": "qcai-v3-residual-report", "format_version": 1, "created_at": "…", "commit": "…",
 "evidence_class": "synthetic telemetry, not research results (plan Phase 6 H: audit counts are telemetry, not research results)",
 "public_corpus_only": true, "config_package": {"version": "5.0.0", "sha256": "…"},
 "deliveries": {"count": 6070, "ids": "turn-{UUID(int=i)}, i = 1..6070", "template": "the contained answer to in-domain fixture query 0 (capture configuration b; p1-floor; not X4-marked)"},
 "draw": {"rule": "seeded-sha256-bernoulli-v1", "seed": "qcai-x6-v1", "rate": "1/20", "considered": 6070, "x6": 300, "x5": 0,
          "interval_99": [261, 348], "replay_identical": true, "drawn_ids_sha256": "…"},
 "adjudication": {"audited": 300, "double_review": {"selected": 23, "pairs": 23, "agreeing": 23}, "applied": 300, "reviewers": 3},
 "residual": {"audited_answers": 300, "errors": 0, "wilson95": {"lower": 8.673617379884035e-19, "upper": 0.012642971224546034},
              "by_month": [{"month": "2026-11", "audited": 300, "errors": 0, "upper": 0.012642971224546034}], "below": "0.013", "pass": true},
 "bounds": [{"errors": 0, "audited": 300, "upper": 0.012642971224546034}, {"errors": 1, "audited": 300, "upper": 0.018636693694531237},
            {"errors": 3, "audited": 300, "upper": 0.02898349336233983}],
 "harness_equal": true, "gold": {"rows": 323, "verified": true, "head_seq": 323, "head_record_hash": "…"}, "ledger_unchanged": true,
 "result": "pass", "problems": [], "inputs": {"rule": "imported-repository-modules-sha256-lf-v1", "files": {}, "sha256": "…"}}
```

**`--check`** compares everything except `created_at`, `commit`, `inputs` and `gold.head_record_hash`. The head hash covers keyed digests (`reviewer_digest`, `response_digest`), so it depends on the guest secret (M6). It is informational, while the chain itself is verified (`gold.verified`). `inputs` is compared with the checkout through `input_problems`, as in `run_v2_fixtures.py`.

**Exit codes.**
- 0: pass.
- 1: drift.
- 3: a stop. Any of these: the template assertions fail; X6 outside `interval_99`; the residual upper not below 0.013; the replay differs; the harness is unequal; the gold chain or the ledger check fails; the ledger changed.
- 4: a dirty tree on `--write`.

`docs/evaluation/phase6/README.md` gives the reproduction, the scenario, "synthetic telemetry, not research results" (plan H) and that HR-3's study form is Phase 10's.

### 12.2 Records re-written at the last code commit (package v5 and changed modules; M15)

- **`docs/evaluation/phase3/three_plan_replay_v1.json`**, through the replay script's write mode. The package and `inputs` change; decisions, counts and hash equality do not.
- **`docs/evaluation/phase4/v1_fixture_report_v1.json`** (`run_v1_fixtures.py --write ... --allow-dirty`). The package and sha256, `inputs`, `created_at`, `commit` and latency change. Every class, final and answer-rate value stays equal.
- **`docs/evaluation/phase5/v2_fixture_report_v1.json`** (`run_v2_fixtures.py --write ... --allow-dirty`).
  - The package, `inputs`, `created_at`, `commit` and latency change.
  - The scenario counts stay equal:
    - the fakes support every claim, so no X1 fires and no sticky hold acts;
    - query 30's V2 verdicts carry `critical: true`, which the report does not count;
    - the V2 track reads the stop through the script's own database, which has the V3 tables and an empty queue (4.13, M19), so no tier-1 response is stopped.
  - A count that changes is a regression to investigate, not to re-write.
- **`apps/api/tests/data/phase4_public_payloads_v1.json` is never re-written.** Its `--check` must pass unchanged (E11).

---

## 13. Tests

### 13.1 `apps/api/tests/test_phase6_acceptance.py`

**Fakes and fixtures** (`apps/api/tests/v3_fakes.py`, not a test module):
- `fresh_v3_sessions()`: a context manager giving a `(session_factory, engine)` over a fresh in-memory SQLite (StaticPool), with `create_all` and `run_schema_upgrades`; disposed on exit.
- `synthetic_deliveries(n, *, start=1, decision="answer", text=..., span_id=...)`: `tutor_fakes.make_entry(f"turn-{UUID(int=i)}")` entries; `reviewable_deliveries` uses a locked claim's quotable span.
- `append_all(factory, entries)`, `seed_items(factory, entries, *, package, now, trigger, double_review)` and `supported_labels(entry)`.
- `shadow_v3_record(query, *, settings, adapters, generator, cache, v3_stop)`: a record through `v2_fakes.v2_pipeline`; `objecting_adapters` and `NoCache` (a cache that never hits, so a correction cycle calls the members again).
- `reviewer(name)`: the demo headers `{"x-demo-user": f"synthetic-{name}", "x-demo-role": "reviewer"}`.
- `staging_settings()`.
- `FIXED_NOW`, used with fresh databases only (0.1).

Security events are read ordered by `seq`. A test that counts denials uses `monkeypatch.setattr(security_log, "_caps", security_log._Caps())`. One module-scoped fixture computes the residual report once, in-process (`run_v3_residual_report.run()`).

**AC-6-1**

1. **`test_ac_6_1_a_critical_tier_1_claim_with_one_objection_fires_x1_and_is_withheld`.**
   - Setup: in-domain query 30 under `MODEL_GATEWAY=on` and the shipped development registry. One member (`fake-beta-v1`) scripts CONTRADICTED with EHMF A on `claim-5986f3f1a2e538431cad1eba9de377a7`, and a `RevisingGenerator` is used.
   - The record: the verdict's `v2.critical` true, `tier` 1 and `objections` 1; the claim's final `abstain` with escalation X2 (never `deliver`); and `generator.revised == []`.
   - `x1_claims(entry)` equals that claim.
   - On a fresh database, the scan gives one claim item with triggers `("X1","X2")`, `held` true and state `queued`, and `withheld_claim_ids(entry)` contains it.
   - The objector leaves the panel: `fake-beta-v1` also fails its next call (`fail_calls`, with `NoCache`). The claim's next tally passes (REDUCED-2, 1oo2, M3), yet its final is `abstain` with X2 and `block.cycles == 2`. Its id is in every correction's `failed_claim_ids`, X1 fires, and the item's triggers are `("X1",)`.
   - The same under `shadow`: X1 fires, the finals are Phase 4's, and no correction runs.
   - A one-objection claim of query 9 (not in the registry) does not fire X1.
   - Under `Settings(environment="staging")` the registry is empty, so `critical_for` is false.
2. **`test_ac_6_1_the_development_critical_registry_lists_claims_the_pipeline_locks_at_tier_1`.**
   - Each registry entry is locked by the development pipeline (`MODEL_GATEWAY` off) for its `query_index` of `score_floor_queries.json`, and the V2 track judges it at tier 1 with `critical` true.
   - The entries are marked synthetic.
   - Every non-development registry is empty.

**AC-6-2**

3. **`test_ac_6_2_one_thousand_synthetic_deliveries_draw_33_to_69_and_a_same_seed_replay_draws_identical_ids`.**
   - Pure draw over the 1000 ids: 47 drawn, and 33 ≤ 47 ≤ 69.
   - Through the scan on a fresh database: 1000 `v3_draws` rows and 47 X6 items, with the same response ids (joined through `ledger_seq`).
   - A second fresh database gives identical ids.
   - A second scan considers none again (still 1000 rows, no new item).
   - Another seed draws another set.

**AC-6-3**

4. **`test_ac_6_3_the_higher_severity_times_exposure_times_one_minus_k_ranks_first`.**
   - On a fresh database, two legacy answer deliveries with one claim set are scanned, so the second has exposure 2. So is a shadow record.
   - Three items are seeded with `queue.upsert_item`:
     - P: the second delivery's response item, types {C} (0.6), exposure 2, K 0, priority 6/5;
     - Q: a claim item on the shadow record, types {A}, exposure 1, K 0, priority 1;
     - S: a claim item on the shadow record, types {A}, exposure 1, K 2/3, priority 1/3.
   - `list_queue` gives P, Q, S: the order of the exact products.
   - Severity alone would give Q, S before P, and (1 − K) alone would tie P and Q.
   - The same order through `GET /v3/queue` as a synthetic reviewer, over the same fresh database (a `get_db` override, conflict 31); no view carries a priority, severity, exposure or K.

**AC-6-4**

5. **`test_ac_6_4_an_adjudication_appends_one_gold_row_and_changes_no_ledger_row`.**
   - On a fresh database: records, their items, a claim and an adjudication of an item not selected for double review.
   - The gold rows grow by exactly one. Its entry validates as `GoldLabel`, and `verify_gold_store` is ok.
   - Every `response_ledger` row's `(seq, entry, entry_sha256, prev_hash, record_hash)` and the head are byte-identical, and `verify_response_ledger` is ok.
   - The same `client_key` again returns the same `gold_seq` with `duplicate` true (no row).
   - A second adjudication of the round is a conflict.
   - A direct insert of the same `(item_id, review_round)` that extends the chain (the next seq, the head's hash) is refused by `uq_v3_gold_labels_item_round`.
   - Apply adds no gold row and changes no ledger row.

**AC-6-5**

6. **`test_ac_6_5_zero_errors_in_300_audited_items_bound_the_residual_below_1_3_percent`.**
   - `wilson_upper(0, 300) == evaluation.qcai_eval.statistics.wilson_interval(0, 300)["upper"]`, exactly, and it is below 0.013.
   - `math.isclose(wilson_upper(0, 300), z*z/(300+z*z), rel_tol=1e-12)` with the harness z (the two evaluations differ in the last bit, M8).
   - The 1/300 and 3/300 values.
   - The report fixture's `residual` gives 300 audited, 0 errors, an upper below 0.013, and `harness_equal` true.

**AC-6-6**

7. **`test_ac_6_6_a_learner_flag_sets_f_i_to_zero_and_changes_no_verdict_or_ledger_row`.**
   - A demo learner's `POST /assistant/chat` gives a turn, its legacy record and its shadow v3 record. After `POST /v3/flags`: 200, `f_i` 0.0.
   - `f_i(db, seq) == 0.0`, and there is an X3 response item on the legacy record.
   - Both records' rows are unchanged, the ledger holds no new row, and the shadow record's verdicts (`v1`, `v2`, `final`, `v3`) are unchanged.
   - A second flag is a duplicate: one `v3_flags` row.
   - Another learner gets 404. An unflagged record's `f_i` is `None`.
   - No property reachable from any `ENTRY_SCHEMAS` model's JSON schema is named `f_i`, `feedback`, `flag`, `flags`, `learner_flag` or `learner_rating`. The only `rating` is `AlignmentVote.rating`, a verifier's alignment rating (M21) (invariant 5).

**AC-6-7**

8. **`test_ac_6_7_a_guest_on_every_reviewer_route_gets_403_and_one_access_log_entry`** (parametrized: development with `V3_QUEUE` off and shadow, and staging with `V3_QUEUE` off and shadow).
   - The guest carries a signed guest token, a trusted Origin and the CSRF header (as `test_authorization._guest()`), so the request reaches the route. In staging the token is signed with the staging secret and the process settings the CSRF guard reads are the staging ones.
   - In staging no reviewer is admitted (D-18), so a guest's refusal naming the role, never the pool, proves the role check comes first.
   - For every route whose policy access is `reviewer`, the guest gets 403 and exactly one new `authz.denied` event, `{"route": <template>, "required": "role:reviewer", "provider": "guest"}`. No `request.forbidden` event is recorded.

**Plan J, L, B, H, G, I, F, E; invariants; freeze; 13.6**

9. **`test_plan_j_with_no_reviewer_every_item_stays_withheld_and_queued`** (fresh database).
   - Setup: an X1 item and a `v2_degraded_withheld` item; `now` moves 30 days with no claim.
   - Both stay `queued` and the X1 item `held`.
   - `withheld_claim_ids` is unchanged.
   - `stop_state` is active.
   - The ledger is unchanged.
10. **`test_plan_l_disabling_v3_releases_no_withheld_item`.**
    - With `V3_QUEUE=off`: the reviewer routes give 404 to a reviewer (valid bodies); the scan raises `V3Off`; the flag route gives 404.
    - Queue rows, holds and F_i are unchanged. A DELETE on `v3_queue_items` is refused by its trigger.
    - The stop computed from the stored queue (fresh database, aged items) is still active. A tier-1 V2 run whose pipeline uses that database is still pre-verified-only.
    - Re-enabling shows the same items.
11. **`test_plan_l_queue_age_above_the_slo_for_two_days_withholds_tier_1`.**
    - `stop_state` cases:
      - an item open since `now - (SLO + 48 h + 1 h)`: active;
      - once that item is closed: clear;
      - above the SLO only for the last 47 h: clear;
      - an old item plus many young items whose p90 age is below the SLO: still active (the oldest-age measure);
      - an unreadable queue: `tier1_withheld` true and `v3.stop_unread` logged.
    - With `v3_stop=lambda: True`, a tier-1 run (query 30, `on`) records the following:
      - `kill_switch "pre_verified_only"`;
      - no call;
      - every claim withheld in ZERO;
      - the response abstaining (`v2_kill_switch`);
      - `tutor.v2.v3_stop` logged.
    - A tier-2 run (`TIER2`) is unaffected, and under `shadow` the finals are Phase 4's.
12. **`test_plan_l_v3_queue_defaults_and_refusals`.**
    - The defaults (shadow in development, off elsewhere).
    - `on` is refused outside development before the exit.
    - A package claiming the exit admits it, and the override is recorded (`v3_queue_on`). `shadow` outside development records `v3_queue_shadow`.
    - A start-up subprocess with `V3_QUEUE=on` outside development exits non-zero.
    - A v3 package problem stops a governed start-up only when V3 is requested; otherwise `/ready` `v3.available` is false and the mode is off.
13. **`test_plan_b_no_reviewer_is_admitted_outside_development_while_d_18_is_open`.**
    - With staging settings (demo auth on, a 32-character guest secret), a demo reviewer gets 403 with `required "reviewer_pool:D-18"` on every reviewer route.
    - With `LEDGER_ROUTE_ENABLED` on as well, the demo reviewer reads another learner's turn and a shadow record as the same 404 as a missing id. No `ledger.reviewer_read` event is recorded.
14. **`test_plan_h_reviewers_see_public_quotable_spans_only_and_no_learner_identifier`.**
    - Every queue and item payload holds no user, turn, thread, message, shadow, qa- or response id, no email, no ledger seq, no severity, exposure, support share or priority.
    - Over a governed store (D-31: nothing quotable), every span `shown` is false and every claim `text` is null. Every such item is `reviewable: false`, and claim gives 409 `not_reviewable`.
    - A span record outside the public plane is not shown.
    - The import rule (7.1).
15. **`test_plan_g_the_phase_6_revision_is_additive_reversible_and_keeps_its_rows`** (`fresh_database_url`).
    - From a Phase 5 stamp, `alembic upgrade head`, then `alembic check`; `SCHEMA_REVISION` is the single head.
    - With a flag, a queue item or a gold row present, `downgrade 20261122_phase5_gateway_controls` fails with "export first" and names the counts.
    - With `-x allow_v3_drop=true` it succeeds: the eight tables are gone and every other table is intact.
16. **`test_plan_g_pre_ledger_deliveries_are_reported_as_non_auditable`.** A tutor turn with `ledger_record_expected` null and no record is counted in `non_auditable.tutor_turns` and never drawn. Q&A interactions created before `ledger_started_at` are counted. The kill-switch turns, lost records and pending appends are counted apart (`test_non_auditable_reports_pre_ledger_turns_apart_from_kill_switch_turns_lost_records_and_pending_appends`).
17. **`test_plan_i_ready_reports_package_v5_and_the_v3_fields_and_no_count`.**
    - The 10.2 fields equal the package's.
    - `_build_fields()` is unchanged after a chat, a flag and a scan, and makes no statement beyond the shared gateway stop's.
    - No key of `v3` equals `count`, `open`, `depth`, `seed`, `head` or `stop`.
18. **`test_plan_i_v3_slis_report_the_escalation_share_queue_age_draws_agreement_and_residual`.** A fresh-database scenario with an injected clock checks:
    - the share `m/n` with X5/X6 not counted, and a shadow item counted on its shadowed delivery's seq;
    - age p90 nearest-rank and the oldest age;
    - draws;
    - one double-review pair agreeing and one disagreeing (a third round);
    - the residual by month;
    - the stop;
    - the gold rows.
19. **`test_plan_f_the_trigger_registry_document_matches_the_package`.**
20. **`test_plan_f_the_committed_residual_report_matches_a_fresh_run_and_names_its_evidence_class`.** The record equals the fresh run except `created_at`, `commit`, `inputs` and `gold.head_record_hash`, and its `inputs` match the checkout.
21. **`test_plan_e_only_two_v3_tables_hold_a_person_s_id_and_erasure_reaches_them`.**
    - Only `v3_claims` and `v3_flags` have a `USER_KEY_COLUMNS` column.
    - `erase_user` deletes a reviewer's lease (the item reads `queued`) and round records, and a learner's flags (F_i stays 0).
    - No append-only V3 table is user-keyed.
22. **`test_invariant_5_a_flag_feeds_quality_only_and_never_a_verdict`.** The schema test of AC-6-6, plus `f_i` and `V3Flag` being read by the feedback service only.
23. **`test_invariant_6_no_x1_claim_is_delivered_under_any_fault_schedule`.**
    - 300 seeded fault schedules run on query 30 under `on`, in the pattern of Phase 5's `test_invariant_6_no_v2_delivery_without_a_completed_passing_vote`.
    - A schedule takes members down, makes them late, fails them on chosen calls, or has them object on chosen claims; half run with a cache that never hits.
    - The schedules include the class where an objecting member fails a later call.
    - No X1 claim has final `deliver`, and every X1 claim is in `withheld_claim_ids`.
24. **`test_freeze_outside_development_v3_is_off_and_no_learner_path_changes`.**
    - Under production-like settings: the V3 mode is off; the flag route gives 404 to an authenticated learner, under `V3_QUEUE=shadow` as well; reviewer routes give 403.
    - A legacy `POST /assistant/chat` writes no V3 row, and `/ready` `v3_queue` is off.
    - The Phase 5 golden test (`test_freeze_public_payloads_with_shipped_non_development_settings_are_byte_identical_to_phase_4`) is unchanged.
25. **`test_plan_13_6_flag_combinations_with_v3_queue_never_release_or_reach_learners`.**
    - The axes: ENVIRONMENT × V3_QUEUE × MODEL_GATEWAY × TWO_PASS_TUTOR.
    - A combination is refused exactly when 6 says so.
    - Outside development the V3 mode is off unless `shadow` is set explicitly, and the flag route is 404 in every combination.
    - No combination yields a `delivered` record or a released hold.
26. **`test_plan_c_the_metrics_count_gold_claims_toward_the_dawid_skene_minimum`.** `gold.claims_labelled` and `dawid_skene_minimum 200`; no tier-3 weight changes.
27. **Doc tests:**
    - `test_phase6_spec_section_3_lists_the_code_s_fields`;
    - `test_phase6_docs_quote_the_plan_and_state_the_current_rules`: plan L, K and D task 1 and 3 quoted exactly; PD-32..PD-39 and DI-89..DI-103 in this spec; `V3_QUEUE` in the spec, the runbook and the env example;
    - `test_phase6_docs_name_the_logger_each_phase6_event_logs_on`: 10.3, read from the source; every `"v3.*"` event the code logs is listed in 10.3 and in the observability runbook, and the worker row names its fields;
    - `test_phase6_docs_the_phase_3_rollback_checks_the_stamp_against_the_current_head`: the Phase 3 rollback's stamp list names `ledger.SCHEMA_REVISION` as the only head, with the Phase 6 and Phase 5 downgrade steps;
    - `test_phase6_docs_the_test_strategy_maps_every_test_module_the_phase_added` (with `PHASE6_EXTENDED_MODULES`);
    - `test_phase6_docs_the_texts_phase6_made_false_state_the_current_code`: 7.4, `tiers.py`, `v1_5_abstention.py`, `ledger.pending_v3_intents`, the ledger route's docstring, Phase 5 R-e and 4.8;
    - `test_phase6_docs_the_spec_ends_in_one_review_history_table`.

**E15** (in `test_phase5_acceptance.py`): `test_phase5_docs_the_records_name_the_merge_and_the_cited_main_run`.
- The Phase 5 spec's DI-74 row, its section 17 exit bullet and the test strategy's Phase 5 exit paragraph each name `c34a8c1`, `8aa4ff1` and `45044415408`.
- None says "the cited run follows the merge", "each later commit needs its own run" or "the cited run must be on `main`".

### 13.2 Unit test files and helper modules

| File | Proves |
|---|---|
| `test_v3_triggers.py` | One test per trigger (plan J), each over the function the scan or the flag path runs.<br>X1: final objection; a claim-loop correction-cycle listing (an alignment re-render is not one); not critical; no V2; at tiers 2 and 3 it fires and is not held (`test_x1_fires_at_every_tier_and_holds_at_tier_1_only`); a registry claim at tier 2 with one objection passes 2oo3, is delivered, and is queued and counted in V-3 without a hold (`test_x1_fires_on_a_critical_tier_2_claim_that_passes_2oo3_and_queues_and_counts_it_without_a_hold`).<br>X2: A or B required, as family-level types; C-D queued as a reason.<br>X3 (`x3_fires`, which `record_flag` asks; AC-6-6 covers the path).<br>X4: the V1.5 mark on verified records equals the `x4_margin` intent (query 139 is the development fixture's near miss); the sufficiency rule on legacy records; p1-floor with a score never marks; a missing score marks; a sufficiency abstain never marks; the scan enqueues the X4 response item with severity 1, its exposure and its priority (`test_the_scan_enqueues_an_x4_response_item_with_its_severity_and_priority`).<br>X5: a known key with a new version; an unknown key is no change; baseline when empty; `x5_active` windows.<br>Queue reasons: the record's own intent; under `on` a completed vote drops `v1_3_flag`; a V2-shadow record's V1.3-withheld claims are queued, so the holds and the queue agree (`test_a_v2_shadow_record_s_v1_3_withheld_claims_are_queued_so_the_holds_and_the_queue_agree`).<br>Type helpers: a disclosed conflict weighs nothing.<br>An unknown `entry_schema` is unparsed. |
| `test_v3_draw.py` | `u64` and `bernoulli` exact integer rule, at the boundary where a float comparison differs; monotone rates.<br>Each delivery considered exactly once under 200 random splits of scan batches (seeded `random.Random`, 40 deliveries copied by sqlite3's backup API) with X5 events arriving mid-stream.<br>An X5 window covers the next learner deliveries, and its draws are X5 only between 1/20 and 1/5; a window closes after its deliveries.<br>A model-version change between scans (a registry verifier's, and a record's verifier vote's) is one `model_change` event and raises the next deliveries to 1/5 (`test_a_model_version_change_between_scans_records_one_x5_event_and_raises_the_next_deliveries_to_1_5`).<br>Shadow records are never drawn; `unparsed` deliveries are still drawn.<br>`claim_set_key` is order-free and null for an abstention. |
| `test_v3_priority.py` | Severity: max weight; unknown 1.0; the plan weights exact.<br>K: support share; mean; 0 without a vote; withheld 0.<br>Exposure: claim-set key count up to the record; 1 for shadow, abstention and no key; at least 1 before the record's draw; an X3 item's exposure and priority are the same whether the flag or the scan came first (`test_an_item_s_exposure_and_priority_do_not_depend_on_whether_a_flag_or_the_scan_came_first`).<br>Ordering over an exhaustive grid of severity × exposure (1-3) × K (0, 1/3, 1/2, 2/3, 1) against a reference sort; the tie-break. |
| `test_v3_workflow.py` | States and derived `claimed`; lease expiry returns to queued; idempotent claim.<br>The conflicts; independent review refused; double-review selection is the seeded rule; agreement closes; disagreement goes to a third reviewer; apply by an adjudicator refused.<br>`test_independence_survives_a_guest_secret_rotation`: the same reviewer is refused the second round and apply after `guest_token_secret` changes.<br>Idempotent adjudicate and apply by client key; a repeat logs no `v3.adjudicated` or `v3.applied`.<br>A late trigger on a closed item is recorded and not reopened (a scan's merge after an adjudication).<br>Two concurrent claims leave exactly one lease row, and the other call is refused with `claimed_by_another` on file SQLite and on PostgreSQL (a SQLite lock is retried).<br>A SQLite "database is locked" error is retried by every mutation and by the scan, and one that outlasts the attempts is `V3Busy` (`test_a_sqlite_lock_is_retried_and_one_that_outlasts_the_attempts_is_busy`).<br>Erasing a reviewer deletes the lease and round records. |
| `test_v3_gold_store.py` | The chain and its hash rule.<br>UPDATE, DELETE and TRUNCATE refused, and an insert that does not extend the chain refused, on SQLite and PostgreSQL (psycopg, pg8000).<br>`verify_gold_store` finds an edited entry, a gap and a broken link (triggers dropped on a fresh database).<br>Export and `--all`; an export into the application tree or the repository checkout is refused and writes nothing (`refused_export_roots` over a checkout and an image layout).<br>The other append-only V3 tables refuse UPDATE and DELETE; `v3_queue_items` refuses DELETE. |
| `test_v3_stop_and_metrics.py` | `stop_state` sampling, the oldest-age measure, empty samples, the cache (per session factory) and its seam, transition logs, the fail-closed unreadable queue.<br>Nearest-rank p90; non-auditable counts, the pre-ledger turns apart from kill-switch turns, lost records and pending appends.<br>The residual bound is null with `no_audited_answers` while nothing (or only an abstention) is audited (`test_the_residual_bound_is_null_while_nothing_is_audited`).<br>X5 alarms through `record_cusum_alarm`: synthetic alarms; `synthetic-test` refused outside development; the contract's `statistic >= h` and `p0 < p1`. |
| `test_v3_routes.py` | Each route's 200 shape on seeded items and its security event (seq-ordered), a repeated apply's `duplicate` included; 404 when off; item ids outside the pattern 404.<br>A locked database is retried and a lock that outlasts the retries answers 503 with no security event (`test_a_locked_database_is_retried_and_a_lock_that_outlasts_the_retries_answers_503`).<br>409 and 422 reasons, `not_reviewable` included (`test_an_unreviewable_item_cannot_be_claimed_or_adjudicated`).<br>The scan route.<br>The flag route's ownership (also in `test_authorization.py`), its 409, its rate limit and its 404 outside development (`flag_intake_open`).<br>`Cache-Control: no-store`. |
| `test_config_package.py` (additions) | `test_v4_stays_readable_for_one_release`; `test_v5_keeps_every_v4_value_but_the_listed_changes`; `test_v5_structural_errors_always_stop_the_load` (each 5.2 refusal, the v2 critical registry included); `test_v3_package_check_problems`; `test_the_v3_start_up_check_runs_from_the_image_layout` (the module executed as the image holds it: no problem with `structural=False`) |
| `v3_fakes.py` | Not a test module (13.1) |
| `conftest.py` (addition) | The autouse fixture also calls `v3.stop.reset_stop_cache()` before and after each test, and fails a test that leaves a shared-database queue item enqueued before the session start |

### 13.3 Existing tests that change (intent kept; each commit message says why)

1. **`test_config_package.py`.**
   - The shipped package is "5.0.0", schema 5, with `package.v3` set.
   - `V4_RAW` reads `V4_PACKAGE_PATH` for `test_v4_keeps_every_v3_value_but_the_listed_changes` and for every `test_v4_*` assertion on v4-only values.
   - `test_v4_structural_errors_always_stop_the_load` applies its refusals to `v4.json` and to the shipped v5. For v5 the `schema_version=5` edit becomes `schema_version=6`, the one edit that is a no-op on v5.
   - `test_v3_structural_errors_always_stop_the_load` applies its refusals to v3.json, v4.json and v5.
   - `test_v3_stays_readable_for_one_release` compares `canonical_sha256(V3_RAW)` with `V4_RAW["supersedes"]["sha256"]`.
   - `test_gateway_package_check_problems` also checks v4.json; it reads the default package, which keeps the gateway block.
2. **`test_phase4_acceptance.py`.**
   - The Phase 3 spec's constants line names `.../{shipped}` with Phase 6 (v5).
   - The test lines read `f"{PACKAGE.package_version} for Phase 6's v5"`, and the `RAW` line "(v5 since Phase 6)".
   - A five-group loader regex `("1", "2", "3", "4", "5")` and "…, 4 since Phase 5, and 5 since Phase 6".
   - The report shape reads "for Phase 6's v5, which the committed record holds".
   - The budgets equality adds v4, the path sets assert `paths["v4"] == paths["v5"]`, and the expected texts read "v5 since Phase 6".
3. **`test_phase5_acceptance.py`.**
   - `test_plan_i_ready_reports_package_v4_and_the_gateway_state_and_no_per_run_outcome` asserts `body["config_package_version"] == PACKAGE.package_version`; the name is kept, because the BEP records cite it.
   - The Phase 4 spec's loader line reads "`schema_version in (1, 2, 3)`, and 4 since Phase 5 and 5 since Phase 6".
   - Plus the E15 test (13.1).
4. **`test_phase3_acceptance.py`.**
   - `test_plan_g_the_alembic_revision_is_reversible_and_refuses_to_drop_a_non_empty_ledger` also excludes the eight Phase 6 tables from its initial `create_all` and steps down through the Phase 6 revision (empty V3 tables), then the Phase 5 one.
   - `test_plan_i_ready_reports_versions_ledger_head_and_two_pass_mode` is unchanged, because the V3 fields read nothing.
   - The ledger-route tests run in development, so they are unchanged by the D-18 gate.
5. **`test_response_ledger_migrations.py`.**
   - `PHASE6_REVISION` and `PHASE6_TABLES` are added.
   - e10 stamps `PHASE6_REVISION`, runs `alembic check`, then goes down to `PHASE5_REVISION` (the eight tables gone; the V3 tables empty), then as before.
   - f14 applies Phase 3, Phase 5, then Phase 6, then `alembic check`.
6. **`test_authorization.py`.**
   - `KINDS` adds `demo_reviewer`, and `ALLOWED_KINDS` adds `authz.REVIEWER: {"demo_reviewer"}`. `demo_reviewer` is refused at `asset_reader`, `durable_learner`, `staff` and `admin` (its role is outside those sets).
   - `_actual_access` maps `{frozenset({"reviewer"})}` to `authz.REVIEWER`.
   - `test_there_are_negatives_for_every_restricted_access_level` adds `REVIEWER`.
   - A new test, `test_every_route_names_roles_of_the_closed_role_set`: every route's role set is a subset of `authz.ROLES`.
   - `_concrete` adds `"item_id": "v3i-" + "0" * 24`.
   - `OWNERSHIP_TESTED` adds `("POST", "/v3/flags")`, with the new `test_another_learners_turn_cannot_be_flagged` (404 for another's and a missing turn).
   - `test_a_role_denial_is_a_security_event` counts against a fresh denial cap: the reviewer negatives record more denials than one minute's cap (M6), and a capped denial is dropped by design.
   - The committed matrix is regenerated (the ledger route's note gains the D-18 clause).
7. **`test_configuration_overrides.py`:** cases for `v3_queue_shadow` and `v3_queue_on` (refused, still recorded when present).
8. **`test_v2_correction.py` (additions):**
   - `test_a_critical_tier_1_claim_is_never_revised_and_ends_with_x2`;
   - `test_a_critical_tier_1_claim_stays_held_when_its_objector_leaves_the_panel`.
   - The existing revise tests are unchanged, because their queries lock no registry claim (M10).
9. **`test_v2_panel.py` (additions):**
   - `test_the_v3_stop_runs_tier_1_through_the_pre_verified_only_path` (an injected `v3_stop`);
   - `test_the_v3_stop_reads_the_pipeline_s_own_database`: a pipeline over a fresh database with aged items is stopped, while the shared database is clear;
   - `test_critical_for_reads_the_environment_s_registry`.
10. **Records:** the three records of 12.2.
11. **Expected unchanged:**
    - the Phase 3 doc and listing guards;
    - the section-3 field tests of Phases 3-5;
    - `test_erasure_retention.py` (the new user-keyed tables seed and erase through its generic helpers);
    - `test_security_log.py` and `test_structured_logging.py`;
    - every Phase 5 V2 test, `test_invariant_6_no_v2_delivery_without_a_completed_passing_vote` included (its queries lock no registry claim);
    - every frontend test.

### 13.4 Frontend tests (`apps/frontend/tests/v3-review.integration.test.ts`)

- `reviewerUiEnabled` is false in production and true in development.
- `v3ModeFromReady` maps a missing or off mode to `"off"`.
- The page source calls `notFound()` on both conditions and sets `index: false`.
- `primary-nav.tsx`, `site-footer.tsx` and `lib/navigation.ts` name no `/review`.
- `reviewerHeaders` admits only the synthetic names, with role `reviewer`.
- `adjudicationPayload` sorts the labels and nulls a SUPPORTED label's EHMF type.
- No label text matches `/verified|grounded/i`.
- The console renders span text only for `shown` spans, offers Claim and Adjudicate only for reviewable items, and names no severity, support share, priority or browser storage (source match).
- `adjudicationReady` refuses an unset verdict, a non-SUPPORTED verdict without a type and an abstention item without its label; the console pre-fills no label, gives each of its four selects a label, keeps one mounted `role="status"` region, catches a failed item read, and disables the EHMF select for SUPPORTED (source match).
- The review page renders no second `<main>` inside the app shell's; no trigger label names an objection type or a tier.
- Lint, typecheck and `test:integration` run with the new tests (165 tests).

### 13.5 Mutation checks (each must fail its tests when reverted; recorded in the BEP phase record)

Every row below has been performed: a run reverts the rule, runs the tests named, which must fail, and restores the file byte for byte. The BEP phase record lists each run (the build's, then each review round's) and any first run that was not caught, whose tests were then strengthened.

| Mutation | Tests that must fail |
|---|---|
| E15: the Phase 5 spec's pre-merge DI-74 and exit text restored | `test_phase5_docs_the_records_name_the_merge_and_the_cited_main_run`; `check_p5_merge_the_records_name_the_merge_and_the_cited_main_run` |
| X1 ignoring correction-cycle failures | tests 1 and 23 |
| X1 firing without `critical` | `test_v3_triggers.py` |
| X1 at tier 1 only again | `test_x1_fires_at_every_tier_and_holds_at_tier_1_only`, `test_x1_fires_on_a_critical_tier_2_claim_that_passes_2oo3_and_queues_and_counts_it_without_a_hold` |
| X1 held at every tier (`held` from the trigger, `withheld_claim_ids` from `x1_claims`) | `test_x1_fires_at_every_tier_and_holds_at_tier_1_only`, `test_x1_fires_on_a_critical_tier_2_claim_that_passes_2oo3_and_queues_and_counts_it_without_a_hold` |
| The runner revising a critical claim | `test_a_critical_tier_1_claim_is_never_revised_and_ends_with_x2`, test 1 |
| The hold not sticky (a held claim leaves `pending` once it passes) | `test_a_critical_tier_1_claim_stays_held_when_its_objector_leaves_the_panel`, tests 1 and 23 |
| `critical_for` ignoring the environment | test 1 (the staging case) |
| X2 counting C-E | `test_v3_triggers.py` |
| `v1_3_flag` dropped once a vote completes (the V3-side rule; a V2-shadow record's V1.3-withheld claims unqueued) | `test_a_v2_shadow_record_s_v1_3_withheld_claims_are_queued_so_the_holds_and_the_queue_agree`, `test_queue_reasons_keep_the_record_s_own_intent_and_x4_is_the_response_item` |
| The scan recording baselines but never a model change (its sightings not through `x5_model_changes`) | `test_a_model_version_change_between_scans_records_one_x5_event_and_raises_the_next_deliveries_to_1_5` |
| `x5_model_changes` naming no change | `test_a_model_version_change_between_scans_records_one_x5_event_and_raises_the_next_deliveries_to_1_5`, `test_x5_a_known_key_with_a_new_version_is_a_change_and_an_unknown_key_a_first_sighting` |
| The scan dropping X4 items, or scanning with no X4 margins | `test_the_scan_enqueues_an_x4_response_item_with_its_severity_and_priority` |
| `record_flag` not asking `x3_fires` (no X3 item) | test 7 |
| The draw redrawing on a re-scan | test 3, `test_v3_draw.py` |
| X5 windows ignored | `test_v3_draw.py` |
| A float draw | `test_v3_draw.py` (exact boundary) |
| Priority ignoring K | test 4, `test_v3_priority.py` |
| Exposure ignoring the claim-set key (always 1) | test 4, `test_v3_priority.py` |
| The scan not raising an earlier item's exposure (`refresh_exposure` skipped) | `test_an_item_s_exposure_and_priority_do_not_depend_on_whether_a_flag_or_the_scan_came_first` |
| The tie-break reversed | `test_v3_priority.py` |
| The adjudication writing a ledger row | test 5 |
| A second gold row per round allowed | test 5 |
| Gold UPDATE allowed (trigger removed) | `test_v3_gold_store.py` |
| `verify_gold_store` skipping `record_hash` | `test_v3_gold_store.py` |
| Same reviewer twice | `test_v3_workflow.py` |
| Independence read from `reviewer_digest` | `test_independence_survives_a_guest_secret_rotation` |
| Adjudicator applying | `test_v3_workflow.py` |
| Lease expiry ignored | `test_v3_workflow.py` |
| Client keys ignored | test 5, `test_v3_workflow.py` |
| A repeated apply logging `v3.applied` | `test_adjudicate_and_apply_are_idempotent_by_client_key` |
| A SQLite lock not retried | `test_a_sqlite_lock_is_retried_and_one_that_outlasts_the_attempts_is_busy`, `test_a_locked_database_is_retried_and_a_lock_that_outlasts_the_retries_answers_503` |
| An export into the repository checkout allowed (the application tree only) | `test_export_writes_the_applied_finals_or_every_row_and_refuses_the_application_tree_and_the_repository` |
| An unreviewable item claimable | test 14, `test_an_unreviewable_item_cannot_be_claimed_or_adjudicated` |
| The flag changing a ledger row | test 7 |
| The flag route open outside development | tests 24, 25 |
| F_i read from the flag table | test 21 |
| `require_reviewer` checking D-18 before the role | test 8 (its staging cases) |
| The D-18 gate removed | test 13 |
| The ledger route's reviewer branch without `reviewer_admitted` | test 13 |
| Views showing an unquotable span | test 14 |
| Views showing severity, K or priority | test 14 |
| `stop_state` passing on one sample | test 11 |
| The stop measured by p90 | test 11 (the diluted case) |
| `tier1_withheld` failing open | test 11 |
| The default V2-track stop reading the global `SessionLocal` | `test_the_v3_stop_reads_the_pipeline_s_own_database` |
| The stop computed only when V3 is on | test 10 |
| Disabling V3 deleting items (trigger removed) | test 10 |
| The fixture-path check at start-up | `test_the_v3_start_up_check_runs_from_the_image_layout` |
| The downgrade guard covering gold only | test 15 |
| `/ready` reporting a count | test 17 |
| V-3 counting X6 | test 18 |
| The residual counting X5 or abstentions | test 18 |
| The residual's empty bound reported as 0 | `test_the_residual_bound_is_null_while_nothing_is_audited` |
| The non-auditable tutor turns counting lost records and kill-switch turns | `test_non_auditable_reports_pre_ledger_turns_apart_from_kill_switch_turns_lost_records_and_pending_appends` |
| The report's stale module hash | test 20 |
| The loader accepting a non-empty staging registry, a rate other than 1/20, unplanned weights, an unmarked `v3` sub-block, or a non-empty v2 critical registry | `test_v5_structural_errors_always_stop_the_load` |
| The frontend page without `notFound` | the frontend test |
| The console pre-filling SUPPORTED, or the page rendering a second `<main>` | the frontend tests (13.4) |
| The Phase 3 rollback's stamp list without the Phase 6 head | `test_phase6_docs_the_phase_3_rollback_checks_the_stamp_against_the_current_head` |
| 10.3 or the observability runbook without a worker event | `test_phase6_docs_name_the_logger_each_phase6_event_logs_on` |

---

## 14. CI changes (`.github/workflows/ci.yml`, job `api-and-evaluation`)

After the v3 package check:

```yaml
      # Phase 6: configuration package v4 stays readable for one release (DI-100).
      - run: python scripts/config_package.py --check --path apps/api/app/config_package/v4.json
      # Plan Phase 6 F/K: the residual report (synthetic telemetry, not research results): the seeded draw over 6070 synthetic
      # deliveries, the Wilson bound of 0 errors in 300 audited items below 1.3% (AC-6-5), the gold chain and an unchanged ledger.
      - run: python scripts/run_v3_residual_report.py --check docs/evaluation/phase6/v3_residual_report_v1.json
```

The v1, v2 and v3 checks stay. The PostgreSQL matrix, the frontend job, `api-image-boundary-scan` and `release-artifacts` are unchanged; the new tests run in both API suites. No CI step makes a network call beyond `pip install`, `pip-audit` and `npm audit`.

---

## 15. Docs and evidence

1. **This spec** as `docs/architecture/phase6-implementation-spec.md`, LF.
2. **`docs/adr/ADR-009-v3-audit-and-adjudication.md`:**
   - `## Context` (E-63, E-74, E-82, E-84, E-85, E-86, E-95, E-105, R-22, R-35, R-40, R-49; holds H4, H10);
   - `## Decision 2026-11-22 (Phase 6: V3 audit and adjudication)`;
   - `## Consequences`;
   - `## Residuals`. Plan M is quoted exactly: "[Risk R-22][Risk R-49][Risk R-35]; residual: reviewer error, bounded by double review." It also covers:
     - no reviewer outside development (DI-91);
     - authorship-based conflict of interest, and the erased reviewer's rounds (DI-99);
     - the CUSUM statistic (DI-96);
     - recalibration (DI-93).
3. **ADR-006:** `## Revision 2026-11-22 (Phase 6: the reviewer role and the V3 access log)`. It covers the closed role set, `require_reviewer`, `reviewer_admitted` (V3 routes and the ledger route's reviewer branch), the security events, the keyed digests as pseudonymous evidence, and the user-keyed round records.
4. **ADR-008:** `## Revision 2026-11-22 (Phase 6: critical claims, the V3 stop and the queue)`. It covers 4.13 (the sticky hold, the stop read through the pipeline's database) and the queue's consumption of the V3 intents.
5. **Plan F:**
   - `docs/architecture/v3-trigger-registry.md`;
   - the reviewer UI (11);
   - the runbook (item 7);
   - the gold store (4.6);
   - the residual report (12.1).
6. **`docs/evaluation/phase6/README.md`.**
7. **`infra/cloudrun/deployment.md`** gets `## Phase 6: V3 audit and adjudication (runbook)`:
   - the D-05 cloud writes (none made);
   - what ships and its defaults;
   - the pre-release checks: check the stamp first (`alembic current`), then `alembic upgrade 20261122_phase6_v3_audit`;
   - what ships says the reviewer routes answer 403 (and `authz.denied`) to every caller outside development, the flag route 404, and that legacy ledger records stamp package 5.0.0 and `schema_revision_expected` `20261122_phase6_v3_audit`;
   - the `/ready` checks (`v3_queue` off, `v3.reviewer_pool` unstaffed);
   - the worker commands, and that outside development the worker's `status` is the only SLI source (its schedule is DI-95);
   - the stop and what it does, and its development behaviour (4.10: it trips 120 h after the first item nobody closes; adjudicate or use a fresh database), and the warning that under the shadow override outside development nothing can clear it while D-18 is open (DI-103);
   - rollback: `V3_QUEUE=off` releases nothing;
   - `export-gold --all` before a downgrade past the revision, with `-x allow_v3_drop=true`; what the downgrade loses that no export keeps (the queue with F_i, the flags, the draws and the once-only record, the X5 windows); that no path restores the gold rows; and the export's handling and retention rule;
   - the Phase 3 rollback's stamp check names the Phase 6 head (`20261122_phase6_v3_audit (head)`: the Phase 6 downgrade step, then the Phase 5 step);
   - a digest rollback needs no downgrade;
   - a guest-secret rotation changes new digests only and readmits no reviewer.
8. **`infra/cloudrun/observability.md`** gets `## Phase 6 SLIs: V3 (plan Phase 6 I)`:
   - each SLI's log-based metric (V-3, queue age p90 and oldest age, draws, agreement, residual), all "Not set up yet" (DI-95), and that the residual bound is null while nothing is audited;
   - the SLI source outside development (the worker's `status` line only, while D-18 is open) and the scheduled job DI-95 defines;
   - every 10.3 event and its logger;
   - the two override keys.
9. **`docs/testing/test-strategy.md`:**
   - the E15 exit edit (17);
   - `## Phase 6 acceptance map (plan Phase 6 K)`, with `### Phase 6 test files`, `### Phase 6 changes to existing test modules` and an `**Exit gate.**` paragraph.
10. **The Phase 3, 4 and 5 specs:** the 7.4 edits.
11. **BEP-2-12** (outside the repository):
    - `phase06/PHASE_RECORD.md` (current state first, with "The exit gate is NOT passed (DI-89)." and `### Open items` listing DI-89..DI-103, then `## History`, one row per round);
    - `phase06/CLOSURE_EVIDENCE_NOTES.md` (R-22, R-35, R-40, R-49);
    - PD-32..PD-39 and DI-89..DI-103 under `## Phase 6` in the registers (the PD rows add `| 6 |`), and the provisional defaults register's header naming the Phase 6 engineering parameters;
    - STATUS row 6;
    - `check_records.py` `check_p6_*` checks mirroring `check_p5_build_*`:
      - the registers hold the spec's rows;
      - the phase record states the exit not passed and lists every open item;
      - every cited test exists;
      - the plan holds the text v5 quotes (D-25 18.4 text, H4 and H10 cells);
    - the E15 edits (17).

---

## 16. Provisional defaults and deferred items (appended under `## Phase 6`)

### 16.1 Provisional defaults

| # | Decision | Plan text | Default applied | Where |
|---|---|---|---|---|
| PD-32 | Trigger registry v1 and the queue (no owner decision names the rules; engineering parameters like PD-27) | Phase 6 D task 1: "X1 critical-claim objection (registry [Decision D-25]; withheld at tier 1); X2 Type A/B unresolved after two cycles; X3 learner flag (F_i = 0, never a verdict); X4 abstention margin [Decision D-06]; X5 CUSUM alarm or model change (audit 20%); X6 audit draw." | `x-triggers-v1`.<br>X1: a claim the record marks critical, at any tier, that drew a family objection (its final verdict, or a claim-loop correction cycle that listed it); it is withheld at tier 1 only (AC-5-4: "critical claims follow X1 from Phase 6"; task 1: "withheld at tier 1").<br>X2: a claim the record escalates X2 with an objecting family verdict of EHMF type A or B.<br>X3: a learner flag on the learner's own tutor turn.<br>X4: the record's V1.5 mark, or the V1.5 rule over a record's sufficiency with the package's X4 margin.<br>X5: a model-version change of a known model key (registry or record) or a CUSUM alarm event.<br>X6: the seeded draw.<br>Queued with no X trigger, from the record's own V3 intent: `v1_3_flag` (under `on` the V2 aggregate drops it once a vote completes; a V2-shadow record keeps it, D-20), `v1_8_misconception`, `v2_degraded_withheld`, and `v2_correction_exhausted` without an A or B objection.<br>One item per record and claim, or per record. A later trigger merges into an open item and is recorded on a closed one. | v5 `v3.triggers`; `app/services/v3/triggers.py` |
| PD-33 | D-25 critical-claim registry (PI) and X1 | 18.4: "D-25 OPEN DECISION: critical-claim registry triggering X1 [Evidence E-86]. PI." | Every non-development registry is empty, so no claim is critical outside development and X1 never fires there. Development holds three synthetic entries: the claims the development pipeline locks for in-domain fixture query 30, an assessment context (tier 1) whose claims no other fixture query locks. A critical tier-1 claim is never revised by the generator. With an objection it is held for the rest of the response, ends abstained (X2) or withheld and is never delivered, and nothing in Phase 6 releases it (DI-93).<br>Engineering parameters (no plan value; Claude's, ratified under DI-98): the three synthetic development entries. | v5 `v3.critical_claims`, `owner_decisions.D-25`; `v2_panel/tiers.py`, `v1_checks/runner.py` |
| PD-34 | Queue priority (the plan's formula; weights pending elicitation) | 6.3: "EHMF weights A=1.0, B=1.0, C=0.6, D=0.6, E=0.4 await expert elicitation [VBT RevB: p. 11, Sec. VI-C]; they MUST be versioned configuration, never constants (invariant 10)."; task 2: "Queue by severity x exposure x (1 - K); seeded 5% draw over ledger deliveries." | Priority = severity × exposure × (1 − K) in exact rationals, ties by enqueue time then item id.<br>Severity: the largest weight among the item's EHMF types (V2 objections and non-pass V1 results; a disclosed V1.7 conflict weighs 0, plan Phase 7 A "D 0.6 (0 when disclosed)"), 1.0 when no type is known.<br>Exposure: the learner deliveries the scan considered whose sorted claim ids hash to the record's claim-set key, up to its record, at least 1; 1 for a shadow or abstention record.<br>K: the support share of the claim's V2 panel (families voting SUPPORTED over members), the mean over a response's claims, 0 without a panel vote.<br>An item's exposure is its record's: an item created before the scan drew its record (an X3 flag) is raised to the record's count when the scan draws it.<br>Engineering parameters (no plan value; Claude's, ratified under DI-98): the exposure and K rules, the claim-set key and the tie-break; the plan's values are the formula and the 6.3 weights. | v5 `v3.priority`; `app/services/v3/priority.py`, `draw.py` |
| PD-35 | The audit draw (X6, X5) | Task 2: "seeded 5% draw over ledger deliveries"; 6.3: "version change -> X5 audit 20%, promotions held"; 15.3: "HR-3 deployment form: monthly Wilson bound from the 5% draw [Evidence E-85]." | Rule `seeded-sha256-bernoulli-v1`, seed `qcai-x6-v1`: a delivery is drawn when the first 8 bytes of sha256("x6-draw-v1\|seed\|response_id"), as an integer u, satisfy u·den < num·2^64.<br>X6 at 1/20. While an X5 window is open, 1/5: below 1/20 is X6, between 1/20 and 1/5 is X5. A window covers the 1500 learner deliveries after its event.<br>Population: every learner delivery (legacy or delivered, answers and abstentions), each considered once, at its first scan. Deliveries before the ledger are non-auditable.<br>The residual counts X6-audited answer deliveries, per UTC month; with none audited the bound is null, never 0.<br>Engineering parameters (no plan value; Claude's, ratified under DI-98): the rule `seeded-sha256-bernoulli-v1`, the seed `qcai-x6-v1` and the 1500-delivery X5 window; the plan's values are the rates (5%, 20%) and the monthly Wilson bound. | v5 `v3.draw`, `v3.triggers.x5`, `v3.residual` |
| PD-36 | The adjudication workflow and D-06's double review (operator policy) | Task 3: "Workflow queued -> claimed -> adjudicated -> applied; append-only gold store; 10% double review (operator policy, set under Decision D-06)."; 16.1: "the X6 auditor MUST NOT audit their own change [Risk R-35]" | A claim is a 30-minute lease; an expired lease returns the item to queued.<br>1/10 of items, drawn by `double-review-v1` on the item id, need a second independent review. A disagreeing pair goes to a third reviewer, whose label is final.<br>No reviewer reviews an item twice, and no adjudicator applies it, judged on erasable per-round records, never on a rotating digest.<br>Reviewers see the triggers and reasons, the claim texts and public, quotable spans only. The triggers and reasons say why an item is queued, so they disclose that an objection exists (X2's rule implies that one was of type A or B), never which family objected, a vote or the EHMF type it named. Reviewers are blind to the panel's votes and their objection types, the support share, the severity and priority, the finals and other rounds. An item whose claims cannot all be shown is not reviewable and stays queued.<br>Every adjudication appends one gold row; no restore path exists.<br>Applied exports the final label as recalibration input, changes no ledger row and releases nothing.<br>A trigger on a closed item is recorded, not reopened.<br>Engineering parameters (no plan value; Claude's, ratified under DI-98): the 30-minute lease, the third reviewer on disagreement, the three rounds and the double-review draw rule; the plan's value is the 10% double review. | v5 `v3.workflow`; `app/services/v3/queue.py`, `gold.py` |
| PD-37 | D-06's V3 SLOs and the stop (plan 13.7 OPERATIONAL TARGET rows) | L: "Stop (operator policy, set under Decision D-06): queue age above SLO for two days limits tier 1 to pre-verified content."; 15.3: "V-3 numerator counts X1-X4 only; audits are proof tests [Evidence E-85]." | Queue-age SLO 72 hours.<br>The stop holds when, at every hourly sample of the last 48 hours, the oldest open item is older than the SLO. That measure is strictly more conservative than the p90 and cannot be diluted by new items. The p90 is the alert's measure (plan I).<br>It applies the pre-verified-only policy to tier-1 responses. With no pre-verified source (PD-30), tier 1 is withheld (abstain and queue under `on`).<br>A queue that cannot be read counts as a stop.<br>V-3: deliveries with an X1-X4 item over learner deliveries, over a rolling 7-day window, at most 1/10, report only.<br>Engineering parameters (no plan value; Claude's, ratified under DI-98): the 72-hour queue-age SLO (plan 13.7 marks V3 queue age an OPERATIONAL TARGET, and "OPERATIONAL TARGET rows are the Product Owner's"), the hourly samples, the oldest-item measure and the rolling 7-day V-3 window (15.3 gives that window for F-1 and V-1 only); the plan's values are the two days, the tier-1 pre-verified limit, V-3 at most 10% and its X1-X4 numerator. | v5 `v3.slo`; `app/services/v3/stop.py`, `metrics.py` |
| PD-38 | `V3_QUEUE` and the reviewer gate (freeze, D-05; D-18 OPEN) | L: "Disabling V3 MUST NOT release withheld items."; B: "OPEN DECISION: reviewer staffing [Decision D-18]; production adjudication MAY start once staffed;" | Development `shadow`, elsewhere `off`; `on` refused outside development before `phase6_exit_passed`.<br>Shadow and on run alike, and nothing reaches a learner (DI-97). Off stops the scan, the draw, the flag intake and the reviewer routes, and releases nothing.<br>Reviewer routes need the closed role `reviewer`. Outside development every caller is refused while the pool is unstaffed (D-18), on the V3 routes and in the ledger route's reviewer branch. Development reviewers are synthetic demo identities.<br>The learner flag route exists in development only and allows 10 flags a minute.<br>Engineering parameters (no plan value; Claude's, ratified under DI-98): the 10-a-minute flag rate limit. | `config.py`; v5 `flag_policy.v3_queue`, `v3.reviewers`; `app/core/reviewer_access.py`, `app/api/routes/ledger.py` |
| PD-39 | X3, F_i and the gold label (no plan values) | Invariant 5: "Ratings never certify truth -> F_i feeds quality only; X3 feeds the V3 queue"; task 1: "X3 learner flag (F_i = 0, never a verdict)" | One flag per learner and tutor turn. F_i is 0 for a response with an X3 item and null otherwise.<br>A gold label (`v3-gold-label-v1`) holds, per claim, SUPPORTED, CONTRADICTED or NOT_ENOUGH_INFO with an EHMF type when not supported, and for an abstention `correct` or `missed_answer`. It holds no free text and no learner identifier.<br>A residual error is an audited answer delivery with a claim labelled other than SUPPORTED.<br>Engineering parameters (no plan value; Claude's, ratified under DI-98): every value in this row. | v5 `v3.schemas`; `app/services/v3/feedback.py`, `contracts.py` |

### 16.2 Deferred items

| # | Item | Who | State |
|---|---|---|---|
| DI-89 | The Phase 6 exit (plan P: "AC-6-1 to AC-6-7 green; one staging audit cycle; [Decision D-25] filed."): AC-6-1..AC-6-7 green in a cited CI run on `main`. `phase6_exit_passed` stays false while D-25, D-18 and D-06 are open, holds H4 and H10 hold, no staging audit cycle has run (DI-92), and the Phase 5 exit is not passed (DI-74). Blocked by: the OPEN owner decisions D-25, D-18 and D-06 (DI-90, DI-91, DI-98), the staging audit cycle (DI-92) and the Phase 5 exit (DI-74). | Eng / PI | Open |
| DI-90 | Plan P "[Decision D-25] filed": the owner's critical-claim registry for each environment. Until it is filed every non-development registry is empty, so X1 never fires outside development; development holds three synthetic entries over public-corpus fixture claims (PD-33). Blocked by: the OPEN owner decision D-25 (PI). | PI | Open |
| DI-91 | Hold H4 (D-18; blocks "P6 pool; P11 start"; release evidence "Capacity statement"): the reviewer pool, its capacity statement and reviewer provisioning outside development (with DI-38). Until then `reviewer_admitted` is false outside development: every V3 route refuses every caller there, the ledger route reads a reviewer as an owner, no item is adjudicated there and every withheld item stays withheld (plan J). Production adjudication may start once staffed (plan Phase 6 B). Blocked by: the OPEN owner decision D-18 (PO, PI) and hold H4. | PO / PI, then Eng | Open |
| DI-92 | Plan P "one staging audit cycle": a scan, draw, adjudication, double review and apply cycle on staging. Blocked by: a staging deployment (a cloud write under D-05), `V3_QUEUE` outside development (on is refused before the exit; shadow is an override), and a staffed pool (DI-91). | PfO / PO, then Eng | Not started |
| DI-93 | Plan task 4 "recalibration via Phase 7 change control (Loop 4) [Evidence E-74]": applying gold labels to thresholds, weights or the critical registry, and releasing any withheld item. Phase 6 exports the applied labels (`python -m app.workers.v3_queue export-gold`) and applies nothing. Blocked by: Phase 7 change control. | MLE (Phase 7) | Deferred |
| DI-94 | Hold H10 (D-08; blocks "P6 experts; P10, P12 cohorts") and research labelling (plan Phase 6 C non-goal; D-14, D-15): expert reviewers for research use, a research-plane gold store and any labelling of the licensed corpus or ULQS. Plan L627-628 places "the V3 gold store" in "the private research data plane [Decision D-14] [Assumption A-13]", while L2593-2594 measures deployment-form HR-3 in production from the 5% draw (spec conflict 2). Phase 6's gold store is the deployment form's: production-plane labels about public-corpus spans only, kept out of the public repository, CI artifacts, logs and releases; the research-plane store waits for D-14. Blocked by: the OPEN owner decisions D-08 and D-14 (PI) and hold H10. | PI | Deferred |
| DI-95 | The Phase 6 log-based metrics and alerts (plan I: the escalation share, the queue-age p90 alert [Risk R-40], the draw rate, double-review agreement and the residual bound), and the scheduled job that emits their source. Outside development, while D-18 is open, `GET /v3/metrics` refuses every caller, so the worker's `v3.status` line is the only SLI source, and it is logged only when `python -m app.workers.v3_queue status` runs. Proposed: a Cloud Run job running `status` hourly (the stop's sample interval) and, wherever `V3_QUEUE` is not off, `scan --until-done` before it, owned by the Platform Owner. Blocked by: a cloud write under D-05. | PfO | Defined, not created |
| DI-96 | The CUSUM statistic and its alarm (6.3 "CUSUM p0/p1/h (11)", "0.05/0.15/4.0 [PROV]"), the sustained-alarm stop-the-line (13.6) and "promotions held" (6.3): Phase 9 computes the statistic and delivers each alarm through `app.services.v3.events.record_cusum_alarm` (contract `cusum-alarm-v1`); Phase 6 tests the interface with synthetic alarms only. Blocked by: Phase 9 (drift control). | MLE (Phase 9) | Deferred |
| DI-97 | The delivered path's V3 behaviour: a learner-facing "looks wrong" control with its privacy disclosure (the flag record is a new personal-data class), the flag intake outside development, and the X1 hold and the V3 stop on delivered two-pass content (with DI-59 and DI-85). The flag intake is an API route behind `V3_QUEUE` in development only, and no frontend control exists. A legacy delivery that quotes a held claim's span text is not checked against the holds (development only, where the registry is synthetic). Blocked by: learner-facing capability outside development (D-05), the Phase 5 exit (DI-74) and the delivered two-pass path (DI-59). | PO, then Eng | Deferred |
| DI-98 | Ratify PD-32..PD-39, including D-06's operator values (the 10% double review, the queue-age SLO, the stop and its measure) and the 15.3 counting rule. Blocked by: owner decisions (PI, PO; D-06 OPEN). | PI / PO | Open |
| DI-99 | Plan 16.1 "the X6 auditor MUST NOT audit their own change [Risk R-35]" for code, configuration and corpus changes. Phase 6 refuses a reviewer's second round on an item and an adjudicator's apply on erasable per-round records. No record names who authored the change an item audits (one author made every commit, E-63). An erased reviewer's rounds leave only the gold rows' digests, so that person's independence on those items is no longer checkable. Blocked by: D-18 (a pool of more than one person) and an authorship record of each change (Eng). | PO, then Eng | Open |
| DI-100 | Remove configuration package v4 after one release, with its CI step. Blocked by: a production release under D-05 (v4 stays readable for the release after the Phase 6 merge). | Eng | Deferred |
| DI-101 | X3 for `/qa/ask` answers: a qa- record names no learner by design (Phase 3 spec R-a), so no owner check can admit a flag on it; X3 covers tutor turns only. Blocked by: an owner decision on linking Q&A answers to their askers (a privacy change; the Phase 8 learner record, D-27 OPEN). | PO, then Eng (P8) | Deferred |
| DI-102 | Dawid-Skene weights (plan Phase 6 C: "Dawid-Skene before 200 gold claims [Evidence E-84]" is a non-goal; arbitration rule 5): `/v3/metrics` reports the labelled claims; tier-3 reliability weights wait for at least 200 gold claims. Blocked by: 200 gold claims (needs the staffed pool, DI-91). | MLE / PI | Deferred |
| DI-103 | An operator path to clear or acknowledge a tripped V3 stop outside development. Under the `V3_QUEUE=shadow` override (which DI-92's staging audit cycle needs), the scan creates items that nobody can close while D-18 is open: no reviewer is admitted, and an item citing a span that is not quotable (D-31) is not reviewable. The stop then trips 120 h after the first such item and stays: only adjudication by an admitted reviewer clears it, and nothing short of the Phase 6 downgrade, which drops the gold evidence, resets it. It acts on the shadow pipeline's tier 1 only, and the runbook warns before the override is set. Plan L makes the stop "operator policy, set under Decision D-06", so a clear path is the owner's to define. Blocked by: the OPEN owner decisions D-06 (operator policy) and D-18 (DI-91). | PO / PI, then Eng | Open |

### 16.3 Rows of other phases that Phase 6 advances

These rows are unchanged; the registers' rule is never to edit other phases' rows (conflict 24):
- **DI-38** (reviewer provisioning): DI-91 carries the Phase 6 hold.
- **DI-56** (V3 consumption of the queue intents): the scan consumes them (4.4). The BEP phase record states this.

---

## 17. Verification, work order and exit

**Work order (commits on the branch).**

1. **E15: the Phase 5 records after the merge.** A separate first commit, docs and one test only.
   - The Phase 5 spec's DI-74 row becomes: "The Phase 5 exit: AC-5-1..AC-5-11 green in a cited CI run on `main`. `phase5_exit_passed` stays false while D-07, D-12, Q-09, A-15 and D-21 are open, holds H6, H8, H9 and H14 hold, and the Phase 4 exit is not passed (DI-58). The plan-P CI item is met: PR #37 was squash-merged on 2026-11-22 as `main` `c34a8c1` (tree identical to `8aa4ff1`); PR run 45043411679 and branch push run 45042478870 at `8aa4ff1` passed every job (release-artifacts skipped by design), and main run 45044415408 at `c34a8c1` passed every job and is the cited run for AC-5-1..AC-5-11. The exit is not passed. Blocked by: the OPEN owner decisions D-07, D-12 and D-21, Q-09 and A-15 (DI-69, DI-70, DI-72, DI-73) and the Phase 4 exit (DI-58)." Its Who and State columns stay `Eng / PI` and `Open`.
   - Section 17's second exit bullet states the same facts: the earlier push run 44998840311 at `3498b52` was green, and main run 45044415408 is the cited run (DI-74). "D-07 closed" stays an owner decision (DI-69), and the holds stay held.
   - Section 18 gains one row: `| Merge | `c34a8c1` | PR #37 squash-merged (tree identical to `8aa4ff1`); main run 45044415408 green on every job, the cited run: `test_phase5_docs_the_records_name_the_merge_and_the_cited_main_run` |`.
   - The test strategy's Phase 5 exit paragraph gets the same facts, keeping "The exit is not passed."
   - The BEP register's DI-74 row is brought to exactly the spec's row in the same change.
   - `check_records.py`:
     - `check_p5_merge_the_records_name_the_merge_and_the_cited_main_run` also requires `c34a8c1`, `8aa4ff1` and `45044415408` in the repository spec's DI-74 row, and none of the three stale phrases;
     - `check_p5_build_the_phase_record_states_the_exit_not_passed_and_lists_every_open_item` and `check_p5_build_the_plan_holds_the_text_the_v4_package_quotes` read `package_raw("v4.json")` explicitly.
   - Mutation check: the pre-merge texts restored fail both the new test and the BEP check.
2. **The build:** package v5, loader, settings and package check; the database (models, the revision, the guards); the V3 services, reviewer access, routes, the ledger route's gate, the authorization matrix, `main.py`, the worker, the V2 integration (4.13); the frontend (11); the residual report and the three re-written records (12.2); docs, ADRs, runbooks, env example, CI and the test strategy; with their tests and the changed tests of 13.3. The BEP records, registers and checks follow outside the repository.
3. **Review rounds:** each round's fixes in their own commits, after the build (section 18 names them).

**Commands** (`<py>` is the scratch venv's python):

```
<py> -m pytest -q -m "not release_artifacts" apps/api/tests evaluation/tests -p no:cacheprovider
<py> scripts/validate_corpus.py --check-public-assets --check-recall-stop
<py> scripts/validate_lqs.py --allow-draft
<py> scripts/config_package.py --check
<py> scripts/config_package.py --check --path apps/api/app/config_package/v4.json
<py> scripts/config_package.py --check --path apps/api/app/config_package/v3.json
<py> scripts/config_package.py --check --path apps/api/app/config_package/v2.json
<py> scripts/config_package.py --check --path apps/api/app/config_package/v1.json
<py> scripts/run_v1_fixtures.py --check docs/evaluation/phase4/v1_fixture_report_v1.json
<py> scripts/run_v2_fixtures.py --check docs/evaluation/phase5/v2_fixture_report_v1.json
<py> scripts/run_v3_residual_report.py --check docs/evaluation/phase6/v3_residual_report_v1.json
<py> scripts/capture_public_payloads.py --check apps/api/tests/data/phase4_public_payloads_v1.json
<py> scripts/authorization_matrix.py --check
<py> scripts/replay_tutor_plans.py --check docs/evaluation/phase3/three_plan_replay_v1.json
<py> scripts/generate_manifest.py --check
<py> scripts/validate_corpus.py --check-hashes --check-near-duplicates
<py> scripts/calibrate_abstention.py --check docs/evaluation/phase2/calibration_record_v1.json
<py> scripts/scan_boundary.py --repo --docker-context apps/api/Dockerfile:. --docker-context apps/frontend/Dockerfile:apps/frontend --report <scratchpad>/boundary.json
<py> D:\QC_AI_Studio\BEP-2-12\00_meta\check_records.py
cd apps/frontend && npm run lint && npm run typecheck && npm run test:integration
(CI only: pip-audit and npm audit --omit=dev --audit-level=high need the network and are not run locally)
git status --short   (no stray files; nothing in the repository root)
```

**Scratch PostgreSQL 17.**
- Never use the installed server's data directory, and never pipe `pg_ctl` output. Ports 55024-55623 are reserved, so use port 57433.
- `initdb` into the scratchpad, then `pg_ctl … -o "-p 57433" … start`, then `createdb qcai_test`.
- Run the suite with `TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:57433/qcai_test`, then with `postgresql+pg8000://…` on a fresh database.
- Finish with `pg_ctl … stop`.

**Exit (plan P).**
- Plan P: "AC-6-1 to AC-6-7 green; one staging audit cycle; [Decision D-25] filed."
- The AC tests are done in code. The cited run must be on `main` after the merge (DI-89).
- "One staging audit cycle" needs a deployment and a staffed pool (DI-92, DI-91). "[Decision D-25] filed" is an owner decision (DI-90). Holds H4 and H10 stay held (DI-91, DI-94).
- `phase6_exit_passed` stays `false`. The exit is not passed.

---

## 18. Review history

The rows below record what each round fixed, in order. They may describe behaviour that a later round superseded; sections 0-17 are authoritative. Each finding is one line naming the tests that fail if its defect comes back.

| Round | Commit | Findings fixed (one line each, with their tests) |
|---|---|---|
| Spec (pre-code) | — (sections 0-17) | The design: `test_ac_6_1_a_critical_tier_1_claim_with_one_objection_fires_x1_and_is_withheld`, `test_ac_6_2_one_thousand_synthetic_deliveries_draw_33_to_69_and_a_same_seed_replay_draws_identical_ids`, `test_ac_6_4_an_adjudication_appends_one_gold_row_and_changes_no_ledger_row`, `test_plan_l_disabling_v3_releases_no_withheld_item` |
| Spec review 1 (pre-code) | — (sections 0-17) | A Wilson closed form asserted bit-exact: `test_ac_6_5_zero_errors_in_300_audited_items_bound_the_residual_below_1_3_percent`. A schema ban on the verifier's `rating`: `test_ac_6_6_a_learner_flag_sets_f_i_to_zero_and_changes_no_verdict_or_ledger_row`. An X1 claim delivered once its objector left the panel (the sticky hold): `test_a_critical_tier_1_claim_stays_held_when_its_objector_leaves_the_panel`, `test_invariant_6_no_x1_claim_is_delivered_under_any_fault_schedule`. The stop read through the global database: `test_the_v3_stop_reads_the_pipeline_s_own_database`. Backdated shared-database items: the `conftest.py` guard. The start-up fixture-path check: `test_the_v3_start_up_check_runs_from_the_image_layout`. Independence on rotating digests: `test_independence_survives_a_guest_secret_rotation`. An inert exposure factor and an unbuildable AC-6-3 case: `test_ac_6_3_the_higher_severity_times_exposure_times_one_minus_k_ranks_first`. A non-blind view and blind labels of hidden claims: `test_plan_h_reviewers_see_public_quotable_spans_only_and_no_learner_identifier`, `test_an_unreviewable_item_cannot_be_claimed_or_adjudicated`. A dilutable p90 stop: `test_plan_l_queue_age_above_the_slo_for_two_days_withholds_tier_1`. A downgrade that dropped flags: `test_plan_g_the_phase_6_revision_is_additive_reversible_and_keeps_its_rows`. The flag intake and the ledger route outside development: `test_freeze_outside_development_v3_is_off_and_no_learner_path_changes`, `test_plan_b_no_reviewer_is_admitted_outside_development_while_d_18_is_open`. The guest CSRF in AC-6-7: `test_ac_6_7_a_guest_on_every_reviewer_route_gets_403_and_one_access_log_entry`. A key-dependent report head: `test_plan_f_the_committed_residual_report_matches_a_fresh_run_and_names_its_evidence_class`. A missed Phase 4 doc assertion, a scan merge reopening a closed item, and the restore path cut |
| Build | the commit after `8ff17a6` | X1 reads only the claim-loop corrections, never an alignment re-render's list of shown claims (conflict 29): `test_x1_fires_when_a_correction_cycle_listed_the_claim_though_its_final_tally_passed`<br>Claim and adjudication read the corpus in force for reviewability (conflict 30): `test_an_unreviewable_item_cannot_be_claimed_or_adjudicated`<br>The AC-6-3 route check reads a fresh database (conflict 31): `test_ac_6_3_the_higher_severity_times_exposure_times_one_minus_k_ranks_first`<br>The role-denial test counts against its own denial cap once the reviewer negatives exceed a minute's: `test_a_role_denial_is_a_security_event`<br>The draw is exact at the 1/20 boundary where a float comparison is not: `test_the_draw_is_exact_at_the_rate_boundary_where_a_float_comparison_is_not`<br>A first flag read as a duplicate on PostgreSQL under psycopg, whose rowcount for the flag insert is -1; the V3 inserts read RETURNING: `test_the_flag_route_flags_the_callers_own_turn_once_and_says_when_its_record_is_not_written_yet`, `test_ac_6_6_a_learner_flag_sets_f_i_to_zero_and_changes_no_verdict_or_ledger_row` (PostgreSQL)<br>The runbook's Phase 6 table has the runbook's two-column shape: `test_phase5_docs_the_runbooks_and_registers_state_the_gateway_s_operations_exactly` |
| Code review 1 | the commit after `6c94032` | X5 model changes ran through a copy of the rule, not `x5_model_changes`, and no test changed a version between scans: `test_a_model_version_change_between_scans_records_one_x5_event_and_raises_the_next_deliveries_to_1_5`<br>No test scanned an X4-marked record: `test_the_scan_enqueues_an_x4_response_item_with_its_severity_and_priority`<br>`x3_fires` was unused; `record_flag` asks it: `test_ac_6_6_a_learner_flag_sets_f_i_to_zero_and_changes_no_verdict_or_ledger_row`<br>X1 fired at tier 1 only, against AC-5-4 "critical claims follow X1 from Phase 6"; it fires at every tier and holds at tier 1 (conflict 1): `test_x1_fires_at_every_tier_and_holds_at_tier_1_only`, `test_x1_fires_on_a_critical_tier_2_claim_that_passes_2oo3_and_queues_and_counts_it_without_a_hold`<br>A V2-shadow record's V1.3-withheld claims were held but never queued: `test_a_v2_shadow_record_s_v1_3_withheld_claims_are_queued_so_the_holds_and_the_queue_agree`<br>An X3 item's exposure depended on whether the flag or the scan came first: `test_an_item_s_exposure_and_priority_do_not_depend_on_whether_a_flag_or_the_scan_came_first`<br>The residual reported an upper bound of 0 with nothing audited: `test_the_residual_bound_is_null_while_nothing_is_audited`<br>The non-auditable tutor turns mixed lost records and kill-switch turns into the pre-ledger count: `test_non_auditable_reports_pre_ledger_turns_apart_from_kill_switch_turns_lost_records_and_pending_appends`<br>A gold export could be written into the repository: `test_export_writes_the_applied_finals_or_every_row_and_refuses_the_application_tree_and_the_repository`<br>A SQLite lock in a V3 mutation or the scan became HTTP 500: `test_a_sqlite_lock_is_retried_and_one_that_outlasts_the_attempts_is_busy`, `test_a_locked_database_is_retried_and_a_lock_that_outlasts_the_retries_answers_503`, `test_two_concurrent_claims_leave_exactly_one_lease`<br>A repeated apply logged `v3.applied` again: `test_adjudicate_and_apply_are_idempotent_by_client_key`, `test_the_reviewer_routes_shape_and_their_security_events`<br>The role-first gate was untested outside development: `test_ac_6_7_a_guest_on_every_reviewer_route_gets_403_and_one_access_log_entry` (staging cases)<br>Texts said every `/v3` route answers 404 while V3 is off; 10.3 and the observability runbook omitted four worker events and two fields; the Phase 3 rollback had no branch for the Phase 6 head: `test_phase6_docs_name_the_logger_each_phase6_event_logs_on`, `test_phase6_docs_the_phase_3_rollback_checks_the_stamp_against_the_current_head`, `test_the_committed_matrix_is_current`<br>Conflict 2 now quotes plan L627-628 and resolves it against L2593-2594 (DI-94); PD-32..PD-39 name their engineering parameters; DI-95 defines the status schedule; DI-103 records the missing stop clear path; the runbook states what a downgrade loses and the gold export's handling rule; the reviewer docs state what the triggers disclose: `test_plan_f_the_trigger_registry_document_matches_the_package`, `test_phase6_docs_quote_the_plan_and_state_the_current_rules`<br>The reviewer console: one main landmark, labelled selects, a mounted status region, no pre-filled label, neutral trigger labels: the frontend tests (13.4) |
