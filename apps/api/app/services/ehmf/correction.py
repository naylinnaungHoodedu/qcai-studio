"""The correction guard (plan Phase 7 D task 4; AC-7-4, AC-7-5; Phase 7 spec 4.4; PD-44).

"Correction: at most two cycles, then abstain and raise X2 [Evidence E-82]." CorrectionGuard is the correction loop's
only bound, in every EHMF mode: V1Track._run_v2 and _final_rendering ask begin_cycle(cycles + 1) before each cycle, and a
cycle beyond max_cycles (package ehmf.max_cycles, v2.correction.max_cycles, 2) raises CorrectionLimit, so the claims a
third cycle would have corrected abstain with escalation X2 (Phase 5 behaviour); the record contracts refuse a third
cycle too (V2Correction.cycle le=2). check_re_render is the AC-7-4 assertion: a Type E correction re-renders the same
candidate, so its claim set and span set must not change; under EHMF shadow or on a re-render that changes either is
refused and the response abstains with ehmf_set_changed.
"""

from __future__ import annotations

import hashlib
from typing import Any


class CorrectionLimit(RuntimeError):
    """A correction cycle beyond max_cycles was asked for."""


def claim_set_sha256(locked: Any) -> str:
    return hashlib.sha256("\n".join(sorted(claim.claim_id for claim in locked.claims)).encode("utf-8")).hexdigest()


def span_set_sha256(locked: Any) -> str:
    return hashlib.sha256("\n".join(sorted(locked.span_ids)).encode("utf-8")).hexdigest()


class CorrectionGuard:
    def __init__(self, *, max_cycles: int) -> None:
        self.max_cycles = int(max_cycles)
        self.asked: list[int] = []

    def begin_cycle(self, next_cycle: int) -> None:
        self.asked.append(int(next_cycle))
        if next_cycle > self.max_cycles:
            raise CorrectionLimit(f"correction cycle {next_cycle} refused: at most {self.max_cycles} cycles (plan Phase 7 D task 4)")

    def check_re_render(self, before: Any, after: Any) -> bool:
        """True iff the re-render kept the claim set and the span set (AC-7-4)."""
        return claim_set_sha256(before) == claim_set_sha256(after) and span_set_sha256(before) == span_set_sha256(after)
