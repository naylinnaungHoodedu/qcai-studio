# E1-E4 evaluation protocol (VBT RevB Sec. VIII-X; Phase 10)

The harness is in `evaluation/qcai_eval` and `scripts/` (Phase 10 spec: `docs/architecture/phase10-implementation-spec.md`).
No E1-E4 run has been executed: every procedure below waits on the research data plane (D-14), the IRB letter and the OSF
DOI (D-08), pinned models (D-07) and the frozen ULQS (DI-129..DI-148). Not executed: nothing here is a result or an asserted outcome.

1. **Freeze.** ULQS v1.0 passes `scripts/validate_ulqs.py --freeze --previous <review set> --corpus-text <dir>
   --agent-check <agent re-check record> --freeze-out <freeze record>` (with the catalog, ratings and rubric; the full
   command is the research-plane runbook's step 4) in the research plane (120-200 items at the strata targets of `lqs/ulqs-v1.0-freeze-rules.json`, every move from the previous
   set allowed by the state machine and no frozen content changed, every pointer resolved and checked against the corpus
   text character for character, Krippendorff's alpha over the live items' rated units at least 0.667 and at least a quarter of items second-rated, and
   the AI-agent re-check of every item by a V2 verifier model chosen before the check, with each disagreement adjudicated
   by a claim rater who did not review that item; an item changed after one of the agent's flags is listed in the
   record with its reason, after a flag or for another reason, and an item retired since the check is listed the same
   way), and every live item in the calibration or the confirmation split, the split balanced to within one per stratum
   counting retired items (a frozen item's split never changes) and every stratum keeping a live item in each split
   (`ulqs-split-v1`; plan 10.5(2), Risk R-25). The freeze record pins the dataset sha256, the canonical sha256 of the agent re-check record, the agent's
   full-report sha256 copied from that record, the model id, the agent's counts, the items changed after a flag (so
   the agent verifier's E2 accuracy is reported with and without them) and the items changed for another reason. No verifier model is pinned until D-07, so no freeze passes yet (DI-142).
2. **Pin.** The run spec pins the configuration package by path and sha256, the items, the evidence catalog, the arms
   (`evaluation/config/arms_v1.json`) and the analysis plan (`evaluation/config/analysis_plans_v1.json`). Seeds are
   sha256(run_id, arm, item_id, replicate).
3. **Arms (Table XV).** Every arm is GATE's configuration plus a declared ablation, checked by the parity check (AC-10-2):
   `NR` (no retrieval, no gate), `LEX` (lexical retrieval with the gate's floor), `SEM` (semantic, no gate), `GATE` (Table XV
   calls it "the deployed configuration" of the paper's design; it is not the current production configuration, where
   semantic retrieval is off and learners receive only contained answers), `GATE+SV` (one verifier in a refine-or-refuse loop), `GATE+V1` (baseline validation only) and
   `VLOOP` (V1, the V2 panel under 2oo3, and correction). The former four-arm letters correspond as A to `NR`, B to `LEX`,
   C to `SEM` and D to `GATE`.
4. **Execute.** Three replicates on a 40-item S1 subsample; failed provider calls are retried three times, then logged and
   counted as outcomes (the provisional defaults of `evaluation/config/harness_parameters_v1.json`; a live or confirmatory
   spec must keep the subsample, so its record reports replicate variance); abstentions are outcomes, not missing data. Payload logs hold pointers, hashes and sizes only.
   A confirmatory run covers every live item, the calibration and the confirmation split alike (E1: all ULQS items
   through all seven arms), and its three replicates fall on all 40 items of the S1 subsample (a subsample stratum with
   fewer live items is refused); the calibration split is for threshold calibration only (plan L470), which this harness
   does not do. A run interrupted by a provider outage resumes from its checkpoint with the same spec (`--resume`), on a
   later day too: its run window starts on the day its checkpoint records, so its IRB must have been approved by then
   and still be valid on the resume day, and every other record dated by its start.
5. **Label.** Atomic claims are labelled supported, attribution error, unsupported but true, or fabricated, with the EHMF
   type; abstaining units are labelled supported or unsupported abstention (`lqs/rubric.md`).
6. **Analyse.** Exact McNemar, the one-sided, paired, cluster, BCa, paired-AUC and two-level bootstraps, the Friedman test
   and the paired TOST of the pre-registration, each hypothesis entering Holm within its family at alpha 0.05 through one
   p-value, with its null as the plans state it (H2b: DR <= 1). The equivalence part of H4b is confirmatory only if
   ICC(2,k) >= 0.50 and Cronbach's alpha >= 0.70 across the EQC's six scales, and is otherwise reported as inconclusive.
   Every hypothesis test the analysis plans register is implemented in `evaluation/qcai_eval/statistics.py` with
   known-answer tests and has run on no research data; the eleven secondary analyses (the claim-level mixed-effects
   logistic regression, cumulative-link mixed models, Cliff's delta, the ordinal sensitivity model for EQC, ICC(2,k),
   Cronbach's alpha, prediction-powered inference, H1a's error rate among answers, the agent verifier's E2 accuracy
   with and without the items changed after its flags, UE-2's cumulative-link model of trust by arm and V-4's n_eff;
   `secondary_analyses` in the analysis plans) are registered and not implemented (DI-138). Every Table XVII row Phase 10
   tests is registered as a hypothesis criterion or a `criteria_only` entry. The runner computes each experiment's
   registered family in its run's record: E1's H1a and H1b exact McNemar paired by item on answerable items (VBT RevB
   Table I) and H1c, with Holm; E2's verifier panel (each model verifying every claim outside its own family, the panels
   formed by rule) with H2a, H2b and, from pinned novice ratings, H2c; E3's two-pass and single-pass designs over every
   S7 item at three levels (each two-pass presentation pass sent the evidential pass's locked claims) with H3a and H3b;
   E4's four models in GATE and VLOOP, priced by their input and output list prices with the local model's cost
   reported separately, and their seeded replay streams over eight routing policies with H4a (with the 95% interval of
   its difference) and H4b (spec 4.14). Each design runs on stub or recorded responses until D-07 pins the models, and
   a run over research data runs the registered protocol (the hypotheses' resamples, E3's three repeats, E4's 1,000
   streams of 2,000 requests and its shift). E3 compares claim sets exactly, standing in for the paper's bidirectional
   entailment with human checks on disagreements, and E4's measured local cost and latency wait on a pinned local model
   and the live adapters (spec conflict 40; DI-148).
7. **Scan.** Before and after a run, `scripts/scan_research_logs.py` scans every research-plane log with the salted
   fingerprints and must report zero matches. The pre-run scan the run spec pins must use the research fingerprint sets,
   the ULQS set built from the run's items, cover the repository and at least one logs or records target (the harness
   writes no prompt file: the payload log keeps prompt hashes only), and pass with full coverage (every target scanned a
   file, none excluded one as too large or unreadable, and no logs or records target excluded one as binary or not
   text; the report says `pass`, never `incomplete`).

The protocol never permits publication of restricted evidence text. A released benchmark carries pointers only.
