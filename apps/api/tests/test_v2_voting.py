"""Phase 5 V2 voting arithmetic (plan Phase 5 J "Unit: voting arithmetic"; tasks 5.5, 5.6, 5.9; Phase 5 spec 4.9).

Exhaustive over every mode, tier and verdict tuple of N = 0..3 family verdicts, against a reference written from the
plan's words, not from the code: tier 1 1oo3, tier 2 2oo3, tier 3 equal weights (2/3 share, PD-25), REDUCED-2 1oo2,
REDUCED-1 tiers 1-2 withheld and queued and tier 3 by its rule on the remaining verifier (D-29 (a)), ZERO withheld;
"fails when at least M of N verifiers object" and NOT-ENOUGH-INFO objects.
"""

from __future__ import annotations

from fractions import Fraction
import itertools

import pytest

from app.services.v2_panel import rules
from app.services.v2_panel.voting import family_verdict, is_split, mode_for, objections, rule_for, tally

VERDICTS = ("SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_INFO")
MODE_BY_MEMBERS = {3: "FULL", 2: "REDUCED-2", 1: "REDUCED-1", 0: "ZERO"}


def reference(mode: str, tier: int, verdicts: tuple[str, ...]) -> str:
    """The plan's words: an objection is any verdict but SUPPORTED; MooN fails when at least M of N object."""
    n = len(verdicts)
    objecting = sum(1 for verdict in verdicts if verdict != "SUPPORTED")
    if mode == "ZERO" or (mode == "REDUCED-1" and tier in (1, 2)):
        return "withheld"
    if mode == "FULL" and tier == 1:
        return "fail" if objecting >= 1 else "pass"
    if mode == "FULL" and tier == 2:
        return "fail" if objecting >= 2 else "pass"
    if mode == "REDUCED-2":
        return "fail" if objecting >= 1 else "pass"
    supporting = n - objecting
    return "pass" if Fraction(supporting, n) >= Fraction(2, 3) else "fail"


def test_the_voting_arithmetic_is_exhaustive_over_tiers_members_and_verdicts():
    checked = 0
    for members, mode in MODE_BY_MEMBERS.items():
        assert mode_for(members) == mode
        for tier in rules.TIERS:
            rule = rule_for(rules.RULE_MATRIX, mode, tier)
            for verdicts in itertools.product(VERDICTS, repeat=members):
                assert tally(rule, list(verdicts)) == reference(mode, tier, verdicts), (mode, tier, verdicts)
                checked += 1
    assert checked == 3 * (27 + 9 + 3 + 1)
    # AC-5-4: one objection fails tier 1 and passes tier 2; NOT_ENOUGH_INFO is an objection.
    for objection in ("CONTRADICTED", "NOT_ENOUGH_INFO"):
        one = ["SUPPORTED", "SUPPORTED", objection]
        assert tally("1oo3", one) == "fail" and tally("2oo3", one) == "pass" and objections(one) == 1
    assert tally("equal-weights-share-v1", ["SUPPORTED"]) == "pass" and tally("equal-weights-share-v1", ["NOT_ENOUGH_INFO"]) == "fail"
    assert tally("equal-weights-share-v1", ["SUPPORTED", "CONTRADICTED"], threshold=(1, 2)) == "pass"


def test_a_rule_given_the_wrong_number_of_family_verdicts_is_refused():
    for rule, wrong in (("1oo3", 2), ("2oo3", 1), ("1oo2", 3), ("equal-weights-share-v1", 0)):
        with pytest.raises(ValueError):
            tally(rule, ["SUPPORTED"] * wrong)
    with pytest.raises(ValueError):
        tally("unknown-rule", ["SUPPORTED"])
    with pytest.raises(ValueError):
        mode_for(4)
    assert tally("withhold-queue-v3", []) == "withheld"


def test_a_family_verdict_is_its_worst_pair_with_the_first_chosen_pair_s_ehmf_type():
    pairs = [(verdict, None if verdict == "SUPPORTED" else ehmf) for verdict, ehmf in itertools.product(VERDICTS, ("A", "B"))]
    for size in (1, 2, 3):
        for combination in itertools.product(pairs, repeat=size):
            verdicts = [verdict for verdict, _ in combination]
            expected = "CONTRADICTED" if "CONTRADICTED" in verdicts else "NOT_ENOUGH_INFO" if "NOT_ENOUGH_INFO" in verdicts else "SUPPORTED"
            verdict, ehmf = family_verdict(list(combination))
            assert verdict == expected
            assert ehmf == (None if expected == "SUPPORTED" else next(item[1] for item in combination if item[0] == expected))
    with pytest.raises(ValueError):
        family_verdict([])


def test_a_split_is_at_least_one_support_and_one_objection():
    for size in (0, 1, 2, 3):
        for verdicts in itertools.product(VERDICTS, repeat=size):
            supports = verdicts.count("SUPPORTED")
            assert is_split(list(verdicts)) == (supports >= 1 and size - supports >= 1)


def test_the_routing_table_is_the_plans_matrix_and_the_prompt_hashes_are_fixed():
    assert rules.ROUTING_TABLES == {"degraded-matrix-v1": rules.RULE_MATRIX}
    assert set(rules.RULE_MATRIX) == set(rules.DEGRADED_MODES) and all(set(row) == {1, 2, 3} for row in rules.RULE_MATRIX.values())
    assert {rule for row in rules.RULE_MATRIX.values() for rule in row.values()} == set(rules.TIER_RULES)
    assert rules.verifier_prompt_hash() == rules.verifier_prompt_hash() != rules.alignment_prompt_hash()
    for text in (rules.VERIFIER_INSTRUCTIONS, rules.ALIGNMENT_INSTRUCTIONS):
        lowered = text.lower()
        assert not any(word in lowered for word in ("learner", "generator", "model", "family", "vote"))
    assert rules.matrix_from_package(rules.matrix_for_package(rules.RULE_MATRIX)) == rules.RULE_MATRIX
