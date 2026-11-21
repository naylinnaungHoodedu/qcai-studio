"""V1.8, the misconception library (Phase 4 spec 4.9, conflict 12; Q-14 unavailable, A-18; DI-53)."""

from __future__ import annotations

import copy
import json

import pytest

from app.core.config import Settings
from app.core.config_package import DEFAULT_PACKAGE_PATH, ConfigPackageError, get_config_package, misconception_library_sha256, parse_config_package
from app.services.v1_checks.v1_8_misconceptions import check_v1_8, load_library
from v1_fakes import MULTI_CLAIM, AlwaysSupportedChecker, dev_pipeline, fixture_library, run

PACKAGE = get_config_package(Settings())
RAW = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))


def test_library_v0_ships_empty_and_hashed():
    library = load_library(PACKAGE)
    assert (library.version, library.entries) == ("v0", ())
    assert library.sha256 == misconception_library_sha256(RAW["v1"]["v1_8"]["library"])
    assert PACKAGE.owner_decisions["Q-14"]["state"] == "unavailable"


def test_an_entry_matches_a_claim_holding_all_its_terms():
    locked = run(dev_pipeline(), MULTI_CLAIM).locked
    words = sorted({word.lower().strip(".,;:") for word in locked.claims[0].text.split() if len(word) > 5})[:2]
    library = fixture_library([("MC-1", words), ("MC-2", ["zzzz-absent", "yyyy-absent"])])
    results = check_v1_8(locked, library, attempt=1)
    assert results[0].reason_code == "misconception_match" and results[0].outcome == "flag"
    assert all(result.claim_id for result in results) and {result.check_id for result in results} == {"V1.8"}
    assert check_v1_8(locked, load_library(PACKAGE), attempt=1) == tuple(
        result.model_copy(update={"reason_code": "no_match", "outcome": "pass"}) for result in check_v1_8(locked, load_library(PACKAGE), attempt=1))


def test_a_match_withholds_the_claim_and_queues_v3():
    locked = run(dev_pipeline(), MULTI_CLAIM).locked
    words = sorted({word.lower().strip(".,;:") for word in locked.claims[0].text.split() if len(word) > 5})[:2]
    record = run(dev_pipeline(checker=AlwaysSupportedChecker(), misconceptions=fixture_library([("MC-1", words)])), MULTI_CLAIM).entry.verification
    verdict = next(v for v in record.verdicts if v.claim_id == locked.claims[0].claim_id)
    assert verdict.final == "withhold" and verdict.v3 is not None and "v1_8_misconception" in verdict.v3.reasons


@pytest.mark.parametrize(
    "edit",
    [
        lambda lib: lib.update(sha256="0" * 64),
        lambda lib: lib["entries"].append({"id": "MC-1", "terms": ["only-one"]}),
        lambda lib: lib["entries"].append({"id": "MC-1", "terms": ["b", "a"]}),
        lambda lib: lib["entries"].append({"id": "MC-1", "terms": ["A", "b"]}),
        lambda lib: lib.update(library="another-library"),
    ],
)
def test_a_malformed_or_rehashed_library_is_refused(edit):
    raw = copy.deepcopy(RAW)
    library = raw["v1"]["v1_8"]["library"]
    edit(library)
    if "sha256" in library and library["sha256"] != "0" * 64:
        library["sha256"] = misconception_library_sha256(library)
    raw["owner_decisions"]["Q-14"]["state"] = "available-for-this-test"
    with pytest.raises(ConfigPackageError):
        parse_config_package(raw, path=DEFAULT_PACKAGE_PATH, sha256="", hash_verified=False)


def test_entries_are_refused_while_q_14_is_unavailable():
    raw = copy.deepcopy(RAW)
    library = raw["v1"]["v1_8"]["library"]
    library["entries"] = [{"id": "MC-1", "terms": ["a", "b"]}]
    library["sha256"] = misconception_library_sha256(library)
    with pytest.raises(ConfigPackageError, match="Q-14"):
        parse_config_package(raw, path=DEFAULT_PACKAGE_PATH, sha256="", hash_verified=False)
    raw["owner_decisions"]["Q-14"]["state"] = "available-for-this-test"
    parsed = parse_config_package(raw, path=DEFAULT_PACKAGE_PATH, sha256="", hash_verified=False)
    assert [entry.entry_id for entry in parsed.v1.library_entries] == ["MC-1"]
