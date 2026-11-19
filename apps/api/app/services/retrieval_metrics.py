"""Per-process retrieval and citation SLIs (plan Phase 2 I; Phase 2 spec 4.25, 6.2).

Counts only: no query text, no identity. /ready reports a snapshot; each decision is also one structured log line
(retrieval.decision), so log-based metrics can aggregate across instances once they are set up (a cloud write,
documented in infra/cloudrun/observability.md, not created here).
"""

from __future__ import annotations

from collections import Counter, deque
import logging
import threading

from app.core.structured_logging import FIELDS

LATENCY_WINDOW = 1000
LOGGER = logging.getLogger("qcai.citations")


class RetrievalMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with getattr(self, "_lock", threading.Lock()):
            self._decisions = 0
            self._abstained = 0
            self._by_reason: Counter[str] = Counter()
            self._latencies: deque[float] = deque(maxlen=LATENCY_WINDOW)
            self._delivered = 0
            self._dropped_unresolved = 0
            self._withheld_unapproved = 0

    def record_decision(self, surface: str, mode: str, gate: str, abstained: bool, reason: str, latency_ms: float) -> None:
        with self._lock:
            self._decisions += 1
            self._abstained += int(bool(abstained))
            self._by_reason[reason] += 1
            self._latencies.append(float(latency_ms))

    def record_citations(self, surface: str, delivered: int, dropped_unresolved: int, withheld_unapproved: int) -> None:
        with self._lock:
            self._delivered += int(delivered)
            self._dropped_unresolved += int(dropped_unresolved)
            self._withheld_unapproved += int(withheld_unapproved)

    @staticmethod
    def _percentile(values: list[float], fraction: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
        return round(ordered[index], 3)

    def snapshot(self) -> dict:
        with self._lock:
            latencies = list(self._latencies)
            delivered, dropped, withheld = self._delivered, self._dropped_unresolved, self._withheld_unapproved
            decisions, abstained, by_reason = self._decisions, self._abstained, dict(self._by_reason)
        attempted = delivered + dropped
        return {
            "citation_resolution": {
                "delivered": delivered,
                "resolved": delivered,
                "dropped_unresolved": dropped,
                "withheld_unapproved": withheld,
                "rate": round(delivered / attempted, 6) if attempted else None,
            },
            "abstention": {
                "decisions": decisions,
                "abstained": abstained,
                "rate": round(abstained / decisions, 6) if decisions else None,
                "by_reason": by_reason,
            },
            "search_latency_ms": {
                "window": len(latencies),
                "p50": self._percentile(latencies, 0.5),
                "p95": self._percentile(latencies, 0.95),
            },
        }


METRICS = RetrievalMetrics()


def record_decision(surface: str, mode: str, gate: str, abstained: bool, reason: str, latency_ms: float) -> None:
    METRICS.record_decision(surface, mode, gate, abstained, reason, latency_ms)


def record_citations(surface: str, delivered: int, dropped_unresolved: int, withheld_unapproved: int) -> None:
    METRICS.record_citations(surface, delivered, dropped_unresolved, withheld_unapproved)
    # Counts only. A dropped citation is one the Phase 2 pipeline produced but could not verify: a WARNING.
    LOGGER.log(
        logging.WARNING if dropped_unresolved else logging.INFO,
        "Citations delivered",
        extra={FIELDS: {"event": "citations.delivered", "surface": surface, "delivered": int(delivered),
                        "dropped_unresolved": int(dropped_unresolved), "withheld_unapproved": int(withheld_unapproved)}},
    )


def snapshot() -> dict:
    return METRICS.snapshot()
