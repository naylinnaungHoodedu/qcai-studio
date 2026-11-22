"""Consistency of configuration package v4's gateway, v2 and tools blocks with the code (Phase 5 spec 4.17, 5.3).

Always (start-up, tests, CI): the committed tool-contract file exists, its canonical sha256 is tools.sha256 and
tools.version is TOOL_CONTRACT_VERSION; the two prompt hashes are the code's; the voting matrix is the routing table
its routing_table_version names, and the weights, tier rule, alignment rule and panel size are the code's; every fake
rule is wired; the generator families cover WIRED_GENERATORS; the retired settings are the code's. A pinning problem
never reaches this check: the loader refuses it structurally in every build (AC-5-10).

structural=True (tests and scripts/config_package.py --check only): the committed tool-contract file equals
tool_contract_document(). Start-up never compares a generated JSON Schema (pydantic is not pinned to a minor version;
Phase 5 spec M21), so a library update cannot stop a production start-up. Reads only the package, the committed files
beside it and code values; writes nothing.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config_package import ConfigPackage


def tool_contract_path(package: "ConfigPackage"):
    return (package.path.parent / package.tools.path).resolve()


def check_gateway_package(package: "ConfigPackage", *, structural: bool) -> list[str]:
    if package.gateway is None or package.v2 is None or package.tools is None:
        return ["the configuration package has no gateway, v2 or tools block (package v4 is required)"]
    from app.core.config_package import WIRED_GENERATORS, canonical_sha256
    from app.gateway.adapters import WIRED_FAKE_RULES
    from app.gateway.retired import RETIRED_PROVIDER_SETTINGS
    from app.gateway.tools import SERVERS, TOOL_CONTRACT_VERSION, tool_contract_document
    from app.services.v2_panel.rules import (
        ALIGNMENT_RULE_ID,
        MAX_MEMBERS,
        PANEL_WEIGHTS_VERSION,
        ROUTING_TABLES,
        TIER_RULE_ID,
        alignment_prompt_hash,
        verifier_prompt_hash,
    )

    gateway, v2, tools = package.gateway, package.v2, package.tools
    problems: list[str] = []
    committed = None
    try:
        committed = json.loads(tool_contract_path(package).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        problems.append(f"tools: {tools.path} is missing or not JSON")
    if committed is not None and canonical_sha256(committed) != tools.sha256:
        problems.append(f"tools: {tools.path} does not match its pinned sha256 (run scripts/config_package.py --rehash)")
    if tools.version != TOOL_CONTRACT_VERSION or tuple(tools.servers) != SERVERS:
        problems.append("tools: the version or the servers differ from the code's")
    if v2.verifier_prompt_hash != verifier_prompt_hash() or v2.alignment_prompt_hash != alignment_prompt_hash():
        problems.append("v2.prompt: a prompt hash differs from the code's fixed instructions (run scripts/config_package.py --rehash)")
    table = ROUTING_TABLES.get(v2.routing_table_version)
    if table is None or {mode: dict(row) for mode, row in v2.matrix.items()} != table:
        problems.append("v2.voting.matrix is not the routing table its routing_table_version names")
    for name, value, code in (("panel_weights_version", v2.panel_weights_version, PANEL_WEIGHTS_VERSION),
                              ("tiers.rule", v2.tier_rule, TIER_RULE_ID), ("alignment.rule", v2.alignment_rule, ALIGNMENT_RULE_ID),
                              ("panel.max_members", v2.max_members, MAX_MEMBERS)):
        if value != code:
            problems.append(f"v2.{name} in the package ({value}) differs from the code's ({code})")
    for name, members in gateway.registries.items():
        for spec in members:
            if spec.provider == "fake" and spec.fake_rule not in WIRED_FAKE_RULES:
                problems.append(f"gateway.registries.{name}: {spec.adapter_id} names a fake rule that is not wired")
    if not set(WIRED_GENERATORS) <= set(v2.generator_families):
        problems.append("v2.generator_families does not name every wired generator")
    if tuple(gateway.retired_settings) != RETIRED_PROVIDER_SETTINGS:
        problems.append("gateway.retired_settings differ from the code's")
    if structural and committed is not None and committed != tool_contract_document():
        problems.append(f"tools: {tools.path} differs from tool_contract_document() (run scripts/config_package.py --write-schemas)")
    return problems
