"""The V2 voting arithmetic (plan 5.5, 5.6, 5.9; VBT RevB p. 14 arbitration rules 2-4; Phase 5 spec 4.9). Pure
functions, standard library only; test_v2_voting.py checks them exhaustively against a table written from the plan.

F  family_verdict: one member family's verdict on a claim from its (verdict, ehmf) pairs, one per cited span, in
   span-id order: CONTRADICTED if any pair is, else NOT_ENOUGH_INFO if any pair is, else SUPPORTED (every bound span
   must support the claim; a non-supporting citation objects). Its EHMF type is the first chosen pair's.
T  tally: objections o (family verdicts other than SUPPORTED; NOT_ENOUGH_INFO objects, rule 3), supports s, N members:
     1oo3                    N = 3, fail iff o >= 1
     2oo3                    N = 3, fail iff o >= 2
     1oo2                    N = 2, fail iff o >= 1
     equal-weights-share-v1  N >= 1, pass iff den * s >= num * N (2/3, PD-25)
     withhold-queue-v3       withheld (no call is made)
   A rule given the wrong N raises ValueError.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from app.services.v2_panel.rules import DEGRADED_MODES, MAX_MEMBERS, OBJECTIONS

_ORDER = {"SUPPORTED": 0, "NOT_ENOUGH_INFO": 1, "CONTRADICTED": 2}


def family_verdict(pairs: Sequence[tuple[str, str | None]]) -> tuple[str, str | None]:
    """(verdict, ehmf_type) of one family over its pairs for one claim, given in span-id order (rule F, worst-pair-v1)."""
    if not pairs:
        raise ValueError("a family verdict needs at least one pair")
    worst = max(_ORDER[verdict] for verdict, _ehmf in pairs)
    chosen = next((verdict, ehmf) for verdict, ehmf in pairs if _ORDER[verdict] == worst)
    return chosen if chosen[0] != "SUPPORTED" else ("SUPPORTED", None)


def objections(verdicts: Sequence[str]) -> int:
    return sum(1 for verdict in verdicts if verdict in OBJECTIONS)


def supports(verdicts: Sequence[str]) -> int:
    return sum(1 for verdict in verdicts if verdict == "SUPPORTED")


def tally(rule: str, family_verdicts: Sequence[str], *, threshold: tuple[int, int] = (2, 3)) -> Literal["pass", "fail", "withheld"]:
    n = len(family_verdicts)
    o, s = objections(family_verdicts), supports(family_verdicts)
    if rule == "withhold-queue-v3":
        return "withheld"
    if rule == "1oo3":
        if n != 3:
            raise ValueError("1oo3 needs three family verdicts")
        return "fail" if o >= 1 else "pass"
    if rule == "2oo3":
        if n != 3:
            raise ValueError("2oo3 needs three family verdicts")
        return "fail" if o >= 2 else "pass"
    if rule == "1oo2":
        if n != 2:
            raise ValueError("1oo2 needs two family verdicts")
        return "fail" if o >= 1 else "pass"
    if rule == "equal-weights-share-v1":
        if n < 1:
            raise ValueError("equal-weights-share-v1 needs at least one family verdict")
        numerator, denominator = threshold
        return "pass" if denominator * s >= numerator * n else "fail"
    raise ValueError(f"unknown tier rule {rule!r}")


def mode_for(n_eligible: int) -> str:
    """FULL with three members, REDUCED-2 with two, REDUCED-1 with one, ZERO with none (plan 5.9)."""
    if n_eligible < 0 or n_eligible > MAX_MEMBERS:
        raise ValueError(f"a panel holds 0 to {MAX_MEMBERS} members")
    return DEGRADED_MODES[MAX_MEMBERS - n_eligible]


def rule_for(table: dict, mode: str, tier: int) -> str:
    return table[mode][tier]


def is_split(family_verdicts: Sequence[str]) -> bool:
    return supports(family_verdicts) >= 1 and objections(family_verdicts) >= 1
