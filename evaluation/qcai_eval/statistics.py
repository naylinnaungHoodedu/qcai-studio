"""Small-sample proportion and paired-arm statistics required by RevB §8.5."""

from __future__ import annotations

from math import comb, sqrt


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> dict[str, float | int]:
    if total < 0 or successes < 0 or successes > total:
        raise ValueError("Wilson interval requires 0 <= successes <= total.")
    if total == 0:
        return {"successes": 0, "total": 0, "rate": 0.0, "lower": 0.0, "upper": 0.0}
    rate = successes / total
    denominator = 1 + (z * z) / total
    centre = (rate + (z * z) / (2 * total)) / denominator
    margin = z * sqrt((rate * (1 - rate) / total) + (z * z) / (4 * total * total)) / denominator
    return {"successes": successes, "total": total, "rate": rate, "lower": max(0.0, centre - margin), "upper": min(1.0, centre + margin)}


def mcnemar_exact(left: list[bool], right: list[bool]) -> dict[str, float | int]:
    if len(left) != len(right):
        raise ValueError("McNemar inputs must be paired.")
    left_only = sum(1 for a, b in zip(left, right) if a and not b)
    right_only = sum(1 for a, b in zip(left, right) if b and not a)
    discordant = left_only + right_only
    if discordant == 0:
        p_value = 1.0
    else:
        smaller = min(left_only, right_only)
        tail = sum(comb(discordant, k) for k in range(smaller + 1)) / (2**discordant)
        p_value = min(1.0, 2 * tail)
    return {
        "left_only": left_only,
        "right_only": right_only,
        "discordant": discordant,
        "p_value": p_value,
        "paired_effect": (right_only - left_only) / len(left) if left else 0.0,
    }
