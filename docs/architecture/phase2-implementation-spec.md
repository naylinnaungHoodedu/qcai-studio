# QC+AI Studio — Phase 2 Implementation Spec (reviewed revision)
## Corpus, span identity and retrieval integrity

Repository: `D:\QC_AI_Studio\Codex_Webapp_QC_AI_Studio`. Branch: `phase2/span-identity`, cut from `origin/main` `a257dd11`. Plan: `D:\QC_AI_Studio\QC_AI_Studio_Ultimate_Software_Upgrade_Plan.txt`. The Phase 2 block is at L1155-1222, and sections 11.1-11.6 are at L2082-2179.

> **Implementation record.** This is the spec the Phase 2 implementation followed, as handed to the implementing engineer. Section 13, at the end, records every place where the code refines or departs from it, and why. The measured figures in sections 0.2 and 0.2b are the spec author's prototype measurements. The committed calibration record (`docs/evaluation/phase2/calibration_record_v1.json`) is authoritative, and its values are summarised in section 13.

**Review revision (2026-11-19).** This revision applies an adversarial review.
- Tags such as `[R1]` mark the changed passages; they refer to the review issue list.
- The main changes:
  - **[R1]** The Phase 2 BM25F gate ships behind `RETRIEVAL_GATE`. It defaults to the approved Phase 1 floor outside development, because measurement shows it is not strictly more conservative.
  - **[R2, R3]** Calibration uses the pre-registered BEP-1 strata, folds and hold-out.
  - **[R5, R6]** The citation migration follows D3 literally and is byte-reversible by construction.
  - **[R7]** A version check that would have broken every import is fixed.
- Section 0.2b records the review measurements.

The spec is written so an engineer can execute it without guessing:
- Section 0 sets out the binding constraints and the AC-2-3 reading.
- Section 1 lists every conflict between the plan and the fixed decisions, and how each is resolved.
- Sections 2-3 define the data shapes and the exact algorithms.
- Sections 4-7 give the file-by-file changes, runtime behaviour, start-up and settings.
- Sections 8-10 cover tests, CI and docs.
- Section 11 gives the order of work and the verification commands.
- Section 12 lists the open and deferred items.

---

## 0. Ground rules, evidence and readings

### 0.1 Binding constraints, restated
**Repository and secrets**
- Stay on the branch: no branch switch, no `git stash`, no push, no git-config change, no history rewrite.
- Every commit message ends with a blank line, then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never open `infra/cloudrun/*.env.yaml`, `apps/frontend/.env.local` or any `.env` file. The scanners match those files by path and never read them (3.13).

**Freeze (D-05) [R1]**
- The freeze is not lifted, so every new learner-visible behaviour either defaults to the current behaviour or is strictly more conservative.
- The BM25F gate (`bm25f-v1`) is neither (0.2b). It returns results for more in-domain questions, for more near-miss questions and for more off-topic questions that share a course word. It therefore sits behind `RETRIEVAL_GATE`, which defaults to `p1-floor` outside development.
- `p1-floor` is the approved P1-D-04 floor (`score-floor-p1-v1`, floor 6) applied to the span index. In a governed build under D-31 it reproduces today's production search exactly: the same 41 authored passages, scores and order. Only the `chunk_id` strings become span ids, and fields are added.

**Changes that are on by default** (all conservative, or not a capability):
- unique span ids;
- chapter summaries removed from search, evidence and citations (task 2.7);
- the 2026 video unbound from its lesson;
- quotation only of citations that the span registry verifies;
- stored citations of unapproved items withheld in governed builds [R13];
- new labelling fields.

**Changes that are off by default outside development:**
- `RETRIEVAL_GATE=bm25f-v1`;
- the `/spans` route;
- semantic retrieval;
- lifting the provisional marker.

In development, `bm25f-v1` and `/spans` are on by default, so the suite and CI exercise the Phase 2 path. The shipped `p1-floor` path is tested explicitly in governed configurations (8.1).

**Switching production to `bm25f-v1`** is a remediation release that closes R-15 under the Section 5.3 release rule: "Remediation releases that close or contain a listed blocker are permitted; each MUST be scoped to that blocker, carry a tested rollback path and be approved under [Decision D-05]". Phase 2 does not make that switch.

**Corpus and answers**
- D-31 / P1-D-07: zero assets are approved. A governed build serves only the approved assets (none), and nothing derived from an unapproved asset.
- D-19 / task 1.11 containment stays: a learner receives an abstention, or verbatim quotes of DOCUMENT spans from approved public assets. `grounded` is always false.
- R1.2 (`answer_history.py`) is unchanged.

**Privacy**
- No learner identifiers, emails or secrets go into fixtures, logs, reports or docs.
- Tests use `uuid4`-based demo ids, as today.
- No API source contains a string literal matching `["'\`]qcai_[a-z0-9_]+["'\`]`.

**Existing tests**
- No Phase 1 test is weakened. Where one must change, its intent is kept and the commit message gives the reason (8.3).
- A test that would pass vacuously after the change counts as weakened [R20].

### 0.2 Measured facts this spec relies on (spec author, 2026-11-19; indicative)
The calibration script (4.21) is authoritative over all figures below.

**The current index**
- The development (ungoverned) index has 459 chunks but only 215 unique `chunk_id`s (E-25): 394 document chunks and 65 video-chapter chunks.
- The governed index (empty manifest) has 41 authored `lesson` chunks, all with unique ids.
- The 394 document chunk rows hold 331 unique (file, text) pairs: 288 are used by one lesson, 33 by two and 10 by four.

**Spans**
- The 12 DOCX files give 265 sections and 1030 splitter chunks.
- Every chunk is found at a deterministic offset with the LangChain `add_start_index` algorithm (1030/1030).
- The working tree pins `langchain-text-splitters==1.1.2` and `python-docx==1.2.0`.
- **[R8]** The legacy build (requirements at `62239c5`) pinned `langchain-text-splitters==1.1.1`. Equality between legacy chunk text and new span text has therefore not been proven for the 2026-04-05 build. Any mismatch fails safe (`legacy_unresolved`), and the dry-run report shows the outcome.
- `text_utils.py` is unchanged since `62239c5`. `docx_parser.py` gained only the `source_filename` field.
- On 90 of 1071 spans, single and double `truncate_display_excerpt(…,320)` give different text. One display key is shared by 2 spans.

**Pre-migration recall@5** (current `CourseStore.search`, top-5 lesson set)

| Configuration | Fixture `in_domain` (174) | Blueprint learner questions (36) |
|---|---|---|
| Governed | 131 | 36 |
| Development (all assets) | 129 | 28 |

With `SCORE_FLOOR=0`, development recall@5 on the fixture is 124.

**BM25F prototype** (`k1=1.5, b=0.75, title_weight=2.0`, minimum token length 2, no stemming, stopwords-v1, coverage-v1)
- No fixture out-of-scope query returns a result at any floor ≥ 0.
- The full-fixture feasible window is [0.00, 4.70].
- At floor 2.35, recall@5 is 151/174 and 36/36 (governed), and 142/174 and 28/36 (all-approved).
- A floor alone is infeasible: the out-of-scope maximum is 6.4 (governed) and 6.9 (all-approved).

**Near-duplicates**
- Document 5-shingle Jaccard: maximum 0.0207; maximum containment 0.044.
- The 2025 and 2026 MP4s both have an `mvhd` duration of 575.176 s. Their sizes are 286,348,553 and 286,549,020 bytes (0.07% apart), and their LFS oids differ.
- All other video pairs are at least 6 s apart.

### 0.2b Review measurements (2026-11-19; scratchpad `review/rv1-rv7.py`; indicative)

**In-domain questions with at least one result** [R1]

| Configuration | bm25f-v1 at 2.35 | P1 floor |
|---|---|---|
| Governed | 159/174 | 148/174 |
| All-approved | 166/174 | 152/174 |

bm25f-v1 answers 13 (governed) and 17 (all-approved) in-domain questions that P1 abstains on.

**BEP-1 strata missing from the repo fixture** (queries that return results) [R1, R2]

| Stratum | bm25f-v1 governed | P1 governed | bm25f-v1 all-approved | P1 all-approved |
|---|---|---|---|---|
| `near_miss` (15) | 2 | 1 | 10 | 7 |
| `oos_lexical` (16) | 0 | 0 | 3 | 2 |

`oos_general`, `stop_only` and hold-out B: 0 in every case.

**Stress probes** (each off-topic fixture question plus a suffix, 124 queries) [R1]

| Suffix | bm25f-v1 at 2.35, governed | P1, governed | bm25f-v1 at 2.35, all-approved | P1, all-approved |
|---|---|---|---|---|
| " noise model" | 124 | 0 | 124 | 15 |
| " for optimization" | 6 | 0 | 42 | 1 |

At floor 4.70 the governed figures fall to 4 and 1.

**Fold-based calibration on the BEP-1 cal fold** [R2]
- Feasible windows: governed [0.00, 4.75], all-approved [0.00, 6.70]. The intersection gives floor 2.35 and margin 2.40.

| Configuration | Conf fold at 2.35 (legacy) | Hold-out B at 2.35 (legacy) |
|---|---|---|
| Governed | 61 (52) | 22 (16) |
| All-approved | 58 (54) | 21 (19) |

**Recall metric sensitivity** [R4]
- Governed: union and slot-equal both give 151.
- All-approved fixture: union 142, slot-equal 140 (legacy 129).
- All-approved learner questions: union 28, slot-equal 27 (legacy 28). This constraint holds with zero slack under the union metric.

**`p1-floor` over the span index** [R1, R20, R21]
- Governed: recall 131 (legacy 131), out-of-scope 0, near_miss 1, answered 148. The governed configuration has no shared spans and no chapters.
- All-approved: recall 119 (legacy 129) and learner questions 22 (legacy 28), because chapter summaries are excluded. Gated 119 against ungated 134.

**Answer rate** [R3]
- Proxy for the Phase 0 in-domain answer rate: 174/174 before the floor (BEP-1/27_score_floor/PROPOSAL.md §3, measured at `b3d6808c`).
- bm25f-v1 (all-approved): 166/174 = 95.4%. P1: 146/174 = 83.9%.

### 0.3 Reading of AC-2-3
AC-2-3 reads: "Every stored or returned citation resolves". This spec, its tests and the ADR-004 revision read it as follows:
- every citation the Phase 2 pipeline stores or returns resolves: `resolution == "resolved"`, found by the resolver, with an equal `content_hash`;
- every migrated citation resolves;
- a `legacy_unresolved` citation is never returned as resolved. It is either withheld, or explicitly labelled with `resolution="legacy_unresolved"`, `provisional=true` and `label="unverified historical reference"`. Two cases are withheld:
  - pre-containment rows (R1.2);
  - in governed builds, citations of items that are not approved [R13].

The frontend does not render history citations today (qa-panel renders only the answer text), so the label lives in the payload.

---

## 1. Conflicts between the plan text and the fixed decisions

Each item gives the conflict and the resolution this spec implements. Every resolution is a refinement; none reverses a fixed decision without a reason in the plan text.

1. **corpus_version inputs.**
   - Plan 11.1: "corpus_version MUST hash the sorted (item_id, item_version, sha256) of built items plus the span-scheme version, so any content or membership change, including partial approval, yields a new version; membership-neutral licence edits do not."
   - D1 (a workflow design note, not an owner decision): hash the sorted (id, version, plane, bound) tuples; licence and approval fields never enter it.
   - **Resolution (revised 2026-11-19, review fix round):** the plan's MUST governs; D1 has no authority over it.
     - `corpus_version` hashes the sorted (item_id, item_version, sha256) of the **built items** plus the span scheme (`corpus-version-v3`, 3.4). Built items are the public-plane, bound items the build admits: in a governed build the authored item and the approved items, in development every public-plane, bound item.
     - Partial approval therefore yields a new version, and a licence-field edit does not. Span ids never hash it, so AC-2-2 is unaffected.
     - The manifest records the governed value; a development build reports its own.
     - `index_version` (3.4) still adds the entries, the retrieval configuration and the active gate.
     - Citations and tutor turns store `corpus_version`, which now identifies the approved subset that produced them (the replay key Phase 3.2 and 3.5 consume). `/ready` and the logs report both values.
2. **span_id inputs.**
   - Plan 11.2: "span record = {item_id, item_version, section_ordinal, char_start, char_end, content_hash of full span}; span_id hashes it without corpus_version".
   - D2: hash (scheme, item_id, start, end, content_hash).
   - **Resolution:**
     - Keep D2. `item_version` and `section_ordinal` stay record fields, not id inputs, so a DOCX re-save with no text change does not rotate ids.
     - The `corpus_spans` key is (span_id, item_version).
     - Offsets are item-global, so an edit early in an item rotates the ids of later spans. This is documented in ADR-004. Old ids keep resolving through the append-only `corpus_spans` table.
3. **Legacy match rule [R5].**
   - Plan 11.2: "the normalised stored excerpt is matched to rebuilt spans containing it with the same source_title and section_title: one match yields the span_id, zero or several yield legacy_unresolved".
   - D3: the exact normalised-excerpt **hash** must match exactly one span.
   - D10's stop also fires "if the migration turns a previously exact-match citation into unresolved".
   - **Resolution:**
     - Apply D3 literally: exactly one distinct span with an equal key means the citation migrates.
     - Title equality (11.2), excerpt containment (11.2) and the v1 `content_hash` agreement become **report-only diagnostics**.
     - A stricter combined rule would label hash-unique citations as ambiguous, which is exactly D10's stop condition.
4. **Margin semantics.**
   - Plan 11.3: "a sufficiency gate (floor plus runner-up margin)".
   - D6 and plan V1.5: "within margin X4 mark".
   - **Resolution:** a result with `floor ≤ score < floor + margin` gets `near_floor = true`. There is no runner-up test (Phase 4).
   - **Status:** a provisional deviation from plan text. It needs Principal Investigator or Research Lead ratification (configuration package `owner_decisions.PLAN-11.3`; BEP-2-12 PD-07).
5. **Stemming.**
   - Plan 11.3: "a stemmed, stopword-filtered BM25-style index".
   - **Resolution:** `stemmer: "none"` in package v1. An S-stemmer raised out-of-scope leakage (all-approved maximum 8.2). The package field exists for Phase 4.
   - **Status:** a provisional deviation from plan text. It needs Principal Investigator or Research Lead ratification (configuration package `owner_decisions.PLAN-11.3`; BEP-2-12 PD-07).
6. **Calibration strata and held-out folds [R2, R3].**
   - Plan 11.3: "Calibrate on public-corpus strata (single-source, multi-source, near-miss, out-of-scope, stopword-only) with held-out folds, keeping in-domain answer rate within 5 points of Phase 0".
   - **Resolution:**
     - Use the pre-registered BEP-1 fixture (strata and cal/conf folds, rule "sha256(query) first hex digit even -> cal, odd -> conf") and hold-out B, copied into a new public fixture (4.26).
     - Select on the cal fold only. Confirm on the conf fold and hold-out B. Report `oos_lexical`, `near_miss` and `in_multi` against P1, as reported strata that do not gate the choice.
     - The answer rate is compared with the pre-floor proxy (174/174, BEP-1 PROPOSAL §3).
     - Limitation: coverage-v1 and the framing stopwords were designed with the whole repo fixture in view (both folds). AC-2-4 on that fixture is therefore design-set evidence. The near_miss and oos_lexical strata were not used in design, and they show a regression against P1 (0.2b).
     - The values stay provisional until Phase 4, where ULQS calibration splits are used.
7. **Lifting the provisional marker [R14].**
   - Plan G: "provisional marker lifted for resolved citations". Task 1.11: "citations marked provisional until Phase 2". AC-1-13: "Every citation returned before Phase 2 is marked provisional". Action 26: "citations provisional (AC-1-13) until V-1 holds", where Phase 2 A defines V-1 as "100% of delivered citations resolve".
   - **Resolution:**
     - Implement the lift behind `CITATION_PROVISIONAL_LIFT_ENABLED`, default `false` (freeze: it removes a label).
     - Enabling it outside development records a `config.override` security event. It requires AC-2-3 green in a cited CI run and D-05 approval.
     - There is no hard refusal, which would contradict plan G for production.
     - `resolution` is always recorded. The plan G test runs with the flag on.
8. **`GET /spans/{span_id}` as a public route.**
   - The freeze forbids new default learner-visible behaviour. D-31 forbids serving anything derived from an unapproved asset.
   - **Resolution:**
     - The route is always registered, so the authorization matrix stays static, but it returns 404 unless `SPAN_RESOLVER_ROUTE_ENABLED`. The default `None` means true in development and false elsewhere.
     - In a governed build it returns 404 for document spans of items that are not approved. Authored spans stay resolvable.
     - The excerpt is returned only when the span is servable, which under D-31 is never.
     - 404 responses carry `Cache-Control: no-store` [R24].
9. **`public_service` of the authored item.**
   - The manifest records `public_service: false` (D1).
   - Indexing of `kind: authored` does not depend on `public_service`, which keeps today's behaviour.
   - The authored item is never servable for the resolver excerpt and never quotable (D-19).
10. **Video near-duplicate detection.**
    - Content hash or size equality cannot detect the 2025/2026 re-encode. Plan 11.1's decoded-audio hash needs ffmpeg, which CI does not have.
    - **Resolution:**
      - Add the dependency-free `mp4-mvhd-v1` rule: duration plus size ratio.
      - The 2026 item is also unbound by the package's Q-10 list.
      - The audio hash is deferred (12).
11. **Hash basis for LFS.** The manifest records `hash_basis: "content-sha256"` and `storage: "git-lfs"`. The per-run basis (`content` or `lfs-pointer`) goes in the `--check-hashes` report.
12. **Start-up hash check.**
    - `MANIFEST_DRIFT_CHECK=fast` (the default) fully hashes the DOCX files present and the authored item, and checks MP4s by size or pointer oid. `full` also hashes MP4 content.
    - Governed builds fail closed on any drift [R27]. A change to `MODULE_BLUEPRINTS` without a regenerated manifest stops governed start-up, and CI's `generate_manifest.py --check` prevents that. Development warns.
13. **Dual-read windows.**
    - Manifest 1.0 stays readable for one release (D1).
    - Citation v0/v1 shapes are dual-read for two releases (plan 11.2). The package records `legacy_citations.dual_read_releases: 2`.
14. **D-30 threshold [R5].**
    - Every limit is read from configuration package v1 (`legacy_citations`), never hard-coded, so ratifying D-30 is a configuration change.
    - The stop fires on any of:
      - a native unresolved share above `max_unresolved_share_native` (0.0, so any native unresolved citation);
      - when `max_unresolved_share_legacy` is a number, a legacy unresolved share above it, measured by `legacy_share_statistic` (`point`, the plan's "unresolved citations exceed the ... threshold", or `wilson95_upper`); the loader accepts only null or a number in [0, 1];
      - an exact-match regression (> 0): a citation whose normalised-excerpt hash is unique in the current build but which still ends unresolved (an older registered span with the same text makes it ambiguous), or an already migrated citation whose span no longer resolves;
      - a row that fails the canonical-JSON precondition (> 0, in `--apply` only) [R6].
    - While D-30 is open the legacy limit is null: the share is reported with a Wilson interval, labelled and not gated (provisional).
15. **AC-2-5 baseline [R29].**
    - The plan's baseline is "the pre-migration commit in the same CI run". CI checks out with `fetch-depth: 1`, so `a257dd11` is not available in the run.
    - **Resolution:** the baseline is a frozen verbatim copy of the `a257dd11` search, run in the same test and calibration run. A snapshot recorded from the unmodified code proves its fidelity (test 15).
16. **AC-2-7 passage scans.**
    - These need salted fingerprints from the private plane (D-14 is open).
    - Public CI proves the path scans only, and its report says `passage_scan.status: "not_run"` and `ac_2_7.status: "partial"`. AC-2-7 is therefore **partially met (path half only)** and may not be cited as passed.
    - A build-context scan is a proxy for the image. `--image-tar` scans a built image (`docker save` or `docker export`); `--require-ac-2-7` makes the exit-gate run fail unless both halves ran and passed over an image and a release.
    - The packager excludes private-plane, licensed and secret-like paths and scans its own bundles; the tag-only release job also runs `--release-zip`. Packaging still refuses unapproved assets [R23], so no release bundle can be built today.
17. **Tutor follow-up rewrite.**
    - `TutorOrchestrator._resolve_query` prefixes the previous user turn of the same thread. That is the learner's own turns, not learner state.
    - For AC-2-9, "one query" means the resolved query, and the tests use fresh threads. Phase 3.1 replaces this heuristic.
18. **Heading matching.** Exact heading matching (11.4) is not a Phase 2 task. `_match_sections` is unchanged and flagged.
19. **Chapters in the lesson UI.**
    - Chapters stay as presentation on lesson pages, labelled `curated_chapter_summary`.
    - The unbound 2026 video's chapters disappear because its lesson no longer binds that video.
20. **Unbound items in development.**
    - "CourseStore must not bind an unbound item to any lesson" (D8) is enforced in every mode, including `lesson.video_asset`, `lesson.chapters` and `lesson.source_assets` [R11].
    - The development overview and `/source-assets` still list and serve the 2026 file, as today, so the dev-only tests stay unchanged.
    - Governed builds never serve an unbound item, even if it is approved.
21. **Span registration and D-31.**
    - Jobs register text-free span identity for public-plane items present on disk, approved or not; legacy matching needs it.
    - In governed builds, the resolver route and `/qa/history` hide spans and citations of items that are not approved [R13].
    - The production image has no DOCX, so only authored spans register there unless an approved workstation run is done.
22. **SLIs.** These are per-process windows in `/ready` plus per-request log fields. Log-based metrics are cloud writes: documented, not created.
23. **R-18.** DOCX metric fidelity is not addressed by tasks 2.1-2.9; it goes in the deferred register.
24. **Semantic backend.**
    - It is off by setting (default false), whatever keys are configured.
    - Enabling it outside development logs a `config.override` event. Provider egress also needs D-23.
25. **Learner questions inside authored spans.** The authored text contains the "Learner question:" lines, so the learner-question set is circular for the governed configuration. This is recorded as a limitation.
26. **NEW: freeze against the BM25F default [R1].**
    - D5 and D6 fix the design of the Phase 2 index. They do not say it serves learners by default, and the freeze does.
    - **Resolution:** `RETRIEVAL_GATE` (Section 7). Both gates use the same span index, chapter exclusion and learner-free signatures. The calibration record reports both.
27. **NEW: the AC-2-5 metric [R4].**
    - The gate uses the BEP-1 definition, "an expected lesson among the top 5 survivors", generalised to the union of each survivor's `lesson_slugs`.
    - The slot-equal metric is reported beside it, and zero-slack constraints are flagged as fragile.
28. **NEW: span item id [R9].**
    - The span `item_id` is always `source_asset_id(filename, kind)`, or `authored-curriculum`. It never comes from a free-form 1.0 manifest id.
    - Manifest 2.0 validation requires `id == source_asset_id(asset_filenames[0], kind)`.
29. **NEW: `p1-floor` with approved assets [R21].**
    - Applied to an all-approved index, `p1-floor` recall is 118, against a pre-migration 129, because chapter summaries are now excluded. With any document indexed, the floor also lowers recall against the same index unfloored (all assets 118 against 130), the Action 27 "recall drops" stop.
    - Approving any document while `p1-floor` is the gate outside development is a stop condition, **enforced in code**: governed start-up and `validate_corpus.py --check-recall-stop` refuse it. It requires the D-05 switch decision or recalibration. `ALLOW_P1_FLOOR_WITH_DOCUMENTS` (default false) is the owner override; outside development it logs a `config.override` event.
    - Tests: AC-2-5 and the Phase 1 recall guard run both gates on the live code; the `p1-floor` case with documents is a strict xfail that cites this conflict.

---

## 2. Data shapes

### 2.1 Manifest v2 (`corpus/public/manifest.json`)
Generated by `scripts/generate_manifest.py`. The file uses LF line endings, `indent=2` and a trailing newline. Items are sorted by `id`, with keys in the order shown.

```json
{
  "schema_version": "2.0",
  "manifest_status": "generated_pending_rights_review",
  "generator": "manifest-gen-v1",
  "span_scheme": "span-v2",
  "corpus_version": "corpus-<16 hex>",
  "items": [
    {
      "id": "analyzing-quantum-computing-and-ai-paper-2025",
      "kind": "document", "plane": "public",
      "asset_filenames": ["Analyzing Quantum Computing and AI Paper 2025.docx"],
      "asset_paths": ["Analyzing Quantum Computing and AI Paper 2025.docx"],
      "storage": "git", "sha256": "<64 hex>", "hash_basis": "content-sha256",
      "size_bytes": 4486050, "version": "sha256:<first 16 hex>",
      "bound": true, "unbound_reason": null,
      "spans": {"scheme": "span-v2", "canonical_text": "sections-v1", "count": 0, "set_sha256": "<64 hex>"},
      "media": null,
      "source": "QC+AI Studio repository asset (rights review pending, Decision D-02)",
      "license": "UNDETERMINED",
      "permitted_use": "none until rights review (Decision D-31)",
      "public_service": false
    },
    {
      "id": "quantum-computing-and-artificial-intelligence-2026",
      "kind": "video", "plane": "public",
      "asset_filenames": ["Quantum Computing and Artificial Intelligence 2026.mp4"],
      "asset_paths": ["Quantum Computing and Artificial Intelligence 2026.mp4"],
      "storage": "git-lfs", "sha256": "569fa7f2…", "hash_basis": "content-sha256",
      "size_bytes": 286549020, "version": "sha256:569fa7f26924e094",
      "bound": false,
      "unbound_reason": "Q-10 unresolved: 2025 asset only (plan Action 25); re-encode of the 2025 lecture [Evidence E-21]",
      "spans": null, "media": {"duration_s": 575.176, "basis": "mp4-mvhd-v1"},
      "source": "…", "license": "UNDETERMINED", "permitted_use": "…", "public_service": false
    },
    {
      "id": "authored-curriculum", "kind": "authored", "plane": "public",
      "asset_filenames": [], "asset_paths": [], "storage": "code",
      "source_module": "apps/api/app/services/content_assembler.py:MODULE_BLUEPRINTS",
      "sha256": "<sha256 of canonical authored JSON>", "hash_basis": "canonical-json-authored-v1",
      "size_bytes": 0, "version": "sha256:<16>", "bound": true, "unbound_reason": null,
      "spans": {"scheme": "span-v2", "canonical_text": "sections-v1", "count": 41, "set_sha256": "<64 hex>"},
      "media": null,
      "source": "QC+AI Studio authored curriculum", "license": "UNDETERMINED",
      "permitted_use": "platform curriculum text; indexed by kind, not a D-31 source asset",
      "public_service": false
    }
  ]
}
```

**Item set.** There is one item per name in `SOURCE_DOCUMENT_NAMES` and `SOURCE_VIDEO_NAMES`, plus exactly one `authored-curriculum` item: 25 items. Files are resolved with `Settings(source_assets_root=root)._resolve_source_assets`, which looks in the root and then in `update_data/`. The drift check and `CourseStore` use the same resolver, so the manifest and the runtime always read the same file.

**Field rules**
- **`id`** is `source_asset_id(asset_filenames[0], kind)` [R9]. The authored item's id is the literal `authored-curriculum`.
- **`asset_paths`** are repository-relative POSIX paths.
- **`storage`** is `git-lfs` when the path matches a `filter=lfs` pattern in `.gitattributes`. The authored item has `code`; all others have `git`.
- **`size_bytes`** is the content size. For an LFS pointer it is the pointer's `size` line. For the authored item it is `len(canonical_json(payload))`.
- **`version`** is `"sha256:" + sha256[:16]`.
- **`spans`** is present for documents and the authored item and is null for videos. It holds `count` (all sections) and `set_sha256 = sha256("\n".join(sorted(span_ids)))`.
- **`media`** is present for videos when the duration is known (3.12). When the file is a pointer and the `sha256` is unchanged, it is carried over from the existing item; otherwise a warning is printed.
- **`bound`** is false for every item in the package's Q-10 list.
- **Licence fields** are carried over from the existing manifest: by `id` (2.0), or by filename (1.0), or else take the defaults shown.

**Validation by `CorpusRegistry`** (failure raises `CorpusGovernanceError`).
`schema_version` must be in {"1.0", "2.0"}. For 2.0:
- `id`s are unique, and a filename is in at most one item;
- there is exactly one `kind == "authored"` item;
- `kind` and `plane` take their allowed values;
- `id == source_asset_id(asset_filenames[0], kind)` for documents and videos [R9];
- `sha256` is 64 hex characters and `version == "sha256:" + sha256[:16]`;
- `size_bytes` is an integer ≥ 0;
- `bound` is a bool, and `unbound_reason` is non-empty if and only if `bound` is false;
- the licence fields are non-empty strings, and `public_service` is a bool;
- the recorded `corpus_version` equals the recomputed one.

**Private-plane items**
- A private-plane item with `public_service: true` is not a load error. It is a `--check-public-assets` problem [R15].
- A private-plane item is never served, indexed or registered.

No separate JSON Schema file is written; the code validator is the only definition [R26].

### 2.2 Span record, index entry and `corpus_spans` table
In memory (`app/services/spans.py`):
```python
@dataclass(frozen=True)
class SpanRecord:
    span_id: str                 # "span-" + 64 hex (3.3)
    scheme: str                  # "span-v2"
    item_id: str                 # source_asset_id(filename, kind) or "authored-curriculum" [R9]
    item_version: str            # "sha256:<16>"
    item_kind: Literal["document", "authored"]
    plane: Literal["public"]
    section_ordinal: int
    section_title: str           # memory only
    source_title: str            # memory only
    source_filename: str | None
    start: int                   # code-point offset into the canonical text (inclusive)
    end: int                     # exclusive
    content_hash: str            # sha256 hex of text[start:end].encode("utf-8")
    text: str                    # memory only, NEVER persisted
    legacy_keys: tuple[str, str] # (lexical, semantic) legacy excerpt keys (3.8)
```

Index entry (`content_assembler.py`): exactly one entry per span bound to at least one lesson.
```python
@dataclass(frozen=True)
class IndexEntry:
    span_id: str; item_id: str; item_version: str
    item_kind: Literal["document", "authored"]
    section_ordinal: int; start: int; end: int; content_hash: str
    title: str
    source_kind: Literal["document", "lesson"]    # "lesson" for authored (API compatibility)
    source_title: str
    excerpt: str                                  # full span text
    source_filename: str | None
    lesson_slugs: tuple[str, ...]                 # blueprint order, len >= 1
    module_indexes: tuple[int, ...]               # module index per lesson slug (p1-floor boost) [R1]
    title_words: frozenset[str]                   # retrieval_p1._tokenize(title) (p1-floor whole words) [R1]
    excerpt_words: frozenset[str]                 # retrieval_p1._tokenize(excerpt)
    timestamp_label: None = None
    @property
    def chunk_id(self) -> str: return self.span_id
    @property
    def lesson_slug(self) -> str: return self.lesson_slugs[0]
```

Database table (`app/db_models.py`). It is append-only and **text-free**.
```python
class CorpusSpan(Base):
    __tablename__ = "corpus_spans"
    __table_args__ = (
        UniqueConstraint("span_id", "item_version", name="uq_corpus_spans_span_id_item_version"),
        CheckConstraint("plane = 'public'", name="ck_corpus_spans_public_plane"),
        Index("ix_corpus_spans_legacy_key_lexical", "legacy_key_lexical"),
        Index("ix_corpus_spans_legacy_key_semantic", "legacy_key_semantic"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    span_id: Mapped[str] = mapped_column(String(80), index=True)
    scheme: Mapped[str] = mapped_column(String(16))
    item_id: Mapped[str] = mapped_column(String(255), index=True)
    item_version: Mapped[str] = mapped_column(String(64))
    item_kind: Mapped[str] = mapped_column(String(16))
    plane: Mapped[str] = mapped_column(String(16), default="public")
    section_ordinal: Mapped[int] = mapped_column(Integer)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    source_title_hash: Mapped[str] = mapped_column(String(64))
    section_title_hash: Mapped[str] = mapped_column(String(64))
    legacy_key_lexical: Mapped[str] = mapped_column(String(64))
    legacy_key_semantic: Mapped[str] = mapped_column(String(64))
    corpus_version_first_seen: Mapped[str] = mapped_column(String(64))
    registered_by: Mapped[str] = mapped_column(String(32))   # "write-through" | "register-job" | "migration"
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

**Rules for the table**
- No column matches the erasure identity pattern (`(user|player|guest|author|opponent|reviewer|learner|account)[a-z_]*_id$`). The table holds no learner data, and erasure and retention do not touch it.
- Append-only triggers come from `schema_upgrades` (4.6). Inserts are insert-if-missing on (span_id, item_version), and `ON CONFLICT DO NOTHING` fires no UPDATE trigger.
- The Alembic revision is `apps/api/alembic/versions/20261119_phase2_corpus_spans.py` (`down_revision = "20260827_cs595_increment"`). The strict xfail `test_alembic_head_builds_the_orm_schema` stays: the chain still cannot build an empty database.

### 2.3 Citation v2 (`app/schemas.py`)
```python
class Citation(BaseModel):
    chunk_id: str                        # == span_id for native and migrated citations
    span_id: str | None = None
    corpus_version: str | None = None
    content_hash: str | None = None      # v2: sha256 of the FULL span text (v1 was excerpt-based)
    source_title: str
    source_kind: str
    section_title: str
    excerpt: str                         # display excerpt, <= 320 chars
    timestamp_label: str | None = None
    source_filename: str | None = None
    provisional: bool = True             # AC-1-13; lifted only per 3.9
    citation_schema: int = 1             # 2 for anything written by Phase 2 code
    item_id: str | None = None
    item_version: str | None = None
    start: int | None = None
    end: int | None = None
    resolution: Literal["resolved", "legacy_unresolved"] = "legacy_unresolved"
    migration_status: Literal["native", "migrated", "legacy_unresolved"] | None = None
    unresolved_reason: str | None = None # excerpt_no_match | excerpt_ambiguous | chapter_summary_excluded |
                                         # missing_excerpt | invalid_shape | not_resolvable_on_read
    legacy_chunk_id: str | None = None
    legacy_span_id: str | None = None
    near_floor: bool = False
    label: str | None = None             # "unverified historical reference" when legacy_unresolved
```

The defaults are conservative: a v0 or v1 dict comes back as `legacy_unresolved` and `provisional=True`.

**Schema detection.** The schema is detected from `citation_schema` and never from the id format. v1 and v2 span ids share the `span-<64 hex>` form [R28].

**Storage.** A migrated citation keeps the full original dict under `legacy_original`. Pydantic ignores that key, so the API never returns it.

| Shape | Keys |
|---|---|
| v0 (2026-04-05 build) | `chunk_id`, `source_title`, `source_kind`, `section_title`, `excerpt`, `timestamp_label` |
| v1 (CS595, Phase 1) | v0 plus `span_id`, `corpus_version`, `content_hash`, `source_filename`, `provisional` |
| v2 | all of the above plus the Phase 2 fields, with `citation_schema == 2` |

### 2.4 SearchResult v2 (`app/schemas.py`)
New fields are added after the existing ones, and `chunk_id` stays:
```python
span_id: str | None = None; item_id: str | None = None; item_version: str | None = None
start: int | None = None; end: int | None = None; content_hash: str | None = None
lesson_slugs: list[str] = Field(default_factory=list)
near_floor: bool = False
```

**Field semantics** [R1]
- **`score`**:
  - `bm25f-v1`: the BM25F evidence score, rounded to 4 places.
  - `p1-floor`: the legacy score, rounded to 3 places, which is today's value.
- **`lesson_slug`** is the request's `lesson_slug` when one is given. Otherwise:
  - `bm25f-v1`: `lesson_slugs[0]`;
  - `p1-floor`: the lesson that gave the boost (3.7a).
- **`excerpt`** is `truncate_display_excerpt(entry.excerpt, 320)`.
- **`timestamp_label`** is always None.
- **`near_floor`** is always false under `p1-floor`.

### 2.5 Configuration package v1 (`apps/api/app/config_package/v1.json`)
The package ships in the image, because the Dockerfile copies `apps/api/app`.

Next to it, `v1.json.sha256` holds one line: the hex sha256 of `canonical_json(json.load(v1.json))`.
- The loader strips whitespace, so a CRLF checkout reads the same value [R19].
- The hash is taken over canonical JSON, not file bytes.

```json
{
  "package": "qcai-configuration-package",
  "package_version": "1.0.0",
  "schema_version": 1,
  "phase": "2",
  "status": "provisional",
  "created": "2026-11-19",
  "span_identity": {
    "scheme": "span-v2",
    "id_inputs": ["scheme", "item_id", "start", "end", "content_hash"],
    "item_id_rule": "source_asset_id(filename, kind) | authored-curriculum",
    "canonical_text": "sections-v1",
    "section_separator": "\n\n\n", "heading_separator": "\n\n",
    "offset_unit": "unicode-code-point",
    "splitter": {"library": "langchain-text-splitters", "version": "1.1.2",
                 "class": "RecursiveCharacterTextSplitter", "chunk_size": 700, "chunk_overlap": 120},
    "parser": {"library": "python-docx", "version": "1.2.0", "function": "parse_docx_sections"}
  },
  "corpus_version": {"scheme": "corpus-version-v2",
                     "inputs": ["item_id", "version", "sha256", "plane", "bound", "span_scheme"]},
  "gates": {
    "p1-floor": {"version": "score-floor-p1-v1", "floor": 6, "authority": "P1-D-04",
                 "stopwords": "retrieval_p1.QUERY_STOPWORDS (178 words, frozen)",
                 "scope": "containment for the D-31 configuration; see conflict 29"},
    "bm25f-v1": {"see": "retrieval, abstention"}
  },
  "retrieval": {
    "algorithm": "bm25f-simple-v1",
    "k1": 1.5, "b": 0.75, "title_weight": 2.0,
    "idf": "ln(1+(N-df+0.5)/(df+0.5))",
    "tokenizer": {"version": "nfkc-casefold-alnum-v1", "min_token_length": 2, "stemmer": "none"},
    "stopwords": {"version": "stopwords-v1", "sha256": "<computed>", "words": ["…sorted…"]},
    "coverage_rule": "coverage-v1",
    "tie_break": "span_id ascending",
    "module_boost": false,
    "chapter_summaries_indexed": false
  },
  "semantic": {"enabled_by_default": false, "vector_id_scheme": "span-v2",
               "require_namespace_count_equals_span_count": true,
               "apply_active_gate_to_every_result": true},
  "abstention": {"version": "abstention-p2-v1", "floor": 2.35, "margin": 2.40,
                 "provisional": true, "provisional_until": "Phase 4", "not_final_before": "E1 freeze",
                 "calibration_record": "docs/evaluation/phase2/calibration_record_v1.json",
                 "calibration_record_sha256": "<canonical sha256 of the record>"},
  "near_duplicate": {"version": "near-dup-v1", "provisional": true,
                     "document_shingle_words": 5, "document_jaccard_threshold": 0.5,
                     "document_containment_threshold": 0.8,
                     "video_duration_tolerance_s": 0.5, "video_size_ratio_tolerance": 0.01,
                     "chapter_shingle_words": 5, "chapter_jaccard_threshold": 0.5},
  "legacy_citations": {"decision": "D-30", "status": "provisional", "ratified": false,
                       "match_rule": "unique normalised-excerpt hash (D3); titles, containment and v1 content_hash are diagnostics",
                       "max_unresolved_share_native": 0.0, "max_unresolved_share_legacy": null,
                       "stop_on_exact_match_regression": true,
                       "stop_on_non_canonical_row_in_apply": true,
                       "unresolved_label": "unverified historical reference",
                       "dual_read_releases": 2},
  "owner_decisions": {
    "D-17": {"option": "a", "text": "interim, migrate by Phase 11", "status": "provisional",
             "authority": "P1-D-18 (owner delegation, 2026-11-19)", "ratified": false,
             "record": "docs/adr/ADR-002-retrieval-architecture.md (Revision 2026-11-19)"},
    "D-30": {"status": "provisional", "authority": "P1-D-18", "ratified": false,
             "rule": "pre-Phase-2 citations that cannot be resolved are labelled legacy_unresolved and never presented as resolved; the migration report shows their share; citations created by the Phase 2 pipeline must resolve 100%"},
    "Q-10": {"state": "unresolved", "path": "2025 asset only (plan Action 25 stop condition)",
             "unbound_items": [{"item_id": "quantum-computing-and-artificial-intelligence-2026",
                                "asset_filename": "Quantum Computing and Artificial Intelligence 2026.mp4"}]}
  },
  "boundary": {"version": "boundary-v1",
               "private_plane_globs": ["corpus/private/**", "lqs/private/**", "lqs/ratings/*.private.jsonl",
                                       "docs/thesis/ethics/private/**", "evaluation/reports/*.private.json",
                                       "**/*.private.json", "**/*.private.jsonl"],
               "public_exceptions": ["corpus/private/README.md"],
               "licensed_volume_globs": ["**/*.pdf"],
               "secret_like_name_globs": [".env", ".env.*", "**/.env", "**/.env.*", "**/*.env", "**/*.env.yaml", "**/*.env.local"],
               "passage_shingle_words": 12, "passage_min_hits_per_file": 1}
}
```

There is no `flags_default` block; `Settings` is the only source of truth for defaults [R19].

**Floor and margin.** `scripts/calibrate_abstention.py --write --update-package` writes them. The values shown are prototype values from the cal-fold windows (0.2b). The engineer commits what the script outputs.

### 2.6 `GET /spans/{span_id}` response (`SpanResolution`)
```json
{"span_id": "span-<64 hex>", "scheme": "span-v2", "item_id": "authored-curriculum",
 "item_version": "sha256:<16>", "kind": "authored", "plane": "public", "section_ordinal": 3,
 "start": 10234, "end": 10871, "content_hash": "<64 hex>", "servable": false, "current": true,
 "registered": true, "corpus_version_first_seen": "corpus-<16>", "corpus_version": "corpus-<16>",
 "excerpt": null}
```

**Errors.** The route returns 404 `{"detail": "Span not found."}` with `Cache-Control: no-store` [R24] in all of these cases:
- the route is disabled;
- the id does not match `^span-[0-9a-f]{64}$`;
- the id is unknown;
- the plane is not public;
- in a governed build, the span belongs to a document whose item is not approved.

**Success.** A 200 response carries `Cache-Control: public, max-age=300, stale-while-revalidate=60` (`content.PUBLIC_CONTENT_CACHE_CONTROL`).

### 2.7 Citation migration report (`--report PATH`, also printed to stdout)
The report holds counts only: no learner ids, row ids or excerpts.
```json
{
  "report": "qcai-citation-migration", "format_version": 1,
  "mode": "dry-run | apply | downgrade",
  "generated_at": "…Z", "commit": "<GIT_SHA or unknown>",
  "database_dialect": "sqlite | postgresql",
  "span_scheme": "span-v2", "corpus_version": "corpus-<16>",
  "config_package": {"version": "1.0.0", "sha256": "<hex>"},
  "span_sources": {"memory_spans": 1071, "database_rows": 0, "memory_items": ["…item ids…"]},
  "tables": {
    "qa_interactions": {
      "rows_scanned": 0, "rows_with_citations": 0, "rows_changed": 0,
      "rows_skipped_null": 0, "rows_skipped_non_canonical": 0, "rows_cas_conflict": 0,
      "citations": {"total": 0, "native_v2": 0, "already_migrated": 0, "migrated": 0,
                    "legacy_unresolved": 0,
                    "by_reason": {"excerpt_no_match": 0, "excerpt_ambiguous": 0,
                                  "chapter_summary_excluded": 0, "missing_excerpt": 0, "invalid_shape": 0},
                    "diagnostics": {"key_lexical": 0, "key_semantic": 0, "title_equal": 0, "title_differs": 0,
                                    "containment_also_in_other_span": 0, "v1_content_hash_agrees": 0},
                    "restored": 0}
    },
    "tutor_turns": {"…same…": "…", "claims": {"total": 0, "remapped": 0, "bound_to_unresolved": 0, "restored": 0}}
  },
  "totals": {"legacy_citations": 0, "migrated": 0, "legacy_unresolved": 0,
             "unresolved_share": null, "unresolved_share_wilson95": null,
             "native_citations": 0, "native_unresolved": 0, "exact_match_regressions": 0},
  "threshold": {"decision": "D-30", "status": "provisional",
                "max_unresolved_share_native": 0.0, "max_unresolved_share_legacy": null,
                "result": "pass | stop", "stop_reasons": []}
}
```
**Exit codes:** `0` pass, `3` stop condition (conflict 14), `2` usage error, `1` other error.

### 2.8 Calibration record (`docs/evaluation/phase2/calibration_record_v1.json`) [R2, R3, R4]
```json
{
  "record": "qcai-abstention-calibration", "format_version": 1,
  "created_at": "…", "commit": "…",
  "config_package_version": "1.0.0", "retrieval_sha256": "<canonical sha256 of package.retrieval>",
  "corpus_version": "corpus-<16>", "span_scheme": "span-v2",
  "public_corpus_only": true,
  "excluded_sources": ["private plane", "lqs/ (ULQS)", "learner records, tutor turns, ratings"],
  "datasets": {
    "fixture": {"path": "apps/api/tests/data/phase2_calibration_queries.json", "sha256": "<canonical sha>",
                "sources": {"BEP-1/27_score_floor/fixture.json": "<sha256>", "BEP-1/27_score_floor/holdout.json": "<sha256>"},
                "fold_rule": "sha256(query) first hex digit even -> cal, odd -> conf (pre-registered, BEP-1)",
                "strata": {"oos_general": 60, "oos_lexical": 16, "near_miss": 15, "stop_only": 16,
                           "in_suggested": 36, "in_flashcard": 36, "in_short": 36, "in_paraphrase": 24,
                           "in_multi": 10, "in_quiz": 8, "holdout_in": 24, "holdout_oos": 40, "holdout_stop": 8}},
    "ac_fixture": {"path": "apps/api/tests/data/score_floor_queries.json", "sha256": "<canonical sha>",
                   "note": "AC-2-4/AC-2-5 fixture (Phase 1); equals the union of the gated strata above"},
    "learner_questions": {"source": "MODULE_BLUEPRINTS learner_questions, label = own lesson", "count": 36}
  },
  "metric_definitions": {
    "recall_at_5": "expected lesson in the union of lesson_slugs of the top 5 survivors (BEP-1 definition, generalised)",
    "recall_at_5_slot_equal": "expected lesson among the first 5 (span, lesson) pairs, lessons expanded in blueprint order (informational)",
    "answer_rate": "share of in-domain queries with >= 1 document span among the top 4 survivors (all-approved configuration)"
  },
  "grid": {"start": 0.0, "stop": 20.0, "step": 0.05},
  "configurations": [
    {"name": "governed_as_configured", "description": "committed manifest, D-31: zero approved; authored spans only",
     "index_version": "index-<16>", "entries": 41,
     "legacy": {"algorithm": "score-floor-p1-v1", "recall_at_5": {"cal": 63, "conf": 52, "holdout": 16, "all": 131},
                "learner_questions_recall_at_5": 36},
     "p1_floor_on_span_index": {"recall_at_5_all": 131, "equals_legacy_per_query": true,
                                "strata_with_results": {"oos_general": 0, "stop_only": 0, "oos_lexical": 0, "near_miss": 1}},
     "sweep": [{"floor": 0.0, "cal": {"oos_with_results": 0, "recall_at_5": 0}, "learner_questions_recall_at_5": 0}],
     "feasible_window_cal": [0.0, 4.75]},
    {"name": "all_public_approved", "description": "every public-plane bound item approved (temporary manifest)", "…": "…"}
  ],
  "selection": {"rule": "feasible on the cal fold (no oos_general/stop_only result; recall >= legacy) and on the learner questions; floor = midpoint of the intersection, rounded down to 0.05; margin = upper end - floor, rounded down to 0.05",
                "intersected_window": [0.0, 4.75], "floor": 2.35, "margin": 2.40},
  "confirmation": {"conf_fold": {"governed_as_configured": {"recall_at_5": 61, "legacy": 52, "oos_with_results": 0}},
                   "holdout_b": {"governed_as_configured": {"recall_at_5": 22, "legacy": 16, "oos_with_results": 0}},
                   "ac_fixture": {"ac_2_4_oos_with_results": 0, "ac_2_5_recall": {"governed": 151, "all": 142}},
                   "result": "pass | stop"},
  "reported_strata_vs_p1": {"near_miss": {"bm25": {"governed": 2, "all": 10}, "p1": {"governed": 1, "all": 7}},
                            "oos_lexical": {"bm25": {"governed": 0, "all": 3}, "p1": {"governed": 0, "all": 2}},
                            "in_multi_recall_at_5": {"…": "…"},
                            "regression_vs_p1": true},
  "stress_probes": {"note": "informational; off-topic fixture question + a course bigram", "results": {"…": "…"}},
  "answer_rate": {"phase0_proxy": {"value": "174/174", "source": "BEP-1/27_score_floor/PROPOSAL.md §3 (b3d6808c, pre-floor)"},
                  "bm25": "166/174", "p1": "146/174", "within_5_points": {"bm25": true, "p1": false}},
  "fragility": ["all_public_approved learner_questions recall_at_5 28 = legacy 28 (zero slack); slot-equal 27"],
  "provisional": true, "provisional_until": "Phase 4", "not_final_before": "E1 freeze (plan Phase 2 H)",
  "shipping_gate": {"outside_development": "p1-floor", "switch_requires": "D-05 remediation approval (R-15)"},
  "limitations": [
    "coverage-v1 and the framing stopwords (define, definition, term, terms, word, words) were designed after inspecting leaks on the whole repo fixture, including the conf fold and hold-out B; AC-2-4 on it is design-set evidence",
    "near_miss and oos_lexical were not used in design; bm25f-v1 returns more results than P1 on both",
    "learner questions appear verbatim in authored spans (circular for the governed configuration)",
    "no ULQS calibration split yet (Phase 4)",
    "the Phase 0 answer rate is a proxy measured at b3d6808c before the floor"
  ],
  "result": "pass | stop"
}
```

### 2.9 Boundary-scan report and fingerprint file
**Report** (paths only, never content):
```json
{
  "report": "qcai-boundary-scan", "format_version": 1, "policy": "boundary-v1",
  "scans": [
    {"target": "repository", "listing": "git ls-files", "files": 0,
     "private_plane_paths": [], "licensed_volume_paths": []},
    {"target": "docker-context", "dockerfile": "apps/api/Dockerfile", "context": ".",
     "ignore_file": ".dockerignore", "listing": "filesystem walk filtered by the context's .dockerignore",
     "files": 0, "image_source_files": 0,
     "private_plane_paths": [], "licensed_volume_paths": [], "secret_like_paths": []},
    {"target": "docker-context", "dockerfile": "apps/frontend/Dockerfile", "context": "apps/frontend",
     "ignore_file": "apps/frontend/.dockerignore", "…": "…"},
    {"target": "release-zip", "path": "dist/release/x.zip", "entries": 0,
     "private_plane_paths": [], "licensed_volume_paths": [], "secret_like_paths": []}
  ],
  "passage_scan": {"status": "not_run",
                   "reason": "no licensed-passage fingerprint file was supplied; passage scanning was not run"},
  "path_scan_result": "pass | fail",
  "passage_scan_result": "not_run | pass | fail"
}
```

**When a passage scan runs**, the `passage_scan` block holds:
- `status: "run"`
- `fingerprint_set_id`
- `files_scanned`
- `files_with_hits: [{"path", "hits"}]`
- `skipped_secret_like_files`

`secret_like_paths` lists names only and is never opened. It fails the scan for an image context or a release zip; for the repository listing it is informational [R16].

**Fingerprint file.** It comes from the private plane, is never committed, and reaches a run only as a path argument.
```json
{"format": "qcai-licensed-fingerprints/1", "fingerprint_set_id": "…", "normalization": "nfkc-casefold-alnum-v1",
 "shingle_words": 12, "hash": "hmac-sha256-trunc32", "salt_hex": "<64 hex>", "fingerprints": ["<32 hex>", "…"]}
```

### 2.10 Legacy baseline snapshot (`apps/api/tests/data/legacy_p1_baseline.json`)
Recorded once from the unmodified code at `a257dd11`. Queries are keyed by sha256.
```json
{"snapshot": "legacy-p1-baseline", "commit": "a257dd11…", "algorithm": "score-floor-p1-v1",
 "fixture_sha256": {"score_floor_queries": "…", "phase2_calibration_queries": "…"},
 "configurations": {
   "governed_empty": {"recall_at_5": 131, "learner_questions_recall_at_5": 36,
                      "per_query": [{"q": "<sha256>", "top5": [["<legacy chunk_id>", "<lesson_slug>", 15.0]]}]},
   "all_public_approved": {"recall_at_5": 129, "learner_questions_recall_at_5": 28, "per_query": []}},
 "ungated_recall_at_5": {"all_public_approved": 124},
 "out_of_scope_with_results": {"governed_empty": 0, "all_public_approved": 0}}
```

---

## 3. Exact algorithms

### 3.1 Canonical text (`sections-v1`)
`canonical_json(o) = json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`.

**Documents**
1. `sections = parse_docx_sections(path)`. The only change to the parser is that each `SectionRecord` gets `ordinal = index`.
2. Build the text:
   ```
   parts, body_starts, pos = [], [], 0
   for i, s in enumerate(sections):
       if i: parts.append("\n\n\n"); pos += 3
       parts.append(s.heading); pos += len(s.heading)
       parts.append("\n\n"); pos += 2
       body_starts.append(pos); parts.append(s.body); pos += len(s.body)
   text = "".join(parts)
   ```
3. Offsets are Python `str` indices. No Unicode normalisation is applied.
4. `source_title = DOCUMENT_TITLE_MAP.get(filename, Path(filename).stem)`.
5. `item_id = source_asset_id(filename, "document")` [R9].

**Authored item**
- The sections are the lessons in `MODULE_BLUEPRINTS` order, then `_module_lessons()` order. The heading is the lesson title.
- The body is exactly the legacy authored text:
  ```
  parts = [summary,
           "\n".join(f"Key idea: {x}" for x in key_ideas),
           "\n".join(f"Key note: {x}" for x in key_notes),
           "\n".join(f"Formula or diagram prompt: {x}" for x in formulas),
           "\n".join(f"Learner question: {x}" for x in learner_questions)]
  body = "\n\n".join(p for p in parts if p)
  ```
- The authored hash is `sha256(canonical_json(payload))`. The payload is a list in the same order, one entry per lesson, with the keys `lesson_slug`, `module_slug`, `title`, `summary`, `key_ideas`, `key_notes`, `formulas` and `learner_questions`.
- `source_title` and `section_title` are both the lesson title.

### 3.2 Span offsets
For each section:
```
splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=120)   # from the package
index = 0; previous = 0
for chunk in splitter.split_text(body):
    offset = index + previous - 120
    local = body.find(chunk, max(0, offset))
    if local < 0: raise SpanBuildError(item_id, ordinal)
    start = body_starts[ordinal] + local; end = start + len(chunk)
    assert text[start:end] == chunk
    index = local; previous = len(chunk)
```

**Version check [R7].** On the first build in a process (not at import), `spans.py` checks two versions against the package:
- `importlib.metadata.version("langchain-text-splitters")` against `span_identity.splitter.version`;
- `importlib.metadata.version("python-docx")` against `span_identity.parser.version`.

A mismatch raises `SpanBuildError`, because a new scheme version would be needed. Note that `langchain_text_splitters.__version__` is `None` in 1.1.2 and must not be used.

### 3.3 Content hash and span id
- `content_hash = sha256(text[start:end].encode("utf-8")).hexdigest()`
- `span_id = "span-" + sha256(canonical_json({"scheme": "span-v2", "item_id": item_id, "start": start, "end": end, "content_hash": content_hash})).hexdigest()`

`corpus_version`, `item_version`, licence fields and lesson slugs never enter the id. Spans are deduplicated on (item_id, start, end). The duplicate-id SLI is `len(all) − len(unique ids)`, and it must be 0.

### 3.4 corpus_version and index_version
**`corpus_version`**
- Formula: `"corpus-" + sha256(canonical_json({"scheme": "corpus-version-v3", "span_scheme": "span-v2", "items": sorted([[i.id, i.version, i.sha256] for i in built_items])}))[:16]` (plan 11.1).
- Built items: public-plane, bound items the build admits. A governed build admits the authored item and the approved items; development admits every public-plane, bound item. The manifest records the governed value.
- Partial approval changes it; a licence-field edit does not.
- A 1.0 manifest keeps the legacy formula `"manifest:" + sha256(file bytes)[:16]`.
- With no manifest it is `"development-unreviewed"`.

**`index_version`**
- Formula: `"index-" + sha256(canonical_json({"corpus_version": cv, "gate": active_gate, "retrieval_sha256": sha256(canonical_json(package["retrieval"])), "entries": sorted([[e.span_id, sorted(e.lesson_slugs)] for e in index])}))[:16]` [R28].

### 3.5 Tokenisation and stopwords for bm25f-v1
```
def tokenize(text):
    norm = unicodedata.normalize("NFKC", text).casefold()
    return [t for t in re.findall(r"[^\W_]+", norm) if len(t) >= 2 and t not in STOPWORDS]
```

`stopwords-v1` is the union of three lists:
- (a) the Phase 1 `QUERY_STOPWORDS`, verbatim;
- (b) the two-letter function words `am an as at be by do go he if in is it me my no of oh ok on or so to up us we`;
- (c) the framing words `define definition term terms word words`.

The package stores the sorted unique list and the sha256 of `"\n".join(sorted(words))`. The loader recomputes that hash.

### 3.6 BM25F-simple (`bm25f-simple-v1`)
**Weighted term frequency and length** (title weight `w`):
- `tf'(t) = tf_body(t) + w·tf_title(t)`
- `dl' = |body| + w·|title|`; `avgdl'` is its mean over the index.

**IDF** is computed over the whole index, never per lesson filter:
- `idf(t) = ln(1 + (N − df + 0.5)/(df + 0.5))`

**Score** of entry `e` for the unique query tokens `Q`:
- `score(e) = Σ_{t∈Q, tf'>0} idf(t)·tf'(t)·(k1+1)/(tf'(t) + k1·(1 − b + b·dl'/avgdl'))`

There is no module or lesson boost.

### 3.7 Sufficiency gate for bm25f-v1 (`coverage-v1`, `abstention-p2-v1`)
**Per entry**
- `m(e) = |{t ∈ Q : tf'_e(t) > 0}|`
- `eligible(e) = (|Q| ≥ 2 and m(e) ≥ 2) or (|Q| == 1 and tf_title_e(q) > 0)`
- `s = round(score, 9)`
- the entry is returned iff `eligible(e) and s ≥ floor`
- `near_floor = s < floor + margin`

**Order and filtering.** Results are sorted by `(−s, span_id)`. The lesson filter (`lesson_slug ∈ e.lesson_slugs`) applies after scoring, and `top_k` applies after the gate.

**Abstention reasons:**
- `no_query_terms`: `Q` is empty;
- `no_match`: no entry has `m(e) ≥ 1`;
- `insufficient_coverage`: no entry is eligible;
- `below_floor`: no entry reaches the floor;
- otherwise the decision is `evidence`.

### 3.7a The p1-floor gate over the span index (`score-floor-p1-v1`; default outside development) [R1]
This is today's `CourseStore.search` applied to `IndexEntry`s. It uses the verbatim P1 helpers in `app/services/retrieval_p1.py`.

1. Compute the query sets:
   - `query_terms = set(_tokenize(query))`
   - `floor_terms = query_terms − QUERY_STOPWORDS`
   - `raw = query.strip().lower()`
   - if `raw` is empty, abstain with `no_query_terms`.
2. For each entry passing the lesson filter:
   - `title_overlap = Σ[t in e.title.lower()]` and `excerpt_overlap = Σ[t in e.excerpt.lower()]`, both substring matches, as today;
   - `phrase_bonus = (4 if raw in title else 2 if raw in excerpt else 0) if len(raw) ≥ 3 else 0`;
   - skip the entry if all three values are 0;
   - skip it if `_floor_score(floor_terms, e, phrase_bonus) < SCORE_FLOOR` (6), which uses `e.title_words` and `e.excerpt_words`.
3. Pick the boost lesson:
   - with a request `lesson_slug`, that lesson;
   - otherwise the lesson in `e.lesson_slugs` with the highest module index (first in blueprint order on a tie). This mirrors the best-ranked legacy duplicate.
4. `boost = module index of that lesson + (0.1 if authored else 0)`.
5. `score = 3·title_overlap + 2·excerpt_overlap + phrase_bonus + boost`, rounded to 3 places.
6. Sort by score, descending and stable on index order. `top_k` applies after the gate, and `near_floor` is false.

**Abstention reasons:** `no_query_terms`, `no_match` or `below_floor`.

In the governed D-31 configuration this gate returns exactly today's results (test 41).

### 3.8 Legacy excerpt keys and migration matching [R5, R6]
Notation: `ws(x) = " ".join(x.split())` and `T = truncate_display_excerpt`.

**Keys**
- For a span:
  - `legacy_key_lexical = sha256(ws(T(T(text,320),320)))`;
  - `legacy_key_semantic = sha256(ws(T(text,320)))`.
- For a stored citation: `k = sha256(ws(citation["excerpt"]))`.
- Diagnostic only: a v1 `content_hash` equals `legacy_key_semantic` on the lexical path, and `sha256(ws(full text))` on the semantic path [R28].

**Per legacy citation (v0 or v1)**
1. Not a dict, or `chunk_id` or `excerpt` missing: `invalid_shape`.
2. `source_kind == "video"`: `chapter_summary_excluded` (task 2.7).
3. Blank excerpt: `missing_excerpt`.
4. `candidates` = the distinct `span_id`s of all spans, in memory or in the database, with `k ∈ {legacy_key_lexical, legacy_key_semantic}`. There is **no title filter** (D3).
5. Zero candidates: `excerpt_no_match`. Several: `excerpt_ambiguous`. Exactly one: **migrated**.
6. Diagnostics, which never change the outcome:
   - whether the source and section title hashes are equal;
   - whether another span's `ws(normalize_display_text(text))` contains `ws(excerpt)` without a trailing "...";
   - whether the v1 `content_hash` agrees;
   - the key used (lexical or semantic).
   `match_basis` is `memory` or `database` (text-free).

**Migrated dict:**
`{**original, "chunk_id": new, "span_id": new, "content_hash": span.content_hash, "corpus_version": <current>, "item_id", "item_version", "start", "end", "citation_schema": 2, "resolution": "resolved", "migration_status": "migrated", "provisional": <3.9>, "legacy_chunk_id": original["chunk_id"], "legacy_span_id": original.get("span_id"), "legacy_original": original}`.
In `--apply` only, the matched span is registered (`registered_by: "migration"`).

**Unresolved dict:**
`{**original, "citation_schema": 2, "resolution": "legacy_unresolved", "migration_status": "legacy_unresolved", "unresolved_reason": r, "label": "unverified historical reference", "provisional": true, "legacy_chunk_id": original["chunk_id"], "legacy_span_id": original.get("span_id"), "legacy_original": original}`.

**Claims.** Each `cited_span_ids` entry that equals the old `span_id` or `chunk_id` of a migrated citation in the same row is replaced, and the claim gets `legacy_original`. Claims still bound to unresolved ids are counted.

**Row procedure (byte-for-byte reversibility by construction):**
1. Read `id` and `CAST(col AS TEXT) AS raw`.
2. If `raw` is SQL NULL, JSON `null` or `[]`, skip and count the row.
3. Require `json.dumps(json.loads(raw)) == raw`, which is what SQLAlchemy `JSON` writes through psycopg's `Json` (builtin `json.dumps`) and through pg8000 (SQLAlchemy's `json_serializer`). Otherwise the row is never rewritten. It is counted as `rows_skipped_non_canonical`, and `--apply` reports a stop.
4. Build the new list. Rows already v2 are skipped and counted.
5. `UPDATE … SET col = :new WHERE id = :id AND CAST(col AS TEXT) = :raw`, written as JSON through SQLAlchemy. A `rowcount == 0` is counted as `rows_cas_conflict`. Each transaction holds 500 rows.
6. The run is monotonic: a `resolved` citation is never rewritten to unresolved, and an attempt to do so is counted as an exact-match regression.
7. **`--dry-run` writes nothing**, including no span registration.

**Downgrade.** Every dict that carries `legacy_original` is replaced by that value, for citations and claims, and `json.dumps(list)` is written with the same compare-and-set. Because of the precondition in step 3, the restored `CAST(col AS TEXT)` equals the original text on SQLite and on PostgreSQL `json`. Native v2 citations stay untouched.

### 3.9 Provisional flag
`provisional = not (settings.citation_provisional_lift_enabled and citation.resolution == "resolved")`. The same function is used on write and on read.

### 3.10 Near-duplicate gate (`near-dup-v1`)
The gate considers only bound, public-plane items, approved or not.

**Documents and the authored item.** 5-word shingles over `re.findall(r"[^\W_]+", NFKC(text).casefold())`. A pair is a near-duplicate iff the Jaccard index is at least 0.5 or the containment is at least 0.8.

**Videos.** A pair is a near-duplicate iff any of these holds:
- the `sha256` values are equal;
- the `size_bytes` are equal;
- both have a duration, `|Δduration| ≤ 0.5` and `|Δsize|/max(size) ≤ 0.01`;
- the curated-chapter fingerprint has a Jaccard index of at least 0.5.

The gate fails on any near-duplicate pair among bound items.

### 3.11 LFS pointers and hashing
A file is an LFS pointer iff all three hold:
- its size is under 1024 bytes;
- it starts with `b"version https://git-lfs.github.com/spec/v1\n"`;
- it has `oid sha256:<64 hex>` and `size <int>` lines.

For a pointer, `sha256 = oid` and `size_bytes = size`. Any other file is hashed in 1 MiB blocks.

`--video-hash size` (for in-suite tests [R25]) checks a pointer by oid and size, and a content file by size only. The CI step uses full hashing.

### 3.12 MP4 duration (`mp4-mvhd-v1`)
1. Walk the top-level boxes (32-bit size, a 64-bit largesize when size == 1, size 0 to the end).
2. Find `moov`, then `mvhd`.
3. Read the version and flags. Version 1: skip 16 bytes, then read `timescale` (u32) and `duration` (u64). Version 0: skip 8 bytes, then read u32 and u32.
4. Return `round(duration/timescale, 3)`, or None for a pointer or a missing box.

### 3.13 Path matching for the boundary scan [R10, R16, R17]
**Paths.** Paths are POSIX.

**Glob semantics.** `**` matches any number of segments, `*` stays within one segment, and a trailing `/` matches a directory prefix.

**Private-plane test (fail closed).** A path is private iff a `private_plane_globs` entry matches it and it is not a `public_exceptions` entry. The globs are matched against:
- the root-relative path, when one exists;
- **every component suffix** of the resolved absolute path. For example `app/corpus/private/x` matches `corpus/private/**` through its suffix `corpus/private/x`.

This holds whatever `project_root` resolves to. In the image it is `/app/source-assets` when `SOURCE_ASSETS_ROOT` is set and `/` when it is not.

**Licensed and secret-like tests.** These match the same globs against the path and its basename.

**Docker context listing.** The listing is a filesystem walk of CONTEXT filtered by CONTEXT's own `.dockerignore`: `apps/frontend/.dockerignore` for the frontend, the root file for the API. Under Docker semantics:
- patterns are relative to the context, with a leading `/` stripped;
- a pattern matches a path or any of its parent directories;
- `!` lines are refused (the existing test already forbids them).

`image_source_files` are the context files under the `COPY` and `ADD` sources:
- lines with `--from=` are skipped;
- globs such as `package*.json` are expanded;
- `COPY . .` means the whole filtered context.

**Content scanning (only when fingerprints are given)**
- Text-like extensions are scanned: `.py .md .txt .json .jsonl .csv .ts .tsx .js .mjs .html .css .yaml .yml .toml .ini .cfg .sql .xml .svg`, plus `.docx` via python-docx.
- Release-zip entries are read in memory for text-like names only.
- There is a 20 MB cap per file.
- Secret-like names are counted and never opened.

**Fingerprint.** `fp = hmac_sha256(salt, " ".join(words[i:i+12]).encode())[:32 hex]` over NFKC-casefolded `[^\W_]+` words.

### 3.14 Calibration selection rule (bm25f-v1) [R2, R4]
1. For each configuration, precompute each query's eligible list with no floor.
2. For each grid floor `f`, compute per stratum and fold:
   - the out-of-scope queries with at least one result at `s ≥ f`;
   - recall@5 (union, and slot-equal for information);
   - the answer rate.
3. `f` is **feasible on the cal fold** iff all three hold:
   - no `oos_general` or `stop_only` cal query returns a result;
   - in-domain cal recall is at least the legacy cal recall (frozen P1, same run);
   - learner-question recall is at least the legacy learner-question recall.
4. Take the largest contiguous feasible interval containing the lowest feasible floor, for each configuration. Intersect them as `[lo, hi]`.
5. `floor = floor_to_0.05((lo+hi)/2)` and `margin = floor_to_0.05(hi − floor)`.
6. **Confirm** on the conf fold, hold-out B and the AC fixture: no `oos_general`, `stop_only` or hold-out out-of-scope result, and recall at least the legacy recall per fold. Any failure means stop.
7. Report the `near_miss`, `oos_lexical`, `in_multi` and stress-probe results against P1, the answer rate against the proxy, and the zero-slack constraints. These are reported and do not gate the choice, as in BEP-1.
8. An empty intersection or a failed confirmation means `result: "stop"` (plan L), exit 3, and an unchanged package.

---

## 4. File-by-file changes
`NEW` marks a new file and `MOD` a modified one. Signatures are binding.

### 4.1 NEW `apps/api/app/config_package/v1.json` and `v1.json.sha256`
The content is given in 2.5.

### 4.2 NEW `apps/api/app/core/config_package.py`
```python
class ConfigPackageError(RuntimeError): ...
@dataclass(frozen=True) class RetrievalParams: algorithm: str; k1: float; b: float; title_weight: float
    min_token_length: int; stemmer: str; tokenizer_version: str; stopwords: frozenset[str]
    stopwords_version: str; stopwords_sha256: str; coverage_rule: str
@dataclass(frozen=True) class AbstentionParams: version: str; floor: float; margin: float; provisional: bool
    provisional_until: str; calibration_record: str; calibration_record_sha256: str
@dataclass(frozen=True) class NearDuplicateParams: shingle_words: int; jaccard: float; containment: float
    video_duration_tolerance_s: float; video_size_ratio_tolerance: float; chapter_shingle_words: int; chapter_jaccard: float
@dataclass(frozen=True) class BoundaryPolicy: private_plane_globs: tuple[str, ...]; public_exceptions: tuple[str, ...]
    licensed_volume_globs: tuple[str, ...]; secret_like_name_globs: tuple[str, ...]
    passage_shingle_words: int; passage_min_hits: int
@dataclass(frozen=True) class ConfigPackage:
    package_version: str; sha256: str; hash_verified: bool; path: Path; is_default_path: bool; raw: Mapping[str, Any]
    span_scheme: str; splitter: Mapping[str, Any]; parser: Mapping[str, Any]
    retrieval: RetrievalParams; retrieval_sha256: str; p1_floor: Mapping[str, Any]
    abstention: AbstentionParams; near_duplicate: NearDuplicateParams; boundary: BoundaryPolicy
    legacy_citations: Mapping[str, Any]; owner_decisions: Mapping[str, Any]
    q10_unbound_filenames: frozenset[str]; q10_unbound_item_ids: frozenset[str]
DEFAULT_PACKAGE_PATH = Path(__file__).resolve().parents[1] / "config_package" / "v1.json"
def canonical_json(value: Any) -> bytes
def canonical_sha256(value: Any) -> str
def load_config_package(path: Path, *, governed: bool) -> ConfigPackage
def get_config_package(settings: Settings | None = None) -> ConfigPackage   # cached per resolved path
```

**Validation**
- Required keys and types; `k1 > 0`, `0 ≤ b ≤ 1`, `title_weight ≥ 0`, `floor ≥ 0`, `margin ≥ 0`.
- The stopword list is sorted, unique and lowercase, and its hash matches.
- The scheme is `span-v2`.
- If Q-10 is unresolved, `unbound_items` is non-empty.
- `p1-floor.floor == 6`.

**On failure**
- A hash mismatch raises when governed. Otherwise it logs WARNING `config_package.hash_mismatch` and sets `hash_verified=False`.
- Structural errors always raise.

**Runtime boundary.** The loader **never opens** the calibration record, which is not in the image [R19]. A relative `CONFIG_PACKAGE_PATH` resolves against the cwd, like `CORPUS_MANIFEST_PATH`.

### 4.3 MOD `apps/api/app/core/config.py`
```python
config_package_path: str | None = None
retrieval_gate: Literal["p1-floor", "bm25f-v1"] | None = None        # [R1]
semantic_retrieval_enabled: bool = False
span_resolver_route_enabled: bool | None = None
citation_provisional_lift_enabled: bool = False                      # [R14] no refusal; override event instead
span_registry_write_through: bool = True
manifest_drift_check: Literal["off", "fast", "full"] = "fast"
spans_rate_limit: str = "30/minute"
```
In `validate_allowed_origins`:
- `retrieval_gate is None` becomes `"bm25f-v1"` in development and `"p1-floor"` elsewhere;
- `span_resolver_route_enabled is None` becomes `environment == "development"`.

### 4.4 NEW `apps/api/app/core/data_planes.py`
```python
class PrivatePlaneAccessError(PermissionError): ...
def relative_posix(path: Path | str, root: Path) -> str | None
def path_suffixes(path: Path | str) -> list[str]          # every component suffix of the resolved path [R10]
def is_private_plane_path(path: Path | str, root: Path, policy: BoundaryPolicy | None = None) -> bool
def is_licensed_volume_path(path: Path | str, root: Path, policy: BoundaryPolicy | None = None) -> bool
def is_secret_like_name(path: Path | str, policy: BoundaryPolicy | None = None) -> bool
def assert_public_plane_path(path: Path | str, root: Path, policy: BoundaryPolicy | None = None) -> None
def glob_match(rel_posix: str, pattern: str) -> bool
```
The checks fail closed: a path outside `root` is still checked through its suffixes (3.13).

### 4.5 MOD `apps/api/app/core/corpus_governance.py`
**`CorpusItem`** gains these fields, with defaults so 1.0 items still parse:
- `kind`, `plane`, `sha256`, `size_bytes`, `hash_basis`
- `asset_paths`, `bound`, `unbound_reason`, `storage`
- `spans_count`, `spans_set_sha256`, `media_duration_s`

For 1.0 items, `kind` comes from `source_asset_kind`.

**`CorpusRegistry`**:
```python
schema_version: str | None
def _load_items(self) -> tuple[CorpusItem, ...]                 # 1.0 and 2.0 (2.1 rules, incl. the id rule [R9])
@property corpus_version -> str
@property approved_items -> tuple[CorpusItem, ...]              # public_service and plane public and bound
@property authored_item -> CorpusItem | None
def item_for_filename(self, filename: str) -> CorpusItem | None
def span_item_id(self, filename: str) -> str                    # always source_asset_id(filename, kind) [R9]
def is_private_plane(self, filename: str) -> bool
def is_bound(self, filename: str) -> bool                       # manifest bound and not in the package Q-10 list
def is_public_asset(self, filename: str) -> bool                # governed: in approved_items; dev: not private
def is_indexable(self, filename: str) -> bool                   # is_public_asset and is_bound and not private
def is_servable_item(self, item_id: str) -> bool                # approved and document or video
def served(self, paths) -> list[Path]                           # unchanged contract (is_public_asset)
def drift_report(self, root: Path, mode: str, *, settings: Settings) -> DriftReport   # files via Settings._resolve_source_assets
@dataclass(frozen=True) class DriftReport: mode: str; checked: int; absent: int
    drifted: tuple[tuple[str, str], ...]; basis: Mapping[str, str]
```

**`review_problems`**
- It still iterates `approved_items` for the register checks.
- It **also** iterates `[i for i in registry.items if i.public_service]` and adds two problems [R15]:
  - `"<id>: private-plane item must not be approved for public service"`;
  - `"<id>: unbound item must not be approved for public service (Q-10)"`.

**Unchanged:** `get_corpus_registry` still creates a new instance on each call.

### 4.6 MOD `apps/api/app/core/schema_upgrades.py`
Add `_guard_corpus_spans(connection)`, re-created on every start like `_guard_security_events` (since Phase 3 spec 18.8 F8, checked on every start and, on PostgreSQL, re-created only when not current; noted in Phase 3 spec 18.10 H6):
- PostgreSQL: a function and the triggers `corpus_spans_append_only` (`BEFORE UPDATE OR DELETE … FOR EACH ROW`) and `corpus_spans_no_truncate` (`BEFORE TRUNCATE … FOR EACH STATEMENT`).
- SQLite: `DROP TRIGGER IF EXISTS` and `CREATE TRIGGER` for `corpus_spans_no_update` and `corpus_spans_no_delete`.

The statements contain no `%`.

### 4.7 MOD `apps/api/app/db_models.py`
Add `CorpusSpan` (2.2).

### 4.8 NEW Alembic revision
`20261119_phase2_corpus_spans` (2.2).

### 4.9 MOD `apps/api/app/services/docx_parser.py`
`SectionRecord.ordinal: int = 0`, set to the section's index. Nothing else changes.

### 4.10 NEW `apps/api/app/services/spans.py`
```python
SPAN_SCHEME = "span-v2"; CANONICAL_TEXT_VERSION = "sections-v1"
class SpanBuildError(RuntimeError): ...
def check_library_versions(package: ConfigPackage) -> None          # importlib.metadata; lazy, once [R7]
@dataclass(frozen=True) class CanonicalSection: ordinal: int; heading: str; body: str; body_start: int; lesson_slug: str | None
@dataclass(frozen=True) class CanonicalItem: item_id: str; item_version: str; kind: Literal["document","authored"]
    plane: Literal["public"]; source_title: str | None; source_filename: str | None; text: str
    sections: tuple[CanonicalSection, ...]
def content_hash(text: str) -> str
def span_id_for(item_id: str, start: int, end: int, content_hash: str, scheme: str = SPAN_SCHEME) -> str
def excerpt_key(excerpt: str) -> str
def legacy_excerpt_keys(text: str) -> tuple[str, str]
def make_splitter(package: ConfigPackage) -> RecursiveCharacterTextSplitter
def canonical_document(path: Path, *, item_id: str, item_version: str, source_title: str,
                       sections: list[SectionRecord] | None = None) -> CanonicalItem
def authored_payload(blueprints: list[dict]) -> list[dict]
def authored_sha256(blueprints: list[dict]) -> str
def canonical_authored(blueprints: list[dict], *, item_version: str) -> CanonicalItem
def build_spans(item: CanonicalItem, splitter) -> list[SpanRecord]
def span_set_digest(span_ids: Iterable[str]) -> str
class SpanRegistry: (get, for_section, records, duplicate_ids, __len__)
def build_identity_registry(settings: Settings, *, include_unapproved: bool) -> tuple[SpanRegistry, dict[str, CanonicalItem]]
```
**Rules**
- Every builder raises for a private-plane item or path.
- `build_identity_registry` covers the authored item plus every public-plane, bound document on disk. Unapproved documents are included only when `include_unapproved` is true (jobs only).

### 4.11 NEW `apps/api/app/services/lexical_index.py`
```python
ALGORITHM = "bm25f-simple-v1"
def tokenize(text: str, params: RetrievalParams) -> list[str]
@dataclass(frozen=True) class ScoredEntry: entry: IndexEntry; score: float; matched_terms: int; near_floor: bool
@dataclass(frozen=True) class RetrievalDecision:
    abstained: bool
    reason: Literal["evidence", "no_query_terms", "no_match", "insufficient_coverage", "below_floor"]
    results: tuple[ScoredEntry, ...]; query_terms: tuple[str, ...]
    gate: Literal["p1-floor", "bm25f-v1"]; floor: float; margin: float; threshold_version: str
class LexicalIndex:
    def __init__(self, entries: Sequence[IndexEntry], params: RetrievalParams, abstention: AbstentionParams,
                 *, gate: Literal["p1-floor", "bm25f-v1"]) -> None
    def query_terms(self, query: str) -> tuple[str, ...]
    def score_entry(self, terms: tuple[str, ...], entry: IndexEntry) -> tuple[float, int, bool]     # bm25f-v1
    def p1_score_entry(self, query: str, entry: IndexEntry, lesson_slug: str | None) -> tuple[float, bool, str]  # 3.7a
    def gate_entry(self, query: str, entry: IndexEntry, lesson_slug: str | None) -> ScoredEntry | None  # active gate; used by hybrid
    def eligible_unfloored(self, query: str) -> list[ScoredEntry]
    def evaluate(self, query: str, lesson_slug: str | None = None, top_k: int = 8) -> RetrievalDecision
```
The module implements 3.5-3.7a. No function takes any user, learner, history or page argument.

### 4.12 NEW `apps/api/app/services/retrieval_p1.py` (runtime; verbatim P1 helpers) [R1, R20]
- It moves `SCORE_FLOOR_VERSION`, `SCORE_FLOOR`, `QUERY_STOPWORDS`, `IndexedChunk` (with `__post_init__`), `_tokenize` and `_floor_score` verbatim from `content_assembler.py`.
- `content_assembler.py` **re-exports** these names, so `test_score_floor.py` imports keep working.
- `_floor_score` is duck-typed: it works on `IndexedChunk` or `IndexEntry` (`title_words`, `excerpt_words`).

### 4.12b NEW `apps/api/app/services/retrieval_legacy_p1.py` (FROZEN baseline)
Its docstring says it is a frozen copy of the pre-Phase-2 index build and search at `a257dd11`. It is used only by the AC-2-5 baseline tests and `scripts/calibrate_abstention.py`, and an AST test checks that no runtime module imports it.
```python
@dataclass(frozen=True) class LegacyResult: chunk_id: str; lesson_slug: str | None; score: float
    source_kind: str; title: str; excerpt: str
def build_legacy_chunks(settings: Settings, documents: list[Path], videos: list[Path]) -> list[IndexedChunk]
def legacy_search(chunks: list[IndexedChunk], query: str, lesson_slug: str | None = None, top_k: int = 8,
                  *, score_floor: int = SCORE_FLOOR) -> list[LegacyResult]
```
- `build_legacy_chunks` reproduces the old `CourseStore.build` chunk loop exactly: `_load_sections`, `_match_sections`, `_build_chunks` with video chapters, the authored fallback and module boosts. The 2026 video stays bound, as at `a257dd11`.
- It imports P1 helpers from `retrieval_p1`, plus blueprint helpers, the parser, `load_video_chapters`, `source_asset_id` and `text_utils`.

### 4.13 MOD `apps/api/app/services/content_assembler.py`
**Moves and re-exports.** P1 helpers move to `retrieval_p1` and are re-exported. `_build_chunks` and `_build_authored_lesson_chunks` move to the frozen module. `DOCUMENT_TITLE_MAP`, `ASSET_TITLE_MAP`, `MODULE_BLUEPRINTS`, `_lesson_blueprint`, `_module_lessons` and `_format_timestamp` stay.

**`CourseStore.__init__(settings)`** keeps its signature and gains these attributes:
- `package`, `registry`, `gate`
- `corpus_version`, `index_version`
- `items`, `span_registry`
- `chunks: list[IndexEntry]`, `entry_by_span_id`
- `index: LexicalIndex`, `duplicate_span_ids`

**`build()`**
1. **Inputs.**
   - Compute `package`, `registry`, `documents = registry.served(...)` and `videos = registry.served(...)`.
   - The overview assets use the served documents and videos (unchanged).
   - Compute `bound_docs`, `bound_videos` and `bound_assets` from `registry.is_indexable` [R11].
2. **Each bound document.** Parse it once and set `item_id = registry.span_item_id(name)` [R9]. Take the version from the 2.0 item, or else from the content bytes. Under 2.0, compare the sha256 of the bytes: governed builds raise `CorpusGovernanceError("manifest drift: …")`; development logs WARNING `corpus.drift` and uses the computed version.
3. **Authored item.** `version = "sha256:" + authored_sha256(MODULE_BLUEPRINTS)[:16]`. A mismatch with the 2.0 authored item raises when governed and warns in development [R27]. The authored item is built when there is no authored item in the manifest, or when it is bound.
4. **Duplicates.** Build `span_registry`. In a governed build, any duplicate span id raises.
5. **Lessons** (existing loop):
   - `video_asset` is chosen only among `bound_videos`.
   - Chapters are loaded only for a bound, served video.
   - `_collect_source_assets(bound_assets, …)` [R11], and related lessons use only bound assets.
6. **Index binding.**
   - Each matched section attaches `lesson.slug` to all spans of `(item_id, ordinal)`.
   - A lesson with no document spans is attached to its own authored section.
   - Entries carry `lesson_slugs` and `module_indexes` in blueprint order of first attachment, plus P1 word sets.
   - `chunks` is ordered by (first lesson position, item_id, start).
7. **Finish.**
   - `entry_by_span_id`
   - `gate = settings.retrieval_gate`
   - `index = LexicalIndex(chunks, package.retrieval, package.abstention, gate=gate)`
   - `index_version` (3.4)

**New methods**
```python
def evaluate(self, query: str, lesson_slug: str | None = None, top_k: int = 8) -> RetrievalDecision
def search(self, query: str, lesson_slug: str | None = None, top_k: int = 8) -> list[SearchResult]
def entry(self, span_id: str) -> IndexEntry | None
def to_search_result(self, scored: ScoredEntry, lesson_slug: str | None) -> SearchResult
```
`search` returns `[]` when the decision abstains.

### 4.14 MOD `apps/api/app/services/retrieval_engine.py`
**`RetrievalResponse`** gains `abstained`, `reason`, `gate`, `index_version`, `floor` and `margin`.

**`semantic_enabled`** is `settings.semantic_retrieval_enabled and backend.enabled and backend.aligned`.

**`sync_semantic_index(refresh)`** runs when `settings.semantic_retrieval_enabled and backend.enabled`, whether or not the backend is aligned. It is the only place that computes `aligned` [R18].

**`search(query, lesson_slug=None, top_k=8)`** keeps its signature and takes no learner input.
- **Lexical path:** `store.evaluate(...)`, mode `"lexical"`.
- **Hybrid path** (only when `semantic_enabled`):
  1. Drop semantic ids that are not in `store.entry_by_span_id`.
  2. Re-gate every remaining entry with `index.gate_entry` (the active gate, p1-floor or bm25f-v1) and drop the ones that fail [R18].
  3. Fuse the gated semantic and lexical lists with RRF (K = 60, weights 1.35 and 1.0).
  4. `score` is the active gate's evidence score.
  5. The mode is `"hybrid-pinecone"`. A semantic failure, or no gated semantic result, gives `"lexical-fallback"`.
- Every call records metrics and logs `retrieval.decision` (6.3).

**`PineconeSemanticBackend`**
- `enabled` also requires the setting.
- Payload ids are span ids. The metadata is `{"span_id", "span_scheme": "span-v2", "item_id", "item_version", "lesson_slugs"}`, with no excerpt or title text.
- `_matches_to_results` drops matches whose `span_scheme` is not `span-v2`, and builds results from in-memory entries only.
- The lesson filter is `{"lesson_slugs": {"$in": [lesson_slug]}}`.
- When the backend is not aligned, it logs WARNING `semantic.misaligned`.

### 4.15 MOD `apps/api/app/services/provenance.py`
This replaces the contents; `evidence_provenance` is removed (E-45).
```python
UNRESOLVED_LABEL = "unverified historical reference"
def provisional_flag(resolution: str, settings: Settings) -> bool
def native_citation(result: SearchResult, *, corpus_version: str, settings: Settings) -> Citation
def label_stored_citation(raw: Any, *, resolver: "SpanResolver", db: Session | None, settings: Settings,
                          registry: CorpusRegistry) -> Citation | None
```

**`label_stored_citation`** returns `None` (withheld) when either holds:
- the dict is not a valid shape;
- in a governed build, the citation's `source_filename` is set and `registry.is_public_asset(source_filename)` is false [R13].

Otherwise it works as follows:
- A v0, v1 or non-resolved v2 citation is returned as `legacy_unresolved`, labelled, with `provisional=True`.
- A resolved v2 citation is re-verified. If verification fails, it is downgraded to `not_resolvable_on_read` and a WARNING `citations.unresolved_on_read` is logged.

### 4.16 NEW `apps/api/app/services/span_resolver.py`
```python
SPAN_ID_PATTERN = re.compile(r"^span-[0-9a-f]{64}$")
@dataclass(frozen=True) class ResolvedSpan: span_id: str; scheme: str; item_id: str; item_version: str; kind: str
    plane: str; section_ordinal: int; start: int; end: int; content_hash: str
    corpus_version_first_seen: str; current: bool; registered: bool; servable: bool; text: str | None
class SpanResolver:
    def __init__(self, store: CourseStore) -> None
    def resolve_current(self, span_id: str) -> ResolvedSpan | None
    def resolve(self, span_id: str, db: Session | None = None) -> ResolvedSpan | None
    def verify(self, citation: Citation, db: Session | None = None) -> ResolvedSpan | None
```
- **`resolve`** checks memory first, then the database (latest row first; `corpus_version_first_seen` comes from the earliest row). It returns None for any non-public plane.
- **`servable`** requires all of:
  - a public plane;
  - a bound item;
  - `registry.is_servable_item`;
  - kind document;
  - `current`.
- **`verify`** requires the id to resolve, an equal `content_hash`, and an equal `item_id` when the citation has one.
- No method takes learner input.

### 4.17 NEW `apps/api/app/services/span_store.py`
```python
def persist_spans(db: Session, records: Iterable[SpanRecord], *, corpus_version: str, registered_by: str) -> int
def persist_cited_spans(db: Session, citations: Iterable[Citation], store: CourseStore, *, registered_by: str = "write-through") -> int
```
- Inserts are dialect-aware insert-if-missing: `on_conflict_do_nothing(index_elements=["span_id", "item_version"])`.
- No text is persisted.
- `persist_cited_spans` does nothing when write-through is off, and skips citations that are not resolved.

### 4.18 MOD `apps/api/app/services/contained_answers.py`
```python
def contain_answer(citations: list[Citation], registry: CorpusRegistry, spans: SpanRegistry | None = None,
                   *, settings: Settings | None = None) -> ContainedAnswer
```
1. `spans` defaults to `get_course_store().span_registry`, imported lazily. Callers that have a store pass its registry explicitly [R28].
2. A citation is quotable iff all of these hold:
   - `is_quotable` (unchanged);
   - the span exists;
   - the span's `content_hash` equals the citation's;
   - the span's `source_filename` equals the citation's;
   - `registry.is_indexable(span.source_filename)`.
3. A quoted copy uses `excerpt = truncate_display_excerpt(span.text, 320)` and the v2 fields, with `provisional=provisional_flag("resolved", settings)`. Answer lines and claims are built from these copies.
4. At most `MAX_QUOTED_SPANS` (3) citations are quoted. A schema-2 citation that fails verification counts as `dropped_unresolved`.
5. The texts and reasons are unchanged, and `grounded` stays false.

### 4.19 MOD `qa_engine.py`, `teaching_assistant.py` and `tutor_orchestrator.py`
**`QAEngine.ask` and `TeachingAssistantService.chat`**
- Citations are built with `native_citation(hit, …)`.
- They call `contain_answer(citations, get_corpus_registry(self.settings), self.retrieval_engine.store.span_registry, settings=self.settings)`.

**`TutorOrchestrator.chat`**
- It calls `contain_answer(candidate.citations, registry, spans=<the assistant's store span registry when available>, settings=self.settings)`.
- It calls `persist_cited_spans(...)` before `db.flush()`.

### 4.20 Routes and wiring
**NEW `routes/spans.py`:** `GET /spans/{span_id}`, rate-limited with `spans_rate_limit`, `response_model=SpanResolution`. It follows 2.6 and conflict 8, and its 404 responses carry `Cache-Control: no-store`.

**MOD `search.py`:** adds `X-Retrieval-Decision: evidence|abstain` and `X-Retrieval-Gate: p1-floor|bm25f-v1`.

**MOD `qa.py`**
- `ask_question` calls `persist_cited_spans` before commit.
- `_history_item`:
  - withdrawn rows are unchanged (R1.2);
  - other rows use `[c for c in (label_stored_citation(raw, …, registry=get_corpus_registry(settings)) for raw in record.citations or []) if c is not None]` [R13].

**MOD `assistant.py`:** calls `persist_cited_spans` before commit (idempotent).

**MOD `admin.py`:** the rebuild response adds `span_count`, `unique_chunk_ids`, `duplicate_span_ids`, `index_version` and `gate`.

**MOD `core/authorization.py`:** adds `("GET", "/spans/{span_id}"): _p(PUBLIC, NONE, "Rate-limited span metadata; 404 unless SPAN_RESOLVER_ROUTE_ENABLED; no excerpt under D-31.")`. Regenerate the matrix.

**MOD `assets.py`**
- After a path resolves, call `assert_public_plane_path(path, settings.project_root)`; a failure becomes 404 "Source asset not found.".
- `require_public_asset` uses the new `is_public_asset`.

**MOD `services/store.py`:** adds `get_span_resolver()` (`lru_cache`), cleared in `rebuild_course_store()`.

### 4.21 Scripts
Every script puts `REPO_ROOT` and `API_ROOT` on `sys.path`. None imports `app.services.store`.

**NEW `scripts/generate_manifest.py`**
- Options: `--output`, `--root`, `--check` (compares parsed JSON and prints a per-item diff), and `--video-hash full|size` (default `full`) [R25].
- The core is `app/core/manifest_v2.py`. Writing `with_all_public_approved` output to the repository path is refused.

**MOD `scripts/validate_corpus.py`**
- `--check-public-assets` keeps its output.
- `--check-hashes` covers AC-2-6:
  - files exist;
  - `sha256` and `size_bytes` match, with the basis printed;
  - span `count` and `set_sha256` are recomputed;
  - `corpus_version` is recomputed;
  - `--video-hash size` is supported.
- `--check-near-duplicates` (3.10).
- `--root`.

**NEW `scripts/scan_boundary.py`**
- Options:
  - `--repo` (`git ls-files`; `--working-tree` adds untracked files that are not ignored);
  - `--docker-context DOCKERFILE:CONTEXT`, repeatable, with defaults `apps/api/Dockerfile:.` and `apps/frontend/Dockerfile:apps/frontend`, each using its own context's `.dockerignore` [R16];
  - `--release-zip PATH`, repeatable;
  - `--fingerprints PATH`;
  - `--report PATH`.
- It exposes `fingerprint_shingles(text, salt, n)` for tests [R26].
- Exit code 1 when any of these is found:
  - a private-plane or licensed path in any target;
  - a secret-like name in an image context or zip;
  - passage hits.
- It never prints file contents.

**NEW, optional (defer to D-14 if short of time) [R26]: `scripts/make_passage_fingerprints.py`**
- Writes only to an output path outside the repository or under `corpus/private/**`.
- Prints counts only.

**NEW `scripts/calibrate_abstention.py`**
- `--write RECORD [--update-package]` follows 3.14.
- `--check RECORD` recomputes everything and ignores `created_at` and `commit`.
- Inputs under `lqs/` are refused.
- It reuses `evaluation.qcai_eval.statistics.wilson_interval` [R26].

**NEW `scripts/record_legacy_baseline.py`:** `--write PATH` (2.10). It is used once, at step 1.

**NEW wrappers:** `scripts/migrate_citations.py` and `scripts/register_spans.py`.

**NEW `scripts/config_package.py`:** `--check` and `--rehash`.

### 4.22 NEW workers and service
**`app/workers/register_spans.py`**
- `main(argv) -> int` with `--dry-run` (the default) or `--apply`.
- It uses `build_identity_registry(settings, include_unapproved=True)` and `persist_spans(..., registered_by="register-job")`.
- It logs one JSON line: `{"job": "register_spans", "status", "items", "inserted", "duration_ms"}`.

**`app/workers/migrate_citations.py`**
- `main(argv) -> int` with `--dry-run`, `--apply` or `--downgrade`, plus `--report`, `--batch-size 500` and `--tables`.
- It exits per 2.7.

**`app/services/citation_migration.py`**
```python
@dataclass(frozen=True) class MatchIndex: by_key: Mapping[str, tuple[SpanRef, ...]]; texts_available: bool
def build_match_index(db: Session, memory: SpanRegistry | None) -> MatchIndex
def classify_citation(raw: Any, index: MatchIndex, *, corpus_version: str, settings: Settings) -> tuple[dict, str, dict]  # (new, outcome, diagnostics)
def is_canonical_json_text(raw: str) -> bool
def migrate(db_factory, *, mode, memory, settings, package, tables, batch_size=500) -> dict
```

### 4.23 NEW `apps/api/app/core/manifest_v2.py`
`is_lfs_pointer`, `file_sha256_and_size(path, *, video_hash="full")`, `mp4_duration_seconds`, `lfs_tracked`, `compute_corpus_version`, `build_manifest(root, existing, package)` and `with_all_public_approved(manifest)`.

### 4.24 MOD `apps/api/app/main.py`
**`_initialize_database()`** runs these steps in order, before any database work:
1. Load the package with `get_config_package(settings)` (`governed=enforce_corpus_governance`).
2. `registry.assert_ready_to_serve()`.
3. Compute the drift report into `STARTUP_DRIFT`. A governed build with drift raises.
4. `create_all`, schema upgrades (with the `corpus_spans` guard) and retention, as today.

**`_record_configuration_overrides()`** adds these overrides outside development [R1, R14, R19]:
- `retrieval_gate_bm25` (when `retrieval_gate == "bm25f-v1"`)
- `semantic_retrieval_enabled`
- `span_resolver_route_enabled`
- `citation_provisional_lift_enabled`
- `config_package_path_overridden` (non-default path)
- `config_package_hash_unverified`

**`ROUTERS`** adds `spans.router`.

**`_build_fields()`** must stay deterministic:
- existing: `governance_enforced`, `corpus_version`, `commit`;
- added:
  - `config_package_version`, `config_package_sha256`
  - `span_scheme`, `index_version`, `retrieval_gate`
  - `duplicate_span_ids`, `manifest_drift`
  - `abstention_floor`, `abstention_margin`, `thresholds_provisional`
  - `semantic_enabled`

**`/ready`** adds `"slis"` (6.2).

### 4.25 NEW `apps/api/app/services/retrieval_metrics.py`
A process-local, thread-safe store with no query text and no identity:
- `record_decision(surface, mode, gate, abstained, reason, latency_ms)`
- `record_citations(surface, delivered, dropped_unresolved, withheld_unapproved)`
- `snapshot()`

The latency window holds the last 1000 decisions.

### 4.26 Other files
- **NEW `apps/api/tests/data/phase2_calibration_queries.json`** [R2]. The BEP-1 `fixture.json` items (query, expected, stratum, fold) plus hold-out B, with their source sha256s. Public questions only. The Phase 1 fixture `score_floor_queries.json` is unchanged.
- **`.dockerignore`**: append the block below. It is strictly more conservative and has no `!` lines [R16].
- **`corpus/public/manifest.json`**: regenerated on the workstation with LFS content.
- **`apps/api/tests/data/legacy_p1_baseline.json`**: new, recorded at step 1.
- **`infra/cloudrun/api-production.env.example.yaml`** (the tracked example only): document `RETRIEVAL_GATE: "p1-floor"`, `SEMANTIC_RETRIEVAL_ENABLED: "false"`, `SPAN_RESOLVER_ROUTE_ENABLED: "false"` and `MANIFEST_DRIFT_CHECK: "fast"`.

The `.dockerignore` block:
```
# Private plane (plan 11.5, task 2.8): never in any build context.
corpus/private/
lqs/private/
**/*.private.json
**/*.private.jsonl
docs/thesis/ethics/private/
# Secrets, local state and release bundles never enter a build context (task 2.8; R-33).
.env
.env.*
**/.env
**/.env.*
infra/cloudrun/*.env.yaml
dist/
qcai_dev.db
**/qcai_dev.db*
```

---

## 5. Request-path behaviour (after Phase 2)

| Path | Before | After (default outside development: `p1-floor`) | After (`bm25f-v1`: development, or after the D-05 switch) |
|---|---|---|---|
| `GET /search` | P1 floor 6 over legacy chunks (with video chapters and colliding ids) | The same P1 floor and scores over the span index; chapters excluded; `chunk_id == span_id`. Governed D-31 output is identical to today apart from the ids | BM25F with coverage-v1, floor and margin from the package, `near_floor`, scores on the BM25 scale |
| `POST /qa/ask` | Quotes approved document citations | Quotes only citations the span registry verifies, with the span's own text; write-through; `provisional` true unless the lift flag is on | Same |
| `POST /assistant/chat` | Same as Q&A | Same; claims cite v2 span ids | Same |
| `GET /qa/history` | Pre-containment rows withheld | Unchanged for withheld rows. Other rows are dual-read and labelled; in governed builds, citations of unapproved items are withheld | Same |
| `GET /spans/{id}` | n/a | 404 (disabled) | Development: enabled (2.6) |
| `GET /source-assets/*` | Approved only (governed) | Approved, bound and public-plane only; plane guard on every path | Same |
| `GET /content/*` | Lessons with chapters | The 2026 video is never attached to `clinical-and-kernel-qcai-systems` (as video, chapters or `source_assets`) | Same |

**Exclusion rules**
- **Private-plane items** are never served, indexed, registered (CHECK constraint), resolved or upserted.
- **Unbound items** are never lesson-bound or indexed, and never served in governed builds.
- **Chapter summaries** are never evidence.
- **The authored item** is indexed when bound, and is never quotable or servable.

---

## 6. Start-up, readiness, logs and SLIs

### 6.1 Start-up order
1. `require_guest_token_secret`.
2. `_initialize_database()`. It fails closed before any table exists on any of these:
   - an invalid package;
   - an unverified package hash (governed builds);
   - a missing or invalid manifest;
   - drift in a governed build.
3. `_record_configuration_overrides()`.
4. `get_course_store()`. A governed build raises on duplicate span ids, document drift, or a mismatched authored version.
5. The startup log line with `_build_fields()`.

**No new start-up writes.** `corpus_spans` is written only by request-path write-through and by the explicit jobs. The new start-up statements are the idempotent DDL of `create_all` and the triggers.

### 6.2 `/ready` (200) body additions
```json
{"config_package_version": "1.0.0", "config_package_sha256": "…", "span_scheme": "span-v2",
 "index_version": "index-…", "retrieval_gate": "p1-floor", "duplicate_span_ids": 0, "manifest_drift": 0,
 "threshold_version": "score-floor-p1-v1", "abstention_floor": 6.0, "abstention_margin": 0.0,
 "thresholds_provisional": false, "threshold_authority": "P1-D-04",
 "bm25f_v1_calibrated": {"version": "abstention-p2-v1", "floor": 2.35, "margin": 2.40, "provisional": true, "provisional_until": "Phase 4"},
 "semantic_enabled": false, "semantic_setting": false,
 "slis": {"citation_resolution": {"delivered": 0, "resolved": 0, "dropped_unresolved": 0, "withheld_unapproved": 0, "rate": null},
          "abstention": {"decisions": 0, "abstained": 0, "rate": null, "by_reason": {}},
          "search_latency_ms": {"window": 0, "p50": null, "p95": null},
          "manifest_drift": {"mode": "fast", "checked": 0, "absent": 24, "drifted": 0}}}
```

### 6.3 Structured log events

| Event | Fields | Severity |
|---|---|---|
| `retrieval.decision` | `surface`, `mode`, `gate`, `abstained`, `reason`, `results`, `near_floor`, `top_score`, `latency_ms`, `index_version`, `threshold_version`. No query text. | INFO |
| `citations.delivered` | `surface`, `delivered`, `dropped_unresolved`, `withheld_unapproved` | INFO, or WARNING when `dropped_unresolved > 0` |
| `citations.unresolved_on_read` | — | WARNING |
| `corpus.drift` | — | WARNING (development), start-up error (governed) |
| `semantic.misaligned` | — | WARNING |
| `semantic.inactive` | — (start-up: the setting is on but this process has not aligned span-id vectors) | WARNING |
| `retrieval.recall_stop_overridden` | `items` | WARNING |
| Job lines | — | INFO, or ERROR on failure |

The SLIs follow plan Phase 2 I: citation resolution rate 100%; duplicate span ids 0; abstention rate; search p95; manifest drift 0.

---

## 7. Settings (new): defaults and freeze rationale

| Setting (env) | Default | Rationale |
|---|---|---|
| `CONFIG_PACKAGE_PATH` | Packaged `v1.json` | For tests. A non-default path outside development raises a `config.override` event [R19]. |
| `RETRIEVAL_GATE` | `None`: `bm25f-v1` in development, `p1-floor` elsewhere | Freeze (conflict 26). `p1-floor` is the approved containment. The switch is a D-05 remediation release (R-15) and logs a `config.override` event. |
| `SEMANTIC_RETRIEVAL_ENABLED` | `false` | Task 2.5. Off whatever keys are set. Effective only in a process that aligned span-id vectors; `/ready` `semantic_enabled` is the effective state and `semantic_setting` the setting. |
| `ALLOW_P1_FLOOR_WITH_DOCUMENTS` | `false` | Conflict 29 stop (plan Phase 2 L). Outside development, start-up and `validate_corpus.py --check-recall-stop` refuse document spans under `p1-floor` unless this owner override is set; it logs a `config.override` event. |
| `SPAN_RESOLVER_ROUTE_ENABLED` | `None`: true in development, false elsewhere | Freeze and D-31 (conflict 8). |
| `CITATION_PROVISIONAL_LIFT_ENABLED` | `false` | Freeze. Enabling it outside development logs a `config.override` event and needs AC-2-3 evidence plus D-05 approval (conflict 7, [R14]). |
| `SPAN_REGISTRY_WRITE_THROUGH` | `true` | Not learner-visible. A kill switch for a new request-path write. |
| `MANIFEST_DRIFT_CHECK` | `fast` | D11, conflict 12. |
| `SPANS_RATE_LIMIT` | `30/minute` | Like other public GETs. |

---

## 8. Tests

**General rules**
- Tests run in development with in-memory SQLite from conftest.
- Isolation uses `fresh_database_url` with `create_all` plus `run_schema_upgrades`, so the same tests run on PostgreSQL 16 in `api-postgres`.
- Rate-limited routes use a distinct `x-forwarded-for` or demo user for each call.
- Stores are module-scoped fixtures, but AC-2-1 always performs one genuinely fresh rebuild [R25].

**Configurations**

| Name | Settings |
|---|---|
| `dev` | `CourseStore(Settings())`, gate `bm25f-v1` |
| `governed_empty` | `Settings(environment="production", enforce_corpus_governance=True, corpus_manifest_path=<repo manifest>, retrieval_gate=<g>)` |
| `all_public_approved` | The same, with a temporary manifest from `with_all_public_approved` |

Tests state the gate `g` explicitly. Governed tests without an explicit gate exercise the shipped default, `p1-floor`.

### 8.1 NEW `apps/api/tests/test_phase2_acceptance.py`
**AC-2-1**
1. `test_ac_2_1_unique_span_ids_equal_total_chunks_and_are_identical_across_two_rebuilds`
   - Parametrised over `dev`, `governed_empty` and `all_public_approved`, and over both gates.
   - Unique ids equal the chunk count. Two independent builds give an equal ordered `[(span_id, lesson_slugs)]`. Duplicates = 0.
2. `test_ac_2_1_a_section_used_by_two_lessons_is_one_index_entry`.
3. `test_ac_2_1_the_rebuild_route_reports_no_duplicate_span_ids`.
4. `test_ac_2_1_manifest_span_digests_match_a_fresh_build`.

**AC-2-2**

5. `test_ac_2_2_a_manifest_licence_field_edit_changes_no_span_id` [R12]
   - Run on `governed_empty` **and** `all_public_approved`, so document spans are covered.
   - Edit `source`, `license` and `permitted_use` on every item.
   - Span ids, `corpus_version` and `index_version` are unchanged, and the manifest validates.
6. `test_ac_2_2_an_approval_edit_changes_membership_not_identity`.
7. **NEW** `test_ac_2_2_span_ids_do_not_depend_on_the_manifest_id_or_schema` [R9]
   - The same approved DOCX under a 1.0 manifest with id `routing-brief` and under 2.0 gives equal span ids.
   - A 2.0 item whose `id` differs from `source_asset_id` fails to load.

**AC-2-3**

8. `test_ac_2_3_every_returned_citation_resolves`
   - Use the first 30 in-domain queries, through `QAEngine.ask`, `TeachingAssistantService.chat`, `/qa/ask` and `/assistant/chat`.
   - Every citation is resolved, has schema 2, and passes `get_span_resolver().verify(c)`. At least one citation exists.
9. `test_ac_2_3_every_stored_citation_resolves` (rows and claims).
10. `test_ac_2_3_every_migrated_citation_resolves_and_the_rest_are_labelled_legacy_unresolved` (fresh database)
    - Seed v0 and v1 citations from `legacy_search` results: document, authored, video, blank, and one through the semantic path.
    - `--apply`. The migrated citations resolve; video citations are `chapter_summary_excluded`; the counts match the report.
11. `test_ac_2_3_a_legacy_unresolved_citation_is_never_returned_as_resolved`.
12. `test_ac_2_3_a_citation_that_does_not_resolve_is_never_quoted`
    - A forged id or a wrong hash abstains.
    - A tampered excerpt quotes the span's own text.
13. **NEW** `test_ac_2_3_governed_history_withholds_citations_of_unapproved_items` [R13].
    - In a governed build, register an unapproved document span through `persist_spans` and store a resolved v2 citation to it.
    - `/qa/history` returns no citation for it, and the metrics count it.

**AC-2-4**

14. `test_ac_2_4_the_out_of_scope_fixture_abstains_with_zero_results_above_the_floor`
    - Parametrised over both gates, on `governed_empty` and `all_public_approved`.
    - All 124 off-topic and stopword-only queries:
      - `store.evaluate(q, top_k=20)` has no results and has abstained;
      - `RetrievalEngine.search` returns `[]`;
      - `QAEngine.ask` decides abstain.
15. `test_ac_2_4_an_out_of_scope_route_sample_abstains`.

**AC-2-5** [R4, R20]

16. `test_ac_2_5_in_domain_recall_at_5_is_not_below_the_pre_migration_baseline`
    - For `bm25f-v1` on both configurations: new recall ≥ legacy recall (frozen module, same run) on the 174-query fixture and the 36 learner questions, using the union metric.
    - The assertion message also prints the slot-equal metric and any zero-slack constraint.
17. `test_ac_2_5_the_frozen_legacy_search_reproduces_the_pre_migration_snapshot`.
18. **NEW** `test_ac_2_5_the_p1_floor_gate_on_the_governed_index_equals_todays_search` [R1].
    - With `governed_empty` and `p1-floor`, per query in both fixtures, the `(lesson_slug, score, excerpt)` top-k equals `legacy_search` over `build_legacy_chunks(settings, [], [])`.
    - Recall is 131 and 36.

**AC-2-6**

19. `test_ac_2_6_every_manifest_hash_matches_disk`: a subprocess runs `--check-hashes --video-hash size` in the suite [R25]. The CI step runs the full check.
20. `test_ac_2_6_a_changed_byte_or_wrong_pointer_oid_fails_the_hash_check`.
21. `test_ac_2_6_an_lfs_pointer_oid_is_accepted_as_the_content_hash`.

**AC-2-7**

22. `test_ac_2_7_no_route_index_or_resolver_reaches_the_private_plane` [R10]
    - `GET /source-assets/..%2Fcorpus%2Fprivate%2FREADME.md` with asset-reader demo headers returns 404 [R24].
    - A temporary private item is not served, indexed or registered.
    - `assert_public_plane_path` raises for `corpus/private/x`, `lqs/private/x`, `*.pdf`, and for the absolute path `/app/corpus/private/x` with `root=/`.
23. `test_ac_2_7_the_boundary_scans_find_zero_private_plane_paths`
    - `scan_boundary.py --repo --docker-context apps/api/Dockerfile:. --docker-context apps/frontend/Dockerfile:apps/frontend`.
    - On a CI checkout: `path_scan_result == "pass"`, `not_run` plus its reason, and the frontend context uses `apps/frontend/.dockerignore`.
24. `test_ac_2_7_the_scanners_detect_a_planted_private_path_a_secret_like_name_and_a_planted_licensed_passage`
    - Uses a temporary tree, a zip and synthetic fingerprints from `fingerprint_shingles`.
    - Each planted item fails, and the report contains no passage text.

**AC-2-8**

25. `test_ac_2_8_a_near_duplicate_fixture_pair_fails_the_gate_and_the_configured_set_passes`.
26. `test_ac_2_8_the_2026_video_stays_unbound_even_when_approved` [R11]
    - In `all_public_approved` and `dev`, the clinical lesson has no video and no chapters, and **no lesson's `source_assets`** contains the 2026 file.
    - In governed builds, `is_public_asset` is false even with `public_service: true`.

**AC-2-9**

27. `test_ac_2_9_one_query_under_different_learner_contexts_returns_identical_spans_scores_and_abstention`
    - Run for both gates.
    - Contexts:
      - three demo learners with mastery 0.1, 0.5 and 0.9, plus notes, quiz attempts and Q&A history;
      - a guest;
      - different `page_path` and `history` values.
    - `/search` has no principal, so contexts vary only by headers and cookies there [R28].
    - The comparison uses `evaluation.qcai_eval.invariance.invariance_violations`, three replays per query [R26].
28. `test_ac_2_9_retrieval_abstention_and_resolver_take_no_learner_state_input`
    - Signature allowlist and an AST import check.
    - `retrieval_legacy_p1` is imported by no runtime module.
29. `test_ac_2_9_invariance_over_seeded_random_queries`.

**Plan G**

30. `test_plan_g_the_migration_is_reversible_byte_for_byte` (fresh database)
    - Apply, then downgrade: `CAST(… AS TEXT)` equals the original for every row.
    - A second apply is idempotent.
    - A seeded non-canonical row (written with `separators=(",", ":")` through raw SQL) is skipped, counted, and stops `--apply` [R6].
31. `test_plan_g_readers_dual_read_v0_v1_and_v2_citation_shapes`.
32. `test_plan_g_provisional_is_lifted_only_for_resolved_citations_and_only_when_enabled` [R14]
    - With the flag on: resolved citations are not provisional, unresolved ones are.
    - With the flag off: every citation is provisional.
    - `Settings(environment="production", citation_provisional_lift_enabled=True)` constructs without error, and start-up records `config.override` with `citation_provisional_lift_enabled`.

**Plan H**

33. `test_plan_h_the_semantic_backend_is_off_by_default_and_needs_span_ids` [R18]
    - With keys set and the flag off, semantic is not enabled.
    - With the flag on, `sync_semantic_index` performs the count check (stubbed) and sets `aligned`. Ids that are not span ids are dropped.
    - A count mismatch keeps the mode lexical.
34. `test_plan_h_every_hybrid_result_passes_the_active_gate`: both gates.
35. `test_plan_h_thresholds_are_provisional_until_phase_4`: the record sha matches, and the package loader never opens the record (monkeypatched `open` guard).

**Plan L**

36. `test_plan_l_the_migration_report_stops_on_an_unresolved_native_citation_or_an_exact_match_regression` [R5]
    - A native citation with an unknown id stops the run.
    - A hash-unique citation that another span contains is migrated: containment is reported, and there is no stop.

**Tasks and D9**

37. `test_task_2_7_chapter_summaries_are_never_evidence`.
38. `test_task_2_1_the_committed_manifest_is_generated_from_disk`: `generate_manifest.py --check --video-hash size`.
39. `test_d9_ready_reports_the_configuration_package_corpus_gate_and_slis`.
40. `test_d9_an_invalid_or_tampered_configuration_package_stops_governed_start_up_before_any_table_exists`.
41. `test_spans_route_resolves_metadata_and_never_an_excerpt_under_d31`: 404 responses carry `no-store` [R24].
42. **NEW** `test_the_shipped_gate_outside_development_is_p1_floor_and_bm25_is_an_override` [R1]
    - `Settings(environment="production").retrieval_gate == "p1-floor"`.
    - With `RETRIEVAL_GATE=bm25f-v1`, start-up records `config.override` with `retrieval_gate_bm25`.

### 8.2 NEW unit test files
- **`test_spans.py`**:
  - the offset property;
  - **the version check through `importlib.metadata`** (with a monkeypatched mismatch) [R7];
  - golden span ids;
  - the inputs that do not enter the id;
  - the legacy keys.
- **`test_lexical_index.py`**:
  - hand-computed BM25F scores;
  - the stopword hash and tokenizer cases;
  - coverage-v1;
  - reason precedence;
  - the tie-break;
  - the lesson filter;
  - `near_floor`;
  - **p1-floor** whole-word floor, substring overlap and boost selection [R1].
- **`test_manifest_v2.py`**: parse rules including the id rule, the version rules, `approved_items`, drift modes including `--video-hash size`, LFS pointers, and mvhd v0 and v1.
- **`test_config_package.py`**: structure, hash (governed and development), Q-10, `QUERY_STOPWORDS ⊂ stopwords-v1`, the p1 block, the parser pin, and CRLF in `.sha256` [R19].
- **`test_citation_migration.py`**:
  - unique, ambiguous and no-match cases;
  - diagnostics never changing the outcome [R5];
  - video and blank excerpts;
  - claims;
  - idempotence and monotonicity;
  - the canonical-JSON precondition [R6];
  - dry-run writes nothing;
  - the report schema;
  - the Wilson interval from `evaluation.qcai_eval`.
- **`test_near_duplicates.py`**.
- **`test_boundary_scan.py`**:
  - `.dockerignore` per context;
  - the refused `!`;
  - COPY parsing with `--from=` and globs [R16];
  - suffix matching [R10];
  - the `**/*.private.json` globs [R17];
  - zip namelists;
  - secret-like files never opened;
  - the `not_run` wording.
- **`test_corpus_spans_table.py`**: insert-if-missing; UPDATE, DELETE and TRUNCATE refused; the CHECK refuses private; `test_startup_schema_matches_orm_metadata` still passes on both dialects.
- **`test_review_problems.py`** (or added to `test_corpus_catalogue`) [R15]: a private or unbound item with `public_service: true` yields its problem from `--check-public-assets`.

### 8.3 Existing tests expected to change, with reasons
Each keeps its intent, and its commit message states the reason.

1. **`test_score_floor.py`** [R20]
   - The imports are unchanged: `content_assembler` re-exports the P1 names, which remain the shipped gate outside development.
   - `test_floor_is_the_approved_value` keeps `(6, "score-floor-p1-v1")`. It adds that the package's p1 block equals these values, and that the BM25 floor and margin equal the calibration record (record sha).
   - `test_floor_score_counts_whole_non_stopword_words_and_ignores_the_module_boost` is unchanged.
   - `test_floor_does_not_lower_in_domain_recall` (revised in the review fix round) keeps the Phase 1 assertion on the **live code**: each gate's floor against the same gate unfloored, every asset served as development serves them, `len == 174`.
     - `bm25f-v1`: the store's index rebuilt with floor 0 (142 against 142). `p1-floor`: `lexical_index.SCORE_FLOOR` patched to 0, the name the gate reads. Patching `content_assembler.SCORE_FLOOR` would reach nothing.
     - The P1 floor applied to the span index with documents does not keep this property (118 against 130), so that case is a strict xfail citing conflict 29, whose stop is enforced in code.
     - The earlier frozen-module version (`legacy_search` floor 6 against 0, 129 ≥ 124) is kept as a separate baseline-fidelity test, `test_the_approved_floor_did_not_lower_recall_on_the_pre_migration_search`; it is not the guard.
   - `test_one_shared_word_does_not_return_a_passage`, `test_off_topic_and_stopword_only_questions_return_no_result` and `test_capital_of_france_…` are unchanged. They run in development, so under `bm25f-v1`. **New sibling tests** run the same assertions on a `governed_empty` `p1-floor` store, so AC-1-11 stays evidenced for what ships.
2. **`test_api.py::test_search_uses_clean_video_source_titles`** becomes `test_search_returns_no_chapter_summaries_and_clean_source_titles` (task 2.7).
3. **`test_api.py::test_retrieval_engine_merges_semantic_and_lexical_results`**
   - `Settings(semantic_retrieval_enabled=True)`, a stub with `enabled = aligned = True`, and span-id results.
   - The mode is hybrid and `len == 3`. The stub returns a gate-passing span ranked outside the lexical candidates and a span below the gate: the first leads the fused list, the second is dropped, every result passes the gate and keeps the gate's score (revised in the review fix round; the first revision's `1 <= len <= 3` no longer required fusion).
4. **`test_api.py::test_contained_answer_abstains_without_an_approved_document_span`**: the positive case uses `native_citation(...)` of a real span. The forged citation now abstains even ungoverned (strictly stronger).
5. **`test_cs595_increment.py::test_persistent_tutor_stores_resolved_follow_up_and_claim_provenance`**: the stub returns a native citation from a real span (choose a query that returns a document span in development), and claims cite that span id.
6. **`test_api.py::test_qa_returns_citations`**: the comment is updated, and `resolution`, `item_id`, `start` and `end` are added (strengthened).
7. **AC-1-13 and AC-1-14 route tests**: unchanged; the flag is off.
8. **`test_corpus_catalogue.py`**: unchanged. 1.0 manifests are dual-read, and span item ids come from `source_asset_id` [R9].
9. **`docs/security/authorization-matrix.md`**: regenerated.

**Expected to pass unchanged:**
- `test_course_overview` (24 assets in development);
- `test_renamed_2026_source_asset_supports_head_requests`;
- `test_video_assets_use_updated_filenames`;
- `test_structured_logging::test_startup_logs_what_the_instance_started_with` (deterministic fields);
- the `/ready` checks in `test_deployment_pipeline`;
- `test_database_schema` (1.0 manifests; the new table through `create_all`);
- `test_deployment_artifacts` workers (semantic off);
- `test_release_packaging_still_refuses_unapproved_curated_assets` (24).

---

## 9. CI changes (`.github/workflows/ci.yml`)

**`api-and-evaluation`**: after the existing steps, add:
```yaml
      - run: python scripts/config_package.py --check
      - run: python scripts/generate_manifest.py --check
      - run: python scripts/validate_corpus.py --check-hashes --check-near-duplicates
      - run: python scripts/calibrate_abstention.py --check docs/evaluation/phase2/calibration_record_v1.json
      - run: python scripts/scan_boundary.py --repo --docker-context apps/api/Dockerfile:. --docker-context apps/frontend/Dockerfile:apps/frontend --report boundary-scan.json
      - run: cat boundary-scan.json
```
CI checks out without LFS, so `--check-hashes` and `--check` check the MP4 pointer oids at full cost, which is cheap.

**`api-postgres`**: unchanged. The new tests run there, covering the migration round trip, the triggers, the resolver and the canonical-JSON precondition.

**`release-artifacts`**: no new step [R23]. `tools/package_release.py` refuses while D-31 leaves every curated asset unapproved, so a scan placed after it could never run. Two actions instead:
- the deferred register records the step to add once packaging can run;
- the workstation evidence is a namelist scan of the existing `dist/release/qcai-studio-v1.0.0-part{1,2}-*.zip`, paths only.

**`frontend`**: unchanged.

---

## 10. Docs and evidence to write

1. **`docs/adr/ADR-002-retrieval-architecture.md`**: append `## Revision 2026-11-19 (Phase 2)`, keeping the existing text. Cover:
   - E-25, E-26 and E-41;
   - bm25f-v1 over span-v2 entries, coverage-v1, and the floor and margin (provisional);
   - **the two gates and the `p1-floor` default outside development, with the measured reasons (0.2b)**;
   - chapters excluded; semantic retrieval gated, with every result re-gated;
   - **D-17 option (a) "interim, migrate by Phase 11"**, provisional under P1-D-18 and pending ratification (the H5 ADR revision);
   - conflicts 4, 5, 6, 24, 26 and 29.
2. **`docs/adr/ADR-004-citation-traceability.md`**: append a revision covering:
   - span-v2 and the id rule [R9];
   - item-global offset rotation;
   - the D2 deviation;
   - the resolver and route gating;
   - citation v2 and dual-read;
   - the D3 migration rule with diagnostics [R5];
   - the canonical-JSON reversibility precondition [R6];
   - D-30 (provisional);
   - the AC-2-3 reading, including governed withholding [R13];
   - the provisional marker policy [R14];
   - `corpus_version` versus `index_version`.
3. **`docs/evaluation/phase2/calibration_record_v1.json`** (generated) and **`README.md`**: reproduction, the BEP-1 strata and folds, the selection rule, the reported regressions against P1, the answer-rate proxy, the limitations, and the statement that no threshold is final before E1.
4. **`docs/evaluation/phase2/citation_migration_report_format.md`** and a **synthetic** `citation_migration_report_sample.json`.
5. **`docs/evaluation/phase2/boundary_scan_2026-11-19.json`** [R22]: the CI-equivalent repository and Docker-context scan (paths only), plus the namelist scan of the local v1.0.0 zips.
6. **`infra/cloudrun/deployment.md`**: a new section, `## Phase 2: spans, manifest and citation migration (runbook)`. Every step is a cloud write that needs Platform Owner approval under D-05; none runs in Phase 2.
   1. Deploy. `RETRIEVAL_GATE` stays `p1-floor`.
   2. Run `register_spans` with `--dry-run`, then `--apply`.
   3. Run `migrate_citations --dry-run --report`, file the report and compare it with D-30.
   4. `--apply` after review; `--downgrade` is the rollback.
   5. Roll back by digest plus `--downgrade`. Span rows stay.
   6. Switching to `bm25f-v1` is its own remediation release (R-15) with the calibration record attached.
   7. **Stop conditions:**
      - approving any document while `p1-floor` is the default (conflict 29);
      - a governed start-up failure on the authored hash, which means the manifest was not regenerated [R27].
7. **`infra/cloudrun/observability.md`**: the 6.3 events and filters, marked "not set up yet".
8. **`docs/testing/test-strategy.md`**: a map from AC-2-1 to AC-2-9 onto the tests in 8.1.
9. **`docs/security/authorization-matrix.md`**: regenerated.
10. **BEP-2-12 [R22]**
    - `phase02/` closure-evidence notes:
      - R-14: tests 1-4 and the rebuild route;
      - R-15: tests 14, 16 and 18 plus the calibration record. The production re-probe is deferred until the D-05 switch;
      - R-17: tests 26 and 37. The audio-fingerprint closure (F-7) is deferred;
      - R-13: the resolver, tests 8-13 and 41. Closure is in Phase 4.
    - `00_meta/PROVISIONAL_DEFAULTS_REGISTER.md` rows for:
      - D-17 (a), D-30 and Q-10;
      - the floor and margin;
      - the near-duplicate thresholds;
      - `RETRIEVAL_GATE` defaults.
    - `00_meta/DEFERRED_ITEMS_REGISTER.md` rows from Section 12.
11. **PR body (later step)**: the provisional owner decisions, the conflicts, the gate default and the deferred items.

---

## 11. Order of work, commits and verification
Commit after each step, on the branch, with the trailer. Run the full suite at steps 4, 7 and 10.

1. **Frozen legacy and baseline.**
   - Add `retrieval_p1.py` (moved helpers with re-exports) and `retrieval_legacy_p1.py` (frozen).
   - Add a temporary fidelity test against the **unmodified** `CourseStore.search`, for both configurations, and run it.
   - Run `record_legacy_baseline.py --write`.
   - Commit.
2. **Configuration package and loader** (placeholder floor and margin), plus `scripts/config_package.py`.
3. **Manifest v2** (workstation with LFS content), the registry dual-read with the id rule, and `--check-hashes`.
4. **Spans, the index with both gates, CourseStore, the retrieval engine and schemas,** plus the `test_score_floor` changes (8.3.1).
5. **Persistence and the resolver:** routes, provenance, `contain_answer`, governed history withholding, and 8.3 items 4-6.
6. **Migration:** service, workers and tests, including byte reversibility on SQLite. The PostgreSQL run is in CI.
7. **Calibration:** add `phase2_calibration_queries.json`, then run `calibrate_abstention.py --write … --update-package`, then the AC-2-4 and AC-2-5 tests.
8. **Near-duplicate gate, boundary scan,** `.dockerignore`, data planes and the assets guard.
9. **`/ready`, metrics, logs, settings and override events.**
10. **Docs, ADRs, evidence files and CI.**

**Verification** (all must pass):
```
cd D:\QC_AI_Studio\Codex_Webapp_QC_AI_Studio
"<venv>\python.exe" -m pytest -q -m "not release_artifacts" apps/api/tests evaluation/tests -p no:cacheprovider
"<venv>\python.exe" scripts/validate_corpus.py --check-public-assets
"<venv>\python.exe" scripts/validate_corpus.py --check-hashes --check-near-duplicates
"<venv>\python.exe" scripts/generate_manifest.py --check
"<venv>\python.exe" scripts/config_package.py --check
"<venv>\python.exe" scripts/calibrate_abstention.py --check docs/evaluation/phase2/calibration_record_v1.json
"<venv>\python.exe" scripts/scan_boundary.py --repo --docker-context apps/api/Dockerfile:. --docker-context apps/frontend/Dockerfile:apps/frontend --report %TEMP%\boundary.json
"<venv>\python.exe" scripts/validate_lqs.py --allow-draft
"<venv>\python.exe" scripts/authorization_matrix.py --check
```
- `<venv>` is the scratch virtual environment the implementing session used.
- On the workstation, the full `--check-hashes` and `generate_manifest --check` hash 3.3 GB of hydrated MP4; this is expected outside the suite.
- The main baseline is 426 passed, 2 skipped, 1 xfailed. Expect that plus the new tests, with no new skips.
- CI evidence (AC-2-1 to AC-2-9 green "in a cited green CI run") needs a push, which this session must not do. It is recorded as pending.

---

## 12. Open and deferred items (for `BEP-2-12/00_meta/DEFERRED_ITEMS_REGISTER.md`)

**Owner decisions**
- D-17 (a), D-30 and the Q-10 path are provisional and need ratification. Q-10 is factual and stays unresolved: it needs an ASR or author note.
- **The D-05 remediation release switching production to `bm25f-v1` (R-15 closure).** The owner weighs the plan's answer-rate requirement (bm25 95.4% against P1 83.9%, proxy 100%) against the near_miss and oos_lexical regressions (0.2b). The production re-probe follows that release.

**Evidence public CI cannot produce**
- **AC-2-7 is partially met (path half only).** The licensed-passage scans need private-plane fingerprints (D-14), and the exit-gate run must also scan a built image (`--image-tar`) and a release (`--release-zip`) with `--require-ac-2-7`. D-14 is the precondition of this Phase 2 exit item.
- DOCX files in the repository may legitimately share 12-grams with the licensed volumes (F-10 overlap ≤ 1.0%). The owner must decide the per-file hit policy before the first run.
- The decoded-audio media fingerprint (E-70, ffmpeg) and the F-7 closure.
- A release-zip scan with evidence: the tag-only job now runs it after packaging, but packaging refuses unapproved assets [R23], so no bundle exists to scan.
- A cited green CI run for the Phase 2 exit, which needs a push.

**Production runs, each needing Platform Owner approval**
- The citation-migration dry-run report, which also answers Q-19 row counts.
- Registering document spans.

**Plan gaps carried into Phase 4**
- ULQS calibration and confirmation splits with a contamination check.
- The runner-up margin reading of 11.3, and stemming (conflicts 4 and 5): provisional deviations awaiting PI or Research Lead ratification.
- Re-deriving coverage-v1 and the framing stopwords on data not used for design.
- The zero-slack learner-question constraint (all-approved configuration).

**Conditions enforced in code**
- Approving any document while `p1-floor` is the gate outside development stops start-up and `validate_corpus.py --check-recall-stop` (conflict 29) until the D-05 switch decision or a recalibration; `ALLOW_P1_FLOOR_WITH_DOCUMENTS` is the logged owner override.

**Out of Phase 2 scope**
- Exact heading match per lesson (11.4) and the conflict metadata fields.
- R-18 (DOCX metric fidelity).
- The legacy splitter version 1.1.1 against 1.1.2: the dry-run report shows its effect [R8].

**Follow-ups**
- Frontend rendering of `resolution`, `label` and `near_floor`. The history panel does not render citations today.
- Removing the v1 dual-read after two releases, and manifest 1.0 after one.
- `scripts/make_passage_fingerprints.py`, if it was deferred under [R26].

---

## 13. Implementation record: refinements and deviations (2026-11-19)

The committed code and data are authoritative. Each item below is a refinement where the code forced a choice, with its reason.

1. **Measured values (record v1, `corpus-f1fc2c12e7d9d01a`).**
   - Floor 2.35, margin 2.40.
   - Cal windows: governed 0.00-4.75; all-approved 0.00-6.00 (the spec's prototype measured 6.70; the tie-break by span_id and the 2026-video exclusion move the upper end).
   - Confirmation: conf 61/52 and 58/54; hold-out B 22/16 and 21/19; AC fixture recall 151/131 and 142/129; 0 out-of-scope results.
   - `p1-floor` on the all-approved span index: recall 118 (the spec measured 119).
   - Answer rate 166/174 against 146/174.
2. **Legacy baseline for the all-approved configuration.** It serves all 24 assets, the 2026 video included, as the pre-migration code did (it had no Q-10 binding). The snapshot was recorded that way, and the calibration script uses the same rule.
3. **`IndexEntry` lives in `lexical_index.py`** and is re-exported through `content_assembler`'s imports, to avoid an import cycle. `ScoredEntry` gained an optional `lesson_slug` (the p1-floor boost lesson).
4. **`RetrievalEngine.search` gained a keyword-only `surface` argument** (default `"search"`) for the decision log and SLIs. It is not learner input, and the AC-2-9 signature allowlist includes it.
5. **`/ready` reported the package's bm25f-v1 thresholds** whatever the gate. Superseded by item 20: it now reports the thresholds in force (the active gate's) and the calibrated bm25f-v1 values under `bm25f_v1_calibrated` (6.2).
6. **`citations.delivered` is logged by `retrieval_metrics.record_citations`**, which also feeds the `/ready` SLIs: once per Q&A, assistant and tutor response, and once per `/qa/history` read that withheld a citation.
7. **`persist_spans` counts inserted rows with `RETURNING`**, because psycopg reports rowcount -1 for the multi-row `ON CONFLICT DO NOTHING` insert.
8. **Matched spans are registered in the same transaction as the migrated rows** (per 500-row batch), so a crash cannot leave migrated citations whose spans are unregistered.
9. **The API image cannot import `evaluation/`**, so the migration report uses its own Wilson interval. A unit test checks that it agrees with `evaluation.qcai_eval.statistics.wilson_interval`. The calibration script, which runs from the repository, uses the harness function.
10. **`approved_items` also excludes items on the package's Q-10 list,** so a 1.0 manifest approving the 2026 video cannot serve it in a governed build.
11. **`apps/frontend/.dockerignore` gained `.env` and `.env.*`.** The frontend build context otherwise holds `apps/frontend/.env.example`, a secret-like name that fails an image-context scan. This is strictly more conservative, and the build reads ARG/ENV only.
12. **`--check-hashes` recomputes spans only for documents whose content hash matches,** reporting a parse failure as a problem rather than crashing on a damaged file.
13. **`test_corpus_spans_table.py` asserts the TRUNCATE guard on PostgreSQL, and the trigger set on SQLite,** instead of skipping on SQLite (no new skips).
14. **`.gitattributes` pins LF** for `corpus/public/manifest.json` and this file.
15. **The local v1.0.0 release zip (part 1) fails the boundary scan by name:** five secret-like names, not opened. It is recorded in `docs/evaluation/phase2/boundary_scan_2026-11-19.json` and is the existing Action 10/29 item. The CI-equivalent scans pass.
16. **`scripts/make_passage_fingerprints.py` was deferred** (D-14), as the spec allowed [R26].

**Review fix round (2026-11-19).** Each item answers a confirmed review finding.

17. **corpus_version follows plan 11.1** (conflict 1 revised, 3.4): built items only, scheme `corpus-version-v3`. The committed manifest records `corpus-a02930b08f2e9251` (the authored item; D-31 approves nothing). The calibration record v1 was regenerated with the same selection, sweeps and confirmation; only its corpus and index versions changed, and each configuration now records its own `corpus_version`.
18. **The conflict 29 stop is enforced in code** (start-up, `validate_corpus.py --check-recall-stop`, override `ALLOW_P1_FLOOR_WITH_DOCUMENTS`). The AC-2-5 test runs both gates in both configurations; the Phase 1 recall guard (`test_floor_does_not_lower_in_domain_recall`) runs on the live code for both gates again, with `p1-floor` as a strict xfail. The frozen-module check is kept as a separate baseline-fidelity test.
19. **D-30 limits come from the package** (conflict 14 revised): the legacy threshold is enforced when it is a number (`legacy_share_statistic` `point`), and the loader refuses anything but null or a number in [0, 1]. The exact-match regression stop can now fire (current-build-unique key that ends unresolved; already migrated citations are re-verified).
20. **`/ready` reports the thresholds in force** (the active gate's `threshold_version`, floor, margin, provisional flag and authority) and the calibrated bm25f-v1 values under `bm25f_v1_calibrated`; `semantic_enabled` is the effective state and `semantic_setting` the setting.
21. **The resolver refuses an item the current manifest puts on the private plane**, including a span registered while it was public. The AC-2-7 tests now drive the `/source-assets` guard and the resolver and span route with a real document span.
22. **Boundary scans:** `--image-tar` (a built image), `--require-passage-scan`, `--require-ac-2-7` and the report's `ac_2_7` block (conflict 16 revised). The packager excludes private-plane, licensed and secret-like paths and scans its bundles; the release job runs `--release-zip`.
