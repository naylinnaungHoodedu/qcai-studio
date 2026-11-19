"""Per-process SLIs of the response ledger and the two-pass shadow (plan Phase 3 I; Phase 3 spec 11.3).

Counts only: no question, claim or rendered text, no identity. /ready reports a snapshot; each event is also one
structured log line on the qcai.tutor logger, so log-based metrics can aggregate across instances once they are
set up (a cloud write, documented in infra/cloudrun/observability.md, not created here).

Plan L stop conditions: write_stop is true once any ledger write failed or conflicted; bound_claim_ratio_stop is
true once the two-pass bound-claim ratio is below the Phase 2 baseline pinned in the package. A null ratio (no
claims proposed) is never a stop. A run's proposed and bound claims are counted as
contracts.bound_claim_ratio_terms gives them: claims bind never saw (the budget ran out after the generator
returned) are in neither term, and claims merged onto an earlier claim's sentence are in both.
"""

from __future__ import annotations

from collections import Counter
import threading

from app.services.tutor_pipeline.contracts import PipelineCounts, bound_claim_ratio_terms

DELIVERIES = ("legacy", "shadow")
SHADOW_FAILURE_STEPS = ("resolve", "pipeline", "ledger")


class LedgerMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with getattr(self, "_lock", threading.Lock()):
            self._attempted: Counter[str] = Counter()
            self._appended: Counter[str] = Counter()
            self._failed: Counter[str] = Counter()
            self._duplicates = 0
            self._conflicts = 0

    def attempt(self, delivery: str) -> None:
        with self._lock:
            self._attempted[delivery] += 1

    def appended(self, delivery: str, *, duplicate: bool) -> None:
        with self._lock:
            self._appended[delivery] += 1
            self._duplicates += int(duplicate)

    def failed(self, delivery: str) -> None:
        with self._lock:
            self._failed[delivery] += 1

    def conflict(self) -> None:
        with self._lock:
            self._conflicts += 1

    def snapshot(self) -> dict:
        with self._lock:
            attempted, appended, failed = dict(self._attempted), dict(self._appended), dict(self._failed)
            duplicates, conflicts = self._duplicates, self._conflicts
        legacy_attempted = attempted.get("legacy", 0)
        return {
            "attempted": {name: attempted.get(name, 0) for name in DELIVERIES},
            "appended": {name: appended.get(name, 0) for name in DELIVERIES},
            "duplicates": duplicates,
            "failed": {name: failed.get(name, 0) for name in DELIVERIES},
            "conflicts": conflicts,
            "legacy_coverage_rate": round(appended.get("legacy", 0) / legacy_attempted, 6) if legacy_attempted else None,
            "write_stop": bool(sum(failed.values()) + conflicts),
        }


class TwoPassMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with getattr(self, "_lock", threading.Lock()):
            self._scheduled = 0
            self._completed = 0
            self._failed: Counter[str] = Counter()
            self._decisions: Counter[str] = Counter()
            self._by_reason: Counter[str] = Counter()
            self._proposed = 0
            self._bound = 0
            self._regenerations = 0
            self._budget_exceeded = 0

    def scheduled(self) -> None:
        with self._lock:
            self._scheduled += 1

    def failed(self, step: str) -> None:
        with self._lock:
            self._failed[step] += 1

    def completed(self, *, decision: str, reason: str | None, counts: PipelineCounts, attempts: int) -> None:
        proposed, bound = bound_claim_ratio_terms(counts)
        with self._lock:
            self._completed += 1
            self._decisions[decision] += 1
            if reason:
                self._by_reason[reason] += 1
                if reason == "budget_exceeded":
                    self._budget_exceeded += 1
            self._proposed += int(proposed)
            self._bound += int(bound)
            self._regenerations += max(0, int(attempts) - 1)

    def snapshot(self, baseline: float | None) -> dict:
        with self._lock:
            proposed, bound = self._proposed, self._bound
            snapshot = {
                "scheduled": self._scheduled,
                "completed": self._completed,
                "failed": {step: self._failed.get(step, 0) for step in SHADOW_FAILURE_STEPS},
                "decisions": {name: self._decisions.get(name, 0) for name in ("answer", "abstain")},
                "abstention_by_reason": dict(self._by_reason),
                "proposed_claims": proposed,
                "bound_claims": bound,
                "render_regenerations": self._regenerations,
                "budget_exceeded": self._budget_exceeded,
            }
        ratio = round(bound / proposed, 6) if proposed else None
        snapshot["bound_claim_ratio"] = ratio
        snapshot["phase2_bound_claim_ratio_baseline"] = baseline
        snapshot["bound_claim_ratio_stop"] = bool(ratio is not None and baseline is not None and ratio < baseline)
        return snapshot


LEDGER_METRICS = LedgerMetrics()
TWO_PASS_METRICS = TwoPassMetrics()


def snapshot(baseline: float | None) -> dict:
    return {"tutor_ledger": LEDGER_METRICS.snapshot(), "two_pass_shadow": TWO_PASS_METRICS.snapshot(baseline)}
