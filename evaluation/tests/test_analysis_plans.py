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
    assert implemented == ["mcnemar_exact", "wilson_upper_bound", "holm", "paired_bootstrap_one_sided", "cluster_bootstrap_bca_one_sided",
                           "cluster_bootstrap_lower_bound", "bootstrap_one_sided", "paired_bootstrap_auc_one_sided",
                           "two_level_bootstrap_share_le_zero", "friedman", "paired_tost"]
    assert all(callable(getattr(statistics, name)) for name in implemented)
    assert set(implemented) == set(statistics.REGISTERED_TESTS)
    assert all(getattr(statistics, name).__module__ == statistics.__name__ for name in statistics.REGISTERED_TESTS)
    assert all(status.startswith("not implemented (DI-138)") for status in raw["tests"].values() if status != "implemented")
    honest = copy.deepcopy(raw)
    honest["tests"]["ordinal_cumulative_link"] = "not implemented (DI-138)"
    analysis_plans.validate_plans(honest)
    honest["tests"]["ordinal_cumulative_link"] = "pending"
    with pytest.raises(analysis_plans.PlanError, match="ordinal_cumulative_link"):
        analysis_plans.validate_plans(honest)
    broken = copy.deepcopy(raw)
    broken["tests"]["wilcoxon_signed_rank"] = "implemented"  # no such callable in statistics.py
    with pytest.raises(analysis_plans.PlanError, match="wilcoxon_signed_rank"):
        analysis_plans.validate_plans(broken)


@pytest.mark.parametrize("name", ["log", "sqrt", "Fraction", "normal_cdf", "auc", "comb"])
def test_a_name_statistics_py_imports_or_a_helper_is_never_an_implemented_test(name):
    # Each of these is a callable attribute of statistics.py (imported from math or fractions, or a helper), not a test.
    assert callable(getattr(statistics, name))
    raw = copy.deepcopy(plans())
    raw["tests"][name] = "implemented"
    with pytest.raises(analysis_plans.PlanError, match=f"tests.{name}: implemented but not a registered test"):
        analysis_plans.validate_plans(raw)


def _hypothesis(raw, identifier):
    return next(h for family in raw["families"].values() for h in family["hypotheses"] if h["id"] == identifier)


def test_every_hypothesis_carries_its_sidedness_margin_and_comparison_with_the_paper_s_nulls():
    raw = plans()
    for family in raw["families"].values():
        for hypothesis in family["hypotheses"]:
            parts = hypothesis["test"].split("+")
            assert hypothesis["sided"] == "+".join(analysis_plans.SIDEDNESS[part] for part in parts), hypothesis["id"]
            if any(analysis_plans.SIDEDNESS[part] in ("one", "equivalence") for part in parts):
                assert "margin" in hypothesis, hypothesis["id"]
            if any(part in analysis_plans.COMPARING for part in parts):
                assert len(hypothesis["comparison"]) >= 2, hypothesis["id"]
    # VBT RevB Sec. X-A: "H2b concludes DR > 1 if the lower bound of its cluster-bootstrap CI exceeds 1" (H0: DR <= 1).
    assert _hypothesis(raw, "H2b")["margin"] == "1" and _hypothesis(raw, "H1c")["margin"] == "-0.05"
    # Table I: H2c is a "Paired bootstrap comparison of AUCs", novices versus the panel.
    h2c = _hypothesis(raw, "H2c")
    assert h2c["test"] == "paired_bootstrap_auc_one_sided" and h2c["comparison"] == ["panel", "novices"]
    for identifier, edit, match in (
            ("H2b", lambda h: h.pop("margin"), "needs its margin"),
            ("H2b", lambda h: h.update(margin="0"), "the paper's null, 1"),
            ("H1c", lambda h: h.update(margin="0"), "the paper's null, -0.05"),
            ("H4b", lambda h: h.update(margin="0.4"), "the paper's null, 0.5"),
            ("H2c", lambda h: h.pop("comparison"), "names its comparison"),
            ("H2c", lambda h: h.update(comparison=["panel"]), "names its comparison"),
            ("H2b", lambda h: h.update(comparison=["panel", "novices"]), "has no comparison"),
            ("H2a", lambda h: h.pop("sided"), "sided must be one"),
            ("H1a", lambda h: h.update(sided="one"), "sided must be two"),
            ("H1a", lambda h: h.update(margin="0"), "a margin belongs"),
            ("H3b", lambda h: h.update(test="holm"), "not a hypothesis test")):
        broken = copy.deepcopy(raw)
        edit(_hypothesis(broken, identifier))
        with pytest.raises(analysis_plans.PlanError, match=match):
            analysis_plans.validate_plans(broken)


def test_h4b_carries_the_eqc_reliability_condition_and_the_secondary_analyses_are_registered():
    raw = plans()
    # VBT RevB Sec. X-A: "EQC is confirmatory only if ICC(2,k) >= 0.50 and Cronbach's alpha >= 0.70 across its six scales".
    assert _hypothesis(raw, "H4b")["confirmatory_if"] == {"icc_2k_min": "0.50", "cronbach_alpha_min": "0.70", "scales": 6,
                                                          "applies_to": "paired_tost", "otherwise": "inconclusive",
                                                          "computed_by": ["icc_2k", "cronbach_alpha"]}
    assert set(raw["secondary_analyses"]) == {"mixed_effects_logistic", "cumulative_link_mixed_model", "cliffs_delta",
                                              "ordinal_sensitivity_eqc", "icc_2k", "cronbach_alpha", "prediction_powered_inference"}
    assert raw["secondary_analyses"]["mixed_effects_logistic"]["for"] == ["H1a", "H1b"]
    assert all(entry["status"] == "not implemented (DI-138)" for entry in raw["secondary_analyses"].values())
    for edit, match in ((lambda r: _hypothesis(r, "H4b").pop("confirmatory_if"), "EQC reliability condition"),
                        (lambda r: _hypothesis(r, "H4b")["confirmatory_if"].update(icc_2k_min="0.40"), "EQC reliability condition"),
                        (lambda r: _hypothesis(r, "H4b")["confirmatory_if"].update(otherwise="supported"), "EQC reliability condition"),
                        (lambda r: _hypothesis(r, "H4a").update(confirmatory_if={}), "only H4b"),
                        (lambda r: r["secondary_analyses"].pop("cliffs_delta"), "secondary_analyses"),
                        (lambda r: r["secondary_analyses"]["icc_2k"].update(status="implemented"), "not a registered test"),
                        (lambda r: r["secondary_analyses"]["cronbach_alpha"].update(status="planned"), "status must be")):
        broken = copy.deepcopy(raw)
        edit(broken)
        with pytest.raises(analysis_plans.PlanError, match=match):
            analysis_plans.validate_plans(broken)


def test_the_preregistration_is_generated_as_a_draft_with_every_test_status():
    text = analysis_plans.preregistration_markdown(plans())
    assert "**DRAFT - not filed with OSF (DI-131).**" in text and "- Status: draft, not filed with OSF (DI-131)." in text
    assert "registered" not in plans()["status"].lower()
    for status in ("registered-draft (not filed; DI-131)", "registered", "filed", None):
        with pytest.raises(analysis_plans.PlanError, match="status"):
            analysis_plans.validate_plans({**plans(), "status": status})
    assert "alpha = 0.05, Holm correction within each family" in text
    for name, status in plans()["tests"].items():
        assert f"| `{name}` | {status} |" in text
    assert "Not executed" in text
    assert "| H2b | DR > 1 | - | `cluster_bootstrap_lower_bound (resamples 10000)` | one | 1 | V-4 |" in text
    assert "H4b is confirmatory only if ICC(2,k) >= 0.50 and Cronbach's alpha >= 0.70" in text
    assert "| `cliffs_delta` | Likert summaries | medians and Cliff's delta | not implemented (DI-138) |" in text
