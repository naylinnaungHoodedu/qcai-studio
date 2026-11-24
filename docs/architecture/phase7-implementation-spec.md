# QC+AI Studio — Phase 7 Implementation Spec
## EHMF operationalization (plan L1500-1555)

- **Repository:** `D:\QC_AI_Studio\Codex_Webapp_QC_AI_Studio`.
- **Branch:** `phase7/ehmf-operationalization`, cut from `origin/main` `31343c8` (Phase 6 merged, PR #38; tree identical to `1c49b74`).
- **Plan:** `D:\QC_AI_Studio\QC_AI_Studio_Ultimate_Software_Upgrade_Plan.txt`. Plan locations used here:
  - The Phase 7 block: L1500-1555.
  - 1.4: L57-75. F-4 and F-7: L474-506. The R-18 closure row: L556-558 and L590.
  - 6.2 Stage 4/11: L662-670. 6.3 EHMF: L678-726. 7.7: L940-958. 7.8 invariants: L960-982.
  - The Phase 4 V1 table: L1303-1313. Phase 5 5.8: L1386. Phase 6 X2: L1455.
  - Phase 11 task 3 and AC-11-3: L1759 and L1783. 9.4 holds: L1904-1926.
  - 12.3-12.5: L2212-2262. 13.6: L2365-2384. 13.7: L2386-2405. 13.9: L2425-2436.
  - Risks: L2470-2530. Decisions: L2538-2562. 15: L2593-2632. 18.1: L2922-2950. 18.3/18.4: L2978-3026. Evidence E-79..E-88: L3139-3148.
- **Fixed decisions:** E1-E16 (`BEP-2-12/00_meta/workflows/p7/p7_design.txt`). Every one is implemented. Section 1 lists each refinement and conflict.

Sections 0-17 describe the behaviour the code has. They are authoritative and kept current in place (P2-12-D-03). Section 18 holds one history-table row per review round. This file is LF in every checkout (`.gitattributes`).

---

## 0. Ground rules, measured facts, readings

### 0.1 Binding constraints (Phase 6 0.1, unchanged, plus Phase 7's)

**Git and files**
- Stay on the branch: no branch switch, no `git stash`, no push, no history rewrite, no git-config change.
- Commit messages end with a blank line, then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Temporary files go only to the scratchpad. Nothing is written to the repository root.

**Forbidden reads and calls**
- Never open `infra/cloudrun/*.env.yaml`, `apps/frontend/.env.local`, `apps/api/.env.example` or any `.env*` file.
- No cloud, gcloud, gh, provider or LLM call, and no deploy. No test touches the network (`apps/api/tests/network_guard.py`).
- No `pip install` from the network.

**Freeze (D-05, P1-D-18; E11)**
- Outside development, `EHMF` is `off`, and every learner-facing path behaves exactly as in Phase 6.
- In development under the default (`shadow`), the learner-facing path is also unchanged: no retrieval change and no change to any learner-visible output. Only shadow records gain the `ehmf` block.
- The public-payload golden passes unchanged and is never re-written: `scripts/capture_public_payloads.py --check apps/api/tests/data/phase4_public_payloads_v1.json`.
- No frontend file changes. No learner-facing control, banner or text changes anywhere, including the learner-reachable ledger route (9).
- The conflict disclosure (template v2) exists only in development shadow records.
- `/ready` is an operations route. It gains static EHMF fields and, only when EHMF's effective mode is not `off`, one stop-state read (10.2), as Phase 5 added the gateway state.

**Content and licensing (E-95, D-16, D-31; E4, E10)**
- Engineering edits no DOCX and adds no library entry. Library v1 ships with zero production entries (Q-14, A-18).
- No source metadata is inferred. Every corpus item's `source_year`, `peer_reviewed` and `source_role` stays absent (unresolved) until the Content Owner supplies them.
- The fidelity register and report hold only numbers, short labels and phrases the plan quotes, never other DOCX text.
- A library entry applied later from a V3 proposal holds only the Content Owner's paraphrase, its span ids and the gold record hash; never a gold label, a rationale or reviewer data (plan L627-628).
- No learner identifier, email, secret or reviewer name goes into fixtures, logs, docs or the repo. No new source literal starts with `qcai_`.

**Parallel Phase 8 track (E16)**
- PD-200..PD-299 and DI-300..DI-499 are never used.
- The learner-record service, erasure, retention, consent, identity, the learner-record routes and the learner-record functions of `api.ts` are not edited.
- If Phase 8 reaches `main` first and takes package v6 or the next Alembic head, the lead engineer merges `main` and renumbers before the PR, by the procedure in `docs/architecture/ehmf-change-control.md` ("Renumbering the Phase 7 package"): the package file, its `package_version`, `schema_version` and `supersedes`, the two constants `config_package.EHMF_SCHEMA_VERSION` and `vocabulary.EHMF_FIRST_MAJOR` (equal, `test_the_phase_7_package_number_is_read_from_one_constant_per_side`), `ehmf.config_version.first_package`, the revision's `down_revision`, the records and every text naming v6. Tests read the shipped version from the package (`ehmf_fakes.SHIPPED_VERSION`, `NEXT_PATCH`, `NEXT_MINOR`). Nothing in Phase 7 waits for Phase 8.

**Tests**
- No existing test or guard is weakened, and no new skip or xfail is added. A changed test keeps its intent (13.3).
- Each fix is mutation-checked: revert it, see the test fail, restore it byte for byte.
- AC tests are in `apps/api/tests/test_phase7_acceptance.py`; unit tests in `apps/api/tests/test_ehmf_units.py` (13.2). No test file is created per review round.
- No test, script or mutation run writes into the checkout (Phase 6's session fixture `_the_checkout_stays_unchanged`). AC-7-6 edits a package copy in `tmp_path`.

### 0.2 Measured facts (on the branch at `31343c8`, 2026-11-23)

- **M1. Baseline.** SQLite: 1859 passed, 2 skipped, 1 deselected, 3 xfailed (strict). PostgreSQL 17: 1861 passed, 1 deselected, 3 xfailed, under psycopg and pg8000. Frontend: lint, typecheck and 165 integration tests. CI main run 45180967316 green on every job.
- **M2. Where the EHMF vocabulary lived.** `tutor_pipeline/contracts.py` held `EhmfType` and `EHMF_BY_CHECK` (the plan's Phase 4 table L1303-1313); `config_package.py` repeated the table as `V1_EHMF`; `v2_panel/rules.py` and `v3/rules.py` each defined `EHMF_TYPES`; `gateway/contracts.py` imported it from `v2_panel.rules`. `v1_checks/results.py` (`make_result`) stamps the check's whole tuple on every result, so a result's `ehmf_types` says which check ran, not which failure mode was found. No B1 or B2 subtype existed.
- **M3. The plan's "lexical gate with hard-coded constants" is stale.** Plan A cites `[Repo: apps/api/app/services/claim_gate.py:11-17, _STOPWORDS, commit 1098a6ae]`; at the base, `claim_gate.py` is the V1.4 subset checker, and `_STOPWORDS`, `ClaimGate` and `evidence_digest` exist nowhere in `apps/api`. The lexical constants that remain are already versioned: the V1 rule vocabulary (`v1.rules_hash`), `retrieval_p1.QUERY_STOPWORDS` (named by `gates.p1-floor.stopwords`), the package's `retrieval.stopwords` and `v1.lexicon`.
- **M4. The misconception library** was inline in v5 at `v1.v1_8.library` (version `v0`, status "empty: Q-14 seed list unavailable (A-18)", no entries); no edit path and no editor rule existed. The Phase 4 fixture file carries its own `fixture_library` (`MC-FIXTURE-1..3`).
- **M5. Conflicts.** `v1_checks/v1_7_conflicts.py` (rule `conflict-version-polarity-v1`) detects `version_of_same_asset`, `number_disagreement` and `negation_disagreement`; its results are response-level and its claims are in `DisclosureBlock.conflicts[i].claim_ids`. v5 `v1.v1_7.on_conflict` is `disclose`. The corpus manifest has no publication year, peer-review flag or primary/secondary field; `corpus_version` hashes only `(item_id, item_version, sha256)` plus the span scheme.
- **M6. Correction and X2.** `MAX_CORRECTION_CYCLES = 2` bounded `V1Track._run_v2` and `_final_rendering`. The contracts bound the loop too (`V2Correction.cycle le=2`, `V2Block.cycles le=2`). `V3IntentV2` sets escalation X2 exactly when `v2_correction_exhausted` is a reason; Phase 6's `x2_claims` fired only for objecting family types A or B. A presentation-only claim is re-rendered from the same run state, so its claim and span sets could not change; nothing asserted it.
- **M7. Weights.** v5 `v3.priority.severity` held the plan's 6.3 weights, provisional (PD-34); the loader bound A-E to `v3/rules.py` `PLAN_SEVERITY`. They were used for V3 priority only; a disclosed V1.7 conflict weighs nothing.
- **M8. Ledger versions.** Every record stamps `config_package_version` and `config_package_sha256`; no `config_version` existed. `ENTRY_SCHEMAS` held v1-v3. Export, restore and verification re-validate every entry with the current `ENTRY_SCHEMAS` model, so a record rule that reads a code constant changes the validity of stored rows when the constant changes.
- **M9. `/ready`** reported the package version and sha256 but no `config_version`; the Phase 3 and Phase 6 tests assert that its only statement is the gateway-stop read.
- **M10. Retrieval.** `CourseStore` builds one `LexicalIndex` for the learner path and the shadow pipeline; `index_version` hashes `{corpus_version, gate, retrieval_sha256, entries}`. bm25f-v1 sorts by `(-score, span_id)`, p1-floor stably by score; both truncate to `top_k`. No penalty hook existed.
- **M11. The DOCX (R-18).** `git ls-files '*.docx'` lists 12 files (8 at the root, 4 under `update_data/`), stored in git (not LFS); `.dockerignore` excludes `*.docx`. `python-docx` is in `apps/api/requirements.txt`. In `Quantum Computing AI Research Synthesis 2026.docx`, table 4 (0-based) row 0 is the header (`Model Variant | Internal Sens. | Internal FP Rate | Internal Dice | External Sens. | External FP Rate | External Dice`) and row 2 the QUEN row, so the F-7 transposition is at row 2, columns 4 and 5. Paragraph 68 is the only paragraph containing "perfectly aligned", and it contains "GEA".
- **M12. Change control.** `run_v1_fixtures.py --check` already failed on a package edit. No golden set, Stage 11 gate or golden-run record existed.
- **M13. The Phase 4 adversarial fixture set** has 66 cases; `conflict_negation` and `conflict_number` are check-level cases (a synthetic twin span outside the store), `conflict_version` cases are pipeline-level (two real items of a fixture version family).
- **M14. V1.1 and V1.2 scope.** V1.1 judges the candidate whole: the first unresolvable span id of any claim fails the candidate; the runner regenerates (at most twice) or returns `V1HardFail`, which never reaches V2. V1.2 runs only after V1.1 passed, so its own `unresolvable` drop is unreachable. V1.2 drops a proposed claim with a claim-scoped `hard_fail`; the proposal is never locked, and its V1.2 result carries the proposal's `claim_id_for(text, span_ids)`.
- **M15. X5 windows.** `scan.open_windows` read `v3_events` rows only.
- **M16. Tests and texts that pinned the shipped package v5** (13.3), and the records carrying the package and `inputs` (12.2).
- **M17. Registers.** The last PD was PD-39 and the last DI DI-103. Phase 7 uses PD-40..PD-49 and DI-104..DI-114.
- **M18. Alembic.** The head was `20261122_phase6_v3_audit`.
- **M19. Results across attempts.** `V1Track._decide` keeps one results list across generation attempts, so a V1.1 hard fail at attempt 1 followed by a passing regeneration leaves the attempt-1 result in `record.checks`. A claim verdict's `v1` holds its own results and every response-level result.
- **M20. The package's entry-schema check** expected every `ENTRY_SCHEMAS` member for schema 4 and later, which would have failed v4 and v5 once v4 records exist.
- **M21. Detector faults.** `check_v1_3` returns the response-level abstain `checker_unavailable` on any checker exception; the V2 track drops a failing member down to ZERO (withhold); `check_v1_7` and `check_v1_8` caught nothing.
- **M22. Development records.** In development the default `MODEL_GATEWAY=shadow` writes a `ledger-entry-v3` beside V1.

### 0.3 Readings

- **R-a. Delivered.** Phase 7 has no delivered two-pass path (DI-59, DI-85). "Not delivered" (AC-7-1) means: the claim's verdict `final` is not `deliver` and it is not among `presentation.rendered_claim_ids`; or the claim never locked (a V1.2 drop); or its candidate was discarded (a V1.1 candidate fail).
- **R-b. Finding.** One failure-mode observation that fails or flags a claim or a response, with one type in `A, B1, B2, C, D, E`. The per-check `ehmf_types` tuple of `CheckResult` stays as it is, for ledger compatibility.
- **R-c. Detector.** A component whose verdict produces a finding: the V1.1 resolver, the V1.2 binder, the V1.3 checker, the V1.4 subset checker, V1.5's sufficiency check, V1.6, V1.7, the V1.8 library, V1.9, and the V2 panel and its alignment item. "Detector down" means the component raised, the library is unavailable, or V1.3 returned `checker_unavailable`. A panel member that drops out is not a detector fault (Phase 5's degraded path).
- **R-d. Typed record.** A `ledger-entry-v4` record, which carries the `ehmf` block. Only development writes typed records.
- **R-e. config_version.** A record's `config_version` is its `versions.config_package_version` when that version's major is at least `EHMF_FIRST_MAJOR` (6), else `"pre-phase-7"` (plan G). Applied at read time and never written back.
- **R-f. Modes.**

| `EHMF` effective | What runs | Learner effect |
|---|---|---|
| `off` (default outside development; also whenever the V2 mode is `off`) | Phase 6 exactly: no v4 record, no detector guard, no set check, no stop detection, no penalty, no stop read on `/ready`. The correction guard bounds the loop exactly where Phase 5's constant did. | none |
| `shadow` (default in development) | Typing, precedence (recorded only), disclosure v2 and the X2 list in v4 shadow records. V1/V2 finals stay Phase 6's, except that a set-changing re-render abstains the shadow response (`ehmf_set_changed`; unreachable under the shipped renderer). Stop detection runs with the V3 scan. No penalty. | none |
| `on` (development only before the Phase 7 exit) | `shadow` plus the detector guard (detector down → abstain, `ehmf_detector_down`) and the span penalty (empty lists ship, so retrieval is byte-identical) | none outside development |

Outside development no typed record is written, so the rising-A/B stop (4.10) cannot fire in production until EHMF is enabled there (DI-111).

---

## 1. Conflicts between plan text and the fixed decisions, with resolutions

Each resolution is a refinement. None reverses a fixed decision.

1. **Plan E "library tables" against E4 (a versioned file).** Plan text: "Correction, conflict and package-loader modules; library tables." Task 6 reads "One hashed configuration package per ledger record [Risk R-46]". A table would be mutable state outside the package hash every record stamps; the library is read once at load. **Resolution:** a hashed file beside the package (`config_package/misconceptions/v1.json`) whose sha256 the package pins. No table.
2. **Plan A's "VERIFIED FACT: the gate is lexical overlap [Evidence E-27] with hard-coded constants [Repo: apps/api/app/services/claim_gate.py:11-17, _STOPWORDS, commit 1098a6ae]"** is stale (M3). **Resolution:** the remaining constants are versioned; Phase 7 moves the EHMF, correction, X2 and weight constants behind package v6 (5). ADR-010 states M3.
3. **AC-7-5 "the engine abstains and emits X2" against Phase 6's trigger "X2 Type A/B unresolved after two cycles" (L1455).** Plan L1520: "Correction: at most two cycles, then abstain and raise X2 [Evidence E-82]." **Resolution:** every exhausted claim, whatever its type, abstains with `v3.escalation "X2"` (Phase 5 already did, M6) and the v4 record lists it in `ehmf.x2_emitted`. The V3 registry moves to `x-triggers-v2`: X2 (`v2-exhausted-any-type-v2`) fires on every recorded X2 escalation; priority stays severity-weighted. It queues and counts more items, never fewer, and holds and releases nothing new (PD-44). Package v5 keeps `x-triggers-v1`; `triggers.x2_claims(entry, *, registry_version)` applies the registry the package names.
4. **Plan P "package v1 hash in the ledger".** **Resolution:** read as the hash of the Phase 7 package (v6, the first with an `ehmf` block) in every record written from the Phase 7 release; `config_version` names it. Nothing is deployed, so no production record carries it yet (DI-104).
5. **Plan P "R-18 closure evidence in Section 5: corrected DOCX values and the source-fidelity CI job over the 12 DOCX passing" against D-16, D-31 and E10.** 18.3 D-16 reads "Correct content at source (CO) | (a) correct; (b) withdraw". **Resolution:** engineering edits no DOCX. CI runs `check_source_fidelity.py --check` (3 mismatches); `--require-zero` (AC-11-3: "Zero DOCX mismatches; QUEN row reads Sensitivity 0.828, FP 1.143.") joins CI only after the correction (DI-105). R-18 stays open.
6. **E9 "a 'revert required' state reported on /ready" against Phase 3's static `/ready`.** **Resolution:** `/ready` reads one cached stop row (`ehmf.stop.process_stop_state()`, per process, refreshed every 60 s), only when EHMF's effective mode is not `off`: `SELECT ehmf_stops.to_config_version, ehmf_stops.from_config_version FROM ehmf_stops ORDER BY ehmf_stops.seq DESC LIMIT 1`. It reports `ehmf.stop.revert_required` (boolean, or null when unreadable or off) and no count, rate, window or seq.
7. **Plan L "a rising A/B rate after a change reverts it" against D-05.** **Resolution:** the stop is computed state: the audit draw rises to 1/5 over a window, and "revert required" is reported. The revert is the operator's ("Reload the prior package", runbook). The automatic revert is not implemented: it would be a production configuration write, which D-05 forbids (DI-114).
8. **AC-7-1 "not delivered" with no delivered path.** **Resolution:** R-a.
9. **AC-7-2 "B1 is final and no vote overrides it" with candidate-level V1.1 (M14).** **Resolution:** a B1 finding at V1.1 fails the whole candidate, never repaired; a regeneration is a new candidate judged from the start. V1.2's own `unresolvable` stays in the routing table so the mapping is total. Neither reaches V2. The v4 record rule refuses a delivered verdict or any V2 verdict when the accepted attempt's V1.1 result is B1, and refuses a B1-typed claim that is delivered or carries a V2 verdict. A gold label edits no ledger row and releases nothing (Phase 6 R-g, `test_ac_6_4_an_adjudication_appends_one_gold_row_and_changes_no_ledger_row`).
10. **AC-7-3 "contradicting spans".** The Phase 4 `conflict_negation` cases are check-level (a synthetic twin span no store holds, M13), so no pipeline record can carry them. **Resolution:** the AC-7-3 fixture is a Phase 4 `conflict_version` pipeline case (two cited spans of two items of one version family) realised through the pipeline with EHMF on. "D weighs 0" means `ehmf.conflicts[i].d_weight == "0"` (the record's `D_disclosed`) and V3 severity 0 for the disclosed conflict (`triggers.claim_types` excludes it).
11. **Plan I "Per-type rate, Type D disclosure share, correction cycles, config_version on /ready".** **Resolution:** `config_version` is a `/ready` field; rates and shares are on reviewer-only `GET /v3/metrics`, in the worker's `ehmf status` line and in log events.
12. **E2's V1.4 split.** **Resolution:** `unmapped_factual_sentence` is D; every other subset code, `render_failed` and the V1.9 envelope are E. V1.4 results are response findings.
13. **Typing without a V2 track.** **Resolution:** EHMF's effective mode is `off` whenever the V2 mode is `off`; ledger-entry-v2 records are untyped.
14. **Plan J "detector down -> claim withheld" against abstention.** **Resolution:** under `on`, a detector that raises abstains the whole response with `ehmf_detector_down` (stricter). V1.3's own unavailability keeps `checker_unavailable` and is recorded as `detector_down: ("V1.3",)`. Under `shadow` and `off` a raising detector fails the shadow run as in Phase 6.
15. **Plan G "earlier ledger rows carry config_version 'pre-phase-7'" against the append-only ledger.** **Resolution:** a read-time mapping (R-e) in `export_ledger`, `ledger_provenance` and the SLIs. The learner-reachable ledger route is unchanged.
16. **Plan task 5 "penalty is operator policy [Decision D-06]".** **Resolution:** factor 1 in every non-development registry; development 1/2 (PD-45), applied only under `EHMF=on`; every shipped span list is empty (DI-113).
17. **Plan H "Library holds public-corpus paraphrases" against Q-14 unavailable (A-18).** **Resolution:** library v1 holds zero entries; library-rule tests use entries built in the test; the golden run's misconception items use the Phase 4 file's own `fixture_library`.
18. **"Stage 11 golden-set gate" (task 6) against 6.2's row "golden set -> 10" and 13.9.** **Resolution:** `golden-set-v1` is the production change-control set (public corpus or synthetic, disjoint from ULQS, R-25) with 100% resolution of delivered citations. The 50-item research golden set stays Phase 10's (D-14).
19. **Plan J "leakage".** **Resolution:** keyed-answer leakage (V1.6, Type E) plus the alignment item's leakage flag (Type E).
20. **E6's "reviewer approval" with one maintainer (A-9).** **Resolution:** the PR review is the approval; with one maintainer the approver is the owner (P1-D-18); "the X6 auditor MUST NOT audit their own change" stays DI-99.
21. **Plan O "OPEN DECISION: EHMF weight values (expert elicitation) owned by the Principal Investigator [Evidence E-88]".** **Resolution:** the plan's 6.3 values are applied, provisional (PD-41); owner decision `EHMF-WEIGHTS` records it (DI-108). Each v4 record carries the weights it used.
22. **"Constants move into the package" against record contracts that bound cycles (M6).** **Resolution:** the runtime reads `package.ehmf.max_cycles` (`v2.correction.max_cycles`); the code constants stay as the loader's plan bounds and the contracts' limits. A guard test asserts no module outside `ehmf/vocabulary.py` defines the A-E value tuple.
23. **AC-7-4 "claim and span sets are unchanged" against Phase 5's record rules (M6).** **Resolution:** a re-render whose claim or span set differs abstains the whole response with `ehmf_set_changed` (valid in a v4 record only). It runs only when EHMF is not `off`; under the shipped renderer it is unreachable, and a test seam proves it.
24. **Task 3 / E3 "D precedence plus disclosure" against the freeze and absent metadata.** **Resolution:** precedence is computed and recorded; both spans are always disclosed; precedence never changes a final in any mode (DI-111).
25. **The golden-set "delivered" of a Phase 4 item.** The Phase 4 runner's `delivered` rule is per class (for a conflict: delivered *undisclosed*). **Resolution:** a Phase 4 golden item's `delivered` is that case's own rule; a conflict item expects `delivered false` and `disclosed true` (the response delivers with the disclosure).
26. **"Alignment leakage: E, re-render only" with leakage on every render.** Two re-renders exhaust the cycles, so the response abstains with `v2_alignment_failed` and the shown claims escalate X2 (Phase 5). **Resolution:** the golden alignment-leakage item expects E and X2; the single-cycle re-render is AC-7-4's test (leakage in cycle 1 only).
27. **V3 proposals "claim_text (shown iff public and quotable)".** A gold row holds claim and span ids and the text's sha256, never the text. **Resolution:** a proposal's `claim_text` is null; the Content Owner reads the claim through its spans.
28. **Plan J "Fixtures per type (negation, invented citation, analogy, conflict, leakage)".** "Analogy" names Type C: task 1 reads "C bind step or label analogy", and 6.3's row reads "C library (V1.8)", so a Type C finding is a V1.8 misconception-library match. **Resolution:** the plan's analogy fixture is the golden set's `misconception` class (3 Phase 4 V1.8 cases, with that file's own fixture library), typed C; `test_plan_j_fixtures_per_type_are_typed_as_the_routing_table_says` names it so. The "label analogy" rendering is the routing table's Type C mitigation, deferred with the other mitigations (DI-111).

---

## 2. Architecture

```
retrieval (LexicalIndex)  ── span penalty (ranking only; EHMF=on only; factor 1 outside development; empty lists) ──► EvidenceBundle
V1Track (V1.1..V1.9) ─► V2Track (MODEL_GATEWAY shadow|on) ─► correction loop (CorrectionGuard is the only bound: ≤ 2 cycles)
      │ EHMF shadow|on                                     │ Type E re-render: claim_set and span_set must not change (refused → response abstains, ehmf_set_changed)
      ▼                                                    ▼
ehmf.classify ── per finding: A | B1 | B2 | C | D | E (routing ehmf-routing-v1)
ehmf.conflicts.precedence ── winner or none (recorded only); disclose both; template conflict-disclosure-v2; D weight 0 when disclosed
ehmf.record.build_record_v4 ─► VerificationRecordV4 ─► LedgerEntryV4 (ledger-entry-v4, additive; shadow only)
V3 scan (Phase 6) ── x-triggers-v2 (X2 on every exhausted claim) ── ehmf.stop.detect (rising A/B after a config_version change)
      └─ ehmf_stops row ─► open_windows ─► draw at 1/5 over the next 1500 learner deliveries; /ready ehmf.stop.revert_required
change control: package edit ─► scripts/run_golden_set.py --write ─► golden_run_v1.json (pins package, library, routing, golden set) ─► CI --check
source fidelity: scripts/check_source_fidelity.py ── register (plan F-7 facts) ─► report (3 mismatches; CI --check; --require-zero after CO correction)
```

| AC | Mechanism | Primary tests (13.1) |
|---|---|---|
| AC-7-1 | `ehmf.classify` (V1.2 `negation_mismatch`, V1.3/V2 contradicted → A); V1.2 drop | `test_ac_7_1_a_negated_claim_fixture_is_tagged_type_a_and_not_delivered` |
| AC-7-2 | V1.1 discards the candidate; V1HardFail never reaches V2; v4 rule 3 over the accepted attempt | `test_ac_7_2_an_unresolvable_citation_is_b1_final_whatever_the_votes_or_a_gold_label` |
| AC-7-3 | `ehmf.conflicts`; disclosure v2; `d_weight` = the record's `D_disclosed`; v4 rule 4 | `test_ac_7_3_contradicting_spans_are_disclosed_and_the_disclosed_conflict_weighs_zero` |
| AC-7-4 | `CorrectionGuard.check_re_render`; `ehmf_set_changed`; v4 rule 6 | `test_ac_7_4_a_corrected_type_e_finding_leaves_the_claim_and_span_sets_unchanged`, `test_ac_7_4_the_engine_refuses_a_re_render_that_changes_the_claim_or_span_set` |
| AC-7-5 | `CorrectionGuard.begin_cycle` (refuses cycle 3); exhausted → abstain + X2; `ehmf.x2_emitted`; x-triggers-v2 | `test_ac_7_5_a_third_correction_attempt_is_refused_the_claim_abstains_and_x2_is_emitted` |
| AC-7-6 | `scripts/run_golden_set.py --check` exit 6 on a pin mismatch; CI step | `test_ac_7_6_a_package_edit_without_a_golden_set_run_fails_the_ci_check` |

---

## 3. Data shapes

### 3.1 The EHMF vocabulary (`apps/api/app/services/ehmf/vocabulary.py`, standard library only; the only definition)

`EHMF_VERSION "ehmf-v1"`; `EHMF_TYPES ("A","B","C","D","E")`; `SUBTYPES {"B": ("B1","B2")}`; `FINDING_TYPES`; `TYPE_OF`; `PRIMARY_ORDER ("B1","A","B2","D","C","E")`; `PLAN_TYPES_BY_CHECK` (the plan's Phase 4 D table, verbatim); `PLAN_WEIGHTS {"A": "1.0", "B": "1.0", "C": "0.6", "D": "0.6", "D_disclosed": "0", "E": "0.4"}`; `ROUTING_VERSION "ehmf-routing-v1"`; `MITIGATIONS` (plan task 1); `OWNERS`; `TELEMETRY`; `EHMF_FIRST_MAJOR 6` (equal to `config_package.EHMF_SCHEMA_VERSION`, the first package schema with an ehmf block; E16); `PRE_PHASE_7 "pre-phase-7"`; `PRECEDENCE_RULE "precedence-v1"`; `DISCLOSURE_TEMPLATE "conflict-disclosure-v2"`; `LIBRARY_SCHEMA "misconception-library-v1"`; `GOLDEN_SET_VERSION "golden-set-v1"`; `STOP_RULE`; `PENALTY_RULE`; `EHMF_DETECTOR_DOWN`; `EHMF_SET_CHANGED`.

Re-exports by import: `contracts.EHMF_BY_CHECK` and `config_package.V1_EHMF` are `PLAN_TYPES_BY_CHECK`; `v2_panel.rules`, `v3.rules`, `gateway/contracts.py` and `schema_upgrades` import `EHMF_TYPES`; `v3.rules.PLAN_SEVERITY` is removed and the loader uses `PLAN_WEIGHTS`. `verifier_prompt_hash()` and the pinned verdict-request schema keep their values.

### 3.2 The routing table (`ehmf/routing.py`; package `ehmf.routing.table`; doc `docs/architecture/ehmf-routing.md`)

`FINDING_RULES_BY_VERSION = {"ehmf-routing-v1": FINDING_RULES}`; `FINDING_RULES` maps `(source, reason)` to a finding type:

| Source | Reason(s) | Type | Scope |
|---|---|---|---|
| V1.1 | `unresolvable`, `malformed_span_id`, `content_hash_mismatch` | B1 | response (the candidate) |
| V1.2 | `unresolvable` (unreachable after V1.1; kept so the mapping is total) | B1 | claim |
| V1.2 | `unbound`, `outside_bundle`, `not_quotable`, `partial_sentence`, `not_verbatim`, `negation_mismatch`, `quantity_mismatch` | A | claim (dropped proposal) |
| V1.2 | `no_bound_claims` | A | response |
| V1.3 | `contradicted` | A | claim |
| V1.3 | `not_enough_info`, `below_support_threshold` | B2 | claim |
| V1.4 | `unmapped_factual_sentence` | D | response |
| V1.4 | every other subset problem code, `render_failed` | E | response |
| V1.5 | every abstain reason | A | response |
| V1.6 | `keyed_answer_present` | E | response |
| V1.7 | `conflict_withheld`, `conflict_disclosed` | D (disclosed weighs `D_disclosed`) | attached to the conflict's claims |
| V1.8 | `misconception_match` | C | claim |
| V1.9 | `claim_plan_invalid`, `generator_mismatch`, `response_envelope_invalid`, `below_band`, `above_band` | E | response |
| V2 | `CONTRADICTED` | A | claim |
| V2 | `NOT_ENOUGH_INFO` | B2 | claim |
| alignment | `leakage` | E | response |

No finding: V1.3 `no_checker` (detector absent), V1.3 `checker_unavailable` (detector down), V1.5 `near_miss` (a mark). `routing_table()` returns per type `{"detectors", "mitigation", "owner", "telemetry", "final"}`; `routing_sha256()` is its canonical sha256; the loader requires the package's table and sha256 to equal them. The verifier's own type is recorded as `reported_type` and never decides a finding's type.

### 3.3 Record contracts (`tutor_pipeline/contracts.py`, section `# EHMF (Phase 7)`; additive)

```python
FindingType = Literal["A", "B1", "B2", "C", "D", "E"]
FindingSource = Literal["V1.1", "V1.2", "V1.3", "V1.4", "V1.5", "V1.6", "V1.7", "V1.8", "V1.9", "V2", "alignment"]
EHMF_FINAL_REASONS = ("ehmf_detector_down", "ehmf_set_changed")

class EhmfFinding(Contract):
    source: FindingSource
    reason_code: str
    type: FindingType
    attempt: int = Field(ge=1, le=3)
    claim_id: str | None = Field(default=None, pattern=CLAIM_ID)
    reported_type: EhmfType | None = None
    family: str | None = None

class EhmfClaim(Contract):
    claim_id: str = Field(pattern=CLAIM_ID)
    findings: tuple[EhmfFinding, ...] = Field(max_length=64)
    primary: FindingType | None
    weight: str

class EhmfConflict(Contract):
    kind: Literal["version_of_same_asset", "number_disagreement", "negation_disagreement"]
    span_ids: tuple[str, ...] = Field(min_length=2, max_length=12)
    item_ids: tuple[str, str]
    claim_ids: tuple[str, ...] = ()
    rule: Literal["precedence-v1"] = "precedence-v1"
    winner_item_id: str | None
    basis: Literal["metadata_incomplete", "no_rule_applies", "rules_disagree", "newer_peer_reviewed", "primary_over_secondary", "both_rules"]
    disclosed: bool
    d_weight: str

class EhmfDisclosure(Contract):
    template: Literal["conflict-disclosure-v2"] = "conflict-disclosure-v2"
    template_sha256: str = Field(pattern=HEX64)
    text: str = Field(max_length=2000)

class EhmfCorrection(Contract):
    cycle: int = Field(ge=1, le=2)
    kind: Literal["revise", "re_render"]
    types: tuple[FindingType, ...]
    claim_set_before: str = Field(pattern=HEX64)
    claim_set_after: str | None = Field(default=None, pattern=HEX64)
    span_set_before: str = Field(pattern=HEX64)
    span_set_after: str | None = Field(default=None, pattern=HEX64)
    outcome: Literal["applied", "refused_set_changed", "ended"]

class EhmfRecord(Contract):
    block_schema: Literal["ehmf-v1"] = "ehmf-v1"
    mode: Literal["shadow", "on"]
    routing_version: Literal["ehmf-routing-v1"]
    routing_sha256: str = Field(pattern=HEX64)
    config_version: str
    library_version: str
    library_sha256: str = Field(pattern=HEX64)
    weights: dict[str, str]
    claims: tuple[EhmfClaim, ...] = Field(max_length=20)
    response_findings: tuple[EhmfFinding, ...] = Field(max_length=256)
    conflicts: tuple[EhmfConflict, ...] = Field(max_length=20)
    disclosure: EhmfDisclosure | None
    corrections: tuple[EhmfCorrection, ...] = Field(max_length=2)
    x2_emitted: tuple[str, ...]
    max_cycles: Literal[2] = 2
    detector_down: tuple[str, ...] = ()
    detector_absent: tuple[str, ...] = ()

class VerificationRecordV4(VerificationRecordV2):
    verification_schema: Literal["ehmf-verification-v1"] = "ehmf-verification-v1"
    ehmf: EhmfRecord
    # _rules: verification_problems(..., final_reasons=V2_FINAL_REASONS + EHMF_FINAL_REASONS) + _v2_rules() + _ehmf_rules()

class LedgerEntryV4(LedgerEntryV3):
    entry_schema: Literal["ledger-entry-v4"] = "ledger-entry-v4"
    verification: VerificationRecordV4
    # _v4_rules: verification.ehmf.config_version == versions.config_package_version; delivery == "shadow" (DI-111)
```

`ACCEPTED_ABSTENTION_REASONS["ledger-entry-v4"]` adds `EHMF_FINAL_REASONS`; `SCHEMA_MODELS["LedgerEntryV4"]` and `ENTRY_SCHEMAS["ledger-entry-v4"]` are set. `primary_of(findings, weights)` and `finding_weight` compute a claim's primary type and weight from a record's own weights.

**`VerificationRecordV4._ehmf_rules()`** (each line a refusal; "accepted" is the final generation attempt, M19):
1. `ehmf.claims` are not one per verdict in order; a claim entry holds a finding of another claim or a response-level one (V1.7 findings sit only on a conflict's claims).
2. A finding whose type is not `FINDING_RULES_BY_VERSION[ehmf.routing_version][(source, reason)]`; a V2 finding without a family (or a non-V2 one with one); weights other than A, B, C, D, D_disclosed, E, or `D_disclosed != "0"`.
3. **AC-7-2.** The accepted V1.1 result is a hard fail while any verdict is delivered or voted on; a claim with a B1 finding that is delivered or voted on.
4. **AC-7-3.** Conflicts not one per disclosure-block conflict in order; `disclosed` not equal to the disclose policy; `d_weight` not the record's `D_disclosed` (disclosed) or `D` (undisclosed); `ehmf.disclosure` set iff a conflict is disclosed.
5. A winner without an ordering basis, an ordering basis without a winner, or a winner outside the pair.
6. **AC-7-4.** An applied re-render whose sets differ; a `refused_set_changed` correction whose sets are equal, or that does not abstain with `ehmf_set_changed`; `ehmf_set_changed` without a refused correction.
7. **AC-7-5.** Corrections not the V2 cycles (count, numbering, kinds); `x2_emitted` not the sorted X2-escalated claims.
8. Detector state: a detector down without an abstention; V1.3 down with a reason other than `checker_unavailable` or `ehmf_detector_down`; another detector down without `ehmf_detector_down`; `ehmf_detector_down` without a detector or outside mode `on`.
9. A claim's `primary` and `weight` not `primary_of(findings, ehmf.weights)`.

`v2_panel.aggregate.build_record_v2` is split into `_record_fields_v2(...)` (the fields, unvalidated) and `build_record_v2` (`VerificationRecordV2(**fields)`); `ehmf.record.build_record_v4` builds `VerificationRecordV4(**fields, ehmf=...)` from the same fields. An EHMF abstention is built as a V1 abstention whose final reason is the EHMF reason.

### 3.4 Runtime types (`ehmf/*.py`)

`SourceMetadata(source_year, peer_reviewed, source_role)` with `complete()`; `Precedence(winner_item_id, basis)`; `StopState(revert_required, reason, from_config_version, to_config_version)` with reasons `clear`, `rising_ab`, `reverted`, `unreadable`, `not_evaluated`; `CorrectionLimit`; `DetectorDown(detector)`.

### 3.5 Library file (`apps/api/app/config_package/misconceptions/v1.json`, LF; sidecar `v1.json.sha256`)

```json
{"library": "qcai-misconception-library", "schema": "misconception-library-v1", "version": "v1",
 "status": "no production entries: the Q-14 seed list is unavailable (A-18); entries are the Content Owner's",
 "editors": ["content_owner", "v3"], "synthetic": false, "entries": []}
```

Entry shape (validated; none ship): `{"id": "mc-<lowercase slug>", "terms": [...], "paraphrase": "<= 280 chars", "span_ids": ["span-<64 hex>"], "editor": "content_owner" | "v3:<64-hex gold record hash>" | "synthetic-test" (synthetic libraries only), "edited": "YYYY-MM-DD"}`. A synthetic library is refused at the shipped path.

### 3.6 Golden set (`docs/evaluation/phase7/golden_set_v1.json`, LF; canonical sha256 pinned in v6)

Items: `{"id", "class", "source": "phase4:<case id>" | "synthetic", "query", "attack", "expect": {"delivered", "types", ["absent_types"], "x2", "disclosed"}}`. 40 items (PD-47):

| Class | Count | Source | Expected |
|---|---|---|---|
| negation | 10 | the 5 `stripped_negation` and 5 `inserted_negation` Phase 4 cases | A, not delivered |
| invented citation | 5 | the 5 `unresolvable_span_id` cases | B1, not delivered |
| non-supporting citation | 3 | synthetic: every verifier NOT_ENOUGH_INFO | B2, not delivered, X2 |
| misconception | 3 | the 3 `misconception` cases with the Phase 4 `fixture_library` | C, not delivered |
| conflict | 3 | the 3 `conflict_version` cases (conflict 10) | D disclosed (weight 0), not delivered undisclosed |
| leakage | 3 | the 3 `keyed_answer_leak` cases | E, keyed claims not delivered |
| alignment leakage | 1 | synthetic: alignment leakage on every render | E, X2 (conflict 26) |
| invalid schema | 2 | the first 2 `invalid_schema` cases | E, not delivered |
| exhausted | 2 | synthetic: every verifier CONTRADICTED | A, abstain, X2 |
| supported | 8 | in-domain `score_floor_queries.json` queries 0, 9, 16, 23, 43, 63, 70, 139 | delivered; no A, B1, B2, C or D finding; 100% citation resolution |

### 3.7 Golden-run record (`docs/evaluation/phase7/golden_run_v1.json`, LF)

`{"report": "qcai-ehmf-golden-run", "format_version", "created_at", "commit", "evidence_class", "pins": {"config_package", "misconception_library", "routing", "golden_set"}, "configuration", "outcomes": [{"id", "delivered", "final", "types", "x2", "disclosed", "met"}], "citation_resolution", "per_type", "result", "problems", "inputs"}`.

`created_at` and `commit` are informational: `--check` compares every other key. `commit` is the HEAD the record was written from, with the suffix `-dirty` when the tree differed from it: a record written with `--allow-dirty` on the finished change, before its own commit exists, names the parent commit with `-dirty` (4.8); one written on a tree equal to HEAD after its code was committed names that commit. The committed record was written with `--allow-dirty` on the finished review-4 change, before its commit existed, so it names the parent commit `51f4ba0` with `-dirty`. `inputs` (rule `application-modules-and-runner-scripts-sha256-lf-v1`) is the sha256 of every `apps/api/app` module and the two runner scripts (`scripts/run_golden_set.py`, `scripts/run_v1_fixtures.py`), LF-normalised: a fixed file set, so an in-process `--check` and a CLI run agree, and any application code change is drift (exit 1) until the record is rewritten.

**Package version history** (`docs/evaluation/phase7/package_versions.json`, LF): `{"history": "qcai-config-package-versions", "format_version": 1, "rule", "entries": [{"version", "sha256"}]}`. One entry per `package_version` of a package with an ehmf block, oldest first and each version once; append-only, so a recorded sha256 never changes. CI enforces append-only against the base branch: `--check --base-ref FETCH_HEAD` (the pull request's base, fetched by name) requires the history to start with the base's committed history unchanged (4.8). It holds `6.0.0` with the shipped package's sha256. `--write` appends to it and `--check` reads it (4.8); the one sanctioned hand edit is the renumbering step (`docs/architecture/ehmf-change-control.md`), made before the history reaches `main`.

### 3.8 Source-fidelity register and report (`docs/evaluation/phase7/`)

The register holds the three plan facts (F-7, E-30): `quen-external-sensitivity` (table 4, row 2, column 4; `External Sens.`; source 0.828), `quen-external-fp-rate` (column 5; `External FP Rate`; source 1.143) and `gea-alignment-wording` (paragraph 68, anchor `GEA`; phrase "perfectly aligned" absent; source "GEA = 0.40"). The report holds the register sha256, the 12 DOCX paths and sha256s, per entry `{"id", "docx_value", "source_value", "match"}`, `"mismatches": 3`, `"result": "mismatches_present"` and `"ac_11_3": "not met: correction at source is the Content Owner's (D-16; DI-105)"`.

---

## 4. Algorithms

### 4.1 Typing (`ehmf/classify.py`)

- `finding_for_v1(result)`: None for pass, mark and the no-finding detector states; else the routed finding with the result's attempt and claim id.
- `findings_for_v2(verdict)`: one finding per objecting member family's folded verdict (rule F): CONTRADICTED A, NOT_ENOUGH_INFO B2, `reported_type` and `family` recorded; a withheld claim has none.
- `claim_entry(verdict, *, disclosure, generation, weights)`: the verdict's results of its own claim id, one V1.7 D finding per conflict listing the claim, and its V2 findings; primary and weight by `primary_of`.
- `response_findings(record)`: response-level results of every attempt, V1.2 results whose claim is not a verdict's (dropped proposals), and the alignment item's leakage (E) when it failed.

### 4.2 Precedence and disclosure (`ehmf/conflicts.py`; PD-42)

`precedence(a, b, *, item_a, item_b)`: incomplete metadata on either side → `metadata_incomplete`; R1 (both peer-reviewed, years differ: the newer), R2 (roles differ: the primary); neither → `no_rule_applies`; one → its winner (`newer_peer_reviewed`, `primary_over_secondary`); both agree → `both_rules`; disagree → `rules_disagree`. `metadata_for` reads only the manifest item's optional fields (5.4). Precedence is recorded only. Every detected conflict is disclosed under `disclose` with `d_weight` = the record's `D_disclosed`; under `withhold` it is undisclosed with weight D. The template `conflict-disclosure-v2` (package `ehmf.conflicts.disclosure_template.text`):

> These course sources disagree ({kinds}) between {items}. Both passages are shown; neither is preferred unless a precedence basis is named: {basis}.

`template_sha256` is the canonical sha256 of `{"id", "text"}`; no span text enters it. Conflicts with a source outside the public corpus are not detected (plan M residual).

### 4.3 The detector guard (`ehmf/detectors.py`)

Under `EHMF=on`, `V1Track._guard` wraps `check_v1_1`, `check_v1_2`, `check_v1_3` (a fault inside it outside the checker call; the checker's own exception is `checker_unavailable`, below), `check_v1_5` (the sufficiency check, called before generation), `check_v1_7`, `check_v1_8` (and raises for a missing or unavailable library), the post-render V1.4 (the subset checker itself: `render_checked(..., subset_check=V1Track._subset_check)` calls `pipeline.check_subset` through the guard, and `_render_with_hook` re-raises `DetectorDown` instead of counting it a render fault), V1.6 and V1.9 (in the post-render hook, called outside the render loop's `except Exception`), the V2 consult and the alignment item. On `DetectorDown(name)` the runner abstains with `ehmf_detector_down`, records `detector_down=(name,)`, pads any cycle in progress as `ended`, and logs `tutor.ehmf.detector_down`. V1.3's own `checker_unavailable` keeps Phase 4's abstention and is recorded as `detector_down: ("V1.3",)`. `ehmf.detectors.DETECTORS` is the closed list of guarded detectors (V1.1-V1.9, V2, alignment): `guarded()` and `DetectorDown` refuse any other name (`ValueError`), and `test_plan_j_every_guarded_detector_has_a_detector_down_case` checks that the detector-down test's cases equal it and that the names every guard call site in `apps/api/app` passes (read with `ast`) are exactly its names. Under `shadow` and `off` nothing is wrapped.

### 4.4 Correction (`ehmf/correction.py`; PD-44)

`CorrectionGuard(max_cycles=package.ehmf.max_cycles)` (v5: Phase 5's constant) is the loop's only bound in every mode: `_v2_loop` and `_final_rendering` call `begin_cycle(cycles + 1)` before each cycle and treat `CorrectionLimit` as exhaustion (claims abstain with X2; `tutor.ehmf.correction_refused` `cycle_limit` is logged only when EHMF is not off). With the guard's raise removed, the runner builds `V2Correction(cycle=3)`, which the contract refuses. With EHMF not off, `_EhmfRun.cycle` records each cycle (`claim_set_sha256`, `span_set_sha256` before and after, its finding types) and, on a `re_render` whose sets differ, abstains the response with `ehmf_set_changed` and logs `tutor.ehmf.correction_refused` `set_changed`. Type E is re-rendered only; other failing claims are revised through `revise()` or re-verified; B1 never reaches the loop.

### 4.5 Library (`ehmf/library.py`; PD-43)

`library_problems(raw, *, store, shipped)` refuses a wrong `library`, `schema` or `editors`; `synthetic` at the shipped path; an editor other than `content_owner` or `v3:<64 hex>` (or `synthetic-test` in a synthetic library); fewer than 2 terms or terms not lowercase, sorted and unique; an empty or over-280-character paraphrase; a malformed span id, or (with a store) one not in the public corpus; (with a store) a paraphrase sharing a run of more than 8 normalised words with a cited span; a duplicate id; a non-ISO `edited`. `read_library_file` also checks the package pin and the sidecar. `proposals_from_gold(db)` emits one `misconception-proposal-v1` per Type C claim label of an applied item's final gold row (`source v3:<record_hash>`, claim id, span ids, `claim_text` null (conflict 27), `editor_required content_owner`, `applied false`). `python -m app.workers.ehmf export-library-proposals --path P` refuses paths inside the application tree or the checkout and never edits the library.

### 4.6 Building the typed record (`ehmf/record.py`; `tutor_pipeline/pipeline.py`)

`TwoPassPipeline._v1` computes `ehmf.mode(settings, package, v2_mode=...)` and passes it to `V1Track`. With a `VerificationRecordV4`, `_entry_v3` builds a `LedgerEntryV4` (same provenance and claims) and logs `tutor.ehmf.record`. `detector_absent = ("V1.3",)` when the checker is `none`. The manifest's items (for precedence) come from the store registry's manifest path (`ehmf.conflicts.manifest_items`).

### 4.7 Retrieval penalty (`lexical_index.py`, `content_assembler.py`; PD-45)

`LexicalIndex(..., penalties=None)`: empty or None keeps both sort lines exactly; otherwise bm25f-v1 sorts by `(-(Fraction(score) * factor), span_id)` and p1-floor by `score * float(factor)`, stable. Only the ranking changes. `CourseStore` passes `_span_penalties(settings, package)`: the environment's registry only when `_penalty_active(settings, package)` (`settings.ehmf == "on"` and `ehmf.mode == "on"` when the store is built), else `{}`. The store keeps `penalty_active`, fixed for its life; `/ready` reports it (10.2), never a mode recomputed later (a gateway that stops after start-up turns the mode off but leaves the index as built). `index_version` adds `penalties_sha256` only when the mapping is non-empty. The mapping depends on span ids and the environment only (invariant 1).

### 4.8 Change control (`scripts/run_golden_set.py`; `docs/architecture/ehmf-change-control.md`; PD-47)

`--write PATH [--allow-dirty] [--package PATH] [--history PATH] [--base-ref REF | --base-history PATH]` and `--check PATH [--package PATH] [--history PATH] [--base-ref REF | --base-history PATH]`; `--history` defaults to the package version history `docs/evaluation/phase7/package_versions.json` (3.7). The runner builds its own in-memory SQLite database and the all-public-approved store, and runs each item with `Settings(environment="development", v1_pipeline="enforce", model_gateway="on", ehmf="on", v3_queue="off", retrieval_gate="bm25f-v1", config_package_path=<package>)` over development fake adapters. Phase 4 items run through `run_v1_fixtures.run_pipeline_case`, whose `_pipeline` and `run_pipeline_case` gained optional `settings` and `pipeline_options` (a gateway, registry, cache and session factory; defaults unchanged). `--check`: (1) pins: the package, library, routing and golden-set sha256s against the record, exit 6; (2) the package's `ehmf.golden_set.sha256` against the file, exit 6; (3) the history (`history_problem`): the package's `package_version` absent from it, or recorded there with a different sha256, exits 6, so a package edit that keeps its version fails the CI step whatever record file is checked (a record re-written for the edited package, after deleting the committed one or at another path, still fails); (4) append-only, when a base is given (`base_problem`): the base's history (`--base-ref REF`: `base_history_at` reads the committed file at REF with `git show`, file content, so a squash merge does not matter; `--base-history PATH`: a file) must be an unchanged prefix of the history, else exit 6, so rewriting the edited version's entry to the new sha256, or removing it for `--write` to append again, fails too; a REF without the file has no entries (before the history first reaches `main`), and an unknown REF or a malformed base exits 2; CI passes `--base-ref FETCH_HEAD` after fetching the pull request's base branch (else `main`) (14); (5) a fresh run: an unmet expectation or an unresolved delivered citation exits 3, a difference from the record (`created_at` and `commit` aside) exits 1. `--write` refuses (exit 6) a package whose sha256 differs from the replaced record's under the same `package_version` (`same_version_edit`), and (`append_problem`) one whose version the history records with another sha256, or that is new but not newer than the history's newest entry, and (with a base) a history that does not start with the base's; on a passing run it appends the package's `(version, sha256)` to the history when absent, then writes the record. A missing or malformed history (an entry other than `{version, sha256}`, a version listed twice or out of order) exits 2, and so does a package whose `package_version` is not MAJOR.MINOR.PATCH (the loader checks only its major part; both modes refuse it before any history comparison). `config_version` is the package version and the stop (4.10) finds a change only where it differs, so every package edit bumps the version. Two write modes: `--write` refuses a tree that differs from HEAD (exit 4) unless `--allow-dirty`. With `--allow-dirty` on the finished change, before its own commit exists, the record's `commit` names the parent commit with `-dirty`; on a tree equal to HEAD (the record written after its code was committed, and committed after it) `commit` names that commit. Either way `inputs.sha256` (the application modules and the two runner scripts) identifies the code. The committed record was written the `--allow-dirty` way (3.7). Exit codes: 0, 1 drift, 2 usage or refusal (a missing or malformed history or base, or a package_version that is not MAJOR.MINOR.PATCH, included), 3 unmet, 4 dirty tree on `--write`, 6 pin mismatch, a same-version package edit, or a history that rewrites the base's. The procedure: edit and bump `package_version`, rehash, rerun `--write` (either mode, with `--base-ref origin/main`), commit the record and the history in the same change, CI green, review approval. Rollback: reload the prior 6.x package, the one the stop names in `from_config_version`. The procedure edits the package in place, so that package is the one in the prior image: the operator deploys the prior image digest, and `/ready` then reports its `config_package_version` and `config_package_sha256`, which the history records. Reloading v5 (readable for one release, DI-112) turns EHMF off and is not a revert of the stop.

### 4.9 config_version (`app/services/ledger.py`)

`config_version_of(versions)` returns the version when its major is at least `EHMF_FIRST_MAJOR`, else `pre-phase-7` (a malformed version is major 0). `export_ledger` adds `config_version` to each line (restore reads named keys only); `ledger_provenance` adds `config_versions` counts; `_provenance_problems` and `pending_v3_intents` include `ledger-entry-v4`. The ledger route is unchanged.

### 4.10 The stop (`ehmf/stop.py`; PD-46)

`ab_series` reads the last `scan_records` (5000) `ledger-entry-v4` rows (a plain column filter, `ORDER BY seq DESC LIMIT`), counting typed claims (claim entries plus dropped proposals) and A/B claims (a finding of A, B1 or B2). `detect` takes each change point of `config_version`: before = the last `window_claims` (200) typed claims of the old version (whole records), after = the new version's from the change, up to `window_claims`; a change point is evaluated only while its before-window is whole: the walk back stops at another version or a full window, or reaches the start of the series with no earlier typed record (`_series` reads `scan_records + 1` rows to know); one whose window the scan cut (later records pushed it to the start of the scan) is skipped, never fired, so a constant A/B rate never fires the stop; it fires at `after_claims >= 100`, `after_ab >= 2` and `after_ab * before_claims * 2 > before_ab * after_claims * 3`, never with no claims before; `detected_seq` is the record at which the after window first meets it. It inserts `ehmf_stops` with `ON CONFLICT (from, to, change_seq) DO NOTHING RETURNING seq` and logs `ehmf.stop`. `v3.scan._scan_once` calls it once per scan before `open_windows`, inside the scan's transaction and lock, only when the package has an ehmf block and `ehmf.mode` is not off. `open_windows` adds `[detected_seq, remaining]` per stop row, so the learner deliveries after it are drawn at 1/5. `stop_state`: the latest row (read in a SAVEPOINT on PostgreSQL, so a failed read leaves the caller's session usable); `revert_required` when its `to_config_version` is the package in force; `reverted` when its `from_config_version` is; `clear` with no row or neither; `unreadable` on an exception. `process_stop_state` is cached per process and returns `not_evaluated` without a read when EHMF is off. The revert is the operator's.

### 4.11 Metrics (`ehmf/metrics.py`)

`slis(db, package, *, window_records=1000, stop=None)` over the last typed records grouped by `config_version`: `per_100_claims` and `per_100_responses`: per type, the rate per 100 as an exact reduced fraction string (`100*k/n`, such as `50` or `100/3`; null when the denominator is 0), beside the denominator (`claims`, `responses`), with `claim_type_counts` and `response_type_counts` holding each `k` (a typed claim is a claim entry or a dropped proposal, one per claim id of a response finding, as `stop._typed_counts` counts it; a response counts each type among its response findings), `type_d_disclosure_share`, `correction_cycles` (`0`, `1`, `2`, `exhausted`), `x2_emissions`, `set_changed_refusals`, `detector_down`, the stop, `config_version` and the evidence class "telemetry, not E2 results (plan Phase 7 H: per-type rates are not E2 results)". `GET /v3/metrics` adds `ehmf` (`v3.metrics.slis(..., settings=)` computes it only when EHMF is not off, else null with no EHMF read); `python -m app.workers.ehmf status` logs `ehmf.status`, or, under a package without an ehmf block, `ehmf.status_refused` (reason `no_ehmf_block`) with the `ehmf_stops` rows and exit 2.

### 4.12 Source fidelity (`scripts/check_source_fidelity.py`; PD-49)

Lists the DOCX with `git ls-files '*.docx'` (exit 2 unless 12) and reads each read-only with python-docx. A number entry compares the cell as decimals after checking the row and column labels (else exit 2, "register location moved"); an absent_phrase entry requires its anchor and matches when the phrase is absent. `--check` compares with the committed report (exit 1); `--require-zero` exits 7 on mismatches. It never prints or stores other DOCX text.

### 4.13 Mode and start-up

`ehmf.mode(settings, package, *, v2_mode=None)` is `off` without an ehmf block, when `EHMF_UNAVAILABLE_REASON` is set, when the setting is off, or when the V2 mode is off; otherwise the setting. `main._check_ehmf_package` runs after `_check_v3_package`: `check_ehmf_package(package, structural=False)` (routing, weights, bound, stop and penalty structure, the library file); a problem stops a governed build when EHMF is not off, else sets the reason and logs `ehmf.unavailable`. `structural=True` (tests, `config_package.py --check`) also checks the golden-set file's sha256 and item count, the routing document, and the library with the development store.

---

## 5. Configuration package v6 (`apps/api/app/config_package/v6.json`)

### 5.1 File

v6 is v5 with: `package_version "6.0.0"`, `schema_version 6`, `phase "7"`, `created "2026-11-23"`, `supersedes` v5 (5.0.0, its sha256, readable until the release after the Phase 7 merge); `v1.v1_8.library` the pin `{"path": "misconceptions/v1.json", "schema", "version": "v1", "sha256"}` (authority "Q-14 unavailable (A-18); DI-53, DI-106"); the `LedgerEntryV4` schema pin and `ledger.entry_schema "ledger-entry-v4"` with `entry_schemas` v1-v4; `v3.triggers` `x-triggers-v2` (`record "PD-32, PD-44"`, `X2 "v2-exhausted-any-type-v2"`, `x2 {"fires_on": "every_x2_escalation", "emitted_by": "ehmf.correction"}`); `v3.priority.severity {"source": "ehmf.weights", "unknown": 1.0}`; `flag_policy.ehmf` (`off|shadow|on`, development `shadow`, elsewhere `off`, `on_requires phase7_exit_passed`, `requires model_gateway_not_off`), `phase7_exit_passed false`, `phase7_exit_evidence null` and the authority's PD-48/DI-109 clause; owner decisions `EHMF-WEIGHTS` (open, PI), `D-16` (recommended, not applied, CO), `Q-11` (unresolved), `EHMF-SOURCE-METADATA` (unsupplied, CO), `Q-14` and `D-06` extended. The `ehmf` block holds `version`, `types`, `subtypes`, `routing` (table and sha256), `weights` (A 1.0, B 1.0, C 0.6, D 0.6, D_disclosed 0.0, E 0.4, unknown 1.0; provisional, owner decision `EHMF-WEIGHTS`), `conflicts` (precedence-v1 recorded only, the two rules, the metadata fields, the template and its sha256), `library` (editors, 280 characters, 8 words, 0 production entries, proposals exported never applied), `correction` (max cycles from `v2.correction.max_cycles`, third cycle refused, every exhausted claim abstains with X2, the set rule, the mitigations), `retrieval_penalty` (rank only, EHMF on only; development 1/2, staging, production and default 1/1; empty span lists), `stop` (200, 100, 2, rise 3/2, 5000, audit rate and window from `v3.triggers.x5`, operator revert, 60 s), `golden_set` (version, path, sha256, 40 items, run record, drift blocks promotion) and `config_version` (`package-version-v1`, earlier `pre-phase-7`, first package `6.0.0`). Every provisional sub-block is marked. New files: `v6.json.sha256`, `misconceptions/v1.json` and its sidecar, `schemas/ledger-entry.v4.schema.json`. v1-v5 and every existing schema file are unchanged.

### 5.2 Loader (`app/core/config_package.py`) and package check

`DEFAULT_PACKAGE_PATH` is v6 and `V5_PACKAGE_PATH` v5; `schema_version` 1-6; `TUTOR_SCHEMA_NAMES_V6` and `LEDGER_ENTRY_SCHEMAS_V6`; `ConfigPackage.ehmf: EhmfParams | None`; `FlagPolicy.phase7_exit_passed/evidence`. `EHMF_SCHEMA_VERSION` (6) is the first schema with an ehmf block; every schema-dependent rule of the loader, `tutor_pipeline/package_check.py`, `v3/package_check.py` and `scripts/config_package.py` compares with it, never with a literal. Schema 6: `_parse_library_pin` resolves the library next to the loaded package file (a package file copied alone, with no `misconceptions/` folder beside it, reads the shipped library, which must still match the pin: a pin naming another sha256 or version is refused, never loaded with the shipped library in its place) and requires its sha256 to equal the pin and the sidecar and `library_problems` to be empty (a missing file is structural, fail-closed); `_parse_ehmf` refuses an unmarked provisional block, a version, type, subtype, routing table or sha256 other than the code's, weights other than the plan's while `EHMF-WEIGHTS` is open, `D_disclosed != 0`, `unknown != 1`, conflict rules or template other than the code's, a correction policy other than 5.1's or `v2.correction.max_cycles != 2`, penalty registries other than the four, a factor outside (0, 1], a non-development factor other than 1 or a non-empty non-development list while D-06 is open, a synthetic span outside development, stop bounds out of range (`min_claims <= window_claims`, `scan_records >= 2 * window_claims`, rise above 1, refresh 1..3600), a golden-set version or path other than 5.1's, a `config_version` other than 5.1's or a package major below 6, and a missing owner decision. `_parse_v3` for schema 6 requires `x-triggers-v2`, the v2 rules and x2 block and builds severity from `ehmf.weights`; `V3Params.x2_types` is `(A, B)` for v1 and None for v2. `_parse_flag_policy` checks `flag_policy.ehmf` against `EHMF_DEFAULT_DEVELOPMENT` and `EHMF_DEFAULT_ELSEWHERE`. `tutor_pipeline/package_check.py` takes the entry model and the expected entry schemas per schema version (v1-v4 for 6, v1-v3 for 4-5, v1-v2 for 3), so v4 and v5 pass unchanged. `v3/package_check.py` expects x-triggers-v2 for schema 6.

### 5.3 Scripts (`scripts/config_package.py`)

The default path is v6. `--check` runs `check_ehmf_package(structural=True)` for v6 and prints an EHMF summary. `--rehash` for v6 recomputes the library pin and sidecar, the routing table and sha256, the template sha256 and the golden-set sha256 and items. `--write-schemas` writes `ledger-entry.v4.schema.json`.

### 5.4 Manifest (`app/core/manifest_v2.py`, `scripts/generate_manifest.py`, `scripts/validate_corpus.py`)

`SOURCE_METADATA_FIELDS = ("source_year", "peer_reviewed", "source_role")` are optional item keys carried over from the existing manifest, never created. `source_metadata_problems` (run by `validate_corpus.py` and `generate_manifest --check`) refuses a year outside 1900..2100, a non-boolean `peer_reviewed`, a role other than primary or secondary, and a partial set. `corpus_version` is unchanged, and the committed manifest is unchanged.

---

## 6. Settings (`app/core/config.py`)

| Setting (env) | Type / default | Freeze rationale |
|---|---|---|
| `EHMF` | `Literal["off", "shadow", "on"] \| None = None`; None is `EHMF_DEFAULT_DEVELOPMENT` ("shadow") in development and `EHMF_DEFAULT_ELSEWHERE` ("off") elsewhere | Off outside development. `on` is refused outside development before the Phase 7 exit and needs the shipped, hash-verified package. Shadow outside development is a recorded override (`ehmf_shadow`) that changes no learner path. |

`main._record_configuration_overrides` adds `ehmf_shadow` and `ehmf_on`. `infra/cloudrun/api-production.env.example.yaml` sets `EHMF: "off"`. `run_v1_fixtures.py`, `run_v2_fixtures.py` and `run_v3_residual_report.py` set `ehmf="off"` in their development Settings; `replay_tutor_plans.py` runs in production, where EHMF is off.

---

## 7. File-by-file changes

### 7.1 NEW `apps/api/app/services/ehmf/`

`__init__.py` (`EHMF_UNAVAILABLE_REASON`, `mode()`), `vocabulary.py`, `routing.py`, `classify.py`, `conflicts.py`, `detectors.py`, `correction.py`, `library.py`, `record.py`, `metrics.py`, `stop.py`, `package_check.py`. No module under `ehmf/` imports the learner-record, progress, intelligence, microlearning, auth or route modules (E16). `vocabulary.py` and `routing.py` import nothing from `app`. Service events log on `qcai.ehmf`.

### 7.2 NEW elsewhere

`apps/api/app/workers/ehmf.py`; `apps/api/alembic/versions/20261123_phase7_ehmf.py`; `apps/api/app/config_package/v6.json`, its sidecar, `misconceptions/v1.json` and its sidecar, `schemas/ledger-entry.v4.schema.json`; `scripts/run_golden_set.py`; `scripts/check_source_fidelity.py`; `docs/evaluation/phase7/` (golden set, golden run, package version history, register, report, README); this spec; `docs/architecture/ehmf-routing.md`; `docs/architecture/ehmf-change-control.md`; `docs/adr/ADR-010-ehmf-operationalization.md`; `apps/api/tests/test_phase7_acceptance.py`, `test_ehmf_units.py` and `ehmf_fakes.py`.

### 7.3 MOD

`tutor_pipeline/contracts.py` (EHMF section), `tutor_pipeline/package_check.py`, `tutor_pipeline/pipeline.py`, `v1_checks/runner.py`, `v1_checks/v1_8_misconceptions.py` (`available`), `v1_checks/v1_7_conflicts.py` (docstring), `v2_panel/aggregate.py` (`_record_fields_v2`), `v2_panel/rules.py`, `v3/rules.py`, `v3/triggers.py`, `v3/scan.py`, `v3/metrics.py`, `v3/package_check.py`, `api/routes/v3.py` and `workers/v3_queue.py` (each passes `settings=` to `v3.metrics.slis`), `gateway/contracts.py`, `core/schema_upgrades.py` (`_guard_ehmf_tables`), `core/config.py`, `core/config_package.py`, `core/manifest_v2.py`, `lexical_index.py`, `content_assembler.py`, `ledger.py`, `db_models.py` (`EhmfStop`), `main.py`, the docstrings of `services/tutor_followups.py` and `services/tutor_pipeline/__init__.py` (they name the shipped package, v6 since Phase 7), `scripts/config_package.py`, `scripts/run_v1_fixtures.py`, `scripts/run_v2_fixtures.py`, `scripts/run_v3_residual_report.py`, `scripts/generate_manifest.py`, `scripts/validate_corpus.py`, `.github/workflows/ci.yml`, `.gitattributes`, the env example, `deployment.md`, `observability.md`, `docs/testing/test-strategy.md`, the Phase 3, 4, 5 and 6 specs and `docs/architecture/v3-trigger-registry.md` (7.4), `apps/api/tests/conftest.py` (resets the EHMF stop cache and availability), `v1_fakes.temp_package` and `v2_fakes.v2_pipeline` (13.3), and the records (12.2). `app/api/routes/ledger.py` is unchanged.

### 7.4 Text that describes the code (edited in place)

The Phase 6 spec's last section-3 block names `ehmf.vocabulary` instead of `EHMF_TYPES` and `PLAN_SEVERITY`, its 5.2 weight rule names `ehmf.vocabulary.PLAN_WEIGHTS`, and its conflict 11 states the v6 registry. The Phase 5 spec's `EHMF_TYPES` line notes the import. The runbook's Phase 3 rollback names `20261123_phase7_ehmf (head)` with the Phase 7, then Phase 6, then Phase 5 downgrade steps. The Phase 3 spec names `.../v6.json` with Phase 7, schema version 6 since Phase 7 and 6.0.0 for Phase 7's v6 (its constants, parsing, record shape and test 31 and 13.3 item 1); the Phase 4 spec names `v6.json` with Phase 7 and schema 6 since Phase 7. `docs/architecture/v3-trigger-registry.md` names the registry `x-triggers-v2` (package v6), X2's rule `v2-exhausted-any-type-v2` and the weights from `ehmf.weights`.

---

## 8. Database

One revision, `20261123_phase7_ehmf`, after `20261122_phase6_v3_audit`; `ledger.SCHEMA_REVISION` names it; `create_all` builds the same table. The table is needed because the stop's window and the `/ready` state must survive restarts and must not be recomputed from a growing ledger.

| Table | Columns | Keys and indexes | Rule |
|---|---|---|---|
| `ehmf_stops` | `seq` PK; `from_config_version`, `to_config_version` String(32); `change_seq`, `detected_seq`, `before_claims`, `before_ab`, `after_claims`, `after_ab`, `window_deliveries` Integer; `package_sha256` String(64); `created_at` DateTime(tz) | `uq_ehmf_stops_change (from_config_version, to_config_version, change_seq)`; `ix_ehmf_stops_to_config_version` | append-only; no learner identifier |

Guards (`schema_upgrades._guard_ehmf_tables`, after the V3 guards; re-created only when not current; no `%`): PostgreSQL triggers `ehmf_stops_append_only` (ROW, UPDATE and DELETE) and `ehmf_stops_no_truncate` (STATEMENT, TRUNCATE) executing Phase 6's `v3_append_only()`; SQLite `ehmf_stops_no_update` and `ehmf_stops_no_delete`. The downgrade refuses while `ehmf_stops` holds rows unless run as `alembic -x allow_ehmf_drop=true downgrade 20261122_phase6_v3_audit`; on PostgreSQL it drops the two triggers, then the index, then the table, never `v3_append_only()`. `ledger-entry-v4` is additive (no column change); mixed v1-v4 chains verify, export and restore through `ENTRY_SCHEMAS`. `ehmf_stops` holds no person's id, so erasure and retention are unchanged (E16).

---

## 9. Routes

No new route; the authorization matrix is unchanged. `GET /v3/metrics` (reviewer-only) adds `ehmf` when the package has one. `GET /ledger/responses/{response_id}` is unchanged.

---

## 10. Start-up, `/ready`, logs and SLIs

### 10.1 Start-up

`_check_v1_package`, `_check_gateway_package`, `_check_v3_package`, `_check_ehmf_package`, the tutor pipeline, the manifest. The library file is read by the loader. Nothing reads `docs/` or `apps/api/tests/` at start-up.

### 10.2 `/ready`

```json
"config_version": "6.0.0", "ehmf_mode": "off|shadow|on", "ehmf_setting": "off|shadow|on", "phase7_exit_passed": false,
"ehmf": {"version": "ehmf-v1", "routing": "ehmf-routing-v1", "routing_sha256": "…",
         "weights": {"A": "1", "B": "1", "C": "3/5", "D": "3/5", "D_disclosed": "0", "E": "2/5"}, "weights_provisional": true,
         "precedence": "precedence-v1", "disclosure_template": "conflict-disclosure-v2",
         "library": {"version": "v1", "entries": 0, "sha256": "…"}, "golden_set": {"version": "golden-set-v1", "items": 40},
         "max_cycles": 2, "retrieval_penalty": {"environment": "…", "factor": "1/2|1", "spans": 0, "active": false},
         "stop": {"revert_required": null}, "available": true}
```

`ehmf` is null for a package without an ehmf block. Every value is the package's own (`weights_provisional` is `ehmf.weights.provisional`, which the loader requires true while `EHMF-WEIGHTS` is open; `golden_set.version` is `ehmf.golden_set.version`). `stop.revert_required` comes from `process_stop_state()` and is null with no read when EHMF is off. `retrieval_penalty.active` is the shared store's `penalty_active` (4.7): true only when the index was built under `EHMF=on`. `config_package_version` reports 6.0.0 and `v3.trigger_registry` `x-triggers-v2`.

### 10.3 Log events

| Event | Logger | Fields | Severity |
|---|---|---|---|
| `tutor.ehmf.record` | `qcai.tutor` | `mode`, `per_type`, `conflicts`, `disclosed`, `x2`, `cycles`, `detector_down`, `config_version` | INFO |
| `tutor.ehmf.detector_down` | `qcai.tutor` | `detector` | WARNING |
| `tutor.ehmf.correction_refused` | `qcai.tutor` | `cycle`, `reason` (`cycle_limit`, `set_changed`) | WARNING |
| `ehmf.stop` | `qcai.ehmf` | `from_config_version`, `to_config_version`, `before_claims`, `before_ab`, `after_claims`, `after_ab` | WARNING |
| `ehmf.stop_unread` | `qcai.ehmf` | — | WARNING |
| `ehmf.unavailable` | `qcai.ehmf` | `reason` | WARNING |
| `ehmf.status`, `ehmf.proposals_exported` | `qcai.worker` | the mode and SLIs; `count` | INFO |
| `ehmf.proposals_export_refused` | `qcai.worker` | `reason` (`no_ehmf_block`, `inside_checkout`) | WARNING |
| `ehmf.status_refused` | `qcai.worker` | `reason` (`no_ehmf_block`), `stops` | WARNING |

### 10.4 SLIs

`ehmf.metrics.slis` (4.11) on `GET /v3/metrics` and `python -m app.workers.ehmf status`. No alert policy, log-based metric, dashboard or schedule is created (DI-110).

---

## 11. Frontend

No change. `apps/frontend` is untouched.

---

## 12. Records

### 12.1 New records

`docs/evaluation/phase7/golden_run_v1.json` (written with `--write --allow-dirty` on the finished change and committed with it: its `commit` names the parent commit with `-dirty`, 3.7, and its `inputs.sha256` the code, 4.8), `package_versions.json` (the package version history, 3.7), `source_fidelity_report_v1.json` (3 mismatches), `golden_set_v1.json`, `source_fidelity_register.json` and `README.md`.

### 12.2 Records re-written at the last code commit

`docs/evaluation/phase3/three_plan_replay_v1.json`, `phase4/v1_fixture_report_v1.json`, `phase5/v2_fixture_report_v1.json` and `phase6/v3_residual_report_v1.json` carry the package and the imported-module `inputs`; they are re-written with their own scripts. Decisions, classes, finals, rates, counts, draws and the residual are unchanged; a count that changes is a regression to investigate. `apps/api/tests/data/phase4_public_payloads_v1.json` is never re-written; its `--check` passes unchanged.

---

## 13. Tests

### 13.1 `apps/api/tests/test_phase7_acceptance.py` (fakes in `ehmf_fakes.py`)

| Test | Asserts |
|---|---|
| `test_ac_7_1_a_negated_claim_fixture_is_tagged_type_a_and_not_delivered` | EHMF on and shadow, the negating generator: a V1.2 `negation_mismatch` A finding on the proposal's claim id, which is in no verdict and not rendered; a V1.3-contradicted verbatim claim carries an A finding and is not delivered |
| `test_ac_7_2_an_unresolvable_citation_is_b1_final_whatever_the_votes_or_a_gold_label` | (a) every candidate cites an invented id under an all-SUPPORTED panel: abstain, hard fail, a B1 finding per attempt, no V2 verdict, no call; (b) the regeneration case keeps the attempt-1 B1 finding and validates; (c) a V3 gold label calling every claim SUPPORTED and the abstention a missed answer, adjudicated and applied, adds one gold row and changes no ledger row (still abstain, B1); (d) the contract refuses a delivered B1 and a B1 claim that is delivered |
| `test_ac_7_3_contradicting_spans_are_disclosed_and_the_disclosed_conflict_weighs_zero` | a Phase 4 conflict_version case with EHMF on: disclosed, template v2 naming both items and no claim text, each conflict `d_weight "0"`, no winner, `metadata_incomplete`, D findings only on the conflict's claims, V3 severity excludes D; the contract refuses `d_weight "3/5"` |
| `test_ac_7_4_a_corrected_type_e_finding_leaves_the_claim_and_span_sets_unchanged` | an alignment member leaking in cycle 1 only: a `re_render` correction of type E, applied, with equal set hashes |
| `test_ac_7_4_the_engine_refuses_a_re_render_that_changes_the_claim_or_span_set` | `_render` swapped on the Socratic re-render: `refused_set_changed`, abstain with `ehmf_set_changed`, a valid v4 entry, the log event; the contract refuses an applied re-render with differing sets |
| `test_ac_7_5_a_third_correction_attempt_is_refused_the_claim_abstains_and_x2_is_emitted` | NOT_ENOUGH_INFO typed C on every pair, NoCache: two cycles, cycle 3 asked and refused, `cycle_limit` logged, X2 claims abstain and are `x2_emitted`; `begin_cycle(3)` raises; the V3 scan (package v6) queues X2 though the reported type is C; the loader refuses `max_cycles 3` |
| `test_ac_7_6_a_package_edit_without_a_golden_set_run_fails_the_ci_check` | a package copy with `window_claims 201` and a library edit each exit 6 naming the pin; the committed record exits 0; a subprocess exits 6; CI holds the step; the checkout is unchanged |
| `test_ac_7_6_a_package_edit_that_keeps_its_version_is_refused_at_write` | `--write` over a copy of the committed record with a 6.0.0 package edit exits 6 (bump `package_version`) and leaves the record; the shipped package and a bumped edit pass `same_version_edit` |
| `test_ac_7_6_a_same_version_edit_fails_the_ci_check_whatever_record_is_checked` | a record re-written for a 6.0.0 package edit (its pins match) exits 6 at `--check` through the history; `--write` to a fresh path exits 6 and writes neither the record nor the history; the CI step reads the committed history, which records the shipped package; a version the history lacks, a new version not newer than the newest entry, a missing history and a duplicated entry are refused |
| `test_ac_7_6_write_appends_a_new_package_version_to_the_history` | `--write` with a bumped package appends its `(version, sha256)` to a copy of the history and pins it in the record |
| `test_ac_7_6_a_same_version_edit_hidden_by_editing_the_history_fails_the_ci_check_against_the_base` | a 6.0.0 package edit with its history entry rewritten to the edited sha256 passes `--write` and `--check` without a base, and exits 6 at both with `--base-history` (the record unchanged); an emptied history is refused at `--write`; an appended newer version keeps the base a prefix, a dropped or reordered base entry does not |
| `test_ac_7_6_the_base_ref_reads_the_committed_history_and_ci_passes_the_base_branch` | `base_history_at("HEAD")` is a prefix of the working history; an unknown ref exits 2; `--check --base-ref HEAD` exits 0; a ref without the file reads as no history; CI fetches the base branch and passes `--base-ref FETCH_HEAD` |
| `test_ac_7_6_a_package_version_that_is_not_major_minor_patch_is_a_refusal_not_a_traceback` | a package with `package_version` `6.1.0-rc1` loads, and `--write` and `--check` exit 2 naming MAJOR.MINOR.PATCH, writing neither the record nor the history |
| `test_plan_j_fixtures_per_type_are_typed_as_the_routing_table_says` | the committed golden run: each class carries its type and is not delivered (the plan's analogy fixture is the misconception class, resolution 28) |
| `test_plan_j_every_guarded_detector_has_a_detector_down_case` | the detector-down cases equal `ehmf.detectors.DETECTORS`; the string literals every `_guard`, `guarded`, `DetectorDown` (and the runner's local `guard`) call in `apps/api/app` passes are exactly `DETECTORS`, and the only other arguments are the two wrappers' own `detector`; `guarded` and `DetectorDown` refuse `V1.10` |
| `test_plan_j_detector_down_withholds_the_claim` | V1.1, V1.2, V1.3 (`check_v1_3` itself raising), V1.4 (the subset checker), V1.5 (the sufficiency check), V1.6, V1.7, V1.8 (unavailable library), V1.9, V2 and alignment raising under EHMF on: abstain `ehmf_detector_down`, the detector recorded, nothing delivered, the log event |
| `test_plan_j_a_raising_subset_checker_is_a_render_fault_only_while_ehmf_is_not_on` | under EHMF shadow a raising subset checker is a render fault: abstain `render_failed`, no detector down |
| `test_plan_j_a_raising_checker_keeps_checker_unavailable_and_off_keeps_phase_6` | a raising checker keeps `checker_unavailable` with `detector_down ("V1.3",)`; under EHMF off a raising V1.1 raises as in Phase 6 |
| `test_plan_h_the_library_holds_public_corpus_paraphrases_edited_only_by_the_content_owner_or_v3` | the shipped library is empty and not synthetic; the editor, span, copied-run and synthetic rules; the proposal export writes outside the checkout, refuses the checkout and changes no library byte |
| `test_plan_task_3_precedence_never_picks_with_incomplete_metadata` | the precedence truth table; no manifest item carries metadata; partial metadata is refused; with complete metadata a winner is recorded and the finals are unchanged |
| `test_plan_g_earlier_ledger_rows_read_as_config_version_pre_phase_7` | `config_version_of`; a chain of a 5.0.0 legacy record and two v4 records (one with other weights) verifies and exports `pre-phase-7`, `6.0.0`, `6.0.0` |
| `test_plan_g_v5_stays_readable_and_v6_parses_v1_to_v4_records` | v5 and v4 load and pass `package_check`; v6 is the default with x-triggers-v2 |
| `test_plan_i_ready_reports_config_version_and_the_ehmf_fields_and_no_count` | the 10.2 keys and values; no count or rate |
| `test_plan_i_ready_reads_the_ehmf_values_from_the_package_in_force` | `weights_provisional` and `golden_set.version` are the package's own values (a package whose values differ is reported as it is) |
| `test_plan_i_per_type_rates_disclosure_share_and_correction_cycles` | rates per 100 as exact fractions (B1 `50` over two responses) with the counts beside them, per response and claim, the exhausted cycle count and the evidence class; the Type D disclosure share `0/0` without a conflict and `n/n` over the AC-7-3 conflict run |
| `test_plan_i_a_dropped_proposal_is_a_typed_claim_in_the_per_type_rates_as_the_stop_counts_it` | the AC-7-1 negated record: `per_100_claims` A `100/N` reduced (N the claim entries plus the dropped proposal, equal to `stop._typed_counts`), `claim_type_counts` A 1, `per_100_responses` A `100`, B1 `0` |
| `test_plan_i_a_per_100_rate_over_a_zero_denominator_is_null_not_zero` | a typed record with no typed claim (a response finding without a claim id): every `per_100_claims` rate is null with `claims` 0, while `per_100_responses` E is `100` and A `0` |
| `test_plan_i_an_unreadable_stop_table_leaves_the_v3_slis_and_the_status_worker_working` | `ehmf_stops` absent on the session's dialect: V3 SLIs with EHMF off carry `ehmf` null; with EHMF shadow the stop reads `unreadable` and the later V3 queries run (the SAVEPOINT on PostgreSQL); the status worker logs its line with `stops` null |
| `test_plan_i_ready_reports_the_penalty_the_shared_index_applies` | `retrieval_penalty.active` is the store's `penalty_active`, whatever the mode is now |
| `test_plan_l_a_rising_a_b_rate_after_a_change_requires_a_revert_and_raises_the_audit_to_one_fifth` | the integer rule; seeded typed rows at 6.0.0 and 6.0.1: one stop row, `revert_required` under 6.0.1, an open window, no second row, `reverted` under 6.0.0 |
| `test_plan_l_reloading_the_prior_package_clears_the_revert_state` | a 6.0.0 -> 6.0.1 stop: the cached state is `rising_ab` (revert required) under 6.0.1 and `reverted` under the prior 6.0.0; v5 gives `not_evaluated`, and the status worker under v5 logs `ehmf.status_refused` with the stop row and exits 2; EHMF off: `not_evaluated` with no read |
| `test_plan_l_a_change_point_whose_before_window_the_scan_cut_never_fires_without_a_rise` | the shipped parameters, a constant 1/10 A/B rate across 6.0.0 -> 6.1.0: no stop at 700 records nor once the change point's window is cut (5398 records); a real rise with whole windows still fires |
| `test_plan_l_a_package_problem_stops_a_production_start_up_only_under_the_recorded_shadow_override` | production with EHMF off reports EHMF unavailable; the recorded EHMF=shadow override stops the governed start-up (`ConfigPackageError`); the docstring says so |
| `test_plan_l_ehmf_defaults_and_refusals` | defaults, `on` refused outside development, off when MODEL_GATEWAY is off, the package names the defaults, the overrides |
| `test_plan_task_5_the_span_penalty_is_inert_outside_development_and_keeps_invariant_1` | no penalty in any shipped configuration; an empty mapping equals no mapping under both gates; a penalised span is demoted with the same reason and scores; the loader refuses a staging factor of 1/2 |
| `test_plan_p_the_source_fidelity_check_reports_the_quen_transposition` | 12 DOCX, the three entries, 3 mismatches, `--check` 0, `--require-zero` 7, short strings only |
| `test_golden_set_is_public_or_synthetic_and_disjoint_from_ulqs` | Phase 4 references exist; no golden query is a ULQS question (the committed ULQS manifest holds no validated item yet, so the overlap check is also run on a seeded copy holding a golden query, which it finds); every type covered; the package pins the file |
| `test_plan_f_the_routing_document_matches_the_package` | each row of `ehmf-routing.md` equals the package table and weights; the template text |
| `test_freeze_outside_development_ehmf_is_off_and_no_learner_path_changes` | EHMF off in staging and production; the public-payload check passes; the shared index has no penalty |
| `test_the_ehmf_vocabulary_lives_in_one_module` | no A-E value tuple outside `ehmf/vocabulary.py`; the verifier prompt hash and verdict-request schema pin are v5's |
| `test_plan_e_the_phase_7_revision_is_additive_reversible_and_keeps_its_rows` | a single head after the Phase 6 revision; the downgrade's source names its guard; the append-only triggers on SQLite |
| `test_plan_e_the_phase_7_downgrade_refuses_while_ehmf_stops_holds_rows_and_the_table_refuses_truncate` | on the session's dialect with the start-up triggers: UPDATE, DELETE and (PostgreSQL) TRUNCATE refused; the downgrade to `20261122_phase6_v3_audit` refuses with a row, naming `allow_ehmf_drop=true` and the status command; with the flag it drops `ehmf_stops` only |
| `test_phase7_no_new_source_literal_starts_with_qcai_` | the Phase 7 sources (the EHMF package, the worker, the scripts and the fakes) hold no `qcai_` literal (0.1) |
| `test_phase6_docs_the_records_name_the_merge_and_the_cited_main_run` | E15 (in `test_phase6_acceptance.py`) |
| `test_phase7_docs_quote_the_plan_and_state_the_current_rules` | plan P quoted; ADR-010 quotes plan M; the runbook names `allow_ehmf_drop`; PD-40..PD-49 and DI-104..DI-114 here; conflict 7, PD-46 and DI-114 state that the revert is the operator's (D-05); the change-control doc holds the renumbering procedure |
| `test_phase7_docs_the_test_strategy_maps_every_test_module_the_phase_added` | the Phase 7 map names every test module the phase added or changed (`PHASE7_TEST_MODULES`), each existing, with what it proves, and states the exit is not passed |
| `test_phase7_spec_section_3_lists_the_code_s_fields` | the 3.3 class fields equal the code's |
| `test_phase7_docs_name_every_modified_file_and_the_ready_stop_read` | 7.3 and 7.4 name the modified routes, worker, docstrings, specs and registry doc; M17 names DI-114; `/ready`'s stop read is stated in ADR-010 and the observability runbook; 4.8 and the change-control doc describe the history, both write modes, the image-digest rollback and the renumbering steps that change tests |
| `test_phase7_docs_the_spec_ends_in_one_review_history_table` | one `## 18. Review history` table naming existing tests |

### 13.2 `apps/api/tests/test_ehmf_units.py`

The unit tests of every `ehmf/` module and of the two runner scripts are in this one module (one file per module was not needed: each test names its unit): the routing table types every non-pass V1 reason and the V1.4 split; findings are typed by failure mode and response-level results stay off claim entries; the primary order; the correction guard and the set hashes; the library pin resolved next to the package file and its sidecar; a package file copied without its `misconceptions/` folder loads the shipped library only while the pin names it, and is refused for another sha256 or version (`test_a_package_file_copied_without_its_library_folder_loads_only_the_library_its_pin_names`); every `_parse_ehmf` refusal named in 5.2 that the parametrisation lists; a later package of the shipped major loads and v5 and v4 parse; `EHMF_SCHEMA_VERSION` equals `EHMF_FIRST_MAJOR` and the shipped schema and major, and no schema rule compares with a literal (`test_the_phase_7_package_number_is_read_from_one_constant_per_side`); the stop's integer boundary; the golden runner's exits 1, 2, 3 and 4; a library proposal takes only the session and its docstring says `claim_text` is always null (`test_library_proposals_take_only_the_session_and_say_claim_text_is_always_null`); the fidelity checker's moved location (exit 2) and a corrected DOCX copy built in `tmp_path` that matches every register entry.

### 13.3 Existing tests that change (intent kept)

- `test_config_package.py`: the shipped package is v6 (schema and major `EHMF_SCHEMA_VERSION`); the v5 assertions read `V5_PACKAGE_PATH`. The v4 structural refusals run on v4, v5 and the shipped v6, and the v5 ones on v5 and v6 (but for the three edits v6 itself makes: x-triggers-v2, schema_version 6 and severity from `ehmf.weights`, counted by `test_the_v5_edits_v6_changes_are_exactly_the_three_it_makes`), each after a control load of the unedited copies; the provenance-fields refusal names v6's entry schema, ledger-entry-v4 (the loader's message now names the package's own schema version and entry schema).
- `test_v1_8_misconceptions.py`: the inline library v0 tests read package v5; `test_v6_library_file_entries_are_refused_while_q_14_is_unavailable` refuses an entry in v6's library file while Q-14 is unavailable.
- `test_phase4_acceptance.py`: the development-default shadow records are `ledger-entry-v4` (two assertions), the `/ready` library version is the package's, and the doc tests name Phase 7's v6, schema version 6 and the v6 `LedgerEntryV4` pin; the loader-bound test compares `EHMF_SCHEMA_VERSION` with the shipped package's `schema_version`, not a literal.
- `test_phase5_acceptance.py`: AC-5-6 sets `ehmf="off"` to judge its ledger-entry-v3 record; AC-5-8's bump is `ehmf_fakes.NEXT_PATCH` (the shipped package's next patch, within its major); plan G's shadow is a v4 that extends v3 (`isinstance` rather than `type is`).
- The `/ready` statement tests of Phase 3 and Phase 6: the allowed statements are the gateway-stop read and, when EHMF is not off, the ehmf-stop read; still no session and no ledger read.
- `test_phase6_acceptance.py`: the `/ready` package test reads the default package and `x-triggers-v2`; the Phase 3 rollback test names `20261123_phase7_ehmf` as the head.
- `v2_fakes.v2_pipeline` defaults to `EHMF=off`, so the Phase 5 and 6 tests keep judging the `ledger-entry-v3` they test; development-default tests that asserted `ledger-entry-v3` accept `ledger-entry-v4` (a v3 subclass).
- `v1_fakes.temp_package` copies v6 with its `misconceptions/` folder and leaves the library pin unchanged.
- `test_v2_ledger_records.py` gains `test_a_mixed_v1_to_v4_chain_verifies_exports_restores_and_reads_its_config_versions` beside Phase 5's v1-v3 chain test (E2: mixed v1-v4 chains verify, export and restore); its other tests are unchanged.
- `test_response_ledger_migrations.py`, `test_phase3_acceptance.py` and `test_phase6_acceptance.py` follow the head `20261123_phase7_ehmf`; `test_response_ledger_provenance.py` reports `config_versions`; `test_configuration_overrides.py` records `ehmf_shadow` and `ehmf_on`; `test_phase2_acceptance.py` names `LexicalIndex(penalties=...)` as not learner state.
- Unchanged, and why: `test_v3_triggers.py` keeps testing x-triggers-v1 (its default registry); v6's X2 on every exhausted claim is AC-7-5's and `test_phase6_acceptance.py`'s. `test_tutor_pipeline_package.py` and `test_database_schema.py` read the default package and the metadata, so they follow v6 and the head without an edit.

### 13.4 Mutation checks (recorded in the BEP phase record)

The B1 rule over the accepted attempt; `d_weight` "0" for disclosed; `check_re_render` and its record rule; `begin_cycle`'s raise; the pin comparison in `run_golden_set.py`; the detector guard; the library editor rule; the `metadata_incomplete` short-circuit; `config_version_of`; the penalty's `on`-only condition; the vocabulary guard. Review 1: the dropped-proposal count in `metrics.slis`; the whole-window rule in `stop.detect`; the SAVEPOINT in `stop_state`; the mode gate in `v3.metrics.slis`; the guarded subset check; `same_version_edit`; `penalty_active` on `/ready`; the downgrade's row guard; the status refusal. Review 2: `/ready`'s `weights_provisional` and golden-set version read from the package; the library pin checked on the fallback path; the schema constant in `scripts/config_package.py`; the fidelity checker's GEA rule; the export's `config_version` over a v1-v4 chain; the ULQS reader; the test-strategy map; DI-114 in the spec. Review 3: the V1.3 and V1.5 guards; the rate per 100 in `metrics.slis`; the history check in `--check`; the `_check_ehmf_package` docstring; the `proposals_from_gold` docstring; the 7.3, `/ready` and change-control texts (the Phase 4 doc test's comparison with the shipped `schema_version` is a renumbering-readiness edit, not a mutation-checked fix: with the shipped schema 6 its reverted literal cannot fail). Review 4: the base-history prefix check (`base_problem`) in `--check` and `--write`; the MAJOR.MINOR.PATCH refusal; the detector-name refusal in `guarded` and `DetectorDown`, and a guard call site renamed outside `DETECTORS`; the null rate over a zero denominator in `metrics.slis`; the runbook rollback and change-procedure texts; PD-47's current text in 16.1. Each with the test that failed is in the BEP phase record.

---

## 14. CI changes (`.github/workflows/ci.yml`, job `api-and-evaluation`)

After the Phase 6 v4 check: `python scripts/config_package.py --check --path apps/api/app/config_package/v5.json` (DI-112), `python scripts/run_golden_set.py --check docs/evaluation/phase7/golden_run_v1.json --base-ref FETCH_HEAD` after `git fetch --no-tags --depth=1 origin "$BASE_REF"` (`BASE_REF` is `github.base_ref`, else `main`) (AC-7-6; it also reads the committed package version history and requires it to start with the base branch's unchanged) and `python scripts/check_source_fidelity.py --check docs/evaluation/phase7/source_fidelity_report_v1.json` (R-18). The other jobs are unchanged; the new tests run in both API suites. The image boundary scan still finds no DOCX in the image.

---

## 15. Docs and evidence

This spec; `docs/adr/ADR-010-ehmf-operationalization.md` (Context, Decision 2026-11-23, Consequences, Residuals quoting plan M "[Risk R-16][Risk R-19][Risk R-46][Risk R-18]; residual: conflicts outside the corpus."); `docs/architecture/ehmf-routing.md` (plan F "Routing spec", the conflict template, the correction and X2 rules); `docs/architecture/ehmf-change-control.md` (plan F "change procedure", rollback, the library edit and proposal paths); `docs/evaluation/phase7/README.md`; `infra/cloudrun/deployment.md` `## Phase 7: EHMF operationalization (runbook)`; `infra/cloudrun/observability.md` `## Phase 7 SLIs: EHMF (plan Phase 7 I)`; `docs/testing/test-strategy.md` `## Phase 7 acceptance map (plan Phase 7 K)`; the BEP phase record, closure notes, registers, STATUS row and `check_records.py` Phase 7 checks.

---

## 16. Provisional defaults and deferred items

### 16.1 Provisional defaults

| # | Decision | Plan text | Default applied | Where |
|---|---|---|---|---|
| PD-40 | EHMF routing table v1 and per-finding typing (no owner decision names the mapping; engineering parameters like PD-32) | Task 1: "Detectors per [VBT RevB: p. 12, Sec. VI-B, Table IX]. Mitigations: A revise or abstain; B span-id citation, B1 final; C bind step or label analogy; D precedence plus disclosure; E regenerate pedagogical pass. Owners: ML Engineer (A, B, E), Content Owner (C, D)." | `ehmf-routing-v1`: each failing V1 result and each objecting V2 family verdict is one finding typed by `FINDING_RULES` (V1.1 and V1.2 unresolvable B1; the other V1.2 drops and a V1.3 or V2 contradiction A; V1.3 not-enough-info or below threshold and V2 NOT_ENOUGH_INFO B2; V1.4 unmapped factual sentence D, other V1.4 codes E; V1.5 A; V1.6 E; V1.7 D; V1.8 C; V1.9 and alignment leakage E). The verifier's own type is recorded, never decisive; a claim's primary type is its heaviest, ties B1, A, B2, D, C, E; a record is validated against its own routing version. Engineering parameters (no plan value; Claude's, ratified under DI-109): the finding rules per reason, the V1.4 split, the primary order, the response/claim scoping and the telemetry keys. The plan's values are the five types, the mitigations, B1 final and the owners. | v6 `ehmf.routing`; `ehmf/routing.py`, `classify.py` |
| PD-41 | EHMF weights (PI OPEN decision) | O: "OPEN DECISION: EHMF weight values (expert elicitation) owned by the Principal Investigator [Evidence E-88]." | A 1.0, B 1.0 (B1 and B2 alike), C 0.6, D 0.6, D disclosed 0, E 0.4, unknown 1.0, bound by the loader while the decision is open; used for V3 severity and a claim's primary weight; each typed record stores the weights it used. Engineering parameters (no plan value; Claude's, ratified under DI-109): B1 and B2 weighing B, and the unknown weight 1.0. The plan's values are the six weights. | v6 `ehmf.weights`, `owner_decisions.EHMF-WEIGHTS` |
| PD-42 | Conflict precedence and the disclosure template | Task 3: "Conflicts: newer peer-reviewed over older, primary over secondary [Evidence E-79]." | `precedence-v1` names a winner only when both items carry complete Content-Owner metadata (year, peer review, role); the newer of two peer-reviewed sources wins; a primary source wins over a secondary one; disagreeing or no rules name no winner. Recorded only (DI-111). Every detected conflict is disclosed with both spans (template `conflict-disclosure-v2`: kinds and public item ids, no span text) and weighs 0. Metadata is never inferred. Engineering parameters (no plan value; Claude's, ratified under DI-109): the metadata fields, the incomplete and disagree rules, recording-only, and the template text. The plan's values are the two precedence rules and "D weighs 0" when disclosed. | v6 `ehmf.conflicts`; `ehmf/conflicts.py`; manifest fields |
| PD-43 | Misconception library v1 (Q-14 unavailable, A-18) | Task 2: "Versioned misconception library, edited only by Content Owner or V3 [VBT RevB: p. 10, Table VIII, V1.8]." | A hashed file (`misconception-library-v1`) the package pins (resolved next to the package file), with zero production entries; an entry's editor is `content_owner` or `v3:<gold record hash>`, its spans resolve in the public corpus, its paraphrase is at most 280 characters and shares no run of more than 8 words with a cited span, and an entry from V3 holds no label or reviewer data. V3 Type C labels are exported as proposals and never applied. Engineering parameters (no plan value; Claude's, ratified under DI-109): the file format, the 280-character and 8-word limits, and the proposal format. The plan's values are versioning, the two editors and public paraphrases only. | `config_package/misconceptions/v1.json`; `ehmf/library.py`, `workers/ehmf.py` |
| PD-44 | Correction and X2 (x-triggers-v2) | Task 4: "Correction: at most two cycles, then abstain and raise X2 [Evidence E-82]." | At most two cycles: the guard is the loop's only bound and refuses a third, and the record contracts refuse one too. Every exhausted claim abstains with X2 whatever its type, and V3's X2 fires on every one (x-triggers-v2; severity still ranks A and B first). A Type E correction re-renders the same candidate; a re-render that changes the claim or span set is refused and the response abstains (`ehmf_set_changed`). Engineering parameters (no plan value; Claude's, ratified under DI-109): the registry `x-triggers-v2`, the set hashes and the refusal rule. The plan's values are two cycles, abstain and X2 (X2 for every type is the reading of L1520 and AC-7-5 over Phase 6's L1455, spec conflict 3). | v6 `ehmf.correction`, `v3.triggers`; `ehmf/correction.py`, `v1_checks/runner.py`, `v3/triggers.py` |
| PD-45 | The B2/D span penalty (D-06 operator policy) | Task 5: "B2/D spans lose retrieval priority [VBT RevB: p. 12, Sec. VI-D]; penalty is operator policy [Decision D-06]." | Ranking only, never the floor or abstention, and only under `EHMF=on`; factor 1 outside development and 1/2 in development; every span list empty until an applied V3 gold label is added through change control (DI-113). Engineering parameters (no plan value; Claude's, ratified under DI-109): the development factor 1/2, the rank-only rule and the `on`-only condition. The plan gives no value. | v6 `ehmf.retrieval_penalty`; `lexical_index.py`, `content_assembler.py` |
| PD-46 | The rising A/B stop (plan L; D-06) | L: "Reload the prior package. Stop: a rising A/B rate after a change reverts it and sets audit to 20%." | After a configuration-version change, the A/B claims among the first 200 typed claims of the new version against those among the last 200 of the old, over the last 5000 typed records; active at 100 or more new claims, at least 2 A/B claims and a rate above 3/2 of the old. It raises the audit draw to 1/5 for the next 1500 learner deliveries and reports "revert required" until the prior package is reloaded (an operator action). Nothing reverts automatically (D-05; DI-114). Engineering parameters (no plan value; Claude's, ratified under DI-109): the windows, the scan bound, the minimums and the 3/2 rise. The plan's values are the 20% audit and the revert, which is the operator's here: an automatic revert would be a production configuration write (D-05; DI-114). | v6 `ehmf.stop`; `ehmf/stop.py`, table `ehmf_stops` |
| PD-47 | Golden set v1 and the change procedure | Task 6: "each change passes the Stage 11 golden-set gate [VBT RevB: p. 8, Sec. IV-D]." | 40 public-corpus or synthetic items covering every type and subtype; a committed run record pins the package, library, routing and golden-set hashes; CI fails on a pin mismatch (exit 6), an unmet expectation or an unresolved delivered citation (exit 3), and drift (exit 1). CI also fails (exit 6) on a package edit that keeps its `package_version` (config_version is the package version, and the rising-A/B stop sees a change only where it differs) and on a package version history (`docs/evaluation/phase7/package_versions.json`, append-only) that does not start with the base branch's history unchanged (`--check --base-ref FETCH_HEAD`). The procedure: edit, bump `package_version`, rehash, rerun, commit the record and the history in the same PR, CI green, review approval; rollback is reloading the prior package, which is the prior 6.x package in the prior image: the operator deploys the prior image digest (no separate package file is kept). Engineering parameters (no plan value; Claude's, ratified under DI-109): the 40 items and their expectations, the exit codes, the version-bump rule, and the append-only history with its base-branch check. The plan's values are public or synthetic text, ULQS disjointness, hashing, rerun on change, drift blocking and 100% resolution. | `docs/evaluation/phase7/golden_set_v1.json`, `scripts/run_golden_set.py`, `docs/architecture/ehmf-change-control.md` |
| PD-48 | `EHMF` (freeze, D-05) | L: "Reload the prior package."; 13.6: "Flags per feature" | Development `shadow`, elsewhere `off`; `on` refused outside development before `phase7_exit_passed`; effectively off whenever the V2 mode is off; shadow records typing; `on` adds the detector guard and the span penalty; nothing reaches a learner. Engineering parameters (no plan value; Claude's, ratified under DI-109): the three values and their defaults. | `config.py`; v6 `flag_policy.ehmf` |
| PD-49 | The source-fidelity register and check (D-16 REC, CO; Q-11 open) | F-7: "Remedy: source-fidelity CI check; media fingerprint gate." | A committed register seeded only with the plan's facts (QUEN External Sens. and FP Rate, and the "perfectly aligned" wording against GEA = 0.40); a read-only checker over the 12 tracked DOCX writes a committed report (3 mismatches); CI runs `--check`; `--require-zero` waits for the Content Owner's correction (DI-105); engineering edits no DOCX. Engineering parameters (no plan value; Claude's, ratified under DI-109): the register format, the measured table and paragraph locations, and the exit codes. The plan's values are the three facts and the 12-DOCX scope. | `scripts/check_source_fidelity.py`, `docs/evaluation/phase7/source_fidelity_*.json`; v6 `owner_decisions.D-16`, `Q-11` |

### 16.2 Deferred items

| # | Item | Who | State |
|---|---|---|---|
| DI-104 | The Phase 7 exit (plan P: "AC-7-1 to AC-7-6 green; package v1 hash in the ledger; R-18 closure evidence in Section 5: corrected DOCX values and the source-fidelity CI job over the 12 DOCX passing (Phase 11 task 3 and AC-11-3 brought forward to this exit)."). It needs AC-7-1..AC-7-6 green in a cited CI run on `main`. "Package v1 hash in the ledger" is read as the v6 hash stamped by every record from the Phase 7 release (conflict 4); none is deployed. `phase7_exit_passed` stays false while R-18 is open (DI-105), the EHMF weights are not elicited (DI-108) and the Phase 6 exit is not passed (DI-89). Blocked by: the Content Owner's correction at source (D-16, DI-105); the OPEN PI decision on the weights (DI-108); a production release under D-05; and the Phase 6 exit, itself blocked by OPEN owner decisions (DI-89). | Eng / PI / CO | Open |
| DI-105 | R-18 closure and AC-11-3: correct the QUEN row (External Sens. 0.828, External FP Rate 1.143) and the "perfectly aligned" wording (GEA = 0.40) in `Quantum Computing AI Research Synthesis 2026.docx` at source; then add `check_source_fidelity.py --require-zero` to CI, and answer Q-11 (other DOCX-source discrepancies). Engineering edits no DOCX (D-16, D-31). Blocked by: the Content Owner's correction (D-16) and Q-11 (CO, RL). | CO / RL, then Eng | Open |
| DI-106 | Q-14 (A-18): the misconception seed list, and the library v1 entries the Content Owner writes from it. Library v1 ships with no production entries, so V1.8 matches nothing outside tests. Blocked by: the PI supplying the supplementary package (A-18), and the Content Owner's entries. | PI / CO | Open |
| DI-107 | Source metadata (`source_year`, `peer_reviewed`, `source_role`) for each corpus item, so that precedence-v1 can order conflicting spans (E-79). Until it is supplied, every conflict is disclosed with both spans and no winner. Blocked by: the Content Owner's facts about the licensed sources (with D-02 and D-31). | CO | Open |
| DI-108 | The EHMF weight values (plan O: "OPEN DECISION: EHMF weight values (expert elicitation) owned by the Principal Investigator [Evidence E-88]"). The plan's 6.3 values are applied provisionally (PD-41). Blocked by: the OPEN PI decision (expert elicitation; with D-06, and D-08 for the experts). | PI | Open |
| DI-109 | Ratify PD-40..PD-49, including D-06's operator values (the span-penalty factor, and the stop's windows and rise). Blocked by: owner decisions (PI, PO; D-06 OPEN). | PI / PO | Open |
| DI-110 | The Phase 7 log-based metrics and alerts (per-type rates, the Type D disclosure share, correction cycles, X2 emissions, the stop), and a scheduled `python -m app.workers.ehmf status` job. Blocked by: a cloud write under D-05. | PfO | Defined, not created |
| DI-111 | Learner-facing and production EHMF behaviour: the conflict disclosure shown to learners; the Type C "label analogy"; applying precedence-v1 to delivered content; the detector guard and the set rule on the delivered two-pass path; typed records outside development, without which the rising-A/B stop cannot fire in production. Blocked by: learner-facing capability outside development (D-05), the Phase 5 exit (DI-74) and the delivered path (DI-59, DI-85). | PO, then Eng | Deferred |
| DI-112 | Remove configuration package v5 after one release, with its CI step and package_check's v4/v5 entry-schema lists. Blocked by: a production release under D-05. | Eng | Deferred |
| DI-113 | Apply V3 gold labels through Phase 7 change control: Type C proposals into the library, and B2/D spans into the penalty lists (with DI-93). Phase 7 builds the procedure, the proposal export and the penalty hook; nothing is applied. Blocked by: the OPEN owner decision D-18 (no gold label exists outside development without a staffed pool, DI-91) and D-06 (penalty values). | MLE / CO, then PI | Deferred |
| DI-114 | Plan L's automatic revert ("Reload the prior package. Stop: a rising A/B rate after a change reverts it and sets audit to 20%."). The stop raises the audit draw to 1/5 and reports "revert required" on `/ready`, in the log and in `ehmf status`; reloading the prior package is the operator's (runbook, `ehmf-change-control.md`). Blocked by: a production configuration write under D-05 (nothing may change production configuration automatically), and typed records outside development (DI-111). | PfO, then Eng | Deferred |

### 16.3 Rows of other phases that Phase 7 advances

Unchanged (the registers never edit other phases' rows), except the sanctioned E15 edit of DI-89: DI-93 (Phase 7 builds the procedure and the proposal export; DI-113 carries the rest), DI-53 (DI-106 carries the library gap), DI-89 (the merge facts).

---

## 17. Verification, work order and exit

**Work order.** (1) E15: the Phase 6 records after the merge, a separate first commit (docs and one test; the BEP DI-89 row and `check_records.py`). (2) The build with its tests, records, docs, CI and the changed tests. (3) Review rounds, each in its own commits.

**Commands** (`<py>` is the scratch venv's python): the full API suite; `validate_corpus.py --check-public-assets --check-recall-stop`; `validate_lqs.py --allow-draft`; `config_package.py --check` (and `--path` v5, v4, v3, v2, v1); `run_golden_set.py --check`; `check_source_fidelity.py --check`; `run_v1_fixtures.py --check`; `run_v2_fixtures.py --check`; `run_v3_residual_report.py --check`; `capture_public_payloads.py --check`; `authorization_matrix.py --check`; `replay_tutor_plans.py --check`; `generate_manifest.py --check`; `validate_corpus.py --check-hashes --check-near-duplicates`; `calibrate_abstention.py --check`; `scan_boundary.py`; the BEP `check_records.py`; `git status --short`. A scratch PostgreSQL 17 cluster in the scratchpad on port 57433 (never 55024-55623 or the installed server's data directory) runs the suite under psycopg and pg8000 and is stopped at the end.

**Exit (plan P).**
- Plan P: "AC-7-1 to AC-7-6 green; package v1 hash in the ledger; R-18 closure evidence in Section 5: corrected DOCX values and the source-fidelity CI job over the 12 DOCX passing (Phase 11 task 3 and AC-11-3 brought forward to this exit)."
- The AC tests are done in code. The branch push run 45234227899 (cs595-quality-gates) at `f381989` passed every job (api-and-evaluation, frontend, api-postgres under psycopg and pg8000 and their aggregate, api-image-boundary-scan; release-artifacts skipped by design). Each later commit needs its own run; the cited run must be on `main` after the merge (DI-104).
- R-18 is not closed: the DOCX values are the Content Owner's to correct (D-16, DI-105), and the CI job runs `--check` with 3 mismatches, not `--require-zero`.
- The EHMF weights await the PI (DI-108). The Phase 6 exit is not passed (DI-89).
- `phase7_exit_passed` stays `false`. The exit is not passed.

---

## 18. Review history

The rows below record what each round fixed, in order. They may describe behaviour that a later round superseded; sections 0-17 are authoritative. Each finding is one line naming the tests that fail if its defect comes back.

| Round | Commit | Findings fixed (one line each, with their tests) |
|---|---|---|
| Spec (pre-code) | — (sections 0-17) | The design: `test_ac_7_1_a_negated_claim_fixture_is_tagged_type_a_and_not_delivered`, `test_ac_7_2_an_unresolvable_citation_is_b1_final_whatever_the_votes_or_a_gold_label`, `test_ac_7_3_contradicting_spans_are_disclosed_and_the_disclosed_conflict_weighs_zero`, `test_ac_7_4_a_corrected_type_e_finding_leaves_the_claim_and_span_sets_unchanged`, `test_ac_7_5_a_third_correction_attempt_is_refused_the_claim_abstains_and_x2_is_emitted`, `test_ac_7_6_a_package_edit_without_a_golden_set_run_fails_the_ci_check` |
| Spec review (pre-code) | — (sections 0-17) | V1.1 judges the candidate whole, so the B1 rule reads the accepted attempt: `test_ac_7_2_an_unresolvable_citation_is_b1_final_whatever_the_votes_or_a_gold_label`<br>Response-level results stay out of claim entries: `test_ehmf_units.py`<br>A set-changing re-render abstains the response: `test_ac_7_4_the_engine_refuses_a_re_render_that_changes_the_claim_or_span_set`<br>The correction guard is the loop's only bound: `test_ac_7_5_a_third_correction_attempt_is_refused_the_claim_abstains_and_x2_is_emitted`<br>package_check's entry-schema list depends on the schema version: `test_plan_g_v5_stays_readable_and_v6_parses_v1_to_v4_records`<br>The library pin resolves next to the package file: `test_ac_7_6_a_package_edit_without_a_golden_set_run_fails_the_ci_check`<br>v4 records validate against their own weights: `test_plan_g_earlier_ledger_rows_read_as_config_version_pre_phase_7`<br>The penalty acts under `on` only: `test_plan_task_5_the_span_penalty_is_inert_outside_development_and_keeps_invariant_1`<br>Precedence is recorded only: `test_plan_task_3_precedence_never_picks_with_incomplete_metadata` |
| Build | the commit after `31343c8` | The Phase 4 conflict_negation cases are check-level, so AC-7-3 and the golden conflict items use the pipeline-level conflict_version cases (conflict 10): `test_ac_7_3_contradicting_spans_are_disclosed_and_the_disclosed_conflict_weighs_zero`<br>A Phase 4 golden item's delivered rule is its own (conflict 25), and leakage on every render exhausts the cycles (conflict 26): `test_plan_j_fixtures_per_type_are_typed_as_the_routing_table_says`<br>The golden runner restores the `qcai` log level after an in-process call, which had silenced later log-capture tests: `test_the_golden_runner_exits_on_drift_dirty_and_unmet`<br>The penalty's `on`-only condition is proven with a penalised development span: `test_plan_task_5_the_span_penalty_is_inert_outside_development_and_keeps_invariant_1` |
| Review 1 | the commit after `c8a1981` | A dropped proposal (V1.2, such as AC-7-1's negated claim) is a typed claim in the per-type SLIs, as the stop counts it: `test_plan_i_a_dropped_proposal_is_a_typed_claim_in_the_per_type_rates_as_the_stop_counts_it`<br>A package edit that keeps `package_version` is refused at `--write` (the stop sees a change only where the version differs): `test_ac_7_6_a_package_edit_that_keeps_its_version_is_refused_at_write`<br>A raising subset checker under EHMF on is `DetectorDown("V1.4")`, and V1.2, V1.6 and V1.9 are tested down too: `test_plan_j_detector_down_withholds_the_claim`, `test_plan_j_a_raising_subset_checker_is_a_render_fault_only_while_ehmf_is_not_on`<br>The Type D disclosure share is tested: `test_plan_i_per_type_rates_disclosure_share_and_correction_cycles`<br>The two test names hold what they promise (a gold label leaves the B1 record final; the prior 6.x package clears the revert state): `test_ac_7_2_an_unresolvable_citation_is_b1_final_whatever_the_votes_or_a_gold_label`, `test_plan_l_reloading_the_prior_package_clears_the_revert_state`<br>The plan's analogy fixture is the misconception class (resolution 28): `test_plan_j_fixtures_per_type_are_typed_as_the_routing_table_says`<br>A change point whose before-window the scan cut is skipped, never fired: `test_plan_l_a_change_point_whose_before_window_the_scan_cut_never_fires_without_a_rise`<br>The stop read runs in a SAVEPOINT on PostgreSQL, and the V3 SLIs read EHMF only when it is not off: `test_plan_i_an_unreadable_stop_table_leaves_the_v3_slis_and_the_status_worker_working`<br>`/ready` reports the penalty the index applies: `test_plan_i_ready_reports_the_penalty_the_shared_index_applies`<br>The runbook's revert names the prior 6.x package, and `status` under v5 logs the stops and exits 2: `test_plan_l_reloading_the_prior_package_clears_the_revert_state`<br>The downgrade guard and TRUNCATE are run: `test_plan_e_the_phase_7_downgrade_refuses_while_ehmf_stops_holds_rows_and_the_table_refuses_truncate`<br>The BEP phase record states the run figures and the mutation outcomes; 13.3 and the test strategy name the changed modules; the golden-run procedure states `--allow-dirty`; ADR-010 expands EHMF as the plan does; the observability doc lists every stop state and the status refusal: `test_phase7_docs_the_spec_ends_in_one_review_history_table`<br>No Phase 7 source literal starts with `qcai_`: `test_phase7_no_new_source_literal_starts_with_qcai_`<br>The structural refusals run on the shipped v6 again, and a v6 library entry is refused while Q-14 is unavailable: `test_v4_structural_errors_always_stop_the_load`, `test_v5_structural_errors_always_stop_the_load`, `test_the_v5_edits_v6_changes_are_exactly_the_three_it_makes`, `test_v6_library_file_entries_are_refused_while_q_14_is_unavailable` |
| Review 2 | the commits after `f381989` | Plan L's automatic revert is recorded as not implemented (conflict 7, DI-114) and PD-46 calls the revert the operator's; PD-44 names conflict 3: `test_phase7_docs_quote_the_plan_and_state_the_current_rules`<br>`/ready` reads `weights_provisional` and the golden-set version from the package in force: `test_plan_i_ready_reads_the_ehmf_values_from_the_package_in_force`<br>A package file copied without its library folder loads the shipped library only while the pin names it: `test_a_package_file_copied_without_its_library_folder_loads_only_the_library_its_pin_names`<br>The corrected DOCX copy must match every register entry (the test had accepted a GEA mismatch): `test_the_fidelity_checker_refuses_a_moved_location_and_matches_a_corrected_copy`<br>Mixed v1-v4 chains restore as well as verify and export (E2): `test_a_mixed_v1_to_v4_chain_verifies_exports_restores_and_reads_its_config_versions`<br>The ULQS disjointness check is proven on a seeded manifest (the committed ULQS holds no item): `test_golden_set_is_public_or_synthetic_and_disjoint_from_ulqs`<br>The test-strategy map names every module the phase added or changed: `test_phase7_docs_the_test_strategy_maps_every_test_module_the_phase_added`<br>The Phase 7 package number is one constant per side (`EHMF_SCHEMA_VERSION`, `EHMF_FIRST_MAJOR`), tests read the shipped version, and the change-control doc holds the renumbering procedure (E16): `test_the_phase_7_package_number_is_read_from_one_constant_per_side`, `test_phase7_docs_quote_the_plan_and_state_the_current_rules`<br>13.2 names the one unit-test module, and 3.7 states the golden-run record's informational `commit` and its `inputs` rule: `test_phase7_docs_quote_the_plan_and_state_the_current_rules` |
| Review 3 | the commit after `3df0dd9` | A fault inside `check_v1_3` (outside the checker call) is tested down under its guard: `test_plan_j_detector_down_withholds_the_claim` (V1.3)<br>V1.5's sufficiency check is guarded and named in `DETECTORS` and R-c, and the detector-down cases equal `DETECTORS`: `test_plan_j_detector_down_withholds_the_claim` (V1.5), `test_plan_j_every_guarded_detector_has_a_detector_down_case`<br>`per_100_claims` and `per_100_responses` hold the rate per 100 (`100*k/n`, exact), with `claim_type_counts` and `response_type_counts` beside them: `test_plan_i_per_type_rates_disclosure_share_and_correction_cycles`, `test_plan_i_a_dropped_proposal_is_a_typed_claim_in_the_per_type_rates_as_the_stop_counts_it`<br>`--check` (the CI step) refuses a package edit that keeps its `package_version`, whatever record is checked, through the committed append-only package version history: `test_ac_7_6_a_same_version_edit_fails_the_ci_check_whatever_record_is_checked`, `test_ac_7_6_write_appends_a_new_package_version_to_the_history`<br>`proposals_from_gold` takes only the session and its docstring says `claim_text` is always null: `test_library_proposals_take_only_the_session_and_say_claim_text_is_always_null`<br>The renumbering procedure names the doc tests that quote the number, says `SCHEMA_REVISION` is unchanged, and the Phase 4 loader-bound test compares with the shipped `schema_version` (two reports of one finding, and a third of the same): `test_phase7_docs_name_every_modified_file_and_the_ready_stop_read`<br>Spec 4.8 and the change-control doc describe both write modes and the committed record (written with `--allow-dirty`, naming `3df0dd9` with `-dirty`): `test_phase7_docs_name_every_modified_file_and_the_ready_stop_read`<br>7.3 and 7.4 name every modified file (`routes/v3.py`, `workers/v3_queue.py`, two docstrings, the Phase 3 and 4 specs, `v3-trigger-registry.md`): `test_phase7_docs_name_every_modified_file_and_the_ready_stop_read`<br>M17 names DI-104..DI-114: `test_phase7_docs_name_every_modified_file_and_the_ready_stop_read`<br>Rollback reloads the prior package by deploying the prior image digest (no prior 6.x file is kept): `test_phase7_docs_name_every_modified_file_and_the_ready_stop_read`<br>ADR-010 and the observability runbook state `/ready`'s cached stop read: `test_phase7_docs_name_every_modified_file_and_the_ready_stop_read`<br>The `_check_ehmf_package` docstring says a recorded EHMF=shadow override stops a governed start-up with a package problem: `test_plan_l_a_package_problem_stops_a_production_start_up_only_under_the_recorded_shadow_override` |
| Review 4 | the commit after `51f4ba0` | The package version history is append-only against the base branch: `--check --base-ref FETCH_HEAD` in CI (and `--write` with a base) refuses a history whose base entries are rewritten or removed, so a same-version edit hidden by editing the history fails (three reports of one finding, and a fourth of the same): `test_ac_7_6_a_same_version_edit_hidden_by_editing_the_history_fails_the_ci_check_against_the_base`, `test_ac_7_6_the_base_ref_reads_the_committed_history_and_ci_passes_the_base_branch`<br>A `package_version` that is not MAJOR.MINOR.PATCH is a refusal (exit 2) in both modes, not a traceback: `test_ac_7_6_a_package_version_that_is_not_major_minor_patch_is_a_refusal_not_a_traceback`<br>`guarded` and `DetectorDown` refuse a name outside `DETECTORS`, and the guard call sites' names equal `DETECTORS`: `test_plan_j_every_guarded_detector_has_a_detector_down_case`<br>A per-100 rate over a zero denominator is null: `test_plan_i_a_per_100_rate_over_a_zero_denominator_is_null_not_zero`<br>The deployment runbook's rollback reaches the prior 6.x package by the prior image digest only (a prior Phase 7 image reads `ehmf_stops`), and its change procedure commits the history: `test_phase7_docs_name_every_modified_file_and_the_ready_stop_read`<br>The renumbering step is the one sanctioned hand edit of the history (README, procedure step 3): `test_phase7_docs_name_every_modified_file_and_the_ready_stop_read`<br>13.4 no longer lists the shipped-schema comparison as a mutation-checked fix: `test_phase7_docs_name_every_modified_file_and_the_ready_stop_read`<br>PD-47's current text states the version-bump rule, the history and the image-digest rollback (BEP register; no repository test)<br>The `v3.metrics` docstring describes the per-100 rates: `test_phase7_docs_name_every_modified_file_and_the_ready_stop_read`<br>The BEP phase record and closure notes name the review-3 and review-4 trees (BEP records; no repository test) |
| Review 4 (final check) | the commit after `c92a222` | PD-47's current text in 16.1 (which the BEP register holds verbatim) states the same-version refusal, the append-only history with its base-branch check, the procedure that commits the record and the history, rollback by the prior image digest, and the version-bump rule and the history as engineering parameters: `test_phase7_docs_pd_47_states_the_version_bump_rule_the_history_and_the_image_digest_rollback` (and, for the register and the BEP records, `check_records.py`'s `check_p7_r4_*` checks)<br>The BEP phase record and closure notes name every branch commit, every commit after `f381989` as needing its own CI run, and the tree the latest verification ran on (`check_records.py`'s `check_p7_r4_*` checks; BEP records, outside the repository) |
