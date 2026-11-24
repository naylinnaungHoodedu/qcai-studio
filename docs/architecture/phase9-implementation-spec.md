# QC+AI Studio: Phase 9 Implementation Spec
## Verified-trust ranking and drift control (plan L1616-1677)

- **Repository:** `D:\QC_AI_Studio\Codex_Webapp_QC_AI_Studio`.
- **Branch:** `phase9/verified-trust-ranking`, cut from `origin/main` `512b8a6` (Phase 7 merged, PR #39; tree identical to `4e682db`).
- **Plan:** `D:\QC_AI_Studio\QC_AI_Studio_Ultimate_Software_Upgrade_Plan.txt`. Plan locations used here:
  - The Phase 9 block: L1616-1677.
  - 6.2 rows: L657, L669-675. 6.4: L729-749. 6.5: L751-790.
  - Loops and 7.3: L840-880. 7.8 invariants: L960-982.
  - Phase 5: L1357-1436. Phase 6: L1439-1498. Phase 7: L1500-1555. Phase 10: L1680-1742. Phase 12 (AC-12-4): L1801-1850.
  - 9.1-9.4 (H11): L1858-1926. 13.6: L2365-2384. 13.7: L2386-2405.
  - Risks: L2470-2530. Decisions: L2538-2562 and L2978-3026 (D-28 at L3018-3019). Section 15: L2580-2700. Evidence E-89..E-94: L3149-3154.
- **Paper:** VBT RevB p. 12-14 (Sec. VII-A..D: eqs. (5)-(11), Table X, Algorithm 1, Table XI, X1-X6) and p. 19 (Table XVII, Table XVIII H4a).
- **Fixed decisions:** E1-E16 (`BEP-2-12/00_meta/workflows/p9/p9_design.txt`). Every one is implemented. Section 1 lists each refinement and conflict; none reverses a fixed decision.

Sections 0-17 describe the behaviour the code has. They are authoritative and are kept current in place (P2-12-D-03). Section 18 holds one history-table row per round. This file is LF in every checkout (`.gitattributes`, as for the Phase 7 spec).

---

## 0. Ground rules, measured facts, readings

### 0.1 Binding constraints (Phase 7 0.1, unchanged, plus Phase 9's)

**Git and files**
- Stay on the branch. No branch switch, no `git stash`, no push, no history rewrite, no git-config change.
- Commit messages end with a blank line, then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Temporary files go to the scratchpad only. Nothing is written to the repository root, and CI's `boundary-scan.json` goes to the scratchpad when run locally.

**Forbidden reads and calls**
- Never open `infra/cloudrun/*.env.yaml`, `apps/frontend/.env.local` or any `.env*` file.
- No cloud, gcloud, gh, provider or LLM call, and no deploy. No test touches the network (`apps/api/tests/network_guard.py`).
- No `pip install`, and nothing is added to `apps/api/requirements.txt`: no scipy or numpy. scipy was used only outside the repository to check the hand fixtures (M16); no module imports it.

**Freeze (D-05, P1-D-18; E10)**
- `RANKING` is `off` outside development.
- `RANKING=on` (live routing) is refused in every environment, development included, while D-28 is OPEN and hold H11 holds, and in any case before the Phase 9 exit.
- In development the default is `shadow`. The ranking scan computes and records, while static assignment (`tutor_pipeline.generator_default`, `extractive-d19-v1`) keeps generating every learner-path shadow record. The learner path stays legacy and contained (D-19).
- No frontend file changes, and no learner-facing control, banner or text changes.
- The public-payload golden passes unchanged and is never rewritten (`scripts/capture_public_payloads.py --check apps/api/tests/data/phase4_public_payloads_v1.json`).
- `/ready` gains static ranking fields. When the ranking mode is not `off`, it also makes one cached read of the ranking stop (10.2).

**Research and data (D-14, D-15, R-25; E8)**
- No research item, ULQS item, gold label or licensed text is ever a fixture or a replay input.
- Synthetic event logs hold numbers and identifiers only, never text.
- The research replay (E4) runs only in the research environment, which is Phase 10's (DI-124).

**Parallel Phase 8 track (E16)**
- PD-200..PD-299 and DI-300..DI-499 are never used.
- These are not edited: the learner-record service, erasure, retention, consent, identity, the learner-record routes and the learner-record functions of `api.ts`.
- No new table has a column matching `test_erasure_retention.py`'s identity pattern `(user|player|guest|author|opponent|reviewer|learner|account)[a-z_]*_id$`. No new table is user-keyed or hangs off a user-keyed table by a foreign key, so erasure (plan 10.3, AC-1-2) is unchanged.

**Tests**
- No existing test or guard is weakened. No new skip or xfail is added.
- A changed test keeps its intent (13.3), and its commit message says why.
- Each fix and guard is mutation-checked: revert it, see the named test fail, then restore it byte for byte.
- AC tests go in `apps/api/tests/test_phase9_acceptance.py`, unit tests in `apps/api/tests/test_ranking_units.py`, and fakes in `apps/api/tests/ranking_fakes.py`. No test file is created per review round.
- No test, script or mutation run writes into the checkout (Phase 6's session fixture `_the_checkout_stays_unchanged`).
- No new source literal starts with `qcai_`.

### 0.2 Measured facts (on the branch at `512b8a6`, 2026-11-23)

- **M1. Baseline.** The E15 commit (`512b8a6` plus two docs and one test) was run on a git-less export of the commit (the checkout carried the build's uncommitted work): 1942 passed, 2 skipped, 1 deselected, 3 xfailed, with 7 failures and 1 error that need a git checkout (source-fidelity `git ls-files`, the base-ref history, the boundary scan, the tree-unchanged checks). Every CI validator exits 0 at the base; BEP `check_records.py` 48 of 48. The PostgreSQL 17 suites run on the finished tree (17); no separate PostgreSQL run of the base was taken (an open issue in the BEP record).
- **M2. No generator choice exists.**
  - `tutor_pipeline/evidential.py:159-165` `get_generator` returns `GENERATORS[generator_default]`. It refuses an id outside `generators_allowed`, `WIRED_GENERATORS` (`{"extractive-d19-v1"}`; D-12 open, H6) or `GENERATORS`.
  - The loader requires `generators_allowed ⊆ WIRED_GENERATORS`.
  - `TwoPassPipeline` accepts an injected `generator` (`pipeline.generator`).
  - `GeneratorRef{generator_id, model_id, kind, prompt_hash}` has no model version. The extractive generator sets `model_id = generator_id`.
  - The pipeline writes `provenance.generator_model_id = ref.model_id` and `provenance.evidential_prompt_hash = ref.prompt_hash`.
  - V1.9 refuses a plan whose `generator != generator_ref`.
- **M3. Registry.**
  - v6 `gateway.registries.development`: `fake-alpha-v1`, `fake-beta-v1` and `fake-gamma-v1` (verify only); `fake-delta-v1` (`["generate","verify"]`; provider `fake`, model_version `2026-11-21`, fake rule `verbatim-support-v1`).
  - The staging, production and default registries are empty. A non-fake member is refused while D-12, D-07, Q-09 or Q-15 is open.
  - No code path consumed `generate` before Phase 9. `registry.generator_family` resolves `v2.generator_families`, or else a `generate` member whose `adapter_id` is the id; otherwise it raises `GeneratorFamilyUnknown`.
  - `ModelGateway.ineligible_reason(spec, *, settings)` returns one of `stopped`, `kill_switch`, `disabled`, `egress_refused`, `budget`, `budget_unavailable` or `down`.
  - `Panel.build` skips the generator family.
- **M4. Ledger.**
  - `response_ledger` has no user id and no foreign key to a tutor table. After erasure a row is unlinkable.
  - Consumers poll by seq with their own cursor.
  - Every learner delivery is a `legacy` record whose `versions.generator_id` is `LEGACY_GENERATOR_ID`. A shadow record is `shadow-<id>`, with `shadowed_response_id` naming the turn.
  - The V2 and EHMF blocks exist only on shadow records (DI-85, DI-111).
  - In development `MODEL_GATEWAY=shadow`, so a shadow V2 block has no cycles, corrections or escalation.
  - No explicit "first pass clean" flag exists, and no latency is recorded.
  - In development every claim carries a V1.3 `no_checker` flag (D-21: no checker; the record's `ehmf.detector_absent` is `["V1.3"]`), a `v1_3_flag` V3 intent reason, and the D-20 interim withhold (`final` `withhold`, `d20_interim_withhold`) (conflict 27).
  - The Phase 3 provenance audit (`ledger._provenance_problems`) reports a two-pass record whose `versions.generator_id` is not in `generators_allowed`, or whose `evidential_prompt_hash` is not the package's.
- **M5. Table X signals.**
  - H: per-claim EHMF `primary` and `weight` on v4. The `ehmf.weights` are A 1, B 1, C 3/5, D 3/5, D_disclosed 0, E 2/5.
  - V and K analogues: `v3/priority.py` `support_share` and `response_k`.
  - S: `entailment_score` is always None (D-21).
  - F: `v3/feedback.f_i(db, seq)` returns 0.0 when the record's V3 items include X3, else None. X3 flags are recorded only on the learner's legacy record, so a shadow record never has an X3 item. No 1-5 rating exists.
- **M6. V3 X5.**
  - `v3/events.py` `record_cusum_alarm(alarm, *, settings, package, session_factory, now, db=None)` inserts `v3_events(kind="cusum_alarm", from_ledger_seq=<ledger head>, window_deliveries=x5_window_deliveries)`; without `db` it opens its own session and commits.
  - `CusumAlarm` (`cusum-alarm-v1`) uses float p0, p1, h and statistic, with `statistic >= h`, `observations >= 1`, a `raised_at` matching `UTC_TIME`, and `source` `phase9-cusum` or `synthetic-test`.
  - `v3/scan.py` `record_model_change(db, change, *, source, from_ledger_seq, window, now) -> int` returns the inserted seq; `window_remaining(db, v3_event_seq) -> int` is a window less the `v3_draws` rows after its `from_ledger_seq`.
  - The V3 scan records X5 model changes from registry `verifier:<model_id>` sightings and record `generator:<generator_id>` sightings (version `provenance.generator_model_id`), both through `v3_model_versions`.
  - V3's advisory lock is `V3_SCAN_LOCK_KEY = 7_401_206`, the gold lock `7_401_207`, the ranking lock `7_401_209`. `record_flag` takes V3's lock.
  - The V3 gold label contract (`V3GoldLabel`) is pinned by sha256 in packages v5 and v6, with the four Phase 6 queue reasons (conflict 28).
- **M7. Contexts.**
  - `MODULE_BLUEPRINTS` (11 modules). `IndexEntry.lesson_slugs` attaches each indexed span to lessons; the ledger records `retrieval.evidence` span ids but no `lesson_slug`.
  - Tier: `assessment_tier` (1) when V1.6 finds assessment items, else `default_tier` (2). Tier 3 never occurs.
  - Measured over the 40 golden-set queries in development: 15 records resolve to a module under `cluster-module-v1` (nisq-hybrid-workflows 3, quantum-enhanced-applications 5, industry-use-cases 2, ai-for-quantum-hardware 2, thermodynamics-roadmap 2, representation-explainability 1) and 25 are `unscoped`; 14 are tier 1 (`quiz_item`).
- **M8. Golden set.** Phase 7 `golden-set-v1` has 40 items, each with a `query`. No 50-item set exists (D-14).
- **M9. No pre-verified store.** `v2.degraded.pre_verified_source` must be null (DI-83).
- **M10. Package.** v6 is 6.0.0, schema 6. `package_versions.json` is append-only, with a base-ref check. `golden_run_v1.json` pins the package and every `apps/api/app` module.
- **M11. Flags.** The type is `Literal["off","shadow","on"] | None`, and None resolves to the default for the environment. `_parse_flag_policy` adds one block per schema step, and the package repeats the code defaults.
- **M12. Workers.** argparse CLIs. No in-app scheduler.
- **M13. Alembic.** The base head is `20261123_phase7_ehmf`. Phase 6's `v3_append_only()` is used. The downgrade guard pattern is `-x allow_ehmf_drop=true`.
- **M14. /ready.** `_build_fields` is in `main.py`. EHMF's stop read is cached per process for `ehmf.stop.refresh_s` and is skipped when EHMF is off.
- **M15. CUSUM defaults.** A seeded stdlib simulation of eq. (11) (p0 0.05, p1 0.15, h 4.0) gives ARL0 about 1525 and a mean delay of about 50. It is an engineering check, not MR-2. The synthetic `drift` scenario detects a p0-to-p1 shift after 61 requests.
- **M16. Quantile references** (scipy, outside the repository, only to check the hand fixtures): Beta(95,5) 0.9099264; Beta(190,10) 0.9224077; Beta(41,1) 0.9296; Beta(194,6) 0.9479. The code gives 0.909926441808, 0.922407666443, 0.929538882730 and 0.947899773827 (about 10 ms each).
- **M17. Registers.** The last PD was PD-49 and the last DI DI-114. Phase 9 uses PD-50..PD-59 and DI-115..DI-128.
- **M18. Tests that read the shipped package's number.** `test_config_package.py`, `test_ehmf_units.py`, `test_phase7_acceptance.py`, `test_phase4_acceptance.py`, `ehmf_fakes.SHIPPED_VERSION`; the BEP `check_records.py` reads `v6.json` explicitly.
- **M19. Kind lengths.** The longest kinds (`recommission_pass` and `recommission_fail`) are 17 characters. PostgreSQL enforces `varchar(n)` and SQLite does not.
- **M20. The shadow regression (4.8).** Over golden-set-v1's 40 queries both the static generator and the clone generate 40 records, all clean (y = 1), mean Q 1: `commission` gives Beta(41, 1), T = 0.929538882730, rating B. The regression runs with a clear V3 stop: with V3 unreadable the 14 tier-1 queries are withheld (`v2_withheld`), which would leave 26 clean (Beta(27, 1), T = 0.8950, rating C).
- **M21. Replay runtime.** `run_ranking_replay.py --check` takes about 18 s on the workstation (seven scenarios, 6,700 input events).

### 0.3 Readings

- **R-a. A model.** A candidate generator `m` is `ModelRef(adapter_id, family, provider, model_id, model_version, cost_units_per_call)`, and its key is `adapter_id`. Its version is held in state. The candidates M are:
  - (i) each `WIRED_GENERATORS` id the package allows (the static assignment `extractive-d19-v1`): family from `v2.generator_families`, provider `none`, cost 0, and `model_version = "p-" + evidential_prompt_hash[:16]` (rule `evidential-prompt-hash-16-v1`);
  - (ii) each `generate` member of the environment's registry.

  A candidate whose family cannot be resolved is never offered (`family_unknown`).
- **R-b. A request.** One ledger record consumed by the ranking scan. Algorithm 1 is evaluated when the scan reads the record (conflict 1). The record's own generator is the model whose outcome it carries.
- **R-c. A completed verdict.** Either a first-pass V1 failure after generation (y = 0), or a V1 pass where every V1-passed claim has a V2 outcome of `pass` or `fail`, with the panel reached. Everything else is skipped (4.3).
- **R-d. Clean (y_i = 1).** All of the following hold:
  - V1 passed with no regeneration or re-render (`cycle_count == 0`, `hard_fail` false, final not a V1 abstention, every accepted-attempt result pass or mark, V1.7's and V1.3's `no_checker` aside);
  - V2 `cycles == 0`, every judged claim `pass` at `cycle == 0`, and the alignment item absent or `pass`;
  - no generator-attributable escalation (X1: a critical claim with an objection; X2; a V3 intent reason `v1_3_flag` from a V1.3 result other than `no_checker`, or `v1_8_misconception`).

  X3 feeds F only (AC-9-2). X4, X5, X6 and V1.7 are not the generator's.
- **R-e. Modes.**

| `RANKING` effective | What runs | Learner effect |
|---|---|---|
| `off` (default outside development; also with no ranking block or with `RANKING_UNAVAILABLE_REASON` set) | Nothing: no scan, no hook, no `/ready` stop read. Event rows, alarms and X5 windows already written stay ("alarms retained"). | none |
| `shadow` (default in development; elsewhere a recorded override) | The ranking scan (worker) consumes ledger rows into events, batches, states, alarms (X5 through Phase 6), model changes (X5), fallback V3 items and the replay check. Shadow generation runs only when `RANKING_SHADOW_GENERATION=true` in development. | none |
| `on` | Refused at settings construction in every environment while D-28 is open, H11 holds or `phase9_exit_passed` is false. | — |

---

## 1. Conflicts between plan text and the fixed decisions, with resolutions

Each resolution is a refinement. None reverses a fixed decision.

1. **Algorithm 1 line 6 ("generate with g; verify") and line 11 ("generate with h in shadow; ... never deliver") against D-12/H6 (no provider generator, M2) and E10 ("static assignment keeps serving").**
   - Algorithm 1's decisions (`select` with incumbent, fallback and exploration) are recorded as derived events when the scan reads each record.
   - Generation by g (when g is not the record's generator) or by h runs only under `RANKING_SHADOW_GENERATION=true`, in development, for a candidate with a wired fake generate rule (`extractive-clone-v1`, 4.12). It writes a separate shadow ledger record that is never delivered.
   - The switch defaults to false, so the development request path and every existing test are unchanged.
2. **E1 ("a model is a registry member with capability generate") against the record producer `extractive-d19-v1`, which is not a registry member.** M = the wired static generator(s) plus the registry's generate members (R-a). Without the static generator, no real record could ever feed the controller.
3. **E3 (the lesson's module "when the turn names a lesson") against a ledger without `lesson_slug`.**
   - Rule `cluster-module-v1` takes the intersection of the module slugs attached to every `retrieval.evidence` span. Exactly one module gives that module; otherwise the cluster is `unscoped`. A record whose `retrieval.corpus_version` differs from the store's is also `unscoped`.
   - The ledger schema does not change.
   - The cluster is frozen into the outcome event, so the replay never needs the store.
4. **Plan A "50-item golden set" and AC-12-4 against `golden-set-v1` (40 items).** The recommission set is golden-set-v1's 40 queries, pinned in `ranking.recommission.golden_set` with `target_items: 50` (DI-119).
5. **The paper's 80-item commissioning against no pilot set.** Commissioning runs the same 40 queries (4.8). All 40 are clean (M20): Beta(41,1) gives T = 0.9296, which is rating B. The 80-item commissioning is DI-119.
6. **AC-9-7 "audit rises to the X5 rate (default 20%)" against the paper's per-model-and-context rise.** Phase 6's window is used unchanged (E6). It raises the audit of every learner delivery, which is stricter.
7. **AC-9-6, and E7's test wording "the record is abstain/withheld with no generated text", against E10 (the static shadow record keeps its generated claims).**
   - Under shadow, "the record" is the controller's decision: a `select` event with kind `fallback`, no model and no field that can carry text (the `Decision` has `action: "abstain"`).
   - The scan enqueues a V3 response item (`ranking_empty_eligible_set`) for that ledger record.
   - `hook.select` never returns a model for an empty E, so the hook runs no generation.
   - The learner received the D-19 contained answer, which the ranking never touches.
   - The pre-verified branch stays DI-83's (DI-127).
8. **Plan I "switch rate (MR-3 ...)" against invariant 9.** The switch rate is telemetry. MR-3 is computed only over the committed synthetic replay and labelled an engineering measurement, never asserted as met.
9. **Plan P "staging shadow run" against an empty staging registry and D-05.** Not done (DI-120).
10. **13.6 "a sustained CUSUM alarm (X5) also stops the line" against D-05.** "Sustained" means a second alarm on the same stream while its hold is open. It is logged and counted. The stop-the-line on delivered content is DI-123 (with DI-96).
11. **E4 "float with a stated rounding rule" against byte identity across platforms.**
    - All ranking arithmetic is `decimal.Decimal`, run inside `decimal.localcontext(CTX)` (prec 34, ROUND_HALF_EVEN, traps InvalidOperation, DivisionByZero and Overflow).
    - Values are quantised to `1e-18`. E4 allows this ("must make AC-9-8 byte-identical across runs and platforms").
12. **Table X "F_i: (rating − 1)/4" against no rating, and X3 flags existing only on legacy records (M5).**
    - F is missing on every shadow record, because the learner never saw that output (invariant 5: a rating attaches to what the learner saw).
    - A `feedback` input arises only for a record the learner was shown (delivery `delivered`) with an X3 item. None exists today: legacy records have no ranked generator, and the delivered path is DI-59.
    - `f_from_rating` is reserved, with no intake (DI-121, DI-97).
    - AC-9-2 is proven on event logs.
13. **Table X "S_i: F1 of citation precision and recall" against no record carrying it.** S is missing, and the weights renormalise (plan 6.4 "renormalise when F missing", applied to every missing signal). DI-128.
14. **E7 (a version change) against `GeneratorRef` having no version, and against Phase 6's existing X5 sightings (M6).**
    - The scan compares each candidate's current version with the version in state.
    - A clone generator's `model_id` is `"<model_id>@<model_version>"`, so every clone record names its version.
    - A record whose version is not the candidate's current version is skipped (`stale_version`).
    - So that one change opens one ranking window, the scan records the change under V3's lock with the key and version a record carries (`generator:<adapter_id>`, `<model_id>@<model_version>`), together with the `v3_model_versions` row. It reuses an existing event when V3 already knows that version.
    - A static generator's prompt-hash change uses the key `generator-prompt:<id>`, which no V3 sighting produces, so it never flip-flops against V3's `generator:` sighting.
15. **"Promotions held" scope.**
    - A model alarm or model change holds every promotion in contexts where that model is the incumbent or a challenger (`contexts: ["*"]`). A (model, cluster) alarm holds that cluster's contexts (`contexts: [<cluster>]`).
    - A hold lasts until its V3 window closes (`v3.scan.window_remaining(db, v3_event_seq) == 0`). The scan observes this and records it as a `hold_release` input.
    - With V3 off, no draws close the window, so the hold stays open (conservative; documented).
16. **Eq. (10) latency against no latency in the record.** `latency_ms` is null, l = 0, and λ_ℓ = 0 (D-06). DI-122.
17. **Eq. (10) cost.** u = `cost_units_per_call` / max over M (0 when the max is 0), in units, not USD (A-15; DI-122).
18. **Family-wise false alarms per 1,000 requests.** Live telemetry reports alarms per 1,000 consumed requests. The synthetic replay reports the false alarms (those before the injected shift).
19. **Initial Q̄.** The commissioning run's mean Q when commissioned, else 1/2 (`ranking.quality.initial_qbar`).
20. **The tier of a record with no V2 verdict.** Rule `tier-source-v1`: the V2 claim tier; else V1.6 (`not_assessment` gives `default_tier`, any other code gives `assessment_tier`); else `default_tier`.
21. **V1.7 corpus conflict.** Ignored for y. A record finalised `conflict_withheld` is skipped (`corpus_conflict`).
22. **E8/E12 tables.** The cursor is `ranking_scans` (append-only). The stop and its clear are control rows of `ranking_events` (`stop`, `clear_stop`), as are the `checkpoint` rows. They are not controller state.
23. **E10 "on" refused "everywhere".** `RANKING=on` is refused in development too.
24. **E7's queue reason.**
    - Schema-7 packages list Phase 6's four reasons plus `ranking_empty_eligible_set` (`v3/rules.QUEUE_REASONS_V7`). The parsed v3 params carry the version-appropriate list, and the SQLite queue-item guard checks every reason of `QUEUE_REASONS_V7`.
    - `QueueReason` gains the value additively (conflict 28 for the pinned gold-label schema).
    - It is not an X trigger, so `V3_COUNTED` is unchanged.
25. **E10's fake generate members.** No member is added. v7's development `fake-delta-v1` gains `fake.generate_rule: "extractive-clone-v1"`. Tests add further members in their own registries.
26. **Operational precondition (new).** The scan refuses (`uncommissioned`) while any static candidate has no `commission` event. Otherwise the uncommissioned prior (Beta(1,1), T = 0.05, D) would empty E on every record and enqueue one V3 item per shadow record into an unstaffed queue, tripping Phase 6's queue-age stop. Commissioning the static generator is the first runbook step (PD-54).
27. **R-d's "no generator-attributable escalation" and 4.3's V1 failure against D-21 (code-forced; M4).** Every development claim carries V1.3 `no_checker` (the checker's absence) and the `v1_3_flag` reason and D-20 interim withhold it causes. Read as generator failures they would make every record y = 0 and every model D. A V1.3 `no_checker` result is therefore not a verdict on the generator: it does not fail the first pass, its `v1_3_flag` reason is not an escalation, and V counts it as passing. Any other V1.3 flag (`not_enough_info`, `contradicted`, `below_support_threshold`) does.
28. **Conflict 24's additive `QueueReason` against the pinned `V3GoldLabel` schema (code-forced; M6).** Packages v5 and v6 pin `schemas/v3-gold-label.v1.schema.json`, whose reasons are Phase 6's four, and both stay readable. `GoldLabel.reasons` takes the five reasons; `GoldLabelV6Schema` reproduces the pinned v5/v6 schema exactly (checked by their structural checks), and package v7 pins `schemas/v3-gold-label.v1.r7.schema.json`. `v3.contracts.v3_schema_models(schema_version)` picks the models a package pins.

---

## 2. Architecture

```
ledger (response_ledger, append-only)
   │ ranking scan (worker: python -m app.workers.ranking scan; RANKING=shadow; ranking lock then V3 lock)
   ▼
inputs ──► ranking_events (append-only, hash chain)  ◄── commission / recommission / clear-stop (worker)
   │  config | availability | model_seen | model_change | commission | recommission_* | outcome | skipped | feedback | hold_release | tick
   ▼
controller.apply(state, input) -> (state', derived[])   (pure; Decimal in CTX; params and candidates from state; no DB, clock, LLM or randomness)
   │  derived: select | batch | promote | demote | alarm | hold
   ├─► ranking_states / ranking_incumbents (derived cache; replay must reproduce it byte for byte)
   ├─► alarm        ─► v3.events.record_cusum_alarm(source "phase9-cusum", db=scan session) ─► X5 window
   ├─► model_change ─► v3.scan.record_model_change(...) + v3_model_versions row (deduplicated) ─► X5 window
   └─► fallback     ─► v3.queue.upsert_item(reason ranking_empty_eligible_set)               ─► V3 item
control rows: checkpoint (state sha at a position), stop, clear_stop: not folded by apply
replay(events) == stored derived events, checkpoints and state? else stop replay_mismatch (scan refused until clear-stop)
hook.select(context, ledger_seq) (read-only) ─► development shadow generation only when RANKING_SHADOW_GENERATION=true
learner path: legacy contained answer; static generator in the two-pass shadow (unchanged)
```

| AC | Mechanism | Primary tests (13.1) |
|---|---|---|
| AC-9-1 | `signals.outcome_of` gives `Skip(reason)`; a skipped input changes only its counter | `test_ac_9_1_an_event_without_a_completed_verdict_leaves_alpha_beta_and_qbar_unchanged` |
| AC-9-2 | A `feedback` input sets F only; `trust`, `cusum` and `selection` never read F | `test_ac_9_2_a_learner_rating_changes_only_f_i` |
| AC-9-3 | `batch.close` streak over `n_d` consecutive context batches with h in E, strict `> delta`, `rating(h) >= rating(g)` | `test_ac_9_3_a_challenger_ahead_by_the_active_deadband_is_promoted_only_after_the_active_debounce` |
| AC-9-4 | `batch.fast_trip` at every batch close and every availability input; `select` incumbent-not-eligible | `test_ac_9_4_trust_below_the_tier_threshold_demotes_immediately` |
| AC-9-5 | `model_change`: deflation, `capped`; `recommission_pass` lifts the cap; X5 through Phase 6 | `test_ac_9_5_a_model_version_change_deflates_caps_at_c_and_raises_x5_until_the_golden_regression_passes` |
| AC-9-6 | `selection.select` gives the fallback decision; the scan enqueues V3; the hook generates nothing | `test_ac_9_6_an_empty_eligible_set_delivers_no_unverified_text_and_enqueues_a_v3_item` |
| AC-9-7 | CUSUM per response; alarm through `record_cusum_alarm`; holds; never demotes | `test_ac_9_7_a_cusum_alarm_raises_the_audit_to_the_x5_rate_holds_promotions_and_never_demotes` |
| AC-9-8 | `replay.replay` twice and in a subprocess; canonical bytes; stop on mismatch | `test_ac_9_8_one_event_log_replayed_twice_gives_byte_identical_final_states` |

---

## 3. Data shapes

### 3.1 Vocabulary (`services/ranking/vocabulary.py`, standard library only)

- `RANKING_VERSION "ranking-v1"`, `PARAMETERS_VERSION "ranking-params-v1"`, `EVENT_SCHEMA "ranking-event-v1"`, `STATE_SCHEMA "ranking-state-v1"`.
- `RANKING_FIRST_MAJOR 7` (equal to `config_package.RANKING_SCHEMA_VERSION`; E16).
- `CLUSTER_RULE "cluster-module-v1"`, `UNSCOPED "unscoped"`, `CLUSTERS` (the 11 `MODULE_BLUEPRINTS` slugs in order, kept equal by a test), `TASK_TYPE_RULE "tier-1-quiz-item-v1"`, `TIER_SOURCE_RULE "tier-source-v1"`.
- `TASK_TYPES ("explanation","worked_example","hint","quiz_item","summary","video_script")`, `ACTIVE_TASK_TYPES ("explanation","quiz_item")`.
- `RATINGS ("A","B","C","D")`.
- `INPUT_KINDS ("config","availability","model_seen","model_change","commission","recommission_pass","recommission_fail","outcome","skipped","feedback","hold_release","tick")`.
- `DERIVED_KINDS ("select","batch","promote","demote","alarm","hold")`.
- `CONTROL_KINDS ("checkpoint","stop","clear_stop")`. Together these are 21 kinds (`EVENT_KINDS`), none longer than 17 characters.
- `SKIP_REASONS ("unparsed","no_verification","generator_unknown","stale_version","not_generated","budget_exceeded","detector_down","kill_switch","v2_withheld","no_v2_verdict","panel_not_reached","corpus_conflict")`.
- `INELIGIBLE`: the gateway's seven reasons plus `"rating"`, `"capped"` and `"family_unknown"`.
- `QUEUE_REASON "ranking_empty_eligible_set"`, `STOP_REASONS ("replay_mismatch","state_mismatch")`, `CLEAR_CAUSES ("fixed_code","fixed_data","restored_backup")`, `SCAN_REFUSALS ("ranking_off","stopped","uncommissioned")`, `SEED_RULE "sha256-u64-v1"`.
- `ARITHMETIC "decimal-prec-34-half-even-quantize-1e-18-v1"`, `QUANTILE_RULE "decimal-regularized-incomplete-beta-bisection-v1"`, `CLONE_RULE "extractive-clone-v1"`, `STATIC_VERSION_RULE "evidential-prompt-hash-16-v1"`, `CHAIN_RULE "ranking-chain-v1"`, `GENESIS "0"*64`, `STATE_KEY "_state"`, `RANKING_SCAN_LOCK_KEY 7_401_209`.
- `RULES`: every rule id the package's ranking block must name (dotted paths), compared by the loader.

### 3.2 Runtime types (`services/ranking/types.py`; frozen dataclasses; no pydantic)

```python
@dataclass(frozen=True)
class Context:            # c = (k, t, r)
    cluster: str; task_type: str; tier: int
    def key(self) -> str: return f"{self.cluster}|{self.task_type}|{self.tier}"

@dataclass(frozen=True)
class ModelRef:
    adapter_id: str; family: str; provider: str; model_id: str; model_version: str; cost_units_per_call: int

@dataclass(frozen=True)
class Signals:            # each a Decimal in [0,1] or None (missing)
    V: Decimal | None; S: Decimal | None; K: Decimal | None; H: Decimal | None; F: Decimal | None

@dataclass(frozen=True)
class Outcome:
    ledger_seq: int; created_at: str; model: str; context: Context; y: int
    signals: Signals; cost_units: int; latency_ms: int | None; tier_source: str

@dataclass(frozen=True)
class Skip:
    ledger_seq: int; reason: str; model: str | None

@dataclass(frozen=True)
class Decision:
    kind: Literal["incumbent", "fallback"]
    model: str | None          # None iff kind == "fallback"
    eligible: tuple[str, ...]
    explore: str | None
    action: Literal["generate", "abstain"]   # "abstain" iff fallback; no text field exists
```

### 3.3 State (`services/ranking/state.py`; canonical JSON with `sort_keys`, separators `(",", ":")`, UTF-8; every number is a Decimal string from `numeric.to_str`, or an int count)

```json
{"schema": "ranking-state-v1", "parameters": {"<the canonical ranking block in force>"}, "parameters_sha256": "<64 hex>", "last_input_seq": 0,
 "models": {"<adapter_id>": {"version": "...", "family": "...", "provider": "...", "model_id": "...", "cost_units": 0,
                             "commissioned": false, "capped": false, "prior": {"alpha": "1", "beta": "1", "qbar": "0.5"},
                             "cusum": {"S": "0", "n": 0}}},
 "cluster_cusum": {"<adapter_id>|<cluster>": {"S": "0", "n": 0}},
 "contexts": {"<cluster|task|tier>": {
     "incumbent": null, "batch_seq": 0, "pending": [{"<full outcome>"}], "pending_since": null,
     "streaks": {"<adapter_id>": 0},
     "models": {"<adapter_id>": {"alpha": "...", "beta": "...", "T": "...", "qbar": "...", "n": 0, "cost_mean": "...", "latency_mean": null}}}},
 "holds": {"<hold_id>": {"stream": "...", "cause": "alarm|model_change", "contexts": ["*"], "models": ["..."]}},
 "availability": {"<adapter_id>": null},
 "counts": {"skipped": {"<reason>": 0}, "requests": 0, "fallbacks": 0, "explorations": 0, "switches": 0, "alarms": 0, "sustained": 0,
            "late_feedback": 0, "recommission_passes": 0, "recommission_fails": 0, "refused_inputs": 0}}
```

- The rating is not stored: `selection.live_rating` computes it from the stored T and the model's `capped` flag, so a cap or its release takes effect at once.
- A context model with no state starts from the model's prior (`selection.prior_state`).
- `state_sha256(state) = sha256(canonical bytes)`. The stop is not part of the state (conflict 22).
- `state.Params` holds the block's values as Decimals (`params_of(state)`, memoised by the block's sha256).

### 3.4 Events (`ranking_events.payload`, canonical JSON; `ranking-event-v1`)

**Inputs.** The scan or the worker writes them, and the replay folds only these.
- `config`: `{package_version, package_sha256, parameters_sha256, parameters}`. `parameters` is the full canonical ranking block; the controller refuses one whose sha256 does not match. It is appended on the first scan and whenever the block's sha256 changes.
- `availability`: `{models: {adapter_id: reason|null}}`, when it changed.
- `model_seen`: `{model: ModelRef}`.
- `model_change`: `{adapter_id, from_version, to_version, source: "registry"|"package"}` (`package` for a static generator's prompt-hash change). The row's `v3_event_seq` names its X5 event.
- `commission`: `{adapter_id, version, clean, failed, generated, mean_q, run_sha256}`.
- `recommission_pass` / `recommission_fail`: `{adapter_id, version, clean, failed, generated, run_sha256}`.
- `outcome`: `{ledger_seq, created_at, model, context, y, signals, cost_units, latency_ms, tier_source}` (`input_key` `ledger:<seq>`).
- `skipped`: `{ledger_seq, reason, model}` (`input_key` `ledger:<seq>`).
- `feedback`: `{ledger_seq, F, source: "x3"|"rating"}` (`input_key` `feedback:<seq>`).
- `hold_release`: `{hold_id}`.
- `tick`: `{at}` (the scan's `now`, ISO UTC).

**Derived.** Each is written right after the input that caused it. The replay recomputes it and compares bytes, and each must follow its own input.
- `select`: `{ledger_seq, context, eligible, kind, model, explore, u_explore}`; a fallback's row notes `v3_off` when V3 is off.
- `batch`: `{context, batch_seq, ledger_seqs, trigger: "count"|"time", states: {adapter_id: {alpha, beta, T, rating, qbar}}}`.
- `promote`: `{context, from, to, streak, delta_seen}`.
- `demote`: `{context, from, to, T, threshold, rating, available}`.
- `alarm`: `{stream, scope, statistic, p0, p1, h, observations, hold_id, sustained, created_at}`; the row's `v3_event_seq` names its `cusum_alarm` event.
- `hold`: `{hold_id, cause, contexts, models}`; the row's `note` is the hold id and its `v3_event_seq` the X5 event whose window it waits for.

**Control rows.** These are not folded by `apply`.
- `checkpoint`: `{state_sha256, last_input_seq}`. The scan writes it at its end, and the replay verifies the state sha at that position.
- `stop`: `{reason, expected_sha256, actual_sha256}`.
- `clear_stop`: `{cause: "fixed_code"|"fixed_data"|"restored_backup"}`.

**Hold ids.** `hold_id = "h-" + sha256(cause|stream|<input event seq>)[:16]`.

---

## 4. Algorithms (`services/ranking/*.py`; pure unless named "scan", "worker", "regression" or "hook")

### 4.1 Numerics (`numeric.py`)

- `CTX = Context(prec=34, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999, traps=[InvalidOperation, DivisionByZero, Overflow])`. Every arithmetic step of the ranking runs inside `localcontext(CTX)`, so the thread's current context never leaks in (a unit test runs the controller under precision 5 and ROUND_DOWN and gets the same bytes).
- `D(x)` accepts str, int or Decimal only (`TypeError` for a float or a bool). `q(x) = x.quantize(Decimal("1e-18"))`. `to_str(x)` is `format(q(x).normalize(), "f")`, with any zero, including negative zero, written as `"0"`.
- `log_gamma(x)`: shift x up to `x >= 30` (one product, one `ln`), then the Stirling series with 12 Bernoulli numbers (exact Fractions).
- `reg_inc_beta(x, a, b)`:
  - x ≤ 0 gives 0 and x ≥ 1 gives 1 (explicit endpoints).
  - Otherwise, the prefactor `exp(a ln x + b ln(1−x) − lnB(a,b))`, with `lnB` computed once per quantile call.
  - Lentz's continued fraction (at most 600 iterations, tolerance `1e-25`), with the symmetry rule when `x >= (a+1)/(a+b+2)`.
  - `ArithmeticError` when the iterations are exhausted.
- `beta_quantile(p, a, b)`: exactly 60 bisection steps on [0, 1], with no early exit. It returns `lo` quantised to `1e-12`, memoised by the canonical texts of its arguments.
- `ln_ratio(p0, p1) -> (A, B)` with `Decimal.ln`.
- `uniform(seed, *parts)`: the first 8 bytes of `sha256("|".join(("ranking-v1", seed, *parts)))`, divided by 2^64. Never `random`.
- **Runtime budget.** `run_ranking_replay.py --check` finishes within 60 s (M21: about 18 s).

### 4.2 Contexts (`contexts.py`)

- `span_modules(store)`: span id → frozenset of module slugs. It is built once per scan.
- `cluster_for(entry, modules, corpus_version)`: `unscoped` on a corpus mismatch or with no evidence; else the intersection over `retrieval.evidence`: exactly one slug gives that slug, otherwise `unscoped`.
- `tier_for(entry, package) -> (tier, source)` (conflict 20).
- `task_type_for(tier, package)`: `"quiz_item"` when `tier == package.v2.assessment_tier`, else `"explanation"`.

### 4.3 Outcomes (`signals.py`): `outcome_of(entry, *, ledger_seq, created_at, candidates, modules, corpus_version, package, current_versions=None) -> Outcome | Skip`

The rules are applied in order; the first match decides.

1. `entry is None` gives `unparsed`.
2. `entry.verification is None` gives `no_verification`. This includes every legacy record.
3. The record's model is `versions.generator_id`. Its version is the clone `@` suffix of `provenance.generator_model_id`, or `"p-" + evidential_prompt_hash[:16]` for a static generator. Not a candidate gives `generator_unknown`; not the current version (the state's, when given) gives `stale_version`.
4. `generation_attempts == 0` gives `not_generated`.
5. Final reasons that are not verdicts: `budget_exceeded` gives `budget_exceeded`; `checker_unavailable`, `ehmf_detector_down` or a non-empty `ehmf.detector_down` gives `detector_down`; `v2_kill_switch` gives `kill_switch`; `v2_degraded_withheld` gives `v2_withheld`; `conflict_withheld` gives `corpus_conflict`. An abstention with a pre-generation reason (a gate reason, `no_quotable_evidence`, `corpus_version_mismatch`) gives `not_generated`.
6. A V1 first-pass failure gives `Outcome(y=0)`. A failure is any of: `hard_fail`; `cycle_count > 0`; `final == "abstain"` with a post-generation V1 reason (`POST_GENERATION_V1`); an accepted-attempt result outside pass/mark other than V1.7's and V1.3's `no_checker` (conflict 27).
7. No `v2` block gives `no_v2_verdict`.
8. `v2.panel_reached` false gives `panel_not_reached`.
9. A V1-passed verdict without `v2`, or with `v2.outcome == "withheld"`, gives `v2_withheld`.
10. Otherwise `Outcome(y = 1 if clean (R-d) else 0)`.

Signals, all taken from the first pass:
- **V** = the share of verdicts whose V1 results pass (as in rule 6) and whose V2 outcome is `pass` at cycle 0. With no verdicts, V = 0.
- **K** = the mean over judged claims at cycle 0 of `1 − H/ln 3`, where H is the Shannon entropy of the family-verdict distribution over {SUPPORTED, CONTRADICTED, NOT_ENOUGH_INFO} (`signals.vote_agreement`), in Decimal; missing with no judged claim.
- **H** (v4 only) = `min(1, mean over the record's EHMF claims of Fraction(weight))` (rule `ehmf-claim-weight-density-v1`, the record's own weights); missing without EHMF claims.
- **S** is missing (conflict 13). **F** is missing (conflict 12).

`cost_units` is the candidate's cost. `latency_ms` is None.

### 4.4 Trust, quality and score (`trust.py`, `quality.py`, `score.py`)

- `update_trust`: `alpha' = q(gamma·alpha + y)` and `beta' = q(gamma·beta + 1 − y)`. `T = beta_quantile(quantile, alpha, beta)` is recomputed once per batch for each touched model.
- `rating(T, ratings, capped)`: A ≥ 0.95, B ≥ 0.90, C ≥ 0.80, else D. `capped` turns A or B into C.
- `permits(rating, tier, a_available)`: A permits tiers 1, 2 and 3; B permits tiers 2 and 3, plus tier 1 when no available, permitted, uncapped A model exists in the context; C and D permit none.
- `quality(signals, weights)`: `Q = (1 − (H or 0)) · Σ w_s s / Σ w_s` over the present signals among V, S, K and F (0 when none is present). `ewma(qbar, Q, eta) = q((1−eta)qbar + eta·Q)`. `f_from_rating(r) = (r−1)/4` for r in 1..5.
- `score = q(T·qbar − lam_u·u − lam_l·l)`, with `u = cost / max_cost` (0 if the max is 0) and `l = 0`.

### 4.5 Selection (`selection.py`; Algorithm 1 lines 1-12)

`select(state, params, key, *, ledger_seq) -> (Decision, u_explore)`. Candidates and parameters come from the state; `ensure_models` first gives every candidate a context state.

1. `E` = the models whose availability is null and which `permits(live_rating(m, c), tier, a_available)`.
2. `E == []` gives `Decision("fallback", None, (), None, "abstain")`.
3. `g` is the incumbent if it is in E. Otherwise g is the argmax of R, with ties broken by the smaller adapter id (`argmax`: comparisons only). Replacing a set incumbent counts as a switch; setting the first incumbent (from None) does not.
4. Exploration: `u = uniform(seed, "explore", key, str(ledger_seq))`. If `u < eps_s`: the challengers are the non-incumbent models that are available and in E or rated C (capped ones included); `θ_m = beta_quantile(uniform(seed, "theta", key, str(ledger_seq), m), alpha_m, beta_m)`; h is the argmax of `θ_m·qbar_m − penalties`, ties by adapter id.

### 4.6 Micro-batches, promotion and demotion (`batch.py`)

- **Pending.** Before an `outcome` is appended to `contexts[c].pending`, the open batch is closed (trigger `time`) when `outcome.created_at >= pending_since + seconds`. The outcome is then appended, and `pending_since` is the first pending `created_at`.
- **Count and time triggers.** A batch closes on count when `len(pending) == responses` (25). A `tick` closes every batch with `at >= pending_since + seconds` (900), in context-key order. The batch identity is `(context, batch_seq)`.
- **Feedback.** A `feedback` input on a pending outcome sets its F. On a closed batch it counts `late_feedback` only. It never touches alpha, beta, T, the CUSUM, streaks or the incumbent.
- **`close(state, params, c, trigger, derived)`**, in this order:
  1. In ledger order, run `update_trust` and `ewma` for each outcome's model, `n += 1`, and the cost EWMA.
  2. Recompute T for each touched model, and emit `batch` (with each touched model's live rating).
  3. **Promotion.** For each challenger h ≠ g with state in c: if `h ∈ E` and `R(h,c) − R(g,c) > delta`, then `streaks[h] += 1`; otherwise `streaks[h] = 0`. Promote when `streaks[h] >= n_d` and `RATINGS.index(rating(h)) <= RATINGS.index(rating(g))` and no open hold covers c with g or h; then emit `promote`, set the incumbent and reset every streak in c. With no incumbent, nothing is promoted. Every batch of the context counts, whichever model's outcomes it holds.
  4. **Fast trip.** If g is set and either `not permits(rating(g,c), tier, a_available)` or g is unavailable: the incumbent becomes the argmax over E \ {g}, or None; emit `demote`, count a switch and reset the streaks. There is no debounce, and a hold does not block it.
- **Availability.** The `availability` input runs the fast trip for every incumbent. This covers a model going down and a tier-1 B incumbent once an A model is available.
- **A CUSUM alarm never demotes.**

### 4.7 CUSUM (`cusum.py`; eq. (11))

- `update(S, e, A, B) = q(max(0, S + e·A + (1−e)·B))`, with `e = 1 − y`. It runs on every `outcome` for the stream `model:<adapter_id>` and the stream `model-cluster:<adapter_id>:<cluster>`.
- `S > h` triggers an alarm: emit `alarm` (`observations = n` since the last reset); open a hold (conflict 15) and emit `hold`, unless the stream's hold is open, when the alarm is `sustained` (counted, logged `ranking.sustained_alarm`) and names the open hold; reset the chart.
- **Scan side effect.** `record_cusum_alarm(CusumAlarm(stream, float(p0), float(p1), float(h), float(statistic), observations, raised_at=<outcome created_at>, source="phase9-cusum"), settings=, package=, db=session)`. The returned seq goes to the row's `v3_event_seq` column, and to the hold's.

### 4.8 Model change and (re-)commissioning (`recommission.py`, controller)

- **Model change** for adapter m: in every context, alpha and beta are deflated (`q(x·deflation)`, 0.3) and T is recomputed, and so is the prior; `capped ← true`; both charts reset; a hold opens (cause `model_change`, `contexts: ["*"]`), and the version is updated.
- **Scan side effect (conflict 14),** inside V3's lock: look up `v3_model_versions` for the key (`generator:<adapter_id>` with version `<model_id>@<model_version>` for a registry candidate; `generator-prompt:<id>` with the prompt-hash version for a static one). If V3 already knows that version, reuse its `model_change` event seq; otherwise call `record_model_change(...)` with `source="ranking"`, `from_ledger_seq=<ledger head>` and `window=x5_window_deliveries`, and insert the `v3_model_versions` row.
- **Cap release.** `recommission_pass` sets `capped ← false`. `recommission_fail` changes only a counter. Elapsed time never lifts the cap. A recommission for another version than the model's counts `refused_inputs`.
- **`commission`** sets the prior (`alpha = 1 + clean`, `beta = 1 + failed`, `qbar = mean_q`), marks the model `commissioned`, and resets its context states to the prior. It is refused (counted `refused_inputs`) for a model that already has outcomes or another version.
- **Uncommissioned prior.** Beta(1,1) with qbar 1/2, which is rated D. The scan refuses while a static candidate is uncommissioned (conflict 26).
- **`regression_run(model, *, package) -> RunResult`:** runs `TwoPassPipeline(generator=generator_for(model))` over each recommission query with `Settings(environment="development", v1_pipeline="enforce", model_gateway="shadow", ehmf="shadow", v3_queue="off", ranking="off")`, its own gateway (an in-memory daily budget), its own evidential cache and a clear V3 stop (the regression has no V3 queue), with `record=False` (no database); applies `outcome_of` to each record. It passes when `failed == 0` and `generated >= min_generated` (8). `run_sha256` is the canonical sha256 of `{model, package_sha256, golden_set_sha256, outcomes}`. M20 has the counts.

### 4.9 The controller (`controller.py`)

`apply(state, event) -> (state', derived)` is total over `INPUT_KINDS` (`apply_in_place` mutates a state the caller owns). It reads only the event and the state, which holds the parameters and the candidates.

| Input | Effect |
|---|---|
| `outcome` | Time-close if due, then `select`, then the CUSUM update and alarms, then pending, then count-close. |
| `skipped` | Counts only. |
| `tick` | Time-close. |
| `availability` | Update, then the fast-trip check on every incumbent. |
| `model_seen` | Add the candidate with the uncommissioned prior. |
| `model_change` | 4.8. |
| `commission` / `recommission_*` | 4.8. |
| `feedback` | 4.6. |
| `hold_release` | Remove the hold. |
| `config` | Replace the parameters and their sha256 (refused when they differ). |

It reads no clock, no randomness beyond `numeric.uniform`, no DB and no environment. Control rows are never passed to `apply`.

### 4.10 The scan (`scan.py`; the only module that writes ranking tables)

`run_scan(*, settings, package, session_factory=SessionLocal, store=None, now=None, limit=500, gateway=None)`. It requires the mode `shadow`, otherwise `RankingOff`. It retries a busy SQLite as the V3 scan does. One transaction:

1. On PostgreSQL, `pg_advisory_xact_lock(7_401_209)`, then `pg_advisory_xact_lock(V3_SCAN_LOCK_KEY)`, always in this order.
2. If the last stop/clear_stop control row is `stop`, refuse (`RankingStopped`).
3. Load `"_state"`. Its sha256 must equal the last `checkpoint`'s. The first scan, with no rows, starts from `empty_state`. On a mismatch, append `stop {state_mismatch}`, commit, log `ranking.stop` and return stopped.
4. Append `config` if the block's sha256 differs; then per candidate `model_seen` (first sighting) or `model_change` (with the side effect in 4.8); then `availability` if it changed (registry candidates `get_gateway().ineligible_reason(spec, settings=settings)`; static candidates `kill_switch` when `MODEL_GATEWAY_KILL_SWITCH != "none"`, else null).
5. If any static candidate is uncommissioned, write the checkpoint and state, commit, and raise `RankingUncommissioned` (worker exit 2).
6. For each open hold with `window_remaining(db, v3_event_seq) == 0`, append `hold_release`.
7. Read ledger rows past the cursor (`max(ranking_scans.to_seq)`), in seq order, up to `limit`. For each row: parse it with `v3.queue.parse_entry`; build the outcome or skip input, unique on `input_key "ledger:<seq>"` (ON CONFLICT DO NOTHING RETURNING); apply it and append the derived events; perform the side effects: the alarm (4.7) and the fallback, which upserts the V3 item `ItemSpec(claim_key="", subject="response", triggers=frozenset(), reasons=frozenset({"ranking_empty_eligible_set"}), ehmf_types=response_types(entry), k=response_k(entry), held=False)` when `v3.mode(settings, package) != "off"`, else notes `v3_off`.
8. Flags: for each pending outcome of a record the learner was shown (delivery `delivered`; none today; conflict 12), append `feedback` when `v3.feedback.f_i(db, seq) == 0.0`.
9. Append `tick {at: now}` and apply it.
10. Append the `ranking_scans` row and the `checkpoint`, write `ranking_states` and `ranking_incumbents`, and commit.

`append_inputs(db, inputs, *, settings, package, now, gateway=None)` appends operator inputs (commission, recommission) under the same locks after steps 2-4, then the checkpoint and state, in the caller's transaction. The ledger is only read.

### 4.11 Replay and the stop (`replay.py`; AC-9-8; plan L)

- **`replay(events) -> Replayed(state, derived, checkpoints)`.** It folds the input events in seq order from `empty_state()`, takes the parameters from the `config` events, and skips control rows. At each stored `checkpoint` position it records the state sha.
- **`compare(rows, stored_state_text) -> ReplayCheck(ok, state_sha256, stored_sha256, first_mismatch_seq, reason)`** checks, in order: the hash chain (`chain`); the replay itself (`input:<error>`); each recomputed derived event against the stored ones, each paired with the input row before it (same order, count, kind and bytes; `derived`); each checkpoint's sha (`checkpoint`); the final state bytes against the stored `"_state"` row (`state`). `check(db)` loads the log and compares.
- **`replay --check`** (worker) runs `check` and two more replays. On a mismatch it appends `stop {replay_mismatch, expected, actual}`, logs `ranking.stop` at ERROR and exits 1.
- **`clear-stop --cause C`** refuses (exit 2) unless two in-process replays are equal. It then rewrites `ranking_states` and `ranking_incumbents` from the replay, appends a `checkpoint` and appends `clear_stop`.
- **Rollback.** `RANKING=off` stops the scan and the hook. Nothing is deleted.

### 4.12 Shadow generation and the hook (`generators.py`, `hook.py`; development only)

- **`CloneGenerator(spec, package, *, settings)`** is the extractive generator with `ref = GeneratorRef(generator_id=spec.adapter_id, model_id=f"{spec.model_id}@{spec.model_version}", kind="extractive", prompt_hash=canonical_sha256({"id": spec.adapter_id, "rule": "extractive-clone-v1", "base": tutor_pipeline.evidential_prompt_hash}))`. It is refused unless the provider is `fake`, `fake_generate_rule == "extractive-clone-v1"`, `generate` is a capability and the environment is development. It makes no gateway or network call.
- **Provenance audit (`ledger._provenance_problems`, `clones=ledger.clone_prompt_hashes(package)`).** A `shadow` record whose `generator_id` is a development-registry generate member with `extractive-clone-v1` is checked against the clone rule's prompt hash instead of `generators_allowed` and the package hash. Every other generator id is reported as before, and without `clones` no generator is a clone.
- **`generator_for(model, *, package, settings)`** returns the static generator for a static model, otherwise a `CloneGenerator`.
- **`hook.select(context, *, ledger_seq, settings, package, session_factory)`** is read-only: it reads `ranking_states` `"_state"` and refuses unless the mode is `shadow` (None before the first scan). `ledger_seq` is the shadow record's own seq, so the scan's later `select` for that record draws the same exploration.
- **`hook.guarded_after_shadow(job, result, ...)`** is called by `run_shadow` after a successful run, only when `settings.ranking_shadow_generation` is true; `after_shadow` runs in its own `try`:
  - it skips unless the mode is `shadow` and the record was appended; it computes the context from `result.entry` and calls `hook.select(..., ledger_seq=result.appended.seq)`;
  - with a fallback decision it runs nothing;
  - otherwise the model to run is `decision.explore` if set, else `decision.model` if it is not the record's generator;
  - it makes at most one run, with the learner-free resolved input, `response_id = "shadow-" + uuid4()`, `delivery="shadow"`, the same `shadowed_response_id` and the remaining shadow budget;
  - a fault logs `ranking.shadow_generation_failed` and increments `hook.SHADOW_GENERATION["failed"]`. It never marks the original shadow run as failed and never reaches the learner.
- **Panel.** Such a run's V2 panel excludes the clone's family (`registry.generator_family` resolves a generate member's family). A candidate whose family does not resolve is never offered.

### 4.13 Metrics (`metrics.py`)

`slis(db, package, *, window_events=20000)` reports:
- `micro_batch_latency_s` (F-3: the p50 and p95 of the `batch` row's `observed_at` minus the last outcome's ledger `created_at`);
- `switch_rate_per_1000` per context (changes of the selected incumbent, the first not counted);
- `fallback_rate` and `exploration_share` (per 1000 requests);
- `cost_units_mean` per model;
- `latency: null`;
- `ratings` per context (with the incumbent);
- `cusum` (S per stream, alarms, `alarms_per_1000_requests`, sustained);
- `skipped` by reason;
- `holds_open`;
- `replay.stopped`;
- `evidence_class: "telemetry, not E4 results (invariant 9)"`.

They appear in `python -m app.workers.ranking status` and under `ranking` in the reviewer-only `GET /v3/metrics` (null when the mode is off).

### 4.14 Mode and start-up (`__init__.py`, `package_check.py`)

- `ranking.mode(settings, package)` is `off` with no ranking block, with a reason set, or when the setting is off. Otherwise it is `shadow`.
- `main._check_ranking_package` runs after `_check_ehmf_package`, with `check_ranking_package(package, structural=False)`. It checks the versions and vocabulary, the cluster list against `CLUSTERS` and `MODULE_BLUEPRINTS`, and the two hand fixtures reproduced to 3 decimals. A problem stops a governed start-up when `RANKING != off`. Otherwise the check sets the reason and logs `ranking.unavailable`. It makes no database read or write.
- `structural=True` also checks the recommission set's sha256 and item count and that the replay report exists.

---

## 5. Configuration package v7 (`apps/api/app/config_package/v7.json`)

### 5.1 File

v7 is v6 with:
- `package_version "7.0.0"`, `schema_version 7`, `phase "9"`, `created "2026-11-23"`.
- `supersedes {"package_version": "6.0.0", "sha256": "cd16a12360b01b1250fdbb339da4c71701828197cd8dcd2629a6a9a34a3d5327", "readable_until": "the release after the Phase 9 merge"}`.
- `gateway.registries.development[fake-delta-v1].fake = {"rule": "verbatim-support-v1", "generate_rule": "extractive-clone-v1"}`.
- `v3.triggers.queue_reasons`: Phase 6's four plus `ranking_empty_eligible_set`; `v3.schemas.V3GoldLabel.path` `schemas/v3-gold-label.v1.r7.schema.json` (conflict 28).
- `owner_decisions` gains:
  - `D-28`: `{"state": "open", "owner": "PO", "text": "D-28 OPEN DECISION: Phase 9 live-routing go-ahead (shadow is the default) after the E4 report [VBT RevB: p. 19, Sec. IX-B, Table XVII, MR-3]. PO.", "hold": "H11", "behaviour": "RANKING=on refused everywhere"}`;
  - `D-15`: `{"state": "recommended", "behaviour": "research replay only in the research environment"}`;
  - `RANKING-TOPIC-CLUSTERS`: `{"state": "open", "owners": ["PI","PO"], "text": "topic clusters [Evidence E-89], whose definition is an OPEN DECISION.", "applied": "cluster-module-v1 (PD-50)"}`;
  - `RANKING-PARAMETERS`: `{"state": "open", "owner": "PI", "text": "Decision owners: Principal Investigator (parameters), Product Owner (routing)."}`;
  - `D-06.operator_values` adds `ranking.penalties`.
- `flag_policy.ranking` (5.2), `phase9_exit_passed false`, `phase9_exit_evidence null`, and the authority adds `PD-58 (DI-117)`.
- The `ranking` block (each sub-block also names its PD as `record`):

```json
"ranking": {
  "version": "ranking-v1", "parameters_version": "ranking-params-v1", "provisional": true,
  "authority": "plan Phase 9 A: \"PAPER-SPECIFIED REQUIREMENT (defaults are provisional; Table XI; re-estimated on E4 data)\"; PD-50..PD-59; DI-117",
  "decision_owners": {"parameters": "PI", "routing": "PO"},
  "contexts": {"cluster_rule": "cluster-module-v1", "unscoped": "unscoped", "clusters": ["<the 11 MODULE_BLUEPRINTS slugs, in order>"],
               "task_types": ["explanation","worked_example","hint","quiz_item","summary","video_script"], "active_task_types": ["explanation","quiz_item"],
               "task_type_rule": "tier-1-quiz-item-v1", "tier_source_rule": "tier-source-v1", "provisional": true, "owner_decision": "RANKING-TOPIC-CLUSTERS"},
  "models": {"static": ["extractive-d19-v1"], "static_version_rule": "evidential-prompt-hash-16-v1", "registry_capability": "generate", "clone_rule": "extractive-clone-v1",
             "static_requires_commission": true},
  "trust": {"gamma": "0.995", "quantile": "0.05", "quantile_rule": "decimal-regularized-incomplete-beta-bisection-v1", "bisection_steps": 60},
  "quality": {"weights": {"V": "0.35", "S": "0.30", "K": "0.15", "F": "0.20"}, "eta": "0.05", "missing": "drop-and-renormalise-v1",
              "h_rule": "ehmf-claim-weight-density-v1", "v_rule": "first-pass-v1-v2-pass-share-v1", "k_rule": "one-minus-normalised-vote-entropy-v1",
              "s_rule": "missing-until-d21", "f_rule": "shown-records-only-rating-minus-one-over-four-flag-zero-v1", "initial_qbar": "0.5"},
  "ratings": {"A": "0.95", "B": "0.90", "C": "0.80"},
  "tier_permissions": {"A": [1,2,3], "B": [2,3], "B_tier_1_when_no_A": true, "C": [], "D": []},
  "clean_rule": "first-pass-no-correction-no-generator-escalation-v1",
  "selection": {"eps_s": "0.05", "thompson": "seeded-inverse-cdf-v1", "tie_break": "adapter_id", "first_incumbent_is_switch": false},
  "promotion": {"delta": "0.05", "n_d": 3, "comparison": "strictly-greater", "streak": "eligible-batches-only-v1", "rating_condition": "rating(h) >= rating(g)", "demotion": "immediate"},
  "micro_batch": {"responses": 25, "seconds": 900, "time_trigger": "record-time-and-scan-tick-v1"},
  "cusum": {"p0": "0.05", "p1": "0.15", "h": "4.0", "streams": ["model", "model_cluster"], "reset_on_alarm": true,
            "hold": "until-x5-window-closes-v1", "sustained": "second-alarm-while-held-v1", "demotes": false},
  "recommission": {"deflation": "0.3", "cap": "C", "pass_rule": "no-failed-first-pass-min-generated-v1", "min_generated": 8,
                   "gateway_mode": "shadow", "commissioning_prior": "one-plus-clean-one-plus-failed-v1", "uncommissioned_prior": {"alpha": "1", "beta": "1"},
                   "golden_set": {"version": "golden-set-v1", "path": "docs/evaluation/phase7/golden_set_v1.json", "sha256": "<= ehmf.golden_set.sha256>", "items": 40, "target_items": 50}},
  "penalties": {"lambda_u": "0", "lambda_l": "0", "cost_rule": "cost-units-over-max-v1", "latency_target_ms": null, "operator_policy": "D-06"},
  "fallback": {"empty_eligible_set": "abstain_and_enqueue_v3", "pre_verified_source": null, "queue_reason": "ranking_empty_eligible_set"},
  "replay": {"event_schema": "ranking-event-v1", "state_schema": "ranking-state-v1", "arithmetic": "decimal-prec-34-half-even-quantize-1e-18-v1",
             "report": "docs/evaluation/phase9/ranking_replay_v1.json", "stop": "replay_mismatch", "stop_refresh_s": 60},
  "seed": "ranking-seed-v1",
  "live_routing": {"state": "refused", "decision": "D-28", "hold": "H11"},
  "hand_fixtures": [{"alpha": 95, "beta": 5, "lower_bound": "0.910"}, {"alpha": 190, "beta": 10, "lower_bound": "0.922"}]
}
```

New files: `v7.json`, `v7.json.sha256` and `schemas/v3-gold-label.v1.r7.schema.json`. v1-v6 and every existing schema file are unchanged. No new ledger entry schema is added.

### 5.2 Loader (`core/config_package.py`)

- `DEFAULT_PACKAGE_PATH = v7.json`, `V6_PACKAGE_PATH = v6.json`.
- `RANKING_SCHEMA_VERSION = 7` (equal to `RANKING_FIRST_MAJOR`), and `LATEST_SCHEMA_VERSION = RANKING_SCHEMA_VERSION`. The bound is `1 <= schema_version <= LATEST_SCHEMA_VERSION`. `EHMF_SCHEMA_VERSION` stays 6, and every `>= EHMF_SCHEMA_VERSION` rule applies to schema 7.
- `ConfigPackage.ranking: RankingParams | None` (`version`, `parameters_version`, the canonical `block`, `parameters_sha256`, `static_models`, `clusters`, `active_task_types`, `cluster_rule`, `min_generated`, the golden-set pin, `report_path`, `stop_refresh_s`, `live_routing`, `provisional`); `FlagPolicy.phase9_exit_passed` and `phase9_exit_evidence`.
- `_parse_ranking(raw, *, decisions, v2, ehmf, tutor)` refuses:
  - an unmarked provisional block or `contexts` block, a version or a rule id (`vocabulary.RULES`) other than the code's, decision owners other than PI and PO;
  - clusters other than `CLUSTERS`, or task types other than the code's;
  - static models other than the package's allowed, wired generators with a family;
  - a decimal value given as a JSON number;
  - gamma outside (0.9, 1) or a quantile outside (0, 0.5); bisection steps other than 60;
  - weights that are not four non-negative values summing to 1; eta outside (0, 1]; an initial Q̄ outside [0, 1];
  - ratings not strictly descending in (0, 1); tier permissions other than Sec. VII-B's;
  - eps_s outside [0, 0.5], delta outside [0, 1), a true `first_incumbent_is_switch`;
  - `n_d < 1`, `responses < 1`, or `seconds` outside 60..86400;
  - CUSUM values breaking `0 < p0 < p1 < 1`, or `h <= 0`; streams other than model and model_cluster, no reset or a demoting chart;
  - deflation outside (0, 1], or a cap other than "C";
  - `min_generated < 1`, a `gateway_mode` other than "shadow", an uncommissioned prior other than Beta(1, 1);
  - a recommission golden set other than `ehmf.golden_set`'s, or a target other than 50;
  - λ ≠ "0" or a non-null latency target while D-06 is open, or `D-06.operator_values` without `ranking.penalties`;
  - a non-null `pre_verified_source`, another queue reason;
  - `live_routing.state` other than "refused" while D-28 is open;
  - `stop_refresh_s` outside 1..3600; hand fixtures other than plan J's;
  - a missing owner decision (`D-28`, `D-15`, `RANKING-TOPIC-CLUSTERS`, `RANKING-PARAMETERS`, `D-06`).
- `_parse_adapter` (schema ≥ 7): a fake member with `generate` must name `fake.generate_rule` in `WIRED_FAKE_GENERATE_RULES` (`{"extractive-clone-v1"}`), and a member without `generate` must not. Below schema 7 the key is refused. `AdapterSpec.fake_generate_rule: str | None = None` is the last field, and `public()` is unchanged.
- `_parse_v3`: for schema ≥ 7, `queue_reasons` must equal `QUEUE_REASONS_V7`, and the parsed params carry it. Below 7, `QUEUE_REASONS`. `v3/package_check` picks the same way, and checks the schema pins against `v3_schema_models(package.schema_version)`.
- `_parse_flag_policy` (schema ≥ 7): `flag_policy.ranking` holds `values [off, shadow, on]`, the code's defaults, `on_requires ["phase9_exit_passed", "D-28"]`, `on_everywhere "refused_while_d28_open"`, and `shadow_generation {"default": false, "development_only": true}`. `phase9_exit_passed` must be a bool, and true needs evidence.
- A guard test asserts that no schema rule compares with the literal 7.

### 5.3 Scripts (`scripts/config_package.py`)

- The default path is v7.
- `--check` runs `check_ranking_package(structural=True)` for a package with a ranking block and prints a ranking summary.
- `--rehash` copies `ehmf.golden_set`'s pin into the recommission pin; `--write-schemas` writes each package's V3 schemas from `v3_schema_models(schema_version)`.
- CI keeps `--check --path v6.json` for one release (DI-126).

### 5.4 History and golden run

`python scripts/run_golden_set.py --write docs/evaluation/phase7/golden_run_v1.json --base-ref origin/main` (with `--allow-dirty` on the finished change) appends `{"version": "7.0.0", "sha256": <v7>}` to `package_versions.json`. The history is never hand-edited.

---

## 6. Settings (`app/core/config.py`)

| Setting (env) | Type / default | Freeze rationale |
|---|---|---|
| `RANKING` | `Literal["off","shadow","on"] \| None = None`. None resolves to `RANKING_DEFAULT_DEVELOPMENT` ("shadow") in development and `RANKING_DEFAULT_ELSEWHERE` ("off") elsewhere. | "on" is refused in every environment while the package's D-28 is not decided or `phase9_exit_passed` is false (`_refuse_ranking_on`: reads the package lazily; `ValueError` naming D-28 and H11). Shadow outside development is a recorded override (`ranking_shadow`). It changes no learner path, and it adds audit (X5) and V3 items in that environment. |
| `RANKING_SHADOW_GENERATION` | `bool = False` | Development only (`ValueError` elsewhere). |

- `main._record_configuration_overrides` adds `ranking_shadow` and `ranking_shadow_generation`.
- `infra/cloudrun/api-production.env.example.yaml` sets `RANKING: "off"`.
- `run_golden_set.py`, `run_v1_fixtures.py`, `run_v2_fixtures.py` and `run_v3_residual_report.py` set `ranking="off"`.
- The test fakes are not edited: the ranking does nothing at turn time unless shadow generation is on.

---

## 7. File-by-file changes

### 7.1 NEW `apps/api/app/services/ranking/`

| File | Contents |
|---|---|
| `__init__.py` | `RANKING_UNAVAILABLE_REASON`, `mode()`, `RankingOff`, `RankingStopped`, `RankingUncommissioned` |
| `vocabulary.py` | 3.1 and `CLUSTERS` (stdlib only) |
| `numeric.py` | 4.1 |
| `types.py` | 3.2 |
| `contexts.py` | 4.2 |
| `models.py` | `candidates(package, settings)`, `record_version(entry)` and `model_of_record(entry, candidates)` |
| `signals.py` | 4.3 |
| `trust.py`, `quality.py`, `score.py` | 4.4 |
| `selection.py` | 4.5 and the state views (`ensure_models`, `live_rating`, `eligible_set`, `ranking_score`, `argmax`) |
| `batch.py` | 4.6 |
| `cusum.py` | 4.7 |
| `recommission.py` | 4.8 |
| `state.py` | 3.3, `canonical`, `state_sha256`, `empty_state`, `Params`, `params_of` |
| `controller.py` | 4.9 |
| `scan.py` | 4.10 |
| `replay.py` | 4.11 and `process_stop_state` |
| `generators.py`, `hook.py` | 4.12 |
| `metrics.py` | 4.13 |
| `synthetic.py` | 8.3 scenarios (numbers only) |
| `package_check.py` | 4.14 |

The pure modules import no DB, gateway, HTTP client or clock. No ranking module imports learner-record, progress, intelligence, microlearning, auth or route modules, or a language-model client. Logs go to `qcai.ranking`.

### 7.2 NEW elsewhere

- `apps/api/app/workers/ranking.py`. Commands: `scan [--limit N] [--until-done]`, `status`, `replay --check`, `commission ADAPTER`, `recommission ADAPTER`, `clear-stop --cause {...}`. Exit codes: 0; 1 (a stop, a failed check, a failed regression); 2 (usage, or refused: off, stopped, uncommissioned, unknown adapter, replays that differ).
- `apps/api/alembic/versions/20261123_phase9_ranking.py`.
- `v7.json`, its sidecar and `schemas/v3-gold-label.v1.r7.schema.json`.
- `scripts/run_ranking_replay.py`.
- `docs/evaluation/phase9/` (`README.md`, `ranking_replay_v1.json`, `hand_fixtures_v1.json`).
- This spec.
- `docs/adr/ADR-011-verified-trust-ranking.md`.
- The tests: `test_phase9_acceptance.py`, `test_ranking_units.py`, `ranking_fakes.py`.

### 7.3 MOD

- `core/config.py` (6) and `core/config_package.py` (5.2).
- `gateway/registry.py` (`fake_generate_rule`) and `gateway/adapters.py` (`WIRED_FAKE_GENERATE_RULES`).
- `v3/events.py`: `record_cusum_alarm(..., db: Session | None = None)`. With `db` it inserts in the caller's session and does not commit.
- `v3/scan.py`: `record_model_change` returns the inserted seq, and a new `window_remaining(db, v3_event_seq) -> int`. Existing callers are unchanged.
- `v3/rules.py` (`RANKING_QUEUE_REASON`, `QUEUE_REASONS_V7`), `v3/contracts.py` (`QueueReason`, `GoldLabelV6Schema`, `v3_schema_models`), `v3/package_check.py`, `api/routes/v3.py` (`/v3/metrics` gains `ranking`).
- `services/ledger.py` (`clone_prompt_hashes`, `_provenance_problems`'s clone rule, `SCHEMA_REVISION = "20261123_phase9_ranking"`).
- `tutor_pipeline/shadow.py`: one call to `ranking.hook.guarded_after_shadow` after a successful run, only under `RANKING_SHADOW_GENERATION`.
- `core/schema_upgrades.py` (`_guard_ranking_tables`; the queue-item reasons guard over `QUEUE_REASONS_V7`), `db_models.py` (four classes), `main.py` (`_check_ranking_package`, the `/ready` fields, the overrides).
- `scripts/config_package.py`, `scripts/run_golden_set.py`, `run_v1_fixtures.py`, `run_v2_fixtures.py`, `run_v3_residual_report.py`.
- `.github/workflows/ci.yml` (14).
- `infra/cloudrun/api-production.env.example.yaml` (`RANKING: "off"`).
- Docs (15).
- `apps/api/tests/conftest.py`: reset `RANKING_UNAVAILABLE_REASON` and the ranking stop cache.
- The records (12.2).
- Learner routes, `api/routes/ledger.py` and the erasure code are unchanged.

---

## 8. Database

### 8.1 Revision `20261123_phase9_ranking` (down_revision `20261123_phase7_ehmf`)

| Table | Columns | Keys and indexes | Rule |
|---|---|---|---|
| `ranking_events` | `seq` PK autoincrement; `kind` String(24) CHECK in the 21 kinds; `context_key` String(160) null; `model_key` String(160) null; `ledger_seq` Integer null; `batch_seq` Integer null (set on `batch` rows only); `input_key` String(64) null; `payload` Text; `prev_sha256`, `sha256` String(64); `v3_event_seq` Integer null; `note` String(32) null; `observed_at` DateTime(tz) | `uq_ranking_events_input (input_key)`; `uq_ranking_events_batch (context_key, batch_seq)`; `ix_ranking_events_kind`; `ix_ranking_events_ledger_seq` | append-only (UPDATE and DELETE refused on both dialects; TRUNCATE refused on PostgreSQL) |
| `ranking_scans` | `seq` PK; `from_seq`, `to_seq`, `records`, `outcomes`, `skipped`, `batches`, `alarms`, `fallbacks` Integer; `package_version` String(32); `package_sha256` String(64); `created_at` | — | append-only |
| `ranking_states` | `state_key` String(200) PK (`"_state"` holds the canonical state; `"<model>\|<context>"` rows are a queryable copy, E8); `payload` Text; `sha256` String(64); `updated_event_seq` Integer | — | derived cache |
| `ranking_incumbents` | `context_key` String(160) PK; `model_key` String(160) null; `since_event_seq` Integer | — | derived cache |

- The chain is `sha256 = sha256(prev_sha256 + "|" + kind + "|" + payload)` (rule `ranking-chain-v1`, genesis `"0"*64`). `observed_at` is outside the hash.
- No column matches the erasure identity pattern. No table holds a user id or text.
- **Guards** (`_guard_ranking_tables`). They run after the EHMF guard and are re-created only when not current. PostgreSQL: ROW UPDATE/DELETE and STATEMENT TRUNCATE triggers on `ranking_events` and `ranking_scans`, executing Phase 6's `v3_append_only()`. SQLite: no-update and no-delete triggers.
- **Downgrade.** Refused while `ranking_events` holds rows, unless run as `alembic -x allow_ranking_drop=true downgrade 20261123_phase7_ehmf`. It drops the triggers, then the indexes, then the four tables, and never `v3_append_only()`.
- **Dialects.** Run on SQLite and on PostgreSQL 17 under psycopg and pg8000. A test inserts every kind on the session dialect (M19).

### 8.2 Idempotency

- A rescan inserts no outcome or skip (`input_key`; the cursor).
- A batch is unique on `(context_key, batch_seq)`.
- Concurrent scans serialise on the ranking lock then the V3 lock (PostgreSQL), or on the database lock (SQLite).

### 8.3 Replay report (`scripts/run_ranking_replay.py`)

- **Usage.** `--write PATH [--allow-dirty]` and `--check PATH` (`--package PATH`). The script refuses paths under `lqs/` and boundary-private paths. There is no database mode: development databases are checked with the worker's `replay --check`.
- **Scenarios** (`ranking.synthetic`, seeded, numbers only; two model families; record times 30 s apart and a tick every 100 requests):
  1. `flapping` (2000 requests, near-equal models);
  2. `promotion` (a better challenger);
  3. `outage` (incumbent down, then back);
  4. `drift` (p0 to p1 in one cluster after 600 requests);
  5. `model_change` (deflation, a recommission fail, then a pass);
  6. `empty_eligible` (every model unavailable);
  7. `rating_only` (a pending outcome with and without feedback).
- **Record.** `{"report": "qcai-ranking-replay", "format_version": 1, "created_at", "commit", "evidence_class": "engineering measurement on synthetic streams, not E4 results (invariant 9; Table XVII MR-1..MR-3 not asserted)", "pins": {config_package, ranking_parameters}, "scenarios": [{"id", "seed", "events", "log_rows", "events_sha256", "final_state_sha256", "derived_sha256", "replays_equal", "requests", "drift_free_requests", "switches_drift_free", "switches_per_1000_drift_free", "false_alarms", "false_alarms_per_1000", "alarms", "detection_delay", "fallbacks", "promotions", "demotions"}], "inputs"}` (the LF sha256 of the ranking modules and the script).
- **`--check` exit codes:** 6: a pin mismatch; 7: a replay mismatch (plan L stop); 3: a scenario assertion failed (flapping at most 2 switches per 1000 drift-free requests; a promotion; an outage demotion and promotion; a drift alarm; a fallback; the cap lifted only by the pass; a rating that changes no trust or chart); 1: drift. 2 a usage error, 4 a dirty tree on `--write`.
- `hand_fixtures_v1.json` holds the two Beta fixtures, eqs. (5)-(9) worked for three outcomes, and the CUSUM constants (`A = ln 3`, `B = ln(17/19)`) with three steps.

---

## 9. Routes

No new route, and the authorization matrix is unchanged. `GET /v3/metrics` (reviewer only) adds `ranking`.

---

## 10. Start-up, `/ready`, logs and SLIs

### 10.1 Start-up

The order is `_check_v1_package`, `_check_gateway_package`, `_check_v3_package`, `_check_ehmf_package`, `_check_ranking_package`, then the pipeline and the manifest. The ranking check reads no database and no `docs/`. The schema guards follow the Phase 6/7 pattern.

### 10.2 `/ready`

```json
"ranking_mode": "off|shadow", "ranking_setting": "off|shadow", "phase9_exit_passed": false,
"ranking": {"version": "ranking-v1", "parameters_version": "ranking-params-v1", "parameters_sha256": "…", "provisional": true,
            "cluster_rule": "cluster-module-v1", "active_task_types": ["explanation", "quiz_item"],
            "live_routing": "refused", "decision": "D-28", "hold": "H11", "shadow_generation": false,
            "stop": {"stopped": null}, "available": true}
```

- `ranking` is null without a ranking block.
- `stop.stopped` comes from `ranking.replay.process_stop_state()`. It is cached per process for `ranking.replay.stop_refresh_s` and reads the last `ranking_events.kind` among `stop` and `clear_stop` (in a SAVEPOINT on PostgreSQL).
- It is null with no read when the mode is off, and null when the read fails.
- No count, rate, rating, incumbent, seq or model state appears.

### 10.3 Log events

| Event | Logger | Fields | Severity |
|---|---|---|---|
| `ranking.scan` | `qcai.ranking` | from_seq, to_seq, records, outcomes, skipped, batches, alarms, fallbacks, done | INFO |
| `ranking.batch` | `qcai.ranking` | context, batch_seq, trigger, models | INFO |
| `ranking.promote`, `ranking.demote` | `qcai.ranking` | context, from, to | WARNING |
| `ranking.alarm` / `ranking.sustained_alarm` | `qcai.ranking` | stream, statistic, observations, sustained | WARNING |
| `ranking.model_change` | `qcai.ranking` | adapter_id, from_version, to_version, reused_v3_event | WARNING |
| `ranking.fallback` | `qcai.ranking` | context | WARNING |
| `ranking.stop` | `qcai.ranking` / `qcai.worker` | reason, expected_sha256, actual_sha256 | ERROR |
| `ranking.unavailable` | `qcai.ranking` | reason | WARNING |
| `ranking.stop_unread` | `qcai.ranking` | — | WARNING |
| `ranking.shadow_generation`, `ranking.shadow_generation_failed` | `qcai.ranking` | model, explore; error class | INFO; WARNING |
| `ranking.status`, `ranking.replay_checked`, `ranking.commissioned`, `ranking.recommissioned`, `ranking.stop_cleared` | `qcai.worker` | SLIs; ok; clean/failed/generated/passed; cause | INFO |
| `ranking.scan_refused` | `qcai.worker` | reason (`ranking_off`, `stopped`, `uncommissioned`, `unknown_adapter`, `replays_differ`) | WARNING |

No line carries a learner identifier, a response id, question text or claim text.

### 10.4 SLIs

`ranking.metrics.slis` is available through the status worker and `/v3/metrics`. No alert, log-based metric, dashboard or schedule is created (DI-125).

---

## 11. Frontend

No change.

---

## 12. Records

### 12.1 First commit (E15; no behaviour change)

- **`docs/architecture/phase7-implementation-spec.md`.** The DI-104 row names the merge (PR #39 squash-merged on 2026-11-23 as `main` `512b8a6`, tree identical to `4e682db`), PR run 45306759765 and branch push run 45306711241 at `4e682db`, and the cited main run 45308186298 at `512b8a6`; it keeps "The exit is not passed." with R-18 (DI-105), DI-108, DI-109 and DI-89 as blockers, and ends `| Eng / PI / CO | Open |`. Section 17's exit bullet names the merge and the run. Section 18 gains the Merge row. `phase7_exit_passed` stays `false`.
- **`docs/testing/test-strategy.md`.** The Phase 7 "Exit gate." paragraph is edited the same way.
- **Test.** `test_phase7_docs_the_records_name_the_merge_and_the_cited_main_run` in `test_phase7_acceptance.py`.
- **BEP.** The register DI-104 row equals the spec's; `check_p7_merge_the_records_name_the_merge_and_the_cited_main_run` reads the spec's DI-104 row (the three facts, and no pre-merge phrase); every check pinning v6 reads `v6.json` explicitly.

### 12.2 Records rewritten at the last code commit

- `docs/evaluation/phase7/golden_run_v1.json` and `package_versions.json` (5.4).
- The `inputs` and package pins of `phase3/three_plan_replay_v1.json`, `phase4/v1_fixture_report_v1.json`, `phase5/v2_fixture_report_v1.json` and `phase6/v3_residual_report_v1.json`, each with its own script.
- Decisions, classes, finals, rates, counts, draws and the residual must not change. A changed count is a regression to investigate.
- The payload golden is never rewritten.

### 12.3 New records

- `docs/evaluation/phase9/*`.
- The BEP `phase09/` phase record and closure notes.
- The register rows.

---

## 13. Tests

### 13.1 `apps/api/tests/test_phase9_acceptance.py`

The fakes are in `ranking_fakes.py`: `ranking_settings()`, `Log` (a hand-built input log), `apply_all()`, `derived_of()`, `two_family_registry()`, `clone_member()`, `package_copy()`, `shadow_record()`, `commission_static()`, `scan()`, `events_of()`, `stored_state()`.

| Test | Asserts |
|---|---|
| `test_ac_9_1_an_event_without_a_completed_verdict_leaves_alpha_beta_and_qbar_unchanged` | Parametrised over every `SKIP_REASONS` value, each with a real record (edited where only an edit gives the reason). Alpha, beta, T, Q̄, n, the charts, streaks and incumbents are identical before and after; no derived event; `counts.skipped[reason]` rises by 1 and no other count changes. A control record with a completed verdict changes the state. |
| `test_ac_9_1_y_is_one_only_for_an_uncorrected_first_pass` | Clean gives y = 1. A regeneration, X1, X2, a V2 fail, `v1_8_misconception`, a hard fail, a V2 correction and a V1.3 `contradicted` give y = 0. X4 alone (a V1.5 mark) gives y = 1. AST check: `signals.py` reads no `ClaimPlan`, `kind` or `prompt_hash`. |
| `test_ac_9_2_a_learner_rating_changes_only_f_i` | Two logs differ only in a `feedback` on a pending outcome: Q̄ differs; alpha, beta, T, n, the charts, streaks, incumbent and select/promote/demote/alarm are equal. Late feedback counts only `late_feedback`. `f_from_rating(1..5)` gives `(r−1)/4`. |
| `test_ac_9_2_a_shadow_record_has_f_missing_and_no_feedback_is_appended_for_it` | A shadow record's outcome has F missing, and the scan appends no feedback for it even with an X3 item on it. |
| `test_ac_9_3_a_challenger_ahead_by_the_active_deadband_is_promoted_only_after_the_active_debounce` | Two then three context batches with d > δ: no promotion, then promotion (streak 3). An interruption resets the streak. δ exactly at the smallest gap blocks it, one quantum below lets it through. A batch while h is not in E resets the streak. A lower-rated challenger is not promoted. A package copy with δ 0.10 and n_d 2 is followed. |
| `test_ac_9_4_trust_below_the_tier_threshold_demotes_immediately` | A batch that takes T(g) below 0.90 at tier 2 emits `demote` in that batch, and the next `select` does not return g. A tier-1 B incumbent is demoted on the availability input that makes an A model available. |
| `test_ac_9_5_a_model_version_change_deflates_caps_at_c_and_raises_x5_until_the_golden_regression_passes` | A registry version bump in a package copy, then a scan: alpha and beta ×0.3 (exact Decimal); rating C; not in E. Exactly one `v3_events` model_change row with `generator:<adapter>`, plus the `v3_model_versions` row; an open X5 window. A following V3 scan over a clone record carrying the new version adds no second row. Time does not lift the cap; a failing recommission keeps it; a passing one lifts it. |
| `test_ac_9_5_the_ranking_reuses_v3_s_model_change_for_a_version_v3_already_saw` | When V3 saw the clone's new version first, the ranking's model change reuses V3's event: one `generator:` row. |
| `test_ac_9_5_the_x5_window_raises_the_next_delivery_s_draw_to_one_in_five` | After the change, the next learner delivery is drawn at 1/5 with X5 active. |
| `test_ac_9_6_an_empty_eligible_set_delivers_no_unverified_text_and_enqueues_a_v3_item` | Parametrised over down, stopped, kill_switch, disabled and all-D, with the static candidate also ineligible (rated D by its commissioning, or the kill switch). The scan writes fallback `select` rows with no model, no eligible model and the 3.4 keys only, and a V3 response item with `ranking_empty_eligible_set`. `hook.select` returns the fallback `Decision` (3.2 fields), and no ledger row is added. With V3 off the rows note `v3_off`. |
| `test_ac_9_7_a_cusum_alarm_raises_the_audit_to_the_x5_rate_holds_promotions_and_never_demotes` | The alarm fires with the active p0, p1 and h and `statistic > h`. h = 3.0 alarms earlier. No demotion by alarm. A challenger far ahead for at least n_d batches is not promoted while the hold is open, and is promoted in the batch after `hold_release`. |
| `test_ac_9_7_the_scan_records_the_alarm_through_phase_6_and_releases_the_hold_when_the_window_closes` | `record_cusum_alarm(db=...)` does not commit; committed, the `cusum_alarm` row has `source` `phase9-cusum` and `statistic >= h`; the next deliveries are drawn at 1/5 and `window_remaining` falls by their count. |
| `test_ac_9_7_with_v3_off_the_hold_stays_open` | A hold whose window never closes is not released. |
| `test_ac_9_8_one_event_log_replayed_twice_gives_byte_identical_final_states` | Two in-process replays and one subprocess replay give byte-identical state, derived events and checkpoints, equal to the stored ones. A stop row does not change the replayed state. A deleted derived event (in a copy), a tampered state, a wrong checkpoint and a broken chain are mismatches; `replay --check` appends the stop, the next scan is refused, and `clear-stop` resyncs. |
| `test_ac_9_8_the_worker_replay_check_exits_1_on_a_mismatch_and_0_when_current` | Exit 0, then 1 on a tampered state, then the scan exits 2. |
| `test_plan_j_hand_fixtures_beta_95_5_and_190_10` | 0.910 and 0.922; the committed fixtures (Beta bounds, the worked example, the CUSUM steps) equal the code. |
| `test_plan_j_flapping_near_equal_models_switch_no_more_than_the_hysteresis_allows` | At most 2 switches per 1000 drift-free requests, the first incumbent not counted (engineering, not MR-3). With δ = 0 and n_d = 1 it switches more. |
| `test_plan_j_outage_makes_a_model_ineligible_and_recovery_is_only_through_promotion` | Down: immediate demotion; back up: not re-instated until n_d batches ahead; every model down: the fallback. |
| `test_plan_h_no_llm_decides_a_rank` | AST import and call guard over `ranking/`. |
| `test_plan_h_the_generator_never_sits_on_its_own_panel` | The candidates' families resolve; an unknown generator raises `GeneratorFamilyUnknown`; a clone record's V2 block excludes fake-delta. |
| `test_plan_h_research_replay_only_in_the_research_environment` | `lqs/` and private paths are refused, the script has no database mode, and the streams, fixtures and report hold no text. |
| `test_plan_task_2_micro_batches_close_at_25_or_900_seconds_and_are_idempotent` | 24 outcomes plus a tick at +899 s: open. +900 s: closed (`time`). An outcome dated +900 s closes the earlier batch first. 25 outcomes: closed (`count`). A rescan adds nothing, and `input_key` is unique. |
| `test_plan_task_1_trust_state_is_per_model_cluster_task_type_and_tier` | A lesson-scoped record gives its module; multi-module, no evidence or another corpus gives `unscoped`; tier 1 gives `quiz_item`; a new context starts from the prior. |
| `test_plan_task_6_cost_and_latency_penalties_are_operator_policy` | λ = 0; cost reported; latency null; λ ≠ 0 refused while D-06 is open. |
| `test_plan_f_the_parameter_package_is_provisional_and_the_controller_reads_it` | Table XI values. A `config` event carries the block and changes behaviour mid-log; a block whose sha256 does not match is refused. |
| `test_plan_f_the_replay_report_is_current` | `--check` exits 0 within 60 s; edited copies exit 6 and 1. |
| `test_plan_f_a_replay_mismatch_exits_7` | A replay that differs from its log exits 7. |
| `test_plan_i_ready_reports_static_ranking_values_and_the_stop_and_no_count` | The 10.2 keys; stop null with no read when off; one read, then the cache. |
| `test_plan_i_metrics_report_micro_batch_latency_switch_rate_fallback_rate_and_cost` | The 4.13 keys and the evidence class. |
| `test_plan_l_rollback_to_static_assignment_keeps_the_event_log_alarms_and_x5_windows` | `RANKING=off` refuses the scan and keeps the rows and windows. |
| `test_plan_l_the_scan_refuses_while_the_static_generator_is_uncommissioned` | `RankingUncommissioned` and worker exit 2; no outcome is consumed and no V3 item is created; `commission` (the real regression: 40 generated, 0 failed) then the scan runs. |
| `test_plan_l_the_scan_takes_the_ranking_then_the_v3_lock` | The ranking lock, then `V3_SCAN_LOCK_KEY`, before the state is read, in the scan and in `append_inputs`. |
| `test_freeze_ranking_is_off_outside_development_and_on_is_refused_everywhere` | Defaults; `on` raises in development, staging and production; shadow generation is refused outside development. |
| `test_freeze_no_learner_path_changes_and_the_payload_golden_is_unchanged` | `capture_public_payloads.py --check` passes. A development record with `RANKING=shadow` equals one with `off`, apart from ids, times and code_sha. |
| `test_plan_g_shadow_generation_writes_only_undelivered_shadow_records` | With `RANKING_SHADOW_GENERATION=true` and a commissioned clone: one extra shadow record whose generator is the clone; `ledger_provenance` reports no problem; a raising pipeline is logged and swallowed; the hook's exploration decision equals the scan's later `select` for the same record. |
| `test_plan_e_the_phase_9_revision_is_additive_reversible_and_keeps_its_rows` | Single head; `SCHEMA_REVISION`; every kind is insertable; UPDATE and DELETE refused. |
| `test_plan_e_the_phase_9_downgrade_refuses_while_ranking_events_holds_rows_and_the_tables_refuse_truncate` | On the session's dialect. |
| `test_phase9_no_new_source_literal_starts_with_qcai_` | — |
| `test_phase9_docs_quote_the_plan_and_state_the_current_rules` | Plan P and L quoted; ADR-011 quotes plan M and H4a; the runbook names `allow_ranking_drop`, `commission` and `clear-stop`; PD and DI rows; renumbering; conflicts 1, 12 and 26. |
| `test_phase9_docs_the_test_strategy_maps_every_test_module_the_phase_added` | — |
| `test_phase9_spec_section_3_lists_the_code_s_fields` | 3.2 and 3.3 equal the dataclasses and the `empty_state()` keys. |
| `test_phase9_docs_the_spec_ends_in_one_review_history_table` | — |
| `test_phase7_docs_the_records_name_the_merge_and_the_cited_main_run` | E15. |

### 13.2 `apps/api/tests/test_ranking_units.py`

- `numeric`: log-gamma against `math.lgamma` to 1e-12; `reg_inc_beta` symmetry and endpoints; the quantile monotone and bounded; a float refused; the same bytes under a different ambient decimal context; negative zero written as `"0"`; 60 steps and a seeded draw.
- K by direct entropy; quality renormalisation; score; `rating` and `permits` (the B-at-tier-1 rule); the tie-break; first incumbent not a switch; the seeded Thompson draw repeats.
- CUSUM constants and steps, the reset, sustained.
- `tier_for`'s sources.
- Every `_parse_ranking` refusal, the flag policy, the owner decisions, the v7 queue reasons and the fake generate rule (v6 refuses it).
- `RANKING_SCHEMA_VERSION == RANKING_FIRST_MAJOR == PACKAGE.schema_version == LATEST_SCHEMA_VERSION`, `EHMF_SCHEMA_VERSION == 6`, no literal 7 in a schema rule, the clusters equal `MODULE_BLUEPRINTS`.
- `CloneGenerator` refusals; `record_model_change` returns its seq; `window_remaining`; the replay script's usage exits.

### 13.3 Existing tests that change (intent kept)

The full list, with each reason, is in the BEP phase record. In short: the tests that pinned the shipped package as v6 read v6 through `V6_PACKAGE_PATH` or the shipped one through `LATEST_SCHEMA_VERSION` and the package; the Alembic head and downgrade walks take the Phase 9 step; the Phase 7 docs tests that named v6 as the shipped package accept v7 since Phase 9. `test_erasure_retention.py` is unchanged and passes.

### 13.4 Mutation checks

Recorded in the BEP phase record, each with the test that failed: the skip rules, F excluded from trust, the strict `> delta`, the streak reset, the rating condition, the fast trip, the availability re-check, the deflation, the cap in the live rating, `recommission_pass` as the only release, the fallback branch and the V3 upsert, the alarm path, the hold check, no demotion on alarm, `window_remaining`, the model-change de-duplication, the bisection steps, `q()` quantisation, `localcontext(CTX)`, the config payload, the checkpoint and derived comparisons, stop rows skipped by the fold, `_refuse_ranking_on`, `input_key` uniqueness, the downgrade guard, the `/ready` mode gate, the lock order, the uncommissioned refusal, the hook's own `try` and the clone provenance rule.

---

## 14. CI changes (`.github/workflows/ci.yml`)

In the job `api-and-evaluation`, after the Phase 7 steps:
- Add `python scripts/config_package.py --check --path apps/api/app/config_package/v6.json` (DI-126).
- Add `python scripts/run_ranking_replay.py --check docs/evaluation/phase9/ranking_replay_v1.json` (exit 7 is the plan L stop).
- The golden-set step is unchanged.

The new tests run in both PostgreSQL 16 suites (psycopg and pg8000). The other jobs are unchanged.

---

## 15. Docs and evidence

- **This spec.**
- **`docs/adr/ADR-011-verified-trust-ranking.md`.** Context, Decision (2026-11-23), Consequences, and Residuals quoting plan M "[Risk R-23][Risk R-24][Risk R-20][Risk R-47]; residual: silent provider changes." and H4a "If ranking does not beat static assignment (H4a), static assignment stays".
- **Dated revisions:** ADR-008 (the fake clone rule, and the clone provenance rule); ADR-009 (CUSUM alarms and model changes from ranking; `window_remaining`; the queue reason; the gold-label schema pin; the de-duplication against `v3_model_versions`); ADR-010 (package v7, and the history entry 7.0.0).
- **`docs/architecture/ehmf-change-control.md`.** "## The ranking block (Phase 9)" and "## Renumbering the Phase 9 package".
- **`docs/evaluation/phase9/README.md`.**
- **`infra/cloudrun/deployment.md`.** `## Phase 9: verified-trust ranking (runbook)`: operations (commission the static generator first, then scan, status, recommission); rollback (`RANKING=off`, alarms retained; a digest rollback needs no downgrade); the stop (replay mismatch, `replay --check`, `clear-stop`); holds with V3 off; the guarded downgrade.
- **`infra/cloudrun/observability.md`.** `## Phase 9 SLIs: ranking (plan Phase 9 I)`.
- **`docs/testing/test-strategy.md`.** `## Phase 9 acceptance map (plan Phase 9 K)` and its "Exit gate." paragraph.
- **`docs/architecture/v3-trigger-registry.md`** and **`gateway-registry.md`.**
- **BEP.** `phase09/PHASE_RECORD.md` and `CLOSURE_EVIDENCE_NOTES.md`, the register rows, the STATUS row, and the `check_records.py` Phase 9 checks (reading `v7.json` explicitly).

### Renumbering the Phase 9 package (E16)

If Phase 8 reaches `main` first with v7 and a revision after `20261123_phase7_ehmf`, the lead engineer merges `main`, then:

1. Renames `v7.json` and its sidecar to `v8.json` (8.0.0, schema 8), with `supersedes` naming Phase 8's v7, carrying over what Phase 8 added; renames `schemas/v3-gold-label.v1.r7.schema.json` if Phase 8 pins another.
2. Sets `RANKING_SCHEMA_VERSION` and `RANKING_FIRST_MAJOR` to 8 (`LATEST_SCHEMA_VERSION` follows), and `DEFAULT_PACKAGE_PATH` to v8. `V7_PACKAGE_PATH` is Phase 8's, readable for one release.
3. Sets `down_revision` to Phase 8's head and updates the downgrade-walk tests.
4. Takes `main`'s `package_versions.json` and drops the branch's 7.0.0. Then runs `config_package.py --rehash` and `run_golden_set.py --write ... --base-ref origin/main`, rewrites the replay report and rewrites the 12.2 records.
5. Edits every text naming v7 or 7.0.0 for Phase 9.

Tests read the number from the constants and the package.

---

## 16. Provisional defaults and deferred items

### 16.1 Provisional defaults

Every value is recorded `provisional: true` in v7 and is ratified under DI-117. "Engineering parameters (no plan value; Claude's, ratified under DI-117)" names the values that are not the plan's.

| # | Decision | Plan text | Default applied | Where |
|---|---|---|---|---|
| PD-50 | Topic clusters and task types (OPEN, PI/PO) | B: "topic clusters [Evidence E-89], whose definition is an OPEN DECISION." | `cluster-module-v1` (the one module common to every evidence span's lessons, else `unscoped`). `quiz_item` at the assessment tier, else `explanation`; the other four types are reserved. Tier by `tier-source-v1`. Engineering parameters (no plan value; Claude's, ratified under DI-117): the derivation, the `unscoped` bucket, the task-type mapping and the tier source. | v7 `ranking.contexts`; `ranking/contexts.py` |
| PD-51 | Trust, quality and ratings (Table XI) | A: "Defaults: gamma 0.995; weights 0.35/0.30/0.15/0.20; eta 0.05; ratings A >= 0.95, B >= 0.90, C >= 0.80" | Eqs. (5)-(9) and the Sec. VII-B permissions. Missing signals are renormalised. K by vote entropy; H by EHMF weight density; F only for shown records; Q̄₀ = 1/2. Engineering parameters (no plan value; Claude's, ratified under DI-117): the H, V, K and F rules, the renormalisation, Q̄₀, the B-at-tier-1 test and V1.3 `no_checker` not counted against the generator (conflict 27). | v7 `ranking.trust`, `quality`, `ratings`, `tier_permissions` |
| PD-52 | Selection, exploration, micro-batches and promotion | A: "shadow 0.05; deadband 0.05 over 3 batches"; task 2: "Micro-batch per 25 verified responses or 15 min (Loop 3)" | Algorithm 1 per consumed record. Seeded inverse-CDF Thompson draws, never delivered. Batches of 25, or 900 s by record time or scan tick. Promotion after 3 consecutive eligible context batches with R(h) − R(g) > 0.05 and rating(h) ≥ rating(g). Immediate demotion. The first incumbent is not a switch. Engineering parameters (no plan value; Claude's, ratified under DI-117): the seed rule, the tie-breaks, the timer rule, the strict comparison, eligible-only streaks and the switch counting. | v7 `ranking.selection`, `promotion`, `micro_batch` |
| PD-53 | CUSUM and holds | A: "CUSUM p0 0.05, p1 0.15, h 4.0"; task 2: "CUSUM alarm -> X5, never demotion" | Per model and per (model, cluster), after every response. An alarm goes through `record_cusum_alarm`, holds promotions until the V3 window closes (open while V3 is off) and resets the chart. Sustained means a second alarm while held (DI-123). Engineering parameters (no plan value; Claude's, ratified under DI-117): the hold scope and release, the reset and the sustained rule. | v7 `ranking.cusum` |
| PD-54 | Re-commissioning and commissioning | A: "deflation 0.3; 50-item golden set"; task 4 | ×0.3 and cap C on a version change, until a recorded shadow regression over golden-set-v1's 40 queries passes (no failed first pass, at least 8 generated, gateway mode shadow). Commissioning prior 1 + clean, 1 + failed. Uncommissioned Beta(1,1). The scan refuses while a static candidate is uncommissioned. Engineering parameters (no plan value; Claude's, ratified under DI-117): the 40-query stand-in, the pass rule and minimum, the commissioning run, its clear V3 stop and the precondition. | v7 `ranking.recommission`, `models` |
| PD-55 | y_i, completed verdicts and skips | Task 1: "y_i = 1 only for an uncorrected first pass; no generator self-confidence" | R-c and R-d, the 4.3 skips; X3 to F only (shown records); X4, X5, X6 and V1.7 not attributed; V1.3 `no_checker` not a verdict (conflict 27). Engineering parameters (no plan value; Claude's, ratified under DI-117): the escalation set, the skip list, V1.7's exclusion and V1.3 `no_checker`'s. | `ranking/signals.py` |
| PD-56 | Cost and latency penalties | Task 6: "Cost and latency penalties are operator policy [Decision D-06]" | λ_u = λ_ℓ = 0; cost in units over the max; latency null. Engineering parameters (no plan value; Claude's, ratified under DI-117): the cost rule. | v7 `ranking.penalties` |
| PD-57 | Empty eligible set | Task 5: "Empty eligible set -> pre-verified content or abstention plus V3 enqueue." | Abstain (a decision with no text) and enqueue a V3 response item (`ranking_empty_eligible_set`); the pre-verified branch is DI-83's. Engineering parameters (no plan value; Claude's, ratified under DI-117): the queue reason and its gold-label schema pin (conflict 28). | v7 `ranking.fallback`, `v3.triggers.queue_reasons` |
| PD-58 | `RANKING` and `RANKING_SHADOW_GENERATION` | G: "New tables; shadow by default; live routing only by flag after [Decision D-28]." | Development `shadow`, elsewhere `off`; `on` refused everywhere; shadow generation false and development only. Engineering parameters (no plan value; Claude's, ratified under DI-117): the values, the defaults and the switch. | `config.py`; v7 `flag_policy.ranking` |
| PD-59 | Event log, replay, arithmetic and the stop | F: "Controller, parameter package v1, hand fixtures, replay report."; L: "Stop: a replay mismatch." | Append-only hash-chained `ranking_events` with the parameters in the log. Decimal in a fixed local context. A 60-step bisection. Replay byte comparison, including checkpoints. Stop until `clear-stop`. The synthetic report checked in CI within 60 s. Engineering parameters (no plan value; Claude's, ratified under DI-117): the arithmetic, the schemas, the scenarios, the exit codes and the stop cache. | `ranking/replay.py`, `scripts/run_ranking_replay.py` |

### 16.2 Deferred items

| # | Item | Who | State |
|---|---|---|---|
| DI-115 | The Phase 9 exit (plan P: "AC-9-1 to AC-9-8 green; staging shadow run; live routing OFF pending E4 [Decision D-28]."). Needs AC-9-1..AC-9-8 green in a cited CI run on `main`; `phase9_exit_passed` stays false. Blocked by: DI-120, DI-118, DI-117, and the Phase 5-7 exits (DI-74, DI-89, DI-104). | Eng / PO / PI | Open |
| DI-116 | The topic-cluster definition and task-type set (PD-50). | PI / PO | Open |
| DI-117 | Ratify PD-50..PD-59 and re-estimate Table XI on E4 data. Blocked by: D-06 OPEN and Phase 10 E4. | PI / PO | Open |
| DI-118 | Live routing (D-28; H11 "E4 report; hysteresis") with MR-1..MR-3. Blocked by: the E4 report (Phase 10, D-14, D-08) and the PO decision. | PO | Deferred |
| DI-119 | The paper's 50-item golden set and 30-item pilot (80-item commissioning). Blocked by: PI content (D-14). | PI | Open |
| DI-120 | Staging shadow run. Blocked by: no non-fake generate member (D-07, D-12, Q-09, Q-15) and D-05. | PfO / PO | Open |
| DI-121 | A learner 1-5 rating for F_i, F on shown records, and the privacy disclosure (with DI-97 and DI-59). Blocked by: D-05, D-27. | PO | Deferred |
| DI-122 | Latency per response, a service target, cost in USD (D-06; A-15). | PO / PfO | Deferred |
| DI-123 | The sustained-CUSUM stop-the-line on delivered content (13.6), with DI-96. Blocked by: D-05 and the delivered path (DI-59, DI-85). | PO, then Eng | Deferred |
| DI-124 | The research replay on E4 logs in the research plane (D-14, D-15; Phase 10). | PI / MLE | Deferred |
| DI-125 | Log-based metrics, alerts and a scheduled ranking scan. Blocked by: a cloud write under D-05. | PfO | Defined, not created |
| DI-126 | Remove package v6 after one release, with its CI step. | Eng | Deferred |
| DI-127 | The pre-verified content branch of the fallback, with DI-83. | CO / PI, then Eng | Deferred |
| DI-128 | S_i needs the V1.3 entailment checker (D-21). | PO, then Eng | Deferred |

### 16.3 Rows of other phases that Phase 9 advances

The registers never edit other phases' rows, except the sanctioned E15 edit of DI-104. Phase 9 advances DI-96 (the statistic and alarm are produced; the stop-the-line is DI-123) and DI-83 (DI-127).

---

## 17. Verification, work order and exit

**Work order.**
1. E15 as a separate first commit.
2. The measurements M1-M21.
3. The build: numeric, vocabulary and types; signals and the controller with AC tests on pure logs; the v7 loader; the revision; the scan, replay and worker (with the V3 helpers); shadow generation, the hook and the provenance rule; `/ready`, metrics and docs; then the records (12.2, 8.3).
4. Review rounds, each in its own commits.

**Commands.**
- The full API suite on SQLite.
- Every CI validator, `config_package.py --check --path` for v1-v6, `run_ranking_replay.py --check`, `run_golden_set.py --check ... --base-ref origin/main`, `scan_boundary.py` (with its report in the scratchpad), BEP `check_records.py`, and `git status --short`.
- A scratch PostgreSQL 17 cluster under psycopg and pg8000, stopped at the end.

**Exit (plan P).**
- AC-9-1..AC-9-8 are done in code once green; the cited run must be on `main` (DI-115).
- No staging shadow run exists (DI-120), and live routing is refused (D-28 OPEN).
- `phase9_exit_passed` stays `false`. The exit is not passed.

---

## 18. Review history

The rows below record what each round fixed, in order. They may describe behaviour that a later round superseded; sections 0-17 are authoritative.

| Round | Commit | Findings fixed (one line each, with their tests) |
|---|---|---|
| Spec (pre-code) | — (sections 0-17) | The design: the AC-9-1..AC-9-8 tests in 13.1 |
| Spec review 1 (pre-code) | — | F only on shown records (AC-9-2 test); parameters and candidates carried in the log (`test_plan_f_the_parameter_package_is_provisional_and_the_controller_reads_it`); checkpoints verified at their positions and stop rows not folded (AC-9-8); `kind` String(24) (revision test); model-change de-duplication through `v3_model_versions` (AC-9-5); ranking lock then V3 lock (lock-order test); `window_remaining` with holds open while V3 is off (AC-9-7); the uncommissioned refusal (scan-refusal test); the clone provenance rule, the hook's ledger-seq keying and the hook's own `try` (`test_plan_g_shadow_generation_writes_only_undelivered_shadow_records`); conflict 7 extended for E7's test wording; Decimal local context, endpoints, Lentz tolerance and runtime budget (`test_plan_f_the_replay_report_is_current`); AC-9-6 cases with the static candidate ineligible; record-time batch closing; eligible-only streaks; the first incumbent not a switch; the availability re-check; the 3.3 state fields; K computed directly; no replay database mode; regression in gateway shadow; `stop_refresh_s` in the package; v7 queue reasons in the parsed params; the erasure pattern stated; M1 deselected count; no edits to the test fakes |
| Build | the commits after `060ffd3` | Code-forced refinements: V1.3 `no_checker` is not a generator failure (conflict 27; `test_ac_9_1_y_is_one_only_for_an_uncorrected_first_pass`); the pinned V3 gold-label schema split by package schema (conflict 28; `test_package_v6_refuses_a_fake_generate_rule`, the v5/v6 `config_package.py --check`); the regression's clear V3 stop (M20; `test_plan_l_the_scan_refuses_while_the_static_generator_is_uncommissioned`); the rating computed live from T and the cap (3.3; `test_ac_9_5_a_model_version_change_deflates_caps_at_c_and_raises_x5_until_the_golden_regression_passes`) |
