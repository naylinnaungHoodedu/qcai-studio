"""V1.8, the misconception library (Phase 4 spec 4.9, conflict 12; Q-14 unavailable, A-18; DI-53)."""

from __future__ import annotations

import copy
import json

import pytest

from app.core.config import Settings
from app.core.config_package import (DEFAULT_PACKAGE_PATH, V5_PACKAGE_PATH, ConfigPackageError, get_config_package, load_config_package,
                                     misconception_library_sha256, parse_config_package)
from app.services.v1_checks.v1_8_misconceptions import check_v1_8, load_library
from v1_fakes import MULTI_CLAIM, AlwaysSupportedChecker, dev_pipeline, fixture_library, run

PACKAGE = get_config_package(Settings())
# The inline library v0 tests read package v5 (readable for one release, DI-112); package v6 pins the library v1 file
# (Phase 7 spec 3.5), whose rules test_ehmf_units.py and test_phase7_acceptance.py test.
RAW = json.loads(V5_PACKAGE_PATH.read_text(encoding="utf-8"))
V5 = load_config_package(V5_PACKAGE_PATH, governed=True)


def test_library_v0_ships_empty_and_hashed():
    library = load_library(V5)
    assert (library.version, library.entries) == ("v0", ())
    assert (load_library(PACKAGE).version, load_library(PACKAGE).entries) == ("v1", ())  # package v6: library v1, empty (DI-106)
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
        parse_config_package(raw, path=V5_PACKAGE_PATH, sha256="", hash_verified=False)


def test_v6_library_file_entries_are_refused_while_q_14_is_unavailable(tmp_path):
    # Package v6 pins the library v1 file (Phase 7 spec 3.5): a well-formed entry in that file is refused while Q-14 is
    # unavailable (A-18), and loads once Q-14 is not (the control).
    from ehmf_fakes import package_copy

    entry = {"id": "mc-synthetic-entry", "editor": "content_owner", "terms": ["alpha", "beta"],
             "paraphrase": "A synthetic paraphrase for this test.", "span_ids": ["span-" + "1" * 64], "edited": "2026-11-23"}

    def add_entry(library):
        library["entries"] = [entry]

    with pytest.raises(ConfigPackageError, match="Q-14"):
        load_config_package(package_copy(tmp_path / "a", library_edit=add_entry), governed=False)
    available = package_copy(tmp_path / "b", lambda raw: raw["owner_decisions"]["Q-14"].update(state="available-for-this-test"),
                             library_edit=add_entry)
    assert [item.entry_id for item in load_config_package(available, governed=False).v1.library_entries] == ["mc-synthetic-entry"]


def test_entries_are_refused_while_q_14_is_unavailable():
    raw = copy.deepcopy(RAW)
    library = raw["v1"]["v1_8"]["library"]
    library["entries"] = [{"id": "MC-1", "terms": ["a", "b"]}]
    library["sha256"] = misconception_library_sha256(library)
    with pytest.raises(ConfigPackageError, match="Q-14"):
        parse_config_package(raw, path=V5_PACKAGE_PATH, sha256="", hash_verified=False)
    raw["owner_decisions"]["Q-14"]["state"] = "available-for-this-test"
    parsed = parse_config_package(raw, path=V5_PACKAGE_PATH, sha256="", hash_verified=False)
    assert [entry.entry_id for entry in parsed.v1.library_entries] == ["MC-1"]
