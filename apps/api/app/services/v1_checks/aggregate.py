"""The V1 decision types and the aggregator (plan Phase 4 D: "HARD = final"; "hard_fail is typed so V2 cannot be
consulted"; plan rule 1 and invariant 3; Phase 4 spec 3.3 and 4.12).

A run ends in exactly one of three types:
  V1HardFail   a candidate's last attempt hard-failed (V1.1 unresolvable, V1.9 invalid plan or envelope, V1.4
               unmapped sentence, V1.6 keyed answer): final. It carries results only, no claim and no rendering, and
               no consult path.
  V1Abstained  V1.5 below the floor, no envelope, no claims, no bound claim, the checker unavailable, a readability
               band never met, the budget: not a hard fail, and no consult path either.
  V1Passed     a rendering passed every check of its candidate. Only this type can reach a V2 hook (consult_v2), and
               V1Passed refuses to exist if its accepted generation attempt or its passing render attempt holds a
               hard_fail or an abstain; the one exemption is V1.2's claim-scoped drop of a proposed claim that is not
               a locked claim (the drop is final for that proposal, and the candidate's other claims go on).
A regeneration is a new candidate that every check judges from the start; no later stage, vote or retry re-judges a
hard-failed candidate (Phase 4 spec R-d).

Per locked claim of a V1Passed, final is deliver iff the passing rendering shows it and it has no V1.3 flag, no V1.8
flag, no withheld V1.7 conflict and was not left out for V1.6; otherwise withhold. Before Phase 5 there is no V2, so
D-20's interim text applies (PD-13): every flagged claim is withheld, and the response's replacement is the D-19
contained answer the learner received (extractive_d19, or abstention), "unknown" when no legacy decision exists (replay
and fixture runs). No "under review" label exists. A V1HardFail or V1Abstained abstains on every claim. Whatever the
decision, a claim V1.3 flagged or V1.8 matched in the accepted candidate carries a V3 queue intent, and every claim does
when V1.5 marked the response (X4).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol

from app.services.tutor_pipeline.contracts import (
    CHECK_IDS,
    CheckResult,
    ClaimVerdict,
    DisclosureBlock,
    LockedClaimSet,
    PresentationPlan,
    RenderedResponse,
    V1Comparison,
    V1Policy,
    V3Intent,
    VerificationRecord,
)


def accepted_results(results: Iterable[CheckResult], generation_attempts: int, render_attempts: int) -> tuple[CheckResult, ...]:
    """The results of the accepted candidate: V1.5 (judged once, on the bundle), the pre-render results of the last
    generation attempt and the post-render results of the last render attempt."""
    return tuple(
        result
        for result in results
        if result.check_id == "V1.5"
        or (result.stage == "pre_render" and result.attempt == generation_attempts)
        or (result.stage == "post_render" and result.attempt == render_attempts)
    )


def _blocking(result: CheckResult, locked_ids: frozenset[str]) -> bool:
    if result.outcome not in ("hard_fail", "abstain"):
        return False
    # V1.2's drop of a proposed claim that never locked (R-d): final for that proposal, not for the candidate.
    return not (result.check_id == "V1.2" and result.claim_id is not None and result.claim_id not in locked_ids)


@dataclass(frozen=True)
class V1HardFail:
    """Final. Results only: no locked claim, no rendering, no consult path (plan rule 1, invariant 3)."""

    results: tuple[CheckResult, ...]
    failing: tuple[CheckResult, ...]
    generation_attempts: int
    render_attempts: int
    abstention_reason: str
    final: Literal["abstain"] = "abstain"


@dataclass(frozen=True)
class V1Abstained:
    """Not a hard fail; no consult path either."""

    results: tuple[CheckResult, ...]
    generation_attempts: int
    render_attempts: int
    abstention_reason: str
    final: Literal["abstain"] = "abstain"


@dataclass(frozen=True)
class V1Passed:
    locked: LockedClaimSet
    rendered: RenderedResponse
    presentation: PresentationPlan
    results: tuple[CheckResult, ...]
    verdicts: tuple[ClaimVerdict, ...]
    disclosure: DisclosureBlock | None
    labels: tuple[str, ...]
    generation_attempts: int
    render_attempts: int
    final: Literal["deliver", "withhold"]
    final_reason: str | None

    def __post_init__(self) -> None:
        locked_ids = frozenset(claim.claim_id for claim in self.locked.claims)
        blocking = [result for result in accepted_results(self.results, self.generation_attempts, self.render_attempts)
                    if _blocking(result, locked_ids)]
        if blocking:
            raise ValueError(f"a V1Passed holds a {blocking[0].outcome} of its own candidate ({blocking[0].check_id} "
                             f"{blocking[0].reason_code}): a hard fail is final (plan rule 1)")


V1Decision = V1HardFail | V1Abstained | V1Passed


class V2Hook(Protocol):
    """The Phase 5 V2 panel implements it; Phase 4 wires none."""

    def consult(self, passed: V1Passed) -> object: ...


def consult_v2(hook: V2Hook | None, decision: V1Decision) -> V1Decision:
    """Only a V1Passed reaches a hook (plan rule 1, invariant 3). Phase 4 returns `decision` unchanged whatever the
    hook returns; Phase 5 defines how V2 verdicts apply to a V1Passed's flagged claims."""
    if hook is None or not isinstance(decision, V1Passed):
        return decision
    hook.consult(decision)
    return decision


def cycle_count(generation_attempts: int, render_attempts: int) -> int:
    return max(generation_attempts - 1, 0) + max(render_attempts - 1, 0)


def _in_check_order(results: Iterable[CheckResult]) -> tuple[CheckResult, ...]:
    return tuple(sorted(results, key=lambda result: CHECK_IDS.index(result.check_id)))


def _claim_results(claim_id: str, accepted: tuple[CheckResult, ...]) -> tuple[CheckResult, ...]:
    return _in_check_order(result for result in accepted if result.claim_id in (claim_id, None))


def _flagged(accepted: tuple[CheckResult, ...], check_id: str) -> frozenset[str]:
    return frozenset(result.claim_id for result in accepted if result.check_id == check_id and result.outcome == "flag" and result.claim_id)


def withheld_claim_ids(results: Iterable[CheckResult], disclosure: DisclosureBlock | None) -> frozenset[str]:
    """The claims D-20 and 13.6 withhold before Phase 5: V1.3-flagged, V1.8-matched, and the claims of a withheld V1.7
    conflict."""
    results = tuple(results)
    conflict = frozenset(claim_id for pair in disclosure.conflicts for claim_id in pair.claim_ids) \
        if disclosure is not None and disclosure.policy == "withhold" else frozenset()
    return _flagged(results, "V1.3") | _flagged(results, "V1.8") | conflict


def passed_verdicts(
    *,
    locked: LockedClaimSet,
    rendered: RenderedResponse,
    results: tuple[CheckResult, ...],
    disclosure: DisclosureBlock | None,
    keyed_omitted: frozenset[str],
    generation_attempts: int,
    render_attempts: int,
) -> tuple[tuple[ClaimVerdict, ...], str, str | None]:
    """(verdicts, final, final_reason) of a passing candidate (spec 4.12)."""
    accepted = accepted_results(results, generation_attempts, render_attempts)
    shown = {segment.claim_id for segment in rendered.segments if segment.kind == "claim" and segment.claim_id}
    v1_3, v1_8 = _flagged(accepted, "V1.3"), _flagged(accepted, "V1.8")
    conflict = withheld_claim_ids((), disclosure)
    intent_of = _v3_intents(accepted)
    cycles = cycle_count(generation_attempts, render_attempts)
    verdicts = []
    for claim in locked.claims:
        claim_id = claim.claim_id
        deliver = claim_id in shown and claim_id not in v1_3 | v1_8 | conflict | keyed_omitted
        verdicts.append(ClaimVerdict(claim_id=claim_id, v1=_claim_results(claim_id, accepted), v3=intent_of(claim_id),
                                     final="deliver" if deliver else "withhold", cycle_count=cycles))
    if any(verdict.final == "deliver" for verdict in verdicts):
        return tuple(verdicts), "deliver", None
    conflict_alone = bool(conflict) and all(
        verdict.claim_id in conflict and verdict.claim_id in shown and verdict.claim_id not in v1_3 | v1_8 | keyed_omitted
        for verdict in verdicts
    )
    return tuple(verdicts), "withhold", "conflict_withheld" if conflict_alone else "d20_interim_withhold"


def abstained_verdicts(locked: LockedClaimSet, results: tuple[CheckResult, ...], generation_attempts: int,
                       render_attempts: int) -> tuple[ClaimVerdict, ...]:
    """Every locked claim of an abstained run abstains, and keeps the V3 intent its accepted candidate's results give
    it (plan 7.2 "--V1.8 match--> V3"; D-20 "queued for V3"), as a delivered or withheld claim does."""
    accepted = accepted_results(results, generation_attempts, render_attempts)
    intent_of = _v3_intents(accepted)
    cycles = cycle_count(generation_attempts, render_attempts)
    return tuple(ClaimVerdict(claim_id=claim.claim_id, v1=_claim_results(claim.claim_id, accepted), v3=intent_of(claim.claim_id),
                              final="abstain", cycle_count=cycles)
                 for claim in locked.claims)


def _v3_intents(accepted: tuple[CheckResult, ...]):
    """claim_id -> its V3 queue intent, or None: v1_3_flag when V1.3 flagged the claim, v1_8_misconception when V1.8
    matched it, x4_margin (trigger X4) on every claim when V1.5 marked the response (spec 4.12)."""
    v1_3, v1_8 = _flagged(accepted, "V1.3"), _flagged(accepted, "V1.8")
    marked = any(result.check_id == "V1.5" and result.outcome == "mark" for result in accepted)

    def intent(claim_id: str) -> V3Intent | None:
        reasons = sorted({*(["v1_3_flag"] if claim_id in v1_3 else []), *(["v1_8_misconception"] if claim_id in v1_8 else []),
                          *(["x4_margin"] if marked else [])})
        return V3Intent(reasons=tuple(reasons), trigger="X4" if marked else None) if reasons else None

    return intent


def replacement_for(legacy_decision: str | None) -> str:
    """D-20: "withheld, replaced by pre-verified module content or extractive mode [Decision D-19], else abstain"."""
    return {"answer": "extractive_d19", "abstain": "abstention"}.get(legacy_decision or "", "unknown")


def comparison_for(final: str, *, phase3_decision: str | None, legacy_decision: str | None) -> V1Comparison:
    outcome = "abstain" if final == "abstain" else "answer"
    return V1Comparison(
        phase3_decision=phase3_decision,
        legacy_decision=legacy_decision,
        v1_outcome=outcome,
        agrees_phase3=None if phase3_decision is None else phase3_decision == outcome,
        agrees_legacy=None if legacy_decision is None else legacy_decision == outcome,
    )


def build_record(
    decision: V1Decision,
    *,
    mode: Literal["shadow", "enforce"],
    policy: V1Policy,
    locked: LockedClaimSet | None,
    disclosure: DisclosureBlock | None,
    phase3_decision: str | None,
    legacy_decision: str | None,
) -> VerificationRecord:
    if isinstance(decision, V1Passed):
        verdicts, final, final_reason = decision.verdicts, decision.final, decision.final_reason
        labels = decision.labels
        record_disclosure = decision.disclosure
        claim_set_hash = decision.locked.claim_set_hash
    else:
        verdicts = abstained_verdicts(locked, decision.results, decision.generation_attempts, decision.render_attempts) if locked is not None else ()
        final, final_reason = "abstain", decision.abstention_reason
        marked = any(result.check_id == "V1.5" and result.outcome == "mark" for result in decision.results)
        record_disclosure = disclosure
        labels = tuple(label for label, present in (("near_floor", marked),
                                                     ("conflict_disclosed", disclosure is not None and disclosure.policy == "disclose")) if present)
        claim_set_hash = locked.claim_set_hash if locked is not None else None
    return VerificationRecord(
        mode=mode,
        policy=policy,
        generation_attempts=decision.generation_attempts,
        render_attempts=decision.render_attempts,
        cycle_count=cycle_count(decision.generation_attempts, decision.render_attempts),
        claim_set_hash=claim_set_hash,
        checks=decision.results,
        verdicts=verdicts,
        labels=labels,
        disclosure=record_disclosure,
        final=final,
        final_reason=final_reason,
        replacement=replacement_for(legacy_decision) if final == "withhold" else "none",
        hard_fail=isinstance(decision, V1HardFail),
        comparison=comparison_for(final, phase3_decision=phase3_decision, legacy_decision=legacy_decision),
    )


def labels_for(results: Iterable[CheckResult], disclosure: DisclosureBlock | None) -> tuple[str, ...]:
    marked = any(result.check_id == "V1.5" and result.outcome == "mark" for result in results)
    disclosed = disclosure is not None and disclosure.policy == "disclose"
    return tuple(label for label, present in (("near_floor", marked), ("conflict_disclosed", disclosed)) if present)
