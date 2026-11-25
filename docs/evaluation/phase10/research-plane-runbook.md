# Research-plane runbook (Phase 10)

Runs only once the research data plane exists (D-14). Until then a research-plane path is a location outside the
repository checkout, or a git-ignored path matching the pinned package's `private_plane_globs` (PD-74), and every run over
non-synthetic data is refused by hold H12. `RESEARCH_PLANE_ROOT` names the plane's root for live runs.

Layout: `<plane>/data/` holds the research data (items, catalog, corpus text, ratings, fingerprints; never a scan
target, since it holds the texts the scan looks for), `<plane>/records/` the records, which hold hashes, counts and codes
only (agreement, agent check, freeze, scan reports, run specs), and `<plane>/runs/<id>/` each run's outputs. The access
log is `<plane>/access.jsonl` (digests only).

1. **Migrate.** `python scripts/migrate_ulqs_rc1.py --input <rc1.jsonl> --output <plane>/data/ulqs-v1.0.jsonl --author-role RL
   --access-log <plane>/access.jsonl` (candidate items stay candidate; human review starts false).
2. **Ratings and agreement.** Raters label the rated units (claims and abstention units) under `lqs/rubric.md`; the
   agreement record is written at step 4 and stays current when items change state.
3. **Review and the AI-agent re-check.** Human review moves items through review to frozen and marks `item_kind`; keep
   the review set (or the last frozen set) as `<plane>/data/ulqs-v1.0-review.jsonl`, the previous set. One of the V2
   verifier models, chosen before the check, re-checks every live item against its evidence with the V2 verdict schema,
   and a claim rater who did not review an item adjudicates each disagreement. The `ulqs-agent-check-v1` record
   (`<plane>/records/agent-check.json`) holds, for each item, the status-free content sha256 of the item as the agent
   checked it (`checked_items`; `ulqs.item_content_sha256`), the sha256 of the agent's full report (`report_sha256`), the
   counts, and the ids of the items changed after one of its flags (`items_changed_after_flag`). An item edited after
   the check must be listed there, and only such an item: the freeze fails with `agent_check_stale` on an unlisted change
   and `agent_check_invalid` on a listed item that did not change.
4. **Validate and freeze.** `python scripts/validate_ulqs.py --items <plane>/data/ulqs-v1.0.jsonl --catalog
   <plane>/data/catalog.jsonl --corpus-text <plane>/data/text --ratings <plane>/data/ratings.private.jsonl --rubric
   lqs/rubric.md --agreement-out <plane>/records/agreement.json --freeze --previous <plane>/data/ulqs-v1.0-review.jsonl
   --agent-check <plane>/records/agent-check.json --freeze-out <plane>/records/freeze.json --access-log
   <plane>/access.jsonl --actor-role RL`. The freeze fails on a move outside the state machine, changed frozen content,
   an EV pointer not checked against the corpus text, or a missing, malformed, stale, incomplete or unadjudicated AI-agent
   re-check. The freeze record carries the canonical sha256 of the agent-check record (`agent_check_sha256`), the agent's
   report sha256 (`agent_report_sha256`), its model id, its counts and `items_changed_after_flag`, so the agent verifier's
   E2 accuracy can be reported with and without those items (the registered secondary analysis
   `agent_verifier_accuracy_with_and_without_changed_items`). Until D-07 pins a verifier model in the freeze rules, every
   freeze fails with `agent_model_not_pinned` (DI-142).
5. **Fingerprints (from the frozen set).** `python scripts/build_licensed_fingerprints.py --licensed-text <volume> ...
   --ulqs <plane>/data/ulqs-v1.0.jsonl --set-id <id> --output-licensed <plane>/data/licensed.json --output-ulqs
   <plane>/data/ulqs.json --salt-env <NAME> --access-log <plane>/access.jsonl --actor-role MLE` (the salt is hex, at
   least 32 bytes, never printed or committed). Build the ULQS set from the exact frozen item file the run spec pins:
   the runner accepts a pre-run scan only when its ULQS set's `dataset_content_sha256` is the status-free content sha256
   of the run's items, and review edits (human review, `item_kind`) change it, so a set built before the freeze is
   refused (`pre_run_scan_invalid:dataset`). Rebuild it whenever the frozen set changes.
6. **Pre-run scan.** `python scripts/scan_research_logs.py --fingerprints <plane>/data/licensed.json --ulqs-fingerprints
   <plane>/data/ulqs.json --repo --include-env-files --path <plane>/records [--research-logs <plane>/runs/<id> for each
   earlier run] --require-zero --report <plane>/records/pre-run-scan.json --access-log <plane>/access.jsonl --actor-role
   MLE`. Name only targets that exist: a target that scans no file makes the scan `incomplete` and `--require-zero` fails
   it (exit 1). A first run has no earlier run directory, so it omits `--research-logs`; `--path <plane>/records` is then
   its non-repository target (the harness writes no prompt file: the payload log keeps prompt hashes only). The run spec
   pins the report by sha256. The runner accepts it only when it passed with zero matches and full coverage (every target
   scanned a file, none excluded one as too large or unreadable, and no records or run directory held a binary or
   non-text file; the report says `pass`, never `incomplete`), was made with the research fingerprint sets (the ULQS set
   built from the run's items, step 5) and covered the repository and at least one logs or path target.
7. **Run (after H12 is released).** `python scripts/run_evaluation.py --spec <plane>/records/spec.json --output-dir <plane>/runs/<id>
   --access-log <plane>/access.jsonl --actor-role MLE`; after an outage (exit 5), rerun with `--resume` and the same
   spec and responder (another run's directory is refused, `checkpoint_mismatch`).
8. **Scan.** `python scripts/scan_research_logs.py --fingerprints ... --research-logs <plane>/runs/<id> --require-zero
   --report <plane>/records/post-run-scan.json --access-log <plane>/access.jsonl --actor-role MLE`, and fill the contamination
   report.
9. **Access log.** Review `<plane>/access.jsonl` (`access-log-format.md`) with the PI before any export.
