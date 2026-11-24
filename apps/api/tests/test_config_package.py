"""Configuration package (plan Phase 2 P; decision D9; Phase 2 spec 2.5, 4.2; Phase 3 P "schemas in configuration
package v2", Phase 3 spec section 5; Phase 4 P "fixture hashes in configuration package v3", Phase 4 spec section 5;
Phase 5 spec section 5 (package v4); Phase 6 spec section 5 (package v5, the shipped package))."""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path, PurePosixPath
import sys
import types

import pytest

from app.core.config import Settings
from app.core.config_package import (
    DEFAULT_PACKAGE_PATH,
    EHMF_SCHEMA_VERSION,
    LATEST_SCHEMA_VERSION,
    RANKING_SCHEMA_VERSION,
    V1_PACKAGE_PATH,
    V2_PACKAGE_PATH,
    V3_PACKAGE_PATH,
    V4_PACKAGE_PATH,
    V5_PACKAGE_PATH,
    V6_PACKAGE_PATH,
    WIRED_GENERATORS,
    ConfigPackageError,
    canonical_sha256,
    load_config_package,
    recorded_sha256,
)
from app.services.retrieval_p1 import QUERY_STOPWORDS, SCORE_FLOOR, SCORE_FLOOR_VERSION

REPO_ROOT = Path(__file__).resolve().parents[3]
API_APP = REPO_ROOT / "apps" / "api" / "app"
# apps/api/Dockerfile: WORKDIR /app and COPY apps/api/app ./app, so the image holds each module under /app/app.
IMAGE_APP = PurePosixPath("/app/app")
RAW = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
V2_RAW = json.loads(V2_PACKAGE_PATH.read_text(encoding="utf-8"))
V3_RAW = json.loads(V3_PACKAGE_PATH.read_text(encoding="utf-8"))
V4_RAW = json.loads(V4_PACKAGE_PATH.read_text(encoding="utf-8"))
# Package v5 (Phase 6), readable for one release after Phase 7 (DI-112): the v5 tests below read it explicitly.
V5_RAW = json.loads(V5_PACKAGE_PATH.read_text(encoding="utf-8"))
# Package v6 (Phase 7), readable for one release after Phase 9 (DI-126): the v6 tests below read it explicitly.
V6_RAW = json.loads(V6_PACKAGE_PATH.read_text(encoding="utf-8"))


def _write(tmp_path: Path, payload: dict, *, sidecar: str | None = None) -> Path:
    path = tmp_path / "v1.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "v1.json.sha256").write_text((sidecar or canonical_sha256(payload)) + "\n", encoding="utf-8")
    return path


def test_the_shipped_package_validates_and_matches_its_hash():
    # Phase 9: the shipped package is the first with a ranking block (v7, 7.0.0: schema and major RANKING_SCHEMA_VERSION, the
    # loader's latest schema, read from the loader so a renumbering edits one constant, E16); the 6.0.0 assertions are
    # test_v6_stays_readable_for_one_release's (v6 read explicitly); the 5.0.0 assertions are
    # test_v5_keeps_every_v4_value_but_the_listed_changes's (v5 read explicitly); the 4.0.0, 3.0.0, 2.0.0 and 1.0.0 assertions are
    # test_v4_stays_readable_for_one_release's, test_v3_stays_readable_for_one_release's,
    # test_v2_stays_readable_for_one_release's and test_v1_stays_readable_for_one_release's.
    package = load_config_package(DEFAULT_PACKAGE_PATH, governed=True)
    assert package.hash_verified and package.is_default_path and package.package_version == f"{RANKING_SCHEMA_VERSION}.0.0"
    assert package.schema_version == RANKING_SCHEMA_VERSION == LATEST_SCHEMA_VERSION and package.tutor_pipeline is not None and package.v1 is not None
    assert package.gateway is not None and package.v2 is not None and package.tools is not None and package.v3 is not None
    assert package.ehmf is not None and package.ranking is not None and RAW["supersedes"]["sha256"] == canonical_sha256(V6_RAW)
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
    # Package v2 itself (the default is v3 since Phase 4; v3's own lineage test is test_v3_keeps_every_v2_value_but_the_listed_changes).
    v2 = load_config_package(V2_PACKAGE_PATH, governed=True)
    v1 = load_config_package(V1_PACKAGE_PATH, governed=True)
    for block in V1_BLOCKS:
        assert V2_RAW[block] == V1_RAW[block], block
    lineage = dict(V2_RAW["abstention"])
    assert lineage.pop("calibrated_with_package_version") == "1.0.0"
    assert lineage == V1_RAW["abstention"]
    for name, decision in V1_RAW["owner_decisions"].items():
        assert V2_RAW["owner_decisions"][name] == decision, name
    # PLAN-12.8 (2026-11-19 hardening): the ledger retention period, an open decision (DI-45). PLAN-3.3 (review
    # round 3): the reading of task 3.3 "atomic claims" under D-19, unratified (DI-47).
    assert set(V2_RAW["owner_decisions"]) == set(V1_RAW["owner_decisions"]) | {"D-19", "D-12", "PLAN-12.8", "PLAN-3.3"}
    # The index and corpus versions do not move with the package version.
    assert v2.retrieval_sha256 == v1.retrieval_sha256
    assert V2_RAW["supersedes"] == {"package_version": "1.0.0", "sha256": v1.sha256, "readable_until": V2_RAW["supersedes"]["readable_until"]}
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
        # v2 claiming schema 3 (no v1 block), and v3 claiming an unknown schema 4.
        lambda p: p.update(schema_version=p["schema_version"] + 1),
    ],
)
@pytest.mark.parametrize("package", ["v2", "v3"])
def test_v2_structural_errors_always_stop_the_load(tmp_path, edit, package):
    # The Phase 3 refusals, on package v2 itself (it stays readable for one release, DI-63) and on the shipped package
    # v3, so a schema-3 branch of the loader cannot stop refusing one of them unnoticed.
    payload = json.loads(json.dumps(V2_RAW if package == "v2" else RAW))
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


# --- Package v3 (Phase 4) ---

V3_CHANGED_TUTOR_KEYS = {"schemas", "ledger", "unused_provenance_fields"}


def test_v2_stays_readable_for_one_release():
    from app.services.tutor_pipeline.package_check import check_tutor_pipeline_package

    package = load_config_package(V2_PACKAGE_PATH, governed=True)
    assert package.hash_verified and package.package_version == "2.0.0" and package.schema_version == 2 and package.v1 is None
    assert package.sha256 == recorded_sha256(V2_PACKAGE_PATH) == canonical_sha256(V2_RAW) == V3_RAW["supersedes"]["sha256"]
    assert not package.is_default_path
    assert check_tutor_pipeline_package(package, structural=True) == []


def test_v3_keeps_every_v2_value_but_the_listed_changes():
    for key in V2_RAW:
        if key in {"package_version", "schema_version", "phase", "created", "supersedes", "tutor_pipeline", "flag_policy", "owner_decisions",
                   "abstention"}:
            continue
        assert V3_RAW[key] == V2_RAW[key], key
    assert (V3_RAW["package_version"], V3_RAW["schema_version"], V3_RAW["phase"]) == ("3.0.0", 3, "4")
    assert V3_RAW["supersedes"] == {"package_version": "2.0.0", "sha256": canonical_sha256(V2_RAW), "readable_until": "the release after the Phase 4 merge"}
    assert V3_RAW["abstention"]["calibrated_with_package_version"] == "1.0.0"
    # The abstention values stay provisional past Phase 4: until Q-22 sets them (DI-52), not "Phase 4" as v2 says.
    abstention = dict(V3_RAW["abstention"])
    assert (abstention.pop("provisional_until"), V2_RAW["abstention"]["provisional_until"]) == ("Q-22 (DI-52)", "Phase 4")
    assert abstention == {key: value for key, value in V2_RAW["abstention"].items() if key != "provisional_until"}
    assert abstention["provisional"] is True
    for key, value in V2_RAW["tutor_pipeline"].items():
        if key not in V3_CHANGED_TUTOR_KEYS:
            assert V3_RAW["tutor_pipeline"][key] == value, key
    assert {name: pin for name, pin in V3_RAW["tutor_pipeline"]["schemas"].items() if name != "LedgerEntryV2"} == V2_RAW["tutor_pipeline"]["schemas"]
    assert V3_RAW["tutor_pipeline"]["schemas"]["LedgerEntryV2"]["path"] == "schemas/ledger-entry.v2.schema.json"
    ledger = dict(V3_RAW["tutor_pipeline"]["ledger"])
    assert (ledger.pop("entry_schema"), ledger.pop("legacy_entry_schema"), ledger.pop("entry_schemas")) == (
        "ledger-entry-v2", "ledger-entry-v1", ["ledger-entry-v1", "ledger-entry-v2"])
    assert ledger == {key: value for key, value in V2_RAW["tutor_pipeline"]["ledger"].items() if key != "entry_schema"}
    assert V3_RAW["tutor_pipeline"]["unused_provenance_fields"] == ["panel_weights_version", "routing_table_version", "tool_contract_version"]
    policy = dict(V3_RAW["flag_policy"])
    assert policy.pop("v1_pipeline") == {"values": ["off", "shadow", "enforce"], "default_development": "enforce", "default_elsewhere": "shadow",
                                         "enforce_requires": "phase4_exit_passed", "off_outside_development": "refused",
                                         "authority": "plan Phase 4 G; 13.6; PD-19"}
    # The block-level authority names both provisional defaults the block holds: PD-10 (two_pass_tutor, ratified under
    # DI-37) and PD-19 (v1_pipeline, ratified under DI-55); every other v2 value is unchanged.
    authority = policy.pop("authority")
    assert all(name in authority for name in ("PD-10", "DI-37", "PD-19", "DI-55")) and "v1_pipeline" in authority
    assert policy == {key: value for key, value in V2_RAW["flag_policy"].items() if key != "authority"}
    assert policy["phase4_exit_passed"] is False and policy["phase4_exit_evidence"] is None
    assert set(V3_RAW["owner_decisions"]) == set(V2_RAW["owner_decisions"]) | {"D-20", "D-21", "Q-22", "Q-14", "D-06"}
    # Q-22 names every value PD-15, PD-16 and PD-18 apply as operator policy: V1.7's alignment rule, and the V1.5 floor
    # and margin (abstention, provisional until Q-22), included.
    assert V3_RAW["owner_decisions"]["Q-22"]["provisional_values"] == ["v1.v1_5.x4_margin", "abstention", "v1.v1_3.support_threshold",
                                                                     "v1.v1_7", "v1.v1_9.readability", "v1.stop"]
    for name, decision in V2_RAW["owner_decisions"].items():
        if name == "PLAN-11.3":
            continue
        assert V3_RAW["owner_decisions"][name] == decision, name
    # PLAN-11.3's runner-up deviation names the item that carries it now (DI-67); nothing else of it changed.
    plan_11_3, v2_plan_11_3 = json.loads(json.dumps(V3_RAW["owner_decisions"]["PLAN-11.3"])), V2_RAW["owner_decisions"]["PLAN-11.3"]
    runner_up = plan_11_3["deviations"][1]
    assert runner_up.pop("applied").endswith("no runner-up test (Phase 2 spec conflict 4; DI-28, carried as DI-67)")
    assert v2_plan_11_3["deviations"][1]["applied"].endswith("no runner-up test (spec conflict 4; Phase 4, DI-28)")
    assert runner_up == {key: value for key, value in v2_plan_11_3["deviations"][1].items() if key != "applied"}
    plan_11_3["deviations"][1] = v2_plan_11_3["deviations"][1]
    assert plan_11_3 == v2_plan_11_3
    # Every prompt hash is v2's, and the eight v1 schema files are unchanged.
    for block in ("resolver", "evidential", "pedagogical"):
        assert V3_RAW["tutor_pipeline"][block]["prompt_hash"] == V2_RAW["tutor_pipeline"][block]["prompt_hash"]
    package = load_config_package(DEFAULT_PACKAGE_PATH, governed=True)
    assert package.retrieval_sha256 == load_config_package(V2_PACKAGE_PATH, governed=True).retrieval_sha256
    v1 = package.v1
    assert v1.checker_hosting == v1.checker_model_id == "none" and v1.library_entries == () and v1.d20_rule == "withhold-all-flagged-v1"
    assert dict(v1.answer_rate_floor) == {"bm25f-v1": (166, 174), "p1-floor": (146, 174)} and v1.p95_budget_ms == 250
    assert all(V3_RAW["v1"][block]["provisional"] is True
               for block in ("lexicon", "v1_3", "v1_5", "v1_6", "v1_7", "v1_9", "quiz_feedback", "d20_interim", "stop"))
    # PD-21 lives in the package, provisional, and names the rule the quiz route implements.
    assert {key: value for key, value in V3_RAW["v1"]["quiz_feedback"].items() if key != "authority"} == {
        "provisional": True, "rule": "keys-after-saved-attempt-answered-only-v1", "public_payloads": "no_keys",
        "feedback": "answered_questions_after_a_saved_attempt"}
    assert "PD-21" in V3_RAW["v1"]["quiz_feedback"]["authority"] and v1.quiz_feedback_rule == "keys-after-saved-attempt-answered-only-v1"


@pytest.mark.parametrize(
    "edit",
    [
        lambda p: p["v1"].update(provisional=False),
        lambda p: p["v1"]["v1_3"].update(provisional=False),
        lambda p: p["v1"]["stop"].pop("provisional"),
        lambda p: p["v1"]["ehmf"].update({"V1.3": ["A"]}),
        lambda p: p["v1"]["regeneration"].update(max_generation_regenerations=3),
        lambda p: p["v1"]["regeneration"].update(max_render_regenerations=-1),
        lambda p: p["v1"]["lexicon"].update(negation_cues=[]),
        lambda p: p["v1"]["lexicon"].update(units=["s", "ms"]),
        lambda p: p["v1"]["lexicon"].update(number_words=["Two", "one"]),
        lambda p: p["v1"]["v1_3"].update(hosting="local-nli"),
        lambda p: p["v1"]["v1_3"].update(support_threshold=1.5),
        lambda p: p["v1"]["v1_3"].update(timeout_ms=5),
        lambda p: p["v1"]["v1_3"].update(timeout_ms=5000),
        lambda p: p["v1"]["v1_3"].update(unavailable="deliver"),
        lambda p: p["v1"]["v1_5"]["x4_margin"].update({"bm25f-v1": -1.0}),
        lambda p: p["v1"]["v1_5"]["x4_margin"].update({"p1-floor": "0.5"}),
        lambda p: p["v1"]["v1_5"]["x4_margin"].pop("p1-floor"),
        lambda p: p["owner_decisions"]["Q-22"]["provisional_values"].remove("abstention"),
        lambda p: p["owner_decisions"]["Q-22"]["provisional_values"].append("v1.v1_5.no_such_value"),
        lambda p: p["owner_decisions"]["Q-22"].update(provisional_values=[]),
        lambda p: p["v1"]["v1_9"].update(provisional_until="Q-22 (DI-52)"),
        lambda p: p["flag_policy"].update(authority="PD-10: the Phase 3 switches outside development (DI-37)"),
        lambda p: p["v1"]["v1_6"].update(assessment_threshold=0),
        lambda p: p["v1"]["v1_6"].update(short_key_min_tokens=0),
        lambda p: p["v1"]["v1_6"].update(socratic_plan="lecture"),
        lambda p: p["v1"]["v1_6"].update(scope="own_lesson"),
        lambda p: p["v1"]["v1_7"].update(alignment_threshold=1.5),
        lambda p: p["v1"]["v1_7"].update(min_alignment_terms=0),
        lambda p: p["v1"]["v1_7"].update(on_conflict="ignore"),
        lambda p: p["v1"]["v1_7"]["version_families"].append({"family": "one", "item_ids": ["a", "a"]}),
        lambda p: p["v1"]["v1_7"]["version_families"].append({"family": "dup", "item_ids": ["quantum-computing-and-artificial-intelligence-2025", "x"]}),
        lambda p: p["v1"]["v1_7"].update(version_families=[{"family": f"f{i}", "item_ids": [f"a{i}", f"b{i}"]} for i in range(21)]),
        lambda p: p["v1"]["v1_8"]["library"].update(sha256="0" * 64),
        lambda p: p["v1"]["v1_8"].update(on_match="hard_fail"),
        lambda p: p["v1"]["v1_9"]["readability"].update(min_grade=70.0),
        lambda p: p["v1"]["v1_9"]["readability"].update(max_grade=500.0),
        lambda p: p["v1"]["stop"]["answer_rate_floor"]["bm25f-v1"].update(answered=175),
        lambda p: p["v1"]["stop"]["answer_rate_floor"]["p1-floor"].update(answered=0.84),
        lambda p: p["v1"]["stop"]["composition"].update(rule="anything"),
        lambda p: p["v1"]["stop"].update(v1_p95_latency_ms=0),
        lambda p: p["v1"]["stop"].update(v1_p95_latency_ms=10**6),
        lambda p: p["v1"]["fixtures"].update(path="../outside.json"),
        lambda p: p["v1"]["fixtures"].update(path="/etc/fixtures.json"),
        lambda p: p["v1"].update(rules_hash="not-a-hash"),
        lambda p: p["owner_decisions"].pop("D-20"),
        lambda p: p["owner_decisions"]["D-21"].update(state="open") or p["v1"]["v1_3"].update(checker_model_id="model-x"),
        lambda p: p["v1"]["d20_interim"].update(rule="deliver-flagged"),
        lambda p: p["flag_policy"]["v1_pipeline"].update(default_elsewhere="enforce"),
        lambda p: p["flag_policy"]["v1_pipeline"].update(default_development="shadow"),
        lambda p: p["flag_policy"]["v1_pipeline"].update(off_outside_development="allowed"),
        lambda p: p["flag_policy"]["v1_pipeline"].update(values=["off", "shadow"]),
        lambda p: p["tutor_pipeline"]["schemas"].pop("LedgerEntryV2"),
        lambda p: p["tutor_pipeline"]["ledger"].update(entry_schemas=["ledger-entry-v1"]),
        lambda p: p["tutor_pipeline"]["ledger"].update(legacy_entry_schema="ledger-entry-v2"),
        lambda p: p["tutor_pipeline"].update(unused_provenance_fields=["v1_3_checker_model_id"]),
        lambda p: p.pop("v1"),
        lambda p: p["v1"]["quiz_feedback"].update(provisional=False),
        lambda p: p["v1"]["quiz_feedback"].update(rule="keys-in-public-payloads-v0"),
        lambda p: p["v1"]["quiz_feedback"].update(public_payloads="keys"),
        lambda p: p["v1"]["quiz_feedback"].update(feedback="every_question_after_a_saved_attempt"),
        lambda p: p["v1"].pop("quiz_feedback"),
    ],
)
def test_v3_structural_errors_always_stop_the_load(tmp_path, edit):
    # Each refusal holds for v3.json, still readable, for v4.json and for the shipped v5, which keep every v3 block (Phase 5
    # spec 13.3; Phase 6 spec 13.3).
    for base in (V3_RAW, V4_RAW, RAW):
        payload = json.loads(json.dumps(base))
        edit(payload)
        path = _write(tmp_path, payload)
        for governed in (True, False):
            with pytest.raises(ConfigPackageError):
                load_config_package(path, governed=governed)


def test_package_check_v1_problems(tmp_path):
    import dataclasses

    from app.services.v1_checks.package_check import check_v1_package

    package = load_config_package(DEFAULT_PACKAGE_PATH, governed=True)
    assert check_v1_package(package, structural=True) == []
    wrong_hash = dataclasses.replace(package, v1=dataclasses.replace(package.v1, rules_hash="0" * 64))
    assert any("rules_hash" in problem for problem in check_v1_package(wrong_hash, structural=False))
    wrong_rule = dataclasses.replace(package, v1=dataclasses.replace(package.v1, rule_ids={**package.v1.rule_ids, "V1.4": "segment-exact-whitespace-v2"}))
    assert any("rule_ids" in problem for problem in check_v1_package(wrong_rule, structural=False))
    wrong_pin = dataclasses.replace(package, v1=dataclasses.replace(package.v1, fixtures_set_sha256="0" * 64, fixtures_cases=1))
    problems = check_v1_package(wrong_pin, structural=True)
    assert any("set_sha256" in problem for problem in problems) and any("cases" in problem for problem in problems)
    assert check_v1_package(wrong_pin, structural=False) == []  # start-up never reads docs/
    missing = dataclasses.replace(package, v1=dataclasses.replace(package.v1, fixtures_path="docs/evaluation/phase4/missing.json"))
    assert any("missing" in problem for problem in check_v1_package(missing, structural=True))
    assert check_v1_package(dataclasses.replace(package, v1=None), structural=False) == ["the configuration package has no v1 block"]
    other_quiz_rule = dataclasses.replace(package, v1=dataclasses.replace(package.v1, quiz_feedback_rule="keys-every-question-v2"))
    assert check_v1_package(other_quiz_rule, structural=False) == [
        "v1.quiz_feedback.rule differs from the quiz route's rule (quiz_keys.FEEDBACK_RULE, PD-21)"]


def _image_module(relative: str, name: str) -> types.ModuleType:
    """A module's committed source executed as the API image holds it (__file__ under /app/app), so a module-level
    computation that needs a repository checkout fails here as it fails at start-up in the image."""
    module = types.ModuleType(name)
    module.__file__ = str(IMAGE_APP / relative)
    exec(compile((API_APP / relative).read_text(encoding="utf-8"), module.__file__, "exec"), module.__dict__)
    return module


def test_the_v1_start_up_check_runs_from_the_image_layout(monkeypatch):
    # In the image the package check is /app/app/services/v1_checks/package_check.py: five parents and no checkout.
    # Start-up imports it (lifespan -> _initialize_database -> _check_tutor_pipeline_package -> _check_v1_package), so
    # it must import and check the shipped package there; only a structural check needs docs/, and it says so.
    from app import main as main_module
    from app.services import v1_checks

    image = _image_module("services/v1_checks/package_check.py", "app.services.v1_checks.package_check")
    monkeypatch.setitem(sys.modules, "app.services.v1_checks.package_check", image)
    monkeypatch.setattr(main_module, "settings", Settings(environment="production"))
    package = load_config_package(DEFAULT_PACKAGE_PATH, governed=True)
    main_module._check_v1_package(package)  # a governed build: any problem raises ConfigPackageError
    assert v1_checks.V1_UNAVAILABLE_REASON is None
    assert image.check_v1_package(package, structural=False) == []
    assert image.fixture_problems(package) == [f"v1 fixtures: {package.v1.fixtures_path} is missing or not JSON"]


def test_no_image_module_computes_a_parent_its_image_path_lacks_at_import():
    # Every module-level `.parents[N]` in apps/api/app has a constant N that exists at the module's image path: the
    # image imports these modules at start-up or in its jobs and holds no repository checkout above /app.
    checked = 0
    for path in sorted(API_APP.rglob("*.py")):
        relative = path.relative_to(API_APP).as_posix()
        depth = len((IMAGE_APP / relative).parents)
        for statement in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for node in ast.walk(statement):
                if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "parents":
                    index = node.slice
                    assert isinstance(index, ast.Constant) and isinstance(index.value, int), (relative, ast.unparse(node))
                    assert index.value < depth, (relative, ast.unparse(node), f"the image path has {depth} parents")
                    checked += 1
    assert checked >= 3


# --- Package v4 (Phase 5) ---

V4_NEW_BLOCKS = {"gateway", "v2", "tools"}
V4_SCHEMAS = {"LedgerEntryV3": "schemas/ledger-entry.v3.schema.json", "V2VerdictRequest": "schemas/v2-verdict-request.v1.schema.json",
              "V2AlignmentRequest": "schemas/v2-alignment-request.v1.schema.json", "V2AdapterVerdict": "schemas/v2-adapter-verdict.v1.schema.json",
              "V2AlignmentVerdict": "schemas/v2-alignment-verdict.v1.schema.json"}


def test_v3_stays_readable_for_one_release():
    from app.services.tutor_pipeline.package_check import check_tutor_pipeline_package
    from app.services.v1_checks.package_check import check_v1_package

    package = load_config_package(V3_PACKAGE_PATH, governed=True)
    assert package.hash_verified and package.package_version == "3.0.0" and package.schema_version == 3 and not package.is_default_path
    assert package.gateway is None and package.v2 is None and package.tools is None and package.flag_policy.phase5_exit_passed is False
    assert package.sha256 == recorded_sha256(V3_PACKAGE_PATH) == canonical_sha256(V3_RAW) == V4_RAW["supersedes"]["sha256"]
    assert check_tutor_pipeline_package(package, structural=True) == [] and check_v1_package(package, structural=True) == []


def test_v4_keeps_every_v3_value_but_the_listed_changes():
    # Package v4 (v4.json, readable for one release after the Phase 6 merge, DI-100) against v3.
    assert (V4_RAW["package_version"], V4_RAW["schema_version"], V4_RAW["phase"]) == ("4.0.0", 4, "5")
    assert V4_RAW["supersedes"] == {"package_version": "3.0.0", "sha256": canonical_sha256(V3_RAW), "readable_until": "the release after the Phase 5 merge"}
    assert set(V4_RAW) == set(V3_RAW) | V4_NEW_BLOCKS
    for key in V3_RAW:
        if key not in {"package_version", "schema_version", "phase", "created", "supersedes", "tutor_pipeline", "flag_policy", "owner_decisions"}:
            assert V4_RAW[key] == V3_RAW[key], key
    tutor, v3_tutor = V4_RAW["tutor_pipeline"], V3_RAW["tutor_pipeline"]
    for key, value in v3_tutor.items():
        if key not in {"schemas", "ledger", "unused_provenance_fields"}:
            assert tutor[key] == value, key
    assert {name: pin for name, pin in tutor["schemas"].items() if name not in V4_SCHEMAS} == v3_tutor["schemas"]
    assert {name: tutor["schemas"][name]["path"] for name in V4_SCHEMAS} == V4_SCHEMAS
    ledger = dict(tutor["ledger"])
    assert (ledger.pop("entry_schema"), ledger.pop("entry_schemas")) == ("ledger-entry-v3", ["ledger-entry-v1", "ledger-entry-v2", "ledger-entry-v3"])
    assert ledger == {key: value for key, value in v3_tutor["ledger"].items() if key not in {"entry_schema", "entry_schemas"}}
    assert tutor["unused_provenance_fields"] == []
    policy = dict(V4_RAW["flag_policy"])
    assert policy.pop("model_gateway")["default_elsewhere"] == "off" and policy.pop("phase5_exit_passed") is False
    assert policy.pop("phase5_exit_evidence") is None
    authority = policy.pop("authority")
    assert authority.startswith(V3_RAW["flag_policy"]["authority"]) and "PD-28" in authority and "DI-76" in authority
    assert policy == {key: value for key, value in V3_RAW["flag_policy"].items() if key != "authority"}
    decisions = V4_RAW["owner_decisions"]
    assert set(decisions) == set(V3_RAW["owner_decisions"]) | {"D-07", "Q-09", "D-23", "D-29", "D-25", "A-15", "Q-15"}
    for name, decision in V3_RAW["owner_decisions"].items():
        if name != "Q-22":
            assert decisions[name] == decision, name
    assert decisions["Q-22"]["provisional_values"] == [*V3_RAW["owner_decisions"]["Q-22"]["provisional_values"], "v2.voting"]
    assert decisions["Q-22"]["record"] == "PD-15, PD-16, PD-18, PD-25; DI-52"
    gateway = V4_RAW["gateway"]
    assert {name: len(members) for name, members in gateway["registries"].items()} == {"development": 4, "staging": 0, "production": 0, "default": 0}
    assert gateway["budgets"]["daily_units"] == {"development": 100000, "staging": 0, "production": 0, "default": 0} and gateway["terms"] is None
    assert V4_RAW["v2"]["degraded"]["pre_verified_source"] is None and V4_RAW["v2"]["correction"]["critical_registry"] == []
    assert V4_RAW["v2"]["voting"]["provisional_until"] == "Q-22 (DI-52)"


@pytest.mark.parametrize(
    "edit",
    [
        lambda p: p["v2"].update(provisional=False),
        lambda p: p["v2"]["panel"].update(max_members=4),
        lambda p: p["v2"].update(routing_table_version="degraded-matrix-v2"),
        lambda p: p["v2"]["voting"]["matrix"]["REDUCED-1"].update({"2": "1oo2"}),
        lambda p: p["v2"]["voting"]["matrix"]["FULL"].update({"1": "2oo3"}),
        lambda p: p["v2"]["voting"]["tier3_threshold"].update(numerator=4),
        lambda p: p["v2"]["voting"]["tier3_threshold"].update(numerator=0),
        lambda p: p["v2"]["tiers"].update(default=4),
        lambda p: p["v2"]["tiers"].update(assessment_context=2),
        lambda p: p["v2"]["correction"].update(max_cycles=3),
        lambda p: p["v2"]["correction"].update(critical_registry=["claim-x"]),
        lambda p: p["v2"]["generator_families"].pop("extractive-d19-v1"),
        lambda p: p["v2"]["generator_families"].update({"extractive-d19-v1": "fake-alpha"}),
        lambda p: p["v2"]["degraded"].update(pre_verified_source="module-store-v1"),
        lambda p: p["v2"]["degraded"]["banners"].pop("degraded-zero-v1"),
        lambda p: p["v2"]["degraded"]["banners"].update({"degraded-zero-v1": " "}),
        lambda p: p["owner_decisions"]["Q-22"]["provisional_values"].remove("v2.voting"),
        lambda p: p["tools"].update(version="mcp-tools-v2"),
        lambda p: p["tools"].update(servers=["corpus"]),
        lambda p: p["tools"].update(path="../tool-contracts.json"),
        lambda p: p["tools"].update(sha256="xyz"),
        lambda p: p["flag_policy"]["model_gateway"].update(default_elsewhere="shadow"),
        lambda p: p["flag_policy"]["model_gateway"].update(default_development="on"),
        lambda p: p["flag_policy"]["model_gateway"].update(on_requires_v1="shadow"),
        lambda p: p["flag_policy"].update(phase5_exit_passed="no"),
        lambda p: p["flag_policy"].update(phase5_exit_passed=True),
        lambda p: p["flag_policy"].update(authority=V3_RAW["flag_policy"]["authority"]),
        lambda p: p["tutor_pipeline"]["schemas"].pop("LedgerEntryV3"),
        lambda p: p["tutor_pipeline"]["ledger"].update(entry_schemas=["ledger-entry-v1", "ledger-entry-v2"]),
        lambda p: p["tutor_pipeline"].update(unused_provenance_fields=["tool_contract_version"]),
        lambda p: p.update(schema_version=5),
        lambda p: p.pop("gateway"),
        lambda p: p["gateway"]["registries"]["development"][0].update(model_version="preview"),
        lambda p: p["owner_decisions"].pop("D-29"),
        # The tier-3 share is 2/3 while Q-22 is unresolved: the record rule re-tallies with it (PD-25).
        lambda p: p["v2"]["voting"]["tier3_threshold"].update(numerator=1, denominator=2),
        # Plan 5.8's correction rules are the code's (type E re-renders only).
        lambda p: p["v2"]["correction"].update(type_e="revise_or_reverify_unchanged"),
        lambda p: p["v2"]["correction"].update(other="re_render_only"),
        lambda p: p["v2"]["correction"].pop("exhausted"),
        # The tool names are provisional (A-18; PD-31).
        lambda p: p["tools"].update(provisional=False),
        # The pinning texts are the code's, and a glued alias is unpinned.
        lambda p: p["gateway"]["pinning"].update(refused_tokens="alias|latest"),
        lambda p: p["gateway"]["pinning"].pop("refused_within_token"),
        lambda p: p["gateway"]["pinning"].update(version_pattern="^.+$"),
        lambda p: p["gateway"]["registries"]["development"][0].update(model_id="fakealpha3preview"),
        lambda p: p["gateway"]["registries"]["development"][0].update(model_version="2026-02-30"),
        # Every provisional sub-block of v2 carries its own mark (PD-25, PD-29, PD-30).
        lambda p: p["v2"]["correction"].pop("provisional"),
        lambda p: p["v2"]["degraded"].update(provisional=False),
        lambda p: p["v2"]["alignment"].pop("provisional"),
        # The budget, the stop and the cache are shared by every instance, and only an operator clears a stop.
        lambda p: p["gateway"]["budgets"].update(scope="process"),
        lambda p: p["gateway"]["cache"].update(scope="process"),
        lambda p: p["gateway"]["stop"].update(scope="process"),
        lambda p: p["gateway"]["stop"].update(clear="restart"),
    ],
)
def test_v4_structural_errors_always_stop_the_load(tmp_path, edit):
    # Each refusal holds for v4.json, still readable (DI-100), for v5, which keeps every v4 block (Phase 6 spec 13.3;
    # read explicitly since Phase 7 ships v6), and for the shipped v6, which keeps them too (Phase 7 spec 5.2). On v5 the
    # schema_version=5 edit is no edit, so schema_version=6 stands for it there (a v6 package needs an ehmf block).
    _the_unedited_copies_load(tmp_path)
    for base in (V4_RAW, V5_RAW, RAW):
        payload = json.loads(json.dumps(base))
        edit(payload)
        if base is V5_RAW and payload.get("schema_version") == 5:
            payload["schema_version"] = EHMF_SCHEMA_VERSION
        path = _write(tmp_path, payload)
        for governed in (True, False):
            with pytest.raises(ConfigPackageError):
                load_config_package(path, governed=governed)


def test_v4_names_the_entry_schema_whose_provenance_fields_it_fills(tmp_path):
    # unused_provenance_fields describes the package's entry schema (ledger-entry-v3 in v4 and v5, ledger-entry-v4 in the
    # shipped v6), as in v1 to v3; a v2 record written under v4 with MODEL_GATEWAY off keeps the three Phase 5 fields null
    # (v5 read explicitly since Phase 7).
    payload = json.loads(json.dumps(RAW))
    payload["tutor_pipeline"]["unused_provenance_fields"] = ["tool_contract_version"]
    with pytest.raises(ConfigPackageError, match="its entry schema, ledger-entry-v4, fills every provenance field"):
        load_config_package(_write(tmp_path, payload), governed=True)
    for base in (V4_RAW, V5_RAW):
        payload = json.loads(json.dumps(base))
        payload["tutor_pipeline"]["unused_provenance_fields"] = ["tool_contract_version"]
        with pytest.raises(ConfigPackageError, match="its entry schema, ledger-entry-v3, fills every provenance field"):
            load_config_package(_write(tmp_path, payload), governed=True)
        assert base["tutor_pipeline"]["ledger"]["entry_schema"] == "ledger-entry-v3"
        assert {base["gateway"][block]["scope"] for block in ("budgets", "cache", "stop")} == {"database"} and base["gateway"]["stop"]["clear"] == "operator"
        assert base["flag_policy"]["model_gateway"]["stop"] == "off_until_cleared"
        assert all(base["v2"][block]["provisional"] is True for block in ("tiers", "voting", "correction", "degraded", "alignment"))


def test_gateway_package_check_problems():
    import dataclasses

    from app.gateway.package_check import check_gateway_package

    package = load_config_package(DEFAULT_PACKAGE_PATH, governed=True)
    assert check_gateway_package(package, structural=True) == []
    assert check_gateway_package(load_config_package(V4_PACKAGE_PATH, governed=True), structural=True) == []
    assert check_gateway_package(load_config_package(V3_PACKAGE_PATH, governed=True), structural=False) == [
        "the configuration package has no gateway, v2 or tools block (package v4 is required)"]
    cases = {
        "tools: schemas/tool-contracts.v1.json does not match its pinned sha256": dataclasses.replace(
            package, tools=dataclasses.replace(package.tools, sha256="0" * 64)),
        "tools: schemas/missing.json is missing": dataclasses.replace(package, tools=dataclasses.replace(package.tools, path="schemas/missing.json")),
        "v2.prompt: a prompt hash differs": dataclasses.replace(package, v2=dataclasses.replace(package.v2, verifier_prompt_hash="0" * 64)),
        "v2.panel_weights_version": dataclasses.replace(package, v2=dataclasses.replace(package.v2, panel_weights_version="dawid-skene-v1")),
        "v2.voting.matrix is not the routing table": dataclasses.replace(package, v2=dataclasses.replace(
            package.v2, matrix={**package.v2.matrix, "ZERO": {1: "1oo2", 2: "1oo2", 3: "1oo2"}})),
        "gateway.retired_settings differ": dataclasses.replace(package, gateway=dataclasses.replace(package.gateway, retired_settings=())),
        "v2.generator_families does not name every wired generator": dataclasses.replace(
            package, v2=dataclasses.replace(package.v2, generator_families={})),
    }
    for expected, broken in cases.items():
        problems = check_gateway_package(broken, structural=False)
        assert any(expected in problem for problem in problems), (expected, problems)


# --- Package v5 (Phase 6) ---

V5_SCHEMAS = {"V3GoldLabel": "schemas/v3-gold-label.v1.schema.json", "V3CusumAlarm": "schemas/v3-cusum-alarm.v1.schema.json"}


def test_v4_stays_readable_for_one_release():
    from app.gateway.package_check import check_gateway_package
    from app.services.tutor_pipeline.package_check import check_tutor_pipeline_package
    from app.services.v1_checks.package_check import check_v1_package

    package = load_config_package(V4_PACKAGE_PATH, governed=True)
    assert package.hash_verified and package.package_version == "4.0.0" and package.schema_version == 4 and not package.is_default_path
    assert package.v3 is None and package.flag_policy.phase6_exit_passed is False and package.gateway is not None
    assert package.sha256 == recorded_sha256(V4_PACKAGE_PATH) == canonical_sha256(V4_RAW) == V5_RAW["supersedes"]["sha256"]
    assert package.sha256 == "9cb984081c89c6f0d3b44cc36b38d3332383b76038734b4e21983d319c23408c"
    assert check_tutor_pipeline_package(package, structural=True) == [] and check_v1_package(package, structural=True) == []
    assert check_gateway_package(package, structural=True) == []


def test_v6_stays_readable_for_one_release():
    # Phase 7's shipped-package assertions, on v6 read explicitly since Phase 9 ships v7 (DI-126).
    package = load_config_package(V6_PACKAGE_PATH, governed=True)
    assert package.hash_verified and package.package_version == f"{EHMF_SCHEMA_VERSION}.0.0" and package.schema_version == EHMF_SCHEMA_VERSION
    assert package.ehmf is not None and package.ranking is None and V6_RAW["supersedes"]["sha256"] == canonical_sha256(V5_RAW)
    assert package.sha256 == recorded_sha256(V6_PACKAGE_PATH) == canonical_sha256(V6_RAW)
    # Its pinned V3 schemas are the four-reason gold label (Phase 9 spec conflict 28), so its structural check passes.
    from app.services.v3.package_check import check_v3_package

    assert check_v3_package(package, structural=True) == []


def test_the_v6_edits_v7_changes_are_exactly_the_ones_it_makes():
    # Package v7 (Phase 9 spec 5.1) is v6 with exactly these changes.
    assert (RAW["package_version"], RAW["schema_version"], RAW["phase"]) == (f"{RANKING_SCHEMA_VERSION}.0.0", RANKING_SCHEMA_VERSION, "9")
    assert RAW["supersedes"] == {"package_version": V6_RAW["package_version"], "sha256": canonical_sha256(V6_RAW),
                                 "readable_until": "the release after the Phase 9 merge"}
    assert set(RAW) == set(V6_RAW) | {"ranking"}
    for key in V6_RAW:
        if key not in {"package_version", "schema_version", "phase", "created", "supersedes", "flag_policy", "owner_decisions", "gateway", "v3"}:
            assert RAW[key] == V6_RAW[key], key
    gateway, v6_gateway = json.loads(json.dumps(RAW["gateway"])), json.loads(json.dumps(V6_RAW["gateway"]))
    delta = next(member for member in gateway["registries"]["development"] if member["adapter_id"] == "fake-delta-v1")
    assert delta["fake"] == {"rule": "verbatim-support-v1", "generate_rule": "extractive-clone-v1"}
    delta["fake"].pop("generate_rule")
    assert gateway == v6_gateway
    v3, v6_v3 = json.loads(json.dumps(RAW["v3"])), json.loads(json.dumps(V6_RAW["v3"]))
    assert v3["triggers"].pop("queue_reasons") == [*v6_v3["triggers"].pop("queue_reasons"), "ranking_empty_eligible_set"]
    assert v3["schemas"]["V3GoldLabel"].pop("path") == "schemas/v3-gold-label.v1.r7.schema.json"
    v3["schemas"]["V3GoldLabel"].pop("sha256")
    v6_v3["schemas"]["V3GoldLabel"].pop("path")
    v6_v3["schemas"]["V3GoldLabel"].pop("sha256")
    assert v3 == v6_v3
    decisions = RAW["owner_decisions"]
    assert set(decisions) == set(V6_RAW["owner_decisions"]) | {"D-28", "D-15", "RANKING-TOPIC-CLUSTERS", "RANKING-PARAMETERS"}
    for name, decision in V6_RAW["owner_decisions"].items():
        if name != "D-06":
            assert decisions[name] == decision, name
    assert decisions["D-06"]["operator_values"] == [*V6_RAW["owner_decisions"]["D-06"]["operator_values"], "ranking.penalties"]
    policy = dict(RAW["flag_policy"])
    assert policy.pop("ranking")["on_everywhere"] == "refused_while_d28_open"
    assert policy.pop("phase9_exit_passed") is False and policy.pop("phase9_exit_evidence") is None
    assert policy.pop("authority").startswith(V6_RAW["flag_policy"]["authority"])
    assert policy == {key: value for key, value in V6_RAW["flag_policy"].items() if key != "authority"}


def test_v5_keeps_every_v4_value_but_the_listed_changes():
    assert (V5_RAW["package_version"], V5_RAW["schema_version"], V5_RAW["phase"]) == ("5.0.0", 5, "6")
    assert V5_RAW["supersedes"] == {"package_version": "4.0.0", "sha256": canonical_sha256(V4_RAW), "readable_until": "the release after the Phase 6 merge"}
    assert set(V5_RAW) == set(V4_RAW) | {"v3"}
    for key in V4_RAW:
        if key not in {"package_version", "schema_version", "phase", "created", "supersedes", "flag_policy", "owner_decisions"}:
            assert V5_RAW[key] == V4_RAW[key], key
    assert V5_RAW["v2"]["correction"]["critical_registry"] == []
    policy = dict(V5_RAW["flag_policy"])
    queue = policy.pop("v3_queue")
    assert (queue["default_development"], queue["default_elsewhere"], queue["on_requires"], queue["disable"]) == (
        "shadow", "off", "phase6_exit_passed", "releases_nothing")
    assert policy.pop("phase6_exit_passed") is False and policy.pop("phase6_exit_evidence") is None
    authority = policy.pop("authority")
    assert authority.startswith(V4_RAW["flag_policy"]["authority"]) and "PD-38" in authority and "DI-98" in authority
    assert policy == {key: value for key, value in V4_RAW["flag_policy"].items() if key != "authority"}
    decisions = V5_RAW["owner_decisions"]
    assert set(decisions) == set(V4_RAW["owner_decisions"]) | {"D-08", "D-14", "D-18"}
    for name, decision in V4_RAW["owner_decisions"].items():
        if name not in ("D-06", "D-25"):
            assert decisions[name] == decision, name
    assert {key: value for key, value in decisions["D-06"].items() if key not in ("operator_values", "record")} == {
        key: value for key, value in V4_RAW["owner_decisions"]["D-06"].items() if key != "record"}
    assert decisions["D-06"]["operator_values"] == ["v3.slo", "v3.workflow.double_review"] and decisions["D-06"]["record"] == "DI-52; PD-36, PD-37; DI-98"
    assert decisions["D-25"]["state"] == "open" and decisions["D-25"]["registry"] == [] and decisions["D-25"]["record"] == "PD-29, PD-33; DI-90"
    assert decisions["D-18"]["state"] == "open" and decisions["D-18"]["reviewer_pool"] == "unstaffed" and decisions["D-18"]["ratified"] is False
    assert decisions["D-08"]["state"] == decisions["D-14"]["state"] == "open"
    v3 = V5_RAW["v3"]
    assert v3["provisional"] is True and all(v3[block]["provisional"] is True for block in (
        "triggers", "priority", "draw", "workflow", "critical_claims", "slo", "reviewers"))
    assert {name: pin["path"] for name, pin in v3["schemas"].items()} == V5_SCHEMAS
    registries = v3["critical_claims"]["registries"]
    assert [len(registries[name]["claims"]) for name in ("development", "staging", "production", "default")] == [3, 0, 0, 0]
    assert registries["development"]["synthetic"] is True
    assert v3["draw"]["rate"] == {"numerator": 1, "denominator": 20} and v3["triggers"]["x5"]["audit_rate"] == {"numerator": 1, "denominator": 5}
    assert v3["workflow"]["double_review"]["rate"] == {"numerator": 1, "denominator": 10} and v3["reviewers"]["pool"] == "unstaffed"
    package = load_config_package(V5_PACKAGE_PATH, governed=True)
    assert package.v3.critical_registry_for("development") == tuple(entry["claim_id"] for entry in registries["development"]["claims"])
    assert package.v3.critical_registry_for("staging") == package.v3.critical_registry_for("production") == ()
    assert package.v3.critical_registry_for("preview") == ()  # an unnamed environment reads the default registry


def _v3_block(payload: dict) -> dict:
    return payload["v3"]


def _unmark(block: str):
    return lambda p: _v3_block(p)[block].pop("provisional")


def _duplicate_development_entry(payload: dict) -> None:
    claims = _v3_block(payload)["critical_claims"]["registries"]["development"]["claims"]
    claims.append(dict(claims[0]))


@pytest.mark.parametrize(
    "edit",
    [
        lambda p: p.pop("v3"),
        lambda p: _v3_block(p).update(provisional=False),
        lambda p: _v3_block(p).update(version="v3-audit-v2"),
        *(_unmark(block) for block in ("triggers", "priority", "draw", "workflow", "critical_claims", "slo", "reviewers")),
        lambda p: _v3_block(p)["triggers"].update(version="x-triggers-v2"),
        lambda p: _v3_block(p)["triggers"]["rules"].update(X6="float-draw-v1"),
        lambda p: _v3_block(p)["triggers"]["x1"].update(min_objections=2),
        lambda p: _v3_block(p)["triggers"]["x1"].update(revision="allowed"),
        lambda p: _v3_block(p)["triggers"]["x1"].update(hold="none"),
        lambda p: _v3_block(p)["triggers"]["x2"].update(ehmf_types=["A", "B", "C"]),
        lambda p: _v3_block(p)["triggers"]["x4"].update(margin_source="v1.v1_5.other"),
        lambda p: _v3_block(p)["triggers"]["x5"].update(audit_rate={"numerator": 1, "denominator": 4}),
        lambda p: _v3_block(p)["triggers"]["x5"].update(window_deliveries=0),
        lambda p: _v3_block(p)["triggers"].update(counted=["X1", "X2", "X3", "X4", "X6"]),
        lambda p: _v3_block(p)["triggers"].update(queue_reasons=["v1_3_flag"]),
        lambda p: _v3_block(p)["priority"].update(rule="severity-only-v1"),
        lambda p: _v3_block(p)["priority"].update(exposure_rule="one-v1"),
        lambda p: _v3_block(p)["priority"]["severity"].update(C=0.7),
        lambda p: _v3_block(p)["priority"]["severity"].update(disclosed_conflict=0.6),
        lambda p: _v3_block(p)["priority"]["severity"].update(unknown=1.5),
        lambda p: _v3_block(p)["priority"]["severity"].pop("E"),
        lambda p: _v3_block(p)["priority"].update(tie_break=["item_id", "enqueued_at"]),
        lambda p: _v3_block(p)["draw"].update(rule="float-bernoulli-v1"),
        lambda p: _v3_block(p)["draw"].update(seed="Not A Seed"),
        lambda p: _v3_block(p)["draw"].update(rate={"numerator": 1, "denominator": 10}),
        lambda p: _v3_block(p)["draw"].update(population=["legacy"]),
        lambda p: _v3_block(p)["workflow"].update(lease_s=10),
        lambda p: _v3_block(p)["workflow"]["double_review"].update(rate={"numerator": 1, "denominator": 5}),
        lambda p: _v3_block(p)["workflow"].update(max_rounds=2),
        lambda p: _v3_block(p)["workflow"].update(self_review="allowed"),
        lambda p: _v3_block(p)["workflow"].update(apply_by="adjudicator"),
        lambda p: _v3_block(p)["workflow"].update(independence="reviewer_digest"),
        lambda p: _v3_block(p)["workflow"].update(applies_to_ledger=True),
        lambda p: _v3_block(p)["workflow"].update(releases_withheld=True),
        lambda p: _v3_block(p)["workflow"].update(blind_to=["finals"]),
        lambda p: _v3_block(p)["workflow"].update(unreviewable="claimable"),
        lambda p: _v3_block(p)["gold_store"].update(append_only=False),
        lambda p: _v3_block(p)["gold_store"].update(restore="import"),
        lambda p: _v3_block(p)["gold_store"].update(chain="tutor-responses"),
        # D-25 open: no registry outside development, and the development one is synthetic and well formed.
        lambda p: _v3_block(p)["critical_claims"]["registries"]["staging"]["claims"].append({"claim_id": "claim-" + "a" * 32, "query_index": 1}),
        lambda p: _v3_block(p)["critical_claims"]["registries"]["production"]["claims"].append({"claim_id": "claim-" + "a" * 32, "query_index": 1}),
        lambda p: _v3_block(p)["critical_claims"]["registries"]["development"].pop("synthetic"),
        lambda p: _v3_block(p)["critical_claims"]["registries"]["development"]["claims"].append({"claim_id": "claim-x", "query_index": 1}),
        lambda p: _v3_block(p)["critical_claims"]["registries"]["development"]["claims"][0].pop("query_index"),
        _duplicate_development_entry,
        lambda p: _v3_block(p)["critical_claims"]["registries"].pop("default"),
        lambda p: _v3_block(p)["critical_claims"].update(fixture="../outside.json"),
        lambda p: p["v2"]["correction"].update(critical_registry=["claim-" + "b" * 32]),
        # A decided D-25 passes the v2 rule (PD-29), and v5 still refuses a v2 registry: v3.critical_claims supersedes it.
        lambda p: (p["owner_decisions"]["D-25"].update(state="decided"), p["v2"]["correction"].update(critical_registry=["claim-" + "b" * 32])),
        lambda p: _v3_block(p)["slo"].update(queue_age_slo_s=60),
        lambda p: _v3_block(p)["slo"].update(stop_window_s=86400),
        lambda p: _v3_block(p)["slo"].update(stop_sample_s=7000),
        lambda p: _v3_block(p)["slo"].update(stop_measure="queue_age_p90"),
        lambda p: _v3_block(p)["slo"].update(stop_tier1="none"),
        lambda p: _v3_block(p)["slo"].update(unreadable="clear"),
        lambda p: _v3_block(p)["slo"].update(escalation_share_max={"numerator": 1, "denominator": 5}),
        lambda p: _v3_block(p)["slo"].update(window_days=0),
        lambda p: _v3_block(p)["residual"].update(population="every_delivery"),
        lambda p: _v3_block(p)["reviewers"].update(pool="staffed"),
        lambda p: _v3_block(p)["reviewers"].update(outside_development="admitted"),
        lambda p: _v3_block(p)["reviewers"].update(flag_intake="everywhere"),
        lambda p: _v3_block(p)["reviewers"].update(role="admin"),
        lambda p: _v3_block(p)["schemas"].pop("V3CusumAlarm"),
        lambda p: _v3_block(p)["schemas"]["V3GoldLabel"].update(sha256="xyz"),
        lambda p: _v3_block(p)["schemas"]["V3GoldLabel"].update(path="../gold.json"),
        lambda p: p["owner_decisions"].pop("D-18"),
        lambda p: p["owner_decisions"].pop("D-08"),
        lambda p: p["owner_decisions"].pop("D-14"),
        lambda p: p["flag_policy"]["v3_queue"].update(default_elsewhere="shadow"),
        lambda p: p["flag_policy"]["v3_queue"].update(default_development="on"),
        lambda p: p["flag_policy"]["v3_queue"].update(on_requires="nothing"),
        lambda p: p["flag_policy"]["v3_queue"].update(disable="releases_held"),
        lambda p: p["flag_policy"].update(phase6_exit_passed="no"),
        lambda p: p["flag_policy"].update(phase6_exit_passed=True),
        lambda p: p["flag_policy"].update(authority=V4_RAW["flag_policy"]["authority"]),
        lambda p: p.update(schema_version=EHMF_SCHEMA_VERSION),
    ],
)
def test_v5_structural_errors_always_stop_the_load(tmp_path, edit):
    # v5 read explicitly since Phase 7 ships v6 (DI-112); a schema_version=6 v5 has no ehmf block, so it is refused. Each
    # refusal holds for the shipped v6 too (it keeps every v5 block), but for the edits v6 itself changes: the trigger
    # registry x-triggers-v2 and schema_version 6 are v6's own values (no edit there), and v6 takes V3 severity from
    # ehmf.weights, so it has no severity.E to remove (test_the_v5_edits_v6_changes_are_exactly_the_three_it_makes).
    _the_unedited_copies_load(tmp_path)
    for base in (V5_RAW, V6_RAW, RAW):
        if base is not V5_RAW and not _v5_edit_applies_to_v6(edit, base):
            continue
        payload = json.loads(json.dumps(base))
        edit(payload)
        path = _write(tmp_path, payload)
        for governed in (True, False):
            with pytest.raises(ConfigPackageError):
                load_config_package(path, governed=governed)


def _v5_edit_applies_to_v6(edit, base=V6_RAW) -> bool:
    payload = json.loads(json.dumps(base))
    try:
        edit(payload)
    except KeyError:
        return False
    return payload != base


def _the_unedited_copies_load(tmp_path: Path) -> None:
    """The control: each base, written as the edited copies are, loads, so a refusal is the edit's."""
    for base in (V4_RAW, V5_RAW, V6_RAW, RAW):
        load_config_package(_write(tmp_path, json.loads(json.dumps(base))), governed=False)


def test_the_v5_edits_v6_changes_are_exactly_the_three_it_makes():
    edits = next(mark.args[1] for mark in test_v5_structural_errors_always_stop_the_load.pytestmark if mark.name == "parametrize")
    assert len([edit for edit in edits if not _v5_edit_applies_to_v6(edit)]) == 3
    assert V6_RAW["v3"]["triggers"]["version"] == "x-triggers-v2" and V6_RAW["schema_version"] == EHMF_SCHEMA_VERSION
    assert "E" not in V6_RAW["v3"]["priority"]["severity"] and V6_RAW["v3"]["priority"]["severity"]["source"] == "ehmf.weights"
    # v7 keeps every v6 block these edits touch, and its own schema_version (7) is an edit there too (Phase 9).
    assert len([edit for edit in edits if not _v5_edit_applies_to_v6(edit, RAW)]) == 2


def test_v3_package_check_problems():
    import dataclasses

    from app.services.v3.package_check import check_v3_package

    package = load_config_package(DEFAULT_PACKAGE_PATH, governed=True)
    assert check_v3_package(package, structural=True) == []
    assert check_v3_package(load_config_package(V4_PACKAGE_PATH, governed=True), structural=False) == [
        "the configuration package has no v3 block (package v5 is required)"]
    pins = dict(package.v3.schemas)
    cases = {
        "does not match its pinned sha256": dataclasses.replace(package, v3=dataclasses.replace(
            package.v3, schemas={**pins, "V3GoldLabel": dataclasses.replace(pins["V3GoldLabel"], sha256="0" * 64)})),
        "is missing or not JSON": dataclasses.replace(package, v3=dataclasses.replace(
            package.v3, schemas={**pins, "V3CusumAlarm": dataclasses.replace(pins["V3CusumAlarm"], path="schemas/missing.json")})),
        "v3.trigger_rules": dataclasses.replace(package, v3=dataclasses.replace(package.v3, trigger_rules={**package.v3.trigger_rules, "X6": "other"})),
        "v3.counted": dataclasses.replace(package, v3=dataclasses.replace(package.v3, counted=("X1", "X2", "X3", "X4", "X6"))),
        "v3.draw_rule": dataclasses.replace(package, v3=dataclasses.replace(package.v3, draw_rule="float-v1")),
    }
    for expected, broken in cases.items():
        problems = check_v3_package(broken, structural=False)
        assert any(expected in problem for problem in problems), (expected, problems)
    missing_fixture = dataclasses.replace(package, v3=dataclasses.replace(package.v3, critical_fixture="apps/api/tests/data/missing.json"))
    assert any("missing" in problem for problem in check_v3_package(missing_fixture, structural=True))
    assert check_v3_package(missing_fixture, structural=False) == []  # start-up never reads apps/api/tests/


def test_the_v3_start_up_check_runs_from_the_image_layout(monkeypatch):
    # In the image the V3 check is /app/app/services/v3/package_check.py: no checkout above /app and no apps/api/tests/.
    # Start-up imports it (lifespan -> _initialize_database -> _check_tutor_pipeline_package -> _check_v3_package), so it
    # must check the shipped package there without the development registry's fixture; only the structural check reads it.
    from app import main as main_module
    from app.services import v3 as v3_service

    image = _image_module("services/v3/package_check.py", "app.services.v3.package_check")
    monkeypatch.setitem(sys.modules, "app.services.v3.package_check", image)
    monkeypatch.setattr(main_module, "settings", Settings(environment="production", v3_queue="shadow"))
    package = load_config_package(DEFAULT_PACKAGE_PATH, governed=True)
    main_module._check_v3_package(package)  # a governed build with V3 requested: any problem raises ConfigPackageError
    assert v3_service.V3_UNAVAILABLE_REASON is None
    assert image.check_v3_package(package, structural=False) == []
    assert image.check_v3_package(package, structural=True) == [f"v3.critical_claims.fixture: {package.v3.critical_fixture} is missing"]
