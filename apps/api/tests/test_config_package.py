"""Configuration package (plan Phase 2 P; decision D9; Phase 2 spec 2.5, 4.2; Phase 3 P "schemas in configuration
package v2", Phase 3 spec section 5; Phase 4 P "fixture hashes in configuration package v3", Phase 4 spec section 5)."""

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
    V1_PACKAGE_PATH,
    V2_PACKAGE_PATH,
    V3_PACKAGE_PATH,
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


def _write(tmp_path: Path, payload: dict, *, sidecar: str | None = None) -> Path:
    path = tmp_path / "v1.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "v1.json.sha256").write_text((sidecar or canonical_sha256(payload)) + "\n", encoding="utf-8")
    return path


def test_the_shipped_package_validates_and_matches_its_hash():
    # Phase 5: the shipped package is v4 (4.0.0); the 3.0.0, 2.0.0 and 1.0.0 assertions are
    # test_v3_stays_readable_for_one_release's, test_v2_stays_readable_for_one_release's and
    # test_v1_stays_readable_for_one_release's.
    package = load_config_package(DEFAULT_PACKAGE_PATH, governed=True)
    assert package.hash_verified and package.is_default_path and package.package_version == "4.0.0"
    assert package.schema_version == 4 and package.tutor_pipeline is not None and package.v1 is not None
    assert package.gateway is not None and package.v2 is not None and package.tools is not None
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
    # Each refusal holds for v3.json, still readable, and for the shipped v4, which keeps every v3 block (Phase 5 spec 13.3).
    for base in (V3_RAW, RAW):
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
    assert package.sha256 == recorded_sha256(V3_PACKAGE_PATH) == canonical_sha256(V3_RAW) == RAW["supersedes"]["sha256"]
    assert check_tutor_pipeline_package(package, structural=True) == [] and check_v1_package(package, structural=True) == []


def test_v4_keeps_every_v3_value_but_the_listed_changes():
    assert (RAW["package_version"], RAW["schema_version"], RAW["phase"]) == ("4.0.0", 4, "5")
    assert RAW["supersedes"] == {"package_version": "3.0.0", "sha256": canonical_sha256(V3_RAW), "readable_until": "the release after the Phase 5 merge"}
    assert set(RAW) == set(V3_RAW) | V4_NEW_BLOCKS
    for key in V3_RAW:
        if key not in {"package_version", "schema_version", "phase", "created", "supersedes", "tutor_pipeline", "flag_policy", "owner_decisions"}:
            assert RAW[key] == V3_RAW[key], key
    tutor, v3_tutor = RAW["tutor_pipeline"], V3_RAW["tutor_pipeline"]
    for key, value in v3_tutor.items():
        if key not in {"schemas", "ledger", "unused_provenance_fields"}:
            assert tutor[key] == value, key
    assert {name: pin for name, pin in tutor["schemas"].items() if name not in V4_SCHEMAS} == v3_tutor["schemas"]
    assert {name: tutor["schemas"][name]["path"] for name in V4_SCHEMAS} == V4_SCHEMAS
    ledger = dict(tutor["ledger"])
    assert (ledger.pop("entry_schema"), ledger.pop("entry_schemas")) == ("ledger-entry-v3", ["ledger-entry-v1", "ledger-entry-v2", "ledger-entry-v3"])
    assert ledger == {key: value for key, value in v3_tutor["ledger"].items() if key not in {"entry_schema", "entry_schemas"}}
    assert tutor["unused_provenance_fields"] == []
    policy = dict(RAW["flag_policy"])
    assert policy.pop("model_gateway")["default_elsewhere"] == "off" and policy.pop("phase5_exit_passed") is False
    assert policy.pop("phase5_exit_evidence") is None
    authority = policy.pop("authority")
    assert authority.startswith(V3_RAW["flag_policy"]["authority"]) and "PD-28" in authority and "DI-76" in authority
    assert policy == {key: value for key, value in V3_RAW["flag_policy"].items() if key != "authority"}
    decisions = RAW["owner_decisions"]
    assert set(decisions) == set(V3_RAW["owner_decisions"]) | {"D-07", "Q-09", "D-23", "D-29", "D-25", "A-15", "Q-15"}
    for name, decision in V3_RAW["owner_decisions"].items():
        if name != "Q-22":
            assert decisions[name] == decision, name
    assert decisions["Q-22"]["provisional_values"] == [*V3_RAW["owner_decisions"]["Q-22"]["provisional_values"], "v2.voting"]
    assert decisions["Q-22"]["record"] == "PD-15, PD-16, PD-18, PD-25; DI-52"
    gateway = RAW["gateway"]
    assert {name: len(members) for name, members in gateway["registries"].items()} == {"development": 4, "staging": 0, "production": 0, "default": 0}
    assert gateway["budgets"]["daily_units"] == {"development": 100000, "staging": 0, "production": 0, "default": 0} and gateway["terms"] is None
    assert RAW["v2"]["degraded"]["pre_verified_source"] is None and RAW["v2"]["correction"]["critical_registry"] == []
    assert RAW["v2"]["voting"]["provisional_until"] == "Q-22 (DI-52)"


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
    ],
)
def test_v4_structural_errors_always_stop_the_load(tmp_path, edit):
    payload = json.loads(json.dumps(RAW))
    edit(payload)
    path = _write(tmp_path, payload)
    for governed in (True, False):
        with pytest.raises(ConfigPackageError):
            load_config_package(path, governed=governed)


def test_gateway_package_check_problems():
    import dataclasses

    from app.gateway.package_check import check_gateway_package

    package = load_config_package(DEFAULT_PACKAGE_PATH, governed=True)
    assert check_gateway_package(package, structural=True) == []
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
