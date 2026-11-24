"""Seeded-fault fixtures and the known-answer reference detector (spec 3.8, 4.5; plan Phase 10 D task 3; PD-66).

The fixture (`evaluation/fixtures/seeded_faults_v1.json`) is synthetic: invented sentences, no ULQS item and no licensed
or course text. It holds clean controls and insertions of each EHMF finding type. `reference_detect` applies the
`reference-detector-v1` rules, and `detection_report` compares any detector's output with each case's expected answer.
"""

from __future__ import annotations

from pathlib import Path
import json
import re
from typing import Any, Mapping

from .canonical import canonical_sha256
from .statistics import wilson_interval

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE = REPO_ROOT / "evaluation" / "fixtures" / "seeded_faults_v1.json"
FINDING_TYPES = ("A", "B1", "B2", "C", "D", "E")
DETECTOR = "reference-detector-v1"
PRESENTATION = "presentation"
WORD = re.compile(r"[a-z0-9]+")
NUMBER = re.compile(r"^[0-9]+$")
NEGATIONS = frozenset({"no", "not", "never", "none", "nothing", "nor", "cannot", "without", "neither"})
STOPWORDS = frozenset({"about", "above", "after", "again", "also", "been", "before", "below", "being", "both", "could", "each",
                       "every", "from", "have", "into", "more", "most", "only", "other", "over", "same", "some", "such", "than",
                       "that", "their", "them", "then", "there", "these", "they", "this", "those", "through", "under", "very",
                       "were", "what", "when", "where", "which", "while", "with", "would", "your"})


def load_fixture(path: Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    fixture = json.loads(Path(path).read_text(encoding="utf-8"))
    if fixture.get("fixture") != "seeded-faults-v1" or fixture.get("synthetic") is not True:
        raise ValueError("not a synthetic seeded-faults-v1 fixture")
    if tuple(fixture.get("finding_types", ())) != FINDING_TYPES:
        raise ValueError("the fixture's finding types are not the EHMF vocabulary")
    return fixture


def fixture_sha256(fixture: Mapping[str, Any]) -> str:
    return canonical_sha256(fixture)


def _words(text: str) -> list[str]:
    return WORD.findall(text.casefold())


def _numbers(text: str) -> set[str]:
    return {word for word in _words(text) if NUMBER.match(word)}


def _negated(text: str) -> bool:
    return any(word in NEGATIONS for word in _words(text))


def _content(text: str) -> set[str]:
    return {word for word in _words(text) if len(word) > 3 and word not in STOPWORDS and not NUMBER.match(word)}


def _quantities(text: str) -> dict[str, str]:
    """Number -> the word after it ("40 metres" gives {"40": "metres"})."""
    words = _words(text)
    return {words[i]: words[i + 1] for i in range(len(words) - 1) if NUMBER.match(words[i])}


def _sentences(text: str) -> list[str]:
    return [part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part]


def reference_detect(case: Mapping[str, Any], *, spans: Mapping[str, str], misconceptions: list[Mapping[str, str]],
                     parameters: Mapping[str, Any]) -> dict[str, list[str]]:
    """{claim_id or "presentation": sorted finding types} for the findings this case raises (empty lists dropped)."""
    found: dict[str, list[str]] = {}
    known_misconceptions = {" ".join(_words(entry["statement"])) for entry in misconceptions}
    for claim in case.get("claims", []):
        types: set[str] = set()
        cited = list(claim.get("cited", []))
        missing = [pointer for pointer in cited if pointer not in spans]
        present = [spans[pointer] for pointer in cited if pointer in spans]
        text = claim["text"]
        if missing:
            types.add("B1")
        if present:
            numbers = set().union(*(_numbers(span) for span in present))
            if not _numbers(text) <= numbers or all(_negated(span) != _negated(text) for span in present):
                types.add("A")
            if not missing and not any(_content(text) & _content(span) for span in present):
                types.add("B2")
            if not case.get("disclosure", False) and len(present) > 1:
                by_noun: dict[str, set[str]] = {}
                for span in present:
                    for number, noun in _quantities(span).items():
                        by_noun.setdefault(noun, set()).add(number)
                if any(len(numbers_) > 1 for numbers_ in by_noun.values()):
                    types.add("D")
        if " ".join(_words(text)) in known_misconceptions:
            types.add("C")
        if types:
            found[claim["claim_id"]] = sorted(types, key=FINDING_TYPES.index)
    limit = int(parameters["max_sentence_words"])
    if any(len(_words(sentence)) > limit for sentence in _sentences(case.get("presentation", ""))):
        found[PRESENTATION] = ["E"]
    return found


def _types_of(detection: Mapping[str, list[str]]) -> set[str]:
    return {finding for types in detection.values() for finding in types}


def detection_report(fixture: Mapping[str, Any], detections: Mapping[str, Mapping[str, list[str]]]) -> dict[str, Any]:
    per_type: dict[str, dict[str, Any]] = {}
    clean = [case for case in fixture["cases"] if case.get("seeded_type") is None]
    false_alarms = sorted(case["case_id"] for case in clean if _types_of(detections.get(case["case_id"], {})))
    exact = []
    for case in fixture["cases"]:
        expected = {key: sorted(value, key=FINDING_TYPES.index) for key, value in case["expect"]["claims"].items()}
        if "E" in case["expect"]["types"]:
            expected[PRESENTATION] = ["E"]
        got = {key: list(value) for key, value in detections.get(case["case_id"], {}).items() if value}
        exact.append(got == expected)
    for finding in FINDING_TYPES:
        seeded = [case for case in fixture["cases"] if case.get("seeded_type") == finding]
        detected = [case for case in seeded if finding in _types_of(detections.get(case["case_id"], {}))]
        misattributed = [case["case_id"] for case in seeded if _types_of(detections.get(case["case_id"], {})) - set(case["expect"]["types"])]
        per_type[finding] = {"seeded": len(seeded), "detected": len(detected), "recall": wilson_interval(len(detected), len(seeded)),
                             "false_alarms_on_clean": len([case for case in false_alarms]), "misattributed": sorted(misattributed)}
    return {"report": "seeded-faults-report", "format_version": 1, "fixture": fixture["fixture"],
            "fixture_sha256": fixture_sha256(fixture), "detector": DETECTOR, "cases": len(fixture["cases"]),
            "clean_controls": len(clean), "false_alarm_cases": false_alarms, "per_type": per_type,
            "all_known_answers_met": all(exact) and not false_alarms}


def reference_report(fixture: Mapping[str, Any] | None = None) -> dict[str, Any]:
    fixture = fixture if fixture is not None else load_fixture()
    detections = {case["case_id"]: reference_detect(case, spans=fixture["spans"], misconceptions=fixture["misconceptions"],
                                                    parameters=fixture["parameters"]) for case in fixture["cases"]}
    return detection_report(fixture, detections)
