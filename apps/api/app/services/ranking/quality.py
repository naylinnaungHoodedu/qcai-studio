"""EWMA quality (paper eqs. (8)-(9), Table X; spec 4.4).

Q = (1 - H) * sum(w_s s) / sum(w_s) over the signals present among V, S, K and F (rule drop-and-renormalise-v1: plan 6.4
"renormalise when F missing", applied to every missing signal); a missing H counts as 0. Qbar' = (1 - eta) Qbar + eta Q.
F is a learner rating or flag on what the learner was shown: it feeds Q only, never trust, the CUSUM or the selection
(invariant 5; AC-9-2). f_from_rating is the 1-5 rating's F ((r - 1)/4); no rating intake exists (DI-121).
"""

from __future__ import annotations

from decimal import Decimal, localcontext

from app.services.ranking.numeric import CTX, D, ONE, ZERO, q

SIGNAL_NAMES = ("V", "S", "K", "F")


def quality(signals: dict, weights: dict) -> Decimal:
    with localcontext(CTX):
        hazard = signals.get("H")
        hazard = ZERO if hazard is None else D(hazard)
        total = ZERO
        weight_sum = ZERO
        for name in SIGNAL_NAMES:
            value = signals.get(name)
            if value is None:
                continue
            total += weights[name] * D(value)
            weight_sum += weights[name]
        if weight_sum == 0:
            return ZERO
        return q((ONE - hazard) * total / weight_sum)


def ewma(previous, value, eta) -> Decimal:
    with localcontext(CTX):
        eta = D(eta)
        return q((ONE - eta) * D(previous) + eta * D(value))


def f_from_rating(stars: int) -> Decimal:
    if isinstance(stars, bool) or not isinstance(stars, int) or not 1 <= stars <= 5:
        raise ValueError("a learner rating is an integer from 1 to 5")
    with localcontext(CTX):
        return q(Decimal(stars - 1) / 4)
