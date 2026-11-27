"""Phase 10: the synthetic seeded-fault fixture and the reference detector's known answers (spec 3.8, 4.5; PD-66)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from evaluation.qcai_eval import seeded_faults

REPO_ROOT = Path(__file__).resolve().parents[2]


def fixture():
    return seeded_faults.load_fixture()


def detect(case, fix=None):
    fix = fix or fixture()
    return seeded_faults.reference_detect(case, spans=fix["spans"], misconceptions=fix["misconceptions"], parameters=fix["parameters"])


def test_the_finding_types_equal_the_ehmf_vocabulary():
    from app.services.ehmf.vocabulary import FINDING_TYPES

    assert seeded_faults.FINDING_TYPES == FINDING_TYPES
    assert tuple(fixture()["finding_types"]) == FINDING_TYPES


def test_the_fixture_has_six_clean_controls_and_three_insertions_per_type():
    cases = fixture()["cases"]
    assert len(cases) == 24
    assert sum(case["seeded_type"] is None for case in cases) == 6
    for finding in seeded_faults.FINDING_TYPES:
        assert sum(case["seeded_type"] == finding for case in cases) == 3


@pytest.mark.parametrize("finding", seeded_faults.FINDING_TYPES)
def test_each_rule_detects_its_seeded_cases_and_nothing_else(finding):
    for case in fixture()["cases"]:
        if case["seeded_type"] == finding:
            found = {kind for kinds in detect(case).values() for kind in kinds}
            assert found == {finding}, case["case_id"]


def test_no_clean_control_is_flagged():
    for case in fixture()["cases"]:
        if case["seeded_type"] is None:
            assert detect(case) == {}, case["case_id"]


def test_the_report_counts_recall_false_alarms_and_misattribution():
    report = seeded_faults.reference_report()
    assert report["all_known_answers_met"] and report["false_alarm_cases"] == []
    for finding, row in report["per_type"].items():
        assert row["seeded"] == row["detected"] == 3 and row["misattributed"] == [], finding
    # A detector that misses B2 and flags a clean control is reported as such.
    fix = fixture()
    detections = {case["case_id"]: detect(case, fix) for case in fix["cases"]}
    for case_id in [c["case_id"] for c in fix["cases"] if c["seeded_type"] == "B2"]:
        detections[case_id] = {}
    detections["sf-base-01"] = {"sf-base-01-c1": ["A"]}
    broken = seeded_faults.detection_report(fix, detections)
    assert not broken["all_known_answers_met"] and broken["per_type"]["B2"]["detected"] == 0
    assert broken["false_alarm_cases"] == ["sf-base-01"]


def test_disclosure_suppresses_d():
    fix = fixture()
    case = copy.deepcopy(next(c for c in fix["cases"] if c["case_id"] == "sf-D-01"))
    case["disclosure"] = True
    assert detect(case, fix) == {}


def test_the_committed_report_is_current():
    committed = json.loads((REPO_ROOT / "docs" / "evaluation" / "phase10" / "seeded_faults_report_v1.json").read_text(encoding="utf-8"))
    assert committed == seeded_faults.reference_report()
    assert committed["fixture_sha256"] == seeded_faults.fixture_sha256(fixture())
