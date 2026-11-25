# ADR-012: Evaluation and research harness

## Status

Accepted for engineering on 2026-11-24 (Phase 10; plan L1680-1742). The parameters are provisional defaults (PD-60..PD-74,
ratified under DI-140). The Phase 10 exit is not passed (DI-129).

## Context

- The runner wrote `metrics={}` (Evidence E-57), and the ablation table had four arms (A-D), not the seven of Table XV.
- ULQS rc1 has 88 of 160 items from one author, no second rater and no agreement data (Evidence E-56). It lives outside
  the repository; its companion files (the evidence catalog, the rc1 validator and schema, the benchmark specification) are
  not on disk (DI-137).
- The research data plane (D-14), pinned models (D-07), the IRB and OSF path (D-08), the licence ruling (Q-07), raters
  (Q-17) and ULQS beyond rc1 (Q-18) are open. Plan section 7: "research runs use a separate gateway and span store".

## Decision

1. The harness is the evaluation package and research-plane scripts only (plan E: "Evaluation package and research plane
   only; no production component."). Nothing changes in the application, the configuration package, Alembic, the settings,
   `/ready` or the frontend; the image ships no evaluation code.
2. ULQS v1.0 is a versioned schema over the rc1 record shape, with the paper's states plus `retired`, a hand-written
   validator, a freeze check (the conventional check, then the paper's AI-agent re-check, whose verifier model D-07 must
   pin first: DI-142) and an rc1 -> v1.0 mapping table (`lqs/`). The strata targets are the paper's Table XIII
   allocation in one provisional data file (PD-63), with the rc1 card's allocation recorded as the conflicting source.
3. EV pointers resolve through a research-plane evidence catalog; public span ids through the Phase 2 resolver.
4. Agreement is Krippendorff's alpha (nominal) over the rated units of the live items, at the 0.667 floor, with at least a
   quarter of the live items second-rated (rounded up in each stratum), in exact arithmetic. A main-round rating of a unit
   its item does not own, or made under another rubric than the one the record names, is refused.
5. The seven arms are data: GATE plus a declared ablation, with a parity check (AC-10-2).
6. The runner pins the package by path and sha256 (the synthetic spec pins v7, named once as `planes.PINNED_PACKAGE`,
   which stays readable under DI-317 while v8 ships; v8 keeps v7's boundary block), the items, the catalog, the arms and
   the analysis plan; seeds are hashed. Stub and recorded runs repeat byte for byte. Live runs are refused here; owner
   decisions are read only from a committed package (an entry of the package history that is a `vN.json` of the package
   directory), so hold H12 refuses every run over non-synthetic data while no committed package the spec pins decides
   D-14, and a hand-made decided copy releases nothing; a confirmatory run needs a valid IRB record and OSF record
   (AC-10-5); E1-E4 runs are confirmatory only, and the runner implements E1's design and its registered family alone
   (E2-E4 refused, `experiment_not_implemented`; DI-144). A confirmatory or live run is judged in its run window, never against its spec's
   `created_at` (which may only not be a future date): `today`, the UTC day it is planned, and `start`, the earliest of
   today, the day its checkpoint's start event records (a resume after an outage, on any later day) and the day a live
   recording's header states (a confirmatory replay). The IRB must be approved by `start` and unexpired on `today`, and
   the OSF and plan H records dated by `start`. An earlier `start` only tightens these checks, so a hand-written start
   event or recording header gains nothing over a fresh start today; the checkpoint and the header are the operator's
   files, so the checks are consistency checks, not tamper evidence (DI-143). Every live item carries its calibration or confirmation split (plan 10.5(2), Risk R-25), for
   threshold calibration on the calibration split only (plan L470); a confirmatory run covers both splits, as E1 runs
   all ULQS items, and replicates its full subsample.
7. Payload logs hold pointers, hashes and sizes only (AC-10-6). Contamination is scanned with salted fingerprints of the
   licensed corpus and of the ULQS; public CI uses synthetic fingerprints with a published salt (AC-10-4).
8. The E1-E4 analysis plans are data with no outcome fields and a draft status (nothing is filed with OSF, DI-131); the
   pre-registration draft is generated from them. Each hypothesis carries its sidedness, its comparison and, as its
   margin, the paper's null (H2b: DR <= 1); H4b carries the paper's EQC reliability condition; the paper's secondary
   analyses are registered as not implemented. Every hypothesis test they register is a function of `statistics.py` with
   known-answer tests that returns its Holm p-value, and has run on no research data (DI-138).

## Consequences

- Every AC is provable in code on synthetic data, and no ULQS item, gold label or licensed text enters the repository or CI.
- The real-data halves wait on the owner decisions and PI items (DI-129..DI-146); nothing here decides them.
- A code change to `evaluation/qcai_eval/*.py` or `scripts/run_evaluation.py` changes the committed synthetic run
  record's code pins, so CI's `run_evaluation.py --check` fails until the record is rewritten with `--write`: the record
  always names the code it ran. The pins read CRLF as LF and cover no other file, so a CRLF checkout or a change
  elsewhere leaves the record current.

## Residuals

Plan M: "[Risk R-10][Risk R-25][Risk R-43][Risk R-45]. Residual: pre-training contamination, reported as limitation."
The scanner finds verbatim and near-verbatim reuse only; pre-training contamination of the pinned models is reported as a
limitation in the dataset card.

Plan L: "Stop: contamination, negative licence determination, low agreement, no IRB." Each stop is a refusal: the scanner
exits 1 on a match and a non-synthetic or confirmatory run needs a passing pre-run scan with full coverage, made with
the research fingerprint sets and bound to its items; a negative licence ruling (a hash-checked record) refuses a
live run (`licence_negative`); low agreement fails the freeze record a confirmatory run needs; a missing IRB refuses a
confirmatory run (`irb_missing`) and a live run (`irb_not_filed`).
