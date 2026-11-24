# Contamination report (template)

Filled in the research plane for each run (pre-run and post-run); it holds paths and counts only, never a text. The scan
report it summarises is `scripts/scan_research_logs.py --report` output (`qcai-research-log-scan`, format 1).

| Field | Value |
|---|---|
| Run id | [run_id] |
| Phase | [pre-run / post-run] |
| Fingerprint sets | [licensed set id (`qcai-licensed-fingerprints/1`, 12-word shingles); ULQS set id (`qcai-ulqs-fingerprints/1`)] |
| Fingerprint files | [sha256 of each file; the files and their salts stay in the research plane] |
| Targets | [repository (git ls-files); each run directory (every file except responses.jsonl); other paths] |
| Files scanned / excluded | [counts, with each exclusion's reason] |
| Matches | [matches_total; must be 0] |
| Result | [pass / fail] |
| Scan report sha256 | [sha256 of the report the run spec pins as `pre_run_scan`] |
| Signed off by (role) | [PI / MLE] |

A match is a plan L stop: the run is not started, or its outputs are quarantined, until the source is removed and a new
scan passes. Limitation: pre-training contamination of the pinned models is not detectable here (R-25).
