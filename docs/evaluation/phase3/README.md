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
- `4`: `--write` refused because the working tree differs from HEAD.

**Provenance** (Phase 3 spec 18.8 F2). The record names the code it replayed by content, not by history: `inputs` lists every repository module the replay imported (under `apps/api/app/` and `scripts/`), each with the sha256 of its text (CRLF read as LF), and the digest of that map (rule `imported-repository-modules-sha256-lf-v1`). The test of the committed record recomputes every listed hash from the checkout, and `--check` (CI) compares the whole block with a fresh run, so a stale record fails in every clone: on this branch, after a squash merge, in CI's shallow checkout. The record and its code are therefore committed together. `commit` is informational: the HEAD the record was written on, + `-dirty` when it was written from a working tree (`--write` still refuses a dirty tree unless `--allow-dirty` is given).

Until 18.8 the record had to name a clean commit that was an ancestor of HEAD (18.7 E3). The project squash-merges its pull requests, so after the merge that commit is in no history of main, and the check failed in every clone that kept the branch's objects while CI's shallow clone skipped it.

Two tests keep that from coming back (18.9 G1). One builds a real git repository merged the way the project merges (a branch commit named by the record, `git merge --squash` onto main, the branch's objects kept) and runs the committed-record check inside it. The other fails if any file that runs or checks the record (the script, its tests, CI) asks git about history.

Any change to the configuration package (its sha256 is in the report) needs a fresh `--write`.

## Inputs and configurations

- **Fixture:** `apps/api/tests/data/score_floor_queries.json`: 174 in-domain, 100 off-topic and 24 stopword-only items (298). Its canonical sha256 is in the report.
- **Regression items:** `apps/api/tests/data/phase3_replay_regressions.json`, public-corpus queries that each name the defect they guard, replayed in full beside any subset (1 item, so 299 in all):
  - a sentence that two overlapping document spans both hold. Before the 2026-11-19 review fix the shadow abstained on it with `subset_check_failed`; now it is one locked claim citing both spans (`two_pass.merged_claims`).
- **Plans:** `concise`, `stepwise` (reordered by each claim's own place in the source: its item, then the item offset of its sentence, so two sentences of one span keep their order; spec 18.10 H2) and `socratic` (fixed opening and closing questions), from `template-renderer-v1`.
- **Configurations:**
  - `governed_empty` / `p1-floor`: the shipped D-31 build, where nothing is approved, so it abstains on all 299 items (the 298 fixture items and the regression item);
  - `all_public_approved` / `bm25f-v1`: a temporary manifest approving every public-plane, bound item;
  - `all_public_approved` / `p1-floor`: the same manifest under the Phase 1 floor.
- **Pipeline:** `thread-resolver-v1` on single turns; lexical retrieval, `top_k` 4; generator `extractive-d19-v1` (D-19, PD-08) over whole `sentences-v2` sentences of each span's section text; binding `resolver-bundle-sentence-v2` (spec 18.10 H1; `-v1` before, which cut the span's own text and so accepted span-edge fragments); subset check `segment-exact-whitespace-v3` (renamed in Phase 3 spec 18.6 D4, when it began to fail a rendering with no claim or an uncited claim, and again in 18.7 E1, when it began to fail a citation list that is not exactly the displayed spans); regeneration limit 2.

## Results (committed record)

| Configuration | Answered | Abstained | Mismatches | Two-pass bound-claim ratio | Phase 2 legacy ratio |
|---|---|---|---|---|---|
| governed_empty / p1-floor | 0 | 299 | 0 | null (no claims proposed) | null |
| all_public_approved / bm25f-v1 | 148 (147 in-domain, 1 regression) | 151 | 0 | 1.0 | 1.0 (167 answered) |
| all_public_approved / p1-floor | 130 (129 in-domain, 1 regression) | 169 | 0 | 1.0 | 1.0 (147 answered) |

- No off-topic or stopword-only item is answered (`answered_by_stratum`).
- Until the seventh review round the answer counts equalled the legacy contained path's over the same retrieval (spec M1, M2). They no longer do (spec 18.10 H1). Binding now refuses a span-edge fragment of a longer document sentence, and the envelope carries only whole document sentences. So an item whose spans hold no whole sentence sharing a content term with the question abstains: `no_whole_sentence` (11 under `bm25f-v1`, 13 under `p1-floor`) when its quotable spans hold no whole document sentence at all, and `no_claims` (8 and 4) when their whole sentences share no content term with it. (Corrected in Phase 3 spec 18.11 I1: the 11 and 13 were recorded as `no_quotable_evidence` until the new reason split them from the D-31 case, where no span is approved; `governed_empty` still records `no_quotable_evidence` 149 times.) Before the fix, 42 of the 263 locked claims of that configuration were such fragments. The legacy path still answers 167 and 147 items. Most such spans fall inside long `sentences-v2` sentences: the rule never ends a sentence at a period followed directly by a footnote number ("optimization.15 If").
- The 298 original items replayed exactly as before the first 2026-11-19 review fixes (equal `items_digest`). The second review round (Phase 3 spec 18.5) changed the configuration package (budgets, idempotency, `PLAN-12.8`) and the sentence rule (`sentences-v2`, C10), so the package sha256, the claim hashes and every `items_digest` changed; the answer counts, the 0 mismatches and the bound-claim ratio of 1.0 did not. The third and fourth rounds (18.6, 18.7) changed the package again (the subset rule id, the idempotency lease) with the same answer counts, mismatches and ratio.
- **Which code.** The third round's record named `028cd40…-dirty`, a commit that did not hold the code it replayed (18.7 E3). The fourth round named the clean `65f56d1`, which did, but required it to be an ancestor of HEAD, which a squash merge breaks (18.8 F2). Since the fifth round the record names its code by `inputs`, checked against every checkout; its `commit` is where it was written.
- The fifth round (18.8) changed the package again (the question-overlap threshold, F5; the D-12 wording, F6), so the package sha256 and the evidential prompt hash changed; the answer counts, the 0 mismatches and the ratio did not.
- The eighth round (18.11) split the empty-envelope abstention in two (I1): `no_quotable_evidence` when no bundle span is quotable, `no_whole_sentence` when the quotable spans hold no whole document sentence. The package did not change. Only the reason labels of 11 and 13 items, `inputs` (four modules), `created_at` and `commit` changed; the answer counts, the 0 mismatches, the ratio, the claim hashes and every `items_digest` did not.
- The seventh round (18.10) changed the binding rule (`resolver-bundle-sentence-v2`), the evidential prompt (whole sentences), the claims' source order and the package (the rule id, the evidential prompt hash, the PLAN-3.3 text), so the package sha256, the claim hashes and every `items_digest` changed. The 0 mismatches and the ratio of 1.0 did not.
- The two-pass counts are the ratio terms (`contracts.bound_claim_ratio_terms`): a claim merged onto an earlier claim's sentence counts as bound, and so does a duplicate (its sentence already bound on every span it cites; spec 18.12 J1, until then a binding failure, so the ratio of one locked claim set could read 1.0 or 0.5 by claim order); a claim bind never saw (a shadow budget overrun) counts in neither term. The extractive generator proposes no duplicate, so no replay count changed.
- The answered items' three renderings are pairwise distinct (`rendered_text_distinct_among_answers`): the plans differ in presentation only.

## The bound-claim stop (plan Phase 3 L)

"Stop if bound-claim ratio falls below Phase 2."
- Phase 2 defined no such SLI. The baseline was measured at 1.0 (every contained claim cites exactly one resolved span) and is pinned in the configuration package at `tutor_pipeline.stop.phase2_bound_claim_ratio`.
- A non-null two-pass ratio below it makes the report's `result` "stop" and the script exit 3.
- A null ratio (nothing proposed) is never a stop.
- In operation the same ratio is the log-based SLI over each shadow run's `tutor.two_pass.shadow` line (`ratio_bound` over `ratio_proposed`, `infra/cloudrun/observability.md`), and in process it is `TwoPassMetrics.snapshot`. It is not on public `/ready`: since the third and fourth review rounds `slis.two_pass_shadow` carries only `scheduled` and the baseline, because a learner could otherwise read their own shadow run's outcome (AC-3-6; spec 18.6 D9, 18.7 E15).

## Limitations

- The renderer is deterministic (fixed templates), so regeneration matters only for test renderers and the Phase 5 model renderer.
- There is no entailment checker before Phase 4. Binding requires a whole verbatim sentence of every cited span (a sentence of the document's section text lying wholly inside the span), so the replay measures structure, not meaning.
- Retrieval is lexical only (spec conflict 33).
- Single-turn items only: follow-up resolution is tested in `test_phase3_acceptance.py` (AC-3-5), not replayed here.
