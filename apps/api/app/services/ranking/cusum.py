"""The Bernoulli log-likelihood-ratio CUSUM (paper eq. (11), Sec. VII-C; spec 4.7).

S_t = max(0, S_{t-1} + e ln(p1/p0) + (1 - e) ln((1 - p1)/(1 - p0))) on e = 1 - y, after every response, for the stream
model:<adapter_id> and the stream model-cluster:<adapter_id>:<cluster>. S > h is an alarm: Phase 6's
record_cusum_alarm raises the X5 audit, promotions hold until its window closes, and the chart resets. An alarm never
demotes (plan task 2 "CUSUM alarm -> X5, never demotion"); demotion is the trust trip's only (4.6).
"""

from __future__ import annotations

from decimal import Decimal, localcontext

from app.services.ranking.numeric import CTX, D, ZERO, ln_ratio, q


def update(statistic, error: int, a: Decimal, b: Decimal) -> Decimal:
    if error not in (0, 1):
        raise ValueError("e is 0 or 1")
    with localcontext(CTX):
        return q(max(ZERO, D(statistic) + error * a + (1 - error) * b))


def constants(p0, p1) -> tuple[Decimal, Decimal]:
    return ln_ratio(p0, p1)


def model_stream(adapter_id: str) -> str:
    return f"model:{adapter_id}"


def cluster_stream(adapter_id: str, cluster: str) -> str:
    return f"model-cluster:{adapter_id}:{cluster}"
