"""In-process gateway metrics (plan Phase 5 I: p95 per stage, cost; Phase 5 spec 7.1, 10.3). Not public: /ready reports
none of it. Calls by adapter and outcome, latency per adapter (nearest-rank p95 over the last 1024), cost units, and
ineligibility and refusals by reason. Adapter ids and enumerations only.
"""

from __future__ import annotations

from collections import Counter, deque
import math
import threading

WINDOW = 1024


def nearest_rank_p95(values) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    return float(ordered[max(math.ceil(0.95 * len(ordered)) - 1, 0)])


class GatewayMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.calls: Counter = Counter()
            self.latency: dict[str, deque] = {}
            self.cost_units = 0
            self.ineligible: Counter = Counter()
            self.refused: Counter = Counter()

    def call(self, adapter_id: str, outcome: str, latency_ms: float | None, cost_units: int) -> None:
        """Count one call; a refused call (latency_ms None) never reached the adapter and adds no latency sample."""
        with self._lock:
            self.calls[(adapter_id, outcome)] += 1
            if latency_ms is not None:
                self.latency.setdefault(adapter_id, deque(maxlen=WINDOW)).append(float(latency_ms))
            self.cost_units += int(cost_units)

    def ineligible_for(self, reason: str) -> None:
        with self._lock:
            self.ineligible[reason] += 1

    def refusal(self, reason: str) -> None:
        with self._lock:
            self.refused[reason] += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "calls": {f"{adapter}:{outcome}": count for (adapter, outcome), count in sorted(self.calls.items())},
                "latency_p95_ms": {adapter: nearest_rank_p95(values) for adapter, values in sorted(self.latency.items())},
                "cost_units": self.cost_units,
                "ineligible": dict(sorted(self.ineligible.items())),
                "refused": dict(sorted(self.refused.items())),
            }


GATEWAY_METRICS = GatewayMetrics()
