"""The ranking score (paper eq. (10); spec 4.4): R = T * Qbar - lambda_u u - lambda_l l.

u is the model's cost units per call over the most expensive candidate's (0 when every cost is 0; rule
cost-units-over-max-v1; units, not USD, A-15); l is 0 because no record carries a latency (DI-122). lambda_u and
lambda_l are operator policy (D-06 OPEN) and 0 while it is open; the package refuses another value.
"""

from __future__ import annotations

from decimal import Decimal, localcontext

from app.services.ranking.numeric import CTX, D, ZERO, q


def cost_share(cost: int, max_cost: int) -> Decimal:
    with localcontext(CTX):
        if max_cost <= 0:
            return ZERO
        return q(Decimal(int(cost)) / Decimal(int(max_cost)))


def score(t, qbar, *, u, latency_excess, lambda_u, lambda_l) -> Decimal:
    with localcontext(CTX):
        return q(D(t) * D(qbar) - D(lambda_u) * D(u) - D(lambda_l) * D(latency_excess))
