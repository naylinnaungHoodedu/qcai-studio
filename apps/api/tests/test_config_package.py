"""Configuration package (plan Phase 2 P; decision D9; Phase 2 spec 2.5, 4.2; Phase 3 P "schemas in configuration
package v2", Phase 3 spec section 5)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.config_package import (
    DEFAULT_PACKAGE_PATH,
    V1_PACKAGE_PATH,
    WIRED_GENERATORS,
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
    # Phase 3 P: the shipped package is v2 (2.0.0); the 1.0.0 assertions moved to test_v1_stays_readable_for_one_release.
    package = load_config_package(DEFAULT_PACKAGE_PATH, governed=True)
    assert package.hash_verified and package.is_default_path and package.package_version == "2.0.0"
    assert package.schema_version == 2 and package.tutor_pipeline is not None
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


# --- Package v2 (Phase 3) ---

V1_RAW = json.loads(V1_PACKAGE_PATH.read_text(encoding="utf-8"))
V1_BLOCKS = ("span_identity", "corpus_version", "gates", "retrieval", "semantic", "near_duplicate", "legacy_citations", "boundary")


def test_v1_stays_readable_for_one_release():
    package = load_config_package(V1_PACKAGE_PATH, governed=True)
    assert package.hash_verified and package.package_version == "1.0.0" and package.schema_version == 1
    assert package.sha256 == recorded_sha256(V1_PACKAGE_PATH) == canonical_sha256(V1_RAW)
    assert package.tutor_pipeline is None and package.flag_policy.phase4_exit_passed is False
    assert not package.is_default_path


def test_package_v2_keeps_every_phase_2_value_of_v1():
    v2 = load_config_package(DEFAULT_PACKAGE_PATH, governed=True)
    v1 = load_config_package(V1_PACKAGE_PATH, governed=True)
    for block in V1_BLOCKS:
        assert RAW[block] == V1_RAW[block], block
    lineage = dict(RAW["abstention"])
    assert lineage.pop("calibrated_with_package_version") == "1.0.0"
    assert lineage == V1_RAW["abstention"]
    for name, decision in V1_RAW["owner_decisions"].items():
        assert RAW["owner_decisions"][name] == decision, name
    # PLAN-12.8 (2026-11-19 hardening): the ledger retention period, an open decision (DI-45).
    assert set(RAW["owner_decisions"]) == set(V1_RAW["owner_decisions"]) | {"D-19", "D-12", "PLAN-12.8"}
    # The index and corpus versions do not move with the package version.
    assert v2.retrieval_sha256 == v1.retrieval_sha256
    assert RAW["supersedes"] == {"package_version": "1.0.0", "sha256": v1.sha256, "readable_until": RAW["supersedes"]["readable_until"]}
    assert v2.owner_decisions["D-12"]["state"] == "open" and v2.owner_decisions["D-19"]["ratified"] is False
    assert v2.flag_policy.phase4_exit_passed is False and v2.tutor_pipeline.max_regenerations == 2
    assert set(v2.tutor_pipeline.generators_allowed) == WIRED_GENERATORS == {"extractive-d19-v1"}


def _schema_path_edit(value: str):
    def edit(payload):
        payload["tutor_pipeline"]["schemas"]["ClaimPlan"]["path"] = value

    return edit


@pytest.mark.parametrize(
    "edit",
    [
        lambda p: p["tutor_pipeline"]["pedagogical"].update(max_regenerations=3),
        lambda p: p["tutor_pipeline"]["pedagogical"].update(default_plan="lecture"),
        lambda p: p["tutor_pipeline"]["pedagogical"].update(presentation_plans=["concise", "stepwise"]),
        lambda p: p["tutor_pipeline"]["evidential"].update(generators_allowed=["extractive-d19-v1", "gateway-v1"]),
        lambda p: p["tutor_pipeline"]["evidential"].update(generator_default="gateway-v1"),
        _schema_path_edit("/etc/claim-plan.json"),
        _schema_path_edit("schemas/../../claim-plan.json"),
        _schema_path_edit("C:/claim-plan.json"),
        lambda p: p["tutor_pipeline"]["schemas"].pop("LedgerEntry"),
        lambda p: p["tutor_pipeline"]["schemas"]["ClaimPlan"].update(sha256="not-a-hash"),
        lambda p: p["tutor_pipeline"]["resolver"].update(prompt_hash="0" * 63),
        lambda p: p["flag_policy"].update(phase4_exit_passed=True),
        lambda p: p["flag_policy"].update(phase4_exit_passed="yes"),
        lambda p: p["tutor_pipeline"]["retrieval"].update(mode="hybrid"),
        lambda p: p["tutor_pipeline"]["retrieval"].update(request_fields=["text", "lesson_slug", "corpus_version", "page_path"]),
        lambda p: p["tutor_pipeline"]["retrieval"].update(top_k=13),
        lambda p: p["tutor_pipeline"]["stop"].update(phase2_bound_claim_ratio=0),
        lambda p: p["tutor_pipeline"]["stop"].update(phase2_bound_claim_ratio=1.5),
        lambda p: p["tutor_pipeline"]["evidential"].update(max_claims_per_span=4),
        lambda p: p["tutor_pipeline"].update(unused_provenance_fields=["v1_3_checker_model_id"]),
        lambda p: p["flag_policy"]["two_pass_tutor"].update(default_elsewhere="shadow"),
        lambda p: p.pop("supersedes"),
        lambda p: p["owner_decisions"].pop("D-12"),
        lambda p: p.update(schema_version=3),
    ],
)
def test_v2_structural_errors_always_stop_the_load(tmp_path, edit):
    payload = json.loads(json.dumps(RAW))
    edit(payload)
    path = _write(tmp_path, payload)
    for governed in (True, False):
        with pytest.raises(ConfigPackageError):
            load_config_package(path, governed=governed)


def test_d12_open_allows_only_the_extractive_generator(tmp_path):
    payload = json.loads(json.dumps(RAW))
    payload["tutor_pipeline"]["evidential"]["generators_allowed"] = ["extractive-d19-v1", "extractive-d19-v1"]
    with pytest.raises(ConfigPackageError, match="D-12"):
        load_config_package(_write(tmp_path, payload), governed=False)


def test_on_is_refused_unless_phase4_exit_passed(tmp_path):
    with pytest.raises(ValueError, match="phase4_exit_passed"):
        Settings(two_pass_tutor="on")
    with pytest.raises(ValueError, match="phase4_exit_passed"):
        Settings(environment="production", two_pass_tutor="on")
    payload = json.loads(json.dumps(RAW))
    payload["flag_policy"].update(phase4_exit_passed=True, phase4_exit_evidence="test-only")
    path = _write(tmp_path, payload)
    import shutil

    shutil.copytree(DEFAULT_PACKAGE_PATH.parent / "schemas", tmp_path / "schemas")
    assert Settings(two_pass_tutor="on", config_package_path=str(path)).two_pass_tutor == "on"  # development, a test package
    with pytest.raises(ValueError, match="shipped, hash-verified"):
        Settings(environment="production", two_pass_tutor="on", config_package_path=str(path))
