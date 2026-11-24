"""Rater agreement: Krippendorff's alpha (nominal, ordinal), Cohen's kappa, second-rater coverage (spec 3.5, 4.4; PD-64, PD-65).

The definitions follow Krippendorff (2011), "Computing Krippendorff's Alpha-Reliability", in exact Fractions:
o_ck = sum over units of (pairs of values c, k within the unit) / (m_u - 1), units with one value dropped; n_c = sum_k o_ck;
alpha = 1 - (n - 1) * sum o_ck d2_ck / sum n_c n_k d2_ck. Nominal d2 is 0/1; ordinal
d2_ck = (sum_{g between c and k} n_g - (n_c + n_k) / 2) ** 2 over the ranked values. Interval and ratio levels are not
implemented. Ratings are research data: a ratings file is private, and the agreement record holds counts and statistics,
never a label or a text. Rater fields hold pseudonymous codes (R1, R2, ...).
"""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from math import ceil
from pathlib import Path
import re
from typing import Any, Hashable, Literal, Mapping, Sequence

from .canonical import read_jsonl

RATER = re.compile(r"^R[0-9]{1,3}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
CLAIM_LABELS = ("supported", "attribution_error", "unsupported_but_true", "fabricated")
ABSTENTION_LABELS = ("supported_abstention", "unsupported_abstention")
EHMF_TYPES = ("A", "B1", "B2", "C", "D", "E")
ROUNDS = ("calibration", "main", "adjudication")
RATING_KEYS = ("item_id", "unit_id", "rater", "label", "ehmf_type", "round", "rubric_sha256")


def coincidence_matrix(units: Sequence[Sequence[Hashable]]) -> tuple[dict, dict, Fraction]:
    """(o_ck, n_c, n) over the pairable units (two values or more; None values are missing)."""
    coincidences: dict[tuple[Hashable, Hashable], Fraction] = defaultdict(Fraction)
    for unit in units:
        values = [value for value in unit if value is not None]
        m = len(values)
        if m < 2:
            continue
        for i, left in enumerate(values):
            for j, right in enumerate(values):
                if i != j:
                    coincidences[(left, right)] += Fraction(1, m - 1)
    totals: dict[Hashable, Fraction] = defaultdict(Fraction)
    for (left, _right), value in coincidences.items():
        totals[left] += value
    return dict(coincidences), dict(totals), sum(totals.values(), Fraction(0))


def _ordinal_distance(order: list, totals: Mapping, c: Hashable, k: Hashable) -> Fraction:
    low, high = sorted((order.index(c), order.index(k)))
    between = sum((totals.get(order[g], Fraction(0)) for g in range(low, high + 1)), Fraction(0))
    return (between - (totals.get(c, Fraction(0)) + totals.get(k, Fraction(0))) / 2) ** 2


def krippendorff_alpha(units: Sequence[Sequence[Hashable]], *, level: Literal["nominal", "ordinal"] = "nominal",
                       ranking: Sequence[Hashable] | None = None) -> Fraction:
    coincidences, totals, n = coincidence_matrix(units)
    if len(totals) < 2:
        raise ValueError("no variation")
    values = list(totals)
    if level == "nominal":
        def distance(c, k):
            return Fraction(0) if c == k else Fraction(1)
    elif level == "ordinal":
        order = list(ranking) if ranking is not None else sorted(values)
        missing = [value for value in values if value not in order]
        if missing:
            raise ValueError("ordinal ranking does not name every value")

        def distance(c, k):
            return _ordinal_distance(order, totals, c, k)
    else:
        raise ValueError("level must be nominal or ordinal (interval and ratio are not implemented)")
    observed = sum((value * distance(c, k) for (c, k), value in coincidences.items()), Fraction(0))
    expected = sum((totals[c] * totals[k] * distance(c, k) for c in values for k in values), Fraction(0))
    if expected == 0:
        raise ValueError("no variation")
    return 1 - (n - 1) * observed / expected


def cohen_kappa(left: Sequence[Hashable], right: Sequence[Hashable]) -> Fraction:
    if len(left) != len(right) or not left:
        raise ValueError("kappa needs two equal, non-empty label sequences")
    total = len(left)
    observed = Fraction(sum(a == b for a, b in zip(left, right)), total)
    categories = set(left) | set(right)
    expected = sum((Fraction(list(left).count(c), total) * Fraction(list(right).count(c), total) for c in categories), Fraction(0))
    if expected == 1:
        raise ValueError("no variation")
    return (observed - expected) / (1 - expected)


def _is_abstention_unit(unit_id: str) -> bool:
    return unit_id.endswith("-abstention")


def load_ratings(path: Path) -> list[Mapping[str, Any]]:
    """Ratings lines, validated. An error names the line number and the field, never a value."""
    ratings = read_jsonl(Path(path))
    for number, line in enumerate(ratings, start=1):
        for key in RATING_KEYS:
            if key not in line:
                raise ValueError(f"ratings line {number}: {key} missing")
        for key in line:
            if key not in RATING_KEYS:
                raise ValueError(f"ratings line {number}: {key} unexpected")
        for key in ("item_id", "unit_id"):
            if not isinstance(line[key], str) or not line[key]:
                raise ValueError(f"ratings line {number}: {key} type")
        if not isinstance(line["rater"], str) or not RATER.match(line["rater"]):
            raise ValueError(f"ratings line {number}: rater pattern (a pseudonymous code R1..R999)")
        allowed = ABSTENTION_LABELS if _is_abstention_unit(line["unit_id"]) else CLAIM_LABELS
        if line["label"] not in allowed:
            raise ValueError(f"ratings line {number}: label enum")
        if line["ehmf_type"] is not None and line["ehmf_type"] not in EHMF_TYPES:
            raise ValueError(f"ratings line {number}: ehmf_type enum")
        if line["round"] not in ROUNDS:
            raise ValueError(f"ratings line {number}: round enum")
        if not isinstance(line["rubric_sha256"], str) or not HEX64.match(line["rubric_sha256"]):
            raise ValueError(f"ratings line {number}: rubric_sha256 pattern")
    return ratings


def _main_labels(ratings: Sequence[Mapping[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    """unit_id -> {rater: value} over the main round (a rater's later main-round line replaces the earlier one)."""
    units: dict[str, dict[str, Any]] = {}
    for rating in ratings:
        if rating.get("round") != "main":
            continue
        units.setdefault(rating["unit_id"], {})[rating["rater"]] = rating.get(field)
    return units


def units_from_ratings(ratings: Sequence[Mapping[str, Any]], field: str = "label") -> list[list]:
    return [list(values.values()) for _unit, values in sorted(_main_labels(ratings, field).items())]


def coverage(ratings: Sequence[Mapping[str, Any]], items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    from .ulqs import STRATA, rated_units

    labels = _main_labels(ratings, "label")
    live = [item for item in items if item.get("status") != "retired"]
    per_stratum = {letter: [0, 0] for letter in STRATA}
    second_rated = 0
    double_claims = 0
    for item in live:
        units = rated_units(item)
        letter = item.get("stratum")
        if letter in per_stratum:
            per_stratum[letter][1] += 1
        double_claims += sum(1 for unit in units if not _is_abstention_unit(unit) and len(labels.get(unit, {})) >= 2)
        if units and all(len(labels.get(unit, {})) >= 2 for unit in units):
            second_rated += 1
            if letter in per_stratum:
                per_stratum[letter][0] += 1
    share = Fraction(second_rated, len(live)) if live else Fraction(0)
    return {"items": len(live), "second_rated_items": second_rated, "share": f"{share.numerator}/{share.denominator}",
            "per_stratum": per_stratum, "double_labelled_claims": double_claims}


def _ratio(value: Fraction | None) -> str | None:
    return None if value is None else f"{value.numerator}/{value.denominator}"


def _alpha_or_none(units: list[list]) -> Fraction | None:
    try:
        return krippendorff_alpha(units)
    except ValueError:
        return None


def _two_rater_kappa(ratings: Sequence[Mapping[str, Any]]) -> Fraction | None:
    labels = _main_labels(ratings, "label")
    raters = {rater for values in labels.values() for rater in values}
    if len(raters) != 2 or not labels or any(set(values) != raters for values in labels.values()):
        return None
    first, second = sorted(raters)
    try:
        return cohen_kappa([labels[unit][first] for unit in sorted(labels)], [labels[unit][second] for unit in sorted(labels)])
    except ValueError:
        return None


def agreement_record(ratings: Sequence[Mapping[str, Any]], items: Sequence[Mapping[str, Any]], *, rules: Any, rubric_sha256: str,
                     ratings_sha256: str) -> dict[str, Any]:
    from .ulqs import STRATA, dataset_content_sha256

    alpha_label = _alpha_or_none(units_from_ratings(ratings, "label"))
    alpha_ehmf = _alpha_or_none(units_from_ratings(ratings, "ehmf_type"))
    covered = coverage(ratings, items)
    failures: list[str] = []
    if alpha_label is None or alpha_label < rules.alpha_min:
        failures.append("alpha_below_floor")
    if Fraction(covered["share"]) < rules.share_min:
        failures.append("second_rated_below_share")
    for letter in STRATA:
        rated, total = covered["per_stratum"][letter]
        if rated < ceil(total * rules.share_min):
            failures.append(f"stratum_second_rated_below_share:{letter}")
    main = [rating for rating in ratings if rating.get("round") == "main"]
    return {
        "record": "ulqs-agreement-v1",
        "ratings_sha256": ratings_sha256,
        "dataset_content_sha256": dataset_content_sha256(items),
        "rubric_sha256": rubric_sha256,
        "raters": len({rating["rater"] for rating in main}),
        "units": len({rating["unit_id"] for rating in main}),
        "alpha_nominal_label": _ratio(alpha_label),
        "alpha_nominal_ehmf": _ratio(alpha_ehmf),
        "cohen_kappa_label": _ratio(_two_rater_kappa(ratings)),
        "coverage": covered,
        "gate": {"passed": not failures, "failures": failures},
    }
