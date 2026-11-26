"""The E1-E4 analysis plans as data, and the pre-registration draft generated from them (spec 3.7, 10; PD-70).

Plan 12.7: "E1-E4 are pre-registered hypothesis tests (alpha = 0.05, Holm per family), not software gates". The plans hold
no outcome: the loader refuses any key that would carry one (`result`, `p_value`, `met`, ...), at any depth. The test
registry is honest: an `implemented` entry names a function of `statistics.py` listed in `statistics.REGISTERED_TESTS`
(never a name it imports); every other test is `not implemented`. Each hypothesis carries its endpoint, its comparison
(when its test compares arms, raters or conditions), its test, its sidedness (the test's: `SIDEDNESS`) and, for a
one-sided or equivalence test, its margin, the null value; where VBT RevB Sec. X-A states the null, the margin must be
that value (`PAPER_NULLS`). H4b carries the paper's EQC reliability condition (`H4B_CONFIRMATORY_IF`), and the secondary
analyses the paper and Table XVII name are registered (`SECONDARY_ANALYSES`), implemented or not. Every Table XVII row
Phase 10 tests (`PHASE10_CRITERIA`) is registered once a family's hypothesis criterion or `criteria_only` entry, and each
family states its data (`data`). Nothing is filed with OSF while D-08
is open (DI-131), so the plans' status must start with `draft` and may not use the word `registered`.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping

from . import statistics
from .canonical import canonical_sha256
from . import inputs

REPO_ROOT = Path(__file__).resolve().parents[2]
PLANS_PATH = REPO_ROOT / "evaluation" / "config" / "analysis_plans_v1.json"
FORBIDDEN_KEYS = frozenset({"result", "results", "p_value", "estimate", "met", "supported", "outcome", "decision", "observed"})
FAMILIES = ("E1", "E2", "E3", "E4")
TABLE_XVII = frozenset({"F-1", "F-2", "F-3", "V-1", "V-2", "V-3", "V-4", "HR-1", "HR-2", "HR-3", "LQ-1", "LQ-2", "LQ-3",
                        "UE-1", "UE-2", "UE-3", "MR-1", "MR-2", "MR-3"})
# The Table XVII rows Phase 10 tests: plan 9.2 "Phase 10 tests research criteria V-2, V-4, HR-1..MR-3" (HR-1 to MR-3 in
# Table XVII's order), and V-3, whose Phase column in plan 15.1 reads "6,10". Every one is a hypothesis criterion or a
# `criteria_only` entry of some family (a criteria_only entry starts with its row id).
PHASE10_CRITERIA = frozenset({"V-2", "V-3", "V-4", "HR-1", "HR-2", "HR-3", "LQ-1", "LQ-2", "LQ-3", "UE-1", "UE-2", "UE-3",
                              "MR-1", "MR-2", "MR-3"})


# The sidedness of each registered test's p-value (VBT RevB Sec. X-A: "Each hypothesis enters Holm through one p-value").
SIDEDNESS = {"mcnemar_exact": "two", "paired_tost": "equivalence", "friedman": "omnibus", "bootstrap_one_sided": "one",
             "paired_bootstrap_one_sided": "one", "cluster_bootstrap_lower_bound": "one", "cluster_bootstrap_bca_one_sided": "one",
             "paired_bootstrap_auc_one_sided": "one", "two_level_bootstrap_share_le_zero": "one", "wilson_upper_bound": "one"}
# Tests that compare two or more arms, raters or conditions, so a hypothesis using one names its comparison.
COMPARING = frozenset({"mcnemar_exact", "paired_tost", "friedman", "paired_bootstrap_one_sided", "cluster_bootstrap_bca_one_sided",
                       "paired_bootstrap_auc_one_sided", "two_level_bootstrap_share_le_zero"})
# The nulls VBT RevB Sec. X-A states: H1c "H0: difference <= -5 points"; H2b "(H0: DR <= 1)" ("concludes DR > 1 if the
# lower bound of its cluster-bootstrap CI exceeds 1"); H4b's TOST "margin +/-0.5"; H2a, H2c and H4a against no difference.
PAPER_NULLS = {"H1c": "-0.05", "H2a": "0", "H2b": "1", "H2c": "0", "H4a": "0", "H4b": "0.5"}
# VBT RevB Sec. X-A: "EQC is confirmatory only if ICC(2,k) >= 0.50 and Cronbach's alpha >= 0.70 across its six scales;
# otherwise the equivalence part of H4b is reported as inconclusive."
H4B_CONFIRMATORY_IF = {"icc_2k_min": "0.50", "cronbach_alpha_min": "0.70", "scales": 6, "applies_to": "paired_tost",
                       "otherwise": "inconclusive", "computed_by": ["icc_2k", "cronbach_alpha"]}
# The secondary and ancillary analyses VBT RevB names: Sec. X-A (and E1's labelling); Table I's H1a secondary endpoint ("the
# error rate among answers is a secondary endpoint"); and Sec. VIII-B's agent-verifier report ("that verifier's E2
# accuracy is reported with and without them", the items changed after one of its flags); and Table XVII's UE-2 ("a
# cumulative-link model of trust by arm adjusted for correctness") and V-4 ("DR and neff reported with 95% CIs").
SECONDARY_ANALYSES = ("mixed_effects_logistic", "cumulative_link_mixed_model", "cliffs_delta", "ordinal_sensitivity_eqc",
                      "icc_2k", "cronbach_alpha", "prediction_powered_inference", "error_rate_among_answers",
                      "agent_verifier_accuracy_with_and_without_changed_items", "cumulative_link_trust_by_arm",
                      "effective_sample_size")


class PlanError(ValueError):
    """An analysis plan that asserts an outcome, repeats a hypothesis or names an unregistered test."""


def _forbidden(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, entry in value.items():
            where = f"{path}.{key}" if path else str(key)
            if key in FORBIDDEN_KEYS:
                found.append(where)
            found += _forbidden(entry, where)
    elif isinstance(value, list):
        for index, entry in enumerate(value):
            found += _forbidden(entry, f"{path}[{index}]")
    return found


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(entry, str) for entry in value)


def _shape_problem(raw: Any) -> str | None:
    """The first container of the plans that is not of the type the checks below and the pre-registration read, or None:
    the plans, `tests` and `secondary_analyses` objects; each family an object whose `hypotheses` is a list of objects
    with a string `id` and string lists for `criteria` and `criteria_only`; each secondary analysis's `for` a string
    list. A value of the wrong type is a PlanError (exit 2 in the runner), never a TypeError or AttributeError."""
    if not isinstance(raw, Mapping):
        return "plans: not an object"
    for name in ("families", "tests", "secondary_analyses"):
        if not isinstance(raw.get(name), Mapping):
            return f"{name}: not an object"
    for family, body in raw["families"].items():
        if not isinstance(body, Mapping):
            return f"{family}: not an object"
        if "criteria_only" in body and not _strings(body["criteria_only"]):
            return f"{family}.criteria_only: not a list of strings"
        hypotheses = body.get("hypotheses", [])
        if not isinstance(hypotheses, list) or not all(isinstance(hypothesis, Mapping) for hypothesis in hypotheses):
            return f"{family}.hypotheses: not a list of objects"
        for hypothesis in hypotheses:
            if not isinstance(hypothesis.get("id"), str):
                return f"{family}.hypotheses: an id is not a string"
            if "criteria" in hypothesis and not _strings(hypothesis["criteria"]):
                return f"{family}.{hypothesis['id']}.criteria: not a list of strings"
    for name, entry in raw["secondary_analyses"].items():
        if isinstance(entry, Mapping) and "for" in entry and not _strings(entry["for"]):
            return f"secondary_analyses.{name}.for: not a list of strings"
    return None


def validate_plans(raw: Mapping[str, Any]) -> None:
    problem = _shape_problem(raw)
    if problem is not None:
        raise PlanError(problem)
    forbidden = _forbidden(raw)
    if forbidden:
        raise PlanError(f"outcome keys are refused in an analysis plan: {', '.join(forbidden)}")
    if raw.get("plans") != "analysis-plans-v1" or raw.get("alpha") != "0.05" or raw.get("correction") != "holm-per-family":
        raise PlanError("plans: must be analysis-plans-v1 at alpha 0.05 with Holm per family")
    status = raw.get("status")
    if not isinstance(status, str) or not status.startswith("draft") or "registered" in status.lower():
        raise PlanError("status: an unfiled plan is a draft and never claims to be registered (DI-131)")
    families = raw.get("families") or {}
    if tuple(families) != FAMILIES:
        raise PlanError("families: must be exactly E1, E2, E3 and E4")
    tests = raw.get("tests") or {}
    for name, status in tests.items():
        _check_status(f"tests.{name}", name, status)
    secondary = raw.get("secondary_analyses")
    if not isinstance(secondary, Mapping) or set(secondary) != set(SECONDARY_ANALYSES):
        raise PlanError(f"secondary_analyses: must register exactly {', '.join(SECONDARY_ANALYSES)}")
    for name, entry in secondary.items():
        if not isinstance(entry, Mapping) or not isinstance(entry.get("analysis"), str) or not isinstance(entry.get("for"), list):
            raise PlanError(f"secondary_analyses.{name}: needs an analysis and the hypotheses or criteria it serves")
        _check_status(f"secondary_analyses.{name}", name, entry.get("status"))
    seen: set[str] = set()
    covered: set[str] = set()
    for family, body in families.items():
        if not isinstance(body.get("data"), str) or not body["data"]:
            raise PlanError(f"{family}: states its data")
        for entry in body.get("criteria_only", []):
            criterion = entry.split(" ", 1)[0] if isinstance(entry, str) else None
            if criterion not in TABLE_XVII:
                raise PlanError(f"{family}: criteria_only entry {entry!r} does not start with a Table XVII row")
            covered.add(criterion)
        for hypothesis in body.get("hypotheses", []):
            identifier = hypothesis.get("id")
            if identifier in seen:
                raise PlanError(f"{family}: hypothesis {identifier} appears twice")
            seen.add(identifier)
            parts = str(hypothesis.get("test", "")).split("+")
            for part in parts:
                if part not in tests:
                    raise PlanError(f"{family}.{identifier}: test {part} is not in the registry")
                if part not in SIDEDNESS:
                    raise PlanError(f"{family}.{identifier}: {part} is not a hypothesis test")
            _check_hypothesis(f"{family}.{identifier}", identifier, hypothesis, parts, secondary)
            for criterion in hypothesis.get("criteria", []):
                if criterion not in TABLE_XVII:
                    raise PlanError(f"{family}.{identifier}: criterion {criterion} is not a Table XVII row")
                covered.add(criterion)
    if covered != PHASE10_CRITERIA:
        missing, extra = sorted(PHASE10_CRITERIA - covered), sorted(covered - PHASE10_CRITERIA)
        raise PlanError(f"criteria: every Table XVII row Phase 10 tests is registered and no other (missing {missing}, extra {extra})")


def _check_status(where: str, name: str, status: Any) -> None:
    if status == "implemented":
        function = getattr(statistics, name, None)
        if name not in statistics.REGISTERED_TESTS or not callable(function) \
                or getattr(function, "__module__", None) != statistics.__name__:
            raise PlanError(f"{where}: implemented but not a registered test defined in statistics.py")
    elif not (isinstance(status, str) and status.startswith("not implemented")):
        raise PlanError(f"{where}: status must be implemented or not implemented")


def _decimal(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        Fraction(value)
    except (ValueError, ZeroDivisionError):
        return False
    return True


def _check_hypothesis(where: str, identifier: Any, hypothesis: Mapping[str, Any], parts: list[str],
                      secondary: Mapping[str, Any]) -> None:
    """Sidedness, margin (the null) and comparison, as VBT RevB Sec. X-A and Table I state them."""
    sided = "+".join(SIDEDNESS[part] for part in parts)
    if hypothesis.get("sided") != sided:
        raise PlanError(f"{where}: sided must be {sided} (the registered test's p-value)")
    needs_margin = any(SIDEDNESS[part] in ("one", "equivalence") for part in parts)
    if needs_margin and not _decimal(hypothesis.get("margin")):
        raise PlanError(f"{where}: a one-sided or equivalence test needs its margin (the null value) as a decimal string")
    if not needs_margin and "margin" in hypothesis:
        raise PlanError(f"{where}: a margin belongs to a one-sided or equivalence test only")
    if identifier in PAPER_NULLS and (not _decimal(hypothesis.get("margin"))
                                      or Fraction(hypothesis["margin"]) != Fraction(PAPER_NULLS[identifier])):
        raise PlanError(f"{where}: margin must be the paper's null, {PAPER_NULLS[identifier]}")
    comparison = hypothesis.get("comparison")
    if any(part in COMPARING for part in parts):
        if not isinstance(comparison, list) or len(comparison) < 2 or not all(isinstance(entry, str) and entry for entry in comparison):
            raise PlanError(f"{where}: a comparing test names its comparison (two or more arms, raters or conditions)")
    elif comparison is not None:
        raise PlanError(f"{where}: a single-quantity test has no comparison")
    if identifier == "H4b":
        if hypothesis.get("confirmatory_if") != H4B_CONFIRMATORY_IF:
            raise PlanError(f"{where}: confirmatory_if must be the paper's EQC reliability condition (ICC(2,k) >= 0.50, "
                            "Cronbach's alpha >= 0.70, otherwise inconclusive)")
    elif "confirmatory_if" in hypothesis:
        raise PlanError(f"{where}: only H4b carries a confirmatory condition")


def load_plans(path: Path = PLANS_PATH) -> dict[str, Any]:
    raw = inputs.read_json(path)
    validate_plans(raw)
    return raw


def plans_sha256(raw: Mapping[str, Any]) -> str:
    return canonical_sha256(raw)


def preregistration_markdown(raw: Mapping[str, Any]) -> str:
    """The pre-registration DRAFT (`docs/evaluation/phase10/preregistration-draft.md`), generated from the plans."""
    validate_plans(raw)
    lines = [
        "# Pre-registration draft: E1-E4 (ULQS v1.0)",
        "",
        "**DRAFT - not filed with OSF (DI-131).** Generated by `scripts/check_research_harness.py --write` from",
        "`evaluation/config/analysis_plans_v1.json`; `--check` in CI proves this file is current. Nothing here is executed:",
        "no hypothesis has been tested and no HR-1 to MR-3 outcome is asserted (plan Phase 10 P; invariant 9).",
        "",
        f"- Analysis plans: `{raw['plans']}`, canonical sha256 `{plans_sha256(raw)}`.",
        f"- Status: {raw['status']}.",
        f"- Significance: alpha = {raw['alpha']}, Holm correction within each family (plan 12.7: \"E1-E4 are pre-registered",
        "  hypothesis tests (alpha = 0.05, Holm per family), not software gates\").",
        f"- Source: {raw['source']}.",
        "- Confirmatory runs need a filed IRB letter and an OSF DOI whose record pins this plan's sha256 (AC-10-5).",
        "",
    ]
    for family, body in raw["families"].items():
        lines += [f"## {family} ({body['rq']})", ""]
        if body.get("data"):
            lines += [f"Data: {body['data']}.", ""]
        lines += ["| Hypothesis | Endpoint | Comparison | Test | Sided | Margin (null) | Table XVII criteria |",
                  "|---|---|---|---|---|---|---|"]
        for hypothesis in body["hypotheses"]:
            comparison = " vs ".join(hypothesis.get("comparison", [])) or "-"
            test = hypothesis["test"] + (f" (resamples {hypothesis['resamples']})" if "resamples" in hypothesis else "")
            criteria = ", ".join(hypothesis.get("criteria", [])) or "-"
            lines.append(f"| {hypothesis['id']} | {hypothesis['endpoint']} | {comparison} | `{test}` | {hypothesis['sided']} | "
                         f"{hypothesis.get('margin', '-')} | {criteria} |")
        lines.append("")
        for hypothesis in body["hypotheses"]:
            condition = hypothesis.get("confirmatory_if")
            if condition:
                lines += [f"{hypothesis['id']} is confirmatory only if ICC(2,k) >= {condition['icc_2k_min']} and Cronbach's alpha >= "
                          f"{condition['cronbach_alpha_min']} across the EQC's {condition['scales']} scales (computed by "
                          f"{' and '.join(f'`{name}`' for name in condition['computed_by'])}); otherwise the equivalence part "
                          f"(`{condition['applies_to']}`) is reported as {condition['otherwise']}.", ""]
        if body.get("criteria_only"):
            lines += [f"Criteria reported without a family test: {'; '.join(body['criteria_only'])}.", ""]
        if body.get("labelling"):
            lines += [f"Labelling: {body['labelling']}.", ""]
    lines += ["## Test registry", "", "| Test | Status |", "|---|---|"]
    lines += [f"| `{name}` | {status} |" for name, status in raw["tests"].items()]
    lines += ["", "## Secondary and ancillary analyses", "", "| Analysis | For | Description | Status |", "|---|---|---|---|"]
    lines += [f"| `{name}` | {', '.join(entry['for'])} | {entry['analysis']} | {entry['status']} |"
              for name, entry in raw["secondary_analyses"].items()]
    lines += ["", "Not executed: every hypothesis above awaits the frozen ULQS, the IRB letter, the OSF DOI and the research data",
              "plane (DI-129..DI-148).", ""]
    return "\n".join(lines)
