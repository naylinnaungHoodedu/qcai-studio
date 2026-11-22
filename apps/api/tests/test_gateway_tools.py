"""Phase 5 tool contracts for the five MCP servers (plan Phase 5 task 5.2; E-76; E-97; invariant 1; Phase 5 spec 4.6)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.config_package import DEFAULT_PACKAGE_PATH, canonical_sha256, get_config_package
from app.gateway.contracts import PresentationRequest, SpanRef
from app.gateway.tools import SERVERS, TOOL_CONTRACT_VERSION, TOOLS, ToolHost, ToolNotVisible, tool_contract_document
from v1_fakes import dev_pipeline
from v2_fakes import fresh_gateway

PACKAGE = get_config_package(Settings())


def test_the_document_names_the_five_servers_and_their_tools_and_the_committed_file_is_pinned():
    document = tool_contract_document()
    assert document["contract_version"] == TOOL_CONTRACT_VERSION == PACKAGE.tools.version and document["transport"] == "in-process"
    assert tuple(document["servers"]) == SERVERS == ("analytics", "citation", "corpus", "learner", "verification")
    assert sum(len(tools) for tools in document["servers"].values()) == len(TOOLS) == 7
    committed_path = DEFAULT_PACKAGE_PATH.parent / PACKAGE.tools.path
    committed = json.loads(committed_path.read_text(encoding="utf-8"))
    assert committed == document and canonical_sha256(committed) == PACKAGE.tools.sha256


def test_the_learner_server_is_hidden_from_the_evidential_pass_and_every_verifier():
    roles = {tool.name: tool.roles for tool in TOOLS}
    assert "evidential" not in roles["learner.presentation_plan"] and "verifier" not in roles["learner.presentation_plan"]
    assert roles["verification.verdict"] == {"verifier"} and roles["analytics.record_outcome"] == {"ledger"}
    host = ToolHost.default(dev_pipeline(), fresh_gateway())
    for role in ("evidential", "verifier", "ledger"):
        with pytest.raises(ToolNotVisible):
            host.call(role, "learner.presentation_plan", PresentationRequest())
    assert host.call("planner", "learner.presentation_plan", PresentationRequest()).source == "default"
    assert host.call("pedagogical", "learner.presentation_plan", {"hint": "socratic"}).plan_id == "socratic"
    with pytest.raises(ToolNotVisible):
        host.call("evidential", "verification.verdict", {})


def test_inputs_and_outputs_are_validated_and_span_text_reads_the_registry():
    pipeline = dev_pipeline()
    host = ToolHost.default(pipeline, fresh_gateway())
    record = next(iter(pipeline.store.span_registry._by_id.values()))
    text = host.call("verifier", "corpus.span_text", SpanRef(span_id=record.span_id))
    assert (text.span_id, text.text, text.content_hash, text.plane) == (record.span_id, record.text, record.content_hash, "public")
    assert host.call("verifier", "citation.resolve", {"span_id": record.span_id}).resolution in ("resolved", "unresolvable")
    with pytest.raises(ValidationError):
        host.call("verifier", "corpus.span_text", {"span_id": "not-a-span"})
    with pytest.raises(ValidationError):
        host.call("verifier", "corpus.span_text", {"span_id": record.span_id, "learner_id": "x"})
    with pytest.raises(KeyError):
        host.call("verifier", "corpus.unknown", {})
    with pytest.raises(ValueError):
        ToolHost({"corpus.unknown": lambda request: request})
    assert host.calls[("verifier", "corpus.span_text")] == 1
