# Phase 8 engineering evidence

`run_invariance_harness.py` exercises the actual two-pass pipeline with three deterministic presentation choices, fresh caches and the pinned fake gateway in shadow mode. It hashes the retrieval and evidence objects and compares locked and delivered claims, citations, and final V1/V2 outcomes. The F-2 scan covers typed payloads and the governing configuration. These public fixtures provide engineering evidence. E3 and LQ-1 require separate research evidence.

A failed probe or check exits with the stop status. A run with `--stop-sqlite` and an explicit existing development database also sets its shared adaptation stop. The operator clears that stop explicitly with `--clear-stop-sqlite`. The check without a database argument runs in isolation.

`prove_erasure.py` builds isolated SQLite schemas, seeds user-keyed tables and dependent rows for four synthetic principal classes, erases each target, and checks that control rows and the receipt digest survive. The report contains table names and counts. It excludes user identifiers and receipt tokens.
