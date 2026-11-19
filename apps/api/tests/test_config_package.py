"""Configuration package v1 (plan Phase 2 P; decision D9; spec 2.5, 4.2)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.config_package import (
    DEFAULT_PACKAGE_PATH,
    ConfigPackageError,
    canonical_sha256,
    load_config_package,
    recorded_sha256,
)
from app.services.retrieval_p1 import QUERY_STOPWORDS, SCORE_FLOOR, SCORE_FLOOR_VERSION

REPO_ROOT = Path(__file__).resolve().parents[3]
RAW = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))


def _write(tmp_path: Path, payload: dict, *, sidecar: str | None = None) -> Path:
    path = tmp_path / "v1.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "v1.json.sha256").write_text((sidecar or canonical_sha256(payload)) + "\n", encoding="utf-8")
    return path


def test_the_shipped_package_validates_and_matches_its_hash():
    package = load_config_package(DEFAULT_PACKAGE_PATH, governed=True)
    assert package.hash_verified and package.is_default_path and package.package_version == "1.0.0"
    assert package.sha256 == recorded_sha256(DEFAULT_PACKAGE_PATH) == canonical_sha256(RAW)
    assert package.span_scheme == "span-v2" and package.abstention.provisional is True
    # The image copies apps/api/app, so the package ships inside it (the Dockerfile has no other path for it).
    assert DEFAULT_PACKAGE_PATH.is_relative_to(REPO_ROOT / "apps" / "api" / "app")


def test_a_hash_mismatch_stops_a_governed_load_and_warns_in_development(tmp_path, caplog):
    path = _write(tmp_path, RAW, sidecar="0" * 64)
    with pytest.raises(ConfigPackageError, match="does not match its recorded sha256"):
        load_config_package(path, governed=True)
    with caplog.at_level(logging.WARNING, logger="qcai.config_package"):
        assert load_config_package(path, governed=False).hash_verified is False
    assert any("hash does not match" in record.getMessage() for record in caplog.records)


def test_a_crlf_sidecar_reads_the_same_hash(tmp_path):
    path = tmp_path / "v1.json"
    path.write_text(json.dumps(RAW, indent=2).replace("\n", "\r\n"), encoding="utf-8")
    (tmp_path / "v1.json.sha256").write_bytes((canonical_sha256(RAW) + "\r\n").encode())
    assert load_config_package(path, governed=True).hash_verified


@pytest.mark.parametrize(
    "edit",
    [
        lambda p: p["retrieval"].update(k1=0),
        lambda p: p["retrieval"].update(b=1.5),
        lambda p: p["abstention"].update(floor=-1),
        lambda p: p["gates"]["p1-floor"].update(floor=5),
        lambda p: p["span_identity"].update(scheme="span-v3"),
        lambda p: p["retrieval"]["stopwords"]["words"].append("aaa"),
        lambda p: p["retrieval"]["tokenizer"].update(stemmer="s-stemmer"),
        lambda p: p["owner_decisions"]["Q-10"].update(unbound_items=[]),
        # D-30: a legacy threshold the migration would not apply is refused, never silently accepted.
        lambda p: p["legacy_citations"].update(max_unresolved_share_legacy=1.5),
        lambda p: p["legacy_citations"].update(max_unresolved_share_legacy="0.2"),
        lambda p: p["legacy_citations"].update(max_unresolved_share_legacy=True),
        lambda p: p["legacy_citations"].update(legacy_share_statistic="median"),
        lambda p: p["legacy_citations"].pop("legacy_share_statistic"),
    ],
)
def test_structural_errors_always_stop_the_load(tmp_path, edit):
    payload = json.loads(json.dumps(RAW))
    edit(payload)
    path = _write(tmp_path, payload)
    for governed in (True, False):
        with pytest.raises(ConfigPackageError):
            load_config_package(path, governed=governed)


def test_the_package_freezes_the_phase_1_floor_the_stopwords_and_the_library_pins():
    package = load_config_package(DEFAULT_PACKAGE_PATH, governed=True)
    assert (package.p1_floor["floor"], package.p1_floor["version"]) == (SCORE_FLOOR, SCORE_FLOOR_VERSION)
    assert QUERY_STOPWORDS <= package.retrieval.stopwords
    requirements = (REPO_ROOT / "apps" / "api" / "requirements.txt").read_text(encoding="utf-8")
    assert f"langchain-text-splitters=={package.splitter['version']}" in requirements
    assert f"python-docx=={package.parser['version']}" in requirements
    q10 = package.owner_decisions["Q-10"]
    assert q10["state"] == "unresolved" and package.q10_unbound_filenames == {"Quantum Computing and Artificial Intelligence 2026.mp4"}
    assert package.owner_decisions["D-17"]["option"] == "a" and package.owner_decisions["D-17"]["ratified"] is False
    assert package.legacy_citations["max_unresolved_share_native"] == 0.0


def test_a_relative_package_path_resolves_against_the_working_directory(tmp_path, monkeypatch):
    from app.core.config_package import resolve_package_path

    monkeypatch.chdir(tmp_path)
    assert resolve_package_path(Settings(config_package_path="pkg/v1.json")) == (tmp_path / "pkg" / "v1.json").resolve()
    assert resolve_package_path(Settings()) == DEFAULT_PACKAGE_PATH


def test_a_numeric_d30_legacy_threshold_loads_and_is_what_the_migration_reads(tmp_path):
    payload = json.loads(json.dumps(RAW))
    assert payload["legacy_citations"]["max_unresolved_share_legacy"] is None  # D-30 open
    assert payload["legacy_citations"]["legacy_share_statistic"] == "point"
    payload["legacy_citations"]["max_unresolved_share_legacy"] = 0.2
    package = load_config_package(_write(tmp_path, payload), governed=True)
    assert package.legacy_citations["max_unresolved_share_legacy"] == 0.2
