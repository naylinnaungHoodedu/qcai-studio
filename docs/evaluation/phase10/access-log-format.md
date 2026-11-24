# Research-plane access log (`access-log-v1`)

An append-only JSONL file in the research plane. Each line records one access to a research artifact by role, with the
artifact's sha256; it holds no names, no identifiers of people and no text. `evaluation/qcai_eval/access_log.py` writes it.

| Field | Values |
|---|---|
| `log` | `access-log-v1` |
| `at` | UTC time, `YYYY-MM-DDTHH:MM:SSZ` |
| `actor_role` | `PI`, `MLE`, `DS`, `RL`, `RV` |
| `action` | `read`, `write`, `run`, `export` |
| `artifact_kind` | `ulqs_items`, `evidence_catalog`, `ratings`, `fingerprints`, `run_output`, `irb_record`, `osf_record` |
| `artifact_sha256` | the artifact's sha256 (a dataset, catalog or file hash) |
| `purpose` | a short purpose code (for example `validate`, `migrate rc1 to v1.0`, `exploratory`) |
| `run_id` | optional: the run the access belongs to |

`--access-log PATH` is required by `run_evaluation.py`, `migrate_ulqs_rc1.py`, `validate_ulqs.py` and
`build_licensed_fingerprints.py` whenever their inputs are not all synthetic, and the log path must itself be a
research-plane path.
