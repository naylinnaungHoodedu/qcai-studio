# Research-plane access log (`access-log-v1`)

An append-only JSONL file in the research plane. Each line records one access to a research artifact by role, with the
artifact's sha256; it holds no names, no identifiers of people and no text. `evaluation/qcai_eval/access_log.py` writes it.

| Field | Values |
|---|---|
| `log` | `access-log-v1` |
| `at` | UTC time, `YYYY-MM-DDTHH:MM:SSZ` |
| `actor_role` | `PI`, `MLE`, `DS`, `RL`, `RV`: the role given on the command line (`--actor-role`; the migrator's `--author-role`) |
| `action` | `read`, `write`, `run`, `export` |
| `artifact_kind` | `ulqs_items`, `evidence_catalog`, `corpus_text`, `ratings`, `licensed_text`, `fingerprints`, `agreement_record`, `freeze_record`, `scan_report`, `scan_target`, `run_spec`, `recording`, `run_output`, `irb_record`, `osf_record`, `governance_record`, `agent_check_record`, `verification_set`, `e4_responses` |
| `artifact_sha256` | the artifact's sha256 (a dataset, catalog or file hash) |
| `purpose` | a short purpose code (for example `validate`, `migrate rc1 to v1.0`, `exploratory`) |
| `run_id` | optional: the run the access belongs to |
| `outcome` | a `run` line only: `started`, `completed`, `interrupted` or `refused` |

`--access-log PATH` is required by `run_evaluation.py`, `migrate_ulqs_rc1.py`, `validate_ulqs.py` and
`build_licensed_fingerprints.py` whenever their inputs are not all synthetic, and by `scan_research_logs.py` whenever it
reads research fingerprints (`--fingerprints`), together with the actor's role, and the log path must itself be a
research-plane path. Each script logs every research-plane input as soon as it is read, before any check that can refuse
it (an input that does not parse is logged by its file's LF sha256), and every record it writes, so a refused validation,
migration, build or scan still leaves its reads. A log that cannot be appended to (a directory, a path under a file, a
path that is not writable) stops the script at once with exit 2, before any further read or write, so the one line it
could not write is the only one missing:

- `run_evaluation.py`: the spec read (`run_spec`), then each input as soon as the planner reads it (the items, the
  catalog, the recording, an E2-E4 design's pinned inputs (`verification_set`, `e4_responses`, `ratings`), and each
  governance record and the pre-run scan with the sha256 of the bytes read, whether or not it matches its pin), each
  checkpoint file it reads (`run_output`, the sha256 of the bytes read:
  `run_events.jsonl` when a confirmatory or live `--resume` is planned, before the gate's reads, and `run_events.jsonl`
  and `responses.jsonl` when the run starts, before any checkpoint check), the run's start, and its outcome: `completed`
  (with the payload log's sha256), `interrupted` (with the checkpoint's sha256) or `refused`. A run that stops early,
  including one the planner refuses after reading its items (hold H12, the confirmatory gate, a live or pin refusal) or
  one refused on its checkpoint or on an output it cannot write (`output_unwritable`), still leaves its reads and its
  `refused` outcome.
- `validate_ulqs.py`: the items and the previous set, the agent-check record (`agent_check_record`), the catalog, the
  corpus text it read (one `corpus_text` line covering every document whose bytes it read: the sha256 of a UTF-8
  document's text, or `{"undecodable_bytes_sha256": ...}` for one that is not UTF-8), the ratings, and the agreement and freeze records it writes.
- `build_licensed_fingerprints.py`: each licensed text and the ULQS items it reads, and each fingerprint file it writes.
- `migrate_ulqs_rc1.py`: the rc1 items it reads (also when it then refuses them) and the v1.0 items it writes.
- `scan_research_logs.py`: each research fingerprint file it reads (`fingerprints`, with the digest the builder logged
  when it wrote the file), each `--path` target (`scan_target`) and `--research-logs` directory (`run_output`), each with a
  digest of the files it actually read (an environment file it excluded, a binary-suffix file or a file over 20 MiB is
  never opened, so never in the digest), and the scan report it writes (`scan_report`).
