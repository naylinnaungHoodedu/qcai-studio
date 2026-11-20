# Phase 3 three-plan replay (plan Phase 3 F; AC-3-2; plan L)

`three_plan_replay_v1.json` is the committed report of `scripts/replay_tutor_plans.py`. It runs the two-pass tutor over public-corpus fixtures under the three presentation plans and checks that the lock precedes rendering: per item, the `claim_set_hash` and the span set must be equal across the plans.

**Evidence class.** This is an engineering replay on public-corpus fixtures. **It is NOT E3 or LQ-1 evidence** (plan Phase 3 H). It reads:
- no item under `lqs/` (refused);
- no private-plane item;
- no learner record, tutor turn or rating.

It writes nothing to a database. The report holds hashes and counts only, never query, claim or span text.

## Reproduce

```
python scripts/replay_tutor_plans.py --write docs/evaluation/phase3/three_plan_replay_v1.json
python scripts/replay_tutor_plans.py --check docs/evaluation/phase3/three_plan_replay_v1.json   # CI
```

Exit codes:
- `0`: pass;
- `1`: a mismatch across plans (`--check` also exits 1 when the record differs from a fresh run, `created_at` and `commit` aside);
- `3`: the plan L stop;
- `4`: `--write` refused because the working tree differs from HEAD (unless `--allow-dirty` is given).

**Provenance.** The record names the code it replayed by content, not by history: `inputs` lists every repository module the replay imported (under `apps/api/app/` and `scripts/`), each with the sha256 of its text (CRLF read as LF), and the digest of that map (rule `imported-repository-modules-sha256-lf-v1`). The test of the committed record recomputes every listed hash from the checkout, and `--check` (CI) compares the whole block with a fresh run, so a stale record fails in every clone: on the branch, after a squash merge, and in CI's shallow checkout. A change to any replayed module or to the configuration package (its sha256 is in the report) therefore needs a fresh `--write`, committed with the code. `commit` is informational: the HEAD the record was written on, with `-dirty` when it was written from a working tree. Two tests keep the record independent of git history: one runs the committed-record check inside a real repository squash-merged the way the project merges, and the other fails if any file that runs or checks the record (the script, its tests, CI) asks git about history.

## Inputs and configurations

- **Fixture:** `apps/api/tests/data/score_floor_queries.json`: 174 in-domain, 100 off-topic and 24 stopword-only items (298). Its canonical sha256 is in the report.
- **Regression items:** `apps/api/tests/data/phase3_replay_regressions.json`, public-corpus queries that each name the defect they guard, replayed in full beside any subset (1 item, so 299 in all): a sentence that two overlapping document spans both hold, locked once as one claim citing both spans (`two_pass.merged_claims`).
- **Plans:** `concise`, `stepwise` (ordered by each claim's own place in the source: its item, then the item offset of its sentence, so two sentences of one span keep their order) and `socratic` (fixed opening and closing questions), from `template-renderer-v1`.
- **Configurations:**
  - `governed_empty` / `p1-floor`: the shipped D-31 build, where nothing is approved, so it abstains on all 299 items (the 298 fixture items and the regression item);
  - `all_public_approved` / `bm25f-v1`: a temporary manifest approving every public-plane, bound item;
  - `all_public_approved` / `p1-floor`: the same manifest under the Phase 1 floor.
- **Pipeline:** `thread-resolver-v1` on single turns; lexical retrieval, `top_k` 4; generator `extractive-d19-v1` (D-19, PD-08) over whole `sentences-v2` sentences of each span's section text; binding `resolver-bundle-sentence-v2`, which refuses a span-edge fragment of a longer document sentence (`partial_sentence`); subset check `segment-exact-whitespace-v3`, which also fails a rendering with no claim, an uncited claim, or a citation list that is not exactly the displayed spans; regeneration limit 2.

## Results (committed record)

| Configuration | Answered | Abstained | Mismatches | Two-pass bound-claim ratio | Phase 2 legacy ratio |
|---|---|---|---|---|---|
| governed_empty / p1-floor | 0 | 299 | 0 | null (no claims proposed) | null |
| all_public_approved / bm25f-v1 | 148 (147 in-domain, 1 regression) | 151 | 0 | 1.0 | 1.0 (167 answered) |
| all_public_approved / p1-floor | 130 (129 in-domain, 1 regression) | 169 | 0 | 1.0 | 1.0 (147 answered) |

- No off-topic or stopword-only item is answered (`answered_by_stratum`).
- The two-pass path answers fewer items than the legacy contained path over the same retrieval (148 against 167, and 130 against 147). Binding accepts only whole document sentences, and the envelope carries only those, so an item whose spans hold no whole sentence sharing a content term with the question abstains: `no_whole_sentence` (11 under `bm25f-v1`, 13 under `p1-floor`) when its quotable spans hold no whole document sentence at all, and `no_claims` (8 and 4) when their whole sentences share no content term with it. Most such spans fall inside long `sentences-v2` sentences: the rule never ends a sentence at a period followed directly by a footnote number ("optimization.15 If"). `governed_empty` records `no_quotable_evidence` (149 items: no span is approved) or a retrieval reason.
- The two-pass counts are the ratio terms (`contracts.bound_claim_ratio_terms`): a claim merged onto an earlier claim's sentence counts as bound, and so does a duplicate (its sentence already bound on every span it cites), so the ratio of one locked claim set does not depend on claim order; a claim bind never saw (a shadow budget overrun) counts in neither term. The extractive generator proposes no duplicate.
- The answered items' three renderings are pairwise distinct (`rendered_text_distinct_among_answers`): the plans differ in presentation only.

## The bound-claim stop (plan Phase 3 L)

"Stop if bound-claim ratio falls below Phase 2."
- Phase 2 defined no such SLI. The baseline was measured at 1.0 (every contained claim cites exactly one resolved span) and is pinned in the configuration package at `tutor_pipeline.stop.phase2_bound_claim_ratio`.
- A non-null two-pass ratio below it makes the report's `result` "stop" and the script exit 3.
- A null ratio (nothing proposed) is never a stop.
- In operation the same ratio is the log-based SLI over each shadow run's `tutor.two_pass.shadow` line (`ratio_bound` over `ratio_proposed`, `infra/cloudrun/observability.md`), and in process it is `TwoPassMetrics.snapshot`. It is not on public `/ready`, whose `slis.two_pass_shadow` carries only `scheduled` and the baseline, because a learner could otherwise read their own shadow run's outcome (AC-3-6).

## Limitations

- The renderer is deterministic (fixed templates), so regeneration matters only for test renderers and the Phase 5 model renderer.
- There is no entailment checker before Phase 4. Binding requires a whole verbatim sentence of every cited span (a sentence of the document's section text lying wholly inside the span), so the replay measures structure, not meaning.
- Retrieval is lexical only (spec conflict 33).
- Single-turn items only: follow-up resolution is tested in `test_phase3_acceptance.py` (AC-3-5), not replayed here.
