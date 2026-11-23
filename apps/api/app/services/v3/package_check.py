"""Consistency of configuration package v5's v3 block with the V3 code (Phase 6 spec 4.15, 5.3).

Always (start-up, tests, CI): the two committed V3 schema files exist and their canonical sha256 equals the pins; the
trigger registry, the queue reasons, the counting rule and the priority, exposure, claim-set key, K, draw, gold and
stop ids equal the code's. structural=True (tests and scripts/config_package.py --check only): every development
registry entry's fixture file exists under the repository (the API image holds no apps/api/tests/, so start-up never
reads it), and each committed schema equals model_json_schema() of its contract (pydantic is not pinned to a minor
version, so a generated schema never gates start-up). Reads only the package, the committed files beside it and code
values; writes nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPOSITORY_DEPTH = 5  # apps/api/app/services/v3/package_check.py -> the checkout


def _repository_root() -> Path:
    parents = Path(__file__).resolve().parents
    if len(parents) <= REPOSITORY_DEPTH:
        raise FileNotFoundError("no repository checkout holds this module (the API image has none)")
    return parents[REPOSITORY_DEPTH]


def check_v3_package(package: Any, *, structural: bool) -> list[str]:
    if package.v3 is None:
        return ["the configuration package has no v3 block (package v5 is required)"]
    from app.core.config_package import canonical_sha256
    from app.services.v3 import rules
    from app.services.v3.contracts import V3_SCHEMA_MODELS

    v3 = package.v3
    problems: list[str] = []
    committed: dict[str, Any] = {}
    for name, pin in sorted(v3.schemas.items()):
        path = (package.path.parent / pin.path).resolve()
        try:
            committed[name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            problems.append(f"v3.schemas: {pin.path} is missing or not JSON")
            continue
        if canonical_sha256(committed[name]) != pin.sha256:
            problems.append(f"v3.schemas: {pin.path} does not match its pinned sha256 (run scripts/config_package.py --rehash)")
    if set(v3.schemas) != set(V3_SCHEMA_MODELS):
        problems.append("v3.schemas does not name the V3 contracts")
    expected = {
        # Package v6 (Phase 7 spec conflict 3) names x-triggers-v2; v5 keeps x-triggers-v1.
        "version": (v3.version, rules.V3_VERSION),
        "trigger_registry_version": (v3.trigger_registry_version, rules.TRIGGER_REGISTRY_VERSION_V2 if package.schema_version >= 6 else rules.TRIGGER_REGISTRY_VERSION),
        "trigger_rules": (dict(v3.trigger_rules), rules.TRIGGER_RULES_V2 if package.schema_version >= 6 else rules.TRIGGER_RULES), "queue_reasons": (tuple(v3.queue_reasons), rules.QUEUE_REASONS),
        "counted": (tuple(v3.counted), rules.V3_COUNTED), "priority_rule": (v3.priority_rule, rules.PRIORITY_RULE),
        "exposure_rule": (v3.exposure_rule, rules.EXPOSURE_RULE), "claim_set_key_rule": (v3.claim_set_key_rule, rules.CLAIM_SET_KEY_RULE),
        "k_rule": (v3.k_rule, rules.K_RULE), "tie_break": (tuple(v3.tie_break), rules.TIE_BREAK), "draw_rule": (v3.draw_rule, rules.DRAW_RULE),
        "gold_chain": (v3.gold_chain, rules.GOLD_CHAIN), "gold_schema": (v3.gold_schema, rules.GOLD_SCHEMA),
        "gold_record_hash_rule": (v3.gold_record_hash_rule, rules.GOLD_RECORD_HASH_RULE), "stop_tier1": (v3.stop_tier1, rules.STOP_POLICY),
    }
    for name, (value, code) in expected.items():
        if value != code:
            problems.append(f"v3.{name} in the package ({value}) differs from the code's ({code})")
    if structural:
        if v3.critical_registries.get("development"):
            try:
                fixture = _repository_root() / v3.critical_fixture
            except FileNotFoundError:
                fixture = None
            if fixture is None or not fixture.is_file():
                problems.append(f"v3.critical_claims.fixture: {v3.critical_fixture} is missing")
        for name, model in V3_SCHEMA_MODELS.items():
            if name in committed and committed[name] != model.model_json_schema(mode="validation"):
                problems.append(f"v3.schemas: {v3.schemas[name].path} differs from the {name} model (run scripts/config_package.py --write-schemas)")
    return problems
