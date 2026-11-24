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
