"""Completed verdicts into outcomes (plan Phase 9 task 1, AC-9-1; invariant 7; spec 4.3, readings R-c and R-d; PD-55).

outcome_of reads a validated ledger record and gives an Outcome (a completed verdict, y and the Table X signals) or a
Skip (no completed verdict: the controller only counts it, AC-9-1). The rules apply in order; the first match decides:
  1 no entry: unparsed            2 no verification block (every legacy record): no_verification
  3 the record's generator is not a candidate: generator_unknown; not at the candidate's current version: stale_version
  4 no generation attempt: not_generated (a pre-generation abstention included)
  5 final reasons that are not verdicts: budget_exceeded; checker_unavailable, ehmf_detector_down or a recorded EHMF
    detector down: detector_down; v2_kill_switch: kill_switch; v2_degraded_withheld: v2_withheld; conflict_withheld:
    corpus_conflict
  6 a V1 first-pass failure gives y = 0: a hard fail, a regeneration or re-render (cycle_count > 0), a post-generation V1
    abstention, or an accepted-attempt V1 result outside pass/mark other than V1.7's and V1.3's no_checker
  7 no V2 block: no_v2_verdict    8 the panel not reached: panel_not_reached
  9 a V1-passed claim without a V2 verdict, or withheld by V2: v2_withheld
 10 otherwise y = 1 when the first pass is clean (R-d), else 0.
Clean (R-d): V1 passed with no regeneration; V2 cycles 0, every judged claim pass at cycle 0, the alignment item absent or
pass; and no generator-attributable escalation (X1: a critical claim with an objection; X2; a V3 intent reason v1_3_flag
from a V1.3 result other than no_checker, or v1_8_misconception). X3 feeds F only (AC-9-2); X4, X5, X6 and V1.7 are not
the generator's. A V1.3 no_checker flag is the checker's absence (D-21; the record's ehmf.detector_absent), not a verdict
on the generator (spec conflict 27). No field the generator writes about itself is read (no generator self-confidence).
Signals (first pass): V the share of verdicts whose V1 results pass and whose V2 outcome is pass at cycle 0; K the mean
over judged claims of 1 - H/ln 3 (H the entropy of the family verdicts); H (ledger-entry-v4 only) the mean primary EHMF
weight of the claims, at most 1; S and F missing (D-21; F only for a record the learner was shown, conflict 12).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Any

from app.services.ranking.contexts import cluster_for, task_type_for, tier_for
from app.services.ranking.models import model_of_record
from app.services.ranking.numeric import CTX, ONE, ZERO, q
from app.services.ranking.types import Context, ModelRef, Outcome, Signals, Skip

DETECTOR_DOWN_REASONS = ("checker_unavailable", "ehmf_detector_down")
POST_GENERATION_V1 = ("claim_plan_invalid", "no_claims", "no_bound_claims", "subset_check_failed", "render_failed", "no_whole_sentence",
                      "unresolvable_citation", "keyed_answer_leak", "readability_out_of_band", "response_envelope_invalid")
NON_VERDICT_FINALS = {"budget_exceeded": "budget_exceeded", "checker_unavailable": "detector_down", "ehmf_detector_down": "detector_down",
                      "v2_kill_switch": "kill_switch", "v2_degraded_withheld": "v2_withheld", "conflict_withheld": "corpus_conflict"}
DELIVERABLE = ("pass", "mark")
VERDICT_NAMES = ("SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_INFO")
CHECKER_ABSENT = ("V1.3", "no_checker")


def utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _passes(result: Any) -> bool:
    """A V1 result that is no failure of the generator's: pass or mark, V1.7's labelling flags, V1.3's no_checker."""
    return result.outcome in DELIVERABLE or result.check_id == "V1.7" or (result.check_id, result.reason_code) == CHECKER_ABSENT


def _verdicts(verification: Any) -> tuple:
    return tuple(getattr(verification, "verdicts", ()) or ())


def _v1_failed(verification: Any) -> bool:
    if verification.hard_fail or int(verification.cycle_count) > 0:
        return True
    if verification.final == "abstain" and verification.final_reason in POST_GENERATION_V1:
        return True
    accepted = max(int(verification.generation_attempts), 1)
    for check in verification.checks:
        if check.claim_id is None and check.attempt == accepted and not _passes(check):
            return True
    return any(not _passes(result) for verdict in _verdicts(verification) for result in verdict.v1)


def _escalated(verdict: Any) -> bool:
    v2 = getattr(verdict, "v2", None)
    if v2 is not None and v2.critical and int(v2.objections) >= 1:
        return True
    intent = getattr(verdict, "v3", None)
    if intent is None:
        return False
    if getattr(intent, "escalation", None) == "X2" or "v1_8_misconception" in intent.reasons:
        return True
    if "v1_3_flag" in intent.reasons:
        return any(result.check_id == "V1.3" and result.outcome == "flag" and result.reason_code != "no_checker" for result in verdict.v1)
    return False


def clean(verification: Any) -> bool:
    block = verification.v2
    if _v1_failed(verification) or int(block.cycles) != 0:
        return False
    if block.alignment is not None and block.alignment.outcome != "pass":
        return False
    for verdict in _verdicts(verification):
        v2 = getattr(verdict, "v2", None)
        if v2 is not None and (v2.outcome != "pass" or int(v2.cycle) != 0):
            return False
        if _escalated(verdict):
            return False
    return True


def _family_verdicts(v2: Any) -> list[str]:
    from app.services.v2_panel.voting import family_verdict

    by_family: dict[str, list] = {}
    for vote in sorted(v2.votes, key=lambda item: (item.family, item.span_id)):
        by_family.setdefault(vote.family, []).append((vote.verdict, vote.ehmf_type))
    return [family_verdict(by_family[family])[0] for family in sorted(by_family)]


def vote_agreement(verdicts: list[str]) -> Decimal:
    """1 - H/ln 3 over the family verdicts (H the Shannon entropy of their distribution), in Decimal."""
    with localcontext(CTX):
        n = Decimal(len(verdicts))
        entropy = ZERO
        for name in VERDICT_NAMES:
            count = sum(1 for verdict in verdicts if verdict == name)
            if count:
                p = Decimal(count) / n
                entropy -= p * p.ln()
        return q(ONE - entropy / Decimal(3).ln())


def signals_of(entry: Any) -> Signals:
    verification = entry.verification
    verdicts = _verdicts(verification)
    with localcontext(CTX):
        passing = sum(1 for verdict in verdicts if all(_passes(result) for result in verdict.v1) and getattr(verdict, "v2", None) is not None
                      and verdict.v2.outcome == "pass" and int(verdict.v2.cycle) == 0)
        v = q(Decimal(passing) / Decimal(len(verdicts))) if verdicts else ZERO
        judged = [verdict.v2 for verdict in verdicts if getattr(verdict, "v2", None) is not None and verdict.v2.outcome != "withheld"
                  and int(verdict.v2.cycle) == 0 and verdict.v2.votes]
        k = q(sum((vote_agreement(_family_verdicts(v2)) for v2 in judged), ZERO) / Decimal(len(judged))) if judged else None
        hazard = None
        ehmf = getattr(verification, "ehmf", None)
        if ehmf is not None and ehmf.claims:
            total = sum((Fraction(claim.weight) for claim in ehmf.claims), Fraction(0)) / len(ehmf.claims)
            hazard = q(min(ONE, Decimal(total.numerator) / Decimal(total.denominator)))
    return Signals(V=v, S=None, K=k, H=hazard, F=None)


def outcome_of(entry: Any, *, ledger_seq: int, created_at: str, candidates: dict[str, ModelRef], modules: dict, corpus_version: str | None,
               package: Any, current_versions: dict[str, str] | None = None) -> Outcome | Skip:
    if entry is None:
        return Skip(int(ledger_seq), "unparsed", None)
    verification = getattr(entry, "verification", None)
    if verification is None:
        return Skip(int(ledger_seq), "no_verification", None)
    model, version = model_of_record(entry, candidates)
    if model is None:
        return Skip(int(ledger_seq), "generator_unknown", None)
    current = (current_versions or {}).get(model, candidates[model].model_version)
    if version != current:
        return Skip(int(ledger_seq), "stale_version", model)
    if int(verification.generation_attempts) == 0:
        return Skip(int(ledger_seq), "not_generated", model)
    reason = verification.final_reason
    if reason in NON_VERDICT_FINALS:
        return Skip(int(ledger_seq), NON_VERDICT_FINALS[reason], model)
    ehmf = getattr(verification, "ehmf", None)
    if ehmf is not None and ehmf.detector_down:
        return Skip(int(ledger_seq), "detector_down", model)
    if verification.final == "abstain" and reason is not None and reason not in POST_GENERATION_V1 and not verification.hard_fail:
        return Skip(int(ledger_seq), "not_generated", model)
    tier, tier_source = tier_for(entry, package)
    context = Context(cluster_for(entry, modules, corpus_version), task_type_for(tier, package), tier)
    cost = int(candidates[model].cost_units_per_call)

    def outcome(y: int) -> Outcome:
        return Outcome(ledger_seq=int(ledger_seq), created_at=created_at, model=model, context=context, y=y, signals=signals_of(entry),
                       cost_units=cost, latency_ms=None, tier_source=tier_source)

    if _v1_failed(verification):
        return outcome(0)
    block = getattr(verification, "v2", None)
    if block is None:
        return Skip(int(ledger_seq), "no_v2_verdict", model)
    if not block.panel_reached:
        return Skip(int(ledger_seq), "panel_not_reached", model)
    for verdict in _verdicts(verification):
        if all(_passes(result) for result in verdict.v1) and (getattr(verdict, "v2", None) is None or verdict.v2.outcome == "withheld"):
            return Skip(int(ledger_seq), "v2_withheld", model)
    return outcome(1 if clean(verification) else 0)


def outcome_payload(outcome: Outcome) -> dict:
    from app.services.ranking.numeric import to_str

    return {"ledger_seq": outcome.ledger_seq, "created_at": outcome.created_at, "model": outcome.model,
            "context": {"cluster": outcome.context.cluster, "task_type": outcome.context.task_type, "tier": outcome.context.tier},
            "y": outcome.y, "signals": {name: (None if getattr(outcome.signals, name) is None else to_str(getattr(outcome.signals, name)))
                                       for name in ("V", "S", "K", "H", "F")},
            "cost_units": outcome.cost_units, "latency_ms": outcome.latency_ms, "tier_source": outcome.tier_source}
