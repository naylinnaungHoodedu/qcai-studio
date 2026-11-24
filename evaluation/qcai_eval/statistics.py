"""Small-sample proportion and paired-arm statistics required by RevB §8.5."""

from __future__ import annotations

from fractions import Fraction
import hashlib
from math import ceil, comb, floor, sqrt
from typing import Any, Callable, Mapping, Sequence

PROVISIONAL_DEFAULTS = ("PD-70",)  # Phase 10 spec 12.1; ratified under DI-140


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


# --- Phase 10 additions (spec 4.7; PD-70). wilson_interval and mcnemar_exact above are unchanged. ---------------------


def holm(p_values: Mapping[str, float], alpha: float = 0.05) -> dict[str, dict]:
    """Holm's step-down correction within one family: adjusted_i = min(1, max_{j<=i} (m - j + 1) p_(j)), ties by name."""
    ordered = sorted(p_values.items(), key=lambda entry: (entry[1], entry[0]))
    m = len(ordered)
    result: dict[str, dict] = {}
    running = 0.0
    for index, (name, p_value) in enumerate(ordered):
        running = max(running, (m - index) * p_value)
        adjusted = min(1.0, running)
        result[name] = {"p_value": p_value, "adjusted": adjusted, "rank": index + 1, "reject": adjusted <= alpha}
    return result


def wilson_upper_bound(errors: int, total: int) -> float:
    """The 95% Wilson upper bound of an error rate (Table XIX: 0 errors in 150 responses gives about 2.5%)."""
    return float(wilson_interval(errors, total)["upper"])


def sample_variance(values: Sequence[float | Fraction]) -> float | None:
    """The unbiased sample variance (`sample-variance-v1`), exact over Fractions; None below two values."""
    if len(values) < 2:
        return None
    exact = [Fraction(value) for value in values]
    mean = sum(exact, Fraction(0)) / len(exact)
    return float(sum(((value - mean) ** 2 for value in exact), Fraction(0)) / (len(exact) - 1))


def least_squares_slope(points: Sequence[tuple[float, float]]) -> float | None:
    if len(points) < 2:
        return None
    xs = [Fraction(x) for x, _ in points]
    ys = [Fraction(y) for _, y in points]
    mean_x, mean_y = sum(xs, Fraction(0)) / len(xs), sum(ys, Fraction(0)) / len(ys)
    denominator = sum(((x - mean_x) ** 2 for x in xs), Fraction(0))
    if denominator == 0:
        return None
    return float(sum(((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)), Fraction(0)) / denominator)


def hash_resample_indices(n: int, seed: str, resample: int) -> list[int]:
    """`hash-resample-v1`: index_j = first 8 bytes of sha256(f"{seed}\x1f{resample}\x1f{j}") mod n."""
    if n < 1:
        raise ValueError("resampling needs at least one cluster")
    return [int.from_bytes(hashlib.sha256(f"{seed}\x1f{resample}\x1f{j}".encode("utf-8")).digest()[:8], "big") % n for j in range(n)]


def bootstrap(clusters: Sequence[Any], statistic: Callable[[list], float], *, resamples: int, seed: str, level: str = "0.95") -> dict:
    """A seeded percentile bootstrap over clusters. Bounds: the sorted replicates at floor((1 - level) / 2 * B) and
    ceil((1 + level) / 2 * B) - 1. BCa and the hypothesis-specific bootstraps are not implemented (DI-138)."""
    if resamples < 1 or not clusters:
        raise ValueError("bootstrap needs clusters and at least one resample")
    confidence = Fraction(level)
    values = list(clusters)
    replicates = sorted(statistic([values[i] for i in hash_resample_indices(len(values), seed, b)]) for b in range(resamples))
    lower_index = floor((1 - confidence) / 2 * resamples)
    upper_index = ceil((1 + confidence) / 2 * resamples) - 1
    return {"estimate": statistic(values), "lower": replicates[lower_index], "upper": replicates[upper_index], "resamples": resamples,
            "seed": seed, "method": "percentile", "rule": "hash-resample-v1", "level": level}
