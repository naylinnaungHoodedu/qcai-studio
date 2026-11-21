"""V1.4 is the Phase 3 subset check (Phase 4 spec 4.5, conflict 6): one implementation, one seam."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services import claim_gate
from app.services.claim_gate import SubsetCheckResult
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline import pipeline as pipeline_module
from app.services.v1_checks.v1_4_subset import v1_4_result
from v1_fakes import MULTI_CLAIM, AlwaysSupportedChecker, dev_pipeline, run


@pytest.mark.parametrize("code", contracts.SUBSET_PROBLEM_CODES)
def test_each_subset_problem_code_is_a_hard_fail_with_its_code(code):
    result = v1_4_result(SubsetCheckResult(False, (code, "empty"), 1, 0, 0), fault=None, attempt=2)
    assert (result.outcome, result.reason_code, result.stage, result.attempt, result.ehmf_types) == ("hard_fail", code, "post_render", 2, ("D", "E"))


def test_a_pass_maps_and_a_fault_is_render_failed():
    assert v1_4_result(SubsetCheckResult(True, (), 2, 2, 0), fault=None, attempt=1).reason_code == "mapped"
    assert v1_4_result(None, fault="render", attempt=1).reason_code == "render_failed"
    assert v1_4_result(SubsetCheckResult(True, (), 2, 2, 0), fault="subset_check", attempt=3).outcome == "hard_fail"


def test_the_contract_codes_are_the_subset_checker_s():
    assert contracts.SUBSET_PROBLEM_CODES == claim_gate.PROBLEM_CODES
    assert contracts.REASON_OUTCOMES["V1.4"] == {"mapped": "pass", "render_failed": "hard_fail", **{code: "hard_fail" for code in claim_gate.PROBLEM_CODES}}


@pytest.mark.parametrize("mode", ["shadow", "enforce"])
def test_the_patched_pipeline_check_subset_is_the_one_v1_4_uses(monkeypatch, mode):
    seen = []
    real = claim_gate.check_subset

    def spy(rendered, locked):
        seen.append(rendered.attempt)
        return SubsetCheckResult(False, ("unmapped_factual_sentence",), 1, 0, 0)

    monkeypatch.setattr(pipeline_module, "check_subset", spy)
    result = run(dev_pipeline(Settings(v1_pipeline=mode), checker=AlwaysSupportedChecker()), MULTI_CLAIM)
    v1_4 = [r for r in result.entry.verification.checks if r.check_id == "V1.4"]
    assert [r.reason_code for r in v1_4] == ["unmapped_factual_sentence"] * 3
    # One subset check per V1 render attempt (and, in shadow, the Phase 3 composition's three before them).
    assert len(seen) == (6 if mode == "shadow" else 3)
    assert real is claim_gate.check_subset
