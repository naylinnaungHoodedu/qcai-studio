"""V1 deterministic validation (plan Phase 4; plan 7.1 L6 "modules v1_checks"; docs/architecture/phase4-implementation-spec.md).

One module per check (v1_1_resolution ... v1_9_schema_readability), each a pure synchronous function except V1.3,
which is model-based behind the EntailmentChecker interface (only the NullChecker is wired while D-21 is open). The
aggregator (aggregate) types the outcome: a V1HardFail is final and has no consult path, and only a V1Passed can
reach a V2 hook (plan rule 1, invariant 3). The runner (runner) is the V1 track of the two-pass pipeline; the legacy
guard (legacy_guard) enforces V1.1 and V1.2 on every contained answer delivered, with no flag (plan Phase 4 L), and
withholds an answer quoting conflicting passages when no evidence panel discloses them (V1.7, AC-4-6).
Thresholds are read only from configuration package v3 `v1` (R-46).

No module here imports a learner module, the auth layer, a route, the answer history or the frozen Phase 1 retrieval
(the AC-3-1 import scan covers this package). Names are re-exported lazily.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config import Settings
    from app.core.config_package import ConfigPackage

# Set (or cleared) by the start-up check (main._check_tutor_pipeline_package): a reason keeps the two-pass V1 mode off
# (only in development with governance off: every other build stops instead); the legacy guard still runs.
V1_UNAVAILABLE_REASON: str | None = None

_EXPORTS = {
    "V1Track": "app.services.v1_checks.runner",
    "V1Context": "app.services.v1_checks.runner",
    "V1Run": "app.services.v1_checks.runner",
    "V1HardFail": "app.services.v1_checks.aggregate",
    "V1Abstained": "app.services.v1_checks.aggregate",
    "V1Passed": "app.services.v1_checks.aggregate",
    "consult_v2": "app.services.v1_checks.aggregate",
    "guard_contained": "app.services.v1_checks.legacy_guard",
    "V1_METRICS": "app.services.v1_checks.metrics",
}

__all__ = sorted([*_EXPORTS, "mode", "V1_UNAVAILABLE_REASON"])


def mode(settings: "Settings", package: "ConfigPackage") -> Literal["off", "shadow", "enforce"]:
    """The V1 mode of the two-pass pipeline: off without a v1 block or when the start-up check found a problem,
    otherwise V1_PIPELINE (enforce in development by default; outside development Settings refuse off, and refuse
    enforce before the Phase 4 exit)."""
    if package.v1 is None or V1_UNAVAILABLE_REASON is not None:
        return "off"
    return settings.v1_pipeline or "off"


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    import importlib

    return getattr(importlib.import_module(module_name), name)
