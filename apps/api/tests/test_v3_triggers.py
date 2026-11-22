"""Phase 6 triggers X1-X6 (plan Phase 6 J "Unit per trigger"; plan 6.3 "one test per trigger"; Phase 6 spec 4.1, 13.2).

Records come from the development pipeline (query 30 is an assessment context whose locked claims form the synthetic
development critical registry; MULTI_CLAIM's are not critical) and from tutor_fakes.make_entry. No network, no
learner data.
"""

from __future__ import annotations

from fractions import Fraction
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.services.tutor_pipeline.contracts import Sufficiency
from app.services.tutor_pipeline.evidential import ExtractiveD19Generator
from app.services.v3 import triggers
from app.services.v3.queue import parse_entry
from tutor_fakes import make_entry
from v1_fakes import MULTI_CLAIM, dev_pipeline, run
from v2_fakes import RevisingGenerator, make_registry
import v3_fakes

PACKAGE = get_config_package(Settings())
MARGINS = dict(PACKAGE.v1.x4_margin)


@pytest.fixture(scope="module")
def critical_target():
    base = dev_pipeline()
    claims = v3_fakes.critical_claims_of(base)
    return base, next(claim for claim in claims if claim.claim_id == v3_fakes.CRITICAL_CLAIMS[0])


def _objected(base, target, *, ehmf="A", fail_calls=(), cache=None, settings=None):
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    adapters = v3_fakes.objecting_adapters(registry, "fake-beta-v1", {target.text: tuple(target.span_ids)}, ehmf=ehmf, fail_calls=fail_calls)
    return v3_fakes.shadow_v3_record(settings=settings, adapters=adapters, generator=RevisingGenerator(ExtractiveD19Generator(base.package)),
                                     cache=cache)[1]


def _verdict(entry, claim_id):
    return next(verdict for verdict in entry.verification.verdicts if verdict.claim_id == claim_id)


def _with_verdict(entry, claim_id, **v2_update):
    verdicts = tuple(verdict.model_copy(update={"v2": verdict.v2.model_copy(update=v2_update)}) if verdict.claim_id == claim_id else verdict
                     for verdict in entry.verification.verdicts)
    return entry.model_copy(update={"verification": entry.verification.model_copy(update={"verdicts": verdicts})})


# --------------------------------------------------------------------------------------------------------- X1


def test_x1_fires_on_a_critical_tier_1_claim_with_an_objection_on_its_final_verdict(critical_target):
    base, target = critical_target
    entry = _objected(base, target)
    verdict = _verdict(entry, target.claim_id)
    assert verdict.v2.critical is True and verdict.v2.tier == 1 and verdict.v2.objections == 1
    assert triggers.x1_claims(entry) == {target.claim_id}


def test_x1_fires_when_a_correction_cycle_listed_the_claim_though_its_final_tally_passed(critical_target):
    # The objector fails its next call and leaves the panel: the claim's final verdict (REDUCED-2, 1oo2) has no objection,
    # but both claim-loop cycles listed it.
    base, target = critical_target
    entry = _objected(base, target, fail_calls=(4,), cache=v3_fakes.NoCache())
    verdict = _verdict(entry, target.claim_id)
    assert verdict.v2.objections == 0 and verdict.v2.outcome == "pass" and verdict.v2.mode == "REDUCED-2"
    assert all(target.claim_id in correction.failed_claim_ids for correction in entry.verification.v2.corrections)
    assert triggers.x1_claims(entry) == {target.claim_id}
    # An alignment re-render lists the shown claims, not objections: a cycle past the verdicts' own is not read.
    later = entry.verification.v2.corrections[-1].model_copy(update={"cycle": 2})
    block = entry.verification.v2.model_copy(update={"corrections": (entry.verification.v2.corrections[0].model_copy(update={"failed_claim_ids": ()}), later)})
    shifted = entry.model_copy(update={"verification": entry.verification.model_copy(update={
        "v2": block, "verdicts": tuple(item.model_copy(update={"v2": item.v2.model_copy(update={"cycle": 1})}) for item in entry.verification.verdicts)})})
    assert triggers.x1_claims(shifted) == frozenset()


def test_x1_does_not_fire_without_critical_at_tier_2_or_without_a_v2_verdict(critical_target):
    base, target = critical_target
    entry = _objected(base, target)
    assert triggers.x1_claims(_with_verdict(entry, target.claim_id, critical=False)) == frozenset()
    assert triggers.x1_claims(_with_verdict(entry, target.claim_id, tier=2)) == frozenset()
    assert triggers.x1_claims(make_entry()) == frozenset()            # a legacy record has no V2 verdict
    assert triggers.x1_claims(run(dev_pipeline(), v3_fakes.CRITICAL_QUERY).entry) == frozenset()   # V1 only (MODEL_GATEWAY off)


def test_x1_needs_the_environment_s_registry_a_non_critical_claim_with_an_objection_does_not_fire():
    base = dev_pipeline()
    claim = run(base, MULTI_CLAIM).locked.claims[0]
    assert claim.claim_id not in v3_fakes.CRITICAL_CLAIMS
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    adapters = v3_fakes.objecting_adapters(registry, "fake-beta-v1", {claim.text: tuple(claim.span_ids)})
    entry = v3_fakes.shadow_v3_record(MULTI_CLAIM, adapters=adapters)[1]
    assert _verdict(entry, claim.claim_id).v2.objections == 1 and triggers.x1_claims(entry) == frozenset()


# --------------------------------------------------------------------------------------------------------- X2


def test_x2_needs_the_x2_escalation_and_an_objection_of_type_a_or_b(critical_target):
    base, target = critical_target
    for ehmf, fires in (("A", True), ("B", True), ("C", False), ("D", False)):
        entry = _objected(base, target, ehmf=ehmf)
        verdict = _verdict(entry, target.claim_id)
        assert verdict.v3.escalation == "X2", ehmf
        assert (target.claim_id in triggers.x2_claims(entry)) is fires, ehmf
        # Every exhausted claim is queued with its reason whatever the type.
        assert "v2_correction_exhausted" in triggers.queue_reasons(verdict), ehmf
    assert triggers.family_objection_types(None) == ()


# --------------------------------------------------------------------------------------------------------- X3


def test_x3_fires_on_one_flag_or_more():
    assert triggers.x3_fires(0) is False and triggers.x3_fires(1) is True and triggers.x3_fires(3) is True


# --------------------------------------------------------------------------------------------------------- X4


def _legacy_with(sufficiency):
    entry = make_entry()
    return entry.model_copy(update={"retrieval": entry.retrieval.model_copy(update={"sufficiency": sufficiency})})


def test_x4_on_a_legacy_record_applies_v1_5_s_rule_with_the_package_margin():
    p1 = dict(gate="p1-floor", threshold_version="score-floor-p1-v1", floor=6.0, margin=0.0)
    assert triggers.x4_fires(_legacy_with(Sufficiency(score=7.0, decision="answer", reason="answer", **p1)), x4_margin=MARGINS) is False
    assert triggers.x4_fires(_legacy_with(Sufficiency(score=6.0, decision="answer", reason="answer", **p1)), x4_margin=MARGINS) is False
    # No recorded score cannot be shown to clear the margin: V1.5 marks it.
    assert triggers.x4_fires(_legacy_with(Sufficiency(score=None, decision="answer", reason="answer", **p1)), x4_margin=MARGINS) is True
    # A sufficiency abstention never marks.
    assert triggers.x4_fires(_legacy_with(Sufficiency(score=1.0, decision="abstain", reason="below_floor", **p1)), x4_margin=MARGINS) is False
    bm = dict(gate="bm25f-v1", threshold_version="bm25f-v1", floor=2.35, margin=2.4)
    assert triggers.x4_fires(_legacy_with(Sufficiency(score=3.0, decision="answer", reason="answer", **bm)), x4_margin=MARGINS) is True
    assert triggers.x4_fires(_legacy_with(Sufficiency(score=9.0, decision="answer", reason="answer", **bm)), x4_margin=MARGINS) is False
    assert triggers.x4_fires(_legacy_with(None), x4_margin=MARGINS) is False
    assert triggers.x4_fires(_legacy_with(Sufficiency(score=3.0, decision="answer", reason="answer", **bm)), x4_margin={}) is False


def test_x4_on_a_verified_record_is_its_v1_5_mark_and_agrees_with_the_x4_margin_intent():
    base = dev_pipeline()
    import json

    # In-domain query 139 is the development fixture's one V1.5 near miss under bm25f-v1 (margin 2.4); the first 20 are not.
    in_domain = json.loads(v3_fakes.QUERIES_PATH.read_text(encoding="utf-8"))["in_domain"]
    queries = [item["query"] for item in in_domain[:20]] + [in_domain[139]["query"]]
    marked = unmarked = 0
    for query in queries:
        entry = run(base, query).entry
        verdicts = entry.verification.verdicts
        fires = triggers.x4_fires(entry, x4_margin=MARGINS)
        if verdicts:
            assert fires == any(verdict.v3 is not None and "x4_margin" in verdict.v3.reasons for verdict in verdicts), query
        marked += int(fires)
        unmarked += int(not fires)
    assert marked >= 1 and unmarked >= 1


# --------------------------------------------------------------------------------------------------------- X5


def test_x5_a_known_key_with_a_new_version_is_a_change_and_an_unknown_key_a_first_sighting():
    sightings = (("verifier:fake-alpha-verifier", "2026-11-22"), ("verifier:new-model", "2026-01-01"))
    changes = triggers.x5_model_changes({"verifier:fake-alpha-verifier": "2026-11-21"}, sightings)
    assert changes == (triggers.ModelChange("verifier:fake-alpha-verifier", "2026-11-21", "2026-11-22"),)
    assert triggers.x5_model_changes({}, sightings) == ()   # a baseline while nothing is known
    assert triggers.x5_model_changes({"verifier:fake-alpha-verifier": "2026-11-22"}, sightings) == ()


def test_x5_record_and_registry_sightings_and_windows(critical_target):
    base, target = critical_target
    entry = _objected(base, target)
    keys = {key for key, _ in triggers.record_sightings(entry)}
    assert {"verifier:fake-alpha-verifier", "verifier:fake-beta-verifier", "verifier:fake-gamma-verifier", "checker:V1.3"} <= keys
    assert any(key.startswith("generator:") for key in keys)
    legacy = triggers.record_sightings(make_entry())
    assert legacy == (("generator:contained-answers-v1", "extractive-lexically-screened"),)
    assert {key for key, _ in triggers.registry_sightings(make_registry(("fake-alpha", "fake-beta")))} == {
        "verifier:fake-alpha-verifier", "verifier:fake-beta-verifier"}
    assert triggers.x5_active([(10, 5)], 11) is True
    assert triggers.x5_active([(10, 5)], 10) is False      # a window covers the deliveries after its event
    assert triggers.x5_active([(10, 0)], 11) is False      # a spent window
    assert triggers.x5_active([], 11) is False


# --------------------------------------------------------------------------------------------------- reasons, types


def test_queue_reasons_v1_3_flag_only_without_a_completed_vote_and_x4_is_the_response_item():
    intent = SimpleNamespace(reasons=("v1_3_flag", "v1_8_misconception", "x4_margin"))
    assert triggers.queue_reasons(SimpleNamespace(v3=intent, v2=None)) == {"v1_3_flag", "v1_8_misconception"}
    assert triggers.queue_reasons(SimpleNamespace(v3=intent, v2=SimpleNamespace(outcome="withheld"))) == {"v1_3_flag", "v1_8_misconception"}
    for outcome in ("pass", "fail"):
        assert triggers.queue_reasons(SimpleNamespace(v3=intent, v2=SimpleNamespace(outcome=outcome))) == {"v1_8_misconception"}
    assert triggers.queue_reasons(SimpleNamespace(v3=None, v2=None)) == frozenset()


def test_a_disclosed_conflict_weighs_nothing_and_non_pass_v1_results_name_their_types():
    disclosed = SimpleNamespace(check_id="V1.7", reason_code="conflict_disclosed", outcome="flag", ehmf_types=("D",), claim_id=None)
    flagged = SimpleNamespace(check_id="V1.3", reason_code="not_entailed", outcome="flag", ehmf_types=("A", "B", "C"), claim_id="claim-x")
    passed = SimpleNamespace(check_id="V1.2", reason_code="bound", outcome="pass", ehmf_types=("A", "B"), claim_id="claim-x")
    assert triggers.claim_types(SimpleNamespace(v2=None, v1=(disclosed, passed))) == frozenset()
    assert triggers.claim_types(SimpleNamespace(v2=None, v1=(flagged,))) == {"A", "B", "C"}
    withheld = SimpleNamespace(check_id="V1.7", reason_code="conflict_withheld", outcome="flag", ehmf_types=("D",), claim_id=None)
    record = SimpleNamespace(verification=SimpleNamespace(verdicts=(), checks=(disclosed, withheld)))
    assert triggers.response_types(record) == {"D"}


def test_evaluate_emits_claim_items_for_triggers_and_reasons_and_a_response_item_for_x4(critical_target):
    base, target = critical_target
    entry = _objected(base, target)
    result = triggers.evaluate(entry, x4_margin=MARGINS)
    assert result.record_kind == "shadow"
    (item,) = [spec for spec in result.items if spec.claim_key == target.claim_id]
    assert item.triggers == {"X1", "X2"} and item.held and item.subject == "claim" and "A" in item.ehmf_types
    assert item.k == Fraction(2, 3)
    marked = triggers.evaluate(_legacy_with(Sufficiency(score=None, gate="p1-floor", threshold_version="v", floor=6.0, margin=0.0,
                                                        decision="answer", reason="answer")), x4_margin=MARGINS)
    assert marked.record_kind == "delivery" and [(spec.subject, spec.triggers, spec.ehmf_types) for spec in marked.items] == [
        ("response", {"X4"}, {"A"})]
    assert triggers.evaluate(make_entry(), x4_margin=MARGINS).items == ()


def test_an_unknown_entry_schema_or_an_invalid_entry_is_unparsed():
    assert parse_entry(SimpleNamespace(entry_schema="ledger-entry-v9", entry="{}")) is None
    assert parse_entry(SimpleNamespace(entry_schema="ledger-entry-v1", entry="{\"not\": \"an entry\"}")) is None
    assert parse_entry(None) is None
    entry = make_entry()
    assert parse_entry(SimpleNamespace(entry_schema="ledger-entry-v1", entry=entry.model_dump_json())) == entry
