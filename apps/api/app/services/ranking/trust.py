"""Discounted trust and ratings (paper eqs. (5)-(7), Sec. VII-B; spec 4.4).

alpha' = gamma alpha + y, beta' = gamma beta + (1 - y); T = F^-1_Beta(quantile; alpha, beta); ratings A >= 0.95,
B >= 0.90, C >= 0.80, else D; a capped model (a version change not yet re-commissioned) is never above C. Tier
permissions: A generates for tiers 1-3; B for tiers 2-3, and tier 1 only when no available, permitted, uncapped A model
exists in the context; C and D generate for no tier (shadow and verification only).
"""

from __future__ import annotations

from decimal import Decimal, localcontext

from app.services.ranking.numeric import CTX, D, beta_quantile, q
from app.services.ranking.vocabulary import RATINGS


def update_trust(alpha, beta, y: int, gamma) -> tuple[Decimal, Decimal]:
    if y not in (0, 1):
        raise ValueError("y is 0 or 1")
    with localcontext(CTX):
        alpha, beta, gamma = D(alpha), D(beta), D(gamma)
        return q(gamma * alpha + y), q(gamma * beta + (1 - y))


def trust(alpha, beta, quantile) -> Decimal:
    return beta_quantile(quantile, alpha, beta)


def rating(t, ratings: dict, *, capped: bool) -> str:
    with localcontext(CTX):
        t = D(t)
        if t >= ratings["A"]:
            grade = "A"
        elif t >= ratings["B"]:
            grade = "B"
        elif t >= ratings["C"]:
            grade = "C"
        else:
            grade = "D"
    if capped and grade in ("A", "B"):
        return "C"
    return grade


def permits(grade: str, tier: int, *, a_available: bool, permissions: dict, b_tier_1_when_no_a: bool) -> bool:
    if grade not in RATINGS:
        raise ValueError(f"unknown rating {grade!r}")
    if tier in permissions[grade]:
        return True
    return grade == "B" and tier == 1 and b_tier_1_when_no_a and not a_available


def threshold(tier: int, *, a_available: bool, ratings: dict, permissions: dict, b_tier_1_when_no_a: bool) -> Decimal:
    """The lowest trust that may generate for this tier: the rating threshold of the lowest permitted grade."""
    for grade in ("C", "B", "A"):
        if grade in ratings and permits(grade, tier, a_available=a_available, permissions=permissions, b_tier_1_when_no_a=b_tier_1_when_no_a):
            return ratings[grade]
    return ratings["A"]
