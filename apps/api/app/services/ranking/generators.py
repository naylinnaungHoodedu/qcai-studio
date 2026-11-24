"""Generators for development shadow generation and the shadow regression (spec 4.12).

CloneGenerator is the D-19 extractive generator under a development fake generate member's identity (rule
extractive-clone-v1): the same verbatim claims, its own GeneratorRef (generator_id the adapter id, model_id
"<model_id>@<model_version>", so every clone record names the version it ran at, and a prompt hash over the clone rule
and the package's evidential prompt hash). It is refused unless the member's provider is fake, its fake.generate_rule is
extractive-clone-v1, it can generate and the environment is development. It makes no gateway or network call.
generator_for gives the static generator for a static candidate and a CloneGenerator for a registry candidate.
"""

from __future__ import annotations

from typing import Any

from app.services.ranking.vocabulary import CLONE_RULE


class CloneUnavailable(RuntimeError):
    """A clone is refused: the member is not a development fake generate member with the clone rule."""


def clone_prompt_hash(adapter_id: str, package: Any) -> str:
    from app.core.config_package import canonical_sha256

    return canonical_sha256({"id": adapter_id, "rule": CLONE_RULE, "base": package.tutor_pipeline.evidential_prompt_hash})


class CloneGenerator:
    def __init__(self, spec: Any, package: Any, *, settings: Any) -> None:
        from app.services.tutor_pipeline.contracts import GeneratorRef
        from app.services.tutor_pipeline.evidential import ExtractiveD19Generator

        if (spec.provider != "fake" or getattr(spec, "fake_generate_rule", None) != CLONE_RULE or "generate" not in spec.capabilities
                or settings.environment.lower() != "development"):
            raise CloneUnavailable(f"{spec.adapter_id} is not a development fake generate member with rule {CLONE_RULE}")
        self.inner = ExtractiveD19Generator(package)
        self.ref = GeneratorRef(generator_id=spec.adapter_id, model_id=f"{spec.model_id}@{spec.model_version}", kind="extractive",
                                prompt_hash=clone_prompt_hash(spec.adapter_id, package))

    def propose(self, envelope: Any) -> Any:
        from app.services.tutor_pipeline.contracts import ClaimPlan

        plan = self.inner.propose(envelope)
        return ClaimPlan(generator=self.ref, claims=plan.claims)


def registry_spec(adapter_id: str, *, package: Any, settings: Any) -> Any:
    from app.gateway.registry import registry_for

    for spec in registry_for(package, settings).members:
        if spec.adapter_id == adapter_id:
            return spec
    raise CloneUnavailable(f"{adapter_id} is not a member of the {settings.environment} registry")


def generator_for(model: Any, *, package: Any, settings: Any) -> Any:
    from app.services.tutor_pipeline.evidential import GENERATORS

    if model.adapter_id in package.ranking.static_models:
        return GENERATORS[model.adapter_id](package)
    return CloneGenerator(registry_spec(model.adapter_id, package=package, settings=settings), package, settings=settings)


def clone_rule_of(generator_id: str, *, package: Any, settings: Any) -> str | None:
    """The clone prompt hash a shadow record of this generator must carry, or None when it is no clone member (the ledger's
    provenance audit, spec 4.12)."""
    if package.ranking is None or settings.environment.lower() != "development":
        return None
    try:
        spec = registry_spec(generator_id, package=package, settings=settings)
    except CloneUnavailable:
        return None
    if spec.provider != "fake" or getattr(spec, "fake_generate_rule", None) != CLONE_RULE or "generate" not in spec.capabilities:
        return None
    return clone_prompt_hash(generator_id, package)
