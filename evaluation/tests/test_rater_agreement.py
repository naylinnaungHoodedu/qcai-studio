"""Phase 10: Krippendorff's alpha, Cohen's kappa and second-rater coverage, with published known answers (spec 4.4; PD-65)."""

from __future__ import annotations

from fractions import Fraction
import json

import pytest

from evaluation.qcai_eval import agreement, synthetic, ulqs

# Krippendorff (2011), "Computing Krippendorff's Alpha-Reliability": 4 coders x 12 units with missing values.
N = None
K2011 = [list(unit) for unit in zip([1, 2, 3, 3, 2, 1, 4, 1, 2, N, N, N], [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, N, 3],
                                    [N, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, N], [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, N])]
# Krippendorff's two-coder binary example (10 units).
TWO_A = [0, 1, 0, 0, 0, 0, 0, 0, 1, 0]
TWO_B = [1, 1, 1, 0, 0, 1, 0, 0, 0, 0]
RUBRIC = "a" * 64


def test_krippendorff_nominal_and_ordinal_known_answers():
    assert agreement.krippendorff_alpha(K2011) == Fraction(113, 152)
    assert agreement.krippendorff_alpha(K2011, level="ordinal") == Fraction(108577, 133160)
    assert agreement.krippendorff_alpha(K2011, level="ordinal", ranking=[1, 2, 3, 4, 5]) == Fraction(108577, 133160)


def test_two_coder_alpha_and_cohen_kappa_known_answers():
    assert agreement.krippendorff_alpha([list(unit) for unit in zip(TWO_A, TWO_B)]) == Fraction(2, 21)
    assert agreement.cohen_kappa(TWO_A, TWO_B) == Fraction(1, 11)


def test_perfect_agreement_is_one_and_no_variation_raises():
    assert agreement.krippendorff_alpha([["a", "a"], ["b", "b"], ["a", "a", "a"]]) == 1
    with pytest.raises(ValueError, match="no variation"):
        agreement.krippendorff_alpha([["a", "a"], ["a", "a"]])
    with pytest.raises(ValueError, match="no variation"):
        agreement.krippendorff_alpha([["a"], ["b"]])  # no unit is pairable
    with pytest.raises(ValueError):
        agreement.krippendorff_alpha(K2011, level="interval")


def ratings_for(items, **kwargs):
    return synthetic.synthetic_ratings(items, rubric_sha256=RUBRIC, **kwargs)


def test_coverage_counts_abstention_units_and_uses_the_ceiling_per_stratum():
    items = synthetic.synthetic_dataset({"A": 5, "B": 1, "C": 5, "D": 2, "E": 3, "F": 4, "G": 1})
    ratings = ratings_for(items)
    covered = agreement.coverage(ratings, items)
    assert covered["per_stratum"] == {"A": [2, 5], "B": [1, 1], "C": [2, 5], "D": [1, 2], "E": [1, 3], "F": [1, 4], "G": [1, 1]}
    assert covered["second_rated_items"] == 9 and covered["share"] == "3/7"  # 9 of 21, reduced
    # C and E carry no claims: they are second-rated through their abstention units only.
    assert any(r["unit_id"] == "SYN-C-001-abstention" and r["rater"] == "R2" for r in ratings)
    assert covered["double_labelled_claims"] == sum(1 for unit, raters in _units(ratings).items()
                                                    if not unit.endswith("-abstention") and len(raters) >= 2)


def _units(ratings):
    units = {}
    for rating in ratings:
        units.setdefault(rating["unit_id"], set()).add(rating["rater"])
    return units


def test_only_main_round_labels_count():
    items = synthetic.synthetic_dataset({"A": 4})
    ratings = ratings_for(items)
    for rating in ratings:
        if rating["rater"] == "R2":
            rating["round"] = "calibration"
    assert agreement.coverage(ratings, items)["second_rated_items"] == 0


def test_the_agreement_record_holds_no_labels_or_text_and_is_unaffected_by_status(tmp_path):
    items = synthetic.synthetic_dataset(synthetic.PAPER_TARGETS)
    rules = ulqs.load_freeze_rules()
    ratings = ratings_for(items, disagree=1)
    record = agreement.agreement_record(ratings, items, rules=rules, rubric_sha256=RUBRIC, ratings_sha256="b" * 64)
    text = json.dumps(record)
    for label in agreement.CLAIM_LABELS + agreement.ABSTENTION_LABELS:
        assert label not in text
    assert "Invented" not in text and record["record"] == "ulqs-agreement-v1"
    assert record["gate"]["passed"] and Fraction(record["alpha_nominal_label"]) >= Fraction("0.667")
    frozen = [{**item, "status": "frozen"} for item in items]
    assert ulqs.dataset_content_sha256(frozen) == record["dataset_content_sha256"]
    assert ulqs.dataset_sha256(frozen) != ulqs.dataset_sha256(items)


def test_rater_codes_and_label_vocabularies_are_enforced(tmp_path):
    items = synthetic.synthetic_dataset({"A": 1, "C": 1})
    ratings = ratings_for(items)
    good = synthetic.write_jsonl(tmp_path / "r.private.jsonl", ratings)
    assert len(agreement.load_ratings(good)) == len(ratings)
    for change, message in ((lambda r: r.update(rater="Dr Example"), "rater pattern"),
                            (lambda r: r.update(label="supported_abstention"), "label enum"),
                            (lambda r: r.update(round="final"), "round enum"),
                            (lambda r: r.update(ehmf_type="Z"), "ehmf_type enum"),
                            (lambda r: r.update(note="free text"), "unexpected")):
        bad = [dict(rating) for rating in ratings]
        change(bad[0])
        path = synthetic.write_jsonl(tmp_path / "bad.private.jsonl", bad)
        with pytest.raises(ValueError, match=message) as raised:
            agreement.load_ratings(path)
        assert "Dr Example" not in str(raised.value) and "free text" not in str(raised.value)
    abstention = [dict(rating) for rating in ratings]
    target = next(r for r in abstention if r["unit_id"].endswith("-abstention"))
    target["label"] = "supported"
    with pytest.raises(ValueError, match="label enum"):
        agreement.load_ratings(synthetic.write_jsonl(tmp_path / "abs.private.jsonl", abstention))


def test_kappa_is_reported_only_for_exactly_two_raters_on_the_same_units():
    items = synthetic.synthetic_dataset({"A": 4})
    rules = ulqs.load_freeze_rules()
    ratings = ratings_for(items, share="1")
    assert agreement.agreement_record(ratings, items, rules=rules, rubric_sha256=RUBRIC, ratings_sha256="b" * 64)["cohen_kappa_label"] is not None
    partial = ratings_for(items, share="1/2")
    assert agreement.agreement_record(partial, items, rules=rules, rubric_sha256=RUBRIC, ratings_sha256="b" * 64)["cohen_kappa_label"] is None
