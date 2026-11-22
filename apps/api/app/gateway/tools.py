"""Versioned tool contracts for the five MCP servers (plan Phase 5 task 5.2; E-76; E-97; VBT RevB p. 8: corpus,
citation, learner, verification and analytics; Phase 5 spec 4.6).

Transport is an implementation choice (plan 5.2): the servers are in-process. The tool names are this phase's own and
provisional (plan 7.4: "tool names are UNVERIFIED / REQUIRES ACCESS [Assumption A-18]"), versioned mcp-tools-v1;
tool_contract_version is stamped on every ledger-entry-v3 record. ToolHost.call refuses a tool its caller's role
cannot see (invariant 1: the learner server is visible only to the planner and the pedagogical pass, never to the
evidential pass or a verifier) and validates each input and output contract. The V2 track builds every claim item's
span text through corpus.span_text and casts every vote through verification.verdict, so every verifier reaches the
same tool surface (E-97). The contract document is committed as config_package/schemas/tool-contracts.v1.json and
package v4 pins its canonical sha256 (tools.sha256).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from app.gateway.contracts import (
    Ack,
    AdapterVerdict,
    AlignmentRequest,
    AlignmentVerdict,
    OutcomeEvent,
    PresentationRequest,
    SpanRef,
    SpanResolution,
    SpanText,
    VerdictRequest,
)
from app.services.tutor_pipeline.contracts import Contract, EvidenceBundle, PresentationPlan, RetrievalRequest

TOOL_CONTRACT_VERSION = "mcp-tools-v1"
SERVERS = ("analytics", "citation", "corpus", "learner", "verification")     # VBT RevB p. 8 (Phase 5 spec M9)
TRANSPORT = "in-process"
Role = Literal["evidential", "pedagogical", "planner", "verifier", "ledger"]
ROLES = ("evidential", "pedagogical", "planner", "verifier", "ledger")


class ToolNotVisible(PermissionError):
    """A role called a tool its server does not expose to it (invariant 1)."""


@dataclass(frozen=True)
class ToolSpec:
    server: str
    name: str
    input_model: type[Contract]
    output_model: type[Contract]
    roles: frozenset[str]


TOOLS = (
    ToolSpec("corpus", "corpus.retrieve", RetrievalRequest, EvidenceBundle, frozenset({"evidential"})),
    ToolSpec("corpus", "corpus.span_text", SpanRef, SpanText, frozenset({"evidential", "verifier"})),
    ToolSpec("citation", "citation.resolve", SpanRef, SpanResolution, frozenset({"evidential", "pedagogical", "verifier"})),
    ToolSpec("learner", "learner.presentation_plan", PresentationRequest, PresentationPlan, frozenset({"planner", "pedagogical"})),
    ToolSpec("verification", "verification.verdict", VerdictRequest, AdapterVerdict, frozenset({"verifier"})),
    ToolSpec("verification", "verification.alignment", AlignmentRequest, AlignmentVerdict, frozenset({"verifier"})),
    ToolSpec("analytics", "analytics.record_outcome", OutcomeEvent, Ack, frozenset({"ledger"})),
)
TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}


def tool_contract_document() -> dict:
    servers: dict[str, dict] = {server: {} for server in SERVERS}
    for tool in TOOLS:
        servers[tool.server][tool.name] = {
            "roles": sorted(tool.roles),
            "input": tool.input_model.model_json_schema(mode="validation"),
            "output": tool.output_model.model_json_schema(mode="validation"),
        }
    return {"contract_version": TOOL_CONTRACT_VERSION, "transport": TRANSPORT, "servers": servers}


class ToolHost:
    """In-process tool servers: one handler per tool name, each a delegation to code that exists."""

    def __init__(self, handlers: dict[str, Callable[..., Any]]) -> None:
        unknown = set(handlers) - set(TOOLS_BY_NAME)
        if unknown:
            raise ValueError(f"no tool contract names {sorted(unknown)}")
        self.handlers = dict(handlers)
        self.calls: Counter = Counter()

    def call(self, role: str, tool: str, payload: Any, **context: Any) -> Any:
        spec = TOOLS_BY_NAME.get(tool)
        if spec is None:
            raise KeyError(f"unknown tool {tool!r}")
        if role not in spec.roles:
            raise ToolNotVisible(f"role {role} cannot see {tool}")
        handler = self.handlers.get(tool)
        if handler is None:
            raise KeyError(f"no handler serves {tool}")
        request = payload if isinstance(payload, spec.input_model) else spec.input_model.model_validate(payload)
        result = handler(request, **context)
        output = result if isinstance(result, spec.output_model) else spec.output_model.model_validate(result)
        self.calls[(role, tool)] += 1
        return output

    @classmethod
    def default(cls, pipeline: Any, gateway: Any) -> "ToolHost":
        """The handlers over one pipeline and one gateway."""
        from app.services.tutor_pipeline.retrieve import retrieve

        def retrieve_tool(request: RetrievalRequest, **_context: Any) -> EvidenceBundle:
            return retrieve(pipeline.engine, request, top_k=pipeline.params.top_k, registry=pipeline.registry)

        def span_text(request: SpanRef, **_context: Any) -> SpanText:
            record = pipeline.store.span_registry.get(request.span_id)
            if record is None:
                raise LookupError("the span does not resolve")
            return SpanText(span_id=record.span_id, text=record.text, content_hash=record.content_hash, plane=record.plane)

        def resolve(request: SpanRef, **_context: Any) -> SpanResolution:
            resolved = pipeline.resolver.resolve_current(request.span_id)
            if resolved is None:
                return SpanResolution(span_id=request.span_id, resolution="unresolvable")
            return SpanResolution(span_id=request.span_id, resolution="resolved", item_id=getattr(resolved, "item_id", None),
                                  content_hash=getattr(resolved, "content_hash", None))

        def presentation(request: PresentationRequest, **_context: Any) -> PresentationPlan:
            if request.hint is not None:
                return PresentationPlan(plan_id=request.hint, source="request")
            return PresentationPlan(plan_id=pipeline.params.default_plan, source="default")

        def verdict(request: VerdictRequest, *, adapter: Any, policy: Any) -> AdapterVerdict:
            return gateway.verify(adapter, request, context=policy)

        def alignment(request: AlignmentRequest, *, adapter: Any, policy: Any) -> AlignmentVerdict:
            return gateway.align(adapter, request, context=policy)

        def record_outcome(request: OutcomeEvent, **_context: Any) -> Ack:
            from app.services.v2_panel.metrics import V2_METRICS

            V2_METRICS.outcome(request)
            return Ack()

        return cls({"corpus.retrieve": retrieve_tool, "corpus.span_text": span_text, "citation.resolve": resolve,
                    "learner.presentation_plan": presentation, "verification.verdict": verdict,
                    "verification.alignment": alignment, "analytics.record_outcome": record_outcome})
