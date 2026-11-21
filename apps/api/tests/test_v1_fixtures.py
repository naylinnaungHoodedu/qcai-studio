"""The adversarial fixture runner (scripts/run_v1_fixtures.py; Phase 4 spec 12; plan Phase 4 F, H)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re

import pytest

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.services.store import get_course_store
from app.services.tutor_pipeline import pipeline as pipeline_module

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "docs" / "evaluation" / "phase4" / "v1_adversarial_fixtures_v1.json"


def load_runner():
    spec = importlib.util.spec_from_file_location("phase4_run_v1_fixtures", REPO_ROOT / "scripts" / "run_v1_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = load_runner()


def test_wilson_vectors():
    assert RUNNER.wilson95(5, 5) == [0.5655, 1.0]
    assert RUNNER.wilson95(166, 174) == [0.9119, 0.9765]
    assert RUNNER.wilson95(146, 174) == [0.7773, 0.8863]
    assert RUNNER.wilson95(0, 3) == [0.0, 0.5615]
    assert RUNNER.wilson95(0, 0) is None


def test_the_case_report_is_deterministic():
    first = RUNNER.compute(answer_rate=False, commit_source=lambda: "0" * 40)
    second = RUNNER.compute(answer_rate=False, commit_source=lambda: "0" * 40)
    assert RUNNER._strip_volatile(first) == RUNNER._strip_volatile(second)
    assert first["result"] == "pass" and first["evidence_class"] == "fixture measurements, not research results (plan Phase 4 H)"


def test_an_unrealisable_case_exits_1_and_names_it(tmp_path, capsys):
    payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    payload["cases"] = [{"id": "unrealisable-01", "class": "stripped_negation", "level": "pipeline", "query": "What is the capital of France?",
                         "attack": {"kind": "claim_transform", "transform": "strip_negation"}, "expect": {"caught_by": ["V1.2"]}}]
    path = tmp_path / "fixtures.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert RUNNER.main(["--check", str(tmp_path / "report.json"), "--fixtures", str(path)]) == RUNNER.EXIT_DRIFT
    assert "unrealisable-01" in capsys.readouterr().err


def test_a_crippled_check_delivers_an_adversarial_case_and_exits_5(monkeypatch):
    from app.services.v1_checks import runner as track
    from app.services.v1_checks.results import make_result

    monkeypatch.setattr(track, "check_v1_7", lambda locked, bundle, **kwargs: (make_result("V1.7", "pre_render", kwargs["attempt"], "no_conflict"), None))
    report = RUNNER.compute(answer_rate=False, commit_source=lambda: "0" * 40)
    assert report["result"] == "delivered" and RUNNER.exit_code(report) == RUNNER.EXIT_DELIVERED
    deterministic = next(c for c in report["configurations"] if c["name"] == "deterministic_only")
    assert deterministic["classes"]["conflict_version"]["delivered"] == 3
    # With no checker, D-20 still withholds them (production delivers nothing).
    production = next(c for c in report["configurations"] if c["name"] == "production")
    assert production["classes"]["conflict_version"]["delivered"] == 0 and production["finals"]["deliver"] == 0


def test_lqs_paths_are_refused(tmp_path):
    lqs = REPO_ROOT / "lqs" / "items.json"
    with pytest.raises(SystemExit, match="lqs"):
        RUNNER.load_fixtures(lqs)
    with pytest.raises(SystemExit, match="lqs"):
        RUNNER.main(["--check", str(lqs)])


def test_no_fixture_string_holds_a_corpus_sentence():
    words = re.compile(r"[a-z0-9]+")
    shingles = set()
    # The source documents (the authored curriculum's learner questions are the project's own fixture queries).
    for record in get_course_store().span_registry.records:
        if record.item_kind != "document":
            continue
        tokens = words.findall(record.text.lower())
        shingles.update(" ".join(tokens[index:index + 12]) for index in range(max(0, len(tokens) - 11)))
    strings = []

    def walk(value):
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(json.loads(FIXTURES.read_text(encoding="utf-8")))
    hits = []
    for text in strings:
        tokens = words.findall(text.lower())
        hits.extend(text for index in range(max(0, len(tokens) - 11)) if " ".join(tokens[index:index + 12]) in shingles)
    assert hits == []


def test_every_class_has_its_minimum_cases_and_every_case_is_public_corpus_only():
    payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    counts = {name: sum(1 for case in payload["cases"] if case["class"] == name) for name in RUNNER.CLASSES}
    assert all(counts[name] >= minimum for name, minimum in RUNNER.MIN_CASES.items()) and sum(counts.values()) == 66
    assert payload["public_corpus_only"] is True and len({case["id"] for case in payload["cases"]}) == len(payload["cases"])
    package = get_config_package(Settings())
    from app.services.v1_checks.package_check import fixture_set_sha256

    assert (package.v1.fixtures_set_sha256, package.v1.fixtures_cases) == (fixture_set_sha256(payload["cases"]), len(payload["cases"]))


def test_check_exits_1_on_a_record_that_differs_from_a_fresh_run_and_ignores_latency(tmp_path, capsys, monkeypatch):
    committed = json.loads((REPO_ROOT / "docs" / "evaluation" / "phase4" / "v1_fixture_report_v1.json").read_text(encoding="utf-8"))
    # Inside a test process the imported-module map also holds what other tests imported; the record's own map is
    # checked against the checkout by test_ac_4_2_the_committed_fixture_report_matches_a_fresh_run_and_its_hashes_match_the_package.
    assert RUNNER.input_problems(committed["inputs"]) == []
    monkeypatch.setattr(RUNNER, "run_inputs", lambda: committed["inputs"])
    drifted = json.loads(json.dumps(committed))
    drifted["configurations"][0]["classes"]["stripped_negation"]["caught"] = 4
    path = tmp_path / "drifted.json"
    path.write_text(json.dumps(drifted), encoding="utf-8")
    assert RUNNER.main(["--check", str(path)]) == RUNNER.EXIT_DRIFT
    assert "configurations" in capsys.readouterr().err
    slower = json.loads(json.dumps(committed))
    slower["latency"]["p95_ms"] = 123.0
    for configuration in slower["configurations"]:
        configuration["latency"]["p95_ms"] = 99.0
    path.write_text(json.dumps(slower), encoding="utf-8")
    assert RUNNER.main(["--check", str(path)]) == 0

