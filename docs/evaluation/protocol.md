# E1-E4 evaluation protocol (VBT RevB Sec. VIII-X; Phase 10)

The harness is in `evaluation/qcai_eval` and `scripts/` (Phase 10 spec: `docs/architecture/phase10-implementation-spec.md`).
No E1-E4 run has been executed: every procedure below waits on the research data plane (D-14), the IRB letter and the OSF
DOI (D-08), pinned models (D-07) and the frozen ULQS (DI-129..DI-141). Not executed: nothing here is a result or an asserted outcome.

1. **Freeze.** ULQS v1.0 passes `scripts/validate_ulqs.py --freeze` in the research plane (120-200 items at the strata
   targets of `lqs/ulqs-v1.0-freeze-rules.json`, every pointer resolved character for character, Krippendorff's alpha at
   least 0.667 and at least a quarter of items second-rated). The freeze record pins the dataset sha256.
2. **Pin.** The run spec pins the configuration package by path and sha256, the items, the evidence catalog, the arms
   (`evaluation/config/arms_v1.json`) and the analysis plan (`evaluation/config/analysis_plans_v1.json`). Seeds are
   sha256(run_id, arm, item_id, replicate).
3. **Arms (Table XV).** Every arm is GATE's configuration plus a declared ablation, checked by the parity check (AC-10-2):
   `NR` (no retrieval, no gate), `LEX` (lexical retrieval with the gate's floor), `SEM` (semantic, no gate), `GATE` (the
   deployed configuration), `GATE+SV` (one verifier in a refine-or-refuse loop), `GATE+V1` (baseline validation only) and
   `VLOOP` (V1, the V2 panel under 2oo3, and correction). The former four-arm letters correspond as A to `NR`, B to `LEX`,
   C to `SEM` and D to `GATE`.
4. **Execute.** Three replicates on a 40-item S1 subsample; failed provider calls are retried three times, then logged and
   counted as outcomes; abstentions are outcomes, not missing data. Payload logs hold pointers, hashes and sizes only.
5. **Label.** Atomic claims are labelled supported, attribution error, unsupported but true, or fabricated, with the EHMF
   type; abstaining units are labelled supported or unsupported abstention (`lqs/rubric.md`).
6. **Analyse.** Exact McNemar, the one-sided bootstraps and the Friedman test of the pre-registration, with Holm within each
   family at alpha 0.05. Only McNemar, Wilson and Holm are implemented; the rest are not implemented (DI-138).
7. **Scan.** Before and after a run, `scripts/scan_research_logs.py` scans every research-plane log with the salted
   fingerprints and must report zero matches.

The protocol never permits publication of restricted evidence text. A released benchmark carries pointers only.
