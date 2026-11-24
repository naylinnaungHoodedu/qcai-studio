"""The V2 verification record (plan Phase 5; plan 7.4 VerificationVerdict; Phase 5 spec 4.13, 4.14).

build_record_v2 turns the final V1 decision and the V2 track's state into a VerificationRecordV2.
  A V1HardFail or V1Abstained is the record of that V1 decision: no claim verdict carries v2 (invariant 3; AC-5-5).
  shadow  the finals, final_reason, replacement and V3 intents are Phase 4's; each V2-eligible claim carries its v2
          verdict, and V2ShadowSummary counts what on would decide without correction.
  on      per locked claim of the final V1Passed: deliver iff it is V2-eligible, its V2 outcome is pass, the final
          rendering shows it and the alignment item passed; withhold iff it is V1-withheld (V1.8, a withheld V1.7
          conflict, V1.6) or its V2 outcome is withheld (or the alignment item could not be judged); abstain iff it is
          exhausted (it failed V2 after two correction cycles, or the alignment item still failed), with V3 escalation
          X2. The response delivers when any claim does; withholds when none does and any claim is withheld
          (v2_degraded_withheld when V2 withheld one, else Phase 4's reason); abstains when every claim is exhausted
          (v2_alignment_failed or v2_correction_exhausted).
          Under a kill switch (plan 13.6 "abstain-only, pre-verified-only"; pre-verified-only abstains while no
          pre-verified source exists, DI-83) no member is eligible, so no call is made: every claim abstains, each claim
          V2 withheld keeps its v2_degraded_withheld queue intent, and the response abstains (v2_kill_switch) whatever
          the legacy decision was.
V3 intents keep the Phase 4 reasons, except that v1_3_flag is dropped once the claim's V2 vote completed (pass or fail:
"after Phase 5, flags route to V2"); a V2 withholding adds v2_degraded_withheld; exhaustion adds
v2_correction_exhausted with escalation X2. The degraded label and banner follow the worst mode of a judged claim.
"""

from __future__ import annotations

from typing import Any

from app.services.tutor_pipeline.contracts import (
    ClaimVerdictV2,
    V2Block,
    V2ShadowSummary,
    V3IntentV2,
    VerificationRecordV2,
)
from app.services.v1_checks.aggregate import (
    V1Passed,
    _flagged,
    accepted_results,
    build_record,
    comparison_for,
    labels_for,
    replacement_for,
    withheld_claim_ids,
)
from app.services.v2_panel.rules import BANNER_FOR_MODE, PANEL_WEIGHTS_VERSION
from app.services.v2_panel.track import worst_mode


def v1_excluded(passed: V1Passed, items: Any, v1: Any) -> frozenset[str]:
    """The claims V1 withholds whatever V2 says: V1.8 matches, the claims of a withheld V1.7 conflict and the claims
    V1.6 left out of the rendering (V1.3 flags route to V2)."""
    from app.services.v1_checks.v1_6_keyed_answers import keyed_claim_ids

    accepted = accepted_results(passed.results, passed.generation_attempts, passed.render_attempts)
    keyed = frozenset()
    if any(result.check_id == "V1.6" and result.outcome == "hard_fail" for result in passed.results):
        keyed = frozenset(keyed_claim_ids(passed.locked, items, v1=v1))
    return _flagged(accepted, "V1.8") | withheld_claim_ids((), passed.disclosure) | keyed


def _intent(base: Any, *, drop_v1_3: bool = False, add: tuple[str, ...] = ()) -> V3IntentV2 | None:
    reasons = set(base.reasons) if base is not None else set()
    if drop_v1_3:
        reasons.discard("v1_3_flag")
    reasons.update(add)
    if not reasons:
        return None
    return V3IntentV2(reasons=tuple(sorted(reasons)), trigger="X4" if "x4_margin" in reasons else None,
                      escalation="X2" if "v2_correction_exhausted" in reasons else None)


def _block(track: Any, *, degraded_mode: str, alignment: Any, cycles: int, corrections: tuple, shadow: V2ShadowSummary | None,
           banner: str | None) -> V2Block:
    package = track.package
    return V2Block(
        mode=track.mode, panel_reached=track.panel_reached, gateway_state=track.gateway.state, registry=track.adapter_registry.name,
        generator_family=track.generator_family, members=track.start_members, degraded_mode=degraded_mode,
        panel_weights_version=package.v2.panel_weights_version, routing_table_version=package.v2.routing_table_version,
        tool_contract_version=package.tools.version, verifier_prompt_hash=package.v2.verifier_prompt_hash,
        alignment_prompt_hash=package.v2.alignment_prompt_hash, alignment=alignment, cycles=cycles, corrections=tuple(corrections),
        calls=track.calls, cache_hits=track.cache_hits, cost_units=track.cost_units, kill_switch=track.kill_switch,
        banner=banner, shadow=shadow,
    )


def _labels(base: tuple[str, ...], judged: dict, degraded_mode: str) -> tuple[tuple[str, ...], str | None]:
    degraded = bool(judged) and degraded_mode != "FULL"
    return (tuple(base) + (("degraded",) if degraded else ())), (BANNER_FOR_MODE[degraded_mode] if degraded else None)


def build_record_v2(decision: Any, **kwargs: Any) -> VerificationRecordV2:
    return VerificationRecordV2(**_record_fields_v2(decision, **kwargs))


def _record_fields_v2(decision: Any, *, mode: str, policy: Any, locked: Any, disclosure: Any, phase3_decision: str | None,
                      legacy_decision: str | None, track: Any, outcome: Any, cycles: int = 0, corrections: tuple = (),
                      exhausted: frozenset[str] = frozenset(), alignment: Any = None, alignment_failed: bool = False,
                      alignment_missing: bool = False) -> dict[str, Any]:
    """The fields of the V2 record build_record_v2 validates; ehmf.record builds a VerificationRecordV4 from the same
    fields (Phase 7 spec 3.3). An EHMF abstention (ehmf_detector_down, ehmf_set_changed; valid in a v4 record only) is
    built as a V1 abstention whose final reason is the EHMF reason."""
    from dataclasses import replace

    from app.services.tutor_pipeline.contracts import EHMF_FINAL_REASONS

    ehmf_reason = getattr(decision, "abstention_reason", None) if getattr(decision, "abstention_reason", None) in EHMF_FINAL_REASONS else None
    if ehmf_reason is not None:
        decision = replace(decision, abstention_reason="no_claims")
    base = build_record(decision, mode=mode, policy=policy, locked=locked, disclosure=disclosure, phase3_decision=phase3_decision,
                        legacy_decision=legacy_decision)
    fields = {name: getattr(base, name) for name in type(base).model_fields if name not in ("verification_schema", "verdicts", "labels")}
    if ehmf_reason is not None:
        fields["final_reason"] = ehmf_reason
    passed = isinstance(decision, V1Passed)
    judged = dict(outcome.claims) if (passed and outcome is not None) else {}
    degraded_mode = worst_mode(verdict.mode for verdict in judged.values())
    if not passed:
        verdicts = tuple(ClaimVerdictV2(claim_id=verdict.claim_id, v1=verdict.v1, v3=_intent(verdict.v3), final=verdict.final,
                                        cycle_count=verdict.cycle_count) for verdict in base.verdicts)
        shadow = V2ShadowSummary(would_deliver=0, would_fail=0, would_withhold=0) if track.mode == "shadow" else None
        block = _block(track, degraded_mode="FULL", alignment=None, cycles=cycles, corrections=corrections, shadow=shadow, banner=None)
        return dict(**fields, verdicts=verdicts, labels=base.labels, v2=block)
    if track.mode == "shadow":
        verdicts = tuple(ClaimVerdictV2(claim_id=verdict.claim_id, v1=verdict.v1, v2=judged.get(verdict.claim_id), v3=_intent(verdict.v3),
                                        final=verdict.final, cycle_count=verdict.cycle_count) for verdict in base.verdicts)
        counts = {"pass": 0, "fail": 0, "withheld": 0}
        for verdict in judged.values():
            counts[verdict.outcome] += 1
        shadow = V2ShadowSummary(would_deliver=counts["pass"], would_fail=counts["fail"], would_withhold=counts["withheld"])
        labels, banner = _labels(base.labels, judged, degraded_mode)
        block = _block(track, degraded_mode=degraded_mode, alignment=alignment if alignment is not None else outcome.alignment,
                       cycles=0, corrections=(), shadow=shadow, banner=banner)
        return dict(**fields, verdicts=verdicts, labels=labels, v2=block)
    # on
    shown = {segment.claim_id for segment in decision.rendered.segments if segment.kind == "claim" and segment.claim_id}
    if alignment_failed:
        exhausted = frozenset(exhausted) | frozenset(claim_id for claim_id, verdict in judged.items() if verdict.outcome == "pass" and claim_id in shown)
    kill = track.kill_switch != "none"
    verdicts = []
    for verdict in decision.verdicts:
        claim_id = verdict.claim_id
        v2 = judged.get(claim_id)
        result = v2.outcome if v2 is not None else None
        completed = result in ("pass", "fail")
        if claim_id in exhausted:
            final, intent = "abstain", _intent(verdict.v3, drop_v1_3=completed, add=("v2_correction_exhausted",))
        elif result == "withheld":
            final, intent = "withhold", _intent(verdict.v3, add=("v2_degraded_withheld",))
        elif result == "pass" and claim_id in shown and not alignment_missing:
            final, intent = "deliver", _intent(verdict.v3, drop_v1_3=True)
        elif result == "pass" and alignment_missing:
            final, intent = "withhold", _intent(verdict.v3, drop_v1_3=True, add=("v2_degraded_withheld",))
        else:
            final, intent = "withhold", _intent(verdict.v3, drop_v1_3=completed)
        if kill:
            final = "abstain"
        verdicts.append(ClaimVerdictV2(claim_id=claim_id, v1=verdict.v1, v2=v2, v3=intent, final=final, cycle_count=verdict.cycle_count))
    finals = [verdict.final for verdict in verdicts]
    if kill:
        final, final_reason = "abstain", "v2_kill_switch"
    elif "deliver" in finals:
        final, final_reason = "deliver", None
    elif "withhold" in finals:
        final = "withhold"
        if any(verdict.v3 is not None and "v2_degraded_withheld" in verdict.v3.reasons for verdict in verdicts):
            final_reason = "v2_degraded_withheld"
        else:
            conflict = withheld_claim_ids((), decision.disclosure)
            withheld = [verdict.claim_id for verdict in verdicts if verdict.final == "withhold"]
            final_reason = "conflict_withheld" if withheld and set(withheld) <= conflict else "d20_interim_withhold"
    else:
        final, final_reason = "abstain", ("v2_alignment_failed" if alignment_failed else "v2_correction_exhausted")
    labels, banner = _labels(labels_for(decision.results, decision.disclosure), judged, degraded_mode)
    fields.update(final=final, final_reason=final_reason, replacement=replacement_for(legacy_decision) if final == "withhold" else "none",
                  comparison=comparison_for(final, phase3_decision=phase3_decision, legacy_decision=legacy_decision))
    block = _block(track, degraded_mode=degraded_mode, alignment=alignment, cycles=cycles, corrections=corrections, shadow=None, banner=banner)
    return dict(**fields, verdicts=tuple(verdicts), labels=labels, v2=block)


__all__ = ["build_record_v2", "v1_excluded", "PANEL_WEIGHTS_VERSION"]
