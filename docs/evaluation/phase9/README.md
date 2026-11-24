# Phase 9 evaluation records: verified-trust ranking

- `ranking_replay_v1.json`: the ranking replay report (`scripts/run_ranking_replay.py`). Seven synthetic scenarios
  (numbers and identifiers only: flapping, promotion, outage, drift, model_change, empty_eligible, rating_only), each
  built from its seed with the package's ranking block, folded into the full event log and replayed twice. It records the
  sha256 of the inputs, of the derived events and of the final state, whether both replays equal the log byte for byte,
  and engineering measurements (switches per 1000 drift-free requests, false alarms, the detection delay, fallbacks,
  promotions, demotions). It is an engineering measurement on synthetic streams, not E4 results (invariant 9): Table XVII's
  MR-1..MR-3 are never asserted as met. CI runs `--check` (exit 6 a pin, 7 a replay mismatch, 3 an assertion, 1 drift).
- `hand_fixtures_v1.json`: plan Phase 9 J's hand fixtures (Beta(95,5) -> 0.910, Beta(190,10) -> 0.922), eqs. (5)-(9)
  worked for three outcomes, and the CUSUM constants and steps; a test compares them with the code.

No research item, ULQS item, gold label or licensed text is a fixture or a replay input (D-14, D-15, R-25). The research
replay over E4 logs runs only in the research environment (DI-124).
