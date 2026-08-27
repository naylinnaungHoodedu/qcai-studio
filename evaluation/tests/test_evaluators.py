import pytest

from evaluation.qcai_eval.ablation import assert_arm_parity
from evaluation.qcai_eval.abstention import abstention_by_turn_depth, correct_abstention
from evaluation.qcai_eval.invariance import invariance_violations
from evaluation.qcai_eval.lqs_loader import LQSItem, validate_lqs
from evaluation.qcai_eval.statistics import mcnemar_exact, wilson_interval


def test_wilson_interval_and_paired_mcnemar_are_bounded_and_paired():
    interval = wilson_interval(8, 10)
    assert interval["lower"] < interval["rate"] < interval["upper"]
    comparison = mcnemar_exact([True, False, True], [True, True, False])
    assert comparison["discordant"] == 2
    assert 0 <= comparison["p_value"] <= 1


def test_lqs_freeze_validator_requires_all_strata_and_proposal_range():
    item = LQSItem("ULQS-A-001", "answerable_single_source", "Question?", True, ("span-1",))
    with pytest.raises(ValueError, match="120-200"):
        validate_lqs([item])
    validate_lqs([item], enforce_proposal_range=False)


def test_invariance_compares_claim_and_span_sets_not_presentation():
    result = invariance_violations(
        {
            "ULQS-G-001": [
                {"factual_claims": ["A"], "cited_span_ids": ["s1"], "presentation": "brief"},
                {"factual_claims": ["A"], "cited_span_ids": ["s1"], "presentation": "worked example"},
                {"factual_claims": ["A"], "cited_span_ids": ["s1"], "presentation": "socratic"},
            ],
            "ULQS-G-002": [
                {"factual_claims": ["A"], "cited_span_ids": ["s1"]},
                {"factual_claims": ["B"], "cited_span_ids": ["s1"]},
                {"factual_claims": ["A"], "cited_span_ids": ["s1"]},
            ],
        }
    )
    assert result["violating_item_ids"] == ["ULQS-G-002"]


def test_abstention_and_arm_parity_follow_frozen_design():
    rate = correct_abstention(
        [
            {"expected_answerable": True, "abstained": False},
            {"expected_answerable": False, "abstained": True},
            {"expected_answerable": False, "abstained": False},
        ]
    )
    assert rate["successes"] == 2
    assert set(abstention_by_turn_depth([{"expected_answerable": False, "abstained": True, "turn_depth": 2}])) == {2}
    shared = {"lqs": "v1", "model": "pinned"}
    assert_arm_parity(
        {
            "A": {"arm": "A", "retrieval_mode": "none", "abstention_gate": False, **shared},
            "B": {"arm": "B", "retrieval_mode": "lexical", "abstention_gate": True, **shared},
            "C": {"arm": "C", "retrieval_mode": "semantic", "abstention_gate": False, **shared},
            "D": {"arm": "D", "retrieval_mode": "semantic", "abstention_gate": True, **shared},
        }
    )
