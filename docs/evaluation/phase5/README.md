# Phase 5 fixture evidence: F-1 and fault injection

`v2_fixture_report_v1.json` is written by `scripts/run_v2_fixtures.py` (Phase 5 spec 12.1). These are fixture measurements, not research results (plan Phase 5 H: "V-2, V-4 are E2 results, never claimed from fixtures").

**Reproduce.**

```
python scripts/run_v2_fixtures.py --check docs/evaluation/phase5/v2_fixture_report_v1.json
python scripts/run_v2_fixtures.py --write docs/evaluation/phase5/v2_fixture_report_v1.json   # from a clean tree; --allow-dirty otherwise
```

**What runs.** The 298 public score-floor queries (174 in-domain, 124 off-topic and stopword-only; never ULQS) through the two-pass pipeline in development with V1 enforcing and `MODEL_GATEWAY=on`, over the all-public-approved store and the development registry's four fake families, in five passes: `all_up` (FULL), `one_down` (`fake-gamma` and `fake-delta` disabled: REDUCED-2), `two_down` (`fake-beta` to `fake-delta`: REDUCED-1), `three_down` (all four: ZERO) and a `cache_pass` repeating `all_up` on its gateway and cache.

**F-1** (spec R-g): every response's ledger record verifies in its chain and carries a verdict with V1 results for every recorded claim, every V2-eligible claim of a V1-passed candidate carries a V2 verdict, and no V2 verdict follows a V1 hard fail or abstention. Each scenario reports `298/298`.

**Provenance.** `commit` is informational (the HEAD the record was written on, `-dirty` with `--allow-dirty`); `inputs` (the LF sha256 of every imported repository module) is what `--check` compares, with `created_at`, `commit` and latency left out.
