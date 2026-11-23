"""V3 audit and adjudication (plan Phase 6 D tasks 1-4; docs/architecture/phase6-implementation-spec.md).

Modules: rules (the vocabulary), contracts (the gold label, the CUSUM alarm, the reviewer's view), triggers (X1-X6 as
pure functions over a validated ledger record), draw (the seeded audit draw), priority (severity x exposure x (1 - K)),
scan (the ledger scan that fills the queue), queue (the queued -> claimed -> adjudicated -> applied workflow), gold (the
append-only, hash-chained gold store), feedback (the learner flag, F_i), events (X5 events and the CUSUM interface),
holds (what V3 withholds), stop (the queue-age stop), metrics and residual (the SLIs and the Wilson bound), views (the
reviewer's blind view) and package_check.

V3 runs only where V3_QUEUE is shadow or on (shadow in development by default, off elsewhere, on refused outside
development before the Phase 6 exit). Nothing here reaches a learner: an applied gold label edits no ledger row and no
verdict and releases nothing (Phase 7 change control, DI-93); the holds and the stop are computed from the immutable
records and the stored queue, so disabling V3 never releases a withheld item (plan Phase 6 L). No module here imports a
learner module, the auth layer, a route, the answer history or the frozen Phase 1 retrieval; stop and triggers import
the V2 panel only inside functions, so the V2 track may import them. Every service event logs on qcai.v3 with
enumerations, counts, item ids, model keys, seq numbers and hashes only.

mode() is the V3 mode:
  off     the package has no v3 block, the start-up check found a v3 problem, or V3_QUEUE is off (the default outside
          development): no scan, no draw, no item, no flag intake (the flag route answers an authenticated caller
          404); the reviewer routes answer 404 to an admitted reviewer, after the role and pool checks that refuse
          every other authenticated caller with 403 (a caller without a credential gets 401 where demo auth is off)
  shadow  the scan, triggers, queue, draw, gold store, workflow, reviewer routes and metrics run (development default)
  on      as shadow; the delivered path's consumption of the holds is DI-97
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config import Settings
    from app.core.config_package import ConfigPackage

# Set by the start-up check (app.main._check_v3_package) when the package's v3 block disagrees with the code.
V3_UNAVAILABLE_REASON: str | None = None

_EXPORTS = {
    "run_scan": "app.services.v3.scan",
    "ScanResult": "app.services.v3.scan",
    "withheld_claim_ids": "app.services.v3.holds",
    "tier1_withheld": "app.services.v3.stop",
    "stop_state": "app.services.v3.stop",
    "record_cusum_alarm": "app.services.v3.events",
    "record_flag": "app.services.v3.feedback",
    "f_i": "app.services.v3.feedback",
}

__all__ = sorted([*_EXPORTS, "V3Off", "V3_UNAVAILABLE_REASON", "mode"])


class V3Off(RuntimeError):
    """The V3 mode is off (or the flag intake is asked for outside development)."""


def mode(settings: "Settings", package: "ConfigPackage") -> Literal["off", "shadow", "on"]:
    if package.v3 is None or V3_UNAVAILABLE_REASON is not None:
        return "off"
    setting = settings.v3_queue or "off"
    return setting  # type: ignore[return-value]


def require_on(settings: "Settings", package: "ConfigPackage") -> str:
    """The V3 mode, or V3Off when it is off."""
    current = mode(settings, package)
    if current == "off":
        raise V3Off("V3_QUEUE is off")
    return current


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    import importlib

    return getattr(importlib.import_module(module_name), name)
