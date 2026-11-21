"""The V1 aggregator, the runner and the render hook (Phase 4 spec 3.2-3.3, 4.11-4.13)."""

from __future__ import annotations

import logging
import random

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.structured_logging import FIELDS
from app.services.claim_gate import check_subset
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline import pipeline as pipeline_module
from app.services.tutor_pipeline.contracts import LedgerEntryV2, PresentationPlan, VerificationRecord, bound_claim_ratio_terms
from app.services.tutor_pipeline.pipeline import render_checked
from app.services.tutor_pipeline.render import TemplateRenderer
from app.services.v1_checks.aggregate import cycle_count, replacement_for
from tutor_fakes import FAULT_MODES, FaultyRenderer, INVENTED, ScriptedGenerator
from v1_fakes import MULTI_CLAIM, AlwaysSupportedChecker, ScriptedChecker, UnmappedRenderer, dev_pipeline, run


def _phase3_render_checked(renderer, locked, presentation, *, max_regenerations, over=None):
    """Phase 3's render_checked, verbatim (main 078bc75), the reference for the no-hook path."""
    attempts = 1 + max_regenerations
    faults = 0
    for attempt in range(1, attempts + 1):
        step = "render"
        try:
            candidate = renderer.render(locked, presentation, attempt=attempt)
            step = "subset_check"
            passed = check_subset(candidate, locked).passed
        except contracts.LockedClaimSetTampered:
            raise
        except Exception as exc:  # noqa: BLE001
            faults += 1
            passed = False
            logging.getLogger("qcai.tutor").error("Two-pass render attempt raised", extra={FIELDS: {
                "event": "tutor.two_pass.render_failed", "step": step, "render_attempt": attempt, "error": type(exc).__name__}})
        if passed:
            return candidate, attempt, None
        if attempt < attempts and over is not None and over():
            return None, attempt, "budget_exceeded"
    return None, attempts, contracts.RENDER_FAILED if faults == attempts else "subset_check_failed"


def _events(caplog):
    return [(getattr(r, FIELDS)["step"], getattr(r, FIELDS)["render_attempt"], getattr(r, FIELDS)["error"]) for r in caplog.records
            if getattr(r, FIELDS, {}).get("event") == "tutor.two_pass.render_failed"]


def test_render_checked_without_a_hook_is_phase_3_s_on_300_fault_schedules(caplog):
    baseline = run(dev_pipeline(Settings(v1_pipeline="off")), MULTI_CLAIM)
    locked = baseline.locked
    outside = "Quantum annealers solve every routing problem instantly."
    plan = PresentationPlan(plan_id="concise", source="request")
    rng = random.Random(20261120)
    for _ in range(300):
        schedule = [rng.random() < 0.5 for _ in range(3)]
        seed = rng.randrange(10**9)
        results = []
        for implementation in (render_checked, _phase3_render_checked):
            caplog.clear()
            renderer = FaultyRenderer(TemplateRenderer(), schedule, random.Random(seed), outside_sentence=outside,
                                      outside_span_id=locked.span_ids[0], modes=FAULT_MODES, exact=rng.random() < 0.2)
            with caplog.at_level(logging.ERROR, logger="qcai.tutor"):
                rendered, attempts, reason = implementation(renderer, locked, plan, max_regenerations=2)
            results.append((None if rendered is None else rendered.model_dump(mode="json"), attempts, reason, renderer.placed, _events(caplog)))
        assert results[0] == results[1]


def test_cycle_count_and_replacement_rules():
    assert [cycle_count(g, r) for g, r in ((0, 0), (1, 1), (3, 1), (1, 3), (3, 3))] == [0, 0, 2, 2, 4]
    assert (replacement_for("answer"), replacement_for("abstain"), replacement_for(None)) == ("extractive_d19", "abstention", "unknown")


def test_with_no_checker_every_claim_is_rendered_and_withheld_with_its_replacement():
    for legacy, replacement in (("answer", "extractive_d19"), ("abstain", "abstention"), (None, "unknown")):
        result = run(dev_pipeline(), MULTI_CLAIM, legacy_decision=legacy)
        record = result.entry.verification
        assert record.final == "withhold" and record.final_reason == "d20_interim_withhold" and record.replacement == replacement
        assert {claim.claim_id for claim in result.locked.claims} == set(result.entry.presentation.rendered_claim_ids)
        assert all(v.final == "withhold" and v.v3.reasons == ("v1_3_flag",) for v in record.verdicts)


def test_a_partly_withheld_set_is_left_out_of_the_rendering_and_the_rest_delivers():
    labels = [("NOT_ENOUGH_INFO", None)] + [("SUPPORTED", 1.0)] * 9
    result = run(dev_pipeline(checker=ScriptedChecker(labels)), MULTI_CLAIM)
    record = result.entry.verification
    first = result.locked.claims[0].claim_id
    assert first not in result.entry.presentation.rendered_claim_ids and record.final == "deliver" and record.final_reason is None
    finals = {v.claim_id: v.final for v in record.verdicts}
    assert finals[first] == "withhold" and all(final == "deliver" for claim_id, final in finals.items() if claim_id != first)


def test_hook_reasons_band_and_faults():
    from dataclasses import replace

    pipeline = dev_pipeline(checker=AlwaysSupportedChecker())
    pipeline.v1_params = replace(pipeline.v1_params, readability_min=99.0, readability_max=100.0)
    result = run(pipeline, MULTI_CLAIM)
    record = result.entry.verification
    assert (result.decision, result.abstention_reason, record.hard_fail, record.render_attempts) == ("abstain", "readability_out_of_band", False, 3)

    class Raising:
        renderer_id = "template-renderer-v1"

        def render(self, locked, plan, *, attempt, **options):
            raise RuntimeError("renderer bug (test)")

    result = run(dev_pipeline(checker=AlwaysSupportedChecker(), renderer=Raising()), MULTI_CLAIM)
    assert (result.abstention_reason, result.entry.verification.hard_fail) == ("render_failed", True)
    assert [r.reason_code for r in result.entry.verification.checks if r.check_id == "V1.4"] == ["render_failed"] * 3


def test_the_budget_stops_the_render_loop():
    from v1_fakes import InjectedClock

    clock = InjectedClock()

    class Slow(UnmappedRenderer):
        def render(self, locked, plan, *, attempt, **options):
            clock.now += 10.0  # the first rendering takes the whole budget
            return super().render(locked, plan, attempt=attempt, **options)

    pipeline = dev_pipeline(checker=AlwaysSupportedChecker(), renderer=Slow(TemplateRenderer(), None), clock=clock)
    result = run(pipeline, MULTI_CLAIM, budget_ms=1000)
    record = result.entry.verification
    assert (result.abstention_reason, record.hard_fail, record.render_attempts) == ("budget_exceeded", False, 1)


@pytest.mark.parametrize("mode", ["shadow", "enforce"])
def test_a_v1_track_overrun_logs_the_phase_3_budget_event_only_when_v1_is_the_record(mode, caplog):
    # Every rendering takes the whole budget. In shadow the first is Phase 3's, which passes, so the record stays within
    # its budget and only the V1 track that follows overruns: tutor.v1.budget_exceeded, never the Phase 3 event. In
    # enforce the V1 track is the record's composition (here its first rendering is refused, so the budget stops the
    # render loop), and its overrun is the record's: tutor.two_pass.budget_exceeded.
    from v1_fakes import InjectedClock

    clock = InjectedClock()

    class Slow(UnmappedRenderer):
        def render(self, locked, plan, *, attempt, **options):
            clock.now += 10.0
            return super().render(locked, plan, attempt=attempt, **options)

    renderer = Slow(TemplateRenderer(), () if mode == "shadow" else None)
    pipeline = dev_pipeline(Settings(v1_pipeline=mode), checker=AlwaysSupportedChecker(), renderer=renderer, clock=clock)
    with caplog.at_level(logging.WARNING, logger="qcai.tutor"):
        result = run(pipeline, MULTI_CLAIM, budget_ms=1000, legacy_decision="answer")
    events = [getattr(r, FIELDS) for r in caplog.records if str(getattr(r, FIELDS, {}).get("event", "")).endswith("budget_exceeded")]
    record = result.entry.verification
    if mode == "shadow":
        assert (result.decision, result.abstention_reason) == ("answer", None)
        assert (record.final, record.final_reason) == ("abstain", "budget_exceeded")
        assert [line["event"] for line in events] == ["tutor.v1.budget_exceeded"]
    else:
        assert (result.decision, result.abstention_reason) == ("abstain", "budget_exceeded")
        assert [line["event"] for line in events] == ["tutor.two_pass.budget_exceeded"]
    assert set(events[0]) == {"event", "step", "elapsed_ms", "budget_ms"} and events[0]["budget_ms"] == 1000


def test_shadow_and_enforce_records():
    shadow = run(dev_pipeline(Settings(v1_pipeline="shadow")), MULTI_CLAIM, legacy_decision="answer").entry
    enforce = run(dev_pipeline(Settings(v1_pipeline="enforce")), MULTI_CLAIM, legacy_decision="answer").entry
    off = run(dev_pipeline(Settings(v1_pipeline="off")), MULTI_CLAIM, legacy_decision="answer").entry
    assert (off.entry_schema, shadow.entry_schema, enforce.entry_schema) == ("ledger-entry-v1", "ledger-entry-v2", "ledger-entry-v2")
    assert shadow.verification.mode == "shadow" and shadow.verification.comparison.phase3_decision == shadow.decision == "answer"
    assert enforce.verification.mode == "enforce" and enforce.verification.comparison.phase3_decision is None
    assert shadow.claim_set_hash == off.claim_set_hash == enforce.claim_set_hash
    assert shadow.provenance.v1_3_checker_model_id == "none" and all(claim.entailment_score is None for claim in enforce.claims)


def test_a_v1_1_hard_failed_candidate_counts_its_claims_so_the_bound_claim_ratio_sees_them():
    # The same three-claim plan in every mode, one claim citing a fabricated span id (R-13, R-16). Off and shadow
    # record the Phase 3 composition (that claim dropped as outside_bundle); enforce hard-fails the candidate on
    # every attempt, so none of its claims is bound and each is counted, never left out of the plan L ratio.
    clean = [(claim.text, list(claim.span_ids)) for claim in run(dev_pipeline(Settings(v1_pipeline="off")), MULTI_CLAIM).plan.claims]
    assert len(clean) == 3
    forged = [(clean[0][0], ["span-" + "e" * 64]), *clean[1:]]
    entries = {}
    for mode in ("off", "shadow", "enforce"):
        pipeline = dev_pipeline(Settings(v1_pipeline=mode), generator=ScriptedGenerator([forged]), checker=AlwaysSupportedChecker())
        entries[mode] = run(pipeline, MULTI_CLAIM, legacy_decision="answer").entry
    for mode in ("off", "shadow"):
        counts = entries[mode].counts
        assert (counts.proposed_claims, counts.bound_claims, dict(counts.dropped)) == (3, 2, {"outside_bundle": 1}), mode
        assert bound_claim_ratio_terms(counts) == (3, 2), mode
    enforced = entries["enforce"]
    assert (enforced.decision, enforced.abstention_reason, enforced.verification.hard_fail) == ("abstain", "unresolvable_citation", True)
    counts = enforced.counts
    assert (counts.proposed_claims, counts.bound_claims, dict(counts.dropped)) == (3, 0, {contracts.UNRESOLVABLE_CANDIDATE: 3})
    assert bound_claim_ratio_terms(counts) == (3, 0)
    # The counts reconcile, and the reason belongs to V1: a shadow record (the Phase 3 counts) may not carry it.
    payload = entries["shadow"].model_dump(mode="json")
    payload["counts"].update(dropped={contracts.UNRESOLVABLE_CANDIDATE: 1})
    with pytest.raises(ValidationError, match="no V1 count reason"):
        LedgerEntryV2.model_validate(payload)


def _record_payload():
    return run(dev_pipeline(checker=AlwaysSupportedChecker()), MULTI_CLAIM, legacy_decision="answer").entry.model_dump(mode="json")


@pytest.mark.parametrize(
    ("edit", "rule"),
    [
        (lambda r: r["verification"].update(cycle_count=1), "cycle_count"),
        (lambda r: r["verification"].update(final="correct"), "correct"),
        (lambda r: r["verification"].update(final="withhold", final_reason="d20_interim_withhold"), "replacement"),
        (lambda r: r["verification"].update(hard_fail=True), "hard fail is final"),
        (lambda r: r["verification"].update(final_reason="d20_interim_withhold"), "final_reason"),
        (lambda r: r["verification"].update(labels=["near_floor"]), "near_floor"),
        (lambda r: r["verification"]["comparison"].update(agrees_legacy=False), "agrees"),
        (lambda r: r["verification"]["verdicts"][0].update(final="abstain"), "abstain"),
        (lambda r: [r["provenance"].update(v1_3_checker_model_id="other"), *(c["provenance"].update(v1_3_checker_model_id="other") for c in r["claims"])],
         "checker"),
        (lambda r: r["verification"].update(claim_set_hash="0" * 64), "claim set"),
        (lambda r: r["verification"]["verdicts"].reverse(), "in order"),
    ],
)
def test_the_verification_and_ledger_v2_rules_refuse_each_inconsistency(edit, rule):
    payload = _record_payload()
    LedgerEntryV2.model_validate(payload)
    edit(payload)
    with pytest.raises(ValidationError, match=rule):
        LedgerEntryV2.model_validate(payload)


def test_only_shadow_records_carry_a_verification_before_the_phase_4_exit(monkeypatch):
    payload = _record_payload()
    monkeypatch.setattr(contracts, "TWO_PASS_DELIVERY_IMPLEMENTED", True)
    payload.update(delivery="delivered", shadowed_response_id=None, response_id="turn-" + payload["response_id"].split("-", 1)[1])
    for claim in payload["claims"]:
        claim["response_id"] = payload["response_id"]
    with pytest.raises(ValidationError, match="only shadow records carry a V1 verification"):
        LedgerEntryV2.model_validate(payload)


def test_a_delivered_verdict_with_a_non_pass_result_is_refused():
    payload = _record_payload()
    verdict = payload["verification"]["verdicts"][0]
    flag = {"check_id": "V1.8", "stage": "pre_render", "attempt": 1, "outcome": "flag", "ehmf_types": ["C"], "reason_code": "misconception_match",
            "claim_id": verdict["claim_id"], "checker_model_id": None}
    verdict["v1"] = [*verdict["v1"], flag]
    with pytest.raises(ValidationError, match="invariant 6"):
        VerificationRecord.model_validate(payload["verification"])


def test_check_results_are_consistent_with_their_vocabulary():
    good = {"check_id": "V1.1", "stage": "pre_render", "attempt": 1, "outcome": "hard_fail", "ehmf_types": ["B"], "reason_code": "unresolvable"}
    contracts.CheckResult.model_validate(good)
    for edit in ({"outcome": "pass"}, {"reason_code": "no_such_reason"}, {"ehmf_types": ["A"]}, {"stage": "post_render"},
                 {"checker_model_id": "none"}, {"claim_id": "claim-" + "0" * 32}, {"attempt": 4}):
        with pytest.raises(ValidationError):
            contracts.CheckResult.model_validate({**good, **edit})
    v1_3 = {"check_id": "V1.3", "stage": "pre_render", "attempt": 1, "outcome": "flag", "ehmf_types": ["A", "B", "C"], "reason_code": "no_checker",
            "claim_id": "claim-" + "0" * 32, "checker_model_id": "none"}
    contracts.CheckResult.model_validate(v1_3)
    with pytest.raises(ValidationError):
        contracts.CheckResult.model_validate({**v1_3, "checker_model_id": None})
    with pytest.raises(ValidationError):
        contracts.CheckResult.model_validate({**v1_3, "claim_id": None})


def test_v3_intents_and_conflict_pairs_are_well_formed():
    contracts.V3Intent(reasons=("v1_3_flag", "x4_margin"), trigger="X4")
    for bad in ({"reasons": ("x4_margin",)}, {"reasons": ("v1_3_flag",), "trigger": "X4"}, {"reasons": ("x4_margin", "v1_3_flag"), "trigger": "X4"}, {"reasons": ()}):
        with pytest.raises(ValidationError):
            contracts.V3Intent(**bad)
    with pytest.raises(ValidationError):
        contracts.ConflictPair(kind="number_disagreement", span_ids=("b", "a"), item_ids=("x", "y"))
    with pytest.raises(ValidationError):
        contracts.ConflictPair(kind="number_disagreement", span_ids=("a", "b"), item_ids=("x", "x"))


def test_a_record_holds_at_most_twenty_verdicts():
    assert VerificationRecord.model_fields["verdicts"].metadata[-1].max_length == 20


def test_the_unmapped_fault_of_tutor_fakes_is_v1_4_s_unmapped_sentence():
    result = run(dev_pipeline(checker=AlwaysSupportedChecker(), renderer=UnmappedRenderer(TemplateRenderer(), [1], sentence=INVENTED)), MULTI_CLAIM)
    assert [r.reason_code for r in result.entry.verification.checks if r.check_id == "V1.4"] == ["unmapped_factual_sentence", "mapped"]
    assert pipeline_module.check_subset is check_subset


def test_an_abstained_run_keeps_each_claim_s_v3_intent():
    # Plan 7.2 "--V1.8 match--> V3" and D-20 "queued for V3": a claim V1.3 flagged or V1.8 matched carries its V3 intent
    # whatever the final decision, so an abstained run (here every rendering adds an unmapped sentence: V1HardFail,
    # subset_check_failed) queues it too; a V1.5 mark adds x4_margin (trigger X4) to every claim. A claim with none of
    # them carries no intent.
    import dataclasses

    from v1_fakes import fixture_library

    unmapped = UnmappedRenderer(TemplateRenderer(), None)
    production = run(dev_pipeline(renderer=unmapped), MULTI_CLAIM).entry.verification
    assert (production.final, production.final_reason, production.hard_fail) == ("abstain", "subset_check_failed", True)
    assert production.verdicts and all(v.final == "abstain" and v.v3 is not None and v.v3.reasons == ("v1_3_flag",) and v.v3.trigger is None
                                       for v in production.verdicts)
    locked = run(dev_pipeline(), MULTI_CLAIM).locked
    words = sorted({word.lower().strip(".,;:") for word in locked.claims[0].text.split() if len(word) > 5})[:2]
    matched = run(dev_pipeline(checker=AlwaysSupportedChecker(), misconceptions=fixture_library([("MC-1", words)]),
                               renderer=UnmappedRenderer(TemplateRenderer(), None)), MULTI_CLAIM).entry.verification
    assert matched.final == "abstain"
    intents = {v.claim_id: v.v3 for v in matched.verdicts}
    assert intents[locked.claims[0].claim_id].reasons == ("v1_8_misconception",)
    assert all(intent is None for claim_id, intent in intents.items() if claim_id != locked.claims[0].claim_id)
    marking = dev_pipeline(checker=AlwaysSupportedChecker(), renderer=UnmappedRenderer(TemplateRenderer(), None))
    marking.v1_params = dataclasses.replace(marking.v1_params, x4_margin={"bm25f-v1": 1000.0, "p1-floor": 0.0})
    marked = run(marking, MULTI_CLAIM).entry.verification
    assert marked.final == "abstain" and "near_floor" in marked.labels
    assert all(v.v3 is not None and v.v3.reasons == ("x4_margin",) and v.v3.trigger == "X4" for v in marked.verdicts)
