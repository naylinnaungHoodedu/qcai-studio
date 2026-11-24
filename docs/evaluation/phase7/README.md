# Phase 7 evaluation records (EHMF operationalization)

Change-control gate, not research results (plan Phase 7 H; 12.5).

| File | What it is | Reproduce |
|---|---|---|
| `golden_set_v1.json` | golden-set-v1: 40 public-corpus or synthetic items, disjoint from ULQS (R-25), each with the EHMF finding types it must carry and whether an attacked claim is delivered, X2 is emitted or a conflict is disclosed | built once from the Phase 4 fixture file and in-domain queries of `apps/api/tests/data/score_floor_queries.json`; its canonical sha256 is pinned in the `ehmf.golden_set` block in packages v6, v7 and v8 |
| `golden_run_v1.json` | the committed golden run: the package, library, routing and golden-set sha256s it ran against and every item's outcome | `python scripts/run_golden_set.py --write docs/evaluation/phase7/golden_run_v1.json --allow-dirty` on the finished change, committed with it (its `commit` then names the parent commit with `-dirty`), or `--write` without `--allow-dirty` on a tree equal to HEAD after the code commit (its `commit` names that commit). The committed record names the clean Phase 8 integration source commit without a `-dirty` suffix. `created_at` and `commit` are informational; `inputs.sha256` identifies the code (`docs/architecture/ehmf-change-control.md`); CI runs `--check` |
| `package_versions.json` | the package version history: one `{version, sha256}` entry per `package_version` of a package with an ehmf block, append-only; `--check` exits 6 when the package's version is missing or recorded with another sha256 (a package edit that keeps its version), and, with `--base-ref` (CI passes the base branch), when the history does not start with the base branch's history unchanged | appended by `run_golden_set.py --write`; never edited by hand, except renumbering step 4 of `docs/architecture/ehmf-change-control.md` before the history reaches `main` |
| `source_fidelity_register.json` | the plan's measured DOCX facts only (F-7, E-30): QUEN External Sens. and External FP Rate, and the "perfectly aligned" wording where GEA = 0.40 | edited only when a source fact is established (Q-11 is unresolved) |
| `source_fidelity_report_v1.json` | the source-fidelity check over the 12 tracked DOCX: 3 mismatches | `python scripts/check_source_fidelity.py --write docs/evaluation/phase7/source_fidelity_report_v1.json`; CI runs `--check` |

Golden-set composition (PD-47): negation 10 (Phase 4 stripped and inserted negation), invented citation 5 (Phase 4
unresolvable span ids), non-supporting citation 3 (synthetic: every verifier NOT_ENOUGH_INFO), misconception 3 (Phase 4,
with its own fixture library), conflict 3 (Phase 4 version-of-same-asset conflicts, disclosed), keyed-answer leakage 3,
alignment leakage 1 (synthetic), invalid schema 2, exhausted 2 (synthetic: every verifier CONTRADICTED), supported 8.

The fidelity report states the current mismatches; AC-11-3 ("Zero DOCX mismatches; QUEN row reads Sensitivity 0.828, FP
1.143.") waits for the Content Owner's correction at source (D-16; DI-105). Engineering edits no DOCX, and
`--require-zero` joins CI only after that correction.
