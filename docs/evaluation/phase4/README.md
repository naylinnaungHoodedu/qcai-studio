# Phase 4: V1 adversarial fixtures and report

**Fixture measurements, not research results** (plan Phase 4 H). The counts here are engineering checks of the V1
code over public-corpus fixtures; they are not E-series evidence, not LQ measurements and never reported as results.
Every threshold they exercise is provisional (Q-22, D-06: "frozen in versioned configuration before use, never
reported as results").

## Files

- `v1_adversarial_fixtures_v1.json`: 66 cases in 16 classes. Each case is hashed (`canonical_sha256`), and the set
  hash and case count are pinned in configuration package v3 (`v1.fixtures`); `scripts/config_package.py --check`
  compares them.
- `v1_fixture_report_v1.json`: the report `scripts/run_v1_fixtures.py` writes.

## Reproduce

```
python scripts/run_v1_fixtures.py --check docs/evaluation/phase4/v1_fixture_report_v1.json
python scripts/run_v1_fixtures.py --write docs/evaluation/phase4/v1_fixture_report_v1.json [--allow-dirty]
```

`--check` recomputes the report and compares it with the record, `created_at`, `commit` and every latency value aside
(latency is compared with the package budget only). Exit codes: 0 pass; 1 drift or a case that does not realise its
attack; 3 a plan L stop; 4 a dirty tree on `--write` without `--allow-dirty`; 5 an adversarial case delivered.

**Provenance.** The committed record is written with `--allow-dirty` before the commit that holds it, so its `commit`
names the HEAD the working tree was based on with `-dirty` (the code that produced it was not yet committed), and is
informational. The provenance is `inputs`: the LF sha256 of every repository module the runner imported, which
`--check` compares with the checkout, together with the fixture set hash and the configuration package hash. The
Phase 3 replay record (`docs/evaluation/phase3/three_plan_replay_v1.json`) is written the same way.

## What runs

- **Corpus.** The all-public-approved store (a temporary manifest approving every public-plane, bound item), in
  development with `V1_PIPELINE=enforce`. Public-corpus only: anything under `lqs/` (ULQS) is refused, and no
  private-plane item, learner record, tutor turn or rating is read. The fixture file holds no corpus text: the
  sentences an attack changes are taken from the store at run time, and every sentence in the file is synthetic. Its
  queries are the project's fixture queries and a few synthetic keyword queries.
- **Two checker configurations.** `production` is the NullChecker (D-21 none): V1.3 flags every claim, D-20 withholds
  it, and nothing is delivered. `deterministic_only` is a fake always-SUPPORTED checker: what the deterministic checks
  (V1.1, V1.2, V1.4-V1.9) catch alone. A case's own checker (raising, late) replaces either.
- **The fixture overlay.** A test-only version family over two document items and a 50 ms checker timeout, applied
  in memory; the shipped package is unchanged and no package is written.

## Classes

| Class | Caught by (deterministic_only) |
|---|---|
| stripped negation, inserted negation, number swap, unit swap, fabricated sentence (generator) | V1.2 (binding and the polarity rule) |
| fabricated sentence (renderer) | V1.4 (the subset check), three renders, then abstain |
| unresolvable span id | V1.1, three generations, then abstain |
| conflict: versions, numbers, negation | V1.7 (a disclosure block) |
| keyed-answer leak | V1.6 (a Socratic re-render without the keyed claim) |
| out of scope | V1.5 |
| checker unavailable | V1.3 (abstain) |
| invalid schema | V1.9 |
| misconception (a fixture library) | V1.8 |
| **residual:** paraphrased contradiction | none under `deterministic_only` (its 3 cases are delivered); under `production` V1.3 withholds it |

Each class reports its cases, catches, catch rate with a Wilson 95% interval (z = 1.959964) and the checks that caught
it. Every non-residual class must be caught in both configurations, and the residual under `production`.

**The residual class.** Plan M names the phase's residuals: "Residual: checker error, paraphrased leakage." The
paraphrased-contradiction class is this fixture set's implementation-defined case of "checker error": a negated
paraphrase of a cited claim, worded too unlike it for V1.7 to align the two, so only an entailment checker could catch
it. AC-4-2 ("every negation, contradiction and fabrication case fails or abstains") therefore holds for these three
cases only under `production`, where the NullChecker flags every claim and D-20 withholds it; with a perfect-support
checker they are delivered. When D-21 hosts a checker (DI-54), AC-4-2 must be re-established for this class (DI-64).

**Per check.** `hard_fail` counts results; `hard_fail_runs` counts the runs in which the check hard-failed at least
once; `hard_fail_rate` is `hard_fail_runs` over `runs` (the runs in which the check ran), the definition of Phase 4
spec 10.3 that `V1_METRICS` and the runbook use, so a run whose three attempts each hard-failed counts once.

## Answer rate and stops

For each gate, the report applies the Phase 2 answer-rate definition ("share of in-domain queries with >= 1 document
span among the top 4 survivors") to V1.5's decision over the 174 in-domain items: 166/174 under `bm25f-v1` and 146/174
under `p1-floor`, equal to the Phase 2 baselines in `docs/evaluation/phase2/calibration_record_v1.json`. The floors
are stored in package v3 as counts. It also counts the two-pass composition with V1 off and with V1 under each
checker (147 and 129), and the items whose decision, claim set and rendering are identical with and without V1 under
`deterministic_only` (174 of 174 per gate). The plan L stops: a V1.5 answer rate below its floor, V1 adding an
in-domain abstention under `deterministic_only`, or the V1 p95 above `v1.stop.v1_p95_latency_ms` (250 ms).
