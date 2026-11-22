"""The generator-excluded V2 panel (plan Phase 5 tasks 5.3-5.11; plan 7.2 L6 V2; docs/architecture/phase5-implementation-spec.md).

Modules: rules (the vocabulary and the routing table), voting (the arithmetic), panel (the generator-excluded panel),
tiers, cache (the evidential cache), track (V2Track, the V1 track's V2 hook), aggregate (the V2 verification record)
and metrics. V2 runs only inside the two-pass shadow (TWO_PASS_TUTOR, off outside development): nothing here reaches a
learner. No module here imports a learner module, the auth layer, a route, the answer history or the frozen Phase 1
retrieval. Names are re-exported lazily.

mode() is the V2 mode of a pipeline:
  off     the package has no gateway or v2 block, the start-up check found a gateway problem, the gateway is stopped,
          the two-pass shadow is off (outside development), V1 is off, or MODEL_GATEWAY is off (the default outside
          development): every path is Phase 4's
  shadow  Phase 4 decides every final; the panel votes once beside it and the record carries its verdicts (development
          default); MODEL_GATEWAY=on with V1 in shadow runs as shadow (Settings refuse that combination)
  on      V2 decides each V1-passed claim, with correction cycles, the final rendering, the alignment item and the
          degraded modes (refused outside development before the Phase 5 exit)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config import Settings
    from app.core.config_package import ConfigPackage

LOGGER = logging.getLogger("qcai.tutor")
_ON_DOWNGRADE_LOGGED = False

_EXPORTS = {
    "V2Track": "app.services.v2_panel.track",
    "V2Outcome": "app.services.v2_panel.track",
    "Panel": "app.services.v2_panel.panel",
    "PanelError": "app.services.v2_panel.panel",
    "V2_METRICS": "app.services.v2_panel.metrics",
    "get_cache": "app.services.v2_panel.cache",
    "reset_process_cache": "app.services.v2_panel.cache",
}

__all__ = sorted([*_EXPORTS, "mode"])


def mode(settings: "Settings", package: "ConfigPackage", *, gateway: Any = None) -> Literal["off", "shadow", "on"]:
    global _ON_DOWNGRADE_LOGGED
    from app import gateway as gateway_package
    from app.services import v1_checks
    from app.services.tutor_pipeline import shadow as tutor_shadow

    if package.gateway is None or package.v2 is None or package.tools is None:
        return "off"
    if gateway_package.GATEWAY_UNAVAILABLE_REASON is not None:
        return "off"
    if gateway is not None:
        if gateway.state == "stopped":
            return "off"
    else:
        from app.gateway.gateway import process_gateway_stopped

        if process_gateway_stopped():
            return "off"
    if tutor_shadow.effective_mode(settings, package) == "off":
        return "off"
    v1 = v1_checks.mode(settings, package)
    setting = settings.model_gateway or "off"
    if v1 == "off" or setting == "off":
        return "off"
    if setting == "on" and v1 != "enforce":
        if not _ON_DOWNGRADE_LOGGED:
            _ON_DOWNGRADE_LOGGED = True
            from app.core.structured_logging import FIELDS

            LOGGER.warning("MODEL_GATEWAY=on runs as shadow while V1 does not enforce", extra={FIELDS: {"event": "tutor.v2.on_downgraded"}})
        return "shadow"
    return setting  # type: ignore[return-value]


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    import importlib

    return getattr(importlib.import_module(module_name), name)
