"""The provider-neutral model gateway (plan Phase 5; docs/architecture/phase5-implementation-spec.md; ADR-008).

The only package that may make model egress or read a model-provider credential (plan 7.1; R-06): the AST guard of
test_gateway_egress_guard.py refuses a provider SDK or HTTP client import anywhere else in the API image (one recorded
exception: the Phase 2 semantic embedding backend, behind the D-23 opt-in; DI-77) and a provider host name in a
string literal of the Python code under apps/api/app, scripts, evaluation and tools outside this package (the
frontend, infra and the tests are not scanned). D-12 (provider and terms), D-07 (pinned models) and Q-09 (terms)
are open, so no real provider is registered: the staging, production and default registries are empty, and
development registers four deterministic fake families that make no network call. Modules: contracts (the payloads), pinning, registry,
adapters, secrets, egress (D-23), budget, policy (the payload policy), gateway (the process gateway and its stop
guards), tools (the five tool servers' contracts), retired (the retired provider settings), metrics and
package_check. Names are re-exported lazily.
"""

from __future__ import annotations

from typing import Any

# Set (or cleared) by the start-up check (main._check_gateway_package): a reason keeps the V2 mode off and /ready
# reports gateway.available false.
GATEWAY_UNAVAILABLE_REASON: str | None = None

_EXPORTS = {
    "ModelGateway": "app.gateway.gateway",
    "get_gateway": "app.gateway.gateway",
    "reset_process_gateway": "app.gateway.gateway",
    "GatewayRefused": "app.gateway.gateway",
    "GatewayStopped": "app.gateway.gateway",
    "AdapterSpec": "app.gateway.registry",
    "AdapterRegistry": "app.gateway.registry",
    "registry_for": "app.gateway.registry",
    "pin_problem": "app.gateway.pinning",
    "ToolHost": "app.gateway.tools",
}

__all__ = sorted([*_EXPORTS, "GATEWAY_UNAVAILABLE_REASON"])


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    import importlib

    return getattr(importlib.import_module(module_name), name)
