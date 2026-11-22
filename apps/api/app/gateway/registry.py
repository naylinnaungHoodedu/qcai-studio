"""The adapter registry (plan Phase 5 E1 ModelAdapter; task 5.1; Phase 5 spec 3.1, 4.2).

Package v4 holds one registry per environment (gateway.registries): development lists four deterministic fakes, and
staging, production and default are empty (D-07, D-12 and Q-09 open: no model is chosen and no provider is
registered). registry_for picks the registry named by ENVIRONMENT, else default. generator_family names the family of
the package's generator, which the panel excludes (AC-5-1); a generator the package does not name raises
GeneratorFamilyUnknown, and the V2 track then fails closed (no panel, every eligible claim withheld).

Standard library only: the configuration loader builds these from the package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config import Settings
    from app.core.config_package import ConfigPackage

Capability = Literal["generate", "verify"]
CAPABILITIES = ("generate", "verify")
REGISTRY_NAMES = ("development", "staging", "production", "default")
IDENTIFIER = r"^[a-z0-9][a-z0-9-]{1,63}$"
AUTH_HEADERS = ("authorization-bearer", "x-api-key")
MAX_TOKENS = (1, 4096)
TIMEOUT_MS = (50, 10000)
MAX_RETRIES = (0, 2)


class GeneratorFamilyUnknown(LookupError):
    """The package names no family for this generator: no panel can exclude it, so none is built (AC-5-1)."""


@dataclass(frozen=True)
class Caps:
    max_tokens: int        # 1..4096
    timeout_ms: int        # 50..10000; timeout_ms * (1 + max_retries) <= tutor_pipeline.budgets.shadow_ms
    max_retries: int       # 0..2


@dataclass(frozen=True)
class AdapterSpec:         # E1 ModelAdapter {adapter_id, family, provider, model_id, model_version, capabilities, caps}
    adapter_id: str        # [a-z0-9][a-z0-9-]{1,63}
    family: str            # [a-z0-9][a-z0-9-]{1,63}
    provider: str          # "fake" for the development fakes
    model_id: str
    model_version: str     # pinned (4.1)
    capabilities: tuple[Capability, ...]
    caps: Caps
    cost_units_per_call: int          # >= 0; fake units in development
    fake_rule: str | None = None      # e.g. "verbatim-support-v1"; set iff provider == "fake"
    endpoint: str | None = None       # HttpJsonAdapter only: https, no query, no userinfo, no fragment
    auth_header: str | None = None    # "authorization-bearer" | "x-api-key"
    secret_ref: str | None = None     # an environment variable name (Secret Manager mounts); never a value

    def public(self) -> dict:
        """What /ready reports of a member: identifiers only, never an endpoint or a secret reference."""
        return {"adapter_id": self.adapter_id, "family": self.family, "provider": self.provider, "model_id": self.model_id,
                "model_version": self.model_version, "capabilities": list(self.capabilities)}


@dataclass(frozen=True)
class AdapterRegistry:
    name: str                          # "development" | "staging" | "production" | "default"
    members: tuple[AdapterSpec, ...]   # registry order

    def families(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(spec.family for spec in self.members))

    def verifiers(self) -> tuple[AdapterSpec, ...]:
        return tuple(spec for spec in self.members if "verify" in spec.capabilities)


def registry_name(settings: "Settings", registries) -> str:
    name = settings.environment.lower()
    return name if name in registries else "default"


def registry_for(package: "ConfigPackage", settings: "Settings") -> AdapterRegistry:
    """The registry of settings.environment when the package names it, else default; empty without a gateway block."""
    gateway = package.gateway
    if gateway is None:
        return AdapterRegistry(name="default", members=())
    name = registry_name(settings, gateway.registries)
    return AdapterRegistry(name=name, members=tuple(gateway.registries.get(name, ())))


def generator_family(package: "ConfigPackage", registry: AdapterRegistry, generator_id: str) -> str:
    """The family of the generator (package v4 v2.generator_families), or of a registry adapter with capability
    generate whose adapter_id is the generator id; GeneratorFamilyUnknown otherwise."""
    v2 = package.v2
    if v2 is not None and generator_id in v2.generator_families:
        return v2.generator_families[generator_id]
    for spec in registry.members:
        if spec.adapter_id == generator_id and "generate" in spec.capabilities:
            return spec.family
    raise GeneratorFamilyUnknown(f"no family is registered for generator {generator_id!r}")
