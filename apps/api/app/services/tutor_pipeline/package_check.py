"""Consistency of configuration package v2 with the tutor pipeline code (Phase 3 spec 5.4; conflict 30).

Always (start-up, tests, CI): each pinned schema file exists and its canonical sha256 equals its pin; the three
prompt hashes the code computes equal the pinned values; the generator registry equals WIRED_GENERATORS.

structural=True (tests and scripts/config_package.py --check only): each committed schema has the structure of
its pydantic model (property names, required set and additionalProperties false at every object, through $defs).
pydantic is not pinned in requirements.txt (spec M21), so the structural comparison never gates production
start-up; the sha256 pins do.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config_package import WIRED_GENERATORS, ConfigPackage, canonical_sha256


def schema_path(package: ConfigPackage, relative: str) -> Path:
    return (package.path.parent / relative).resolve()


def _structure(schema: Any, defs: dict[str, Any], seen: frozenset[str] = frozenset()) -> Any:
    """A comparable skeleton: properties, required, additionalProperties and $ref targets, recursively."""
    if isinstance(schema, dict):
        if "$ref" in schema:
            name = str(schema["$ref"]).rsplit("/", 1)[-1]
            if name in seen:
                return {"$ref": name}
            return {"$ref": name, "target": _structure(defs.get(name, {}), defs, seen | {name})}
        skeleton: dict[str, Any] = {}
        if schema.get("type") == "object" or "properties" in schema:
            skeleton["properties"] = {key: _structure(value, defs, seen) for key, value in sorted((schema.get("properties") or {}).items())}
            skeleton["required"] = sorted(schema.get("required") or [])
            skeleton["additionalProperties"] = schema.get("additionalProperties", True)
        for key in ("items", "prefixItems", "anyOf", "allOf", "oneOf"):
            if key in schema:
                value = schema[key]
                skeleton[key] = [_structure(item, defs, seen) for item in value] if isinstance(value, list) else _structure(value, defs, seen)
        return skeleton
    if isinstance(schema, list):
        return [_structure(item, defs, seen) for item in schema]
    return schema


def _closed_everywhere(schema: Any, path: str = "$") -> list[str]:
    problems: list[str] = []
    if isinstance(schema, dict):
        # A record (an object with properties) is closed; a map (dict[str, int]) must type its values.
        if "properties" in schema and schema.get("additionalProperties") is not False:
            problems.append(path)
        elif schema.get("type") == "object" and "properties" not in schema and not isinstance(schema.get("additionalProperties"), dict):
            problems.append(path)
        for key, value in schema.items():
            problems.extend(_closed_everywhere(value, f"{path}.{key}"))
    elif isinstance(schema, list):
        for index, value in enumerate(schema):
            problems.extend(_closed_everywhere(value, f"{path}[{index}]"))
    return problems


def model_schema(name: str) -> dict[str, Any]:
    from app.services.tutor_pipeline.contracts import SCHEMA_MODELS

    return SCHEMA_MODELS[name].model_json_schema(mode="validation")


def structural_problems(name: str, committed: dict[str, Any]) -> list[str]:
    generated = model_schema(name)
    problems = []
    if _structure(committed, committed.get("$defs", {})) != _structure(generated, generated.get("$defs", {})):
        problems.append(f"schema {name}: the committed file's structure differs from the {name} model")
    open_objects = _closed_everywhere(committed)
    if open_objects:
        problems.append(f"schema {name}: objects without additionalProperties false at {', '.join(open_objects[:3])}")
    return problems


def check_tutor_pipeline_package(package: ConfigPackage, *, structural: bool) -> list[str]:
    params = package.tutor_pipeline
    if params is None:
        return ["the configuration package has no tutor_pipeline block"]
    from app.services.tutor_pipeline.evidential import GENERATORS, evidential_prompt_hash
    from app.services.tutor_pipeline.render import pedagogical_prompt_hash
    from app.services.tutor_pipeline.resolve import resolver_prompt_hash

    problems: list[str] = []
    for name, pin in sorted(params.schemas.items()):
        path = schema_path(package, pin.path)
        try:
            committed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            problems.append(f"schema {name}: {pin.path} is missing or not JSON")
            continue
        if canonical_sha256(committed) != pin.sha256:
            problems.append(f"schema {name}: {pin.path} does not match its pinned sha256")
        if structural:
            problems.extend(structural_problems(name, committed))
    expected = {
        "resolver": (resolver_prompt_hash(params, package.retrieval), params.resolver_prompt_hash),
        "evidential": (evidential_prompt_hash(params), params.evidential_prompt_hash),
        "pedagogical": (pedagogical_prompt_hash(), params.pedagogical_prompt_hash),
    }
    for name, (computed, pinned) in expected.items():
        if computed != pinned:
            problems.append(f"the {name} prompt hash in the package ({pinned[:12]}) differs from the code's ({computed[:12]})")
    from app.services.tutor_pipeline.bind import BINDING_RULE
    from app.services.tutor_pipeline.text import SENTENCE_RULE

    # The rule ids the package names must be the code's (a rule changed under its old id is a silent change).
    for name, (code_value, pinned) in {"sentence_rule": (SENTENCE_RULE, params.sentence_rule), "binding_rule": (BINDING_RULE, params.binding_rule)}.items():
        if code_value != pinned:
            problems.append(f"tutor_pipeline.evidential.{name} in the package ({pinned}) differs from the code's ({code_value})")
    if set(GENERATORS) != set(WIRED_GENERATORS):
        problems.append("the generator registry differs from WIRED_GENERATORS")
    return problems
