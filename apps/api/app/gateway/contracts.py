"""The gateway's request and verdict contracts (plan Phase 5 tasks 5.2, 5.4; AC-5-3; Phase 5 spec 3.1, 4.6).

Two closed request kinds leave the platform, and nothing else (E5):
  VerdictRequest    the claim item: one locked claim's text, one of its bound spans (id and resolved public text) and
                    the fixed instructions. Never the resolved question, another claim, the generator's identity or
                    another member's vote.
  AlignmentRequest  the alignment item: the rendering (locked claim texts and fixed templates), the lesson's authored
                    summary as the objective, and the package's readability band. The only payload holding objective
                    and band.
An adapter projects a provider's output onto AdapterVerdict's or AlignmentVerdict's keys before validation: every
other key, a rationale included, is dropped and never recorded or logged.

The small contracts of the in-process tool servers (SpanRef ... Ack) are here too. Importing this module registers
the four request and verdict models in tutor_pipeline.contracts.SCHEMA_MODELS, whose JSON schemas package v4 pins
(package_check.model_schema imports this module before it reads the registry).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field, model_validator

from app.services.tutor_pipeline.contracts import HEX64, SCHEMA_MODELS, SPAN_ID, Contract, EhmfType
from app.services.ehmf.vocabulary import EHMF_TYPES
from app.services.v2_panel.rules import V2_VERDICTS

V2Verdict = Literal["SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_INFO"]
_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
# A learner identifier (a turn, shadow, Q&A, thread or message id, a bare uuid), an email address, or a bearer
# credential. No shipped corpus text matches (Phase 5 spec M20).
IDENTIFIER_PATTERN = re.compile(rf"(?:\b(?:turn|shadow|qa|thread|message)-)?\b{_UUID}\b|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{{2,}}|\bBearer\b")


def identifier_in(value: Any) -> str | None:
    """The first identifier-like string inside value (recursively), else None."""
    if isinstance(value, str):
        match = IDENTIFIER_PATTERN.search(value)
        return match.group(0) if match else None
    if isinstance(value, dict):
        for item in value.values():
            found = identifier_in(item)
            if found:
                return found
    if isinstance(value, (list, tuple)):
        for item in value:
            found = identifier_in(item)
            if found:
                return found
    return None


class VerdictSpan(Contract):
    span_id: str = Field(pattern=SPAN_ID)
    text: str = Field(min_length=1, max_length=20000)


class VerdictInstructions(Contract):
    prompt_id: Literal["blind-claim-span-v1"] = "blind-claim-span-v1"
    prompt_hash: str = Field(pattern=HEX64)
    verdicts: tuple[V2Verdict, ...] = V2_VERDICTS
    ehmf_types: tuple[EhmfType, ...] = EHMF_TYPES
    tool_contract_version: str


class VerdictRequest(Contract):           # the claim item: claim + one bound span + fixed instructions only (E5)
    request_schema: Literal["v2-verdict-request-v1"] = "v2-verdict-request-v1"
    item: Literal["claim"] = "claim"
    claim_text: str = Field(min_length=1, max_length=2000)
    span: VerdictSpan
    instructions: VerdictInstructions

    @model_validator(mode="after")
    def _no_identifier(self) -> "VerdictRequest":
        if identifier_in(self.claim_text):
            raise ValueError("a claim item never carries a learner identifier")
        return self


class ReadabilityBand(Contract):
    min_grade: float
    max_grade: float


class AlignmentInstructions(Contract):
    prompt_id: Literal["alignment-item-v1"] = "alignment-item-v1"
    prompt_hash: str = Field(pattern=HEX64)
    ratings: tuple[int, ...] = (1, 2, 3, 4, 5)
    tool_contract_version: str


class AlignmentRequest(Contract):         # the alignment item: the only payload holding objective and band (AC-5-3)
    request_schema: Literal["v2-alignment-request-v1"] = "v2-alignment-request-v1"
    item: Literal["alignment"] = "alignment"
    rendered_text: str = Field(min_length=1, max_length=20000)
    objective: str | None = Field(default=None, max_length=4000)
    band: ReadabilityBand
    instructions: AlignmentInstructions


class AdapterVerdict(Contract):           # an adapter projects a provider's output onto these keys before validation
    verdict: V2Verdict
    ehmf_type: EhmfType | None            # None iff verdict == "SUPPORTED"
    span_id: str = Field(pattern=SPAN_ID) # must equal the request's span id

    @model_validator(mode="after")
    def _ehmf_iff_objection(self) -> "AdapterVerdict":
        if (self.ehmf_type is None) != (self.verdict == "SUPPORTED"):
            raise ValueError("an objection names one EHMF type, and SUPPORTED none")
        return self


class AlignmentVerdict(Contract):
    rating: int = Field(ge=1, le=5)
    leakage: bool


# ------------------------------------------------------------------------------------- tool server contracts


class SpanRef(Contract):
    span_id: str = Field(pattern=SPAN_ID)


class SpanText(Contract):
    span_id: str = Field(pattern=SPAN_ID)
    text: str = Field(min_length=1)
    content_hash: str = Field(pattern=HEX64)
    plane: Literal["public"]


class SpanResolution(Contract):
    span_id: str
    resolution: Literal["resolved", "unresolvable"]
    item_id: str | None = None
    content_hash: str | None = None


class PresentationRequest(Contract):
    hint: Literal["concise", "stepwise", "socratic"] | None = None


class OutcomeEvent(Contract):             # enums and counts only
    surface: Literal["two_pass"] = "two_pass"
    final: Literal["deliver", "withhold", "abstain"]
    degraded_mode: Literal["FULL", "REDUCED-2", "REDUCED-1", "ZERO"]
    calls: int = Field(ge=0)
    cost_units: int = Field(ge=0)


class Ack(Contract):
    ok: Literal[True] = True


VERDICT_KEYS = ("verdict", "ehmf_type", "span_id")
ALIGNMENT_KEYS = ("rating", "leakage")

SCHEMA_MODELS.update({
    "V2VerdictRequest": VerdictRequest,
    "V2AlignmentRequest": AlignmentRequest,
    "V2AdapterVerdict": AdapterVerdict,
    "V2AlignmentVerdict": AlignmentVerdict,
})
