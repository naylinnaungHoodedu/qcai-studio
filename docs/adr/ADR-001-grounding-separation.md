# ADR-001: Grounding separation

## Context

RevB §6.1 requires learner progress to affect presentation but never to function as factual evidence or silently alter retrieval/abstention behavior.

## Decision

The Tutor orchestrator has two typed channels. `build_pedagogical_context` supplies style guidance after retrieval; the resolved factual query is the only input to retrieval. The claim gate binds each factual answer sentence to retrieved span IDs. A failure produces an abstention, not an uncited personalized answer.

## Consequences

RQ2 can compare factual-claim/cited-span sets across low/medium/high mastery replays. Personalization is intentionally constrained to explanation style, pacing, and scaffolding.

## Revision 2026-11-19 (Phase 3: provenance-first two-channel tutor)

The decision above stands as first written. This revision states how plan Phase 3 (tasks 3.1-3.8) implements the separation, in `apps/api/app/services/tutor_pipeline/` (spec: `docs/architecture/phase3-implementation-spec.md`).

**Status.** Accepted for Phase 3 engineering. The evidential generator follows the D-19 RECOMMENDATION (no-provider extractive mode), applied provisionally (PD-08). D-12 (the provider) is open: no provider generator is wired and hold H6 stays unresolved (PD-09).

**Two channels.**
- *Evidential:* the resolver `thread-resolver-v1` builds the resolved question from the learner's own user turns of one thread only (task 3.1). The retrieval request holds exactly the resolved text, the lesson scope and the corpus version (task 3.2). Retrieval is the active Phase 2 lexical gate (never the semantic backend). The evidential envelope carries the quotable span texts in typed fields. The generator returns a claim plan (task 3.3); binding checks every cited span with the Phase 2 `SpanResolver`, requires the claim to be a whole sentence of every cited span (a sentence of the document's section text that lies wholly inside the span), and drops anything else (task 3.4). The envelope carries each span's whole sentences only, never a fragment cut at its edge. The locked claim set is frozen and hashed (task 3.5).
- *Pedagogical:* the renderer `template-renderer-v1` takes the locked set and a `PresentationPlan` (concise, stepwise or socratic). It may reorder claims and add fixed questions; it emits typed segments (task 3.6). The subset checker (`app/services/claim_gate.py`, rule `segment-exact-whitespace-v3`, which replaces the overlap gate) requires every factual segment to equal a locked claim, at least one claim to be shown, every shown claim to carry one of its own spans, and the rendering's citation list to be exactly the spans it displays; otherwise it re-renders, at most twice, then abstains (task 3.7). The ledger records the claims and spans the passing rendering displayed.

**Learner state is an input to neither channel.** The contracts refuse unknown fields (`extra="forbid"`), so no mastery, preference, id, history or page path can ride along (AC-3-1, R-41). The `PresentationPlan` comes from a request hint or the package default, never from learner state (the learner model is Phase 8). `build_pedagogical_context` still reaches no prompt. The invariant 1 test replays the same questions under three seeded learner contexts and finds identical retrieval requests and top-k, envelopes, ClaimPlans, evidence bundles (every span field, the sufficiency, the threshold version, floor and margin), locked claims and claim-set hashes, decisions, abstention reasons and counts: plan 7.8's "identical EvidenceBundle, ClaimPlan and abstain decision". It compares every field of the shadow record but its ids, and a learner-dependent value in any of them fails it.

**Lock before render.** The pedagogical prompt hash is the hash of the whole renderer registry, all plans included, so it is known at lock time. No lock stamp is plan-, learner-, request- or commit-specific, so the three plans give one `claim_set_hash` and one span set (AC-3-2, spec conflict 1). The three-plan replay (`scripts/replay_tutor_plans.py`, `docs/evaluation/phase3/`) is RQ2-style engineering evidence on public fixtures. It is not E3 or LQ-1 evidence.

**Verbatim claims.** The claim text that is stored, locked, ledgered and rendered is the span's own text with whitespace collapsed. NFKC is used only to compare. The binding rule `resolver-bundle-sentence-v2` refuses a truncated sentence that drops a qualification or a negation (spec conflict 32), whether a generator cut it or the span's edge did (`partial_sentence`). A span is a splitter chunk that can start or end inside a document sentence, so a whole sentence is one of the span's section text that lies wholly inside the span.
- Binding locks the matching sentence as the span holds it, never the generator's text.
- The subset check looks each rendered claim up by its `claim_id` and requires the locked text exactly (whitespace runs aside), so a rendering that folds "x²" to "x2" is an unmapped factual sentence.
- A sentence that two overlapping spans both hold is locked once, citing both spans.

**The claim unit, and task 3.3 "atomic claims".** Plan 3.3 reads: "Claim plan: atomic claims bound to span ids from a structured envelope; unbound dropped [Risk R-11]." Under D-19 extractive mode a claim is one verbatim whole sentence of every span it cites (`sentences-v2` over the document's section text, wholly inside the span, at most `max_sentence_chars`), not a decomposed atomic claim. A sub-sentence cut can drop a qualification or a negation, so binding refuses it (`not_verbatim`, or `partial_sentence` for a fragment cut at a span's edge). A compound sentence is therefore one claim, and in Phase 4 it gets one V1.3 verdict for what may be several facts. Decomposing it needs a generator that writes its own claims (Phase 5, D-12) and per-claim entailment (Phase 4 V1.3). This is an engineering reading of the plan text, not a plan default: configuration package v2 records it as `owner_decisions.PLAN-3.3` (`ratified: false`), spec conflict 34, and DI-47 for the Principal Investigator or the Research Lead to accept or change.

**Provenance.** The append-only, hash-chained `response_ledger` (task 3.8, R-22) records every tutor delivery (`delivery: legacy`) and every shadow run (`delivery: shadow`), with all plan 7.4 version fields. It replaces mutable `TutorTurn` provenance as the record. The `TutorTurn` columns stay for one dual-write release (DI-41).

**Delivery.** `two_pass_tutor` runs in shadow only until the Phase 4 exit, under three independent locks:
1. settings refuse `on` while the configuration package's `phase4_exit_passed` is false;
2. the code downgrades `on` to shadow while `TWO_PASS_DELIVERY_IMPLEMENTED` is False;
3. the pipeline and the ledger entry refuse `delivered`.

Learners receive only the D-19 contained answer, unchanged. Its evidence panel (development only by default) labels it "lexically screened" and never "grounded".

**Residual risks.**
- Plan Phase 3 M names "misleading wording within locked claims". `sentences-v2` keeps abbreviations (for example "e.g."), initials and numbers inside their sentence: 1 of 2177 dev sentences still ends at an initial, a bibliography line. A quotation cannot be cut at a span's edge either, since `resolver-bundle-sentence-v2` refuses such a fragment. Locked claims can still mislead by what a whole sentence leaves out of context; Phase 4 adds the entailment and V1 checks.
- Recall. `sentences-v2` never ends a sentence at a period followed directly by a footnote number ("optimization.15 If"), so many document sentences run long, and 485 of the 1030 dev document spans hold no whole sentence. On public fixtures the two-pass shadow therefore answers fewer items than the legacy contained path (148 against 167 of 299 under `bm25f-v1`; `docs/evaluation/phase3/`). Shadow runs reach no learner; a sentence rule that splits at footnote markers would be a new rule id and a new replay.
- The renderer's own wording (fixed templates) is a residual R-41 surface. It is pinned by the pedagogical prompt hash and covered by the subset check.
