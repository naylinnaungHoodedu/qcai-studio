# Citation migration report (format 1)

**What writes it.** `python -m app.workers.migrate_citations` (or `python scripts/migrate_citations.py`) prints this report. With `--report PATH` it also writes it to a file. The job implements plan task 2.3 and Phase 2 G.

**What it holds.** Counts only. It never contains a learner id, a row id or an excerpt.

**Sample.** `citation_migration_report_sample.json` is a synthetic example. It was made from made-up rows in a temporary SQLite database; no production or learner data was read.

## Modes and exit codes

| Mode | Writes | Purpose |
|---|---|---|
| `--dry-run` (default) | nothing, not even span registrations | the report to file and compare with D-30 before any cutover |
| `--apply` | rewrites matching rows with compare-and-set, and registers the matched spans in the same transaction | migration |
| `--downgrade` | restores every element that carries `legacy_original` | rollback; the restored text is byte-for-byte the original |

Exit codes:
- `0`: pass.
- `3`: stop condition (D-30, below).
- `2`: usage error.
- `1`: any other error.

In production, every mode except `--dry-run` is a database write. Each one needs Platform Owner approval under D-05.

## Fields

**Top level:**
- `report`, `format_version`, `mode`, `generated_at` (UTC);
- `commit` (the image `GIT_SHA`);
- `database_dialect`, `span_scheme`, `corpus_version`;
- `config_package` (version and sha256).

**`span_sources`:** where the match keys came from.
- `memory_spans`: the authored item plus every public-plane, bound document on disk.
- `database_rows`: rows in `corpus_spans`.
- `memory_items`: item ids.

**`tables.<name>`:** one block per table, `qa_interactions` and `tutor_turns`.
- **Row counts:**
  - `rows_scanned`, `rows_with_citations`;
  - `rows_changed`: rows that `--apply` would rewrite (or `--dry-run` counts);
  - `rows_skipped_null`;
  - `rows_skipped_non_canonical`: rows whose stored JSON text is not exactly `json.dumps` of its value. They are never rewritten, because they could not be restored byte for byte;
  - `rows_cas_conflict`: the row changed between read and write.
- **`citations`:**
  - `total`;
  - `native_v2`: Phase 2 citations that resolve;
  - `native_unresolved`: Phase 2 citations that do not resolve. This is a stop;
  - `already_migrated`, `migrated`;
  - `legacy_unresolved`, broken down in `by_reason`: `excerpt_no_match`, `excerpt_ambiguous`, `chapter_summary_excluded`, `missing_excerpt`, `invalid_shape`;
  - `diagnostics`, which never change an outcome: `key_lexical` and `key_semantic` (which display path matched), `title_equal`, `title_differs`, `containment_also_in_other_span` and `v1_content_hash_agrees`;
  - `exact_match_regressions`;
  - `restored` (`--downgrade`).
- **`claims`** (`tutor_turns` only): `total`, `remapped` (claim span ids moved to the migrated span id), `bound_to_unresolved` and `restored`.

**`totals`:**
- `legacy_citations` = `migrated` + `already_migrated` + `legacy_unresolved`;
- `unresolved_share` and `unresolved_share_wilson95`;
- `native_citations`, `native_unresolved`;
- `exact_match_regressions`, `rows_skipped_non_canonical`.

**`threshold`:**
- the `decision` (D-30) and its `status` (provisional);
- the native and legacy limits from configuration package v1 (`max_unresolved_share_native`, `max_unresolved_share_legacy`), the `native_unresolved_share`, the `legacy_share_statistic` and the `legacy_share_observed` it compares, and `legacy_gated`;
- `result` (`pass` or `stop`) and `stop_reasons`.

## Match rule (D3)
A v0 or v1 citation migrates only when the sha256 of its whitespace-normalised excerpt matches exactly one distinct span. There are two keys:
- the lexical key, `T(T(text, 320), 320)`;
- the semantic key, `T(text, 320)`, where `T` is `truncate_display_excerpt`.

Zero matches give `excerpt_no_match`, several give `excerpt_ambiguous`, and a video citation gives `chapter_summary_excluded` (task 2.7).

## D-30 comparison (provisional; P1-D-18)
Every limit is read from configuration package v1 (`legacy_citations`); none is hard-coded, so ratifying D-30 is a configuration change and a PR. The run stops (exit 3) in any of these cases:
- the native unresolved share exceeds `max_unresolved_share_native` (0.0), because citations created by the Phase 2 pipeline must resolve 100%;
- `max_unresolved_share_legacy` is a number and the legacy unresolved share exceeds it (plan Phase 2 L: "stop if unresolved citations exceed the OPEN DECISION threshold"). `legacy_share_statistic` names the measure: `point` (the observed share, the default) or `wilson95_upper` (its Wilson 95% upper bound). The package loader accepts only null or a number in [0, 1];
- `exact_match_regressions > 0`. A regression is a citation whose excerpt hash is unique in the current build but which still ends unresolved (an older registered span with the same text makes it ambiguous), or an already migrated citation whose span no longer resolves (every run re-verifies them);
- in `--apply`, `rows_skipped_non_canonical > 0`.

While D-30 is open the legacy limit is null: the legacy unresolved share is reported with its Wilson 95% interval and labelled, but not gated.

Every `legacy_unresolved` citation:
- is labelled "unverified historical reference";
- stays provisional;
- is never presented as resolved (AC-2-3).
