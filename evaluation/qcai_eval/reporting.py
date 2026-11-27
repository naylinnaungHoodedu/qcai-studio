"""A report envelope kept for import compatibility. The time is an input, never the wall clock, so a report repeats byte for
byte; the run record of the E1-E4 harness is built by `runner.build_record` (Phase 10 spec 7.2)."""

from __future__ import annotations

from typing import Mapping


def build_report(*, run_manifest: Mapping[str, object], metrics: Mapping[str, object], generated_at: str) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "run_manifest": dict(run_manifest),
        "metrics": dict(metrics),
        "reporting_requirements": ["wilson_intervals", "paired_mcnemar", "effect_sizes", "comparison_count", "stratum_denominators"],
    }
