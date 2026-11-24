"""The EHMF operationalization (plan Phase 7; Phase 7 spec 2): the vocabulary, the routing table ehmf-routing-v1,
per-finding typing (classify), conflict precedence and disclosure (conflicts), the detector guard (detectors), the
correction guard (correction), the misconception library v1 (library), the typed record (record), the SLIs (metrics) and
the rising-A/B stop (stop). EHMF runs only in development by default (EHMF shadow) and nothing reaches a learner:
outside development it is off and every learner path is Phase 6's (D-05).

This module imports nothing beyond the standard library at import time (the vocabulary and the routing table are imported
by the record contracts and the configuration-package loader).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config import Settings
    from app.core.config_package import ConfigPackage

# Set at start-up by main._check_ehmf_package when the package's ehmf block fails its check outside a governed build.
EHMF_UNAVAILABLE_REASON: str | None = None


def mode(settings: "Settings", package: "ConfigPackage", *, v2_mode: str | None = None, gateway: Any = None) -> Literal["off", "shadow", "on"]:
    """EHMF's effective mode: off without an ehmf block, when unavailable, when the setting is off or when the V2 mode is
    off (typing needs a V2 track, spec conflict 13); otherwise the setting."""
    if getattr(package, "ehmf", None) is None or EHMF_UNAVAILABLE_REASON is not None:
        return "off"
    setting = getattr(settings, "ehmf", None) or "off"
    if setting == "off":
        return "off"
    if v2_mode is None:
        from app.services import v2_panel

        v2_mode = v2_panel.mode(settings, package, gateway=gateway)
    if v2_mode == "off":
        return "off"
    return setting
