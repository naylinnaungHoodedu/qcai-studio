"""The candidate generators M (spec reading R-a, conflict 2).

M is (i) each static generator the package allows and wires (ranking.models.static: the static assignment
extractive-d19-v1), whose family is v2.generator_families', provider "none", cost 0 and version
"p-" + evidential_prompt_hash[:16] (rule evidential-prompt-hash-16-v1), and (ii) each member of the environment's gateway
registry with capability generate (a development fake while D-12 and D-07 are open). A candidate whose family does not
resolve is never offered (family_unknown).
"""

from __future__ import annotations

from typing import Any

from app.services.ranking.types import ModelRef

STATIC_PROVIDER = "none"


def static_version(prompt_hash: str | None) -> str | None:
    return None if not prompt_hash else "p-" + prompt_hash[:16]


def candidates(package: Any, settings: Any) -> list[ModelRef]:
    from app.gateway.registry import GeneratorFamilyUnknown, generator_family, registry_for

    params = package.ranking
    out: list[ModelRef] = []
    for generator_id in params.static_models:
        family = package.v2.generator_families.get(generator_id)
        if family is None:
            continue
        out.append(ModelRef(generator_id, family, STATIC_PROVIDER, generator_id, static_version(package.tutor_pipeline.evidential_prompt_hash), 0))
    registry = registry_for(package, settings)
    for spec in registry.members:
        if "generate" not in spec.capabilities or spec.adapter_id in params.static_models:
            continue
        try:
            family = generator_family(package, registry, spec.adapter_id)
        except GeneratorFamilyUnknown:
            continue
        out.append(ModelRef(spec.adapter_id, family, spec.provider, spec.model_id, spec.model_version, int(spec.cost_units_per_call)))
    return sorted(out, key=lambda item: item.adapter_id)


def record_version(entry: Any) -> str | None:
    """The version a record's generator ran at: a clone's "<model_id>@<version>" suffix, else the prompt-hash version."""
    model_id = getattr(entry.provenance, "generator_model_id", "") or ""
    if "@" in model_id:
        return model_id.rsplit("@", 1)[1]
    return static_version(getattr(entry.provenance, "evidential_prompt_hash", None))


def model_of_record(entry: Any, known: dict[str, ModelRef]) -> tuple[str | None, str | None]:
    """(adapter id, version) of the record's generator, the id None when it is no candidate."""
    generator_id = getattr(entry.versions, "generator_id", None)
    if generator_id not in known:
        return None, None
    return generator_id, record_version(entry)
