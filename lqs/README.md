# CS595 Labeled Question Set (LQS) and ULQS v1.0

This directory holds the public, reproducible *metadata and instruments* for the RevB evaluation. It contains no ULQS item,
no gold label and no restricted evidence text: those stay in the private research plane (R-25, R-26).

## ULQS v1.0 (Phase 10)

- `ulqs-v1.0.schema.json`: the v1.0 item schema (JSON Schema 2020-12, `$id` `ulqs-item-schema-1.1`). It accepts the rc1
  record shape (`schema_version` 1.0) and v1.0 records (`schema_version` 1.1). The validator CI runs is
  `evaluation/qcai_eval/ulqs.py`; a unit test keeps the two in agreement.
- `ulqs-v1.0-freeze-rules.json`: the provisional freeze rules (PD-63, PD-64): 120-200 items, the paper's strata targets
  S1-S7 = A-G = 40/25/20/15/15/20/25, alpha at least 0.667, at least 1/4 second-rated, the Bloom and bibliographic
  shares, the AI-agent re-check with its pinned verifier models (none until D-07; DI-142), and the rc1 card's
  conflicting allocation (DI-136).
- `ulqs-rc1-to-v1.0-mapping.json`: the rc1 -> v1.0 mapping table (PD-61); `corpus_version` is copied and never part of an id.
- `rubric.md`: the rating rubric, frozen before any label is produced.
- `ratings/`: ratings files are private (`*.private.jsonl`, git-ignored).

`python scripts/validate_ulqs.py --items evaluation/fixtures/synthetic_ulqs_v1.jsonl --catalog
evaluation/fixtures/synthetic_evidence_catalog_v1.jsonl` validates the synthetic fixture in CI. The strict freeze check
(`--freeze`, with `--previous` and `--corpus-text`) refuses synthetic items: it runs only in the research plane, on the
real items, checks every state transition from the previous set and every EV pointer against the corpus text, requires
the AI-agent re-check record (`--agent-check`), and writes the freeze record (`--freeze-out`: the dataset sha256, the
agent-check record's sha256, the agent's report sha256, model id and counts, and the items changed after an agent flag;
`docs/evaluation/phase10/research-plane-runbook.md`).

## Legacy LQS

`manifest.jsonl` (empty) and `schema.json` are the earlier LQS format, read by `evaluation/qcai_eval/lqs_loader.py`.
`python scripts/validate_lqs.py --allow-draft` validates the empty state without asserting that an instrument is frozen.
The legacy long-name strata correspond to the ULQS letters as listed in the mapping table.
