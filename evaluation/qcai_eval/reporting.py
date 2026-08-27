from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping


def build_report(*, run_manifest: Mapping[str, object], metrics: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_manifest": dict(run_manifest),
        "metrics": dict(metrics),
        "reporting_requirements": ["wilson_intervals", "paired_mcnemar", "effect_sizes", "comparison_count", "stratum_denominators"],
    }
