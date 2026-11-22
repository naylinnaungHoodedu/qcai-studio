"""In-process V2 metrics (plan Phase 5 I: verification completion, time degraded, p95 per stage, cost per response,
the 80% budget event; Phase 5 spec 10.3). Not public: /ready reports none of it, and no per-run outcome, spend or cache
count is public (AC-3-6 rule). Verification completion is a V1-passed response whose every eligible claim got a
completed vote (pass or fail) or a typed withheld outcome.
"""

from __future__ import annotations

from collections import Counter, deque
import threading
import time

from app.gateway.metrics import GATEWAY_METRICS, WINDOW, nearest_rank_p95


class V2Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.runs: Counter = Counter()
            self.passed_v1 = 0
            self.completed = 0
            self.modes: Counter = Counter()
            self.budget_exceeded = 0
            self.time_in_mode_s: Counter = Counter()
            self._current_mode: str | None = None
            self._mode_since = time.monotonic()
            self.panel_latency: deque = deque(maxlen=WINDOW)
            self.correction_latency: deque = deque(maxlen=WINDOW)
            self.cost: deque = deque(maxlen=WINDOW)
            self.cost_total = 0
            self.x2 = 0
            self.degraded_withheld = 0
            self.disagreements = 0
            self.outcomes: Counter = Counter()

    def run(self, *, mode: str, degraded_mode: str, passed_v1: bool, completed: bool, latency_ms: float, cost_units: int,
            x2: int, degraded_withheld: int, budget_exceeded: bool) -> None:
        with self._lock:
            self.runs[mode] += 1
            now = time.monotonic()
            if self._current_mode is not None:
                self.time_in_mode_s[self._current_mode] += now - self._mode_since
            self._current_mode, self._mode_since = degraded_mode, now
            if passed_v1:
                self.passed_v1 += 1
                self.completed += int(completed)
                self.modes[degraded_mode] += 1
                self.panel_latency.append(float(latency_ms))
                self.cost.append(int(cost_units))
            self.cost_total += int(cost_units)
            self.x2 += int(x2)
            self.degraded_withheld += int(degraded_withheld)
            self.budget_exceeded += int(budget_exceeded)

    def correction(self, latency_ms: float) -> None:
        with self._lock:
            self.correction_latency.append(float(latency_ms))

    def disagreement(self) -> None:
        with self._lock:
            self.disagreements += 1

    def outcome(self, event) -> None:
        with self._lock:
            self.outcomes[(event.final, event.degraded_mode)] += 1

    def detail_snapshot(self, *, budget: dict | None = None, cache: dict | None = None, gateway: dict | None = None) -> dict:
        with self._lock:
            costs = list(self.cost)
            snapshot = {
                "runs": dict(self.runs),
                "completion": {"passed_v1": self.passed_v1, "completed": self.completed, "rate": f"{self.completed}/{self.passed_v1}"},
                "modes": {**dict(self.modes), "budget_exceeded": self.budget_exceeded},
                "time_in_mode_s": {mode: round(seconds, 3) for mode, seconds in self.time_in_mode_s.items()},
                "latency_ms": {"panel": nearest_rank_p95(self.panel_latency), "correction": nearest_rank_p95(self.correction_latency)},
                "cost_units": {"total": self.cost_total, "per_response_mean": round(sum(costs) / len(costs), 3) if costs else 0.0,
                               "per_response_p95": nearest_rank_p95(costs)},
                "x2": self.x2,
                "degraded_withheld": self.degraded_withheld,
                "disagreements": self.disagreements,
            }
        snapshot["latency_ms"]["gateway_call"] = GATEWAY_METRICS.snapshot()["latency_p95_ms"]
        snapshot["budget"] = budget or {}
        snapshot["cache"] = cache or {}
        snapshot["gateway"] = gateway or {}
        return snapshot


V2_METRICS = V2Metrics()
