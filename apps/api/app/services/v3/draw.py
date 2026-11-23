"""The seeded audit draw (plan Phase 6 D task 2 "seeded 5% draw over ledger deliveries"; AC-6-2; plan 6.3 "X6 = 5%",
"version change -> X5 audit 20%"; Phase 6 spec 4.2; PD-35).

Rule seeded-sha256-bernoulli-v1: u = the first 8 bytes of sha256("x6-draw-v1|<seed>|<response_id>") as a big-endian
integer; a delivery is drawn at rate num/den when u * den < num * 2^64. Integers only, so no float takes part in the
decision, and the 1/20 set is a subset of the 1/5 set: raising the rate never undraws a delivery. While an X5 window is
open a delivery is X6 below 1/20 and X5 between 1/20 and 1/5. The draw depends only on (seed, response_id, rate), so a
same-seed replay over the same deliveries draws the same ids. Each delivery is considered once, at the first scan that
reads its record (scan.run_scan; v3_draws' primary key is the ledger seq). The same rule with purpose
double-review-v1 on an item id selects the items that need a second independent review (queue.upsert_item).
"""

from __future__ import annotations

from fractions import Fraction
import hashlib
from typing import Any

from app.services.v3.rules import DRAW_PURPOSE


def u64(purpose: str, seed: str, key: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{purpose}|{seed}|{key}".encode("utf-8")).digest()[:8], "big")


def bernoulli(purpose: str, seed: str, key: str, rate: Fraction) -> bool:
    rate = Fraction(rate)
    return u64(purpose, seed, key) * rate.denominator < rate.numerator * 2**64


def draw_trigger(seed: str, response_id: str, *, base: Fraction, elevated: Fraction, x5_active: bool) -> str | None:
    u = u64(DRAW_PURPOSE, seed, response_id)
    base, elevated = Fraction(base), Fraction(elevated)
    if u * base.denominator < base.numerator * 2**64:
        return "X6"
    if x5_active and u * elevated.denominator < elevated.numerator * 2**64:
        return "X5"
    return None


def claim_set_key(entry: Any) -> str | None:
    if entry is None or entry.decision != "answer" or not entry.claims:
        return None
    ids = sorted({claim.claim_id for claim in entry.claims})
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()
