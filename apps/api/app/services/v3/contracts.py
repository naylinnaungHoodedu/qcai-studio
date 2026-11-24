"""The V3 contracts (plan Phase 6 D tasks 1-4; plan 7.4 AuditEvent and "v3 {trigger (X1-X6), gold_label_id}"; Phase 6
spec 3.1).

Frozen, extra="forbid" (tutor_pipeline.contracts.Contract). A gold label (GoldLabel, v3-gold-label-v1) holds claim and
span ids, sha256 hashes of claim text, enumerations, keyed digests (app.core.client_identity.keyed_digest) of a response
id and of a reviewer, a client key and the package in force: never a learner identifier, learner text, rendered text or
a private-plane span (plan H; E-95). The reviewer's view (QueueItemView) holds public, quotable claim and span text only,
and no vote, objection type, support share, severity, exposure, priority, final or other round's label (blind review,
PD-36). CusumAlarm (cusum-alarm-v1) is the interface through which Phase 9's CUSUM statistic raises an X5 window (DI-96).
V3_SCHEMA_MODELS names the two contracts configuration package v5 pins (v3.schemas). A gold label's reasons include the
ranking fallback's (ranking_empty_eligible_set, package schema 7; Phase 9 spec conflict 24): packages v5 and v6 pin the
schema of the four Phase 6 reasons, which GoldLabelV6Schema reproduces, and package v7 pins the current one
(v3_schema_models picks by the package's schema).
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from app.services.tutor_pipeline.contracts import CLAIM_ID, HEX64, SPAN_ID, Contract

ITEM_ID = r"^v3i-[0-9a-f]{24}$"
DIGEST = r"^[0-9a-f]{32}$"
CLIENT_KEY = r"^[A-Za-z0-9_-]{8,64}$"
UTC_TIME = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$"
Trigger = Literal["X1", "X2", "X3", "X4", "X5", "X6"]
QueueReasonV6 = Literal["v1_3_flag", "v1_8_misconception", "v2_correction_exhausted", "v2_degraded_withheld"]
QueueReason = Literal["v1_3_flag", "v1_8_misconception", "v2_correction_exhausted", "v2_degraded_withheld", "ranking_empty_eligible_set"]


def _sorted_unique(values) -> bool:
    values = list(values)
    return values == sorted(set(values))


class ClaimLabel(Contract):
    claim_id: str = Field(pattern=CLAIM_ID)
    verdict: Literal["SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_INFO"]
    ehmf_type: Literal["A", "B", "C", "D", "E"] | None = None

    @model_validator(mode="after")
    def _ehmf(self) -> "ClaimLabel":
        if (self.ehmf_type is None) != (self.verdict == "SUPPORTED"):
            raise ValueError("a label names an EHMF type exactly when it is not SUPPORTED")
        return self


class AdjudicationRequest(Contract):
    client_key: str = Field(pattern=CLIENT_KEY)
    claim_labels: tuple[ClaimLabel, ...] = Field(default=(), max_length=20)
    abstention_label: Literal["correct", "missed_answer"] | None = None

    @model_validator(mode="after")
    def _sorted(self) -> "AdjudicationRequest":
        if not _sorted_unique(label.claim_id for label in self.claim_labels):
            raise ValueError("claim labels are sorted by claim_id and unique")
        return self


class ApplyRequest(Contract):
    client_key: str = Field(pattern=CLIENT_KEY)


class FlagRequest(Contract):
    response_id: str = Field(pattern=r"^turn-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class GoldClaim(Contract):
    claim_id: str = Field(pattern=CLAIM_ID)
    span_ids: tuple[str, ...] = Field(min_length=1, max_length=12)
    text_sha256: str = Field(pattern=HEX64)


class GoldLabel(Contract):
    gold_schema: Literal["v3-gold-label-v1"] = "v3-gold-label-v1"
    item_id: str = Field(pattern=ITEM_ID)
    review_round: int = Field(ge=1, le=3)
    subject: Literal["claim", "response"]
    triggers: tuple[Trigger, ...] = Field(max_length=6)
    reasons: tuple[QueueReason, ...] = Field(max_length=5)
    ledger_seq: int = Field(ge=1)
    response_digest: str = Field(pattern=DIGEST)
    delivery_digest: str = Field(pattern=DIGEST)
    delivered_answer: bool
    claims: tuple[GoldClaim, ...] = Field(max_length=20)
    claim_labels: tuple[ClaimLabel, ...] = Field(max_length=20)
    abstention_label: Literal["correct", "missed_answer"] | None
    residual_error: bool
    reviewer_digest: str = Field(pattern=DIGEST)
    client_key: str = Field(pattern=CLIENT_KEY)
    package_version: str
    package_sha256: str = Field(pattern=HEX64)
    adjudicated_at: str = Field(pattern=UTC_TIME)

    @model_validator(mode="after")
    def _consistent(self) -> "GoldLabel":
        problems = []
        if not _sorted_unique(self.triggers) or not _sorted_unique(self.reasons):
            problems.append("triggers and reasons are sorted and unique")
        if not self.triggers and not self.reasons:
            problems.append("a gold label names at least one trigger or reason")
        if [label.claim_id for label in self.claim_labels] != [claim.claim_id for claim in self.claims]:
            problems.append("the claim labels name the label's claims, in order")
        if self.subject == "claim" and (len(self.claims) != 1 or self.abstention_label is not None):
            problems.append("a claim label covers exactly one claim and no abstention")
        if self.residual_error != (self.delivered_answer and any(label.verdict != "SUPPORTED" for label in self.claim_labels)):
            problems.append("residual_error is an audited answer delivery with a claim labelled other than SUPPORTED")
        if problems:
            raise ValueError("; ".join(problems))
        return self


class CusumAlarm(Contract):
    alarm_schema: Literal["cusum-alarm-v1"] = "cusum-alarm-v1"
    stream: str = Field(pattern=r"^[a-z0-9][a-z0-9:._-]{0,95}$")
    p0: float = Field(gt=0, lt=1)
    p1: float = Field(gt=0, lt=1)
    h: float = Field(gt=0)
    statistic: float = Field(ge=0)
    observations: int = Field(ge=1)
    raised_at: str = Field(pattern=UTC_TIME)
    source: Literal["phase9-cusum", "synthetic-test"]

    @model_validator(mode="after")
    def _alarm(self) -> "CusumAlarm":
        if not self.p0 < self.p1:
            raise ValueError("an alarm's p0 is below its p1")
        if self.statistic < self.h:
            raise ValueError("an alarm is the statistic crossing h (statistic >= h)")
        return self


class SpanView(Contract):
    span_id: str = Field(pattern=SPAN_ID)
    shown: bool
    text: str | None

    @model_validator(mode="after")
    def _shown(self) -> "SpanView":
        if (self.text is not None) != self.shown:
            raise ValueError("a span's text is set exactly when it is shown")
        return self


class ClaimView(Contract):
    claim_id: str = Field(pattern=CLAIM_ID)
    text: str | None
    spans: tuple[SpanView, ...] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def _hidden(self) -> "ClaimView":
        if self.text is not None and not all(span.shown for span in self.spans):
            raise ValueError("a claim's text is hidden when any of its spans is")
        return self


class QueueItemView(Contract):
    item_id: str = Field(pattern=ITEM_ID)
    subject: Literal["claim", "response"]
    record_kind: Literal["delivery", "shadow"]
    decision: Literal["answer", "abstain"]
    triggers: tuple[Trigger, ...]
    reasons: tuple[QueueReason, ...]
    held: bool
    state: Literal["queued", "claimed", "adjudicated", "applied"]
    review_round: int = Field(ge=1, le=3)
    double_review: bool
    reviewable: bool
    enqueued_at: str = Field(pattern=UTC_TIME)
    age_s: int = Field(ge=0)
    response_digest: str = Field(pattern=DIGEST)
    claims: tuple[ClaimView, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def _reviewable(self) -> "QueueItemView":
        if self.reviewable and any(claim.text is None for claim in self.claims):
            raise ValueError("a reviewable item shows every claim's text")
        return self


# The gold label as packages v5 and v6 pin it (the four Phase 6 queue reasons): used only to check those pins (no docstring:
# it would enter the schema as a description).
class GoldLabelV6Schema(GoldLabel):
    model_config = ConfigDict(title="GoldLabel")
    reasons: tuple[QueueReasonV6, ...] = Field(max_length=4)


V3_SCHEMA_MODELS = {"V3GoldLabel": GoldLabel, "V3CusumAlarm": CusumAlarm}
V3_SCHEMA_MODELS_V6 = {"V3GoldLabel": GoldLabelV6Schema, "V3CusumAlarm": CusumAlarm}


def v3_schema_models(schema_version: int) -> dict:
    """The V3 contracts a package of this schema pins: package v7 (the ranking schema) and later the current ones."""
    from app.core.config_package import RANKING_SCHEMA_VERSION

    return V3_SCHEMA_MODELS if int(schema_version) >= RANKING_SCHEMA_VERSION else V3_SCHEMA_MODELS_V6
