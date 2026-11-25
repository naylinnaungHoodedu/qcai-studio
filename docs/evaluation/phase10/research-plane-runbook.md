# Research-plane runbook (Phase 10)

Runs only once the research data plane exists (D-14). Until then a research-plane path is a location outside the
repository checkout, or a git-ignored path matching the pinned package's `private_plane_globs` (PD-74), and every run over
non-synthetic data is refused by hold H12. `RESEARCH_PLANE_ROOT` names the plane's root for live runs.

1. **Migrate.** `python scripts/migrate_ulqs_rc1.py --input <rc1.jsonl> --output <plane>/ulqs-v1.0.jsonl --author-role RL
   --access-log <plane>/access.jsonl` (candidate items stay candidate; human review starts false).
2. **Fingerprints.** `python scripts/build_licensed_fingerprints.py --licensed-text <volume> ... --ulqs <plane>/ulqs-v1.0.jsonl
   --set-id <id> --output-licensed <plane>/licensed.json --output-ulqs <plane>/ulqs.json --salt-env <NAME>
   --access-log <plane>/access.jsonl --actor-role MLE` (the salt is hex, at least 32 bytes, never printed or committed).
3. **Validate and freeze.** Human review moves items through review to frozen; keep the review set (or the last frozen
   set) as the previous set, then
   `python scripts/validate_ulqs.py --items <plane>/ulqs-v1.0.jsonl --catalog <plane>/catalog.jsonl --corpus-text <plane>/text
   --ratings <plane>/ratings.private.jsonl --rubric lqs/rubric.md --agreement-out <plane>/agreement.json --freeze
   --previous <plane>/ulqs-v1.0-review.jsonl --agent-check <plane>/agent-check.json --freeze-out <plane>/freeze.json
   --access-log <plane>/access.jsonl --actor-role RL`. The freeze fails on a move outside the state machine, changed
   frozen content, an EV pointer not checked against the corpus text, or a missing, stale, incomplete or unadjudicated AI-agent
   re-check (`ulqs-agent-check-v1`: one of the V2 verifier models, chosen before the check, re-checks every item against
   its evidence; a claim rater who did not review an item adjudicates each disagreement; the counts of agent-detected
   defects, false alarms and misses go into the freeze record). Until D-07 pins a verifier model in the freeze rules,
   every freeze fails with `agent_model_not_pinned` (DI-142).
4. **Ratings and agreement.** Raters label the rated units (claims and abstention units) under `lqs/rubric.md`; the
   agreement record is written at step 3 and stays current when items change state.
5. **Pre-run scan.** `python scripts/scan_research_logs.py --fingerprints <plane>/licensed.json --ulqs-fingerprints
   <plane>/ulqs.json --repo --include-env-files --path <plane>/prompts --research-logs <plane>/runs/<previous id>
   --require-zero --report <plane>/pre-run-scan.json --access-log <plane>/access.jsonl --actor-role MLE`; the run spec
   pins the report by sha256. The runner accepts it only when it passed with zero matches and full coverage (every target
   scanned a file and none excluded one as too large or unreadable; the report says `pass`, never `incomplete`), was made
   with the research fingerprint sets (the ULQS set built from the run's items) and covered the repository and at least
   one logs or path target.
6. **Run (after H12 is released).** `python scripts/run_evaluation.py --spec <plane>/spec.json --output-dir <plane>/runs/<id>
   --access-log <plane>/access.jsonl --actor-role MLE`; after an outage (exit 5), rerun with `--resume` and the same
   spec and responder (another run's directory is refused, `checkpoint_mismatch`).
7. **Scan.** `python scripts/scan_research_logs.py --fingerprints ... --research-logs <plane>/runs/<id> --require-zero
   --report <plane>/post-run-scan.json --access-log <plane>/access.jsonl --actor-role MLE`, and fill the contamination
   report.
8. **Access log.** Review `<plane>/access.jsonl` (`access-log-format.md`) with the PI before any export.
