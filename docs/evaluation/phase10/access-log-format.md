# Research-plane access log (`access-log-v1`)

An append-only JSONL file in the research plane. Each line records one access to a research artifact by role, with the
artifact's sha256; it holds no names, no identifiers of people and no text. `evaluation/qcai_eval/access_log.py` writes it.

| Field | Values |
|---|---|
| `log` | `access-log-v1` |
| `at` | UTC time, `YYYY-MM-DDTHH:MM:SSZ` |
| `actor_role` | `PI`, `MLE`, `DS`, `RL`, `RV`: the role given on the command line (`--actor-role`; the migrator's `--author-role`) |
| `action` | `read`, `write`, `run`, `export` |
| `artifact_kind` | `ulqs_items`, `evidence_catalog`, `corpus_text`, `ratings`, `licensed_text`, `fingerprints`, `agreement_record`, `freeze_record`, `scan_report`, `run_spec`, `recording`, `run_output`, `irb_record`, `osf_record`, `governance_record` |
| `artifact_sha256` | the artifact's sha256 (a dataset, catalog or file hash) |
| `purpose` | a short purpose code (for example `validate`, `migrate rc1 to v1.0`, `exploratory`) |
| `run_id` | optional: the run the access belongs to |
| `outcome` | a `run` line only: `started`, `completed`, `interrupted` or `refused` |

`--access-log PATH` is required by `run_evaluation.py`, `migrate_ulqs_rc1.py`, `validate_ulqs.py` and
`build_licensed_fingerprints.py` whenever their inputs are not all synthetic, together with the actor's role, and the log
path must itself be a research-plane path. Each script logs every research-plane input it reads and every record it
writes:

- `run_evaluation.py`: the spec read (`run_spec`), then each input as soon as the planner reads it (the items, the
  catalog, the recording, and each governance record and the pre-run scan with the sha256 of the bytes read, whether or
  not it matches its pin), the run's start, and its outcome: `completed` (with the payload log's sha256), `interrupted`
  (with the checkpoint's sha256) or `refused`. A run that stops early, including one the planner refuses after reading
  its items (hold H12, the confirmatory gate, a live or pin refusal), still leaves its reads.
- `validate_ulqs.py`: the items and the previous set, the catalog, the corpus text it read, the ratings, and the agreement
  and freeze records it writes.
- `build_licensed_fingerprints.py`: each licensed text and the ULQS items it reads, and each fingerprint file it writes.
- `migrate_ulqs_rc1.py`: the rc1 items it reads and the v1.0 items it writes.
