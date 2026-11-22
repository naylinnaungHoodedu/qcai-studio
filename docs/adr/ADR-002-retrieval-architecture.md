# ADR-002: Retrieval architecture

## Context

RevB §§5.1 and 6.2 require retrieval, citations, and graceful semantic-to-lexical degradation.

## Decision

Retain lexical retrieval as the canonical baseline and wrap optional semantic/Pinecone retrieval behind `RetrievalEngine`. Every result has a stable `chunk_id`; the persistent Tutor records retrieval mode and corpus manifest version. The evaluation harness models the four required arms explicitly.

## Consequences

Provider failure cannot remove the evidence path. Semantic retrieval is an optimization, not the sole source of truth, and arm B remains measurable rather than a claim in documentation.

## Revision 2026-11-19 (Phase 2: corpus, span identity and retrieval integrity)

Status: accepted for Phase 2 engineering; the thresholds are **provisional** (until Phase 4 in configuration packages v1 and v2; package v3, the shipped one, keeps them provisional until Q-22 sets them, `abstention.provisional_until` `Q-22 (DI-52)`) and "no threshold is final before the E1 freeze" (plan Phase 2 H). Implements plan tasks 2.1 and 2.5-2.7. The full design is `docs/architecture/phase2-implementation-spec.md`; the original decision above stays as history.

### Context
- **E-25:** 459 chunks shared 215 chunk ids, and those ids keyed fusion and vectors.
- **E-26:** substring scoring with an 11-point module boost had no threshold. Phase 1 contained this with the approved P1 floor (P1-D-04, `score-floor-p1-v1`, floor 6).
- **E-41:** semantic retrieval was keyed by colliding chunk ids. The P1 floor did not apply to hybrid results (the latent hybrid bypass found on 2026-11-17).

### Decision
1. **One index entry per span.** The evidence index holds one entry for each span record (span-v2, ADR-004) that is bound to at least one lesson. A section used by two lessons is one entry listing both lessons, so unique ids equal total entries (AC-2-1).
2. **Chapter summaries are not evidence.** Curated video chapter summaries are never index entries, search results or citations (task 2.7). They stay lesson presentation, labelled `curated_chapter_summary`.
3. **Two gates over the same entries.** Both use the same learner-free signatures (invariant 1).
   - **`bm25f-v1`** is BM25F-simple (`k1` 1.5, `b` 0.75, title weight 2.0, from configuration package v1).
     - It drops stopwords (`stopwords-v1`, 210 words, hashed in the package) and does no stemming (conflict 5).
     - It has no module or lesson boost. Ties break on `span_id`.
     - It applies the `coverage-v1` sufficiency rule, then the provisional abstention floor 2.35 with margin 2.40 (`abstention-p2-v1`).
     - A result within the margin above the floor is marked `near_floor`, the later X4 trigger. There is no runner-up test (conflict 4; Phase 4 did not add one, DI-67).
   - **`p1-floor`** is the approved P1 floor applied to the span index. In the governed D-31 configuration it returns exactly the pre-migration results (`test_ac_2_5_the_p1_floor_gate_on_the_governed_index_equals_todays_search`).
4. **Default gate.**
   - `RETRIEVAL_GATE` defaults to `bm25f-v1` in development and `p1-floor` everywhere else (conflict 26). The reason is measured: `bm25f-v1` is not strictly more conservative.
     - All-approved configuration: it answers 166/174 in-domain questions against 146/174 for P1.
     - It returns results for 10/15 `near_miss` questions against 7/15 for P1, and for 3/16 `oos_lexical` against 2/16 (calibration record v1, `reported_strata_vs_p1`).
   - The D-05 freeze allows only conservative learner-visible defaults. Switching production to `bm25f-v1` is therefore a separate D-05 remediation release that closes R-15 (Section 5.3). It logs a `config.override` event.
5. **Semantic retrieval stays off.** It is disabled unless `SEMANTIC_RETRIEVAL_ENABLED` is set, whatever keys are present. Since Phase 5 it embeds only through the model gateway (`app/gateway/embeddings.py`, which alone reads `OPENAI_API_KEY`), and the gateway gives it no embedder: it names the first check that fails (the environment's opt-in, D-23: `openai-embeddings` in `MODEL_EGRESS_PROVIDERS`, PD-22; D-07, D-12, Q-09 and the Q-15 payload review; a pinned model in package v4's `gateway.embeddings`; a budget; an open gateway; the key), and once every one passes, plan H's bar remains: a query embedding would send the learner's query text, and only public-corpus spans leave the platform (Phase 5 spec 4.19). Without one the setting leaves retrieval lexical, and the reason is logged (`gateway.egress_refused` for the missing opt-in; `semantic.inactive` with its `reason` at start-up).
   - It is used only when aligned: vector ids are span ids (metadata `span_scheme: span-v2`) and the namespace count equals the entry count.
   - Every semantic result is re-gated with the active gate before fusion, so fusion cannot bypass the floor (task 2.5; plan 11.3, "hybrid fusion needs its own floor").
6. **Calibration** follows task 2.6 and `docs/evaluation/phase2/README.md`.
   - It uses public-corpus items only, never the private plane or ULQS.
   - It uses the pre-registered BEP-1 strata, the cal fold for selection, and the conf fold plus hold-out B for confirmation.
   - It covers two configurations: the governed build as configured, and every public-plane item approved.
   - AC-2-5's baseline is the frozen pre-migration search, run in the same run (conflict 15).

### Provisional deviations from plan 11.3 (need Principal Investigator or Research Lead ratification)
These are engineering defaults applied under P1-D-18; they depart from the plan's text, so an engineering decision alone does not settle them. They are recorded in configuration package v1 (`owner_decisions.PLAN-11.3`, `ratified: false`).
- **No stemming.** Plan 11.3 asks for "a stemmed, stopword-filtered BM25-style index". Package v1 sets `stemmer: "none"`: an S-stemmer raised out-of-scope leakage (all-approved maximum 8.2) (spec conflict 5).
- **The margin labels; it does not test a runner-up.** Plan 11.3 asks for "a sufficiency gate (floor plus runner-up margin) before any generator call". The margin marks `near_floor` results (floor ≤ score < floor + margin, D6 and plan V1.5) and drops none; there is no runner-up comparison (spec conflict 4; DI-28, carried as DI-67).

### D-17: the long-term public corpus model (hold H5, "ADR revision")
- **Provisional choice:** option (a), "interim, migrate by Phase 11", the plan's 18.3 recommendation. It was applied under P1-D-18 (owner delegation, 2026-11-19) and is **provisional, pending ratification**.
- **Interim model:** a manifest-governed public plane (`corpus/public/manifest.json`, schema 2.0, generated from disk). Assets stay in the repository and Git LFS until the Phase 11 media move.
- **Where it is recorded:** configuration package v1, `owner_decisions.D-17`.

### Consequences
- Search scores change scale under `bm25f-v1` (development only by default). Under `p1-floor` they are unchanged.
- `chunk_id` becomes the span id, a new string format with the same field.
- **Conflict 29:** approving any document while `p1-floor` is the default loses recall, because chapter summaries are excluded (all-approved recall 118 against 129 before migration; all assets 118 against 130 unfloored). That approval is a stop condition (plan Phase 2 L), **enforced in code**: outside development, start-up and `validate_corpus.py --check-recall-stop` refuse document spans under `p1-floor` unless the owner override `ALLOW_P1_FLOOR_WITH_DOCUMENTS` is set, which logs a `config.override` event. It needs the D-05 gate switch, or recalibration.
- **Residual risks:**
  - The learner-question constraint has zero slack in both configurations.
  - `coverage-v1` and the framing stopwords were designed with the whole repository fixture in view.
  - Both items are recorded in the calibration record's `fragility` and `limitations` lists for Phase 4.
