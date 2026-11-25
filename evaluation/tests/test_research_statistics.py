"""Phase 10: Holm, McNemar, Wilson, the seeded bootstrap and the variance helpers, with known answers (spec 4.7; PD-70)."""

from __future__ import annotations

from fractions import Fraction
import hashlib

import pytest

from evaluation.qcai_eval import statistics


def test_wilson_upper_bounds_match_table_xix():
    assert statistics.wilson_upper_bound(0, 125) == pytest.approx(0.029815393708326456, abs=1e-15)
    assert statistics.wilson_upper_bound(0, 124) == pytest.approx(0.030048615340677695, abs=1e-15)
    assert statistics.wilson_upper_bound(0, 150) == pytest.approx(0.0249702443680766, abs=1e-15)
    assert statistics.wilson_upper_bound(0, 300) == pytest.approx(0.012642971224546034, abs=1e-15)
    assert statistics.wilson_upper_bound(0, 125) <= 0.03 < statistics.wilson_upper_bound(0, 124)  # HR-3 needs at least 125


def test_mcnemar_exact_known_answer():
    left = [True] * 1 + [False] * 9 + [True] * 5
    right = [False] * 1 + [True] * 9 + [True] * 5
    result = statistics.mcnemar_exact(left, right)
    assert result["discordant"] == 10 and result["p_value"] == pytest.approx(float(Fraction(11, 512)), abs=1e-15)


def test_holm_known_answer_and_monotonicity():
    result = statistics.holm({"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.005})
    assert {name: round(value["adjusted"], 12) for name, value in result.items()} == {"d": 0.02, "a": 0.03, "c": 0.06, "b": 0.06}
    assert {name for name, value in result.items() if value["reject"]} == {"d", "a"}
    assert statistics.holm({"x": 0.6, "y": 0.7})["y"]["adjusted"] == 1.0
    # Step-down monotonicity: a larger p never gets a smaller adjusted value, even when (m - j + 1) p_(j) falls.
    assert result["b"]["adjusted"] >= result["c"]["adjusted"]


def test_hash_resample_indices_follow_the_published_rule():
    expected = [int.from_bytes(hashlib.sha256(f"seed\x1f0\x1f{j}".encode()).digest()[:8], "big") % 7 for j in range(7)]
    assert statistics.hash_resample_indices(7, "seed", 0) == expected
    assert statistics.hash_resample_indices(7, "seed", 1) != expected
    with pytest.raises(ValueError):
        statistics.hash_resample_indices(0, "seed", 0)


def test_the_bootstrap_is_deterministic_and_uses_the_percentile_indices():
    clusters = [0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    mean = lambda values: sum(values) / len(values)  # noqa: E731
    first = statistics.bootstrap(clusters, mean, resamples=1000, seed="s")
    assert first == statistics.bootstrap(clusters, mean, resamples=1000, seed="s")
    replicates = sorted(mean([clusters[i] for i in statistics.hash_resample_indices(10, "s", b)]) for b in range(1000))
    assert first["lower"] == replicates[25] and first["upper"] == replicates[974]
    assert first["method"] == "percentile" and first["rule"] == "hash-resample-v1" and first["estimate"] == 0.4
    assert statistics.bootstrap(clusters, mean, resamples=1000, seed="t") != first


def test_sample_variance_and_slope():
    assert statistics.sample_variance([1, 2, 3, 4]) == pytest.approx(5 / 3)
    assert statistics.sample_variance([1]) is None
    assert statistics.least_squares_slope([(1, 1.0), (2, 3.0), (3, 5.0)]) == pytest.approx(2.0)
    assert statistics.least_squares_slope([(1, 1.0)]) is None
    assert statistics.least_squares_slope([(1, 1.0), (1, 2.0)]) is None


# --- The analysis plans' registered tests: closed forms, table values and hand-computed answers. --------------------


def test_chi_square_and_student_t_tails_match_closed_forms_and_table_values():
    from math import atan, exp, pi

    for x in (0.1, 1.0, 5.991464547107979, 13.8):
        assert statistics.chi2_sf(x, 2) == pytest.approx(exp(-x / 2), rel=1e-12)  # df 2: exp(-x/2) exactly
    assert statistics.chi2_sf(3.841458820694124, 1) == pytest.approx(0.05, abs=1e-12)  # 5% points of the chi-square table
    assert statistics.chi2_sf(7.814727903251178, 3) == pytest.approx(0.05, abs=1e-12)
    assert statistics.chi2_sf(0.0, 4) == 1.0
    for t in (-3.0, -1.0, 0.0, 0.5, 1.0, 3.0, 40.0):
        assert statistics.student_t_cdf(t, 1) == pytest.approx(0.5 + atan(t) / pi, abs=1e-13)  # df 1 is the Cauchy law
    assert statistics.student_t_cdf(2.2281388519649385, 10) == pytest.approx(0.975, abs=1e-11)  # t table, 10 df
    assert statistics.student_t_cdf(-1.8124611228107335, 10) == pytest.approx(0.05, abs=1e-11)
    assert statistics.normal_quantile(0.975) == pytest.approx(1.959963984540054, abs=1e-12)
    assert statistics.normal_cdf(statistics.normal_quantile(0.05)) == pytest.approx(0.05, abs=1e-13)
    for call in (lambda: statistics.chi2_sf(1.0, 0), lambda: statistics.student_t_cdf(1.0, 0), lambda: statistics.normal_quantile(1.0)):
        with pytest.raises(ValueError):
            call()


def test_friedman_known_answers_with_and_without_ties():
    from math import exp

    # Four blocks ranking three treatments alike: rank sums 4, 8, 12, so Q = 12 / (4 * 3 * 4) * 224 - 48 = 8, p = exp(-4).
    result = statistics.friedman([[1, 2, 3]] * 4)
    assert result["statistic"] == pytest.approx(8.0, abs=1e-12) and result["df"] == 2
    assert result["p_value"] == pytest.approx(exp(-4), rel=1e-12) and result["rank_sums"] == [4.0, 8.0, 12.0]
    # With ties: average ranks give rank sums 12, 13.5, 11.5, 13 (sum of squares 627.5), so the uncorrected Q is
    # 0.12 * 627.5 - 75 = 0.3; a pair ties in three blocks and a triple in one, so the correction is
    # 1 - (6 + 6 + 6 + 24) / (5 * 4 * 15) = 0.86 and Q = 0.3 / 0.86 (scipy.stats.friedmanchisquare agrees).
    tied = statistics.friedman([[3, 3, 1, 2], [2, 4, 4, 1], [1, 1, 2, 3], [5, 2, 2, 2], [1, 3, 2, 4]])
    assert tied["rank_sums"] == [12.0, 13.5, 11.5, 13.0] and tied["df"] == 3
    assert tied["statistic"] == pytest.approx(0.3 / 0.86, abs=1e-12)
    for bad in ([[1, 2]] * 3, [[1, 2, 3]], [[1, 2, 3], [1, 2]], [[1, 1, 1], [2, 2, 2]]):
        with pytest.raises(ValueError):
            statistics.friedman(bad)


def test_paired_tost_known_answers():
    from math import atan, pi

    # Two pairs give one degree of freedom (the Cauchy law): d = (1, 0), mean 0.5, se 0.5, margin 1, so
    # p_lower = 1 - T(3) = 0.5 - atan(3) / pi and p_upper = T(-1) = 0.25.
    result = statistics.paired_tost([1, 0], [0, 0], margin="1")
    assert result["p_lower"] == pytest.approx(0.5 - atan(3) / pi, abs=1e-13) and result["p_upper"] == pytest.approx(0.25, abs=1e-13)
    assert result["p_value"] == result["p_upper"] and result["equivalent"] is False and result["df"] == 1
    close = statistics.paired_tost([1.0, 2.1, 3.0, 2.5, 1.9, 2.2], [1.1, 2.0, 2.8, 2.6, 2.0, 2.0], margin="0.5")
    assert close["equivalent"] is True and close["p_value"] == pytest.approx(0.0003146448802213064, rel=1e-9)  # scipy agrees
    assert statistics.paired_tost([1, 1], [1, 1], margin="0.5")["p_value"] == 0.0  # no spread, inside the margin
    assert statistics.paired_tost([2, 2], [1, 1], margin="0.5")["p_value"] == 1.0  # no spread, outside it
    for call in (lambda: statistics.paired_tost([1], [1], margin="1"), lambda: statistics.paired_tost([1, 2], [1, 2], margin="0"),
                 lambda: statistics.paired_tost([1, 2], [1], margin="1")):
        with pytest.raises(ValueError):
            call()


def _mean(values):
    return sum(values) / len(values)


def test_the_one_sided_paired_and_cluster_bootstraps_use_the_lower_percentile_index():
    data = [0.2, 1.5, 0.3, 2.8, 0.9, 0.1, 4.0, 0.6, 1.1, 0.4]
    result = statistics.bootstrap_one_sided(data, _mean, resamples=2000, seed="bca", margin="0.5")
    replicates = sorted(_mean([data[i] for i in statistics.hash_resample_indices(10, "bca", b)]) for b in range(2000))
    assert result["lower_bound"] == replicates[100] and result["reject"] is (replicates[100] > 0.5)
    assert result["share_at_or_below_margin"] == sum(1 for value in replicates if value <= 0.5) / 2000
    assert result == statistics.bootstrap_one_sided(data, _mean, resamples=2000, seed="bca", margin="0.5")
    few = sorted(_mean([data[i] for i in statistics.hash_resample_indices(10, "f", b)]) for b in range(30))
    assert statistics.bootstrap_one_sided(data, _mean, resamples=30, seed="f")["lower_bound"] == few[1]  # floor(0.05 * 30) = 1
    left, right = [1, 1, 0, 1, 1, 0, 1, 1], [1, 0, 0, 1, 0, 0, 1, 1]
    paired = statistics.paired_bootstrap_one_sided(left, right, resamples=500, seed="p", margin="-0.05")
    pairs = list(zip(map(float, left), map(float, right)))
    differences = sorted(sum(a - b for a, b in (pairs[i] for i in statistics.hash_resample_indices(8, "p", r))) / 8 for r in range(500))
    assert paired["estimate"] == 0.25 and paired["lower_bound"] == differences[25] and paired["method"] == "paired-percentile-one-sided"
    assert paired["reject"] is (differences[25] > -0.05)
    clusters = [[1, 0], [1], [0, 0, 1], [1, 1]]

    def pooled(chosen):
        return _mean([value for cluster in chosen for value in cluster])

    cluster = statistics.cluster_bootstrap_lower_bound(clusters, pooled, resamples=400, seed="c")
    expected = sorted(pooled([clusters[i] for i in statistics.hash_resample_indices(4, "c", b)]) for b in range(400))[20]
    assert cluster["lower_bound"] == expected and cluster["method"] == "cluster-percentile-one-sided"
    with pytest.raises(ValueError):
        statistics.paired_bootstrap_one_sided([1], [1, 0], resamples=10, seed="x")


@pytest.mark.parametrize("alpha", ["0.05", "0.1", "0.025"])
def test_each_one_sided_bootstrap_returns_a_holm_p_value_that_agrees_with_its_reject(alpha):
    # VBT RevB Sec. X-A: "Each hypothesis enters Holm through one p-value: ... one-sided bootstrap p-values for H1c, H2a,
    # H2b ... and H2c". Over margins on both sides of the bound, p_value <= alpha exactly when the test rejects.
    data = [0.2, 1.5, 0.3, 2.8, 0.9, 0.1, 4.0, 0.6, 1.1, 0.4]
    clusters = [[1.2], [0.9], [1.5], [1.1], [0.7, 1.3], [2.0]]
    labels = [True, False, True, False, True, False, True, False]
    seen: dict[str, set] = {}
    for margin in [f"{value / 100:.2f}" for value in range(20, 160, 6)]:
        results = [statistics.bootstrap_one_sided(data, _mean, resamples=1000, seed="p", margin=margin, alpha=alpha),
                   statistics.cluster_bootstrap_lower_bound(clusters, lambda c: _mean([v for x in c for v in x]), resamples=800,
                                                            seed="c", margin=margin, alpha=alpha),
                   statistics.cluster_bootstrap_bca_one_sided(data, _mean, resamples=1000, seed="bca", margin=margin, alpha=alpha),
                   statistics.paired_bootstrap_one_sided(data, [x / 2 for x in data], resamples=700, seed="q",
                                                         margin=f"{float(margin) - 0.8:.2f}", alpha=alpha),
                   statistics.paired_bootstrap_auc_one_sided(labels, [0.9, 0.2, 0.8, 0.3, 0.7, 0.1, 0.6, 0.4],
                                                             [0.6, 0.5, 0.4, 0.3, 0.7, 0.2, 0.5, 0.6], resamples=600, seed="a",
                                                             margin=f"{float(margin) - 0.9:.2f}", alpha=alpha)]
        for result in results:
            assert 0.0 <= result["p_value"] <= 1.0
            assert (result["p_value"] <= float(alpha)) is result["reject"], (result["method"], margin, result["p_value"])
            seen.setdefault(result["method"], set()).add(result["reject"])
    assert len(seen) == 5 and all(outcomes == {True, False} for outcomes in seen.values())  # every form both rejects and not


def test_the_bca_p_value_inverts_the_adjusted_percentile_and_differs_from_the_plain_share():
    data = [0.2, 1.5, 0.3, 2.8, 0.9, 0.1, 4.0, 0.6, 1.1, 0.4]
    result = statistics.cluster_bootstrap_bca_one_sided(data, _mean, resamples=2000, seed="bca", margin="0.65")
    # The BCa bound (0.68) exceeds 0.65, so H0 is rejected at 0.05; the plain percentile share (0.0605) would not be.
    assert result["reject"] is True and result["share_at_or_below_margin"] == pytest.approx(0.0605, abs=1e-12)
    w = statistics.normal_quantile(0.0605) - result["z0"]
    expected = statistics.normal_cdf(w / (1 + result["acceleration"] * w) - result["z0"])
    assert result["p_value"] == pytest.approx(expected, abs=1e-15) and result["p_value"] < 0.05 < result["share_at_or_below_margin"]
    assert statistics.cluster_bootstrap_bca_one_sided(data, _mean, resamples=2000, seed="bca", margin="-1")["p_value"] == 0.0
    assert statistics.cluster_bootstrap_bca_one_sided(data, _mean, resamples=2000, seed="bca", margin="9")["p_value"] == 1.0
    plain = statistics.bootstrap_one_sided(data, _mean, resamples=2000, seed="bca", margin="0.65")
    assert plain["p_value"] == plain["share_at_or_below_margin"] == pytest.approx(0.0605, abs=1e-12) and plain["reject"] is False
    two_level = statistics.two_level_bootstrap_share_le_zero([[0.5, -0.2], [0.1], [-0.4, 0.3]], lambda g: _mean([v for x in g for v in x]),
                                                            resamples=100, seed="t")
    assert two_level["p_value"] == two_level["share_le_zero"]


def test_the_auc_and_the_paired_auc_bootstrap_known_answers():
    labels = [True, True, False, False]
    assert statistics.auc(labels, [0.9, 0.8, 0.2, 0.1]) == 1.0
    assert statistics.auc(labels, [0.1, 0.2, 0.8, 0.9]) == 0.0
    assert statistics.auc(labels, [0.5, 0.5, 0.5, 0.5]) == 0.5
    assert statistics.auc(labels, [0.9, 0.3, 0.5, 0.1]) == 0.75  # 3 of 4 positive-negative pairs ordered
    with pytest.raises(ValueError):
        statistics.auc([True, True], [0.1, 0.2])
    left, right = [0.9, 0.8, 0.2, 0.1], [0.9, 0.3, 0.5, 0.1]
    result = statistics.paired_bootstrap_auc_one_sided(labels, left, right, resamples=400, seed="h2c")
    rows = list(zip(labels, left, right))

    def difference(chosen):
        try:
            return statistics.auc([r[0] for r in chosen], [r[1] for r in chosen]) - statistics.auc([r[0] for r in chosen], [r[2] for r in chosen])
        except ValueError:
            return float("-inf")

    replicates = sorted(difference([rows[i] for i in statistics.hash_resample_indices(4, "h2c", b)]) for b in range(400))
    assert result["estimate"] == 0.25 and result["lower_bound"] == replicates[20] and result["method"] == "paired-auc-percentile-one-sided"
    assert result["p_value"] == sum(1 for value in replicates if value <= 0) / 400
    with pytest.raises(ValueError):
        statistics.paired_bootstrap_auc_one_sided(labels, left, right[:3], resamples=10, seed="x")


def test_the_bca_lower_bound_known_answer_and_its_undefined_case():
    data = [0.2, 1.5, 0.3, 2.8, 0.9, 0.1, 4.0, 0.6, 1.1, 0.4]
    result = statistics.cluster_bootstrap_bca_one_sided(data, _mean, resamples=2000, seed="bca")
    # Recomputed independently (numpy and scipy.stats.norm) from the same 2000 hash-resample-v1 replicates.
    assert result["z0"] == pytest.approx(0.02256156839022472, abs=1e-9)
    assert result["acceleration"] == pytest.approx(0.06774727499994508, abs=1e-12)
    assert result["adjusted_alpha"] == pytest.approx(0.07506297081900551, abs=1e-9)
    assert result["lower_bound"] == pytest.approx(0.68, abs=1e-12) and result["method"] == "cluster-bca-one-sided"
    # The right skew moves the BCa bound above the plain percentile bound (0.63).
    assert statistics.bootstrap_one_sided(data, _mean, resamples=2000, seed="bca")["lower_bound"] == pytest.approx(0.63, abs=1e-12)
    symmetric = statistics.cluster_bootstrap_bca_one_sided([-2.0, -1.0, 0.0, 1.0, 2.0], _mean, resamples=500, seed="s")
    assert symmetric["acceleration"] == pytest.approx(0.0, abs=1e-15)
    with pytest.raises(ValueError):
        statistics.cluster_bootstrap_bca_one_sided([1.0, 1.0, 1.0], _mean, resamples=50, seed="s")  # no replicate below it


def test_the_two_level_bootstrap_follows_its_published_rule():
    groups = [[0.5, -0.2], [0.1], [-0.4, 0.3, 0.2], [0.6, 0.0]]

    def pooled(chosen):
        return _mean([value for group in chosen for value in group])

    result = statistics.two_level_bootstrap_share_le_zero(groups, pooled, resamples=300, seed="t")
    replicates = []
    for b in range(300):
        chosen = [[groups[g][i] for i in statistics.hash_resample_indices(len(groups[g]), f"t\x1f{b}\x1f{k}", 0)]
                  for k, g in enumerate(statistics.hash_resample_indices(4, "t", b))]
        replicates.append(pooled(chosen))
    assert result["share_le_zero"] == sum(1 for value in replicates if value <= 0) / 300
    assert result["estimate"] == pytest.approx(pooled(groups)) and result["rule"] == "hash-resample-two-level-v1"
    assert statistics.two_level_bootstrap_share_le_zero([[1.0], [2.0, 3.0]], pooled, resamples=50, seed="t")["share_le_zero"] == 0.0
    assert statistics.two_level_bootstrap_share_le_zero([[-1.0], [0.0]], pooled, resamples=50, seed="t")["share_le_zero"] == 1.0
    with pytest.raises(ValueError):
        statistics.two_level_bootstrap_share_le_zero([[1.0], []], pooled, resamples=5, seed="t")
