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
   agreement record is written at step 4 and stays current when items change state. Every main-round line names a rated
   unit of its item and the LF sha256 of the rubric passed as `--rubric`; the validator refuses any other (exit 2).
3. **Review and the AI-agent re-check.** Human review moves items through review to frozen and marks `item_kind`; keep
   the review set (or the last frozen set) as `<plane>/data/ulqs-v1.0-review.jsonl`, the previous set. One of the V2
   verifier models, chosen before the check, re-checks every live item against its evidence with the V2 verdict schema,
   and a claim rater who did not review an item adjudicates each disagreement. The `ulqs-agent-check-v1` record
   (`<plane>/records/agent-check.json`) holds, for each item, the status-free content sha256 of the item as the agent
   checked it (`checked_items`; `ulqs.item_content_sha256`), the sha256 of the agent's full report (`report_sha256`), the
   counts, and the ids of the items changed after one of its flags (`items_changed_after_flag`). An item edited after
   the check must be listed there, and only such an item: the freeze fails with `agent_check_stale` on an unlisted change
   and `agent_check_invalid` on a listed item that did not change. An item retired since the check stays in
   `checked_items` and is listed the same way. Each listed item carries its reason: `items_changed_after_flag` for a
   change after one of the agent's flags (at most as many as it flagged), `items_changed_without_flag` for any other
   (such as trimming a stratum to its target). `checked_items` must name every item live in the review set the agent
   checked and every item live now (`agent_check_incomplete` otherwise). Every live item carries its split (`calibration` or `confirmation`;
   the migrator assigns `ulqs-split-v1`, and an added item is given the split that keeps its stratum balanced).
4. **Validate and freeze.** `python scripts/validate_ulqs.py --items <plane>/data/ulqs-v1.0.jsonl --catalog
   <plane>/data/catalog.jsonl --corpus-text <plane>/data/text --ratings <plane>/data/ratings.private.jsonl --rubric
   lqs/rubric.md --agreement-out <plane>/records/agreement.json --freeze --previous <plane>/data/ulqs-v1.0-review.jsonl
   --agent-check <plane>/records/agent-check.json --freeze-out <plane>/records/freeze.json --access-log
   <plane>/access.jsonl --actor-role RL`. The freeze fails on a move outside the state machine, changed frozen content,
   an EV pointer not checked against the corpus text, a live item without a split, a stratum whose split is
   unbalanced counting retired items, or a stratum left without a live item in one split (`split_missing`,
   `split_unbalanced:<S>`, `split_live_missing:<S>`), or a missing, malformed, stale, incomplete or unadjudicated
   AI-agent re-check. A rules file that is unreadable or malformed is refused with exit 2. The freeze record carries the canonical sha256 of the agent-check record (`agent_check_sha256`), the agent's
   report sha256 (`agent_report_sha256`), its model id, its counts, `items_changed_after_flag` and `items_changed_without_flag`, so the agent verifier's
   E2 accuracy can be reported with and without those items (the registered secondary analysis
   `agent_verifier_accuracy_with_and_without_changed_items`). Until D-07 pins a verifier model in the freeze rules, every
   freeze fails with `agent_model_not_pinned` (DI-142).
5. **Fingerprints (from the frozen set).** `python scripts/build_licensed_fingerprints.py --licensed-text <volume> ...
   --ulqs <plane>/data/ulqs-v1.0.jsonl --set-id <id> --output-licensed <plane>/data/licensed.json --output-ulqs
   <plane>/data/ulqs.json --salt-env <NAME> --access-log <plane>/access.jsonl --actor-role MLE` (the salt is hex, at
   least 32 bytes, never printed or committed). Build the ULQS set from the exact frozen item file the run spec pins:
   the runner accepts a pre-run scan only when its ULQS set's `dataset_content_sha256` is the status-free content sha256
   of the run's items, and review edits (human review, `item_kind`) change it, so a set built before the freeze is
   refused (`pre_run_scan_invalid:dataset`). The licensed set is bound to the same run: it records the corpus version
   the items name and their content sha256, and the runner accepts it only when both are the run's
   (`pre_run_scan_invalid:licensed_corpus`), so build both sets in one call. Rebuild them whenever the frozen set
   changes. The builder checks only that each licensed text gives a fingerprint: that the `--licensed-text` files are
   the licensed corpus volumes the catalog's corpus version names is the operator's to ensure (DI-141).
6. **Pre-run scan.** `python scripts/scan_research_logs.py --fingerprints <plane>/data/licensed.json --ulqs-fingerprints
   <plane>/data/ulqs.json --repo --include-env-files --path <plane>/records [--research-logs <plane>/runs/<id> for each
   earlier run] --require-zero --report <plane>/records/pre-run-scan.json --access-log <plane>/access.jsonl --actor-role
   MLE`. Name only targets that exist: a target that scans no file makes the scan `incomplete` and `--require-zero` fails
   it (exit 1). A first run has no earlier run directory, so it omits `--research-logs`; `--path <plane>/records` is then
   its non-repository target (the harness writes no prompt file: the payload log keeps prompt hashes only). The run spec
   pins the report by sha256. The runner accepts it only when it passed with zero matches and full coverage (every target
   scanned a file, none excluded one as too large or unreadable, and no records or run directory held a binary or
   non-text file; the report says `pass`, never `incomplete`), was made with the research fingerprint sets (the ULQS set
   built from the run's items, and the licensed set built alongside them with the same content sha256 and the one
   corpus version the items name, `pre_run_scan_invalid:licensed_corpus`, step 5) and covered the repository and at least one logs or path target.
7. **Run (after H12 is released).** `python scripts/run_evaluation.py --spec <plane>/records/spec.json --output-dir <plane>/runs/<id>
   --access-log <plane>/access.jsonl --actor-role MLE`; after an outage (exit 5), rerun with `--resume` and the same
   spec and responder, the same day or later. Every confirmatory or live run is judged in its run window: today, and its
   start, the day its checkpoint's start event records (`started_on`; a first event that is not a start with a valid
   day not after today is refused, `run_start_invalid`). The IRB must be approved by the start and unexpired today, and
   the OSF and plan H records dated by the start, so a record dated after the run started refuses the resume. The run
   digest covers the spec, `created_at` included, so do not edit it: another run's directory, or a changed spec, is
   refused (`checkpoint_mismatch`). `--resume` into a directory without run events is a fresh start, judged on today.
   `--resume` truncates only a trailing partial line of `responses.jsonl`; a checkpoint with a corrupt complete line, or
   run events that are not UTF-8 JSON, is refused (exit 2) and left as it is, for the operator to inspect. Each
   checkpoint file the run reads is in the access log (`run_output`). An output directory that is a file or lies under
   one, or any output the run cannot write, is refused (`output_unwritable`, exit 2) with its `refused` outcome logged.
   Every input is decoded strictly (no `NaN`, infinity, overflowing, underflowing or out-of-range number, and no string
   that cannot be encoded as UTF-8, such as an escaped unpaired surrogate) and shape-checked by its own validator before
   any request is sent (the package with its ranking block, which an E4 run also dry-runs through the controller
   policies and eq. (8), the harness parameters, the rc1 mapping, the previous item set, the fingerprint files, the salt file, the
   corpus-text documents (one that is not UTF-8 is unavailable) and the agent-check record among them); JSONL files
   are split at LF only, so a text holding a raw U+2028, U+2029 or U+0085 reads back as written; an exit 10 (`internal_error`, naming only the exception's class) is a harness defect no
   validator caught, never a property of the data: keep the inputs as they are, the run's `refused` outcome is in the
   access log, and report it. `created_at` may be any past day (never a future one, `created_at_in_future`). The checkpoint is the operator's
   own file, so this is a consistency check, not tamper evidence (DI-143); an earlier start day only tightens the
   checks. Keep run outputs in the research plane and review each run's start in the access log (step 10). A
   confirmatory run covers every live item of both splits and gives the subsample's 40 S1 items their replicates
   (fewer live items in the stratum: `replicate_subsample_short`); an E3 run uses no subsample, its replicate variance
   being its single-pass repeats at the fixed level. A confirmatory recorded run replays a live recording
   whose header states the live run's start (`started_on`, required, `recording_started_on_missing`, and not after
   today, `recording_after_run`); its window starts on that day, so the IRB must have been approved by then and be
   unexpired on the replay day.
8. **Label.** The registered tests and E2's verification set read the human claim labels inside a run's responses,
   and a live provider's responses carry none, so a run's H1a-H1c, H4a and H4b wait (`awaiting_labels`) and an E2 design
   over them has no verification set (`verification_set_empty`) until the raters' labels (`lqs/rubric.md`) are written
   into the claims of a live recording of the run (`recorded-responses-v1`, its header stating the live run's start) and
   that recording is replayed as a confirmatory recorded run (step 7). The run spec's `labels` is null (any other value
   is refused, `labels`, exit 2). No tool derives that recording from a completed live run or writes the labels into
   it yet (DI-143), so until one exists no confirmatory run reads human labels.
9. **Scan.** `python scripts/scan_research_logs.py --fingerprints ... --research-logs <plane>/runs/<id> --require-zero
   --report <plane>/records/post-run-scan.json --access-log <plane>/access.jsonl --actor-role MLE`, and fill the contamination
   report.
10. **Access log.** Review `<plane>/access.jsonl` (`access-log-format.md`) with the PI before any export.
