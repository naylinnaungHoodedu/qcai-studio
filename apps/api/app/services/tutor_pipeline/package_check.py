"""Consistency of configuration package v2 with the tutor pipeline code (Phase 3 spec 5.4; conflict 30).

Always (start-up, tests, CI): each pinned schema file exists and its canonical sha256 equals its pin; the three
prompt hashes the code computes equal the pinned values; every rule id and name the package records (sentence,
binding and subset rules, the near-miss rule, the ledger's chain, entry schema, record-hash rule and genesis) equals
the code's (spec 18.8 F4); the generator registry equals WIRED_GENERATORS. The two_pass_tutor defaults in
flag_policy are compared with the code by the loader itself (config_package._parse_flag_policy).

structural=True (tests and scripts/config_package.py --check only): each committed schema has the structure and
the constraints of its pydantic model: property names, the required set, additionalProperties false at every
object (through $defs), and every leaf keyword that constrains a value (type, enum, const, pattern, lengths, bounds,
item counts, defaults; LEAF_KEYWORDS). The sha256 pins cover only the committed files, so this comparison is what
catches a model changed without --write-schemas: a Literal widened, a pattern or a bound changed (spec 18.7 E2).
Only title and description are left out, as annotations. requirements.txt gives pydantic a floor and a major-version
cap, not a pin (spec M21, 18.6 D11), so the comparison still never gates production start-up; the sha256 pins do.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config_package import WIRED_GENERATORS, ConfigPackage, canonical_sha256


def schema_path(package: ConfigPackage, relative: str) -> Path:
    return (package.path.parent / relative).resolve()


# The JSON Schema keywords that constrain a value, compared as they are (spec 18.7 E2). title and description are
# annotations, which pydantic derives from names and docstrings, so they are left out.
LEAF_KEYWORDS = (
    "type", "enum", "const", "pattern", "format",
    "minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minItems", "maxItems", "uniqueItems", "minProperties", "maxProperties", "default",
)


def _leaves(schema: dict[str, Any]) -> dict[str, Any]:
    return {key: schema[key] for key in LEAF_KEYWORDS if key in schema}


def _structure(schema: Any, defs: dict[str, Any], seen: frozenset[str] = frozenset()) -> Any:
    """A comparable skeleton: properties, required, additionalProperties, $ref targets and the leaf constraints
    (LEAF_KEYWORDS), recursively."""
    if isinstance(schema, dict):
        if "$ref" in schema:
            name = str(schema["$ref"]).rsplit("/", 1)[-1]
            reference: dict[str, Any] = {"$ref": name, **_leaves(schema)}
            if name in seen:
                return reference
            return {**reference, "target": _structure(defs.get(name, {}), defs, seen | {name})}
        skeleton: dict[str, Any] = _leaves(schema)
        if schema.get("type") == "object" or "properties" in schema:
            skeleton["properties"] = {key: _structure(value, defs, seen) for key, value in sorted((schema.get("properties") or {}).items())}
            skeleton["required"] = sorted(schema.get("required") or [])
            extra = schema.get("additionalProperties", True)
            skeleton["additionalProperties"] = _structure(extra, defs, seen) if isinstance(extra, dict) else extra
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
        problems.append(f"schema {name}: the committed file's structure differs from the {name} model (a property, the required set or a constraint)")
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
    from app.services.claim_gate import SUBSET_CHECK_RULE
    from app.services.ledger import CHAIN, GENESIS_HASH, RECORD_HASH_RULE
    from app.services.tutor_pipeline.bind import BINDING_RULE
    from app.services.tutor_pipeline.contracts import LedgerEntry
    from app.services.tutor_pipeline.retrieve import NEAR_MISS_RULE
    from app.services.tutor_pipeline.text import SENTENCE_RULE

    # The rule ids and names the package records must be the code's (a rule changed under its old id is a silent
    # change; spec 18.8 F4 added the ledger's chain, entry schema, record-hash rule and genesis, and the near-miss rule).
    rules = {
        "evidential.sentence_rule": (SENTENCE_RULE, params.sentence_rule),
        "evidential.binding_rule": (BINDING_RULE, params.binding_rule),
        "pedagogical.subset_check": (SUBSET_CHECK_RULE, params.subset_check),
        "retrieval.near_miss_rule": (NEAR_MISS_RULE, params.near_miss_rule),
        "ledger.chain": (CHAIN, params.ledger_chain),
        "ledger.entry_schema": (LedgerEntry.model_fields["entry_schema"].default, params.ledger_entry_schema),
        "ledger.record_hash_rule": (RECORD_HASH_RULE, params.record_hash_rule),
        "ledger.genesis": (GENESIS_HASH, params.genesis),
    }
    for name, (code_value, pinned) in rules.items():
        if code_value != pinned:
            problems.append(f"tutor_pipeline.{name} in the package ({pinned}) differs from the code's ({code_value})")
    if set(GENERATORS) != set(WIRED_GENERATORS):
        problems.append("the generator registry differs from WIRED_GENERATORS")
    return problems
