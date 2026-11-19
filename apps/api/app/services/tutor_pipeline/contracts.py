"""The versioned contracts of the two-channel tutor (plan Phase 3 tasks 3.1-3.8; plan 7.4; Phase 3 spec section 3).

Every contract is frozen and refuses unknown fields (extra="forbid"), so a learner-state field can never ride along
on a retrieval request or an evidential envelope (AC-3-1, R-41) and a generator cannot smuggle text past the claim
plan (R-11). The committed JSON schemas (app/config_package/schemas/*.v1.schema.json) are generated from these
models and pinned by sha256 in configuration package v2.

Channels:
- evidential: ResolvedQuestion -> RetrievalRequest -> EvidenceBundle -> EvidentialEnvelope -> ClaimPlan ->
  LockedClaimSet. Nothing here takes a learner input.
- pedagogical: PresentationPlan + LockedClaimSet -> RenderedResponse (typed segments) -> subset check.
- ledger: LedgerEntry, one per response, hash-chained in response_ledger (app/services/ledger.py).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SPAN_ID = r"^span-[0-9a-f]{64}$"
HEX64 = r"^[0-9a-f]{64}$"
CLAIM_ID = r"^claim-[0-9a-f]{32}$"
# turn- a tutor turn (TutorTurn.id); shadow- a two-pass shadow run; qa- a /qa/ask delivery (a random id that names no
# learner; the record matches the asker's Q&A row by its answer hash while that row exists, spec 18.6 D10).
RESPONSE_ID = r"^(turn|shadow|qa)-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

# Phase 4 sets this True together with its V1 module (plan 13.6: nothing whose verification has not completed is
# delivered). While it is False no code path builds a "delivered" ledger entry or returns two-pass text (AC-3-6).
TWO_PASS_DELIVERY_IMPLEMENTED = False

ABSTENTION_REASONS = (
    "no_query_terms",
    "no_match",
    "insufficient_coverage",
    "below_floor",
    "corpus_version_mismatch",
    "no_quotable_evidence",
    "claim_plan_invalid",
    "no_claims",
    "no_bound_claims",
    "subset_check_failed",
    "budget_exceeded",
)
# The legacy contained path's own abstention reason (contained_answers.contain_answer).
LEGACY_ABSTENTION_REASON = "no_approved_span"

# Why a proposed claim is not a locked claim of its own (PipelineCounts.dropped). Every proposed claim is either
# locked or counted under exactly one reason, so proposed_claims == bound_claims + sum(dropped).
BINDING_FAILURES = ("unbound", "outside_bundle", "unresolvable", "not_quotable", "not_verbatim", "duplicate")
# Not binding failures, so the plan L bound-claim ratio treats them apart (bound_claim_ratio_terms):
#   merged           it bound, onto the spans of an earlier claim with the same sentence (bind.py)
#   budget_exceeded  bind never ran: the shadow budget ran out after the generator returned (pipeline.py)
MERGED = "merged"
BUDGET_SKIPPED = "budget_exceeded"
# The legacy contained path: a citation the Phase 2 pipeline produced but could not verify (a binding failure).
LEGACY_UNRESOLVED = "unresolved_citation"
# The legacy contained path: a delivered quotation whose span's derived license class is not public. Its claim is
# kept out of the ledger (no non-public text is ever recorded) and counted; any such count is an upstream breach.
LEGACY_NOT_PUBLIC = "not_public"
DROP_REASONS = (*BINDING_FAILURES, MERGED, BUDGET_SKIPPED, LEGACY_UNRESOLVED, LEGACY_NOT_PUBLIC)

# Field names that would carry learner state. None may appear in a retrieval request or an evidential envelope
# (AC-3-1); the contract tests add each one and expect a refusal.
LEARNER_STATE_FIELDS = (
    "mastery",
    "mastery_band",
    "band",
    "preference",
    "preferences",
    "user_id",
    "learner_id",
    "guest_id",
    "account_id",
    "email",
    "history",
    "page_path",
    "pedagogical_context",
    "learner_state",
    "profile",
    "quiz_attempts",
    "notes",
    "cursor",
    "target_role",
    "focus_area",
    "self_ratings",
    "preferred_pace",
    "presentation",
    "presentation_plan",
    "plan_id",
    "thread_id",
)


def ledger_canonical(value: Any) -> bytes:
    """Canonical JSON bytes: sorted keys, no whitespace, UTF-8, NaN and infinities refused."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_hex(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ------------------------------------------------------------------------------------------------- evidential


class ResolverRef(Contract):
    model_id: str
    prompt_hash: str = Field(pattern=HEX64)


class ResolvedQuestion(Contract):
    """Plan 7.4: built only from the learner's own user turns of one thread (task 3.1)."""

    text: str = Field(min_length=1, max_length=4001)
    resolver: ResolverRef
    source_turn_ids: tuple[str, ...] = Field(min_length=1, max_length=2)
    contains_learner_state: Literal[False] = False


class RetrievalRequest(Contract):
    """Plan 3.2: exactly the resolved text, the lesson scope and the corpus version; no learner field (R-41)."""

    text: str = Field(min_length=1, max_length=4001)
    lesson_slug: str | None = Field(default=None, max_length=255)
    corpus_version: str = Field(min_length=1, max_length=64)


class EvidenceSpan(Contract):
    span_id: str = Field(pattern=SPAN_ID)
    item_id: str
    item_version: str
    kind: Literal["document", "authored"]
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=1)
    content_hash: str = Field(pattern=HEX64)
    # None only on legacy records without a retrieval side channel (the delivered quotations).
    score: float | None
    near_floor: bool
    license_class: Literal["public"]
    # D-19: a public-plane, bound, indexable document span (contained_answers.span_is_quotable).
    quotable: bool


class Sufficiency(Contract):
    score: float | None
    gate: Literal["p1-floor", "bm25f-v1"]
    threshold_version: str
    floor: float
    margin: float
    decision: Literal["answer", "abstain", "near_miss"]
    reason: str


class EvidenceBundle(Contract):
    bundle_schema: Literal["evidence-bundle-v1"] = "evidence-bundle-v1"
    corpus_version: str
    index_version: str
    retrieval_mode: Literal["lexical"]
    spans: tuple[EvidenceSpan, ...] = Field(max_length=12)
    sufficiency: Sufficiency
    conflicts: tuple[str, ...] = ()

    @field_validator("conflicts")
    @classmethod
    def _no_conflicts_before_phase_4(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value:
            raise ValueError("conflict detection (V1.7) is Phase 4; a Phase 3 bundle carries no conflicts")
        return value


class EnvelopeSpan(Contract):
    span_id: str = Field(pattern=SPAN_ID)
    text: str = Field(min_length=1)


class EvidentialInstructions(Contract):
    rule_id: str
    prompt_hash: str = Field(pattern=HEX64)
    max_claims: int = Field(ge=1, le=10)
    max_claims_per_span: int = Field(ge=1, le=10)
    min_sentence_words: int = Field(ge=1, le=50)


class EvidentialEnvelope(Contract):
    """The evidential prompt (F-2): span text only in typed fields, never inside instructions (R-11)."""

    envelope_schema: Literal["evidential-envelope-v1"] = "evidential-envelope-v1"
    question: str = Field(min_length=1, max_length=4001)
    corpus_version: str
    evidence: tuple[EnvelopeSpan, ...] = Field(min_length=1, max_length=12)
    instructions: EvidentialInstructions


class GeneratorRef(Contract):
    generator_id: str
    model_id: str
    kind: Literal["extractive", "generative"]
    prompt_hash: str = Field(pattern=HEX64)


class ProposedClaim(Contract):
    text: str = Field(min_length=1, max_length=2000)
    span_ids: tuple[str, ...] = Field(default=(), max_length=8)


class ClaimPlan(Contract):
    plan_schema: Literal["claim-plan-v1"] = "claim-plan-v1"
    generator: GeneratorRef
    claims: tuple[ProposedClaim, ...] = Field(max_length=20)


class LockedClaim(Contract):
    claim_id: str = Field(pattern=CLAIM_ID)
    # Verbatim, whitespace-normalised corpus text (tutor_pipeline.text.whitespace); never NFKC-folded.
    text: str
    span_ids: tuple[str, ...] = Field(min_length=1)
    source_order: tuple[str, int]


class ConfigStamp(Contract):
    version: str
    sha256: str = Field(pattern=HEX64)


class LockedClaimSetTampered(ValueError):
    """A LockedClaimSet whose claim_set_hash or span set no longer matches its content (a model_copy edit)."""


def lock_hash(locked: "LockedClaimSet") -> str:
    return sha256_hex(ledger_canonical(locked.model_dump(mode="json", exclude={"claim_set_hash"})))


def _lock_problems(locked: "LockedClaimSet") -> list[str]:
    problems = []
    union = sorted({span_id for claim in locked.claims for span_id in claim.span_ids})
    if list(locked.span_ids) != union:
        problems.append("span_ids is not the sorted union of the claims' span ids")
    ids = [claim.claim_id for claim in locked.claims]
    if len(ids) != len(set(ids)):
        problems.append("claim ids are not unique")
    for claim in locked.claims:
        if list(claim.span_ids) != sorted(set(claim.span_ids)):
            problems.append(f"{claim.claim_id} span ids are not sorted and unique")
    if locked.claim_set_hash != lock_hash(locked):
        problems.append("claim_set_hash does not match the locked content")
    return problems


class LockedClaimSet(Contract):
    """Task 3.5: immutable, hashed, stamped. The lock precedes rendering, so no stamp is plan-specific (AC-3-2)."""

    lock_schema: Literal["locked-claim-set-v1"] = "locked-claim-set-v1"
    claims: tuple[LockedClaim, ...]
    span_ids: tuple[str, ...]
    corpus_version: str
    index_version: str
    generator: GeneratorRef | None
    evidential_prompt_hash: str | None
    pedagogical_prompt_hash: str
    resolver: ResolverRef
    config_package: ConfigStamp
    claim_set_hash: str = Field(pattern=HEX64)

    @model_validator(mode="after")
    def _consistent(self) -> "LockedClaimSet":
        problems = _lock_problems(self)
        if problems:
            raise ValueError("; ".join(problems))
        return self


def verify_locked(locked: LockedClaimSet) -> None:
    """Recompute the lock: model_copy(update=...) skips validation, so every consumer re-checks (task 3.5)."""
    problems = _lock_problems(locked)
    if problems:
        raise LockedClaimSetTampered("; ".join(problems))


# ------------------------------------------------------------------------------------------------ pedagogical


class PresentationPlan(Contract):
    plan_id: Literal["concise", "stepwise", "socratic"]
    source: Literal["request", "default"]


class Segment(Contract):
    kind: Literal["connective", "question", "claim", "citation"]
    line: int = Field(ge=0)
    text: str
    template_id: str | None = None
    params: tuple[int, ...] = ()
    claim_id: str | None = None
    span_id: str | None = None


class RenderedResponse(Contract):
    renderer_id: str
    plan_id: str
    attempt: int = Field(ge=1, le=3)
    segments: tuple[Segment, ...]
    citations: tuple[str, ...]
    text: str


# ----------------------------------------------------------------------------------------------------- ledger


class Provenance(Contract):
    """Plan 7.4 provenance. Fields without a Phase 3 value are explicit nulls (Phase 4 and 5 fill them)."""

    generator_model_id: str
    evidential_prompt_hash: str | None
    pedagogical_prompt_hash: str | None
    v1_3_checker_model_id: None = None
    corpus_version: str
    threshold_set_version: str
    panel_weights_version: None = None
    routing_table_version: None = None
    tool_contract_version: None = None


class ClaimLedgerEntry(Contract):
    """Plan 7.4 ClaimLedgerEntry. text is corpus text (a verbatim span sentence or a delivered quotation)."""

    claim_id: str = Field(pattern=CLAIM_ID)
    response_id: str = Field(pattern=RESPONSE_ID)
    text: str
    span_ids: tuple[str, ...] = Field(min_length=1)
    entailment_score: None = None
    locked: Literal[True] = True
    provenance: Provenance


class ResolvedQuestionRef(Contract):
    """The resolved question without its text (no learner text in the ledger)."""

    resolver: ResolverRef
    source_turn_ids: tuple[str, ...]
    contains_learner_state: Literal[False] = False


class RetrievalRecord(Contract):
    corpus_version: str
    index_version: str
    gate: str
    threshold_version: str
    floor: float
    margin: float
    mode: str
    evidence_scope: Literal["retrieved", "delivered_citations"]
    sufficiency: Sufficiency | None
    evidence: tuple[EvidenceSpan, ...]


class PresentationRecord(Contract):
    plan_id: str
    source: str
    renderer_id: str
    attempts: int = Field(ge=1, le=3)
    subset_check: Literal["passed", "failed"]
    # What the passing rendering showed, in render order: the locked claims it rendered and the spans it cited
    # (both empty when no rendering passed). The locked set is LedgerEntry.claims; a renderer may leave a claim out
    # (spec 4.9), so the record never implies that a claim or a citation it did not render was shown.
    rendered_claim_ids: tuple[str, ...] = ()
    rendered_span_ids: tuple[str, ...] = ()


BUDGET_OVERRIDES = ("shadow_ms", "ledger_append_ms")


class BudgetStamp(Contract):
    """The budgets in force for this record (PD-11). They are package values unless TWO_PASS_SHADOW_BUDGET_MS or
    TUTOR_LEDGER_APPEND_BUDGET_MS overrode them, so config_package_sha256 alone does not name them when
    `overridden` is not empty (R-46). shadow_ms is null where no shadow budget applies (a legacy record, an
    unbounded replay run)."""

    shadow_ms: int | None = Field(ge=1)
    ledger_append_ms: int = Field(ge=1)
    overridden: tuple[Literal["shadow_ms", "ledger_append_ms"], ...] = ()


class VersionStamps(Contract):
    pipeline_version: str
    code_sha: str
    schema_revision_expected: str
    config_package_version: str
    config_package_sha256: str
    manifest_sha256: str | None
    span_scheme: str
    policy_version: str
    resolver_id: str | None
    generator_id: str | None
    renderer_id: str | None
    budgets: BudgetStamp


class PipelineCounts(Contract):
    proposed_claims: int = Field(ge=0)
    # The locked claims (len(LedgerEntry.claims) for a two-pass entry).
    bound_claims: int = Field(ge=0)
    dropped: dict[str, int]
    render_attempts: int = Field(ge=0)

    @model_validator(mode="after")
    def _reconciles(self) -> "PipelineCounts":
        unknown = sorted(set(self.dropped) - set(DROP_REASONS))
        if unknown:
            raise ValueError(f"unknown drop reasons {unknown}")
        if any(count < 1 for count in self.dropped.values()):
            raise ValueError("a drop reason is listed only with a positive count")
        if self.proposed_claims != self.bound_claims + sum(self.dropped.values()):
            raise ValueError("proposed_claims must equal bound_claims plus the dropped claims")
        return self


def bound_claim_ratio_terms(counts: PipelineCounts) -> tuple[int, int]:
    """(proposed, bound) for the plan L bound-claim ratio ("Stop if bound-claim ratio falls below Phase 2").

    A claim bind never saw (budget_exceeded) is in neither term: a slow generator is a latency event, not a binding
    failure. A claim merged into an earlier claim on the same sentence did bind, so it is in both.
    """
    skipped = counts.dropped.get(BUDGET_SKIPPED, 0)
    return counts.proposed_claims - skipped, counts.bound_claims + counts.dropped.get(MERGED, 0)


class LedgerEntry(Contract):
    entry_schema: Literal["ledger-entry-v1"] = "ledger-entry-v1"
    response_id: str = Field(pattern=RESPONSE_ID)
    delivery: Literal["shadow", "delivered", "legacy"]
    shadowed_response_id: str | None
    pipeline: Literal["two-pass-v1", "legacy-contained-v1"]
    decision: Literal["answer", "abstain"]
    abstention_reason: str | None
    resolved_question: ResolvedQuestionRef | None
    retrieval: RetrievalRecord
    claim_set_hash: str | None
    claims: tuple[ClaimLedgerEntry, ...]
    span_ids: tuple[str, ...]
    presentation: PresentationRecord | None
    rendered_text_sha256: str | None
    provenance: Provenance
    versions: VersionStamps
    # No V1/V2/V3 verdict exists before Phase 4: such a record reads as "no-verdict".
    verification: None = None
    counts: PipelineCounts

    @model_validator(mode="after")
    def _rules(self) -> "LedgerEntry":
        problems = []
        if self.delivery == "shadow":
            if not self.response_id.startswith("shadow-") or not (self.shadowed_response_id or "").startswith("turn-"):
                problems.append("a shadow record has a shadow- id and names the turn it shadowed")
        elif self.delivery == "legacy":
            # A legacy delivery is a tutor turn (turn-) or a /qa/ask answer (qa-).
            if not self.response_id.startswith(("turn-", "qa-")) or self.shadowed_response_id is not None:
                problems.append("a legacy record has a turn- or qa- id and no shadowed_response_id")
        else:
            if not self.response_id.startswith("turn-") or self.shadowed_response_id is not None:
                problems.append(f"a {self.delivery} record has a turn- id and no shadowed_response_id")
        if self.delivery == "delivered" and not TWO_PASS_DELIVERY_IMPLEMENTED:
            problems.append("delivered two-pass records are refused before the Phase 4 exit (AC-3-6)")
        if (self.decision == "abstain") != (self.abstention_reason is not None):
            problems.append("an abstention, and only an abstention, has an abstention_reason")
        if self.abstention_reason is not None and self.abstention_reason not in (*ABSTENTION_REASONS, LEGACY_ABSTENTION_REASON):
            problems.append(f"unknown abstention_reason {self.abstention_reason!r}")
        if self.decision == "answer" and (not self.claims or self.rendered_text_sha256 is None):
            problems.append("an answer has claims and a rendered_text_sha256")
        union = sorted({span_id for claim in self.claims for span_id in claim.span_ids})
        if list(self.span_ids) != union:
            problems.append("span_ids is not the sorted union of the claims' span ids")
        for claim in self.claims:
            if claim.response_id != self.response_id or claim.provenance != self.provenance:
                problems.append(f"{claim.claim_id} names another response or another provenance")
        if self.counts.bound_claims != len(self.claims):
            problems.append("counts.bound_claims is the number of recorded claims")
        if self.presentation is not None:
            locked_ids = {claim.claim_id for claim in self.claims}
            shown = self.presentation.rendered_claim_ids
            if not set(shown) <= locked_ids or len(shown) != len(set(shown)):
                problems.append("presentation.rendered_claim_ids names a claim that is not a recorded claim, or one twice")
            if not set(self.presentation.rendered_span_ids) <= set(self.span_ids):
                problems.append("presentation.rendered_span_ids names a span that is not a recorded span")
            if self.decision == "answer" and (self.presentation.subset_check != "passed" or not shown or not self.presentation.rendered_span_ids):
                problems.append("an answer's passing rendering shows at least one claim and one citation")
        if problems:
            raise ValueError("; ".join(problems))
        return self


SCHEMA_MODELS: dict[str, type[Contract]] = {
    "ResolvedQuestion": ResolvedQuestion,
    "RetrievalRequest": RetrievalRequest,
    "EvidenceBundle": EvidenceBundle,
    "EvidentialEnvelope": EvidentialEnvelope,
    "ClaimPlan": ClaimPlan,
    "LockedClaimSet": LockedClaimSet,
    "PresentationPlan": PresentationPlan,
    "LedgerEntry": LedgerEntry,
}
# verify_response_ledger dispatches on a row's entry_schema; Phase 4 adds ledger-entry-v2.
ENTRY_SCHEMAS: dict[str, type[LedgerEntry]] = {"ledger-entry-v1": LedgerEntry}
