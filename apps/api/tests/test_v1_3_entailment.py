"""V1.3, the entailment checker interface (Phase 4 spec 4.4; plan Phase 4 D "flag only, never HARD"; D-21 none; AC-4-7)."""

from __future__ import annotations

import dataclasses
import logging

import pytest

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.services.tutor_pipeline import contracts
from app.services.v1_checks.v1_3_entailment import CHECKERS, CheckerUnavailable, NullChecker, check_v1_3, get_checker
from app.services.v1_checks.rules import WIRED_CHECKERS
from v1_fakes import MULTI_CLAIM, AlwaysContradictedChecker, AlwaysSupportedChecker, InjectedClock, LateChecker, RaisingChecker, ScriptedChecker, WrongTypeChecker, dev_pipeline, run

PACKAGE = get_config_package(Settings())
V1 = PACKAGE.v1


def _locked():
    locked = run(dev_pipeline(), MULTI_CLAIM).locked
    assert len(locked.claims) >= 2
    return locked


def test_the_null_checker_flags_every_claim_without_a_call():
    locked = _locked()

    class Exploding(NullChecker):
        def check(self, claim, spans):  # pragma: no cover - must never run
            raise AssertionError("the NullChecker is never called")

    results = check_v1_3(locked, {}, checker=Exploding(), v1=V1, attempt=1)
    assert [(r.outcome, r.reason_code, r.claim_id, r.checker_model_id) for r in results] == [
        ("flag", "no_checker", claim.claim_id, "none") for claim in locked.claims]
    assert get_checker(PACKAGE).checker_model_id == "none" and PACKAGE.v1.checker_hosting == "none"


@pytest.mark.parametrize(
    ("label", "score", "reason", "outcome"),
    [("SUPPORTED", None, "supported", "pass"), ("SUPPORTED", 0.9, "supported", "pass"), ("SUPPORTED", 0.1, "below_support_threshold", "flag"),
     ("CONTRADICTED", 0.9, "contradicted", "flag"), ("NOT_ENOUGH_INFO", 0.5, "not_enough_info", "flag")],
)
def test_labels_and_scores_map_to_outcomes(label, score, reason, outcome):
    locked = _locked()
    scores: dict = {}
    results = check_v1_3(locked, {}, checker=ScriptedChecker([(label, score)]), v1=V1, attempt=2, scores=scores)
    assert {(r.reason_code, r.outcome, r.attempt) for r in results} == {(reason, outcome, 2)}
    assert set(scores) == {claim.claim_id for claim in locked.claims} and set(scores.values()) == {score}


def test_the_support_threshold_comes_from_the_package():
    locked = _locked()
    strict = dataclasses.replace(V1, support_threshold=0.95)
    assert {r.reason_code for r in check_v1_3(locked, {}, checker=ScriptedChecker([("SUPPORTED", 0.9)]), v1=strict, attempt=1)} == {"below_support_threshold"}
    assert {r.reason_code for r in check_v1_3(locked, {}, checker=ScriptedChecker([("SUPPORTED", 0.9)]), v1=V1, attempt=1)} == {"supported"}


@pytest.mark.parametrize("make", [RaisingChecker, WrongTypeChecker, "late"])
def test_an_unavailable_checker_is_one_response_level_abstain_and_is_logged(make, caplog):
    locked = _locked()
    clock = InjectedClock()
    checker = LateChecker(clock, V1.checker_timeout_ms + 1) if make == "late" else make()
    with caplog.at_level(logging.WARNING, logger="qcai.tutor"):
        results = check_v1_3(locked, {}, checker=checker, v1=V1, attempt=1, clock=clock)
    assert len(results) == 1
    (result,) = results
    assert (result.outcome, result.reason_code, result.claim_id, result.checker_model_id) == ("abstain", "checker_unavailable", None, checker.checker_model_id)
    (line,) = [r.json_fields for r in caplog.records if getattr(r, "json_fields", {}).get("event") == "tutor.v1.checker_unavailable"]
    assert line["cause"] == ("timeout" if make == "late" else "error")


def test_a_late_answer_within_the_timeout_is_used():
    locked = _locked()
    clock = InjectedClock()
    results = check_v1_3(locked, {}, checker=LateChecker(clock, V1.checker_timeout_ms - 1), v1=V1, attempt=1, clock=clock)
    assert {r.reason_code for r in results} == {"supported"}


def test_v1_3_never_hard_fails_in_any_configuration():
    assert "hard_fail" not in set(contracts.REASON_OUTCOMES["V1.3"].values())
    locked = _locked()
    for checker in (NullChecker(), AlwaysSupportedChecker(), AlwaysContradictedChecker(), RaisingChecker(), WrongTypeChecker()):
        assert all(r.outcome != "hard_fail" for r in check_v1_3(locked, {}, checker=checker, v1=V1, attempt=1))


def test_get_checker_refuses_an_unwired_hosting():
    assert set(CHECKERS) == set(WIRED_CHECKERS) == {"none"}
    other = dataclasses.replace(PACKAGE, v1=dataclasses.replace(V1, checker_hosting="local-nli"))
    with pytest.raises(CheckerUnavailable):
        get_checker(other)
    with pytest.raises(CheckerUnavailable):
        get_checker(dataclasses.replace(PACKAGE, v1=None))
