# Phase 10 records: evaluation and research harness

Evidence class: engineering records over synthetic inputs. Nothing here is an E1-E4 result; no experiment has been
executed and no Table XVII row or HR-1..MR-3 outcome is asserted (plan Phase 10 P; invariant 9).

| Record | Written by | Checked in CI by |
|---|---|---|
| `synthetic_run_spec_v1.json` | hand (the synthetic stub run's spec) | `run_evaluation.py --check` |
| `synthetic_run_record_v1.json` | `run_evaluation.py --write ... --spec synthetic_run_spec_v1.json` | `run_evaluation.py --check` (byte for byte, AC-10-3) |
| `pinned_configuration_v1.json` | `check_research_harness.py --write` | `check_research_harness.py --check` |
| `seeded_faults_report_v1.json` | `check_research_harness.py --write` | `check_research_harness.py --check` |
| `preregistration-draft.md` | `check_research_harness.py --write` | `check_research_harness.py --check` |
| `ulqs-v1.0-dataset-card.md`, `contamination-report-template.md`, `access-log-format.md`, `research-plane-runbook.md` | hand | the AC module's docs tests |

## Exit codes

- `run_evaluation.py`: 0 ok; 1 drift; 2 usage, path or experiment refused; 3 invalid items, unresolved pointers, a freeze
  record or a payload-log violation; 5 interrupted (resume with `--resume`); 6 a pin mismatch; 7 arm parity; 8 a
  confirmatory run refused (IRB or OSF); 9 a live run or hold H12 refused.
- `validate_ulqs.py`: 0; 2 usage or path refused; 3 schema problems; 4 freeze failed; 5 unresolved pointers.
- `migrate_ulqs_rc1.py`: 0; 2 refused path; 3 an input item fails rc1 validation.
- `build_licensed_fingerprints.py`: 0; 2 refused; 3 bad salt.
- `scan_research_logs.py`: 0 zero matches (or the self-test found its sentinel); 1 matches (or the self-test missed); 2 usage.
- `check_research_harness.py`: 0; 1 drift; 3 a known answer not met; 6 a pin; 7 parity.

## Holds and SLIs

- H8 (pinned models, D-07): the run record's `models` pin is null and live runs are refused.
- H10 (IRB and OSF, D-08): confirmatory runs are refused without valid records; the pre-registration is a draft.
- H12 (the research data plane, D-14): every run over non-synthetic items or catalog is refused (`hold_h12_data_plane`).
- Harness SLIs (plan I): completion rate, provider failures by reason, retries and cost units per arm, in provider usage
  units, not USD. There is no production SLO.

## Re-pinning v7

The synthetic spec pins `apps/api/app/config_package/v7.json` by path and sha256. When v7 is retired, the change that
removes it re-pins the synthetic spec to the current package and rewrites the synthetic run record and the pinned
configuration record with `--write`.

Not executed: E1, E2, E3 and E4 (DI-138).
