"""The versioned contracts of the two-channel tutor (plan Phase 3 tasks 3.1-3.8; plan 7.4; Phase 3 spec section 3).

Every contract is frozen and refuses unknown fields (extra="forbid"), so a learner-state field can never ride along
on a retrieval request or an evidential envelope (AC-3-1, R-41) and a generator cannot smuggle text past the claim
plan (R-11). The committed JSON schemas (app/config_package/schemas/: the eight *.v1.schema.json,
ledger-entry.v2.schema.json for LedgerEntryV2, ledger-entry.v3.schema.json for LedgerEntryV3 and ledger-entry.v4.schema.json
for LedgerEntryV4) are generated from these models and pinned by sha256 in the shipped configuration package (v7 since
Phase 9, which pins the same tutor schemas as v6 and, in its v3 block, the gold-label schema with the ranking queue reason;
v6 since Phase 7, which also pins LedgerEntryV4 and the misconception library v1 file; v5 since Phase 6, which pins the same fourteen
schemas as v4 and, in its v3 block, the two V3 contracts of app.services.v3.contracts; v4 since Phase 5, which also pins
the four gateway request and verdict schemas; v3, still readable, pins nine, and v2 the eight v1 schemas).

Channels:
- evidential: ResolvedQuestion -> RetrievalRequest -> EvidenceBundle -> EvidentialEnvelope -> ClaimPlan ->
  LockedClaimSet. Nothing here takes a learner input.
- pedagogical: PresentationPlan + LockedClaimSet -> RenderedResponse (typed segments) -> subset check.
- ledger: LedgerEntry, one per response, hash-chained in response_ledger (app/services/ledger.py); LedgerEntryV2 adds
  the V1 verification (Phase 4), LedgerEntryV3 the V2 panel's verdicts beside it (Phase 5, section "V2").
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

# The Phase 4 exit sets this True together with the delivered two-pass path (DI-59; plan 13.6: nothing whose
# verification has not completed is delivered). V1 runs inside the shadow until then. While it is False no code path
# builds a "delivered" ledger entry or returns two-pass text (AC-3-6).
TWO_PASS_DELIVERY_IMPLEMENTED = False

# Two reasons for an empty evidential envelope (spec 18.11 I1; evidential.no_envelope_reason):
#   no_quotable_evidence  the bundle holds no quotable span: nothing approved under D-31, or the license gate excluded
#                         every result (retrieve.py)
#   no_whole_sentence     it holds quotable spans, but none holds a whole document sentence (spec 18.10 H1), so there
#                         is nothing to quote whole
NO_QUOTABLE_EVIDENCE = "no_quotable_evidence"
NO_WHOLE_SENTENCE = "no_whole_sentence"
# Every render attempt raised (in the renderer, or in the subset check on its output) instead of producing a
# rendering that the subset check could refuse (spec 18.12 J3). Each such attempt logs tutor.two_pass.render_failed;
# subset_check_failed stays for a run in which at least one rendering was checked and every checked one failed.
RENDER_FAILED = "render_failed"
ABSTENTION_REASONS = (
    "no_query_terms",
    "no_match",
    "insufficient_coverage",
    "below_floor",
    "corpus_version_mismatch",
    NO_QUOTABLE_EVIDENCE,
    NO_WHOLE_SENTENCE,
    "claim_plan_invalid",
    "no_claims",
    "no_bound_claims",
    "subset_check_failed",
    RENDER_FAILED,
    "budget_exceeded",
)
# The legacy contained path's own abstention reason (contained_answers.contain_answer). A legacy ledger record keeps
# it when the gate matched passages none of which could be quoted (not approved under D-31, or not verified), and when
# the Phase 4 legacy guard withheld the contained answer (V1.1, V1.2, or V1.7 conflict_withheld; its
# tutor.v1.legacy_guard_withheld line tells the two apart); when the gate itself returned nothing, the record carries
# the gate's reason.
LEGACY_ABSTENTION_REASON = "no_approved_span"
# The Phase 2 retrieval gate's own abstention reasons (lexical_index.Reason without "evidence").
GATE_ABSTENTION_REASONS = ("no_query_terms", "no_match", "insufficient_coverage", "below_floor")

# Why a proposed claim is not a locked claim of its own (PipelineCounts.dropped). Every proposed claim is either
# locked or counted under exactly one reason, so proposed_claims == bound_claims + sum(dropped).
# partial_sentence (spec 18.10 H1): a piece of a cited span's own text that the span cuts out of a longer document
# sentence (it starts or ends at the span's edge), so it is not a whole sentence and never binds.
PARTIAL_SENTENCE = "partial_sentence"
BINDING_FAILURES = ("unbound", "outside_bundle", "unresolvable", "not_quotable", PARTIAL_SENTENCE, "not_verbatim")
# Not binding failures, so the plan L bound-claim ratio treats them apart (bound_claim_ratio_terms):
#   merged           it bound, onto the spans of an earlier claim with the same sentence (bind.py)
#   duplicate        it bound too: its sentence was already bound on every span it cites, so it adds nothing. It
#                    passed every binding check, exactly as a merged claim did, so the ratio counts it as bound, and
#                    two claim plans that lock one claim set give one ratio whatever the order of their claims
#   budget_exceeded  bind never ran: the shadow budget ran out after the generator returned (pipeline.py)
MERGED = "merged"
DUPLICATE = "duplicate"
BUDGET_SKIPPED = "budget_exceeded"
# The legacy contained path: a citation the Phase 2 pipeline produced but could not verify (a binding failure).
LEGACY_UNRESOLVED = "unresolved_citation"
# The legacy contained path: a delivered quotation whose span's derived license class is not public. Its claim is
# kept out of the ledger (no non-public text is ever recorded) and counted; any such count is an upstream breach.
LEGACY_NOT_PUBLIC = "not_public"
DROP_REASONS = (*BINDING_FAILURES, MERGED, DUPLICATE, BUDGET_SKIPPED, LEGACY_UNRESOLVED, LEGACY_NOT_PUBLIC)

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
            raise ValueError("V1.7 (Phase 4) records conflicts on the verification record (DisclosureBlock), never on an evidence bundle")
        return value


class EnvelopeSpan(Contract):
    span_id: str = Field(pattern=SPAN_ID)
    # The span's own characters from its first whole document sentence to its last (bind.whole_sentence_text): a
    # leading or trailing span-edge fragment of a longer sentence is never sent (spec 18.10 H1).
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
    failure. A claim merged into an earlier claim on the same sentence, or a duplicate of one (its sentence already
    bound on every span it cites), passed every binding check, so it is in both: the ratio of a
    locked claim set does not depend on the order in which its claims were proposed.
    """
    skipped = counts.dropped.get(BUDGET_SKIPPED, 0)
    return counts.proposed_claims - skipped, counts.bound_claims + counts.dropped.get(MERGED, 0) + counts.dropped.get(DUPLICATE, 0)


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
        if self.abstention_reason is not None and self.abstention_reason not in ACCEPTED_ABSTENTION_REASONS[self.entry_schema]:
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


# ------------------------------------------------------------------------------------------------- V1 (Phase 4)
#
# Plan Phase 4 D: nine synchronous pre-delivery checks; "HARD = final". The vocabulary below is what every CheckResult
# is validated against, so a check cannot record an outcome its reason does not have (Phase 4 spec 3.1-3.2).

CHECK_IDS = ("V1.1", "V1.2", "V1.3", "V1.4", "V1.5", "V1.6", "V1.7", "V1.8", "V1.9")
CheckId = Literal["V1.1", "V1.2", "V1.3", "V1.4", "V1.5", "V1.6", "V1.7", "V1.8", "V1.9"]
Outcome = Literal["pass", "flag", "hard_fail", "abstain", "mark"]
EhmfType = Literal["A", "B", "C", "D", "E"]
# Plan Phase 4 D table, EHMF column (verbatim), re-exported from ehmf.vocabulary.PLAN_TYPES_BY_CHECK (Phase 7).
from app.services.ehmf.vocabulary import PLAN_TYPES_BY_CHECK as EHMF_BY_CHECK  # noqa: E402 - standard library only
STAGES_BY_CHECK = {"V1.1": ("pre_render",), "V1.2": ("pre_render",), "V1.3": ("pre_render",), "V1.4": ("post_render",),
                   "V1.5": ("pre_render",), "V1.6": ("post_render",), "V1.7": ("pre_render",), "V1.8": ("pre_render",),
                   "V1.9": ("pre_render", "post_render")}
SUBSET_PROBLEM_CODES = ("empty", "text_not_segments", "unmapped_factual_sentence", "duplicate_claim", "citation_outside_locked_set",
                        "citation_not_on_claim", "citation_marker_mismatch", "no_claim_rendered", "claim_uncited",
                        "citation_list_mismatch")   # == claim_gate.PROBLEM_CODES (package_check and a test compare)
# V1.2's polarity drop codes: a claim whose bind passed but whose quantities or negation cues differ from its span.
V1_DROP_REASONS = ("quantity_mismatch", "negation_mismatch")
# Every claim of a final candidate V1.1 hard-failed: V1.1 judges the candidate whole, so none of its claims is bound
# (an enforce record's counts; Phase 3 counts the same plan per claim, as outside_bundle).
UNRESOLVABLE_CANDIDATE = "unresolvable_citation"
V1_COUNT_REASONS = (*V1_DROP_REASONS, UNRESOLVABLE_CANDIDATE)
REASON_OUTCOMES: dict[str, dict[str, str]] = {
    "V1.1": {"resolved": "pass", "unresolvable": "hard_fail", "malformed_span_id": "hard_fail", "content_hash_mismatch": "hard_fail"},
    "V1.2": {"bound": "pass", "merged": "pass", "duplicate": "pass", **{code: "hard_fail" for code in BINDING_FAILURES},
             **{code: "hard_fail" for code in V1_DROP_REASONS}, "no_bound_claims": "abstain"},
    "V1.3": {"supported": "pass", "no_checker": "flag", "not_enough_info": "flag", "contradicted": "flag",
             "below_support_threshold": "flag", "checker_unavailable": "abstain"},
    "V1.4": {"mapped": "pass", "render_failed": "hard_fail", **{code: "hard_fail" for code in SUBSET_PROBLEM_CODES}},
    "V1.5": {"answer": "pass", "near_miss": "mark", **{code: "abstain" for code in (*GATE_ABSTENTION_REASONS, "corpus_version_mismatch",
                                                                                  NO_QUOTABLE_EVIDENCE)}},
    "V1.6": {"not_assessment": "pass", "key_absent": "pass", "short_key_unmatchable": "pass", "keyed_answer_present": "hard_fail"},
    "V1.7": {"no_conflict": "pass", "conflict_disclosed": "flag", "conflict_withheld": "flag"},
    "V1.8": {"no_match": "pass", "misconception_match": "flag"},
    "V1.9": {"schema_valid": "pass", "claim_plan_invalid": "hard_fail", "generator_mismatch": "hard_fail",
             "response_envelope_invalid": "hard_fail", "within_band": "pass", "below_band": "flag", "above_band": "flag"},
}
# Abstention reasons only an enforce-mode V1 decision gives (LedgerEntryV2 accepts them; ABSTENTION_REASONS is unchanged).
V1_ABSTENTION_REASONS = ("unresolvable_citation", "checker_unavailable", "keyed_answer_leak", "readability_out_of_band",
                         "response_envelope_invalid")
V1_WITHHOLD_REASONS = ("d20_interim_withhold", "conflict_withheld")
ACCEPTED_ABSTENTION_REASONS = {
    "ledger-entry-v1": (*ABSTENTION_REASONS, LEGACY_ABSTENTION_REASON),
    "ledger-entry-v2": (*ABSTENTION_REASONS, LEGACY_ABSTENTION_REASON, *V1_ABSTENTION_REASONS),
}
# The final reasons a Phase 4 VerificationRecord accepts (VerificationRecordV2 adds V2's).
PHASE4_FINAL_REASONS = (*ABSTENTION_REASONS, *V1_ABSTENTION_REASONS, *V1_WITHHOLD_REASONS)
# Claim-scoped results: these checks judge one claim (claim_id set), except the response-level reasons listed.
_CLAIM_SCOPED = {"V1.2": ("no_bound_claims",), "V1.3": ("checker_unavailable",), "V1.8": ()}
_RESPONSE_SCOPED = ("V1.1", "V1.4", "V1.5", "V1.6", "V1.7", "V1.9")
# A delivered claim's own results may hold only these outcomes, besides V1.7's labelling flags (spec 3.2, conflict 32).
DELIVERABLE_OUTCOMES = ("pass", "mark")


def _sorted_unique(values: tuple[str, ...]) -> bool:
    return list(values) == sorted(set(values))


class CheckResult(Contract):
    check_id: CheckId
    stage: Literal["pre_render", "post_render"]
    attempt: int = Field(ge=1, le=3)
    outcome: Outcome
    ehmf_types: tuple[EhmfType, ...]
    reason_code: str
    claim_id: str | None = Field(default=None, pattern=CLAIM_ID)
    checker_model_id: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "CheckResult":
        problems = []
        outcomes = REASON_OUTCOMES[self.check_id]
        if self.reason_code not in outcomes:
            problems.append(f"{self.check_id} has no reason {self.reason_code!r}")
        elif outcomes[self.reason_code] != self.outcome:
            problems.append(f"{self.check_id} {self.reason_code} is outcome {outcomes[self.reason_code]}, not {self.outcome}")
        if self.ehmf_types != EHMF_BY_CHECK[self.check_id]:
            problems.append(f"{self.check_id} EHMF types are {EHMF_BY_CHECK[self.check_id]}")
        if self.stage not in STAGES_BY_CHECK[self.check_id]:
            problems.append(f"{self.check_id} does not run at {self.stage}")
        if (self.checker_model_id is not None) != (self.check_id == "V1.3"):
            problems.append("checker_model_id is set on V1.3 results only")
        if self.check_id in _CLAIM_SCOPED:
            response_level = self.reason_code in _CLAIM_SCOPED[self.check_id]
            if response_level and self.claim_id is not None:
                problems.append(f"{self.check_id} {self.reason_code} is a response-level result (no claim_id)")
            if not response_level and self.claim_id is None:
                problems.append(f"{self.check_id} {self.reason_code} names its claim")
        elif self.claim_id is not None:
            problems.append(f"{self.check_id} results are response-level (no claim_id)")
        if problems:
            raise ValueError("; ".join(problems))
        return self


class V3Intent(Contract):
    queue: Literal["pending_v3"] = "pending_v3"
    reasons: tuple[Literal["v1_3_flag", "v1_8_misconception", "x4_margin"], ...] = Field(min_length=1)
    trigger: Literal["X4"] | None = None
    gold_label_id: None = None

    @model_validator(mode="after")
    def _consistent(self) -> "V3Intent":
        if not _sorted_unique(self.reasons):
            raise ValueError("V3 intent reasons are sorted and unique")
        if (self.trigger == "X4") != ("x4_margin" in self.reasons):
            raise ValueError("the X4 trigger is set exactly when x4_margin is a reason")
        return self


class ConflictPair(Contract):
    kind: Literal["version_of_same_asset", "number_disagreement", "negation_disagreement"]
    span_ids: tuple[str, ...] = Field(min_length=2, max_length=12)
    item_ids: tuple[str, str]
    claim_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> "ConflictPair":
        if not _sorted_unique(self.span_ids) or not _sorted_unique(self.claim_ids):
            raise ValueError("a conflict's span_ids and claim_ids are sorted and unique")
        if list(self.item_ids) != sorted(self.item_ids) or self.item_ids[0] == self.item_ids[1]:
            raise ValueError("a conflict names two distinct items, sorted")
        return self


class DisclosureBlock(Contract):
    block_schema: Literal["conflict-disclosure-v1"] = "conflict-disclosure-v1"
    policy: Literal["disclose", "withhold"]
    conflicts: tuple[ConflictPair, ...] = Field(min_length=1, max_length=20)


class ClaimVerdict(Contract):
    claim_id: str = Field(pattern=CLAIM_ID)
    v1: tuple[CheckResult, ...]
    v2: None = None
    v3: V3Intent | None = None
    final: Literal["deliver", "correct", "withhold", "abstain"]
    cycle_count: int = Field(ge=0, le=4)


class V1Policy(Contract):
    rules_version: str
    rules_hash: str = Field(pattern=HEX64)
    checker_hosting: str = Field(min_length=1, max_length=64)
    checker_model_id: str = Field(min_length=1, max_length=128)
    misconception_library_version: str
    misconception_library_sha256: str = Field(pattern=HEX64)
    d20_interim: Literal["withhold-all-flagged-v1"]


class V1Comparison(Contract):
    phase3_decision: Literal["answer", "abstain"] | None
    legacy_decision: Literal["answer", "abstain"] | None
    v1_outcome: Literal["answer", "abstain"]
    agrees_phase3: bool | None
    agrees_legacy: bool | None


def _deliverable(result: CheckResult) -> bool:
    """A delivered claim's own V1 results: pass or mark, and V1.7's labelling flags (a disclosed conflict is
    deliverable; a withheld one names its claims, which the withheld-conflict rule refuses separately)."""
    return result.outcome in DELIVERABLE_OUTCOMES or result.check_id == "V1.7"


class VerificationRecord(Contract):
    verification_schema: Literal["v1-verification-v1"] = "v1-verification-v1"
    mode: Literal["shadow", "enforce"]
    policy: V1Policy
    generation_attempts: int = Field(ge=0, le=3)
    render_attempts: int = Field(ge=0, le=3)
    cycle_count: int = Field(ge=0, le=4)
    claim_set_hash: str | None = Field(default=None, pattern=HEX64)
    checks: tuple[CheckResult, ...] = Field(max_length=256)
    verdicts: tuple[ClaimVerdict, ...] = Field(max_length=20)
    labels: tuple[Literal["near_floor", "conflict_disclosed"], ...] = ()
    disclosure: DisclosureBlock | None = None
    final: Literal["deliver", "correct", "withhold", "abstain"]
    final_reason: str | None
    replacement: Literal["extractive_d19", "abstention", "unknown", "none"]
    hard_fail: bool
    comparison: V1Comparison

    @model_validator(mode="after")
    def _rules(self) -> "VerificationRecord":
        problems = verification_problems(self)
        if problems:
            raise ValueError("; ".join(problems))
        return self


def _never(verdict: ClaimVerdict) -> bool:
    return False


def verification_problems(record: VerificationRecord, *, v1_3_routed=_never, claim_abstains_alone=_never,
                          final_reasons: tuple[str, ...] = PHASE4_FINAL_REASONS) -> list[str]:
    """The rules every verification record keeps (Phase 4 spec 3.3; Phase 5 spec 3.3). With the default parameters they
    are Phase 4's exactly. VerificationRecordV2 under MODEL_GATEWAY=on passes three: v1_3_routed (a delivered claim may
    hold a V1.3 flag when its V2 vote passed: "after Phase 5, flags route to V2"), claim_abstains_alone (a claim
    abstained with escalation X2 may abstain in a response that does not) and final_reasons (V2's reasons too)."""
    problems = []
    cycles = max(record.generation_attempts - 1, 0) + max(record.render_attempts - 1, 0)
    if record.cycle_count != cycles or any(verdict.cycle_count != cycles for verdict in record.verdicts):
        problems.append("cycle_count is the regenerations made (generation and render), on the record and on every verdict")
    if record.final == "correct":
        problems.append("a record never ends in 'correct': a correction is a new candidate (Phase 4 R-d)")
    if (record.final == "withhold") != (record.replacement != "none"):
        problems.append("a withheld response, and only one, names its replacement")
    if record.final == "withhold":
        expected = {"answer": "extractive_d19", "abstain": "abstention", None: "unknown"}[record.comparison.legacy_decision]
        if record.replacement != expected:
            problems.append(f"a withheld response's replacement follows the legacy decision ({expected})")
    finals = [verdict.final for verdict in record.verdicts]
    if record.final == "deliver" and "deliver" not in finals:
        problems.append("a delivered response delivers at least one claim")
    if record.final == "withhold" and (not finals or "deliver" in finals):
        problems.append("a withheld response has claims and delivers none")
    if record.final == "abstain" and any(final != "abstain" for final in finals):
        problems.append("an abstention abstains on every claim")
    if record.final != "abstain" and any(verdict.final == "abstain" and not claim_abstains_alone(verdict) for verdict in record.verdicts):
        problems.append("a claim abstains only when the response abstains")
    if record.hard_fail and record.final != "abstain":
        problems.append("a V1 hard fail is final: the response abstains")
    if (record.final_reason is None) != (record.final == "deliver"):
        problems.append("every response but a delivered one has a final_reason")
    if record.final_reason is not None and record.final_reason not in final_reasons:
        problems.append(f"unknown final_reason {record.final_reason!r}")
    for verdict in record.verdicts:
        routed = v1_3_routed(verdict)
        if verdict.final == "deliver" and not all(_deliverable(result) or (routed and result.check_id == "V1.3" and result.outcome == "flag")
                                                  for result in verdict.v1):
            problems.append(f"{verdict.claim_id} is delivered despite a V1 result that is not pass (invariant 6; 13.6)")
    if record.disclosure is not None and record.disclosure.policy == "withhold":
        named = {claim_id for pair in record.disclosure.conflicts for claim_id in pair.claim_ids}
        if any(verdict.final == "deliver" and verdict.claim_id in named for verdict in record.verdicts):
            problems.append("a claim of a withheld conflict is never delivered")
    disclosed = record.disclosure is not None and record.disclosure.policy == "disclose"
    if ("conflict_disclosed" in record.labels) != disclosed:
        problems.append("the conflict_disclosed label is set exactly when a disclosure block is disclosed")
    marked = any(result.check_id == "V1.5" and result.outcome == "mark" for result in record.checks)
    if ("near_floor" in record.labels) != marked:
        problems.append("the near_floor label is set exactly when V1.5 marked the response")
    if record.comparison.v1_outcome != ("abstain" if record.final == "abstain" else "answer"):
        problems.append("comparison.v1_outcome is abstain exactly when the response abstains")
    for reference, agrees in ((record.comparison.phase3_decision, record.comparison.agrees_phase3),
                              (record.comparison.legacy_decision, record.comparison.agrees_legacy)):
        if (reference is None) != (agrees is None) or (reference is not None and agrees != (reference == record.comparison.v1_outcome)):
            problems.append("each comparison agrees_* is null exactly when its reference is, else reference == v1_outcome")
    return problems


class ProvenanceV2(Provenance):
    v1_3_checker_model_id: str = Field(min_length=1, max_length=128)


class ClaimLedgerEntryV2(ClaimLedgerEntry):
    entailment_score: float | None = Field(default=None, ge=0.0, le=1.0)
    provenance: ProvenanceV2


class PipelineCountsV2(PipelineCounts):
    """PipelineCounts that also accept V1's own reasons (V1_COUNT_REASONS: V1.2's polarity drops, and a V1.1
    hard-failed candidate's claims); the arithmetic rule is unchanged."""

    @model_validator(mode="after")
    def _reconciles(self) -> "PipelineCountsV2":
        unknown = sorted(set(self.dropped) - set(DROP_REASONS) - set(V1_COUNT_REASONS))
        if unknown:
            raise ValueError(f"unknown drop reasons {unknown}")
        if any(count < 1 for count in self.dropped.values()):
            raise ValueError("a drop reason is listed only with a positive count")
        if self.proposed_claims != self.bound_claims + sum(self.dropped.values()):
            raise ValueError("proposed_claims must equal bound_claims plus the dropped claims")
        return self


class LedgerEntryV2(LedgerEntry):
    entry_schema: Literal["ledger-entry-v2"] = "ledger-entry-v2"
    claims: tuple[ClaimLedgerEntryV2, ...]
    provenance: ProvenanceV2
    verification: VerificationRecord
    counts: PipelineCountsV2

    @model_validator(mode="after")
    def _v1_rules(self) -> "LedgerEntryV2":
        problems = []
        verification = self.verification
        if self.delivery != "shadow":
            problems.append("only shadow records carry a V1 verification before the Phase 4 exit (DI-59)")
        checker = verification.policy.checker_model_id
        if self.provenance.v1_3_checker_model_id != checker:
            problems.append("provenance.v1_3_checker_model_id is the policy's checker")
        if any(result.check_id == "V1.3" and result.checker_model_id != checker for result in verification.checks):
            problems.append("every V1.3 result names the policy's checker")
        if (checker == "none" or verification.mode == "shadow") and any(claim.entailment_score is not None for claim in self.claims):
            problems.append("an entailment_score is recorded only from a real checker in enforce mode")
        if verification.mode == "enforce":
            if (self.decision == "abstain") != (verification.final == "abstain"):
                problems.append("in enforce, the record abstains exactly when V1 does")
            if [verdict.claim_id for verdict in verification.verdicts] != [claim.claim_id for claim in self.claims]:
                problems.append("in enforce, the verdicts name the recorded claims, in order")
            if verification.claim_set_hash != self.claim_set_hash:
                problems.append("in enforce, the verification names the recorded claim set")
        else:
            if verification.comparison.phase3_decision != self.decision:
                problems.append("in shadow, the record is the Phase 3 decision and the comparison names it")
            if self.abstention_reason is not None and self.abstention_reason not in (*ABSTENTION_REASONS, LEGACY_ABSTENTION_REASON):
                problems.append("in shadow, the abstention reason is a Phase 3 reason")
            if set(self.counts.dropped) & set(V1_COUNT_REASONS):
                problems.append("in shadow, the counts are the Phase 3 composition's (no V1 count reason)")
        if problems:
            raise ValueError("; ".join(problems))
        return self


SCHEMA_MODELS["LedgerEntryV2"] = LedgerEntryV2
# verify_response_ledger, export and restore dispatch on a row's entry_schema.
ENTRY_SCHEMAS: dict[str, type[LedgerEntry]] = {"ledger-entry-v1": LedgerEntry, "ledger-entry-v2": LedgerEntryV2}


# ------------------------------------------------------------------------------------------------- V2 (Phase 5)
#
# Plan 7.4's v2 verdict {tier, rule, generator_family, votes[] {verifier_model_id, family, verifier_prompt_hash, verdict,
# ehmf_type, span_id}, blind: true}, additive: VerificationRecordV2 and LedgerEntryV3 extend the Phase 4 classes, whose
# fields are unchanged (Phase 5 spec 3.3). Votes add the verifier's model version and a cache flag (conflict 17).

from app.services.v2_panel.rules import (  # noqa: E402 - standard library only, after the Phase 4 section it extends
    BANNER_FOR_MODE,
    MAX_CORRECTION_CYCLES,
    ROUTING_TABLES,
    V2_ABSTENTION_REASONS,
    V2_WITHHOLD_REASONS,
)
from app.services.v2_panel.voting import family_verdict, is_split, mode_for, objections, tally  # noqa: E402

V2_FINAL_REASONS = (*PHASE4_FINAL_REASONS, *V2_ABSTENTION_REASONS, *V2_WITHHOLD_REASONS)
_V1_REASONS = (*ABSTENTION_REASONS, *V1_ABSTENTION_REASONS)


class V2Vote(Contract):                       # plan 7.4 votes[] plus model version and cache flag
    verifier_model_id: str
    verifier_model_version: str
    family: str
    verifier_prompt_hash: str = Field(pattern=HEX64)
    verdict: Literal["SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_INFO"]
    ehmf_type: EhmfType | None                # None iff SUPPORTED
    span_id: str = Field(pattern=SPAN_ID)
    cached: bool

    @model_validator(mode="after")
    def _ehmf(self) -> "V2Vote":
        if (self.ehmf_type is None) != (self.verdict == "SUPPORTED"):
            raise ValueError("a vote names an EHMF type exactly when it objects")
        return self


class V2ClaimVerdict(Contract):               # plan 7.4 v2 {tier, rule, generator_family, votes[], blind: true}
    tier: Literal[1, 2, 3]
    rule: Literal["1oo3", "2oo3", "1oo2", "equal-weights-share-v1", "withhold-queue-v3"]
    generator_family: str
    mode: Literal["FULL", "REDUCED-2", "REDUCED-1", "ZERO"]
    members: tuple[str, ...] = Field(max_length=3)     # the families eligible for this claim's tally, sorted
    votes: tuple[V2Vote, ...] = Field(max_length=24)   # sorted by (family, span_id)
    blind: Literal[True] = True
    objections: int = Field(ge=0, le=3)
    split: bool
    outcome: Literal["pass", "fail", "withheld"]
    critical: bool = False
    cycle: int = Field(ge=0, le=2)

    @model_validator(mode="after")
    def _consistent(self) -> "V2ClaimVerdict":
        problems = []
        if self.generator_family in self.members:
            problems.append("a claim's panel never holds the generator's family (AC-5-1)")
        if not _sorted_unique(self.members):
            problems.append("the members are sorted and unique")
        if any(vote.family not in self.members for vote in self.votes):
            problems.append("every vote is a member family's")
        keys = [(vote.family, vote.span_id) for vote in self.votes]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            problems.append("one vote per family and span, sorted (AC-5-2)")
        if problems:
            raise ValueError("; ".join(problems))
        return self


class AlignmentVote(Contract):
    verifier_model_id: str
    verifier_model_version: str
    family: str
    verifier_prompt_hash: str = Field(pattern=HEX64)
    rating: int = Field(ge=1, le=5)
    leakage: bool


class V2Alignment(Contract):
    rule: Literal["1ooN-leakage-v1"] = "1ooN-leakage-v1"
    members: tuple[str, ...] = Field(max_length=3)
    votes: tuple[AlignmentVote, ...] = Field(max_length=3)
    rendered_text_sha256: str = Field(pattern=HEX64)   # the rendering judged
    outcome: Literal["pass", "fail"]

    @model_validator(mode="after")
    def _consistent(self) -> "V2Alignment":
        if [vote.family for vote in self.votes] != list(self.members) or not _sorted_unique(self.members):
            raise ValueError("the alignment votes are one per member family, sorted")
        if (self.outcome == "fail") != any(vote.leakage for vote in self.votes):
            raise ValueError("the alignment item fails exactly when a member flags leakage (1ooN-leakage-v1)")
        return self


class V2Correction(Contract):
    cycle: int = Field(ge=1, le=2)
    kind: Literal["revise", "re_render"]
    failed_claim_ids: tuple[str, ...]          # sorted, claim-id pattern
    revised_claim_ids: tuple[str, ...] = ()    # the failed claims whose text the generator changed

    @model_validator(mode="after")
    def _consistent(self) -> "V2Correction":
        import re

        if not _sorted_unique(self.failed_claim_ids) or not _sorted_unique(self.revised_claim_ids):
            raise ValueError("the correction's claim ids are sorted and unique")
        if any(not re.fullmatch(CLAIM_ID, claim_id) for claim_id in (*self.failed_claim_ids, *self.revised_claim_ids)):
            raise ValueError("a correction names claim ids")
        if not set(self.revised_claim_ids) <= set(self.failed_claim_ids) or (self.kind == "re_render" and self.revised_claim_ids):
            raise ValueError("only failed claims are revised, and a re-render revises none")
        return self


class V2ShadowSummary(Contract):              # mode "shadow" only: what "on" would decide without correction
    would_deliver: int = Field(ge=0)
    would_fail: int = Field(ge=0)
    would_withhold: int = Field(ge=0)


class V2Block(Contract):
    block_schema: Literal["v2-panel-v1"] = "v2-panel-v1"
    mode: Literal["shadow", "on"]
    panel_reached: bool                       # the hook was consulted on at least one V1Passed candidate of this response
    gateway_state: Literal["open", "stopped"]
    registry: str
    generator_family: str
    members: tuple[str, ...] = Field(max_length=3)     # the panel at the start of the response, sorted
    degraded_mode: Literal["FULL", "REDUCED-2", "REDUCED-1", "ZERO"]   # the worst mode of a recorded claim verdict, FULL if none
    panel_weights_version: str
    routing_table_version: str
    tool_contract_version: str
    verifier_prompt_hash: str = Field(pattern=HEX64)
    alignment_prompt_hash: str = Field(pattern=HEX64)
    alignment: V2Alignment | None
    cycles: int = Field(ge=0, le=2)
    corrections: tuple[V2Correction, ...] = Field(max_length=2)
    calls: int = Field(ge=0)
    cache_hits: int = Field(ge=0)
    cost_units: int = Field(ge=0)
    kill_switch: Literal["none", "abstain_only", "pre_verified_only"]
    banner: Literal["degraded-reduced-2-v1", "degraded-reduced-1-v1", "degraded-zero-v1"] | None
    shadow: V2ShadowSummary | None


class V3IntentV2(V3Intent):
    reasons: tuple[Literal["v1_3_flag", "v1_8_misconception", "x4_margin", "v2_correction_exhausted", "v2_degraded_withheld"], ...] = Field(min_length=1)
    escalation: Literal["X2"] | None = None    # X2 iff "v2_correction_exhausted" in reasons

    @model_validator(mode="after")
    def _escalation(self) -> "V3IntentV2":
        if (self.escalation == "X2") != ("v2_correction_exhausted" in self.reasons):
            raise ValueError("the X2 escalation is set exactly when v2_correction_exhausted is a reason")
        return self


class ClaimVerdictV2(ClaimVerdict):
    v2: V2ClaimVerdict | None = None
    v3: V3IntentV2 | None = None


def _v2_vote_problems(record: "VerificationRecordV2", verdict: ClaimVerdictV2) -> list[str]:
    """What in one claim's V2 verdict the record's block or its own votes contradict (Phase 5 spec 3.3)."""
    block, v2 = record.v2, verdict.v2
    problems = []
    name = verdict.claim_id
    if v2.generator_family != block.generator_family or v2.generator_family in v2.members:
        problems.append(f"{name}: the panel names the response's generator family and excludes it (AC-5-1, R-20)")
    if any(vote.family not in v2.members for vote in v2.votes):
        problems.append(f"{name}: every vote is a member family's")
    keys = [(vote.family, vote.span_id) for vote in v2.votes]
    if len(keys) != len(set(keys)):
        problems.append(f"{name}: two votes of one family on one span (AC-5-2)")
    if v2.mode != mode_for(len(v2.members)):
        problems.append(f"{name}: the mode is the one its member count gives")
    table = ROUTING_TABLES.get(block.routing_table_version)
    if table is None or v2.rule != table[v2.mode][v2.tier]:
        problems.append(f"{name}: the rule is the routing table's for its mode and tier")
    if v2.rule == "withhold-queue-v3":
        if v2.votes or v2.objections or v2.split or v2.outcome != "withheld":
            problems.append(f"{name}: a withheld claim has no vote, no objection and outcome withheld")
    else:
        by_family: dict[str, list] = {}
        for vote in sorted(v2.votes, key=lambda item: (item.family, item.span_id)):
            by_family.setdefault(vote.family, []).append((vote.verdict, vote.ehmf_type))
        if set(by_family) != set(v2.members):
            problems.append(f"{name}: every member family voted")
        else:
            family_verdicts = [family_verdict(by_family[family])[0] for family in sorted(by_family)]
            try:
                outcome = tally(v2.rule, family_verdicts)
            except ValueError:
                outcome = None
            if (v2.objections != objections(family_verdicts) or v2.split != is_split(family_verdicts) or v2.outcome != outcome):
                problems.append(f"{name}: the objections, split and outcome are the ones its votes give")
    if any(vote.verifier_prompt_hash != block.verifier_prompt_hash for vote in v2.votes):
        problems.append(f"{name}: every vote carries the block's verifier prompt hash (E-97)")
    if v2.cycle > block.cycles:
        problems.append(f"{name}: a claim verdict's cycle is at most the record's cycles")
    return problems


class VerificationRecordV2(VerificationRecord):
    verification_schema: Literal["v2-verification-v1"] = "v2-verification-v1"
    verdicts: tuple[ClaimVerdictV2, ...] = Field(max_length=20)
    labels: tuple[Literal["near_floor", "conflict_disclosed", "degraded"], ...] = ()
    v2: V2Block

    @model_validator(mode="after")
    def _rules(self) -> "VerificationRecordV2":
        on = self.v2.mode == "on"
        problems = verification_problems(
            self,
            v1_3_routed=lambda verdict: on and verdict.v2 is not None and verdict.v2.outcome == "pass",
            claim_abstains_alone=lambda verdict: on and verdict.v3 is not None and verdict.v3.escalation == "X2",
            final_reasons=V2_FINAL_REASONS,
        )
        problems.extend(self._v2_rules())
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def _v2_rules(self) -> list[str]:
        block = self.v2
        problems = []
        judged = [verdict for verdict in self.verdicts if verdict.v2 is not None]
        if self.hard_fail or (self.final == "abstain" and self.final_reason in _V1_REASONS):
            if judged or block.alignment is not None:
                problems.append("V2 never overwrites a V1 decision: a V1 hard fail or abstention carries no V2 verdict (invariant 3)")
        if not block.panel_reached and (block.calls or block.cycles or block.corrections or judged):
            problems.append("a response whose panel was never reached made no call, no cycle and no V2 verdict")
        if block.generator_family in block.members or not _sorted_unique(block.members):
            problems.append("the panel excludes the generator's family and lists its families sorted (AC-5-1)")
        for verdict in judged:
            problems.extend(_v2_vote_problems(self, verdict))
        if block.mode == "shadow":
            if block.shadow is None or block.cycles or block.corrections:
                problems.append("a shadow block has its would-summary and no correction")
            if any(verdict.v3 is not None and verdict.v3.escalation is not None for verdict in self.verdicts):
                problems.append("a shadow record escalates nothing")
            if self.final_reason is not None and self.final_reason not in PHASE4_FINAL_REASONS:
                problems.append("a shadow record's final reason is Phase 4's")
        else:
            if block.shadow is not None:
                problems.append("an on block has no would-summary")
            for verdict in self.verdicts:
                outcome = verdict.v2.outcome if verdict.v2 is not None else None
                if verdict.final == "deliver" and outcome != "pass":
                    problems.append(f"{verdict.claim_id} is delivered without a passing V2 vote (invariant 6)")
                if outcome == "fail" and (verdict.final != "abstain" or verdict.v3 is None or verdict.v3.escalation != "X2"):
                    problems.append(f"{verdict.claim_id} failed V2 and is not abstained with X2")
                held = "abstain" if block.kill_switch != "none" else "withhold"
                if outcome == "withheld" and (verdict.final != held or verdict.v3 is None or "v2_degraded_withheld" not in verdict.v3.reasons):
                    problems.append(f"{verdict.claim_id} was withheld by V2 and is not {held} and queued")
            if len(block.corrections) != block.cycles or [item.cycle for item in block.corrections] != list(range(1, block.cycles + 1)):
                problems.append("the corrections are the cycles, numbered from 1")
            if any(verdict.v3 is not None and verdict.v3.escalation == "X2" for verdict in self.verdicts) and block.cycles != MAX_CORRECTION_CYCLES:
                problems.append("an X2 escalation follows the last correction cycle")
            if block.kill_switch != "none" and (self.final != "abstain" or self.final_reason not in (*_V1_REASONS, "v2_kill_switch")):
                problems.append("a kill switch abstains with reason v2_kill_switch (or the response is V1's abstention)")
        if self.final_reason == "v2_kill_switch" and block.kill_switch == "none":
            problems.append("only a kill switch gives the reason v2_kill_switch")
        if block.kill_switch != "none":
            if any(verdict.v2.votes or verdict.v2.outcome != "withheld" or verdict.v2.mode != "ZERO" for verdict in judged) or block.calls:
                problems.append("a kill switch makes no call: every judged claim is withheld in ZERO")
        degraded = bool(judged) and block.degraded_mode != "FULL"
        if degraded != ("degraded" in self.labels):
            problems.append("the degraded label is set exactly when a judged claim ran below FULL")
        if (block.banner is not None) != ("degraded" in self.labels) or (block.banner is not None and block.banner != BANNER_FOR_MODE.get(block.degraded_mode)):
            problems.append("the banner is set exactly with the degraded label, and names the degraded mode")
        worst = max((verdict.v2.mode for verdict in judged), key=("FULL", "REDUCED-2", "REDUCED-1", "ZERO").index, default="FULL")
        if block.degraded_mode != worst:
            problems.append("degraded_mode is the worst mode of a judged claim, FULL if none")
        return problems


class ProvenanceV3(ProvenanceV2):             # plan 7.4: every provenance field is filled
    panel_weights_version: str
    routing_table_version: str
    tool_contract_version: str


class ClaimLedgerEntryV3(ClaimLedgerEntryV2):
    provenance: ProvenanceV3


class LedgerEntryV3(LedgerEntryV2):
    entry_schema: Literal["ledger-entry-v3"] = "ledger-entry-v3"
    claims: tuple[ClaimLedgerEntryV3, ...]
    provenance: ProvenanceV3
    verification: VerificationRecordV2

    @model_validator(mode="after")
    def _v3_rules(self) -> "LedgerEntryV3":
        problems = []
        block = self.verification.v2
        for name in ("panel_weights_version", "routing_table_version", "tool_contract_version"):
            if getattr(self.provenance, name) != getattr(block, name):
                problems.append(f"provenance.{name} is the V2 block's")
        if self.delivery != "shadow":
            problems.append("only shadow records carry a V2 verification (DI-85)")
        if self.verification.mode == "enforce":
            spans = {claim.claim_id: set(claim.span_ids) for claim in self.claims}
            for verdict in self.verification.verdicts:
                if verdict.v2 is not None and any(vote.span_id not in spans.get(verdict.claim_id, set()) for vote in verdict.v2.votes):
                    problems.append(f"{verdict.claim_id}: every vote names one of its claim's spans")
        if problems:
            raise ValueError("; ".join(problems))
        return self


ACCEPTED_ABSTENTION_REASONS["ledger-entry-v3"] = (*ACCEPTED_ABSTENTION_REASONS["ledger-entry-v2"], *V2_ABSTENTION_REASONS)
SCHEMA_MODELS["LedgerEntryV3"] = LedgerEntryV3
ENTRY_SCHEMAS["ledger-entry-v3"] = LedgerEntryV3


# ------------------------------------------------------------------------------------------------ EHMF (Phase 7)
#
# Plan Phase 7 D tasks 1-4 (Phase 7 spec 3.3): per-finding EHMF typing, the precedence record, the disclosure template
# conflict-disclosure-v2, the correction record and the X2 list, additive in ledger-entry-v4. A v4 record is validated
# against the routing version and the weights it carries, so a later package never invalidates a stored record.

from fractions import Fraction  # noqa: E402

from app.services.ehmf.routing import FINDING_RULES_BY_VERSION  # noqa: E402 - standard library only
from app.services.ehmf.vocabulary import EHMF_DETECTOR_DOWN, EHMF_SET_CHANGED, PRIMARY_ORDER, TYPE_OF  # noqa: E402

FindingType = Literal["A", "B1", "B2", "C", "D", "E"]
FindingSource = Literal["V1.1", "V1.2", "V1.3", "V1.4", "V1.5", "V1.6", "V1.7", "V1.8", "V1.9", "V2", "alignment"]
EHMF_FINAL_REASONS = (EHMF_DETECTOR_DOWN, EHMF_SET_CHANGED)
EHMF_WEIGHT_KEYS = ("A", "B", "C", "D", "D_disclosed", "E")
_NO_WINNER = ("metadata_incomplete", "no_rule_applies", "rules_disagree")


class EhmfFinding(Contract):
    source: FindingSource
    reason_code: str                          # the V1 reason, the V2 verdict, or "leakage"
    type: FindingType                         # FINDING_RULES_BY_VERSION[record.routing_version][(source, reason_code)] (record rule 2)
    attempt: int = Field(ge=1, le=3)          # the generation attempt of a V1 result (1 for V2 and alignment)
    claim_id: str | None = Field(default=None, pattern=CLAIM_ID)
    reported_type: EhmfType | None = None     # V2 only: the verifier's type; never decides `type`
    family: str | None = None                 # V2 only


class EhmfClaim(Contract):
    claim_id: str = Field(pattern=CLAIM_ID)
    findings: tuple[EhmfFinding, ...] = Field(max_length=64)
    primary: FindingType | None               # highest weight, ties by PRIMARY_ORDER; None without a finding
    weight: str                               # str(Fraction) of the primary's weight ("0" without a finding or for a disclosed D)


class EhmfConflict(Contract):
    kind: Literal["version_of_same_asset", "number_disagreement", "negation_disagreement"]
    span_ids: tuple[str, ...] = Field(min_length=2, max_length=12)
    item_ids: tuple[str, str]
    claim_ids: tuple[str, ...] = ()
    rule: Literal["precedence-v1"] = "precedence-v1"
    winner_item_id: str | None                # recorded only: never changes a final (conflict 24)
    basis: Literal["metadata_incomplete", "no_rule_applies", "rules_disagree", "newer_peer_reviewed", "primary_over_secondary", "both_rules"]
    disclosed: bool
    d_weight: str                             # "0" when disclosed, else the record's D weight ("3/5")


class EhmfDisclosure(Contract):
    template: Literal["conflict-disclosure-v2"] = "conflict-disclosure-v2"
    template_sha256: str = Field(pattern=HEX64)
    text: str = Field(max_length=2000)        # the filled template: kinds and public item ids only, no span text


class EhmfCorrection(Contract):
    cycle: int = Field(ge=1, le=2)
    kind: Literal["revise", "re_render"]
    types: tuple[FindingType, ...]            # the failing claims' finding types this cycle, sorted and unique
    claim_set_before: str = Field(pattern=HEX64)
    claim_set_after: str | None = Field(default=None, pattern=HEX64)    # None when the cycle ended the run (V1 fail)
    span_set_before: str = Field(pattern=HEX64)
    span_set_after: str | None = Field(default=None, pattern=HEX64)
    outcome: Literal["applied", "refused_set_changed", "ended"]


class EhmfRecord(Contract):
    block_schema: Literal["ehmf-v1"] = "ehmf-v1"
    mode: Literal["shadow", "on"]
    routing_version: Literal["ehmf-routing-v1"]
    routing_sha256: str = Field(pattern=HEX64)
    config_version: str                       # == versions.config_package_version (LedgerEntryV4 rule)
    library_version: str
    library_sha256: str = Field(pattern=HEX64)
    weights: dict[str, str]                   # the weights this record used: A, B, C, D, D_disclosed, E as str(Fraction)
    claims: tuple[EhmfClaim, ...] = Field(max_length=20)      # one per verdict, in verdict order
    response_findings: tuple[EhmfFinding, ...] = Field(max_length=256)   # response-level results and dropped proposals, every attempt
    conflicts: tuple[EhmfConflict, ...] = Field(max_length=20)
    disclosure: EhmfDisclosure | None
    corrections: tuple[EhmfCorrection, ...] = Field(max_length=2)
    x2_emitted: tuple[str, ...]               # sorted claim ids escalated X2
    max_cycles: Literal[2] = 2
    detector_down: tuple[str, ...] = ()       # sorted detector names (R-c) that raised or were unavailable
    detector_absent: tuple[str, ...] = ()     # "V1.3" under D-21


def finding_weight(finding_type: str, weights: dict[str, str], *, disclosed: bool = False) -> Fraction:
    """A finding type's weight from a record's own weights: B1 and B2 weigh B, a disclosed V1.7 D weighs D_disclosed."""
    if finding_type == "D" and disclosed:
        return Fraction(weights["D_disclosed"])
    return Fraction(weights[TYPE_OF[finding_type]])


def primary_of(findings, weights: dict[str, str]) -> tuple[str | None, str]:
    """(primary type, str(weight)): the heaviest finding, ties by PRIMARY_ORDER; (None, "0") without a finding."""
    best: tuple[Fraction, int, str] | None = None
    for finding in findings:
        disclosed = finding.source == "V1.7" and finding.reason_code == "conflict_disclosed"
        weight = finding_weight(finding.type, weights, disclosed=disclosed)
        key = (weight, -PRIMARY_ORDER.index(finding.type), finding.type)
        if best is None or key[:2] > best[:2]:
            best = key
    if best is None:
        return None, "0"
    return best[2], str(best[0])


def accepted_v1_1_is_b1(record: "VerificationRecordV2") -> bool:
    """The accepted (final) generation attempt's V1.1 result is a hard fail: a B1 finding on the whole candidate."""
    accepted = max(record.generation_attempts, 1)
    return any(result.check_id == "V1.1" and result.attempt == accepted and result.outcome == "hard_fail" for result in record.checks)


class VerificationRecordV4(VerificationRecordV2):
    verification_schema: Literal["ehmf-verification-v1"] = "ehmf-verification-v1"
    ehmf: EhmfRecord

    @model_validator(mode="after")
    def _rules(self) -> "VerificationRecordV4":
        on = self.v2.mode == "on"
        problems = verification_problems(
            self,
            v1_3_routed=lambda verdict: on and verdict.v2 is not None and verdict.v2.outcome == "pass",
            claim_abstains_alone=lambda verdict: on and verdict.v3 is not None and verdict.v3.escalation == "X2",
            final_reasons=(*V2_FINAL_REASONS, *EHMF_FINAL_REASONS),
        )
        problems.extend(self._v2_rules())
        problems.extend(self._ehmf_rules())
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def _ehmf_rules(self) -> list[str]:  # noqa: C901 - one block per numbered rule of spec 3.3
        ehmf = self.ehmf
        problems: list[str] = []
        rules = FINDING_RULES_BY_VERSION.get(ehmf.routing_version, {})
        verdict_ids = [verdict.claim_id for verdict in self.verdicts]
        # 1. one claim entry per verdict, in order; a claim entry holds only its own findings (and its conflicts' V1.7 D)
        if [claim.claim_id for claim in ehmf.claims] != verdict_ids:
            problems.append("ehmf.claims are one per verdict, in verdict order")
        for claim in ehmf.claims:
            for finding in claim.findings:
                if finding.source == "V1.7":
                    if not any(claim.claim_id in conflict.claim_ids for conflict in ehmf.conflicts):
                        problems.append(f"{claim.claim_id}: a V1.7 finding sits only on its conflict's claims")
                elif finding.claim_id != claim.claim_id:
                    problems.append(f"{claim.claim_id}: a claim entry holds only its own findings (response-level ones are response_findings)")
        # 2. every finding is typed by the record's own routing table; the weights are complete and D_disclosed is 0
        for finding in [finding for claim in ehmf.claims for finding in claim.findings] + list(ehmf.response_findings):
            if rules.get((finding.source, finding.reason_code)) != finding.type:
                problems.append(f"a {finding.source} {finding.reason_code} finding is typed by the record's routing table")
            if (finding.source == "V2") != (finding.family is not None):
                problems.append("a V2 finding, and only one, names its family")
        if set(ehmf.weights) != set(EHMF_WEIGHT_KEYS) or ehmf.weights.get("D_disclosed") != "0":
            problems.append("ehmf.weights name A, B, C, D, D_disclosed and E, and D_disclosed is 0 (plan \"0 when disclosed\")")
            return problems
        try:
            for value in ehmf.weights.values():
                Fraction(value)
        except (ValueError, ZeroDivisionError):
            problems.append("ehmf.weights are fractions")
            return problems
        # 3. AC-7-2: B1 is final
        if accepted_v1_1_is_b1(self) and any(verdict.final == "deliver" or verdict.v2 is not None for verdict in self.verdicts):
            problems.append("the accepted candidate's V1.1 result is B1: no claim is delivered or voted on (AC-7-2)")
        by_claim = {claim.claim_id: claim for claim in ehmf.claims}
        for verdict in self.verdicts:
            entry = by_claim.get(verdict.claim_id)
            if entry is not None and any(finding.type == "B1" for finding in entry.findings) and (verdict.final == "deliver" or verdict.v2 is not None):
                problems.append(f"{verdict.claim_id} has a B1 finding: it is never delivered and never voted on (AC-7-2)")
        # 4. AC-7-3: the conflicts follow the disclosure block; a disclosed conflict's D weighs D_disclosed (0)
        pairs = self.disclosure.conflicts if self.disclosure is not None else ()
        disclose = self.disclosure is not None and self.disclosure.policy == "disclose"
        if [(c.kind, c.span_ids, c.item_ids, c.claim_ids) for c in ehmf.conflicts] != [(p.kind, p.span_ids, p.item_ids, p.claim_ids) for p in pairs]:
            problems.append("ehmf.conflicts are the disclosure block's conflicts, in order")
        for conflict in ehmf.conflicts:
            if conflict.disclosed != disclose:
                problems.append("a conflict is disclosed exactly when the disclosure policy is disclose")
            expected = ehmf.weights["D_disclosed"] if conflict.disclosed else ehmf.weights["D"]
            if conflict.d_weight != expected:
                problems.append("a disclosed conflict's D weighs D_disclosed (0), an undisclosed one D (AC-7-3)")
            # 5. precedence names a winner of the pair only on a rule that orders it (recorded only)
            if (conflict.winner_item_id is None) != (conflict.basis in _NO_WINNER) or (
                    conflict.winner_item_id is not None and conflict.winner_item_id not in conflict.item_ids):
                problems.append("precedence names a winner of the pair exactly when a rule orders it")
        if (ehmf.disclosure is not None) != any(conflict.disclosed for conflict in ehmf.conflicts):
            problems.append("ehmf.disclosure is set exactly when a conflict is disclosed")
        # 6. AC-7-4: a re-render keeps the claim and span sets, or the response abstains (ehmf_set_changed)
        refused = False
        for correction in ehmf.corrections:
            same = correction.claim_set_after == correction.claim_set_before and correction.span_set_after == correction.span_set_before
            if correction.kind == "re_render" and correction.outcome == "applied" and not same:
                problems.append("an applied re-render keeps the claim set and the span set (AC-7-4)")
            if correction.outcome == "refused_set_changed":
                refused = True
                if same or correction.claim_set_after is None:
                    problems.append("a refused re-render changed the claim or span set")
                if self.final != "abstain" or self.final_reason != EHMF_SET_CHANGED:
                    problems.append("a refused re-render abstains the response (ehmf_set_changed)")
        if self.final_reason == EHMF_SET_CHANGED and not refused:
            problems.append("ehmf_set_changed follows a refused re-render")
        # 7. AC-7-5: the corrections are V2's cycles; x2_emitted lists every X2 escalation
        block = self.v2
        if (len(ehmf.corrections) != block.cycles or [c.cycle for c in ehmf.corrections] != list(range(1, block.cycles + 1))
                or [c.kind for c in ehmf.corrections] != [c.kind for c in block.corrections]):
            problems.append("ehmf.corrections are the V2 correction cycles, numbered from 1, of the same kinds")
        x2 = sorted(verdict.claim_id for verdict in self.verdicts if verdict.v3 is not None and verdict.v3.escalation == "X2")
        if list(ehmf.x2_emitted) != x2:
            problems.append("ehmf.x2_emitted lists every claim escalated X2, sorted (AC-7-5)")
        # 8. detector state
        down = tuple(ehmf.detector_down)
        if down and self.final != "abstain":
            problems.append("a detector that is down abstains the response")
        if down == ("V1.3",):
            if self.final_reason not in ("checker_unavailable", EHMF_DETECTOR_DOWN):
                problems.append("V1.3 down abstains with checker_unavailable or ehmf_detector_down")
        elif down and self.final_reason != EHMF_DETECTOR_DOWN:
            problems.append("a detector that is down abstains with ehmf_detector_down")
        if self.final_reason == EHMF_DETECTOR_DOWN and (not down or ehmf.mode != "on"):
            problems.append("ehmf_detector_down names its detector and needs EHMF on")
        if list(down) != sorted(set(down)) or list(ehmf.detector_absent) != sorted(set(ehmf.detector_absent)):
            problems.append("detector_down and detector_absent are sorted and unique")
        # 9. primary and weight from the record's own weights
        for claim in ehmf.claims:
            if (claim.primary, claim.weight) != primary_of(claim.findings, ehmf.weights):
                problems.append(f"{claim.claim_id}: primary is the heaviest finding type (ties by PRIMARY_ORDER) and weight its weight")
        return problems


class LedgerEntryV4(LedgerEntryV3):
    entry_schema: Literal["ledger-entry-v4"] = "ledger-entry-v4"
    verification: VerificationRecordV4

    @model_validator(mode="after")
    def _v4_rules(self) -> "LedgerEntryV4":
        problems = []
        if self.verification.ehmf.config_version != self.versions.config_package_version:
            problems.append("verification.ehmf.config_version is the record's config_package_version")
        if self.delivery != "shadow":
            problems.append("only shadow records carry an EHMF block before the Phase 7 exit (DI-111)")
        if problems:
            raise ValueError("; ".join(problems))
        return self


ACCEPTED_ABSTENTION_REASONS["ledger-entry-v4"] = (*ACCEPTED_ABSTENTION_REASONS["ledger-entry-v3"], *EHMF_FINAL_REASONS)
SCHEMA_MODELS["LedgerEntryV4"] = LedgerEntryV4
ENTRY_SCHEMAS["ledger-entry-v4"] = LedgerEntryV4
