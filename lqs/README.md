# CS595 Labeled Question Set (LQS)

This directory holds the public, reproducible *metadata and instruments* for the RevB §8 evaluation. It intentionally contains no restricted full-text evidence spans. Those spans remain in the controlled private evaluation corpus.

Before G3, freeze and tag:

1. `manifest.jsonl` with 120-200 validated items across every required stratum;
2. `rubric.md` before any candidate or second-rater labels are produced;
3. the corpus manifest/version and evaluator configuration; and
4. `ratings/` with per-item candidate ratings, an independently rated stratified >=25% subsample, and adjudications.

`python scripts/validate_lqs.py --allow-draft` validates the empty/template state without falsely asserting that the required research instrument is frozen. Omit `--allow-draft` only at the freeze gate.
