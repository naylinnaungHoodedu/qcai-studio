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

- `run_evaluation.py`: 0 ok; 1 drift; 2 usage, a malformed spec, a path, an experiment or another run's checkpoint
  refused; 3 invalid items, unresolved pointers, a freeze
  record or a payload-log violation; 5 interrupted (resume with `--resume`); 6 a pin mismatch; 7 arm parity; 8 a
  confirmatory run refused (IRB or OSF); 9 a live run or hold H12 refused.
- `validate_ulqs.py`: 0; 2 usage (`--freeze` without `--previous` or `--corpus-text`; `--access-log` without
  `--actor-role`), path refused, or an input (items, previous set, ratings, agent check) unreadable or invalid; 3 schema
  problems; 4 freeze failed; 5 evidence catalog invalid or unresolved pointers.
- `migrate_ulqs_rc1.py`: 0; 2 refused path; 3 the input unreadable, an input item fails rc1 validation, or a migrated
  record fails v1.0 validation.
- `build_licensed_fingerprints.py`: 0; 2 refused (a path, no `--access-log` or `--actor-role`, an unreadable input, or a
  licensed text that is not text or .docx); 3 bad salt; 4 ULQS items that are not JSON lines or fail validation.
- `scan_research_logs.py`: 0 zero matches with full coverage (or the self-test found its sentinel); 1 matches, or
  incomplete coverage under `--require-zero` (or the self-test missed); 2 usage (including research fingerprints without
  `--access-log` and `--actor-role`, or an access log on a public path).
- `check_research_harness.py`: 0; 1 drift; 3 a known answer not met or an invalid analysis plan; 6 a pin; 7 parity.

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
