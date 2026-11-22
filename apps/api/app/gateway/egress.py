"""Provider egress opt-in (D-23 RECOMMENDATION: "provider egress needs a per-environment opt-in [Evidence E-109]";
invariant 8; R-10; PD-22; Phase 5 spec 4.3).

A non-fake provider may be called only when the environment's MODEL_EGRESS_PROVIDERS names it; the setting is empty in
every environment, development included. The development fakes make no network call and need none. A refused member
is ineligible and logs gateway.egress_refused once per process and provider (names only).
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from app.core.structured_logging import FIELDS

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config import Settings

LOGGER = logging.getLogger("qcai.gateway")
FAKE_PROVIDER = "fake"
_refused: set[str] = set()
_lock = threading.Lock()


def egress_allowed(settings: "Settings", provider: str) -> bool:
    return provider == FAKE_PROVIDER or provider in (settings.model_egress_providers or [])


def log_refusal(provider: str, adapter_id: str) -> None:
    with _lock:
        if provider in _refused:
            return
        _refused.add(provider)
    LOGGER.warning("Model egress refused: the provider is not opted in for this environment",
                   extra={FIELDS: {"event": "gateway.egress_refused", "provider": provider, "adapter_id": adapter_id}})


def reset_refusal_log() -> None:
    with _lock:
        _refused.clear()
