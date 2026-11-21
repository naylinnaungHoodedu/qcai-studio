# QC+AI Studio — Phase 4 Implementation Spec
## V1 deterministic validation (plan L1286-1355)

- **Repository:** `D:\QC_AI_Studio\Codex_Webapp_QC_AI_Studio`.
- **Branch:** `phase4/v1-validation`, cut from `origin/main` `078bc75` (Phase 3 merged, PR #35).
- **Plan:** `D:\QC_AI_Studio\QC_AI_Studio_Ultimate_Software_Upgrade_Plan.txt`.
  - Phase 4 block: L1286-1355.
  - Section 7: L811-983 (pipeline L832-852; VerificationVerdict L894-902; invariants L960-978).
  - 13.6: L2365-2385. 18.3/18.4: L2960-3026. Holds: L1904-1926.

Sections 0-17 describe the behaviour the code has. They are authoritative and are kept current in place (P2-12-D-03). Section 18 holds one history-table row per review round.

---

## 0. Ground rules, measured facts, readings

### 0.1 Binding constraints (unchanged from Phase 3 0.1)

**Git**
- Stay on the branch: no branch switch, no `git stash`, no push, no history rewrite, no git-config change.
- Commits end with a blank line, then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Temporary files go only in the scratchpad; nothing is written to the repository root.

**Forbidden reads and calls**
- Never open `infra/cloudrun/*.env.yaml`, `apps/frontend/.env.local` or any `.env` file. The `*.env.example.yaml` files may be edited.
- No cloud, gcloud, gh, provider or LLM calls.

**Freeze (D-05) and containment**
- D-05 is not lifted. Nothing adds learner-facing capability outside development unless it is strictly more conservative.
- D-31: zero assets are approved.
- D-19 containment is unchanged (`contained_answers.contain_answer` stays byte-for-byte). R1.2 withholding is unchanged.
- Production `/assistant/chat` and `/qa/ask` bodies keep today's keys and values.

**Privacy**
- No learner text, user id, email, response id, turn id, thread id or message id goes into logs or V1 verdicts.
- Tests use uuid4 demo ids.
- No new source literal matches `qcai_[a-z0-9_]+`.

**Tests**
- No existing test or guard is weakened, and no test may keep passing for a reason other than its intent (13.3).
- No new skip or xfail.
- Each changed test keeps its intent, and its commit message says why.
- Each fix is mutation-checked: revert it, see a test fail, restore it byte for byte.
- One test module per feature. AC tests go in `test_phase4_acceptance.py`. No per-round files.

**Phase 3 doc-text and listing guards.** New Phase 4 text in the regions Phase 3 tests scan must pass them.
- `test_phase3_docs.py::test_k3_the_authoritative_text_states_the_current_code_only` applies its NARRATIVE regex to every `apps/api/app/**/*.py`, `apps/api/alembic/**/*.py` and `scripts/*.py`; ADR-001 and ADR-005 after `## Revision 2026-11-19`; `deployment.md` and `observability.md` after `## Phase 3`; and the test strategy after `## Phase 3 acceptance map`. The evidence package's `00_meta/check_records.py` (`check_k3_*`) applies it to the BEP register rows `PD-08..PD-12` and `DI-31..DI-59`, which includes Phase 4's DI-52..DI-59. `test_phase4_docs_the_spec_ends_in_one_review_history_table` applies the same regex to sections 0-17 of this spec, and refuses a review-round reference there. So no Phase 4 text uses a phrase that regex names.
- `test_phase3_docs.py::test_k3_spec_section_3_lists_the_code_s_fields` requires every class that the Phase 3 spec's section 3 lists in full to equal the code. The only Phase 3 class whose fields Phase 4 changes is `EvidencePanel` (3.4); its Phase 3 spec listing carries the `conflicts` line (7.14).
- `test_phase3_docs.py::test_d7_the_records_say_what_the_code_does` forbids "NFKC normalisation" anywhere in ADR-005.
- `test_phase3_docs.py::test_l5_the_adr_005_revision_withdraws_the_overlap_gate_and_keeps_fail_closed_abstention`: ADR-005's first `## Decision` section stays the original overlap decision; the first line starting "The " after `## Revision 2026-11-19` stays the Phase 3 opening; the revision text does not contain "stands as first written".
- `test_phase3_docs.py::test_i1_the_records_name_both_reasons` needs every non-gate `ABSTENTION_REASONS` value in ADR-005 after `## Revision 2026-11-19 (Phase 3)` and the Phase 3 spec's `ABSTENTION_REASONS` listing to equal the code. So `ABSTENTION_REASONS` is not extended (3.1).

### 0.2 Measured facts (measured on `078bc75`, 2026-11-20; M7's legacy count on the branch)

Unless stated otherwise, measurements use `all_public_approved` (a temporary manifest approving every public-plane bound item) and the fixture `apps/api/tests/data/score_floor_queries.json` (174 in-domain, 100 off-topic, 24 stopword-only). The fixture runner (section 12) reproduces M1, M2 and M6 on every run. The code and data the other facts measure are unchanged on the branch.

**M1. V1.5 answer rate under the Phase 2 definition.** The definition (`calibration_record_v1.json` `metric_definitions.answer_rate`) is: "share of in-domain queries with >= 1 document span among the top 4 survivors (all-approved configuration)". The record's `answer_rate` is computed over all 174 in-domain items; it has no per-fold value.

| Gate | V1.5 answer rate (fixture report) | Phase 2 baseline (`answer_rate`) |
|---|---|---|
| `bm25f-v1` | 166/174 | `"bm25": "166/174"` (Wilson95 [0.9119, 0.9765]) |
| `p1-floor` | 146/174 | `"p1_floor_span_index": "146/174"` (Wilson95 [0.7773, 0.8863]) |

- 166/174 = 0.954022988…; 146/174 = 0.839080459…. Floors are therefore stored as counts, never as rounded decimals (5.1).
- Off-topic and stopword: 124 of 124 abstain under V1.5 for both gates.

**M2. Two-pass composition.**

| Gate | Answered in-domain, V1 off | V1 enforce, checker (b) | V1 enforce, checker (a), not abstaining | Items identical (decision, claim_set_hash, rendered hash) |
|---|---|---|---|---|
| `bm25f-v1` | 147/174 | 147/174 | 147/174 | 174/174 |
| `p1-floor` | 129/174 | 129/174 | 129/174 | 174/174 |

- Abstention reasons with V1 off (`bm25f-v1`): `insufficient_coverage` 8, `no_whole_sentence` 11, `no_claims` 8; (`p1-floor`): `below_floor` 28, `no_whole_sentence` 13, `no_claims` 4.
- 0 answers cite both `analyzing-quantum-computing-and-ai-paper-2025` and `quantum-computing-ai-research-synthesis-2026`; four synthetic keyword queries put spans of both in one envelope (used by `conflict_version`, 12.1).

**M3. Quiz keys.**
- 12 lessons hold 12 quiz items: 6 `mcq` and 6 `short-answer`. Ids are `{lesson_slug}-quiz-{n}`.
- Every mcq answer equals one of its choices. Every short-answer explanation equals its answer.
- No key or explanation text appears in any other field of any public lesson or course payload, in any public span of the corpus, or in any rendered fixture answer (`test_v1_6_keyed_answers`).

**M4. Public payloads that carried keys** (main `078bc75`).
- `GET /content/lessons/{slug}` (`LessonDetail`) carried `quiz_questions[].answer` and `explanation`; `GET /content/modules/{slug}` serialised the same objects.
- `apps/frontend/src/components/quiz-panel.tsx` scored against `question.answer` and showed "Model answer" on "Reveal rubric" before any attempt; `src/app/quiz/[lessonSlug]/page.tsx` passed the whole `lesson.quiz_questions` (cached publicly) into that client component.
- The Arena's `round_result` reveals the accepted answer after a round. The Arena is off outside development (D-03) and out of scope.

**M5. Assessment-context similarity.** The measure is `max(Jaccard, prompt containment)` over alignment terms. 8 of 174 in-domain items match a quiz item at threshold 0.6 (verbatim prompts); 0 of 124 off-topic and stopword items do (`test_v1_6_keyed_answers`).

**M6. Readability (`fk-grade-segments-v1`).** Over the corpus's whole sentences plus the renderer templates, the component envelope (minimum and maximum words per sentence and syllables per word) is [−3.40, 63.54] (fixture report `readability_envelope`).

**M7. V1.7 alignment.** 0 conflicts occur in any two-pass answer of the dev corpus, and 0 of the 166 answered development contained answers (`bm25f-v1`, the fixture's 298 queries) quote conflicting passages (`legacy_conflicts`).

**M8. Legacy D-19 quotations cut sentences.** Of 473 dev quotations (`bm25f-v1`), 107 leave out a negation cue or a number of the sentence they cut, at a span edge or at the 320-character display truncation. Every quotation is a substring of its span's `normalize_display_text`, and every number and negation cue in a quotation is in its span (`test_v1_legacy_guard`: every dev contained answer passes the guard unchanged).

**M9. Overlap gate and digest.** `claim_gate.py` has no `ClaimGate`, `evidence_digest` or `_STOPWORDS`. `TeachingAssistantService._ask_vertex` is called by no app or script code (only the Phase 1 AC-1-8 redaction tests call it). No app code sets `grounded=True` (`test_plan_d_*`).

**M10. Latency.** The V1 p95 over the fixture runs is a few milliseconds (fixture report `latency`, compared with the 250 ms budget only).

**M11. p1-floor scoring.** Under `bm25f-v1` the gate returns no result below `abstention.floor`, and `near_floor` is exactly `score < floor + margin`. Under `p1-floor` the margin is 0.

**M12. Ledger storage.** `response_ledger.entry_schema` is VARCHAR(32), so `ledger-entry-v2` fits; the CHECK constraints name only `delivery` and `decision` values; verification, export and restore dispatch on `ENTRY_SCHEMAS`.

**M13. Package v2.** `scripts/config_package.py --check` passes on v2: 2.0.0, sha256 `f35a4edfcdf3953267109902813dd28d443ccaa6c2a88ddd111a0f7ef907a42a`.

**M14. Phase 3 seams.** Phase 3 tests monkeypatch `pipeline_module.check_subset`, `retrieve`, `build_envelope` and `append_ledger_entry`, call `render_checked(renderer, locked, presentation, max_regenerations=...)` directly, and assert `contracts.TWO_PASS_DELIVERY_IMPLEMENTED is False`. `tutor_fakes.ScriptedGenerator` repeats its last script.

**M15. `hypothesis` is not installed.** Property tests use a seeded `random.Random`.

**M16. Development default `V1_PIPELINE=enforce`.** Tests run with `ENVIRONMENT=development`, so every `TwoPassPipeline(…, Settings())` writes `ledger-entry-v2`. The Phase 3 tests that this changed are listed in 13.3.

### 0.3 Readings

**R-a. "Delivered text" in Phase 4.**
- No two-pass text reaches a learner: `TWO_PASS_DELIVERY_IMPLEMENTED` stays `False`, `TWO_PASS_TUTOR=on` stays refused, and `phase4_exit_passed` stays `false` (conflict 9).
- In AC-4-4 and AC-4-5, "delivered text" is the text of V1's accepted rendering. It is recorded in the shadow ledger record (`rendered_text_sha256`), with per-claim `final` verdicts.
- The learner's delivery is still the legacy D-19 contained answer.
- In AC-4-6, "a disclosure block is shown" on the learner path is the evidence panel's `conflicts` (labels of the passages that disagree); with the panel off nothing is shown, so the legacy guard withholds the answer (4.15). On the two-pass track the `DisclosureBlock` is on the verification record; V1's accepted rendering holds no disclosure text, and the delivered path must show the block before a `disclose` verdict reaches a learner (DI-59).

**R-b. "The legacy gate" that V1 shadows** (plan G; E10). The overlap gate is gone (M9). The shadowed path is:
1. the Phase 3 decision path: the composition of bind, lock, render and the subset check, plus its abstention;
2. the legacy contained decision the learner received.

V1's final outcome is compared with both (`V1Comparison`, 4.12).

**R-c. AC-4-3.**
- "V1.5 abstains" on out-of-scope fixtures.
- "In-domain answer rate stays at or above the Phase 2 baseline" is the Phase 2 `answer_rate` definition applied to V1.5's decision (M1), for the same gate, over the same 174 in-domain items.
- The composition rate (M2) is reported beside it. Under checker configuration (b), V1 adds no in-domain abstention over the Phase 3 composition (stop condition `stop.composition`, 5.1).
- Under configuration (a) (NullChecker), V1 abstains on no more items than under (b), and every answer it would give is `withhold`. The learner's answer rate is carried by the D-20 replacement (the D-19 contained answer, unchanged).

**R-d. "HARD = final".**
- A response-level `hard_fail` judges one candidate (a claim plan or a rendering). That candidate is discarded and never delivered, and no later stage, vote or retry re-judges it.
- A regeneration is a new candidate that every check judges from the start (plan: "regenerate (<= 2) or abstain").
- A V1.2 `hard_fail` with a `claim_id` is claim-scoped: that proposed claim is dropped for good, and the candidate's other claims go on.
- `VerificationRecord.hard_fail` is true exactly when the decision is a `V1HardFail`.

**R-e. Modes.**

| Mode | What runs | What is recorded |
|---|---|---|
| `off` | Phase 3, exactly | `ledger-entry-v1` |
| `shadow` | The Phase 3 composition decides the record; V1 runs its own track alongside | `ledger-entry-v2`, `verification.mode = "shadow"`, with a comparison |
| `enforce` | V1's track decides the shadow record: its decision, claims, rendering and counts | `ledger-entry-v2`, `verification.mode = "enforce"` |

The legacy V1.1/V1.2 guard runs in every mode (conflict 4).

---

## 1. Conflicts between plan text and the fixed decisions, with resolutions

Each resolution is a refinement. None reverses a fixed decision without quoted plan text.

1. **Package location.** Plan 7.1: "| L6 | lexical ClaimGate; no V2, no V3 | modules v1_checks, v2_panel; service review-console | 4-6 |". E1 allows `services/v1/` or `tutor_pipeline/v1/`.
   - **Resolution:** `apps/api/app/services/v1_checks/`, the plan's own name and layer. L6 judges L5's output, and V1 also guards the legacy paths (V1.1/V1.2) and the evidence panel (V1.7), which live outside `tutor_pipeline`.
   - The V1 contracts live in `tutor_pipeline/contracts.py` beside `LedgerEntry`.
   - `tutor_pipeline/pipeline.py` imports `v1_checks` lazily inside `run()` and its helpers, and `runner.py` imports `pipeline` lazily, so there is no import cycle.
   - The AC-3-1 import rule is extended to `v1_checks/*.py` (13.1 test 30).
2. **Outcome vocabulary.** Plan 7.4: "v1 {check_id (V1.1-V1.9), outcome (pass|flag|hard_fail), checker_model_id (V1.3 only)}". E1 adds `abstain` and `mark`.
   - **Resolution:** a superset. `abstain` is used only by V1.5, by V1.2 when no claims are left, and by V1.3 when the checker is unavailable. `mark` is V1.5's X4 candidate.
3. **13.6 (L2373): "No flag, kill switch, setting or governance override MAY disable V1 or deliver text whose verification has not completed"**, against E10's `off`.
   - **Resolution:** `off` is development and test only; Settings refuse it elsewhere. The legacy guard (V1.1 and V1.2, and V1.7 while no evidence panel is shown, 4.15) has no flag and runs on every delivery path. Outside development the only accepted value is `shadow` until the Phase 4 exit.
4. **Plan L: "V1.1/V1.2 stay enforced with extractive mode or abstention [Decision D-19], never the legacy overlap gate alone [Risk R-16]".**
   - **Resolution:** (a) `legacy_guard.guard_contained` enforces V1.1 and V1.2 on `/assistant/chat`, `/tutor/turns` and `/qa/ask` in every mode; (b) the two-pass composition is bound by the Phase 3 resolver binding in every mode, never by an overlap gate; (c) `shadow` (the rollback target) records V1's whole verdict.
5. **Plan G "shadows the legacy gate"** while the overlap gate is deleted. **Resolution:** R-b, stated in ADR-005 and in 4.12.
6. **Plan E "V1 module replacing claim_gate"**, against E16 "V1.4 IS the Phase 3 subset check (wrap it)".
   - **Resolution:** `claim_gate.py` stays the subset-check module. `v1_4_subset.py` maps the result that `render_checked` computes through the `pipeline.check_subset` seam (M14). There is one seam and no second implementation.
7. **Coverage map V1.2 "negation -> V1.3"**, against E3's deterministic polarity check in V1.2. **Resolution:** both. V1.2 adds `quantity-negation-polarity-v1` (E-27), and V1.3 still flags every claim (NullChecker). This is stricter than the map.
8. **Plan 7.4 `EvidenceBundle {… conflicts[]}`**, against E8 ("the cited spans of one response").
   - **Resolution:** V1.7 runs after binding over the cited spans; its result is the response's `DisclosureBlock` (3.2). `EvidenceBundle.conflicts` stays `()` and is refused if non-empty, with the message "V1.7 (Phase 4) records conflicts on the verification record (DisclosureBlock), never on an evidence bundle"; the JSON schema is unchanged.
9. **Plan 7.2 "[L7 ledger append] --> DELIVER"** and the Phase 3 spec's note that Phase 4 sets `TWO_PASS_DELIVERY_IMPLEMENTED`, against the freeze and `phase4_exit_passed` false.
   - **Resolution:** Phase 4 builds no delivered two-pass path; `TWO_PASS_DELIVERY_IMPLEMENTED` stays `False` (R-a). The flip, `TWO_PASS_TUTOR=on` and F-1 belong to the Phase 4 exit (DI-59). The Phase 3 spec's two sentences and the `contracts.py`/`shadow.py` comments say so (7.14).
   - Invariant 6 ("delivery requires final = deliver") is enforced now, in the `VerificationRecord` and `LedgerEntryV2` rules and the aggregator.
10. **Precondition "Phase 3 exit".** Not passed (E16). **Resolution:** proceed under P1-D-18; DI-58.
11. **Precondition "V1.3, X4 and V1.9 values set as operator policy (Q-22) [Decision D-06]".** Not met.
    - **Resolution:** plan L795-800: "[PROV] values and the unspecified X4 margin, V1.3 threshold, V1.9 band and tier-3 threshold MUST be frozen in versioned configuration before use (Q-22; Decision D-06), never reported as results". Package v3 holds every such value with `provisional: true` (PD-15, PD-16, PD-17). Owner values and hold H7's "Signed configuration" are DI-52.
12. **Precondition "misconception seed list (Q-14) [Assumption A-18]".** Unavailable. **Resolution:** library v0 ships empty, inline in the package. The loader refuses entries while Q-14 is unavailable. Tests inject a fixture library (DI-53).
13. **Precondition "keyed answers outside public payloads".** Not met on `078bc75` (M4).
    - **Resolution:** Phase 4 meets it (E7; 4.14, 9, 11). The change is strictly less disclosure and ships only with a D-05 release.
    - The frontend strips quiz fields before any client component sees them, so frontend-first deployment removes keys from public HTML at once (15.5).
14. **D-20 is an OPEN DECISION**, while P1-D-18 applies only RECOMMENDATION, "until decided" or stop-path defaults. E4 says to apply D-20's own text provisionally.
    - **Resolution:** apply it. D-20's text is itself the interim policy, and hold H15 ("V1.3 routing [Decision D-20] | P4 V1.3 enforcement | Interim policy") names that policy as its release evidence. It is the most conservative path: every flagged claim is withheld. Recorded as PD-13; ratification and the filed policy are DI-55.
15. **D-21 OPEN** ("hosting for the V1.3 checker and open-weight verifier, or none"). **Resolution:** take the "none" path, which is the fact today. Plan E reads "if none, V1.3 flags everything". `NullChecker` (`checker_model_id: "none"`); PD-14, DI-54.
16. **V1.3 "flag only, never HARD"**, against AC-4-7 (abstain when the checker is unavailable). **Resolution:** unavailability is outcome `abstain` (response-level), never `hard_fail`.
17. **V1.8 "flag, queue V3"**, while D-20 names only V1.3. **Resolution:** a V1.8-flagged claim is also withheld before Phase 5, by 13.6 ("deliver text whose verification has not completed"), and carries a V3 intent. This is stricter.
18. **V1.9 "invalid schema HARD; outside band | E | HARD/regen"**, against E9 ("readability … re-render only, never hard"). **Resolution:** a band miss is outcome `flag`, which forces a re-render; when the render limit is spent the run abstains (`V1Abstained`, E2).
19. **V1.5 under the two gates** (M11). **Resolution:** V1.5 maps the active gate's own decision: abstain when the gate returned nothing, with the gate's reason; `mark` on `near_miss`; otherwise `pass`. The X4 margin is still frozen in v3 (`x4_margin`, required equal to `abstention.margin` for `bm25f-v1` and 0 for `p1-floor`).
20. **AC-4-3's metric**, against the lower composition rate (M2). **Resolution:** R-c. The stop floor in v3 applies to the V1.5 rate. A second stop (`stop.composition`) catches V1's own over-abstention. The composition gap is Phase 3's whole-sentence extractive rule.
21. **Plan L's p95 budget.** No value is given. **Resolution:** 250 ms provisional (PD-18). It is measured by `run_v1_fixtures.py` and per process, and is never byte-compared.
22. **Legacy quotations cut sentences** (M8). E3's rule is claim→span ("every number/quantity token and every negation cue in a claim must be matched … in at least one bound span"); legacy quotations pass it by construction. Forcing whole-sentence legacy quotations would change most development answers, a learner-visible change. **Resolution:** the guard enforces E3's rule literally, plus verbatim binding. The edge-cut residual is DI-60.
23. **`Provenance.v1_3_checker_model_id: None`** (the Phase 3 contract), against "none" now being a real id. **Resolution:** `ProvenanceV2.v1_3_checker_model_id: str` in `ledger-entry-v2`. v1 is unchanged. v3's `unused_provenance_fields` drops it.
24. **E15 "ADR-005 REWRITE … keep the old text as a superseded dated section"**, against the Phase 3 text tests (0.1). **Resolution:** the original sections and the Phase 3 revision stay verbatim; a dated status line under the title marks the 2025 Context/Decision/Consequences sections superseded and says the Phase 3 revision stays in force as V1.4; `## Decision 2026-11-20 (Phase 4: V1 deterministic validation)` is appended as the authoritative section (15.2).
25. **E7 "per-question feedback {question_id, correct, answer, explanation}".** **Resolution:** the key and explanation are returned only for questions the saved attempt answered; unanswered questions get `answered: false` with no key. This is strictly less disclosure.
26. **Fixture hash in the package**, while the image holds no `docs/`. **Resolution:** `check_v1_package` compares the fixture pin only when the check is structural (tests, CI, `config_package.py --check`), never at production start-up.
27. **E11 migration.** No column or table is added (M12). **Resolution:** no Alembic revision; `ledger.SCHEMA_REVISION` is unchanged.
28. **V3 queue (E4 "stub table only if cheap and erasable").** **Resolution:** the typed V3 intent lives on the ledger record (`ClaimVerdict.v3`). A read-only helper `ledger.pending_v3_intents` serves Phase 6. No table (DI-56).
29. **Plan I SLIs**, against public `/ready` carrying no per-run outcome (AC-3-6). **Resolution:** V1 SLIs and the legacy-guard counts are in-process (`V1_METRICS.detail_snapshot`) and in log lines. Public `/ready` gains only the package's static V1 fields and the effective mode; `slis` is unchanged.
30. **VerificationVerdict `cycle_count`.** In the plan it counts the X2 correct and re-verify cycles; E2 asks for V1 regenerations. **Resolution:** V1 records its regenerations there (0-4: up to 2 generation plus 2 render). Phase 5 adds V2 cycles as a separate field.
31. **Prompt hashes.** Socratic omission (E7) adds a renderer parameter, but `pedagogical_prompt_hash` must stay equal to v2's pin (M13). **Resolution:** the template registry (`PEDAGOGICAL_PROMPT_HASH_INPUT`) is unchanged. Omission is V1.6's rule (`keyed-answer-socratic-omit-v1`), pinned in `v1.rule_ids` and `v1.rules_hash`, and recorded per response in `verification.checks`.
32. **13.6 stop-the-line "delivered V1 hard failure, unresolvable citation".** **Resolution:** the aggregator and the `VerificationRecord`/`LedgerEntryV2` rules refuse `final: deliver` for any claim with a non-pass result in its accepted candidate, or involved in a withheld V1.7 conflict; the legacy guard withholds any unresolvable quotation. Both are tested (13.1 tests 2 and 21).
33. **V1.7 "2025-vs-2026 disclosed" (coverage map) in production.** The plan's 2025/2026 pair is the lecture video (Q-10, E-21), and the 2026 item is unbound. Video spans are never cited: D-19 quotes document spans only, and the two-pass envelope takes quotable document spans only. **Resolution:** the production family is recorded (Q-10) but cannot fire. AC-4-6 is proven with a fixture family over two document items. In production, disclosure can come only from a number or negation disagreement (M7: none today). Recorded as a residual in ADR-005 and the closure notes.
34. **The legacy guard without a v1 block.** A v1 or v2 package can be selected (`CONFIG_PACKAGE_PATH`). **Resolution:** a governed build, and any build outside development whatever its governance setting (plan 13.6: no flag, setting or governance override may disable V1), refuses at start-up a package with no `v1` block, because the guard needs its lexicon. Only in development with governance off does the guard run V1.1 and verbatim binding alone (no package value needed), skipping the polarity rule, with `tutor.v1.unavailable` logged once at start-up.
35. **D-20 replacement wording.** D-20: "withheld, replaced by pre-verified module content or extractive mode [Decision D-19], else abstain". **Resolution:** the record's `replacement` is `extractive_d19` when the learner's contained answer quoted spans, `abstention` when it abstained, `unknown` when no legacy decision exists (replay and fixture runs).
36. **P2-12-D-03 and Phase 3 text that described Phase 4 as future.** The text is edited in place where Phase 4 makes it false (7.14).
37. **The Phase 3 tests that pin rule ids in package_check** (`test_tutor_pipeline_package.py`, `test_f4_*`). **Resolution:** the v3 loader does not itself require `ledger.entry_schema` to be `ledger-entry-v2`; `package_check` compares it with the `LedgerEntryV2` contract, as it compares every rule id. The loader requires `legacy_entry_schema` and `entry_schemas`.

---

## 2. Architecture

```
learner turn ──► TutorOrchestrator.chat / QAEngine.ask
   ├─ contain_answer (D-19, unchanged) ─► legacy_guard.guard_contained (V1.1, V1.2; V1.7 when no panel is shown; every mode) ─► learner response
   │       └─ (EVIDENCE_PANEL_ENABLED, development by default) evidence panel + V1.7 legacy conflicts (labels only)
   └─ ShadowJob(legacy_decision=…) ─► background: TwoPassPipeline.run (shadow only, AC-3-6)
        retrieve ─► V1.5 (abstain | mark | pass) ─► envelope
        V1_PIPELINE=off     : Phase 3 composition ─► ledger-entry-v1
        V1_PIPELINE=shadow  : Phase 3 composition (recorded) + V1 track (verification, comparison) ─► ledger-entry-v2
        V1_PIPELINE=enforce : V1 track decides ─► ledger-entry-v2
        V1 track:
          generation loop (1 + 2): propose ─► V1.9 plan schema ─► [budget] ─► V1.1 ─► V1.2 (bind + polarity) ─► lock
                                   ─► [budget] ─► V1.3 (NullChecker: flag all | unavailable ⇒ abstain) ─► V1.7 ─► V1.8
          render loop (render_checked + post_render hook, 1 + 2):
                                   V1.9 envelope ─► subset check (V1.4) ─► V1.6 ─► V1.9 band
          aggregate ─► V1HardFail | V1Abstained | V1Passed ─► consult_v2(hook=None) [only a V1Passed may reach a hook]
```

**Where each AC is enforced**

| AC | Mechanism | Primary tests |
|---|---|---|
| AC-4-1 | `check_v1_1` hard-fails any unresolvable id. `V1HardFail` has no consult path; `consult_v2` passes only a `V1Passed` to a hook. | `test_ac_4_1_*` (property and contract) |
| AC-4-2 | V1.2 polarity and binding, V1.1, V1.4, V1.7; NullChecker withholding | `test_ac_4_2_*`, `run_v1_fixtures.py --check` |
| AC-4-3 | `check_v1_5` maps the active gate's decision; the in-domain rate is compared with the calibration record by counts | `test_ac_4_3_*` |
| AC-4-4 | V1.4 (the subset check inside `render_checked`), at most 2 re-renders | `test_ac_4_4_*` |
| AC-4-5 | V1.6 key containment plus Socratic omission; the public `QuizQuestion` has no key | `test_ac_4_5_*` |
| AC-4-6 | Two-pass: V1.7 `DisclosureBlock` (disclose) on the record, or the claims withheld. Learner path: the evidence panel's `conflicts`, or, with the panel off, the legacy guard withholds the answer (4.15) | `test_ac_4_6_*` |
| AC-4-7 | V1.3 call; an error, wrong type or late result gives `abstain` / `checker_unavailable` | `test_ac_4_7_*` |

---

## 3. Data shapes

### 3.1 V1 vocabulary (`apps/api/app/services/tutor_pipeline/contracts.py`, section "V1 (Phase 4)")

```python
CHECK_IDS = ("V1.1", "V1.2", "V1.3", "V1.4", "V1.5", "V1.6", "V1.7", "V1.8", "V1.9")
CheckId = Literal["V1.1", "V1.2", "V1.3", "V1.4", "V1.5", "V1.6", "V1.7", "V1.8", "V1.9"]
Outcome = Literal["pass", "flag", "hard_fail", "abstain", "mark"]
EhmfType = Literal["A", "B", "C", "D", "E"]
# Plan Phase 4 D table, EHMF column (verbatim).
EHMF_BY_CHECK = {"V1.1": ("B",), "V1.2": ("A", "B"), "V1.3": ("A", "B", "C"), "V1.4": ("D", "E"), "V1.5": ("A",),
                 "V1.6": ("E",), "V1.7": ("D",), "V1.8": ("C",), "V1.9": ("E",)}
STAGES_BY_CHECK = {"V1.1": ("pre_render",), "V1.2": ("pre_render",), "V1.3": ("pre_render",), "V1.4": ("post_render",),
                   "V1.5": ("pre_render",), "V1.6": ("post_render",), "V1.7": ("pre_render",), "V1.8": ("pre_render",),
                   "V1.9": ("pre_render", "post_render")}
SUBSET_PROBLEM_CODES = ("empty", "text_not_segments", "unmapped_factual_sentence", "duplicate_claim", "citation_outside_locked_set",
                        "citation_not_on_claim", "citation_marker_mismatch", "no_claim_rendered", "claim_uncited",
                        "citation_list_mismatch")   # == claim_gate.PROBLEM_CODES (package_check and a test compare)
V1_DROP_REASONS = ("quantity_mismatch", "negation_mismatch")
UNRESOLVABLE_CANDIDATE = "unresolvable_citation"   # each claim of a final candidate V1.1 hard-failed (counts only)
V1_COUNT_REASONS = (*V1_DROP_REASONS, UNRESOLVABLE_CANDIDATE)
REASON_OUTCOMES: dict[str, dict[str, str]] = {
    "V1.1": {"resolved": "pass", "unresolvable": "hard_fail", "malformed_span_id": "hard_fail", "content_hash_mismatch": "hard_fail"},
    "V1.2": {"bound": "pass", "merged": "pass", "duplicate": "pass", **{code: "hard_fail" for code in BINDING_FAILURES},
             **{code: "hard_fail" for code in V1_DROP_REASONS}, "no_bound_claims": "abstain"},
    "V1.3": {"supported": "pass", "no_checker": "flag", "not_enough_info": "flag", "contradicted": "flag",
             "below_support_threshold": "flag", "checker_unavailable": "abstain"},
    "V1.4": {"mapped": "pass", "render_failed": "hard_fail", **{code: "hard_fail" for code in SUBSET_PROBLEM_CODES}},
    "V1.5": {"answer": "pass", "near_miss": "mark", **{code: "abstain" for code in (*GATE_ABSTENTION_REASONS, "corpus_version_mismatch",
                                                                                  NO_QUOTABLE_EVIDENCE)}},
    "V1.6": {"not_assessment": "pass", "key_absent": "pass", "short_key_unmatchable": "pass", "keyed_answer_present": "hard_fail"},
    "V1.7": {"no_conflict": "pass", "conflict_disclosed": "flag", "conflict_withheld": "flag"},
    "V1.8": {"no_match": "pass", "misconception_match": "flag"},
    "V1.9": {"schema_valid": "pass", "claim_plan_invalid": "hard_fail", "generator_mismatch": "hard_fail",
             "response_envelope_invalid": "hard_fail", "within_band": "pass", "below_band": "flag", "above_band": "flag"},
}
V1_ABSTENTION_REASONS = ("unresolvable_citation", "checker_unavailable", "keyed_answer_leak", "readability_out_of_band",
                         "response_envelope_invalid")
V1_WITHHOLD_REASONS = ("d20_interim_withhold", "conflict_withheld")
ACCEPTED_ABSTENTION_REASONS = {
    "ledger-entry-v1": (*ABSTENTION_REASONS, LEGACY_ABSTENTION_REASON),
    "ledger-entry-v2": (*ABSTENTION_REASONS, LEGACY_ABSTENTION_REASON, *V1_ABSTENTION_REASONS),
}
```

- `LedgerEntry._rules` reads `ACCEPTED_ABSTENTION_REASONS[self.entry_schema]`; v1 behaviour, v1's fields and v1's JSON schema are unchanged.
- `package_check` and `test_v1_2_binding` check that every `bind` outcome and every `Sufficiency.reason` the gate can give is a key of `REASON_OUTCOMES` (totality).

### 3.2 Check result and verdict contracts

```python
class CheckResult(Contract):
    check_id: CheckId
    stage: Literal["pre_render", "post_render"]
    attempt: int = Field(ge=1, le=3)
    outcome: Outcome
    ehmf_types: tuple[EhmfType, ...]
    reason_code: str
    claim_id: str | None = Field(default=None, pattern=CLAIM_ID)
    checker_model_id: str | None = None

class V3Intent(Contract):
    queue: Literal["pending_v3"] = "pending_v3"
    reasons: tuple[Literal["v1_3_flag", "v1_8_misconception", "x4_margin"], ...] = Field(min_length=1)
    trigger: Literal["X4"] | None = None
    gold_label_id: None = None

class ConflictPair(Contract):
    kind: Literal["version_of_same_asset", "number_disagreement", "negation_disagreement"]
    span_ids: tuple[str, ...] = Field(min_length=2, max_length=12)
    item_ids: tuple[str, str]
    claim_ids: tuple[str, ...] = ()

class DisclosureBlock(Contract):
    block_schema: Literal["conflict-disclosure-v1"] = "conflict-disclosure-v1"
    policy: Literal["disclose", "withhold"]
    conflicts: tuple[ConflictPair, ...] = Field(min_length=1, max_length=20)

class ClaimVerdict(Contract):
    claim_id: str = Field(pattern=CLAIM_ID)
    v1: tuple[CheckResult, ...]
    v2: None = None
    v3: V3Intent | None = None
    final: Literal["deliver", "correct", "withhold", "abstain"]
    cycle_count: int = Field(ge=0, le=4)

class V1Policy(Contract):
    rules_version: str
    rules_hash: str = Field(pattern=HEX64)
    checker_hosting: str = Field(min_length=1, max_length=64)
    checker_model_id: str = Field(min_length=1, max_length=128)
    misconception_library_version: str
    misconception_library_sha256: str = Field(pattern=HEX64)
    d20_interim: Literal["withhold-all-flagged-v1"]

class V1Comparison(Contract):
    phase3_decision: Literal["answer", "abstain"] | None
    legacy_decision: Literal["answer", "abstain"] | None
    v1_outcome: Literal["answer", "abstain"]
    agrees_phase3: bool | None
    agrees_legacy: bool | None

class VerificationRecord(Contract):
    verification_schema: Literal["v1-verification-v1"] = "v1-verification-v1"
    mode: Literal["shadow", "enforce"]
    policy: V1Policy
    generation_attempts: int = Field(ge=0, le=3)
    render_attempts: int = Field(ge=0, le=3)
    cycle_count: int = Field(ge=0, le=4)
    claim_set_hash: str | None = Field(default=None, pattern=HEX64)
    checks: tuple[CheckResult, ...] = Field(max_length=256)
    verdicts: tuple[ClaimVerdict, ...] = Field(max_length=20)
    labels: tuple[Literal["near_floor", "conflict_disclosed"], ...] = ()
    disclosure: DisclosureBlock | None = None
    final: Literal["deliver", "correct", "withhold", "abstain"]
    final_reason: str | None
    replacement: Literal["extractive_d19", "abstention", "unknown", "none"]
    hard_fail: bool
    comparison: V1Comparison

class ProvenanceV2(Provenance):
    v1_3_checker_model_id: str = Field(min_length=1, max_length=128)

class ClaimLedgerEntryV2(ClaimLedgerEntry):
    entailment_score: float | None = Field(default=None, ge=0.0, le=1.0)
    provenance: ProvenanceV2

class PipelineCountsV2(PipelineCounts):
    pass  # _reconciles overridden: accepts DROP_REASONS + V1_COUNT_REASONS; the arithmetic rule is unchanged

class LedgerEntryV2(LedgerEntry):
    entry_schema: Literal["ledger-entry-v2"] = "ledger-entry-v2"
    claims: tuple[ClaimLedgerEntryV2, ...]
    provenance: ProvenanceV2
    verification: VerificationRecord
    counts: PipelineCountsV2
```

- `SCHEMA_MODELS["LedgerEntryV2"] = LedgerEntryV2`; `ENTRY_SCHEMAS = {"ledger-entry-v1": LedgerEntry, "ledger-entry-v2": LedgerEntryV2}`.
- `bound_claim_ratio_terms` counts `V1_COUNT_REASONS` as binding failures: in `proposed`, not in `bound`. V1.1 judges a candidate whole, so when it hard-fails the last candidate every claim of it is counted under `unresolvable_citation` (an enforce record holds `proposed == len(plan.claims)`, `bound == 0`); Phase 3 counts the same plan per claim (`outside_bundle`).

**`CheckResult._consistent`**
- `reason_code in REASON_OUTCOMES[check_id]`, and `outcome == REASON_OUTCOMES[check_id][reason_code]`.
- `ehmf_types == EHMF_BY_CHECK[check_id]`, and `stage in STAGES_BY_CHECK[check_id]`.
- `checker_model_id is not None` iff `check_id == "V1.3"`.
- `claim_id` is required for V1.2 (except `no_bound_claims`), V1.3 (except `checker_unavailable`) and V1.8, and refused for V1.1, V1.4, V1.5, V1.6, V1.7 and V1.9.

**`V3Intent`:** `trigger == "X4"` iff `"x4_margin" in reasons`; reasons are sorted and unique.

**`ConflictPair`:** `span_ids` and `claim_ids` are sorted and unique; `item_ids` are sorted and distinct.

**`ClaimVerdict.v1`** holds the accepted candidate's results whose `claim_id` is this claim, plus that candidate's response-level results (claim_id None), in check order. The accepted candidate is V1.5 (judged once, on the bundle), the last generation attempt's pre-render results and the last render attempt's post-render results (`aggregate.accepted_results`).

**`VerificationRecord._rules`**
- `cycle_count == max(generation_attempts - 1, 0) + max(render_attempts - 1, 0)`, and each verdict's `cycle_count` equals it.
- `final != "correct"`: there is no V2 yet.
- `(final == "withhold") == (replacement != "none")`; when `final == "withhold"`, `replacement` is `extractive_d19` iff `comparison.legacy_decision == "answer"`, `abstention` iff it is `"abstain"`, and `unknown` iff it is None.
- `deliver` needs at least one verdict `deliver`; `withhold` needs at least one verdict and none `deliver`; `abstain` needs every verdict `abstain`; and a verdict `abstain` occurs only when the response abstains.
- `hard_fail` implies `final == "abstain"`.
- `final_reason` is `None` iff `final == "deliver"`, and otherwise lies in `ABSTENTION_REASONS + V1_ABSTENTION_REASONS + V1_WITHHOLD_REASONS`.
- No verdict `deliver` has, among its own `v1` results, any outcome other than `pass` or `mark`, V1.7's results aside (V1.7 is response-level: a disclosed conflict is deliverable, and a withheld one is refused by the next rule). This covers conflict 32 and invariant 6.
- When `disclosure` has policy `withhold`, no claim named in any of its `claim_ids` has verdict `deliver`.
- `labels` holds `"conflict_disclosed"` iff `disclosure` is set with policy `disclose`, and `"near_floor"` iff a V1.5 result has outcome `mark`.
- `comparison.v1_outcome == ("abstain" if final == "abstain" else "answer")`; each `agrees_*` is `None` iff its reference is `None`, and otherwise equals `reference == v1_outcome`.

**`LedgerEntryV2._v1_rules`** (the inherited `_rules` runs too)
- `delivery == "shadow"`: in Phase 4 only shadow records carry V1.
- `provenance.v1_3_checker_model_id == verification.policy.checker_model_id`, and every V1.3 result carries that id.
- A claim's `entailment_score` is `None` when the checker id is `"none"` and in `shadow` mode.
- In `enforce`: `(decision == "abstain") == (final == "abstain")`; the verdict claim ids equal `[claim.claim_id for claim in claims]`, in order; `verification.claim_set_hash == claim_set_hash`.
- In `shadow`: `comparison.phase3_decision == decision`; `abstention_reason` lies in `ABSTENTION_REASONS + (LEGACY_ABSTENTION_REASON,)`; `counts.dropped` holds no `V1_COUNT_REASONS` key.

In enforce, `decision == "answer"` means "a rendering passed V1" (a `V1Passed`), and `presentation.plan_id` is the accepted rendering's plan. Whether any of it may be delivered is `verification.final`. Consumers read `final`; the Phase 3 metrics keep counting `decision`.

### 3.3 Runtime decision types (`v1_checks/aggregate.py`; dataclasses, not ledger contracts)

```python
@dataclass(frozen=True)
class V1HardFail:            # final; carries results only: no claim, no rendering, no consult path
    results: tuple[CheckResult, ...]; failing: tuple[CheckResult, ...]
    generation_attempts: int; render_attempts: int; abstention_reason: str
    final: Literal["abstain"] = "abstain"
@dataclass(frozen=True)
class V1Abstained:           # V1.5, no claims, V1.2 none left, V1.3 unavailable, band, budget: not a hard fail, no consult path
    results: tuple[CheckResult, ...]; generation_attempts: int; render_attempts: int; abstention_reason: str
    final: Literal["abstain"] = "abstain"
@dataclass(frozen=True)
class V1Passed:
    locked: LockedClaimSet; rendered: RenderedResponse; presentation: PresentationPlan
    results: tuple[CheckResult, ...]; verdicts: tuple[ClaimVerdict, ...]; disclosure: DisclosureBlock | None
    labels: tuple[str, ...]; generation_attempts: int; render_attempts: int
    final: Literal["deliver", "withhold"]; final_reason: str | None
V1Decision = V1HardFail | V1Abstained | V1Passed

class V2Hook(Protocol):                       # Phase 5 implements it; Phase 4 wires none
    def consult(self, passed: V1Passed) -> object: ...

def consult_v2(hook: V2Hook | None, decision: V1Decision) -> V1Decision:
    """Only a V1Passed reaches a hook (plan rule 1, invariant 3). Phase 4 returns `decision` unchanged whatever the
    hook returns; Phase 5 defines how V2 verdicts apply to a V1Passed's flagged claims."""
    if hook is None or not isinstance(decision, V1Passed):
        return decision
    hook.consult(decision)
    return decision
```

`V1Passed.__post_init__` raises `ValueError` if the accepted generation attempt, or the passing render attempt, holds a `hard_fail` or `abstain` result. The one exemption is a claim-scoped V1.2 `hard_fail` whose `claim_id` is not a locked claim's id (a dropped proposal, R-d).

### 3.4 API additions (`app/schemas.py`)

```python
class QuizQuestion(BaseModel):            # public: no key (Phase 4, R-42)
    id: str
    question_type: str
    prompt: str
    choices: list[str] = Field(default_factory=list)
    difficulty: str

class QuizFeedbackItem(BaseModel):
    question_id: str
    answered: bool
    correct: bool | None = None           # None when not answered
    answer: str | None = None             # the key, only for an answered question
    explanation: str | None = None

class QuizAttemptResult(BaseModel):
    status: Literal["saved"] = "saved"
    attempt_id: int
    score: int
    feedback: list[QuizFeedbackItem] = Field(default_factory=list)

class EvidenceConflict(BaseModel):
    kind: Literal["version_of_same_asset", "number_disagreement", "negation_disagreement"]
    passages: list[int]                   # 1-based positions in EvidencePanel.spans

class EvidencePanel(BaseModel):  # Phase 4 additions only
    conflicts: list[EvidenceConflict] | None = Field(default=None, exclude_if=lambda value: value is None)
```

- The Phase 3 spec's full `EvidencePanel` listing carries the same `conflicts` line (7.14).
- The internal key model is not a pydantic response model: it is the frozen dataclass `QuizKey` in `app/services/quiz_keys.py` (4.14).

---

## 4. V1 specification (algorithms)

### 4.1 Rules and lexicon (`v1_checks/rules.py`, `v1_checks/lexicon.py`, `v1_checks/results.py`)

**`rules.py`** holds `RULE_IDS`:

| Check | Rule id |
|---|---|
| V1.1 | `span-resolution-current-v1` |
| V1.2 | `binding-polarity-v1` (with the polarity sub-rule `quantity-negation-polarity-v1`) |
| V1.3 | `entailment-interface-v1` |
| V1.4 | `claim_gate.SUBSET_CHECK_RULE` (`segment-exact-whitespace-v3`) |
| V1.5 | `gate-decision-margin-v1` |
| V1.6 | `keyed-answer-containment-v1` (context rule `prompt-containment-or-jaccard-v1`), plus `keyed-answer-socratic-omit-v1` for the omission |
| V1.7 | `conflict-version-polarity-v1` |
| V1.8 | `misconception-all-terms-v1` |
| V1.9 | `schema-forbid-v1` (schema) and `fk-grade-segments-v1` (readability) |

It also holds `RULES_VERSION = "v1-checks-v1"`, `D20_RULE = "withhold-all-flagged-v1"`, `FK = (0.39, 11.8, 15.59)`, the syllable rule `vowel-groups-silent-e-v1` (`VOWEL_GROUP_PATTERN = r"[aeiouy]+"`, exceptions `("le", "ee")`), `WIRED_CHECKERS = frozenset({"none"})`, and the patterns:
- `WORD_PATTERN = r"[a-z0-9]+(?:['’][a-z]+)?"`;
- `QUANTITY_PATTERN = r"(?<![\w.])(?P<number>\d+(?:[.,]\d+)*)(?:\s*(?P<unit>%|[a-zµμ]+))?"` (named groups, so no index literal is needed);
- `ALPHA_PATTERN = r"[A-Za-z]+"`;
- `KEY_STRIP_PATTERN = r"[^\w\s]"`.

The fixed numbers the checks use (attempt and verdict caps, the conflict caps, the parity divisor, the millisecond factor, rounding digits, the latency histogram, the p95 window, the repository depth of the fixture file) are constants there too. `v1_rules_hash(package)` is `canonical_sha256({"rule_ids", "polarity", "assessment", "d20", "fk", "patterns" (the four above), "lexicon" (package.v1.lexicon: cues, suffixes, number words, units, min_alignment_term_chars), "syllables"})`.

Thresholds come from `package.v1` only (R-46). Numeric literals other than 0, 1 and −1 appear only in `rules.py`. An AST test enforces this (13.1 test 27).

**`lexicon.py`.** Pure functions; every comparison uses NFKC plus casefold.
- `tokens(text)`: `WORD_PATTERN` over the folded text.
- `negation_cues(text, lexicon) -> Counter`: tokens in `lexicon.negation_cues`, plus tokens ending in a `negation_suffixes` entry.
- `quantities(text, lexicon) -> Counter[(number, unit)]`: each `QUANTITY_PATTERN` match gives `(number with "," removed, unit)`, where `unit` is the `unit` group when it is `%` or in `lexicon.units`, else `""` (any other following word is not a unit); each token in `number_words` gives `(token, "")`.
- `numbers(text, lexicon) -> Counter[str]`: the number values of `quantities`.
- `quantities_covered(claim, span) -> bool` (multiset): every claim quantity `(n, u)` with a unit is matched by a distinct span quantity `(n, u)`; then a claim quantity `(n, "")` may match a remaining span quantity `(n, any unit)`, because a quotation may end at the number.
- `alignment_terms(text, lexicon, stopwords) -> frozenset`: tokens that are not stopwords, not cues and not number words, do not start with a digit, and have at least `min_alignment_term_chars` characters.
- `jaccard(a, b)`: `|a∩b| / |a∪b|`, and 0 when both are empty.
- `knorm(text) = " " + " ".join(re.sub(KEY_STRIP_PATTERN, " ", fold(text)).split()) + " "`.

**`results.py`.** `make_result(check_id, stage, attempt, reason, *, claim_id=None, checker_model_id=None)` builds every `CheckResult` from the contract vocabulary, so a check names only its reason.

### 4.2 V1.1 resolution (`v1_1_resolution.py`)

```python
def check_v1_1(plan: ClaimPlan, bundle: EvidenceBundle, *, resolver: SpanResolver, attempt: int) -> CheckResult
```

1. For every span id of every proposed claim, in order (`resolution_problem`): an id that does not match `SPAN_ID_PATTERN` is `malformed_span_id`; `resolver.resolve_current(id) is None` (no span at the current corpus version; in-memory) is `unresolvable`; a bundle span with another content hash is `content_hash_mismatch`.
2. The first failure decides (`hard_fail`). Otherwise `pass` / `resolved`; a plan citing nothing passes.
3. The V-1 SLI ("100% of delivered citations resolve") is counted over the span ids of delivered verdicts by the runner (`V1_METRICS.citation_resolution`, 10.3), not over proposals.

### 4.3 V1.2 binding and polarity (`v1_2_binding.py`)

```python
@dataclass(frozen=True)
class BindingCheck: results: tuple[CheckResult, ...]; bind: BindResult; drafts: tuple[LockedClaimDraft, ...]; polarity_dropped: Counter
def check_v1_2(plan, bundle, *, resolver, store, registry, params: TutorPipelineParams, v1: V1Params, stopwords, attempt,
               bind_fn=bind) -> BindingCheck
def polarity_problem(claim_text: str, candidates: Sequence[str], *, v1, stopwords) -> Literal["quantity_mismatch", "negation_mismatch"] | None
```

- **Binding.** `outcomes: list[str] = []`, then `bind_fn(plan, bundle, ..., outcomes=outcomes)`: the Phase 3 rule `resolver-bundle-sentence-v2`, unchanged; it gains one keyword parameter (7.3).
- **Candidates.** For a claim, the whole sentences (`bind.whole_sentences`) of its cited spans that are in the bundle; when there are none, the sentences-v2 pieces of those spans' text.
- **Polarity rule `quantity-negation-polarity-v1`.** `best = max(jaccard(align(claim), align(s)))`; `best == 0` gives no judgement. Otherwise, among the sentences at `best`, the claim passes iff one of them covers the claim's quantities and holds exactly its negation cues; else `quantity_mismatch` when none covers the quantities, `negation_mismatch` otherwise.
- **Per-claim result.** A proposal that bound, merged or duplicated takes the id of the locked draft it bound into and the draft's polarity problem, or its outcome. Any other proposal takes `claim_id_for(claim.text, claim.span_ids)` and its own polarity problem, or its binding failure. The outcome is `REASON_OUTCOMES["V1.2"][reason]`.
- **Drafts and counts.** `drafts` are the bound drafts minus any whose locked sentence fails polarity, each counted in `polarity_dropped[reason]`; `BindingCheck.dropped` is bind's drop counts plus those (an enforce record's `counts.dropped`). A verbatim draft cannot fail; the rule is defence in depth.
- **No drafts left.** A response-level `abstain` / `no_bound_claims`, with no regeneration (plan "drop/abstain").

### 4.4 V1.3 entailment interface (`v1_3_entailment.py`)

```python
@dataclass(frozen=True)
class EntailmentResult: label: Literal["SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_INFO"]; score: float | None
class EntailmentChecker(Protocol):
    checker_model_id: str
    def check(self, claim: str, spans: tuple[str, ...]) -> EntailmentResult: ...
class NullChecker:            # D-21 "none": no checker exists
    checker_model_id = "none"
def get_checker(package) -> EntailmentChecker        # hosting "none" -> NullChecker; anything else raises (WIRED_CHECKERS)
def check_v1_3(locked, span_texts, *, checker, v1, attempt, clock=time.monotonic, scores=None) -> tuple[CheckResult, ...]
```

- **No checker.** When `checker.checker_model_id == "none"`, no call is made: every claim gets `flag` / `no_checker` (plan E).
- **Calls.** Each claim is checked inline against its own cited spans' texts, timed with `clock`. A result after `v1.checker_timeout_ms` counts as unavailable. Pre-empting a hung checker belongs with a real checker (DI-54).
- **Mapping.** `SUPPORTED` with `score is None or score >= v1.support_threshold`: `pass` / `supported`; `SUPPORTED` below: `flag` / `below_support_threshold`; `CONTRADICTED`: `flag` / `contradicted`; `NOT_ENOUGH_INFO`: `flag` / `not_enough_info`. With `scores`, each claim's score is written there (an enforce record's `entailment_score`).
- **Unavailable.** An exception, a late result, or a result that is not an `EntailmentResult` with a known label and a score in [0, 1] stops the check: one response-level `abstain` / `checker_unavailable`, logged as `tutor.v1.checker_unavailable` with `cause` (`timeout` or `error`) and `error` (a class name). This is AC-4-7.

### 4.5 V1.4 subset check (`v1_4_subset.py`)

```python
def v1_4_result(subset: SubsetCheckResult | None, *, fault: str | None, attempt: int) -> CheckResult
```

A fault (the renderer, or the subset check on a valid envelope, raised) gives `hard_fail` / `render_failed`; a passing subset check gives `pass` / `mapped`; otherwise `hard_fail` with `subset.problems[0]`. The subset result is the one `render_checked` computes through the `pipeline.check_subset` module global and passes in `RenderAttempt.subset`; there is no second implementation and no second seam. The module refuses to import if `SUBSET_PROBLEM_CODES` and `claim_gate.PROBLEM_CODES` differ.

### 4.6 V1.5 abstention (`v1_5_abstention.py`)

```python
def check_v1_5(sufficiency: Sufficiency, *, attempt: int = 1) -> CheckResult
def x4_margin(package, gate) -> float
```

`decision == "abstain"` gives `abstain` with the gate's reason; `near_miss` gives `mark` / `near_miss` (the X4 candidate: label `near_floor`, V3 intent `x4_margin` with trigger `X4` on every claim); `answer` gives `pass` / `answer`. Under `p1-floor` the margin is 0, so V1.5 never marks. `x4_margin` returns `package.v1.x4_margin[gate]`, recorded, never re-applied.

### 4.7 V1.6 keyed answers (`v1_6_keyed_answers.py`)

```python
@dataclass(frozen=True)
class KeyedItem: item_id: str; lesson_slug: str; prompt: str; choices: tuple[str, ...]; answer: str
class KeyedItemSource(Protocol):
    def items(self) -> tuple[KeyedItem, ...]
def assessment_items(question_text: str, source: KeyedItemSource, *, v1, stopwords) -> tuple[KeyedItem, ...]
def key_text(item: KeyedItem, *, v1) -> str | None
def keyed_claim_ids(locked: LockedClaimSet, items, *, v1) -> frozenset[str]
def check_v1_6(rendered: RenderedResponse, items, *, v1, attempt) -> CheckResult
```

- **Assessment context (`prompt-containment-or-jaccard-v1`).** Every lesson's items are searched, whatever the request's lesson. An item matches when its id occurs in the folded question bounded by characters outside `[a-z0-9-]` or the text's edges, or when `max(jaccard(T(q), T(p)), |T(q)∩T(p)|/|T(p)|) >= v1.assessment_threshold` (T = alignment terms).
- **`key_text`.** The answer when `knorm(answer)` has at least `short_key_min_tokens` tokens; a shorter key that equals a choice, or the letters a-d or digits 1-4 indexing `choices`, designates that choice, whose text is used if long enough; otherwise `None` (`short_key_unmatchable`, a residual).
- **Check.** No item: `pass` / `not_assessment`. Any `knorm(key_text)` inside `knorm(rendered.text)`: `hard_fail` / `keyed_answer_present`. Otherwise `pass` / `key_absent`, or `short_key_unmatchable` when every key is `None`.
- **`keyed_claim_ids`.** The locked claims that hold a key or lie inside one (a key may span several claims).
- **Socratic regeneration.** On `hard_fail`, the next render uses `PresentationPlan(plan_id=v1.socratic_plan, source=<the original source>)` and omits the keyed claims plus anything already omitted. When that would leave no claim, the hook stops: `V1HardFail` / `keyed_answer_leak`. The omitted keyed claims get verdict `withhold`. The record's `presentation.plan_id` is the accepted rendering's plan.

### 4.8 V1.7 conflicts (`v1_7_conflicts.py`)

```python
def disagreement(left: str, right: str, *, v1, stopwords) -> str | None
def check_v1_7(locked, bundle, *, sentences_of, v1, stopwords, attempt) -> tuple[CheckResult, DisclosureBlock | None]
def legacy_conflicts(citations, *, v1, stopwords) -> list[EvidenceConflict]
```

Rule `conflict-version-polarity-v1`:
1. **Versions.** Cited spans of two different items of one `v1.version_families` family form one `version_of_same_asset` pair per item pair, naming all cited spans of both items and the claims that cite them.
2. **Polarity.** For each locked claim and each whole sentence of a cited span of another item: both need at least `min_alignment_terms` alignment terms and `jaccard >= v1.alignment_threshold`; `number_disagreement` when both hold numbers and their number values differ; `negation_disagreement` when the parities of their negation-cue counts differ.
3. **Output.** No pair: `pass` / `no_conflict`, no block. Otherwise a `DisclosureBlock` with `policy = v1.on_conflict` (at most 20 pairs): `disclose` gives `flag` / `conflict_disclosed` and the label; `withhold` gives `flag` / `conflict_withheld` and withholds the claims involved. Precedence ("newer peer-reviewed over older") belongs to Phase 7.
4. **Legacy path.** `legacy_conflicts` applies the same rule to a contained answer's quotations from different items (families, and the sentences-v2 pieces of each quotation); passages are panel positions. `evidence_panel.panel_conflicts` calls it for answers with at least two quotations when the package has a v1 block, and the panel labels them; with the panel off, `legacy_guard.undisclosed_conflict` applies the same test and the guard withholds the answer (4.15).

### 4.9 V1.8 misconceptions (`v1_8_misconceptions.py`)

```python
@dataclass(frozen=True)
class MisconceptionEntry: entry_id: str; terms: tuple[str, ...]
@dataclass(frozen=True)
class MisconceptionLibrary: version: str; sha256: str; entries: tuple[MisconceptionEntry, ...]
def load_library(package) -> MisconceptionLibrary
def check_v1_8(locked, library, *, attempt) -> tuple[CheckResult, ...]
```

- **Format** (inline in v3 `v1.v1_8.library`): `{"library": "qcai-misconception-library", "version": "v0", "status": "...", "entries": [{"id": "MC-…", "terms": ["…"]}], "sha256": "<canonical sha256 of the object without sha256>"}`; each entry has at least 2 lowercase, sorted, unique terms.
- **Match (`misconception-all-terms-v1`).** Every term of an entry is a token of the claim. A match gives `flag` / `misconception_match` and the V3 intent `v1_8_misconception`; other claims `pass` / `no_match`.
- v0 is empty (conflict 12). Tests pass a fixture library to the pipeline constructor.

### 4.10 V1.9 schema and readability (`v1_9_schema_readability.py`)

```python
def check_v1_9_plan(raw: object, *, generator_ref: GeneratorRef, attempt) -> tuple[CheckResult, ClaimPlan | None]
def check_v1_9_envelope(raw: object, *, attempt) -> tuple[CheckResult, RenderedResponse | None]
def readability_grade(rendered: RenderedResponse) -> float
def check_v1_9_readability(rendered, *, v1, attempt) -> CheckResult
```

- **Plan schema.** `ClaimPlan.model_validate(raw.model_dump(mode="json") if BaseModel else raw)` (`extra="forbid"`); a failure or a generator exception gives `claim_plan_invalid`; another generator gives `generator_mismatch`.
- **Envelope.** The same coercion to `RenderedResponse`, so a `model_construct`-built object is re-validated; a failure gives `response_envelope_invalid`.
- **Readability (`fk-grade-segments-v1`).** Over the non-citation segments: words are `ALPHA_PATTERN` matches over NFKC text; sentences are the segment count (at least 1); syllables are vowel groups less a final silent `e` (not after `le` or `ee`), at least 1; `grade = round(0.39*wps + 11.8*spw - 15.59, 3)`. Below `readability_min`: `flag` / `below_band`; above `readability_max`: `above_band`; else `within_band`. The provisional band [−4.0, 64.0] contains the M6 envelope, so it changes no outcome until Q-22 sets it.

### 4.11 Runner (`v1_checks/runner.py`) and the Phase 3 hooks it uses

```python
@dataclass(frozen=True)
class V1Context: resolved: ResolvedQuestion; lesson_slug: str | None; presentation: PresentationPlan; legacy_decision: str | None
@dataclass(frozen=True)
class V1Run: decision: V1Decision; record: VerificationRecord; plan: ClaimPlan | None; bind: BindingCheck | None
             locked: LockedClaimSet; rendered: RenderedResponse | None; presentation: PresentationPlan; latency_ms: float
             proposed: int; dropped: Counter; scores: dict
class V1Track:
    def __init__(self, pipeline, *, checker=None, keyed_items=None, library=None, v2_hook=None, v1=None, clock=time.monotonic): ...
    def run(self, ctx, bundle, envelope, *, envelope_reason=None, first_raw=_UNSET, budget_over, mode, phase3_decision) -> V1Run
```

**`V1Track.run`, step by step**
1. **V1.5** on `bundle.sufficiency`. On `abstain`, `V1Abstained` with the gate's reason and no attempts.
2. **No envelope**: `V1Abstained` with the pipeline's `no_envelope_reason` (or `budget_exceeded` when the retrieve budget ran out).
3. **Generation loop**, g = 1 .. 1 + `v1.max_generation_regenerations`; each attempt is a new candidate (nothing of the previous one is kept):
   1. `raw` is `first_raw` on g = 1 when given (shadow mode reuses Phase 3's raw proposal or its exception, which `run()` keeps), else `generator.propose(envelope)`, an exception becoming the raw value.
   2. **V1.9 plan.** A `hard_fail` regenerates, or after the last attempt gives `V1HardFail` / `claim_plan_invalid`. A valid plan stamps its generator on the (still empty) lock, as Phase 3's lock does. Zero claims: `V1Abstained` / `no_claims`.
   3. **Budget** (`generate`): `V1Abstained` / `budget_exceeded`, the claims counted as skipped (Phase 3's rule).
   4. **V1.1.** A `hard_fail` regenerates, or after the last attempt gives `V1HardFail` / `unresolvable_citation`, every claim of that candidate counted under `unresolvable_citation` (none is bound; 3.2).
   5. **V1.2.** No drafts: `V1Abstained` / `no_bound_claims`.
   6. **Lock**, exactly as Phase 3; then **budget** (`bind`).
   7. **V1.3.** `checker_unavailable`: `V1Abstained` / `checker_unavailable`.
   8. **V1.7, then V1.8.** The candidate is accepted.
   9. Before each regeneration, `budget_over("generate")` abstains with `budget_exceeded`.
4. **Withheld set**: V1.3-flagged ∪ V1.8-flagged ∪ the claims of a withheld V1.7 conflict. If it covers every claim, `omit = ∅` (every claim rendered, recorded, never deliverable); else `omit` = the withheld set.
5. **Render loop.** `render_checked(pipeline.renderer, locked, ctx.presentation, max_regenerations=v1.max_render_regenerations, over=..., post_render=hook, omit=omit)`. Each attempt's output is coerced with `check_v1_9_envelope` (an invalid one is passed to the hook as `envelope_error`, not a fault, and not subset-checked); otherwise it is subset-checked through `pipeline.check_subset`. The hook records V1.4 `render_failed` for a faulted attempt, `response_envelope_invalid` for an invalid envelope, and otherwise, in order, V1.9 envelope, V1.4, V1.6 (items computed once from `ctx.resolved.text`) and the V1.9 band; the attempt is accepted iff all four pass. A V1.6 failure sets the next presentation to `socratic` and adds the keyed claims to `omit`, or stops. The abstention reason is that of the last rejected attempt that was not a fault:

   | Last rejection | Abstention reason | Decision |
   |---|---|---|
   | subset check failed | `subset_check_failed` | `V1HardFail` |
   | V1.6 | `keyed_answer_leak` | `V1HardFail` |
   | V1.9 envelope | `response_envelope_invalid` | `V1HardFail` |
   | V1.9 band | `readability_out_of_band` | `V1Abstained` |
   | every attempt faulted | `render_failed` | `V1HardFail` |
   | budget | `budget_exceeded` | `V1Abstained` |

6. **Aggregate** (4.12), `consult_v2(self.v2_hook, decision)` (None in production), the `VerificationRecord`, then the metrics and log lines (10.3, 10.4).

**Phase 3 code changes the runner needs** (listed again in 7.3):
- **`pipeline.render_checked(...)`** gains keyword-only `post_render: Callable[[RenderAttempt], HookVerdict] | None = None` and `omit: frozenset[str] = frozenset()`. With both at their defaults the code path is Phase 3's, unchanged (`test_v1_aggregate_and_runner` compares it with Phase 3's text over 300 fault schedules). `renderer.render(..., omit_claim_ids=omit)` is passed only when `omit` is non-empty. `RenderAttempt(attempt, presentation, omit, rendered, subset, fault, envelope_error)`; `HookVerdict(accept, next_presentation=None, next_omit=None, reason=None, stop=False)`.
- **`bind.bind(..., outcomes: list[str] | None = None)`** appends one entry per proposed claim: `"bound"`, `"merged"`, `"duplicate"` or the drop reason. The binding and `BINDING_RULE` are unchanged.
- **`TemplateRenderer.render(locked, plan, *, attempt, omit_claim_ids=frozenset())`** skips the omitted claims, numbers citations by first appearance among the claims it shows, and raises `ValueError` if every claim is omitted. `PEDAGOGICAL_PROMPT_HASH_INPUT` is unchanged (conflict 31).

### 4.12 Aggregation (`v1_checks/aggregate.py`)

**Per locked claim (accepted candidate):** `final = "deliver"` iff the passing rendering shows it and it has no V1.3 flag, no V1.8 flag, no withheld V1.7 conflict and was not omitted for V1.6; otherwise `"withhold"`. When the decision abstains, every claim is `"abstain"`.

**Claim V3 intent** (deliver and withhold verdicts): `v1_3_flag` when V1.3 flagged it; `v1_8_misconception` when V1.8 matched it; `x4_margin` (trigger `X4`) when V1.5 marked the response.

**Response:**

| Decision | `final` | `replacement` | `final_reason` |
|---|---|---|---|
| `V1HardFail` or `V1Abstained` | `abstain` | `none` | its abstention reason |
| `V1Passed`, at least one claim `deliver` | `deliver` | `none` | None |
| `V1Passed`, no claim `deliver` | `withhold` | from `ctx.legacy_decision`: `extractive_d19` (answer), `abstention` (abstain), `unknown` (None) | `conflict_withheld` if a withheld V1.7 conflict alone withheld every claim, else `d20_interim_withhold` |

- No "under review" label exists (D-20).
- The record rules refuse a `deliver` verdict for a claim with a non-pass result (invariant 6, 13.6; 3.2).

**Comparison (plan G):** `v1_outcome` = `abstain` if `final == "abstain"`, else `answer`; `agrees_phase3` against `phase3_decision` (shadow only; None in enforce); `agrees_legacy` against `ctx.legacy_decision`. Each disagreement logs `tutor.v1.disagreement` and increments a counter.

### 4.13 Pipeline integration (`tutor_pipeline/pipeline.py`)

- **Constructor.** `TwoPassPipeline.__init__` gains keyword-only `checker=None`, `keyed_items=None`, `misconceptions=None` and `v2_hook=None`. With a v3 package their defaults are `get_checker(package)`, `QuizKeySource(getattr(store, "quiz_keys", None) or QuizKeyStore(()))` and `load_library(package)`; it stores `self.v1_params` and `self.v1_clock` (the clock V1.3 times a call with; time.monotonic).
- **`PipelineInput`** gains `legacy_decision: Literal["answer", "abstain"] | None = None` (last field). **`PipelineResult`** gains `v1: V1Run | None = None` (last field).
- **`run()`** computes `mode = v1_checks.mode(self.settings, self.package)`, retrieves, and runs Phase 3 steps 2-3 (`_envelope`: the gate's abstention, the retrieve budget, the envelope):
  - **`off`**: Phase 3 exactly; `_entry()` builds a `LedgerEntry`.
  - **`shadow`**: the Phase 3 composition (`_propose(envelope, keep=raws)` keeps the generator's raw output or exception), then `V1Track.run(..., first_raw=<that raw>, phase3_decision=decision)`; `_entry_v2(..., mode="shadow")` with the Phase 3 fields and counts.
  - **`enforce`**: `V1Track.run(...)`; its plan, bind, locked set, rendering, presentation and counts fill the record (`_entry_v2`, mode `enforce`). The decision is `answer` iff the result is a `V1Passed`.
- **`_entry_v2`** builds a `LedgerEntryV2`: `ProvenanceV2(v1_3_checker_model_id=<the policy's checker>, …)`; claims with `entailment_score` (enforce only); `verification = run.record`; `PipelineCountsV2`.
- **Budget.** The shadow budget covers the V1 track (checks at retrieve, generate, bind, between render attempts and before each regeneration). An overrun logs `tutor.two_pass.budget_exceeded` when it is the record's own (Phase 3's composition, or the V1 track in `enforce`); in `shadow` the V1 track runs after the record's decision is fixed, so its overrun logs `tutor.v1.budget_exceeded` (`pipeline._over(..., event=)`) and only its verdict abstains. V1 latency goes to `V1_METRICS` and `tutor.v1.run`, never into the entry. The ledger append is unchanged.

### 4.14 Quiz keys (`app/services/quiz_keys.py`)

```python
@dataclass(frozen=True)
class QuizKey: id: str; lesson_slug: str; question_type: str; prompt: str; choices: tuple[str, ...]; answer: str; explanation: str
class QuizKeyStore:
    def __init__(self, keys: Iterable[QuizKey]) -> None
    def for_lesson(self, slug: str) -> tuple[QuizKey, ...]
    def all(self) -> tuple[QuizKey, ...]
class QuizKeySource:                      # V1.6 KeyedItemSource over a QuizKeyStore
    def items(self) -> tuple[KeyedItem, ...]
def score_attempt(keys: Sequence[QuizKey], responses: Mapping) -> tuple[int, dict[str, str], list[QuizFeedbackItem]]
```

`score_attempt` keeps only this lesson's question ids with string answers, each at most 2000 characters (the task 1.2 rule); the score counts exact matches against `key.answer`; feedback has one item per question in lesson order: an answered question (non-empty after `strip()`) gets `answered=True`, `correct`, `answer` and `explanation`; any other gets `answered=False` and no key. Nothing is logged. The rule is `FEEDBACK_RULE = "keys-after-saved-attempt-answered-only-v1"` (PD-21), which package v3 names in `v1.quiz_feedback` (provisional) and `package_check` compares. Residual: any answer counts as answered, so a caller that saves an attempt with a placeholder answer for every question gets every key of the lesson (DI-65).

### 4.15 Legacy guard (`v1_checks/legacy_guard.py`)

```python
@dataclass(frozen=True)
class GuardResult: contained: ContainedAnswer; withheld: tuple[tuple[str, str], ...]   # (check_id, reason_code)
def guard_contained(contained: ContainedAnswer, *, store, package, surface: Literal["tutor", "qa"], disclosure_shown: bool = False) -> GuardResult
def undisclosed_conflict(contained: ContainedAnswer, package) -> bool   # panel_conflicts' rule and inputs
```

1. An abstention passes. For each quotation (a `GroundedClaim`) and each span it cites:
   - **V1.1:** the span resolves current (`SpanResolver(store).resolve_current`) with the citation's content hash;
   - **V1.2 binding:** at least one span, and the quotation without a trailing `...`, whitespace collapsed, is a substring of the span's `normalize_display_text`;
   - **V1.2 polarity (E3, claim→span; only with a v1 block):** `quantities_covered(quotation, span)`, and every negation cue of the quotation is in the span at least as often.
   An answer with no quotation is withheld too (`no_bound_claims`).
   **V1.7 (AC-4-6; only with a v1 block):** when the caller shows no disclosure (`disclosure_shown` False; the orchestrator and the Q&A engine pass `EVIDENCE_PANEL_ENABLED`, off by default outside development) and V1.7 finds a conflict among the answer's quotations (`undisclosed_conflict`, `legacy_conflicts` over at least two quotations), the answer is withheld (`V1.7`, `conflict_withheld`). With the panel on, the panel labels the conflict instead. The default `False` is the conservative one.
2. Any failure withholds the whole answer: `ContainedAnswer(answer=ABSTENTION, decision="abstain", reason="no_approved_span", dropped_unresolved=…)`, the body bytes of today's abstention; it is counted (`V1_METRICS.legacy_guard`, `by_check` over V1.1, V1.2 and V1.7) and logged as `tutor.v1.legacy_guard_withheld` with `check_id`, `reason_code` and `surface`.
3. The guard has no flag and runs in every mode. Every current development quotation passes (M8), and no current development answer quotes conflicting passages (M7). Under D-31 nothing is quoted outside development. Without a v1 block it skips polarity and V1.7 (conflict 34; only a development build with governance off starts without one). The polarity rule runs claim to span only: a quotation may hold no number or cue its span lacks, so it never adds one, but an edge-cut quotation can omit one (M8, DI-60). It catches what verbatim binding cannot: a quotation that is a substring of its span but cuts a token, such as "12" out of "128" (`quantity_mismatch`) or "no" out of "not" (`negation_mismatch`).

### 4.16 Effective mode and start-up (`v1_checks/__init__.py`)

`mode(settings, package)` is `off` when `package.v1 is None` or `V1_UNAVAILABLE_REASON` is set, else `settings.v1_pipeline`. `V1_UNAVAILABLE_REASON` is set by the start-up check (10.1).

---

## 5. Configuration package v3 (`apps/api/app/config_package/v3.json`)

### 5.1 File

- v3 is a copy of v2 with `package_version "3.0.0"`, `schema_version 3`, `phase "4"`, `created "2026-11-20"` and `supersedes: {"package_version": "2.0.0", "sha256": "f35a4edf…7a42a", "readable_until": "the release after the Phase 4 merge"}`. Every other v2 block is unchanged except `abstention.provisional_until`, which is `"Q-22 (DI-52)"` (v2 says `"Phase 4"`; Phase 4 did not lift the provisional status, PD-15); `abstention` keeps `calibrated_with_package_version "1.0.0"`, and `retrieval_sha256` is unchanged.
- **`tutor_pipeline` changes:** `schemas` adds `LedgerEntryV2` (`ledger-entry-v2`, `schemas/ledger-entry.v2.schema.json`); `ledger.entry_schema` is `"ledger-entry-v2"`, with `"legacy_entry_schema": "ledger-entry-v1"` and `"entry_schemas": ["ledger-entry-v1", "ledger-entry-v2"]`; `unused_provenance_fields` is `["panel_weights_version", "routing_table_version", "tool_contract_version"]`; every prompt hash is v2's.
- **New block `v1`** (its values, all frozen and provisional where the plan gives none): `version "v1-checks-v1"`, `status "provisional"`, `provisional: true`, `rules_hash`, `rule_ids` (4.1), `ehmf` (the plan table), `regeneration` (2 generation, 2 render), `lexicon` (PD-20: the negation cues `cannot, neither, never, no, nobody, none, nor, not, nothing, nowhere, without`, the suffixes `n't`/`n’t`, 21 number words, the closed unit list `bit … μs`, `min_alignment_term_chars 2`), `v1_3` (`hosting "none"`, `checker_model_id "none"`, `support_threshold 0.5`, `timeout_ms 1000`, `unavailable "abstain"`), `v1_5` (`x4_margin {"bm25f-v1": 2.4, "p1-floor": 0.0}`), `v1_6` (`assessment_threshold 0.6`, `short_key_min_tokens 3`, `socratic_plan "socratic"`, `scope "all_lessons"`), `v1_7` (`alignment_threshold 0.6`, `min_alignment_terms 4`, `on_conflict "disclose"`, the family `qcai-lecture-2025-2026` over the two lecture video items), `v1_8` (library v0, empty, hashed; `on_match "flag_withhold_queue_v3"`), `v1_9` (band [−4.0, 64.0]), `quiz_feedback` (PD-21: `rule "keys-after-saved-attempt-answered-only-v1"`, `public_payloads "no_keys"`, `feedback "answered_questions_after_a_saved_attempt"`, provisional), `d20_interim` (`withhold-all-flagged-v1`, replacement `extractive_d19_else_abstention`), `fixtures` (`docs/evaluation/phase4/v1_adversarial_fixtures_v1.json`, `set_sha256`, `cases 66`, `public_corpus_only`), `stop` (`answer_rate_floor` `{"bm25f-v1": {"answered": 166, "in_domain": 174}, "p1-floor": {"answered": 146, "in_domain": 174}}` compared as `answered * floor.in_domain >= floor.answered * in_domain`; `composition` rule `v1-adds-no-in-domain-abstention-v1` under `deterministic_only`; `v1_p95_latency_ms 250`).
- **`flag_policy` adds** `"v1_pipeline": {"values": ["off", "shadow", "enforce"], "default_development": "enforce", "default_elsewhere": "shadow", "enforce_requires": "phase4_exit_passed", "off_outside_development": "refused", "authority": "plan Phase 4 G; 13.6; PD-19"}`. `phase4_exit_passed: false` and `phase4_exit_evidence: null` are unchanged.
- **`owner_decisions` adds** `D-20` (`state open`, `applied withhold-all-flagged-v1`, its 18.4 text, `ratified false`, record PD-13), `D-21` (`state open`, path none, record PD-14), `Q-22` (`state unresolved`, the provisional values `v1.v1_5.x4_margin`, `v1.v1_3.support_threshold`, `v1.v1_7`, `v1.v1_9.readability` and `v1.stop`, records PD-15, PD-16, PD-18, DI-52), `Q-14` (`state unavailable`, record DI-53) and `D-06` (`state open`, record DI-52).
- **New files:** `v3.json.sha256` and `schemas/ledger-entry.v2.schema.json`. No other file is added, so every package copy that carries `schemas/` stays complete. `v2.json`, `v1.json`, their sidecars and the 8 v1 schema files are byte-unchanged.

### 5.2 Loader (`app/core/config_package.py`)

- `DEFAULT_PACKAGE_PATH` is `v3.json`; `V2_PACKAGE_PATH` and `V1_PACKAGE_PATH` name the readable older packages.
- `schema_version in (1, 2, 3)`. Schema 3 applies every v2 rule with the schema names `TUTOR_SCHEMA_NAMES_V3`, `legacy_entry_schema == "ledger-entry-v1"`, `entry_schemas == ["ledger-entry-v1", "ledger-entry-v2"]` and the v3 unused fields (`ledger.entry_schema` is compared with the `LedgerEntryV2` contract by `package_check`, conflict 37).
- **`_parse_v1` refuses**: an unmarked provisional block (`v1`, `lexicon`, `v1_3`, `v1_5`, `v1_6`, `v1_7`, `v1_9`, `quiz_feedback`, `d20_interim`, `stop`); a `quiz_feedback` rule other than `V1_QUIZ_FEEDBACK_RULE`, `public_payloads` other than `no_keys` or `feedback` other than `answered_questions_after_a_saved_attempt`; `ehmf` other than the plan's; regeneration values outside 0-2; empty lexicon lists or lists that are not lowercase, sorted and unique (suffixes exempt); `hosting` not in `WIRED_CHECKERS`; `support_threshold` outside [0, 1]; `timeout_ms` outside 10-10000 or not below `budgets.shadow_ms`; `unavailable` other than `abstain`; an `x4_margin` other than `{"bm25f-v1": abstention.margin, "p1-floor": 0.0}`; `assessment_threshold` or `alignment_threshold` outside (0, 1]; `min_alignment_terms` outside 1-20; `short_key_min_tokens` outside 1-10; a `socratic_plan` that is not a presentation plan; a `scope` other than `all_lessons`; `on_conflict` other than disclose or withhold; a family with fewer than 2 distinct items, an item in two families, or more than 20 families; a library that is malformed, breaks the entry rules or whose `sha256` is not its canonical sha256; `on_match` other than `flag_withhold_queue_v3`; a band with `min_grade >= max_grade` or a bound outside [−50, 200]; answer-rate floors that are not integers with 0 < answered ≤ in_domain; another composition rule; `v1_p95_latency_ms` outside 1 to `shadow_ms`; a `fixtures` path that is absolute or holds `..`; a malformed `rules_hash` or `set_sha256`.
- **Owner decisions:** `D-20`, `D-21`, `Q-22`, `Q-14` and `D-06` must be objects; `D-21` open ⇒ hosting and model id `"none"`; `Q-14` unavailable ⇒ no library entries; `D-20` open ⇒ `d20_interim.rule == "withhold-all-flagged-v1"`.
- **`flag_policy.v1_pipeline`** (schema 3): its values; its defaults equal `V1_PIPELINE_DEFAULT_DEVELOPMENT` ("enforce") and `V1_PIPELINE_DEFAULT_ELSEWHERE` ("shadow"); `enforce_requires == "phase4_exit_passed"`; `off_outside_development == "refused"`.
- **`V1Params`** (frozen dataclass) holds every value, with `lexicon` as a frozen `V1Lexicon`, `version_families: Mapping[item_id, family]`, the library (version, sha256, entries), the fixture pin, the stop counts, `rules_hash` and `quiz_feedback_rule`. `ConfigPackage` gains `v1: V1Params | None = None`.

### 5.3 Package check (`v1_checks/package_check.py`)

`check_v1_package(package, *, structural) -> list[str]`. Always: `rules_hash` equals `v1_rules_hash(package)`; `rule_ids` equal `RULE_IDS`, V1.4's equal to `claim_gate.SUBSET_CHECK_RULE`; `SUBSET_PROBLEM_CODES == claim_gate.PROBLEM_CODES`; `REASON_OUTCOMES` is total over `bind`'s outcomes and the gate's reasons; the checker registry equals `WIRED_CHECKERS`; `v1.quiz_feedback_rule` equals `quiz_keys.FEEDBACK_RULE`. With `structural=True` only: the fixture file exists and its `set_sha256` and case count match the pin. The repository root is found only then (`repository_root()`, never at import): in the API image the module is `/app/app/services/v1_checks/package_check.py`, which has five parents and no checkout, and start-up imports it.

`tutor_pipeline/package_check.check_tutor_pipeline_package` is unchanged except for two schema-3 rules: `ledger.entry_schema` is compared with `LedgerEntryV2`'s literal, and `entry_schemas == sorted(ENTRY_SCHEMAS)`.

### 5.4 Scripts (`scripts/config_package.py`)

- **`--check`** also runs `check_v1_package(package, structural=True)` for schema 3 and prints the V1 summary line.
- **`--rehash`** for schema 3 also recomputes the library sha256, the fixture set sha256 and case count (from the fixture file), the `LedgerEntryV2` pin and `v1.rules_hash`.
- **`--write-schemas`** writes the pinned schemas (9 for v3); the 8 v1 files come out byte-identical in content. The default path is v3.
- CI checks v2 and v1 with `--path` (14).

---

## 6. Settings (`app/core/config.py`)

| Setting (env) | Type / default | Freeze rationale |
|---|---|---|
| `V1_PIPELINE` | `Literal["off", "shadow", "enforce"] \| None = None`. `None` means `"enforce"` in development and `"shadow"` elsewhere (`V1_PIPELINE_DEFAULT_DEVELOPMENT`, `V1_PIPELINE_DEFAULT_ELSEWHERE`, which v3 `flag_policy.v1_pipeline` must name). | Plan G: "flag v1_pipeline shadows the legacy gate, logging disagreements, then enforces". It acts only on the two-pass shadow pipeline (R-a), so no learner sees a change. |

**Validator additions** (after the `two_pass_tutor` block):
- Not development and `v1_pipeline == "off"`: `ValueError` ("V1_PIPELINE=off is refused outside development (plan 13.6: no flag may disable V1). Use shadow."). The package is not read.
- Not development and `v1_pipeline == "enforce"`: the package is read lazily, as for `two_pass_tutor` on; refused while `phase4_exit_passed` is false, and unless the package is the shipped, hash-verified one.
- In development, `enforce` is the default and is allowed.

**`main._record_configuration_overrides`** adds `("v1_pipeline_enforce", settings.v1_pipeline == "enforce")`; under production defaults its details are unchanged.

**`infra/cloudrun/api-production.env.example.yaml`** sets `V1_PIPELINE: "shadow"` with its rationale.

---

## 7. File-by-file changes

### 7.1 NEW `apps/api/app/services/v1_checks/`

| Module | Contents |
|---|---|
| `__init__.py` | `mode()`, `V1_UNAVAILABLE_REASON`, lazy re-exports |
| `rules.py` | 4.1 (`RULE_IDS`, constants, `v1_rules_hash`, `WIRED_CHECKERS`) |
| `lexicon.py`, `results.py` | 4.1 |
| `v1_1_resolution.py` … `v1_9_schema_readability.py` | 4.2-4.10 (one module per check) |
| `aggregate.py` | 3.3, 4.12 |
| `runner.py` | 4.11 |
| `legacy_guard.py` | 4.15 |
| `metrics.py` | 10.3 |
| `package_check.py` | 5.3 |

**Import rule** (13.1 test 30): no `v1_checks` module imports `learner_record`, `learner_progress`, `learning_intelligence`, `microlearning`, `app.core.auth`, `app.api.routes.*`, `answer_history` or `retrieval_legacy_p1`. The logger is `logging.getLogger("qcai.tutor")`.

### 7.2 MOD `tutor_pipeline/contracts.py`

3.1 and 3.2, and the `ACCEPTED_ABSTENTION_REASONS` lookup in `LedgerEntry._rules`. `TWO_PASS_DELIVERY_IMPLEMENTED` stays `False`; its comment says the Phase 4 exit sets it with the delivered path (DI-59). The `EvidenceBundle.conflicts` message names the verification record (conflict 8).

### 7.3 MOD Phase 3 modules (each change is required by a V1 check)

| File | Change | Why |
|---|---|---|
| `tutor_pipeline/pipeline.py` | `render_checked` hook parameters and `_render_with_hook` (4.11); `_propose(keep=)`; `_envelope`; `PipelineInput.legacy_decision`; `PipelineResult.v1`; `RenderAttempt`, `HookVerdict`; constructor injections and `v1_clock`; mode dispatch; `_entry_fields`, `_entry_v2`, `_finish` | E2, E10, E11 |
| `tutor_pipeline/bind.py` | `outcomes` keyword | V1.2 per-claim results |
| `tutor_pipeline/render.py` | `omit_claim_ids` keyword; Protocol doc | V1.6 Socratic omission, D-20 omission |
| `tutor_pipeline/shadow.py` | `ShadowJob.legacy_decision` (last field), passed into `PipelineInput`; docstring item 2 and the `on_downgraded` message name the Phase 4 exit | plan G comparison; P2-12-D-03 |
| `tutor_pipeline/package_check.py` | Schema-3 ledger rules (5.3) | v3 |
| `claim_gate.py` | Docstring: this check is V1.4 | P2-12-D-03 |

### 7.4 MOD `app/services/tutor_orchestrator.py`

After `contain_answer(...)`, `contained = guard_contained(contained, store=self._store(), package=get_config_package(self.settings), surface="tutor", disclosure_shown=self.settings.evidence_panel_enabled).contained` before anything reads it (citation SLIs, messages, `TutorTurn`, ledger follow-up, response). `_shadow_followup` passes `legacy_decision=contained.decision`. With `EVIDENCE_PANEL_ENABLED`, the panel gets `conflicts=panel_conflicts(contained, package)`. `TeachingAssistantService.chat`'s own internal containment is never delivered (the orchestrator re-contains), so it needs no guard.

### 7.5 MOD `app/services/qa_engine.py`

The same guard (`surface="qa"`, `disclosure_shown=self.settings.evidence_panel_enabled`) before the response, the Q&A row and the ledger record, and the same panel conflicts.

### 7.6 MOD `app/services/evidence_panel.py`

`build_evidence_panel(..., conflicts: list[EvidenceConflict] | None = None)` (labels only) and `panel_conflicts(contained, package)` (4.8).

### 7.7 MOD `app/services/content_assembler.py`

`_build_quiz` returns `(list[QuizQuestion], list[QuizKey])`; `CourseStore` gains `quiz_keys: QuizKeyStore`; `LessonDetail.quiz_questions` holds the public questions; `admin/rebuild-content` rebuilds both through the same constructor.

### 7.8 MOD `app/api/routes/content.py`

`_score_quiz` is replaced by `quiz_keys.score_attempt`; `record_quiz_attempt` has `response_model=QuizAttemptResult` and returns `QuizAttemptResult(attempt_id, score, feedback)`; mastery uses `len(keys)`; the keys come from `get_course_store().quiz_keys.for_lesson(slug)`.

### 7.9 MOD `app/services/ledger.py`

- `_provenance_problems(seq, entry, params, v1)`: `v1` is the package's v1 block, passed by every caller (no default, so no call skips the check); a two-pass v2 record must also have `provenance.v1_3_checker_model_id == v1.checker_model_id` and `verification.policy.rules_hash == v1.rules_hash` (a v2 record under a package without a v1 block is a problem).
- `pending_v3_intents(db, *, after_seq=0, limit=1000) -> list[dict]`: read-only; filters `entry_schema == 'ledger-entry-v2'` in SQL and parses in Python; one `{"seq", "response_id", "claim_id", "reasons", "trigger"}` per v2 claim verdict with a V3 intent; no text.
- Verification, export and restore need no change (dispatch).

### 7.10 MOD `app/main.py`, `app/core/config.py`, `app/core/config_package.py`, `app/schemas.py`

Sections 5, 6, 10 and 3.4.

### 7.11 NEW scripts and data

`scripts/run_v1_fixtures.py` (12); `docs/evaluation/phase4/v1_adversarial_fixtures_v1.json`; `docs/evaluation/phase4/v1_fixture_report_v1.json`; `docs/evaluation/phase4/README.md`.

### 7.12 `scripts/replay_tutor_plans.py`

No code change. Its record is re-written (`--write`) because the package is v3 and the replayed modules changed. Under the replay's production settings V1 runs in shadow, so the decision, hash-equality and count columns equal the Phase 3 values (governed 0 answered; all-approved 148 and 130; 0 mismatches). Each configuration's `items_digest` differs, because every lock hashes its own stamp: the package version (3.0.0) and, for a valid plan with no claims, its generator.

### 7.13 Frontend (11)

### 7.14 Text that describes the code (P2-12-D-03; no behaviour change)

- `docs/architecture/phase3-implementation-spec.md`: section 3's full `EvidencePanel` listing carries the `conflicts` line (`test_k3`); the two sentences that said Phase 4 sets `TWO_PASS_DELIVERY_IMPLEMENTED` with its V1 module say that delivery waits for the Phase 4 exit (DI-59) while V1 runs in the shadow.
- `tutor_pipeline/contracts.py` (the delivery flag comment and the bundle message), `tutor_pipeline/shadow.py`, and the `claim_gate.py` docstring.

### 7.15 Other files the phase changes

| File | Change |
|---|---|
| `app/services/demo_seed.py` | `REPO_ROOT = manifest_v2.repository_root()`: bounded, because the API image's `/app/app/services/demo_seed.py` has fewer parents than a checkout (no module computes a parent at import that its image path lacks, `test_no_image_module_computes_a_parent_its_image_path_lacks_at_import`) |
| `scripts/calibrate_abstention.py` | `--check` prints the package's `abstention.provisional_until` (`Q-22 (DI-52)` for v3); its docstring says so |
| `scripts/config_package.py` | 5.4 |
| `.github/workflows/ci.yml` | 14 |
| `infra/cloudrun/api-production.env.example.yaml` | `V1_PIPELINE: "shadow"` (6) |
| `.gitattributes` | This spec is stored LF, as the Phase 2 and Phase 3 specs are |

---

## 8. Database

- **No migration.** No column or table is added (M12, conflict 27). `ledger.SCHEMA_REVISION` is unchanged.
- `ledger-entry-v2` rows go into `response_ledger` as canonical JSON, exactly like v1 rows; legacy records stay `ledger-entry-v1`.
- A mixed v1 and v2 chain verifies, exports and restores on SQLite and on PostgreSQL under psycopg and pg8000 (13.1 test 19).
- **Erasure:** unaffected. V2 rows hold no learner identifier and no learner text; verdicts hold enums and content-addressed ids only; the comparison holds the legacy decision only. Quiz feedback is not stored; `QuizAttempt` rows are already covered by erasure.
- **Rollback by digest:** an earlier image cannot validate v2 rows, so its `verify_response_ledger` reports an unknown entry schema. Before such a rollback the runbook (15.5) has the operator take `python -m app.workers.response_ledger --export`. Production writes no v2 rows while `TWO_PASS_TUTOR` is off.

---

## 9. Routes and request-path behaviour

| Path | Outside development | Development |
|---|---|---|
| `GET /content/lessons/{slug}`, `GET /content/modules/{slug}` | No `answer` or `explanation` on quiz questions; otherwise unchanged. Strictly less disclosure; ships with a D-05 release. | Same |
| `POST /content/quiz-attempts` | `{status, attempt_id, score}` as before, plus `feedback` (keys only for answered questions) | Same |
| `POST /assistant/chat`, `POST /tutor/turns`, `POST /qa/ask` | Legacy guard runs: V1.1, V1.2, and V1.7 (the panel is off, so an answer quoting conflicting passages is withheld); bytes unchanged on every current answer (M7, M8; under D-31 nothing is quoted) | V1.1 and V1.2; with the panel on (the default), panel `conflicts` when V1.7 finds one (labels) |
| Shadow pipeline | Off (`TWO_PASS_TUTOR` off) | V1 `enforce` on the shadow run; nothing reaches a learner |

No route is added, and the authorization matrix is unchanged.

---

## 10. Start-up, `/ready`, logs and SLIs

### 10.1 Start-up

`main._check_tutor_pipeline_package` first runs `_check_v1_package(package)`: `check_v1_package(package, structural=False)` when `package.v1` is set, else the problem "no v1 block". It reads only the package and in-memory code values, and writes nothing.
- **A governed build, and any build outside development whatever its governance setting:** any problem raises `ConfigPackageError("v1 checks: …")`, a package without a v1 block included (conflict 34), before any table.
- **Development with governance off:** `v1_checks.V1_UNAVAILABLE_REASON` is set and `tutor.v1.unavailable` (WARNING) is logged; the two-pass V1 mode becomes `off` (`/ready` `v1_pipeline` `off`, `v1.available` false), and the legacy guard still runs.

### 10.2 `/ready`

`_build_fields()` adds the following (deterministic, no database read; the start-up log carries the same fields):

```json
"v1_pipeline": "enforce|shadow|off", "v1_pipeline_setting": "enforce|shadow|off",
"v1": {"version": "v1-checks-v1", "rules_hash": "…", "checker": {"hosting": "none", "model_id": "none"},
       "misconception_library": {"version": "v0", "entries": 0, "sha256": "…"}, "fixtures_set_sha256": "…",
       "regeneration": {"generation": 2, "render": 2}, "readability_band": [-4.0, 64.0], "x4_margin": {"bm25f-v1": 2.4, "p1-floor": 0.0},
       "stop": {"answer_rate_floor": {"bm25f-v1": "166/174", "p1-floor": "146/174"}, "v1_p95_latency_ms": 250},
       "quiz_feedback": {"rule": "keys-after-saved-attempt-answered-only-v1", "provisional": true},
       "provisional": true, "available": true, "legacy_guard": "on"}
```

`v1_pipeline` is `v1_checks.mode(settings, package)`: the mode the two-pass shadow pipeline's V1 track runs in (`off` when the start-up check found a problem, else the setting). It acts only while `TWO_PASS_TUTOR` is not `off`, so production reports `shadow` while it runs no V1 track. `v1` is `null` with a v1 or v2 package. `slis` is unchanged: no per-run V1 outcome and no guard count is public (conflict 29).

### 10.3 Metrics (`v1_checks/metrics.py`; locked counters)

`V1_METRICS.detail_snapshot()`: `runs` by mode; `finals`; `checks` (check → outcome → count); `hard_fail_rate` (per check, the runs in which it hard-failed at least once over the runs in which it ran: `metrics.hard_failed_checks` and `metrics.checks_run`, which the fixture report's `per_check` also uses, and which the runbook's log-based metric states); `citation_resolution` (`checked`, `resolved`, `rate`) over the span ids of delivered verdicts; `v1_3` (`claims_checked`, `flagged`, `flag_rate`, `unavailable`); `latency_ms` (`buckets` 1-1000 ms and `+Inf`, nearest-rank `p95` over the last 1024 runs, `budget` from the package, `stop = p95 > budget`); `disagreements` (`phase3`, `legacy`); `v3_intents`; `legacy_guard` (`checked` and `withheld` per surface, `by_check` for V1.1, V1.2 and V1.7). There is no public snapshot.

### 10.4 Log events (logger `qcai.tutor`; enums, counts and hashes only; no text, no ids)

| Event | Fields | Severity |
|---|---|---|
| `tutor.v1.run` | `mode`, `final`, `final_reason`, `hard_fail`, `generation_attempts`, `render_attempts`, `cycle_count`, `outcomes` (check → outcome → count), `flagged_claims`, `v3_intents`, `disclosure` (bool), `latency_ms`, `gate` | INFO |
| `tutor.v1.disagreement` | `with` (`phase3`\|`legacy`), `v1_outcome`, `reference` | INFO |
| `tutor.v1.checker_unavailable` | `cause`, `error` | WARNING |
| `tutor.v1.legacy_guard_withheld` | `check_id`, `reason_code`, `surface` | WARNING (a V1.1 or V1.2 failure is an upstream defect; V1.7 `conflict_withheld` is an answer quoting conflicting passages with no panel shown) |
| `tutor.v1.unavailable` | `reason` (a development build with governance off only; every other build stops) | WARNING |
| `tutor.v1.budget_exceeded` | `step`, `elapsed_ms`, `budget_ms`: in `shadow`, the V1 track overran after the record's decision (4.13) | WARNING |

---

## 11. Frontend (`apps/frontend`)

| File | Change |
|---|---|
| `src/lib/types.ts` | `QuizQuestion` has no `answer` or `explanation`. `QuizFeedback = {question_id; answered; correct; answer; explanation}`. `QuizAttemptResult.feedback?: QuizFeedback[]`. `EvidencePanelPayload.conflicts?: Array<{kind; passages: number[]}> \| null`. |
| NEW `src/lib/quiz-feedback.ts` | `publicQuestions(questions)` keeps exactly `id, question_type, prompt, choices, difficulty`. `feedbackFor(questionId, result \| null)` gives `{state: "none" \| "unanswered" \| "correct" \| "incorrect"; answer?; explanation?}`; a result without `feedback` (an older API) gives `"none"`. `resultLabel(question, feedback)` gives the result line, or null without one: for a question with no choices it names the exact-match result, never "Not correct". |
| `src/app/quiz/[lessonSlug]/page.tsx` | Passes `publicQuestions(lesson.quiz_questions)` to `QuizPanel`. Hero text: "Work through the questions, then save an attempt to see the model answers and rubrics." |
| `src/components/quiz-panel.tsx` | No client score, no "Reveal rubric", no "Auto-score". Keeps "Answered: n / N", `recordQuizAttempt(lessonSlug, answers)`, the textarea `aria-label` and "Recorded score: {savedAttempt.score} / …". After saving, each answered question shows its result line from `resultLabel` (a choice item: "Correct" or "Not correct"; a short answer, which the server scores by exact string match: "Matches the model answer" or "Does not match the model answer exactly"), "Model answer: {answer}" and the explanation from `feedbackFor`; an unanswered one "Answer this question and save an attempt to see its rubric."; each question's input names its feedback (`aria-describedby` to `quiz-feedback-{id}`), and the save error and "Saved attempt #n. Recorded score: … Feedback is shown under each question." are in an always-rendered `role="status"` `aria-live="polite"` region (WCAG 2.1 4.1.3: the feedback arrives after a network call). The short-answer note reads "Short answers are scored on the server by exact match; use the model answer shown after saving for final judgment." |
| `src/lib/evidence-panel.ts` | `CONFLICT_TEXT` for the three kinds ("Passages {a} and {b} …"); `evidencePanelView` gains `conflicts: string[]`. |
| `src/components/evidence-panel.tsx` | Renders `<ul className="assistant-evidence-conflicts">` when `view.conflicts.length`. |
| `src/app/globals.css` | `.assistant-evidence-conflicts` in `var(--ink)`, at least 4.5:1 on the panel in both themes. |

**Production.** The quiz change ships to production: less disclosure, plus post-attempt feedback, with a short answer's result labelled as the server's exact match. Panel `conflicts` appear in development only (outside development the API withholds an answer quoting conflicting passages instead, 4.15). Frontend first: at once no key reaches page HTML (`publicQuestions`); lesson JSON from the old API still carries keys until the API deploys and caches expire (API max-age 300 + stale-while-revalidate 60, and the Next revalidate window). Then the API: keys leave every public payload. `feedbackFor` tolerates the older API. A rollback runs in the reverse order, the API first: the pre-Phase-4 panel against the Phase 4 API would score an empty quiz N/N (`undefined === undefined`) and show a blank model answer (the runbook).

---

## 12. Adversarial fixtures and report (E13)

### 12.1 Fixture file `docs/evaluation/phase4/v1_adversarial_fixtures_v1.json`

Public-corpus only, never ULQS: the runner refuses `lqs/` paths. The fixture holds no corpus text: attacked sentences are taken from the store at run time, and its own sentences are synthetic. Its queries are the project's public fixture queries (`score_floor_queries.json`, whose in-domain items are the authored curriculum's learner questions) and four short synthetic keyword queries (one `unit_swap` case; the three `conflict_version` cases), because the in-domain list holds too few claims with a lexicon unit and no envelope with both fixture-family items.

```json
{"fixture_set": "qcai-v1-adversarial", "format_version": 1, "public_corpus_only": true,
 "excluded_sources": ["private plane", "lqs/ (ULQS)", "learner records, tutor turns, ratings"],
 "evidence_class": "fixture measurements, not research results (plan Phase 4 H)",
 "fixture_package": {"v1_7.version_families": [{"family": "fixture-2025-2026", "item_ids": ["analyzing-quantum-computing-and-ai-paper-2025", "quantum-computing-ai-research-synthesis-2026"]}],
                     "v1_3.timeout_ms": 50, "note": "test-only family: the manifest does not relate these items"},
 "fixture_keys": [{"item_id": "fixture-key-1", "prompt": "<a fixture query>", "key": {"from_query": "<the same query>", "claim": 0}}],
 "fixture_library": [{"id": "MC-FIXTURE-1", "terms": ["…", "…"]}],
 "cases": [{"id": "neg-strip-01", "class": "stripped_negation", "level": "pipeline", "query": "<public fixture query>",
            "attack": {"kind": "claim_transform", "transform": "strip_negation"}, "expect": {"caught_by": ["V1.2"]}}]}
```

**Classes (66 cases):**

| Class | Cases | Attack |
|---|---|---|
| `stripped_negation` | 5 | Strips a negation cue from the first claim holding one |
| `inserted_negation` | 5 | Inserts "not" after the first auxiliary |
| `number_swap` | 5 | Adds 1 to the first number |
| `unit_swap` | 5 | Changes the first lexicon unit (or `%`) after a number, by a fixed table |
| `fabricated_sentence_generator` | 5 | The generator adds a synthetic sentence citing a real bundle span |
| `fabricated_sentence_renderer` | 3 | The renderer adds an unmapped sentence on every attempt |
| `unresolvable_span_id` | 5 | Well-formed nonexistent, malformed or upper-case-hex ids |
| `conflict_version` | 3 | Pipeline level: one sentence from each fixture-family item (`compose_from_items`) |
| `conflict_number` | 3 | Check level: a real claim and its number-swapped twin on a synthetic second item |
| `conflict_negation` | 3 | Check level: a real claim and its negated twin |
| `keyed_answer_leak` | 3 | A fixture key equal to claim 0 of a query that locks at least two claims |
| `out_of_scope` | 10 | The first 7 off-topic and the first 3 stopword-only items |
| `checker_unavailable` | 2 | A raising checker and a late checker (injected clock) |
| `invalid_schema` | 3 | A plan with an extra field, a plan naming another generator, a renderer returning an invalid envelope |
| `misconception` | 3 | A fixture library entry matching a real claim (two of its terms) |
| `residual_paraphrased_contradiction` | 3 | Check level: a low-alignment negated paraphrase |

- A case whose query does not realise its attack makes `--check` and `--write` exit 1 naming the case (`Unrealisable`).
- `case_sha256 = canonical_sha256(case)`; `set_sha256 = canonical_sha256(sorted(case_sha256s))`. Both `set_sha256` and `cases` are pinned in v3 `v1.fixtures`.

### 12.2 Runner `scripts/run_v1_fixtures.py`

```
python scripts/run_v1_fixtures.py --write docs/evaluation/phase4/v1_fixture_report_v1.json [--allow-dirty]
python scripts/run_v1_fixtures.py --check docs/evaluation/phase4/v1_fixture_report_v1.json [--fixtures PATH]
```

- **Setup.** All-public-approved stores in a `tempfile` directory (only the temporary manifest is written there), with `Settings(environment="development", enforce_corpus_governance=True, corpus_manifest_path=…, retrieval_gate=…, two_pass_tutor="shadow", v1_pipeline="enforce")` and a `v1_pipeline="off"` twin over the same store. Cases run under `bm25f-v1`; the answer-rate block under both gates. The fixture overlay (the family, the 50 ms timeout) is applied in memory to `V1Params`; no package is written. The report names the shipped package and the overlay's sha256.
- **Checker configurations:** (a) `production`: `NullChecker`; (b) `deterministic_only`: the script's `AlwaysSupportedChecker` (`fixture-always-supported`). A case's own checker overrides either.
- **`delivered`**, per case: claim transforms and generator fabrications, a delivered claim's text equals the attacked text; renderer fabrication, `final == "deliver"` and the rendering holds the sentence; unresolvable, `final != "abstain"` and a delivered claim cites the bad id; version conflict, `final == "deliver"` with no disclosure, or a delivered involved claim under withhold; keyed, the accepted rendering holds the key; out-of-scope, checker and invalid schema, `final != "abstain"`; misconception, the matched claim's verdict is `deliver`; check-level cases, no disclosure and V1.3 (under the configuration's checker) does not flag the claim.
- **Exit codes:** 0 pass; 1 drift or an unrealisable case; 3 a stop (a gate's V1.5 answered count below its floor, V1's in-domain answered count under (b) below the V1-off composition count, or p95 above `v1_p95_latency_ms`); 4 a dirty tree on `--write`; 5 a non-residual case delivered in either configuration, a residual delivered in (a), a delivery in (a), or an expected check missing under (b).
- **`--check`** compares a fresh run with the record, ignoring `created_at`, `commit` and every `latency` value; latency is compared with the budget only. `evaluate(report, package)` gives the result and its problems, so a test can apply a package's stop conditions to a computed report.

### 12.3 Report shape

```json
{"report": "qcai-v1-fixture-report", "format_version": 1, "created_at": "…", "commit": "…",
 "evidence_class": "fixture measurements, not research results (plan Phase 4 H)", "public_corpus_only": true,
 "fixtures": {"path": "…", "set_sha256": "…", "cases": 66}, "config_package": {"version": "3.0.0", "sha256": "…"},
 "fixture_overlay_sha256": "…",
 "configurations": [{"name": "production", "checker_model_id": "none", "per_check": {"V1.1": {"runs": 0, "hard_fail": 0, "hard_fail_runs": 0, "hard_fail_rate": null, "flag": 0, "abstain": 0, "mark": 0}},
    "v1_3_flag_rate": {"checked": 0, "flagged": 0, "rate": null}, "citation_resolution_delivered": {"span_ids": 0, "resolved": 0, "rate": null},
    "finals": {"deliver": 0, "withhold": 0, "abstain": 0},
    "classes": {"stripped_negation": {"cases": 5, "caught": 5, "catch_rate": 1.0, "wilson95": [0.5655, 1.0], "caught_by": {"V1.2": 5}, "delivered": 0}},
    "residual": ["residual_paraphrased_contradiction"], "cases": [{"id": "…", "case_sha256": "…", "final": "…", "final_reason": "…", "caught_by": ["V1.2"], "delivered": false, "realised": {"query_sha256": "…"}}],
    "expected_missing": [], "latency": {"p95_ms": 0.0, "budget_ms": 250, "within_budget": true}}],
 "answer_rate": [{"gate": "bm25f-v1", "in_domain": 174, "v1_5_answered": 166, "rate": "166/174", "wilson95": [0.9119, 0.9765],
                  "floor": "166/174", "phase2_baseline": "166/174", "off_topic": 124, "off_topic_v1_5_abstained": 124,
                  "composition_answered_v1_off": 147, "composition_answered_v1_b": 147, "composition_answered_v1_a_not_abstain": 147,
                  "composition_identical_b": 174}],
 "readability_envelope": {"min_grade": -3.4, "max_grade": 63.54, "band": [-4.0, 64.0], "contained": true},
 "latency": {"p95_ms": 0.0, "budget_ms": 250, "within_budget": true},
 "result": "pass", "problems": [], "inputs": {"rule": "imported-repository-modules-sha256-lf-v1", "files": {}, "sha256": "…"}}
```

- `wilson95` is the Wilson score interval with z = 1.959964, rounded to 4 places; null when n = 0.
- `per_check`: `runs` are the runs the check ran in; `hard_fail`, `flag`, `abstain` and `mark` count results; `hard_fail_runs` counts the runs in which it hard-failed at least once, and `hard_fail_rate = hard_fail_runs / runs` (10.3).
- `commit` is informational: the HEAD the record was written on, with `-dirty` when the tree differed (`--write --allow-dirty`, as the committed record is written before the commit that holds it); `inputs` is the provenance `--check` compares.
- `inputs` uses the replay's rule (every imported repository module's LF text sha256).
- **Report invariants** (AC-4-2 and the runner): every non-residual class is 100% caught in both configurations, and the residual class under (a) only (its three cases are delivered under (b); AC-4-2 holds for them only while V1.3 withholds every claim, DI-64); `composition_answered_v1_b == composition_answered_v1_off` and `composition_identical_b == 174`; `citation_resolution_delivered.rate` is 1.0 or null; under (a) `finals.deliver == 0`.

---

## 13. Tests

### 13.1 NEW `apps/api/tests/test_phase4_acceptance.py`

Fakes are in NEW `apps/api/tests/v1_fakes.py` (`AlwaysSupportedChecker`, `AlwaysContradictedChecker`, `RaisingChecker`, `WrongTypeChecker`, `LateChecker` on an `InjectedClock`, `ScriptedChecker`, `SupportedVoter`, `FixtureKeys`/`keyed_item`, `fixture_library`, `UnmappedRenderer`, `temp_package`, `dev_pipeline`, `run`). One module-scoped fixture runs `run_v1_fixtures.compute()` once for the tests that read the report.

**AC-4-1**
1. `test_ac_4_1_property_an_unresolvable_span_id_hard_fails_and_no_vote_changes_the_outcome`: `random.Random(20261120)`, 200 trials over answered dev queries; each plan holds 1-4 claims with at least one id replaced (random hex, malformed, upper case). `check_v1_1` hard-fails; the pipeline (enforce, always-SUPPORTED checker, `SupportedVoter` hook) abstains with `unresolvable_citation`, `hard_fail` true, 3 generation attempts, every V1.1 result hard_fail, the voter never called, and `consult_v2(voter, decision) is decision`.
2. `test_ac_4_1_a_hard_fail_is_typed_final_and_only_a_v1_passed_reaches_the_v2_hook`: the decision types; `V1Passed` refusing its own hard fails and accepting a dropped proposal's; `consult_v2`; the ledger refusing a delivered verdict with its own flag or a withheld conflict.
3. `test_ac_4_1_a_regenerated_candidate_is_judged_afresh_and_the_hard_failed_one_never_reaches_v2`.

**AC-4-2**
4. `test_ac_4_2_the_adversarial_set_fails_or_abstains_under_production_and_only_the_residual_class_is_delivered_with_a_perfect_checker` (every non-residual class caught under (a) and (b); the residual paraphrased contradiction withheld under (a) and delivered under (b), DI-64).
5. `test_ac_4_2_the_committed_fixture_report_matches_a_fresh_run_and_its_hashes_match_the_package` (the record equals a fresh run, the volatile fields and the imported-module map aside, whose hashes are checked against the checkout; the pins; the label; `lqs/` refused; only the manifest in the runner's temporary directory).
6. `test_ac_4_2_deterministic_checks_alone_catch_negation_number_fabrication_unresolvable_and_conflict_cases` (`negation_mismatch`, `quantity_mismatch`, `not_verbatim`, `unresolvable`, `unmapped_factual_sentence`, `conflict_disclosed`).

**AC-4-3**
7. `test_ac_4_3_out_of_scope_fixtures_abstain_under_v1_5_for_both_gates`.
8. `test_ac_4_3_the_in_domain_answer_rate_is_at_least_the_phase_2_baseline_for_the_same_gate` (the calibration record's counts; the v3 floors equal them as integers; a 167/174 floor is a stop).
9. `test_ac_4_3_v1_adds_no_in_domain_abstention_over_the_phase_3_composition` (174/174 identical per gate).

**AC-4-4**
10. `test_ac_4_4_an_unmapped_sentence_is_re_rendered_at_most_twice_then_only_locked_claims_remain`.
11. `test_ac_4_4_a_renderer_that_never_stops_adding_a_sentence_abstains_after_two_regenerations`.

**AC-4-5**
12. `test_ac_4_5_an_assessment_draft_with_the_keyed_answer_is_re_rendered_socratically_without_it` (checkers (a) and (b); the item named by id inside the turn; all-lessons scope).
13. `test_ac_4_5_a_draft_whose_every_claim_holds_the_key_abstains`.
14. `test_ac_4_5_no_public_content_payload_carries_a_keyed_answer` (course, modules, lessons, search, Q&A and chat bodies; OpenAPI).
15. `test_ac_4_5_the_quiz_attempt_returns_feedback_only_after_saving_and_only_for_answered_questions` (demo, guest and durable callers).

**AC-4-6**
16. `test_ac_4_6_conflicting_cited_spans_get_a_disclosure_block_or_are_withheld`.
17. `test_ac_4_6_the_evidence_panel_shows_the_disclosure_for_a_contained_answer`, with `test_ac_4_6_with_no_disclosure_shown_a_contained_answer_quoting_conflicting_spans_is_withheld` (`/assistant/chat` and `/qa/ask`: with the panel off the answer is today's abstention, logged and counted as V1.7 `conflict_withheld`; with it on, delivered with the panel's conflicts).

**AC-4-7**
18. `test_ac_4_7_an_unavailable_or_late_checker_makes_the_decision_abstain` (raising, wrong type, late on an injected clock).

**Plan G / L / D / I / H, invariants, freeze**
19. `test_plan_g_ledger_v2_is_additive_and_old_records_still_verify` (a mixed chain verifies; `verify_ledger.py --check-provenance` exits 0; export and restore round-trip; a tampered v2 entry is refused as `entry fails ledger-entry-v2`; `pending_v3_intents`; runs on the session dialect).
20. `test_plan_g_shadow_logs_disagreements_with_the_phase_3_decision_path`, with `test_plan_g_a_route_turn_s_shadow_record_compares_v1_with_the_decision_the_learner_received` (`/assistant/chat` and `/tutor/turns`: an answered, a guard-withheld and an off-topic turn; `comparison.legacy_decision`, `agrees_legacy` and the D-20 replacement on the route-produced shadow record).
21. `test_plan_l_v1_1_and_v1_2_are_enforced_on_every_delivery_path_in_every_mode`, with `test_plan_l_the_unforged_answer_is_byte_identical_across_modes`.
22. `test_plan_l_flag_back_to_shadow_restores_the_phase_3_decision_and_keeps_the_verdict`.
23. `test_plan_l_the_stop_conditions_are_named_in_package_v3_and_the_fixture_runner_exits_3` (a raised floor, a 1 ms budget against slow samples, a crippled V1 track).
24. `test_plan_d_the_digest_and_overlap_gate_paths_are_gone_and_stay_gone`.
25. `test_plan_d_hard_fail_is_typed_so_v2_cannot_be_consulted_and_v1_3_never_hard_fails`.
26. `test_plan_e_with_no_checker_v1_3_flags_every_claim_and_every_answer_is_withheld`.
27. `test_plan_d_thresholds_load_only_from_the_configuration_package`.
28. `test_plan_i_ready_reports_package_v3_and_the_v1_fields_and_no_shadow_outcome`.
29. `test_plan_i_v1_metrics_report_resolution_hard_fails_flag_rate_latency_and_disagreements`, with `test_plan_i_the_hard_fail_rate_per_check_has_one_definition_in_process_in_the_report_and_in_the_runbook` and `test_plan_i_the_runbook_names_every_configuration_override_the_api_records`.
30. `test_plan_h_and_ac_3_1_v1_checks_import_no_learner_module_and_hold_no_learner_state`.
31. `test_invariant_6_no_two_pass_text_reaches_a_learner_with_v1_enforcing`.
32. `test_freeze_production_bodies_are_unchanged_by_v1` (production settings over an all-approved store: `/qa/ask` bodies equal those with the guard replaced by identity, on 8 queries).
33. `test_settings_v1_pipeline_defaults_and_refusals` (defaults; production off and enforce refused; a package claiming the exit allows production enforce and records the override; start-up subprocesses, a production build with governance off and a v2 package included), with `test_start_up_a_v1_package_problem_turns_v1_off_only_in_development_with_governance_off` (10.1).
34. `test_phase4_spec_section_3_lists_the_code_s_fields`, with `test_phase4_docs_quote_plan_m_and_state_the_current_rules` (the plan M quote, the guard's claim-to-span rule, the synthetic query count, the rollback order), `test_phase4_docs_name_every_q_22_value_and_the_package_s_provisional_until` (16.2's DI-52 row and main.py's threshold comment), `test_phase4_docs_the_test_strategy_maps_every_test_module_the_phase_added` and `test_phase4_docs_the_spec_ends_in_one_review_history_table` (section 18 is one table; sections 0-17 carry no review-round narrative).

### 13.2 NEW unit test files

| File | Proves |
|---|---|
| `test_v1_1_resolution.py` | Each reason code; content-hash mismatch; empty-citation pass |
| `test_v1_2_binding.py` | The polarity table; closed units; tie-break; bind `outcomes`; claim ids; a forced polarity drop counted in `PipelineCountsV2`; `no_bound_claims`; totality |
| `test_v1_3_entailment.py` | NullChecker flags all with no call; mapping; threshold; unavailable checkers; never hard; `get_checker` refuses unknown hosting |
| `test_v1_4_subset.py` | Each code; faults; the codes equal the subset checker's; the patched `pipeline.check_subset` is V1.4's in shadow and enforce |
| `test_v1_5_abstention.py` | Gate reasons; mark and pass; p1-floor never marks; the X4 label and intents |
| `test_v1_6_keyed_answers.py` | Context by similarity (8 of 174 in-domain, 0 of 124 off-topic) and by id; all lessons; long and short keys; `keyed_claim_ids`; no key in any public span |
| `test_v1_7_conflicts.py` | Version family; number and negation disagreement; the min-terms filter; same item; disclose and withhold; legacy panel passages |
| `test_v1_8_misconceptions.py` | v0 empty and hashed; all-terms match; withhold and V3 intent; malformed libraries; entries refused while Q-14 is unavailable |
| `test_v1_9_schema_readability.py` | Plan and envelope schema; an invalid envelope reaching `render_checked`; syllables; FK vectors; band edges; templates inside the band |
| `test_v1_aggregate_and_runner.py` | The no-hook path equals Phase 3's on 300 fault schedules; cycle counts; replacements; omission; hook reasons; budget, and the event a V1-track overrun logs in shadow and in enforce; shadow and enforce records; a V1.1 hard-failed candidate's counts across modes; every record rule; result and intent validators |
| `test_v1_legacy_guard.py` | Every dev contained answer passes; each failure at its exact (check, reason); the polarity rule on verbatim quotations cut mid-number and mid-cue; truncation; counts; without a v1 block only the polarity rule is skipped; conflicting quotations withheld unless a disclosure is shown (V1.7) |
| `test_v1_fixtures.py` | Wilson vectors; determinism; unrealisable exit 1; a crippled check exit 5; `lqs/` refusal; no fixture string holds a 12-word shingle of a source document |
| `test_quiz_keys.py` | `score_attempt`; `QuizKeyStore`; the public/internal split; `/content/modules`; the rebuild constructor; the attempt route |
| `test_config_package.py` (additions) | `test_v2_stays_readable_for_one_release`; `test_v3_keeps_every_v2_value_but_the_listed_changes`; `test_v3_structural_errors_always_stop_the_load` (55 refusals); `test_package_check_v1_problems`; `test_the_v1_start_up_check_runs_from_the_image_layout` and `test_no_image_module_computes_a_parent_its_image_path_lacks_at_import` (the API image's `/app/app` paths) |
| `test_response_ledger.py` (additions) | v2 dispatch beside v1; the v2 provenance audit; `pending_v3_intents` |
| `test_python_sources.py` | No Python source raises a SyntaxWarning; no test reads outside the repository; no test reads one security event from a select without an order; each scan's sample test |
| `test_phase3_docs.py` (addition) | `test_k3_the_records_state_the_merge_and_the_cited_run_on_main`: the Phase 3 spec and the test strategy state the squash merge `078bc75` and the cited main run 44723513394 (DI-31 closed) |

### 13.3 Existing tests that change (intent kept; the commit message gives each reason)

1. **`test_config_package.py`:** the shipped package is "3.0.0"; `test_package_v2_keeps_every_phase_2_value_of_v1` reads `v2.json` itself (the default is v3); `test_v2_structural_errors_always_stop_the_load` applies its 24 Phase 3 refusals to `v2.json` and to the shipped v3 (its schema edit is "the next schema version", 3 for v2 and 4 for v3), so a schema-3 loader branch cannot drop one.
2. **`test_phase3_acceptance.py`:** `/ready` reports `PACKAGE.package_version`; `PACKAGE_FILE` is `DEFAULT_PACKAGE_PATH.relative_to(REPO_ROOT)`; the start-up test copies the default package under its own name and sidecar; the AC-3-1 signature scan allows `bind`'s `outcomes` and `TemplateRenderer.render`'s `omit_claim_ids` (neither is learner input).
2a. **`write_package` in `test_tutor_pipeline_package.py` and `test_configuration_overrides.py`, `test_phase3_acceptance.py::test_ac_3_6_on_forced_past_settings_still_runs_shadow_only`, `test_tutor_pipeline_package.py::_package_copy` and `test_tutor_pipeline_contracts.py::test_a_changed_schema_file_or_prompt_hash_is_a_package_problem`:** copy the shipped package under its own name (`v3.json`), not as `v2.json`; behaviour is unchanged (the loader dispatches on `schema_version`).
2b. **`test_phase2_acceptance.py`:** `test_plan_h_thresholds_are_provisional_until_phase_4` and the `/ready` test read `provisional_until` `"Q-22 (DI-52)"` from package v3 and `"Phase 4"` from v1, v2 and the calibration record.
3. **`test_tutor_pipeline_binding.py` (`test_i1_*`), `test_tutor_pipeline_rendering.py` (`test_j3_*`) and `test_response_ledger_provenance.py` (`_changed` and the generator edit):** validate with `ENTRY_SCHEMAS[entry_schema]`. `test_response_ledger_provenance.py`'s `test_l7_*` also passes the package's v1 block to `_provenance_problems` (7.9): its two-pass record is now a v2 record.
4. **`test_tutor_pipeline_rendering.py`, `test_d4_*`:** validates the edited payload with its own schema and matches each refusal's rule text, so it cannot pass on a schema-literal mismatch.
5. **`test_tutor_pipeline_invariants.py::_patch_entry`:** patches both record builders (`_entry` and `_entry_v2`).
6. **`test_configuration_overrides.py`:** `REFUSED_RELAXATIONS = {"v1_pipeline_enforce": …}` gives the new override key its own case (refused by Settings, still recorded when present).
7. **`test_tutor_retrieve_bind_lock.py`:** the lock stamp is `PACKAGE.package_version`.
8. **`test_api.py` and `test_authorization.py`:** read keys from `get_course_store().quiz_keys.for_lesson(…)`. Server scoring is unchanged. `test_authorization.py::test_a_role_denial_is_a_security_event` reads every matching `authz.denied` event `ORDER BY seq` and asserts exactly one, with its details (it read one row with `.first()` and no order).
9. **`test_rate_limit.py::test_repeated_failures_lock_the_email_even_for_the_right_password`:** reads the lockout events `ORDER BY seq` (their append order). Without it PostgreSQL may return rows in physical order, and the full suite under psycopg returned the two events out of order twice.
10. **`docs/evaluation/phase3/three_plan_replay_v1.json`:** re-written; decision, count and hash-equality columns unchanged (7.12).
11. **Expected unchanged and verified:** the Phase 2 `d9` tests; `test_structured_logging`; `test_security_log`; every Phase 3 doc-text test, with `test_k3` passing after 7.14; AC-3-6 tests; `calibrate_abstention.py --check`; every package-copy test; the frontend `quiz-scoring` and `accessibility` tests.

### 13.4 Frontend tests

- **NEW `tests/quiz-keys.integration.test.ts`:** `QuizQuestion` has no `answer` or `explanation`; the panel has no `question.answer`, `question.explanation`, "Reveal rubric", `=== question.answer`, "Auto-score" or `showResults`, and calls `feedbackFor(`; the page passes `publicQuestions(lesson.quiz_questions)`; `publicQuestions` drops an older payload's keys; `feedbackFor` maps none, unanswered, correct, incorrect and an older API's result; the save result and error are in a polite status region and each input names its feedback; `resultLabel` names a short answer's exact-match result and calls only a choice item correct or not, and the final-judgment note stays.
- **`evidence-panel.integration.test.ts` additions:** each `CONFLICT_TEXT`; conflicts rendered only when present; no "grounded"; the contrast of `.assistant-evidence-conflicts`.

### 13.5 Mutation checks (each must fail its test when reverted)

Each check below was applied, its test run and seen to fail, and the file restored byte for byte; the commit message of each change names the mutation checks of that change.
- **The checks:** V1.1 hard fail; V1.2 polarity, closed units and bind `outcomes`; the NullChecker's flag-all and unavailable→abstain; the V1.4 seam; V1.5 abstain and mark; V1.6 containment, id-in-text and all-lessons scope, and Socratic omission; V1.7 disclose and withhold; V1.8 match; V1.9 schema, envelope order and band.
- **Typed decisions and ledger rules:** the `consult_v2` guard; the `V1Passed` post-init and its V1.2 exemption; the deliver and withheld-conflict rules; `PipelineCountsV2`, the V1.1 candidate counts and the shadow count rule; the replacement rule.
- **The legacy guard:** V1.1 and V1.2; the polarity rule's quantity and negation cases and its skip without a v1 block; V1.7 with no disclosure shown (the guard's rule, each caller's `disclosure_shown`, the `V1.7` count).
- **Start-up, settings and package:** the image-layout root; the settings refusals; the refusal of a missing or wrong v1 block outside development, the development-only fallback and the mode's and `/ready`'s reading of it; the v3-only loader branch; the quiz rule pin.
- **Pipeline and metrics:** the legacy decision through the orchestrator and the shadow job; the V1-track budget event; the one hard-fail-rate definition.
- **Quiz keys and frontend:** the public `QuizQuestion`; `publicQuestions`; answered-only feedback; the live region and `aria-describedby`; `resultLabel`'s short-answer result and the final-judgment note.
- **Fixture runner:** drift; the stop exit 3.
- **Records:** the Q-22 values in DI-52 and the main.py comment; the Phase 3 records' merge and main run; the security-event order scan; the test strategy's Phase 4 file table; this spec's last section.

---

## 14. CI changes (`.github/workflows/ci.yml`, job `api-and-evaluation`)

After the v1 package check:

```yaml
      # Phase 4: configuration package v2 stays readable for one release (DI-63).
      - run: python scripts/config_package.py --check --path apps/api/app/config_package/v2.json
      # Plan Phase 4 F/H/K: the hashed adversarial fixture set and its report (fixture measurements, not research
      # results). Exit 3 is a plan L stop (answer-rate floor, V1 composition, or V1 p95 budget); exit 5 an adversarial
      # case delivered.
      - run: python scripts/run_v1_fixtures.py --check docs/evaluation/phase4/v1_fixture_report_v1.json
```

The PostgreSQL matrix jobs, the frontend job and `release-artifacts` are unchanged; the new tests run in both suites.

---

## 15. Docs and evidence

1. **This spec.** Section 4 is the plan F "V1 specification".
2. **ADR-005.** The title line is kept, followed by the dated status line (conflict 24); the 2025 sections and the Phase 3 revision stay verbatim; `## Decision 2026-11-20 (Phase 4: V1 deterministic validation)` states V1.1-V1.9 with their rule ids and EHMF types, HARD = final (typed), the modes and the shadowed path, the unflagged legacy guard, V1.3 none and the D-20 withholding with its replacement values, the V1.5 gate rule, V1.7 disclosure and its inert production family, the abstention reasons, and the residuals: plan M's "checker error, paraphrased leakage", with paraphrased contradiction as the implementation-defined case of checker error (DI-64), plus the legacy edge cuts, short keys and placeholder-answer key disclosure (DI-65).
3. **`docs/evaluation/phase4/README.md`:** reproduction, configurations, classes, Wilson intervals, "fixture measurements, not research results", residuals, the answer-rate block and the stops; no corpus text.
4. **`docs/testing/test-strategy.md`:** `## Phase 4 acceptance map (plan Phase 4 K)` after Phase 3, with `### Phase 4 test files`: every test module the phase added and what it proves (`test_phase4_docs_the_test_strategy_maps_every_test_module_the_phase_added`).
5. **`infra/cloudrun/deployment.md`:** `## Phase 4: V1 validation and quiz keys (runbook)` (D-05 cloud writes; shipped defaults; pre-release checks; frontend first, then the API, with the cache windows; `/ready` checks; stop conditions; rollback to `V1_PIPELINE=shadow`; the export before a digest rollback; the rollback order, the API first; the package-version notes of the Phase 2 and Phase 3 sections).
6. **`infra/cloudrun/observability.md`:** `## Phase 4 SLIs: V1 (plan Phase 4 I)`, the log-based metrics and alerts marked "Not set up yet" (DI-62).
7. **`infra/cloudrun/api-production.env.example.yaml`:** `V1_PIPELINE: "shadow"`.
8. **BEP-2-12** (outside the repository): `phase04/PHASE_RECORD.md` (current state first, then `## History`, one row per round); `phase04/CLOSURE_EVIDENCE_NOTES.md` (R-13, R-15, R-16, R-19, R-42, R-46); the register rows PD-13..PD-21 and DI-52..DI-65; `00_meta/STATUS.md` gains a `| 4 |` row; `00_meta/check_records.py`, run with the API virtual environment, checks the evidence package's wording (its Phase 3 records and registers, and the plan text the configuration package quotes) and exits 0 on the current records. No repository test reads outside the repository: those checks are the checker's, each named after the finding it guards.

---

## 16. Provisional defaults and deferred items (appended under `## Phase 4`)

### 16.1 Provisional defaults

| # | Decision | Plan text | Default applied | Where |
|---|---|---|---|---|
| PD-13 | D-20 interim V1.3 routing (PI); hold H15 | 18.4: "D-20 OPEN DECISION: before Phase 5 (no V2), V1.3-flagged claims at every tier are withheld, replaced by pre-verified module content or extractive mode [Decision D-19], else abstain, and queued for V3; no "under review" delivery without a completed V2 vote" | Its own text: every V1.3-flagged claim (and V1.8, conflict 17) is withheld; the replacement is the D-19 contained answer (`extractive_d19` or `abstention`); V3 intent on the record; no under-review label | v3 `v1.d20_interim`, `owner_decisions.D-20` |
| PD-14 | D-21 checker hosting (PO) | 18.4: "D-21 OPEN DECISION: hosting for the V1.3 checker and open-weight verifier, or none"; Phase 4 E: "if none, V1.3 flags everything" | `none`: NullChecker (`checker_model_id "none"`); the 1000 ms timeout applies to any future checker's result | v3 `v1.v1_3`, `owner_decisions.D-21` |
| PD-15 | Q-22 / D-06 thresholds (PI) | Plan L795-800 [PROV]; 18.4 Q-22 | X4 margin `bm25f-v1` 2.4 (= PD-04), `p1-floor` 0; V1.3 support threshold 0.5 (unused while none); V1.7 alignment 0.6, min terms 4, disclose | v3 `v1.v1_5`, `v1_3`, `v1_7` |
| PD-16 | V1.9 readability band (Q-22) | Phase 4 D: "V1.9 \| invalid schema HARD; outside band" | `fk-grade-segments-v1` band [−4.0, 64.0], the M6 envelope (changes no outcome until Q-22) | v3 `v1.v1_9` |
| PD-17 | V1.6 assessment rule (no plan value) | Phase 4 D: "V1.6 \| keyed-answer match -> HARD" | Similarity 0.6 (M5); id in text; all lessons; short keys under 3 tokens matched only as choice text | v3 `v1.v1_6` |
| PD-18 | Phase 4 stop conditions (Q-22) | Phase 4 L: "Stop below the answer-rate floor or above the V1 p95 budget, both named in configuration package v3 (Q-22)" | Floor = the Phase 2 baseline per gate, as counts (166/174, 146/174), on the V1.5 metric; the composition stop (V1 adds no in-domain abstention under (b)); p95 250 ms | v3 `v1.stop` |
| PD-19 | `V1_PIPELINE` defaults (freeze) | Phase 4 G; 13.6 | Development enforce; elsewhere shadow; enforce refused before the Phase 4 exit; off refused outside development | `config.py`; v3 `flag_policy.v1_pipeline`; env example |
| PD-20 | V1 lexicon (engineering parameters) | Phase 4 D (no values) | The negation cues, suffixes, number words, closed unit list, quantity rule and alignment terms of 4.1 | v3 `v1.lexicon`, `rules.py` |
| PD-21 | Quiz key disclosure (R-42; no owner decision named) | Phase 4 B "keyed answers outside public payloads" | No key in any public payload or page; key and explanation only after a saved attempt, only for answered questions (rule `keys-after-saved-attempt-answered-only-v1`); a short answer's result reads "Matches the model answer" or "Does not match the model answer exactly" (the server's exact match). Residual: a placeholder answer counts as answered (DI-65) | v3 `v1.quiz_feedback` (provisional; `/ready` `v1.quiz_feedback`); `schemas.py`, `quiz_keys.py` (`FEEDBACK_RULE`), quiz page and panel |

### 16.2 Deferred items

| # | Item | Who | State |
|---|---|---|---|
| DI-52 | Q-22 / D-06 owner values (X4 margin, V1.3 threshold, V1.7 alignment rule, V1.5 frozen before E1 (`abstention.provisional_until` `Q-22 (DI-52)`), V1.9 band, stop values; `owner_decisions.Q-22.provisional_values` names each) and hold H7's "Signed configuration" | PI | Open |
| DI-53 | Q-14 misconception seed list (A-18); v0 ships empty; Content Owner edits follow in Phase 7 | CO / PI | Open |
| DI-54 | D-21 hosting decision, then a real checker with a pre-emptive timeout and an in-flight cap (H14 at the P5 exit) | PO | Open |
| DI-55 | Ratify PD-13..PD-21; file D-20's interim policy (H15 release evidence) | PI / PO | Open |
| DI-56 | V3 consumption of `pending_v3_intents` and the X4 trigger: reviewer UI and queue (Phase 6) | MLE (P6) | Deferred |
| DI-57 | Production evidence for R-13 and R-16 closure after a D-05 release: legacy-guard counts in production logs, a V1 shadow in production (needs DI-32) | PfO / MLE | Not started |
| DI-58 | Phase 3 exit carried over (its plan-P items are evidenced, DI-31 closed; not passed under P1-D-18); Phase 4 exit: AC-4-1..7 in a cited CI run on `main` (branch run 44868544555 at `863179f` passed every job; a branch run is not the cited run); `phase4_exit_passed` stays false while Q-22, Q-14, D-20 and D-21 are open | Eng / PI | Open |
| DI-59 | The two-pass delivered path (`TWO_PASS_DELIVERY_IMPLEMENTED`, `TWO_PASS_TUTOR=on`) and the F-1 measurement (DI-36), at the Phase 4 exit; the delivered rendering must show a `disclose` verdict's `DisclosureBlock` (AC-4-6 on delivered text; V1's accepted rendering holds no disclosure text) | Eng | Deferred |
| DI-60 | Legacy quotation edge cuts (M8); remedy: whole-sentence legacy quotations, or retire the legacy path when two-pass delivers; a learner-visible change (D-05) | PO, then Eng | Open |
| DI-61 | The quiz-key change (no key in any public payload; feedback after a saved attempt; the short-answer result labels) ships only with a D-05 release, frontend first | PfO | Not released |
| DI-62 | Phase 4 log-based metrics and alerts (a cloud write); operating the answer-rate stop needs labelled in-domain traffic | PfO, then Eng | Defined, not created |
| DI-63 | Remove package v2 after one release, with its CI step (and v1 under DI-42) | Eng | Deferred |
| DI-64 | AC-4-2 for the paraphrased-contradiction class once D-21 hosts a checker: it holds today only because the NullChecker withholds every claim (3 cases delivered under (b)) | MLE (after DI-54) | Open |
| DI-65 | The quiz-key harvesting residual: a saved attempt with placeholder answers returns every key of the lesson; a mitigation (attempt limits, a substantive-answer rule, or server-side assessment, Phase 8) is a learner-visible change (D-05) needing PD-21's ratification (DI-55) | PO / PI, then Eng | Open |

Plan M names the phase's residuals: "Residual: checker error, paraphrased leakage." The paraphrased-contradiction class is this phase's implementation-defined case of checker error (DI-64). These, the quiz-key harvesting residual (DI-65) and the inert production V1.7 family are in the closure notes and in ADR-005.

---

## 17. Verification, work order and exit

**Commands** (`<py>` is the scratch venv's python):

```
<py> -m pytest -q -m "not release_artifacts" apps/api/tests evaluation/tests -p no:cacheprovider
<py> scripts/validate_corpus.py --check-public-assets --check-recall-stop
<py> scripts/validate_lqs.py --allow-draft
<py> scripts/config_package.py --check
<py> scripts/config_package.py --check --path apps/api/app/config_package/v2.json
<py> scripts/config_package.py --check --path apps/api/app/config_package/v1.json
<py> scripts/authorization_matrix.py --check
<py> scripts/replay_tutor_plans.py --check docs/evaluation/phase3/three_plan_replay_v1.json
<py> scripts/run_v1_fixtures.py --check docs/evaluation/phase4/v1_fixture_report_v1.json
<py> scripts/generate_manifest.py --check
<py> scripts/validate_corpus.py --check-hashes --check-near-duplicates
<py> scripts/calibrate_abstention.py --check docs/evaluation/phase2/calibration_record_v1.json
<py> scripts/scan_boundary.py --repo --docker-context apps/api/Dockerfile:. --docker-context apps/frontend/Dockerfile:apps/frontend --report <scratchpad>/boundary.json
cd apps/frontend && npm run lint && npm run typecheck && npm run test:integration
git status --short   (no stray files; nothing in the repository root)
```

CI also runs `pip-audit -r apps/api/requirements.txt` and `npm audit --omit=dev --audit-level=high`, which need the network, and the image boundary scan, which needs Docker.

**Scratch PostgreSQL 17** (never the installed server's data directory; never pipe `pg_ctl` output; ports 55024-55623 are reserved): `initdb` into the scratchpad, `pg_ctl … -o "-p 57433" … start`, `createdb qcai_test`, the suite with `TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:57433/qcai_test` and then with `postgresql+pg8000://…` on a fresh database, `pg_ctl … stop`.

**Exit (plan P)**
- Plan P: "AC-4-1 to AC-4-7 green in a cited CI run; fixture hashes in configuration package v3; Finding 4 closed [Risk R-16]; R-13 closure evidence (V1.1 hard fail, AC-4-1) in Section 5 [Risk R-13]; Finding 3 (R-15, closed at Phase 2) re-verified by AC-4-3."
- The fixture hashes in v3 and the AC tests are done in code. The cited run and the production closure evidence are DI-58 and DI-57.
- **CI.** Branch run 44868544555 (push, at `863179f`) passed every job: api-and-evaluation, frontend, api-postgres (psycopg) and api-postgres (pg8000) on PostgreSQL 16, api-postgres, api-image-boundary-scan (release-artifacts skipped by design). It is a branch run, not the cited run; each later commit needs its own run, and the cited run must be on `main`.
- `phase4_exit_passed` stays `false`.

---

## 18. Review history

The rows below record what each round fixed, in order. They may describe behaviour that a later round superseded; sections 0-17 are authoritative. Each finding is one line with the tests that fail if its defect comes back (13.1 numbers the acceptance tests). Each round's commit message lists its findings, the existing tests it changed with the reason, and its mutation checks; the latest verification is in section 17.

| Round | Commit | Findings fixed (one line each, with their tests) |
|---|---|---|
| Spec review 1 (pre-code) | — (folded into sections 0-17 before the build) | The stop floors are counts, never rounded rates: `test_ac_4_3_the_in_domain_answer_rate_is_at_least_the_phase_2_baseline_for_the_same_gate`, `test_plan_l_the_stop_conditions_are_named_in_package_v3_and_the_fixture_runner_exits_3`<br>A `V1Passed` exempts only claim-scoped V1.2 drops, and `hard_fail` is the `V1HardFail` type: `test_ac_4_1_a_hard_fail_is_typed_final_and_only_a_v1_passed_reaches_the_v2_hook`<br>`PipelineCountsV2` counts polarity drops: `test_a_forced_polarity_drop_is_removed_and_counted_in_pipeline_counts_v2`<br>The Phase 3 tests the package change touches keep their intent (13.3): `test_package_v2_keeps_every_phase_2_value_of_v1`, `test_v2_structural_errors_always_stop_the_load`<br>The Phase 3 spec's `EvidencePanel` listing carries `conflicts` (7.14): `test_k3_spec_section_3_lists_the_code_s_fields`<br>The quiz page passes `publicQuestions`: `apps/frontend/tests/quiz-keys.integration.test.ts`<br>Units are a closed list: `test_a_non_unit_word_is_never_a_unit_and_a_unit_less_claim_number_matches_any_unit`<br>`REASON_OUTCOMES` is total: `test_reason_outcomes_are_total_over_every_binding_failure`<br>V1.6 finds an item id in the turn and searches every lesson: `test_context_by_a_hyphenated_item_id_inside_the_turn`, `test_every_lesson_s_items_are_searched_whatever_the_lesson`<br>The guard without a v1 block: `test_without_a_v1_block_the_polarity_rule_is_skipped_in_development`<br>No public guard SLI: `test_plan_i_ready_reports_package_v3_and_the_v1_fields_and_no_shadow_outcome`<br>One V1.4 seam: `test_the_patched_pipeline_check_subset_is_the_one_v1_4_uses`<br>The envelope is checked before the subset check: `test_an_invalid_envelope_reaching_render_checked_is_response_envelope_invalid_not_a_fault`<br>The replacement values: `test_plan_e_with_no_checker_v1_3_flags_every_claim_and_every_answer_is_withheld`<br>The checker call is inline: `test_ac_4_7_an_unavailable_or_late_checker_makes_the_decision_abstain`<br>The fixture runner writes no package: `test_ac_4_2_the_committed_fixture_report_matches_a_fresh_run_and_its_hashes_match_the_package`<br>At most 20 verdicts: `test_a_record_holds_at_most_twenty_verdicts`<br>The composition stop: `test_ac_4_3_v1_adds_no_in_domain_abstention_over_the_phase_3_composition`<br>Phase 3 text that described Phase 4 as future is current (7.14): `test_k3_the_authoritative_text_states_the_current_code_only`<br>The production V1.7 family is inert: `test_ac_4_6_conflicting_cited_spans_get_a_disclosure_block_or_are_withheld`<br>The misconception library is inline and hashed: `test_library_v0_ships_empty_and_hashed`<br>V1.5 maps the gate's decision: `test_the_gate_s_abstention_is_v1_5_s_with_its_reason` |
| Build | `669510a`, `4b05ae1` | `QUANTITY_PATTERN` uses named groups: `test_the_polarity_table`<br>Every result is built from the vocabulary (`results.make_result`): `test_check_results_are_consistent_with_their_vocabulary`<br>The V-1 SLI counts delivered verdicts' span ids: `test_plan_i_v1_metrics_report_resolution_hard_fails_flag_rate_latency_and_disagreements`<br>The V1 track checks the budget at Phase 3's points: `test_the_budget_stops_the_render_loop`<br>A valid plan stamps its generator on an empty lock (174/174 identical): `test_ac_4_3_v1_adds_no_in_domain_abstention_over_the_phase_3_composition`<br>The v3 loader leaves `ledger.entry_schema` to `package_check` (conflict 37): `test_f4_*`<br>The bundle message keeps "Phase 4": `test_the_bundle_refuses_conflicts_before_phase_4`<br>A claim abstains only with its response: `test_the_verification_and_ledger_v2_rules_refuse_each_inconsistency`<br>AC-4-5 runs a turn on another lesson's page, so narrowing V1.6 to the request's lesson fails it: `test_ac_4_5_an_assessment_draft_with_the_keyed_answer_is_re_rendered_socratically_without_it`<br>The lockout events are read in seq order: `test_repeated_failures_lock_the_email_even_for_the_right_password`<br>No fixture string holds a source document's 12-word shingle: `test_no_fixture_string_holds_a_corpus_sentence` |
| Review 1 | `863179f` | Blocker: the API image could not start (`package_check` computed `parents[5]` at import); the root is found on demand: `test_the_v1_start_up_check_runs_from_the_image_layout`, `test_no_image_module_computes_a_parent_its_image_path_lacks_at_import`<br>The guard's polarity rule on verbatim quotations cut mid-number and mid-cue: `test_the_polarity_rule_withholds_a_verbatim_quotation_that_cuts_a_number_or_a_cue`<br>Plan G's comparison with the decision the learner received, on real turns: `test_plan_g_a_route_turn_s_shadow_record_compares_v1_with_the_decision_the_learner_received`<br>The start-up fallback only in development with governance off: `test_start_up_a_v1_package_problem_turns_v1_off_only_in_development_with_governance_off`<br>A V1 package problem stops every build outside development, whatever its governance setting: `test_settings_v1_pipeline_defaults_and_refusals`<br>A V1.1 hard-failed candidate's claims are counted: `test_a_v1_1_hard_failed_candidate_counts_its_claims_so_the_bound_claim_ratio_sees_them`<br>One hard-fail-rate definition: `test_plan_i_the_hard_fail_rate_per_check_has_one_definition_in_process_in_the_report_and_in_the_runbook`<br>AC-4-2 qualified (DI-64): `test_ac_4_2_the_adversarial_set_fails_or_abstains_under_production_and_only_the_residual_class_is_delivered_with_a_perfect_checker`<br>The R-42 harvesting residual (DI-65) and plan M quoted exactly: `test_phase4_docs_quote_plan_m_and_state_the_current_rules`<br>The rollback order, the API first: `test_phase4_docs_quote_plan_m_and_state_the_current_rules`<br>The observability runbook names every override: `test_plan_i_the_runbook_names_every_configuration_override_the_api_records`<br>PD-21 in `v1.quiz_feedback`: `test_v3_structural_errors_always_stop_the_load`, `test_package_check_v1_problems`<br>Q-22 names `v1.v1_7`, and `abstention.provisional_until` is `Q-22 (DI-52)`: `test_v3_keeps_every_v2_value_but_the_listed_changes`, `test_plan_h_thresholds_are_provisional_until_phase_4`<br>Four synthetic queries (12.1): `test_phase4_docs_quote_plan_m_and_state_the_current_rules`<br>The records' `--allow-dirty` provenance: `test_phase4_docs_quote_plan_m_and_state_the_current_rules`<br>The quiz live region and `aria-describedby`: `apps/frontend/tests/quiz-keys.integration.test.ts`<br>The Phase 3 refusals run on the shipped v3: `test_v2_structural_errors_always_stop_the_load`<br>A shadow V1-track overrun logs its own event: `test_a_v1_track_overrun_logs_the_phase_3_budget_event_only_when_v1_is_the_record`<br>The Phase 3 helpers copy the shipped package under its own name: `test_a_changed_schema_file_or_prompt_hash_is_a_package_problem`<br>ADR-005 states the claim-to-span rule: `test_phase4_docs_quote_plan_m_and_state_the_current_rules` |
| Housekeeping H1-H3 | `b3b8a69`, `df7b1ee`, `e3ac436` | H1 the `\u` SyntaxWarning (a raw bytes literal now, the same bytes), and any SyntaxWarning fails the suite: `test_no_python_source_raises_a_syntax_warning`<br>H2 no repository test reads outside the repository; the evidence package checks its own records (`00_meta/check_records.py`): `test_no_test_reads_outside_the_repository`<br>H3 the Phase 3 tests are in feature modules, every test under its own name, and the test strategy maps every Phase 3 test file: `test_k3_the_test_strategy_maps_every_phase3_test_file` |
| Review 2 | `48b3fe8` (fixes); the two commits after it (documents, verification) | The spec's DI-52 row and main.py's threshold comment state every Q-22 value and `Q-22 (DI-52)`: `test_phase4_docs_name_every_q_22_value_and_the_package_s_provisional_until`<br>AC-4-6 on the learner path: with no evidence panel shown, an answer quoting conflicting passages is withheld (V1.7 `conflict_withheld`): `test_ac_4_6_with_no_disclosure_shown_a_contained_answer_quoting_conflicting_spans_is_withheld`, `test_conflicting_quotations_are_withheld_unless_a_disclosure_is_shown`<br>A two-pass `disclose` verdict's block is on the record only, and the delivered path must show it (R-a, DI-59): `test_ac_4_6_conflicting_cited_spans_get_a_disclosure_block_or_are_withheld`<br>AC-4-2's status says what each checker configuration shows (under production nothing is delivered, so detection is shown under the deterministic-only checker): `test_ac_4_2_the_adversarial_set_fails_or_abstains_under_production_and_only_the_residual_class_is_delivered_with_a_perfect_checker`<br>A short answer's result names the exact match, never "Not correct": `apps/frontend/tests/quiz-keys.integration.test.ts`<br>The Phase 3 records state the merge and the cited main run (DI-31 closed): `test_k3_the_records_state_the_merge_and_the_cited_run_on_main`<br>Security events are read in seq order and counted: `test_no_test_reads_one_security_event_without_an_order`, `test_a_role_denial_is_a_security_event`<br>The test strategy maps every module the phase added: `test_phase4_docs_the_test_strategy_maps_every_test_module_the_phase_added`<br>This section is one history table: `test_phase4_docs_the_spec_ends_in_one_review_history_table` |
