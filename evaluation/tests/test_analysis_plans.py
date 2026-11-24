"""Phase 10: the E1-E4 analysis plans as data, with no outcome and an honest test registry (spec 3.7; PD-70)."""

from __future__ import annotations

import copy

import pytest

from evaluation.qcai_eval import analysis_plans, statistics


def plans():
    return analysis_plans.load_plans()


def test_the_shipped_plans_validate_and_cover_e1_to_e4_with_holm_at_0_05():
    raw = plans()
    assert tuple(raw["families"]) == ("E1", "E2", "E3", "E4")
    assert raw["alpha"] == "0.05" and raw["correction"] == "holm-per-family"
    ids = [h["id"] for family in raw["families"].values() for h in family["hypotheses"]]
    assert ids == ["H1a", "H1b", "H1c", "H2a", "H2b", "H2c", "H3a", "H3b", "H4a", "H4b"]


@pytest.mark.parametrize("key", sorted(analysis_plans.FORBIDDEN_KEYS))
def test_an_outcome_key_at_any_depth_is_refused(key):
    raw = copy.deepcopy(plans())
    raw["families"]["E3"]["hypotheses"][0][key] = "anything"
    with pytest.raises(analysis_plans.PlanError, match=key):
        analysis_plans.validate_plans(raw)


def test_ids_are_unique_tests_registered_and_criteria_from_table_xvii():
    raw = copy.deepcopy(plans())
    raw["families"]["E2"]["hypotheses"][0]["id"] = "H1a"
    with pytest.raises(analysis_plans.PlanError, match="appears twice"):
        analysis_plans.validate_plans(raw)
    raw = copy.deepcopy(plans())
    raw["families"]["E4"]["hypotheses"][1]["test"] = "mcnemar_exact+wilcoxon"
    with pytest.raises(analysis_plans.PlanError, match="wilcoxon"):
        analysis_plans.validate_plans(raw)
    raw = copy.deepcopy(plans())
    raw["families"]["E1"]["hypotheses"][0]["criteria"] = ["HR-9"]
    with pytest.raises(analysis_plans.PlanError, match="Table XVII"):
        analysis_plans.validate_plans(raw)
    for family in plans()["families"].values():
        for hypothesis in family["hypotheses"]:
            assert set(hypothesis["criteria"]) <= analysis_plans.TABLE_XVII


def test_every_implemented_test_names_a_callable_and_the_rest_say_not_implemented():
    raw = plans()
    implemented = [name for name, status in raw["tests"].items() if status == "implemented"]
    assert implemented == ["mcnemar_exact", "wilson_upper_bound", "holm"]
    assert all(callable(getattr(statistics, name)) for name in implemented)
    assert all(status.startswith("not implemented (DI-138)") for status in raw["tests"].values() if status != "implemented")
    broken = copy.deepcopy(raw)
    broken["tests"]["friedman"] = "implemented"
    with pytest.raises(analysis_plans.PlanError, match="friedman"):
        analysis_plans.validate_plans(broken)


def test_the_preregistration_is_generated_as_a_draft_with_every_test_status():
    text = analysis_plans.preregistration_markdown(plans())
    assert "**DRAFT - not filed with OSF (DI-131).**" in text
    assert "alpha = 0.05, Holm correction within each family" in text
    for name, status in plans()["tests"].items():
        assert f"| `{name}` | {status} |" in text
    assert "Not executed" in text
