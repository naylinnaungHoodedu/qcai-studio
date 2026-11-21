"""Per-process SLIs of the V1 checks (plan Phase 4 I: "Citation resolution 100%; hard-fail rate per check; V1.3 flag
rate; V1 p95 (95th-percentile) latency"; Phase 4 spec 10.3).

Counts, enumerations and latencies only: no question, claim or rendered text, no identity. Public /ready carries none
of it (a V1 run is part of the two-pass shadow, whose outcomes never reach a learner, AC-3-6; Phase 3 spec 11.2):
the per-run tutor.v1.run, tutor.v1.disagreement and tutor.v1.legacy_guard_withheld log lines are the cross-instance
view, and detail_snapshot is in-process only, read by tests.

  citation_resolution   the span ids of delivered V1 verdicts and how many resolve (V-1: 100% of delivered citations)
  hard_fail_rate        per check, the runs in which it hard-failed (at least once) over the runs in which it ran
                        (checks_run, hard_failed_checks: the one definition the fixture report and the runbook use)
  v1_3                  claims checked, flagged (flag rate) and checker-unavailable runs
  latency_ms            a histogram and the nearest-rank p95 over the last LATENCY_WINDOW runs; stop is p95 above the
                        package's v1.stop.v1_p95_latency_ms (a plan L stop condition)
  disagreements         V1's final outcome against the Phase 3 decision and against the legacy decision (plan G)
  legacy_guard          contained answers checked and withheld per surface, and withholdings per check
"""

from __future__ import annotations

from collections import Counter, deque
import math
import threading
from typing import TYPE_CHECKING

from app.services.tutor_pipeline.contracts import CHECK_IDS
from app.services.v1_checks.rules import LATENCY_BUCKETS_MS, LATENCY_WINDOW, P95, RATE_DIGITS, SCORE_DIGITS

if TYPE_CHECKING:  # pragma: no cover
    from app.services.tutor_pipeline.contracts import VerificationRecord

OUTCOMES = ("pass", "flag", "hard_fail", "abstain", "mark")
FINALS = ("deliver", "withhold", "abstain")
MODES = ("shadow", "enforce")
GUARD_SURFACES = ("tutor", "qa")
GUARD_CHECKS = ("V1.1", "V1.2")


def checks_run(record: "VerificationRecord") -> set[str]:
    """The checks that ran in one V1 run: the denominator of the hard-fail rate per check."""
    return {result.check_id for result in record.checks}


def hard_failed_checks(record: "VerificationRecord") -> set[str]:
    """The checks that hard-failed at least once in one V1 run, however many of their results did: the numerator of the
    hard-fail rate per check (spec 10.3), so the rate is a share of runs and never exceeds 1."""
    return {result.check_id for result in record.checks if result.outcome == "hard_fail"}


def nearest_rank_p95(samples) -> float | None:
    ordered = sorted(samples)
    if not ordered:
        return None
    return ordered[max(0, math.ceil(P95 * len(ordered)) - 1)]


class V1Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with getattr(self, "_lock", threading.Lock()):
            self._runs: Counter[str] = Counter()
            self._finals: Counter[str] = Counter()
            self._outcomes: dict[str, Counter[str]] = {check: Counter() for check in CHECK_IDS}
            self._ran: Counter[str] = Counter()
            self._hard_runs: Counter[str] = Counter()
            self._citations = [0, 0]
            self._v1_3 = Counter()
            self._latencies: deque[float] = deque(maxlen=LATENCY_WINDOW)
            self._buckets: Counter[str] = Counter()
            self._disagreements: Counter[str] = Counter()
            self._v3_intents = 0
            self._guard_checked: Counter[str] = Counter()
            self._guard_withheld: Counter[str] = Counter()
            self._guard_by_check: Counter[str] = Counter()
            self._budget: int | None = None

    def run(self, record: "VerificationRecord", *, latency_ms: float, delivered_span_ids: int, delivered_resolved: int,
            budget_ms: int | None) -> None:
        with self._lock:
            self._runs[record.mode] += 1
            self._finals[record.final] += 1
            for check in checks_run(record):
                self._ran[check] += 1
            for check in hard_failed_checks(record):
                self._hard_runs[check] += 1
            for result in record.checks:
                self._outcomes[result.check_id][result.outcome] += 1
            v1_3 = [result for result in record.checks if result.check_id == "V1.3"]
            self._v1_3["checked"] += sum(1 for result in v1_3 if result.claim_id is not None)
            self._v1_3["flagged"] += sum(1 for result in v1_3 if result.outcome == "flag")
            self._v1_3["unavailable"] += int(any(result.reason_code == "checker_unavailable" for result in v1_3))
            self._citations[0] += delivered_span_ids
            self._citations[1] += delivered_resolved
            self._latencies.append(float(latency_ms))
            bucket = next((str(edge) for edge in LATENCY_BUCKETS_MS if latency_ms <= edge), "+Inf")
            self._buckets[bucket] += 1
            self._v3_intents += sum(1 for verdict in record.verdicts if verdict.v3 is not None)
            self._budget = budget_ms

    def disagreement(self, reference: str) -> None:
        with self._lock:
            self._disagreements[reference] += 1

    def guard(self, surface: str, *, withheld_by: str | None) -> None:
        name = surface if surface in GUARD_SURFACES else "tutor"
        with self._lock:
            self._guard_checked[name] += 1
            if withheld_by is not None:
                self._guard_withheld[name] += 1
                self._guard_by_check[withheld_by] += 1

    def detail_snapshot(self) -> dict:
        with self._lock:
            checks = {check: {outcome: self._outcomes[check].get(outcome, 0) for outcome in OUTCOMES} for check in CHECK_IDS}
            ran = dict(self._ran)
            hard_runs = dict(self._hard_runs)
            checked, resolved = self._citations
            v1_3 = dict(self._v1_3)
            p95 = nearest_rank_p95(self._latencies)
            budget = self._budget
            snapshot = {
                "runs": {mode: self._runs.get(mode, 0) for mode in MODES},
                "finals": {final: self._finals.get(final, 0) for final in FINALS},
                "checks": checks,
                "hard_fail_rate": {check: round(hard_runs.get(check, 0) / ran[check], RATE_DIGITS) if ran.get(check) else None
                                   for check in CHECK_IDS},
                "citation_resolution": {"checked": checked, "resolved": resolved,
                                        "rate": round(resolved / checked, RATE_DIGITS) if checked else None},
                "v1_3": {"claims_checked": v1_3.get("checked", 0), "flagged": v1_3.get("flagged", 0),
                         "flag_rate": round(v1_3.get("flagged", 0) / v1_3["checked"], RATE_DIGITS) if v1_3.get("checked") else None,
                         "unavailable": v1_3.get("unavailable", 0)},
                "latency_ms": {
                    "buckets": {**{str(edge): self._buckets.get(str(edge), 0) for edge in LATENCY_BUCKETS_MS}, "+Inf": self._buckets.get("+Inf", 0)},
                    "p95": None if p95 is None else round(p95, SCORE_DIGITS),
                    "budget": budget,
                    "stop": bool(p95 is not None and budget is not None and p95 > budget),
                },
                "disagreements": {"phase3": self._disagreements.get("phase3", 0), "legacy": self._disagreements.get("legacy", 0)},
                "v3_intents": self._v3_intents,
                "legacy_guard": {
                    "checked": {name: self._guard_checked.get(name, 0) for name in GUARD_SURFACES},
                    "withheld": {name: self._guard_withheld.get(name, 0) for name in GUARD_SURFACES},
                    "by_check": {name: self._guard_by_check.get(name, 0) for name in GUARD_CHECKS},
                },
            }
        return snapshot


V1_METRICS = V1Metrics()
