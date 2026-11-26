"""Small-sample proportion and paired-arm statistics required by RevB §8.5."""

from __future__ import annotations

from fractions import Fraction
import hashlib
from math import ceil, comb, erf, exp, floor, lgamma, log, sqrt
from typing import Any, Callable, Mapping, Sequence

PROVISIONAL_DEFAULTS = ("PD-70",)  # Phase 10 spec 12.1; ratified under DI-140
# The tests an analysis plan may mark `implemented` (analysis_plans.validate_plans): each is a function defined in this
# module. A name this module merely imports (log, sqrt, Fraction, ...) or a helper is never a registered test.
REGISTERED_TESTS = ("mcnemar_exact", "wilson_upper_bound", "holm", "paired_bootstrap_one_sided", "cluster_bootstrap_bca_one_sided",
                    "cluster_bootstrap_lower_bound", "bootstrap_one_sided", "paired_bootstrap_auc_one_sided",
                    "two_level_bootstrap_share_le_zero", "friedman", "paired_tost")


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
    """A seeded two-sided percentile bootstrap over clusters. Bounds: the sorted replicates at floor((1 - level) / 2 * B)
    and ceil((1 + level) / 2 * B) - 1. The one-sided, paired, cluster, BCa and two-level forms the analysis plans name
    follow below."""
    if resamples < 1 or not clusters:
        raise ValueError("bootstrap needs clusters and at least one resample")
    confidence = Fraction(level)
    values = list(clusters)
    replicates = sorted(statistic([values[i] for i in hash_resample_indices(len(values), seed, b)]) for b in range(resamples))
    lower_index = floor((1 - confidence) / 2 * resamples)
    upper_index = ceil((1 + confidence) / 2 * resamples) - 1
    return {"estimate": statistic(values), "lower": replicates[lower_index], "upper": replicates[upper_index], "resamples": resamples,
            "seed": seed, "method": "percentile", "rule": "hash-resample-v1", "level": level}


# --- The analysis plans' remaining registered tests (spec 4.7; analysis_plans_v1.json "tests"). Each is the textbook
# procedure with the harness's hash-resample-v1 resampling; none is run on research data here (DI-138). --------------


def normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + erf(z / sqrt(2.0)))


def normal_quantile(p: float) -> float:
    """The standard normal quantile by bisection on `normal_cdf` (absolute error below 1e-12)."""
    if not 0.0 < p < 1.0:
        raise ValueError("the normal quantile needs 0 < p < 1")
    low, high = -40.0, 40.0
    for _ in range(200):
        middle = (low + high) / 2.0
        if normal_cdf(middle) < p:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def _gamma_q(a: float, x: float) -> float:
    """The regularized upper incomplete gamma function Q(a, x): series below a + 1, continued fraction above."""
    if x <= 0.0:
        return 1.0
    if x < a + 1.0:
        term = total = 1.0 / a
        n = a
        for _ in range(10000):
            n += 1.0
            term *= x / n
            total += term
            if abs(term) < abs(total) * 1e-16:
                break
        return max(0.0, 1.0 - total * exp(-x + a * log(x) - lgamma(a)))
    tiny = 1e-300
    b = x + 1.0 - a
    c, d = 1.0 / tiny, 1.0 / b
    h = d
    for i in range(1, 10000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        d = tiny if abs(d) < tiny else d
        c = b + an / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-16:
            break
    return exp(-x + a * log(x) - lgamma(a)) * h


def chi2_sf(x: float, df: int) -> float:
    """P(X >= x) for a chi-square variable with `df` degrees of freedom."""
    if df < 1:
        raise ValueError("chi-square needs at least one degree of freedom")
    return _gamma_q(df / 2.0, x / 2.0)


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    tiny = 1e-300
    c, d = 1.0, 1.0 - (a + b) * x / (a + 1.0)
    d = 1.0 / (tiny if abs(d) < tiny else d)
    h = d
    for m in range(1, 10000):
        delta = 1.0
        for numerator in (m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m)),
                          -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))):
            d = 1.0 + numerator * d
            d = 1.0 / (tiny if abs(d) < tiny else d)
            c = 1.0 + numerator / c
            c = tiny if abs(c) < tiny else c
            delta = d * c
            h *= delta
        if abs(delta - 1.0) < 1e-16:
            break
    return h


def _beta_regularized(a: float, b: float, x: float) -> float:
    """The regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = exp(lgamma(a + b) - lgamma(a) - lgamma(b) + a * log(x) + b * log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_continued_fraction(a, b, x) / a
    return 1.0 - front * _beta_continued_fraction(b, a, 1.0 - x) / b


def student_t_cdf(t: float, df: int) -> float:
    if df < 1:
        raise ValueError("Student's t needs at least one degree of freedom")
    tail = 0.5 * _beta_regularized(df / 2.0, 0.5, df / (df + t * t))
    return 1.0 - tail if t > 0 else tail


def _replicates(values: list, statistic: Callable[[list], float], resamples: int, seed: str) -> list[float]:
    if resamples < 1 or not values:
        raise ValueError("bootstrap needs clusters and at least one resample")
    return sorted(statistic([values[i] for i in hash_resample_indices(len(values), seed, b)]) for b in range(resamples))


def _one_sided(replicates: list[float], estimate: float, index: int, *, margin: str, alpha: str, method: str, seed: str) -> dict:
    """The one-sided result. `p_value` is the percentile p-value of H0 (statistic <= margin), the share of replicates at or
    below the margin; with the bound at the sorted replicate floor(alpha * B), `reject` holds exactly when p_value <=
    alpha. The BCa form replaces `p_value` with its own (cluster_bootstrap_bca_one_sided)."""
    resamples = len(replicates)
    bound = float(Fraction(margin))
    lower = replicates[min(max(index, 0), resamples - 1)]
    share = sum(1 for value in replicates if value <= bound) / resamples
    return {"estimate": estimate, "lower_bound": lower, "margin": margin, "alpha": alpha, "reject": lower > bound,
            "p_value": share, "share_at_or_below_margin": share, "resamples": resamples, "seed": seed, "method": method,
            "rule": "hash-resample-v1"}


def bootstrap_one_sided(clusters: Sequence[Any], statistic: Callable[[list], float], *, resamples: int, seed: str,
                        margin: str = "0", alpha: str = "0.05") -> dict:
    """A one-sided percentile bootstrap: the lower bound is the sorted replicate at floor(alpha * B), and the null
    (statistic <= margin) is rejected when that bound exceeds the margin."""
    values = list(clusters)
    replicates = _replicates(values, statistic, resamples, seed)
    return _one_sided(replicates, statistic(values), floor(Fraction(alpha) * resamples), margin=margin, alpha=alpha,
                      method="percentile-one-sided", seed=seed)


def cluster_bootstrap_lower_bound(clusters: Sequence[Any], statistic: Callable[[list], float], *, resamples: int, seed: str,
                                  margin: str = "0", alpha: str = "0.05") -> dict:
    """The one-sided percentile lower bound with whole clusters (for example every claim of one item) as the resampling
    unit; `statistic` receives the resampled list of clusters."""
    result = bootstrap_one_sided(clusters, statistic, resamples=resamples, seed=seed, margin=margin, alpha=alpha)
    return {**result, "method": "cluster-percentile-one-sided"}


def paired_bootstrap_one_sided(left: Sequence[float], right: Sequence[float], *, resamples: int, seed: str, margin: str = "0",
                               alpha: str = "0.05") -> dict:
    """mean(left) - mean(right) over paired items, each pair resampled whole, one-sided against `margin` (H1c's
    non-inferiority margin is -0.05)."""
    if len(left) != len(right):
        raise ValueError("a paired bootstrap needs paired inputs")
    pairs = [(float(a), float(b)) for a, b in zip(left, right)]
    result = bootstrap_one_sided(pairs, _mean_difference, resamples=resamples, seed=seed, margin=margin, alpha=alpha)
    return {**result, "method": "paired-percentile-one-sided"}


def _mean_difference(pairs: list) -> float:
    return sum(a - b for a, b in pairs) / len(pairs)


def auc(labels: Sequence[bool], scores: Sequence[float]) -> float:
    """The area under the ROC curve (Mann-Whitney): P(score of a positive > score of a negative) + 0.5 P(tie), positives
    being the items labelled True. Undefined (ValueError) without both a positive and a negative."""
    if len(labels) != len(scores):
        raise ValueError("an AUC needs one score per label")
    positives = [float(score) for label, score in zip(labels, scores) if label]
    negatives = [float(score) for label, score in zip(labels, scores) if not label]
    if not positives or not negatives:
        raise ValueError("an AUC needs at least one positive and one negative item")
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in positives for n in negatives)
    return wins / (len(positives) * len(negatives))


def paired_bootstrap_auc_one_sided(labels: Sequence[bool], left_scores: Sequence[float], right_scores: Sequence[float], *,
                                   resamples: int, seed: str, margin: str = "0", alpha: str = "0.05") -> dict:
    """The paired bootstrap comparison of two AUCs on the same items (H2c: the panel's against the novices'): each item is
    resampled whole with both of its scores, the statistic is AUC(left) - AUC(right), one-sided against `margin`. A
    replicate that draws only one class has no AUC and counts as at or below the margin (conservative)."""
    if not len(labels) == len(left_scores) == len(right_scores):
        raise ValueError("a paired AUC comparison needs one label and two scores per item")
    rows = [(bool(label), float(a), float(b)) for label, a, b in zip(labels, left_scores, right_scores)]

    def difference(chosen: list) -> float:
        try:
            return auc([row[0] for row in chosen], [row[1] for row in chosen]) - auc([row[0] for row in chosen], [row[2] for row in chosen])
        except ValueError:
            return float("-inf")

    estimate = auc([row[0] for row in rows], [row[1] for row in rows]) - auc([row[0] for row in rows], [row[2] for row in rows])
    replicates = _replicates(rows, difference, resamples, seed)
    return _one_sided(replicates, estimate, floor(Fraction(alpha) * resamples), margin=margin, alpha=alpha,
                      method="paired-auc-percentile-one-sided", seed=seed)


def cluster_bootstrap_bca_one_sided(clusters: Sequence[Any], statistic: Callable[[list], float], *, resamples: int, seed: str,
                                    margin: str = "0", alpha: str = "0.05") -> dict:
    """The one-sided BCa lower bound (Efron 1987) over clusters: z0 = Phi^-1(share of replicates below the estimate), the
    acceleration from the leave-one-cluster-out jackknife, a = sum(d^3) / (6 sum(d^2)^1.5) with d = mean - theta_(i), and
    the bound at the sorted replicate floor(Phi(z0 + (z0 + z_alpha) / (1 - a (z0 + z_alpha))) * B).

    `p_value` is the BCa one: the alpha at which the BCa bound reaches the margin. With q the share of replicates at or
    below the margin and w = Phi^-1(q) - z0, it is Phi(w / (1 + a w) - z0), the inverse of the adjusted percentile (0
    when q = 0 or when no alpha's bound reaches down to q; 1 when q = 1 or when none reaches up to it), so that `reject`
    holds exactly when p_value <= alpha. `share_at_or_below_margin` stays the plain percentile share."""
    values = list(clusters)
    if len(values) < 2:
        raise ValueError("BCa needs at least two clusters for the jackknife")
    replicates = _replicates(values, statistic, resamples, seed)
    estimate = statistic(values)
    below = sum(1 for value in replicates if value < estimate) / resamples
    if not 0.0 < below < 1.0:
        raise ValueError("BCa is undefined when no replicate, or every replicate, lies below the estimate")
    z0 = normal_quantile(below)
    jackknife = [statistic(values[:i] + values[i + 1:]) for i in range(len(values))]
    centre = sum(jackknife) / len(jackknife)
    squares = sum((centre - value) ** 2 for value in jackknife)
    acceleration = 0.0 if squares == 0 else sum((centre - value) ** 3 for value in jackknife) / (6.0 * squares ** 1.5)
    z_alpha = normal_quantile(float(Fraction(alpha)))
    adjusted = normal_cdf(z0 + (z0 + z_alpha) / (1.0 - acceleration * (z0 + z_alpha)))
    result = _one_sided(replicates, estimate, floor(adjusted * resamples), margin=margin, alpha=alpha,
                        method="cluster-bca-one-sided", seed=seed)
    return {**result, "p_value": _bca_p_value(result["share_at_or_below_margin"], z0, acceleration), "z0": z0,
            "acceleration": acceleration, "adjusted_alpha": adjusted}


def _bca_p_value(share: float, z0: float, acceleration: float) -> float:
    if share <= 0.0:
        return 0.0
    if share >= 1.0:
        return 1.0
    w = normal_quantile(share) - z0
    denominator = 1.0 + acceleration * w
    if denominator <= 0.0:  # beyond the adjusted percentile's range: every alpha rejects (a > 0) or none does (a < 0)
        return 0.0 if acceleration > 0 else 1.0
    return normal_cdf(w / denominator - z0)


def two_level_bootstrap_share_le_zero(groups: Sequence[Sequence[Any]], statistic: Callable[..., float], *, resamples: int,
                                      seed: str, indexed: bool = False) -> dict:
    """A two-level bootstrap (`hash-resample-two-level-v1`): resample the groups (hash-resample-v1 with `seed` and
    resample b), then the members of the group at each position k (hash-resample-v1 with seed f"{seed}\\x1f{b}\\x1f{k}"
    and resample 0). Reports the share of replicates at or below zero (H4a). With `indexed` the statistic is also told
    the replicate, `statistic(chosen, b)`, and `statistic(groups, None)` gives the estimate: E4 draws one seeded replay
    stream per replicate from the resampled items (VBT RevB Sec. X-A: "items are resampled before 1,000 replay streams
    are generated")."""
    outer = [list(group) for group in groups]
    if resamples < 1 or not outer or any(not group for group in outer):
        raise ValueError("a two-level bootstrap needs non-empty groups and at least one resample")
    replicates = []
    for b in range(resamples):
        chosen = []
        for k, index in enumerate(hash_resample_indices(len(outer), seed, b)):
            group = outer[index]
            chosen.append([group[i] for i in hash_resample_indices(len(group), f"{seed}\x1f{b}\x1f{k}", 0)])
        replicates.append(statistic(chosen, b) if indexed else statistic(chosen))
    share = sum(1 for value in replicates if value <= 0) / resamples
    return {"estimate": statistic(outer, None) if indexed else statistic(outer), "share_le_zero": share, "p_value": share,  # H4a's Holm input (VBT RevB Sec. X-A)
            "resamples": resamples, "seed": seed, "method": "two-level", "rule": "hash-resample-two-level-v1"}


def _ranks(values: Sequence[float]) -> list[float]:
    """Ranks from 1, ties sharing their average rank."""
    ordered = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start
        while end + 1 < len(ordered) and values[ordered[end + 1]] == values[ordered[start]]:
            end += 1
        for position in range(start, end + 1):
            ranks[ordered[position]] = (start + end) / 2.0 + 1.0
        start = end + 1
    return ranks


def friedman(blocks: Sequence[Sequence[float]]) -> dict:
    """Friedman's test over n >= 2 blocks (rows) of the same k >= 3 treatments (columns): average ranks for ties, the
    tie correction 1 - sum(t^3 - t) / (n k (k^2 - 1)), and p from chi-square with k - 1 degrees of freedom."""
    rows = [list(row) for row in blocks]
    k = len(rows[0]) if rows else 0
    if k < 3 or len(rows) < 2 or any(len(row) != k for row in rows):
        raise ValueError("Friedman's test needs at least two blocks of the same k >= 3 treatments")
    n = len(rows)
    sums = [0.0] * k
    ties = 0.0
    for row in rows:
        ranks = _ranks(row)
        for j, rank in enumerate(ranks):
            sums[j] += rank
        for rank in set(ranks):
            t = ranks.count(rank)
            ties += t ** 3 - t
    correction = 1.0 - ties / (n * k * (k * k - 1))
    if correction == 0:
        raise ValueError("Friedman's test is undefined when every block is fully tied")
    statistic = (12.0 / (n * k * (k + 1)) * sum(total * total for total in sums) - 3.0 * n * (k + 1)) / correction
    return {"statistic": statistic, "df": k - 1, "p_value": chi2_sf(statistic, k - 1), "rank_sums": sums, "blocks": n}


def paired_tost(left: Sequence[float], right: Sequence[float], *, margin: str, alpha: str = "0.05") -> dict:
    """Two one-sided paired t-tests of equivalence within (-margin, margin) on d = left - right: p = max(p_lower,
    p_upper) with p_lower = 1 - T((mean + margin) / se) and p_upper = T((mean - margin) / se), T Student's t with n - 1
    degrees of freedom; equivalence is supported when p <= alpha."""
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("a paired TOST needs at least two paired values")
    bound = float(Fraction(margin))
    if bound <= 0:
        raise ValueError("the equivalence margin must be positive")
    differences = [float(a) - float(b) for a, b in zip(left, right)]
    n = len(differences)
    mean = sum(differences) / n
    se = sqrt((sample_variance(differences) or 0.0) / n)
    if se == 0:
        p_lower = p_upper = 0.0 if -bound < mean < bound else 1.0
    else:
        p_lower = 1.0 - student_t_cdf((mean + bound) / se, n - 1)
        p_upper = student_t_cdf((mean - bound) / se, n - 1)
    p_value = max(p_lower, p_upper)
    return {"mean_difference": mean, "se": se, "df": n - 1, "margin": margin, "p_lower": p_lower, "p_upper": p_upper,
            "p_value": p_value, "equivalent": p_value <= float(Fraction(alpha)), "alpha": alpha}
