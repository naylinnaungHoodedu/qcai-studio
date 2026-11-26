# Phase 10 records: evaluation and research harness

Evidence class: engineering records over synthetic inputs. Nothing here is an E1-E4 result; no experiment has been
executed and no Table XVII row or HR-1..MR-3 outcome is asserted (plan Phase 10 P; invariant 9).

| Record | Written by | Checked in CI by |
|---|---|---|
| `synthetic_run_spec_v1.json` | hand (the synthetic stub run's spec) | `run_evaluation.py --check` |
| `synthetic_run_record_v1.json` | `run_evaluation.py --write ... --spec synthetic_run_spec_v1.json` | `run_evaluation.py --check` (byte for byte, AC-10-3) |
| `pinned_configuration_v1.json` (the package and the harness data files, `harness_parameters_v1.json` among them) | `check_research_harness.py --write` | `check_research_harness.py --check` |
| `seeded_faults_report_v1.json` | `check_research_harness.py --write` | `check_research_harness.py --check` |
| `preregistration-draft.md` | `check_research_harness.py --write` | `check_research_harness.py --check` |
| `ulqs-v1.0-dataset-card.md`, `contamination-report-template.md`, `access-log-format.md`, `research-plane-runbook.md` | hand | the AC module's docs tests |

## Exit codes

- `run_evaluation.py`: 0 ok; 1 drift; 2 usage, a malformed spec, a path, an experiment or a checkpoint refused
  (another run's, this run's own with a corrupt line or a partial line without `--resume`, or a complete one without
  `--resume`: `checkpoint_mismatch`, `checkpoint_invalid`, `partial_checkpoint`, `output_exists`), a run output that
  cannot be written (`output_unwritable`), a `--write` or `--record-stub` target or the access log that cannot be
  written (refused without a reason code), a non-synthetic run without the access log or a passing pre-run scan
  (`access_log_required`,
  `pre_run_scan_*`), an E1-E4 family the design does not compute (`analysis_plan_invalid:<experiment>`) or an E2-E4
  design that cannot run (`design`, `design.<field>`, `design_departs_from_registration:<field>` in a live run or over
  research data, `e2_panel_invalid`, `verification_set_empty`, `e3_no_s7_items`, `e4_models_invalid`,
  `e4_shift_invalid`, `e4_later_price_in_force`, `e4_stream_items_below_floor` in a live run or over research data,
  `experiment_requires_arms`), or a confirmatory run refused with no
  IRB, OSF, items or freeze-record reason; 3 invalid items, unresolved pointers, a recording entry the run cannot
  read (`recording_invalid`), a design input (`<input>`:
  `verification_set`, `e4_responses`, `ratings`) unreadable (`<input>_unreadable`) or invalid (`<input>_invalid`,
  `<input>_items`, `<input>_generator_unknown`, `ratings_invalid`) or a payload-log violation, or a confirmatory run
  refused with an items (`items_not_frozen`,
  `items_split_missing`) or freeze-record (`freeze_record_*`) reason and no IRB or OSF reason; 5 interrupted (resume
  with `--resume`, on a later day too); 6 a pin mismatch (a design input's `<input>_sha256` among them); 7 arm parity;
  8 a confirmatory run refused with an IRB or OSF
  reason; 9 a live run or hold H12 refused; 10 an unexpected internal error (`internal_error`: the last-resort handler of `main`, which names the exception's class, never its message, after the run's refused outcome is logged). A refused confirmatory run lists every reason and exits with the first
  class present (`governance.confirmatory_exit_code`). Its dates are judged in the run window (spec 3.13; the
  script's docstring names each date reason).
- `validate_ulqs.py`: 0; 2 usage (`--freeze` without `--previous` or `--corpus-text`; `--access-log` without
  `--actor-role`), path refused, an output or the access log that cannot be written, or an input unreadable or invalid (the items or previous set, the ratings, a main-round rating of a unit its item does not own or under another rubric included, the rubric,
  the freeze rules, or an agent-check record that does not parse or is not shaped as `ulqs-agent-check-v1`); 3 schema
  problems; 4 freeze failed (an agent-check record that does not match the items is a freeze code); 5 evidence catalog
  invalid or unresolved pointers; 10 an unexpected internal error (`internal_error`: the last-resort handler of `main`, which names the exception's class, never its message).
- `migrate_ulqs_rc1.py`: 0; 2 refused path or usage, or an output or the access log that cannot be written; 3 the input unreadable, an input item fails rc1 validation, or a migrated
  record fails v1.0 validation; 10 an unexpected internal error (`internal_error`: the last-resort handler of `main`, which names the exception's class, never its message).
- `build_licensed_fingerprints.py`: 0; 2 refused (a path, no `--access-log` or `--actor-role`, an unreadable input, a
  licensed text that is not text or .docx, or an output or the access log that cannot be written); 3 bad salt; 4 ULQS items that are not JSON lines or fail validation; 10 an unexpected internal error (`internal_error`: the last-resort handler of `main`, which names the exception's class, never its message).
- `scan_research_logs.py`: 0 zero matches (with full coverage only under `--require-zero`: without it an incomplete
  scan also exits 0, its report's `result` says `incomplete` and stderr names the targets), or the self-test found its
  sentinel; 1 matches, or incomplete coverage under `--require-zero` (or the self-test missed); 2 usage (including
  research fingerprints without `--access-log` and `--actor-role`, `--ulqs-fingerprints` with `--synthetic-fixture`,
  an access log on a public path, research fingerprints or their report on a public path, or a report or access log
  that cannot be written); 10 an unexpected internal error (`internal_error`: the last-resort handler of `main`, which names the exception's class, never its message).
- `check_research_harness.py`: 0; 1 drift (a record that differs, or is missing or unreadable); 2 usage (an
  unknown option, `--check` with `--write`, or a path argument holding a NUL) or a `--dir` the records cannot be
  written to (`--write`); 3 a known answer
  not met or an invalid analysis plan; 6 a pin; 7 parity; 10 an unexpected internal error (`internal_error`: the last-resort handler of `main`, which names the exception's class, never its message).

## Holds and SLIs

- H8 (pinned models, D-07): the run record's `models` pin is null and live runs are refused.
- H10 (IRB and OSF, D-08): confirmatory runs are refused without valid records; the pre-registration is a draft.
- H12 (the research data plane, D-14): every run over non-synthetic items or catalog is refused (`hold_h12_data_plane`)
  while the package the spec pins is not a committed package that decides D-14. Owner decisions are read only from a
  committed package (an entry of `docs/evaluation/phase7/package_versions.json` that is a `vN.json` of
  `apps/api/app/config_package`); any other package, such as a hand-made copy with a matching sidecar kept outside the
  package directory, reads every decision `uncommitted` and releases no hold, and the run record pins `committed`. The
  history and the package directory are read from the working tree, never from git, so a copy written into the package
  directory with an entry appended to the history counts as committed: the rule is a consistency check of the
  checkout, not proof that a package was committed or reviewed (DI-147), as the run window is for run starts (DI-143).
- Harness SLIs (plan I): completion rate, provider failures by reason, retries and cost units per arm, in provider usage
  units, not USD. There is no production SLO.

## Re-pinning the pinned package

The harness pins `apps/api/app/config_package/v7.json` by path and sha256 and names it in one place:
`planes.PINNED_PACKAGE` and `planes.PINNED_PACKAGE_VERSION` (`evaluation/qcai_eval/planes.py`). The synthetic spec
generator (`synthetic.PACKAGE_PATH`), the pinned configuration record (`check_research_harness.PACKAGE`) and the
research-plane path rule's default boundary (`planes.boundary_policy`) read them; no other harness module or script names
a package file. Hold H12, the confirmatory gate's D-14 and the live checks read the package a spec pins (when committed),
and a non-synthetic run's output is checked against that package's boundary. The shipped package is v8 (Phase 8); v7
stays readable for one release (DI-317), and every later package keeps v7's boundary block
(`test_plan_e_every_later_package_keeps_the_pinned_package_s_boundary_and_open_decisions`). When v7 is retired (DI-146),
the change that removes it:

1. sets `planes.PINNED_PACKAGE` and `planes.PINNED_PACKAGE_VERSION` to the current package;
2. re-pins the `package` block of `synthetic_run_spec_v1.json` (path, sha256 and package_version of that package);
3. rewrites the synthetic run record (`run_evaluation.py --write`) and the pinned configuration record
   (`check_research_harness.py --write`);
4. rewrites the sentences that name v7: the spec's section 6 configuration-package line, M7 and conflicts 17 and 18,
   ADR-012 decision 6 and this section.

The tests read the two constants (the synthetic spec's package, section 6's pinned package, the pinned package's
boundary), so they follow steps 1-3; the section 6 test fails until step 4 names the new pin, and the boundary check
covers the pinned package and every package numbered after it, none once the pin is the newest package.

Implemented designs: all four, each run under its own analysis-plan family and computing its registered family in the
record's `registered_tests` (spec 4.12, 4.14): E1, every live item through the seven arms (H1a and H1b exact McNemar
paired by item on answerable items, H1c); E2, the three-family verifier panel without the generator, formed by rule
(H2a, H2b, H2c from pinned novice ratings); E3, two-pass generation (the evidential pass's locked claims sent to each
level's presentation pass) and single-pass generation of every S7 item at three levels (H3a, H3b); E4, four models in
GATE and VLOOP, costed at their input and output list prices (the local model's cost reported separately), and their
seeded replay streams over eight routing policies (H4a, H4b). A live run or a run over research data runs the registered
protocol (`design_departs_from_registration:<field>` otherwise); a synthetic run may depart and its record names each
departure. E3's exact claim-set comparison stands in for the paper's entailment comparison, and E4's measured local cost
and latency wait on a pinned local model and the live adapters (spec conflict 40; DI-148).
E2-E4 take their models from the spec's `design` block (PD-75): none is pinned (D-07), so they run on stub or recorded
responses only.

Not executed: E1, E2, E3 and E4 (DI-138).
