"""Phase 3: the configuration package's tutor_pipeline block and flag policy against the code and the loader's bounds
(Phase 3 spec section 5).

C3  the PD-11 values live in the package (budgets included), not in code constants, and the loader bounds them.
C4  plan 12.8 (ledger retention) is an open decision: the package says "retain" (that no job deletes a ledger row is
    in test_response_ledger_chain.py).
D6  flag_policy is marked provisional (PD-10), and POST /tutor/turns has no rate limit of its own.
E2  the schema guard compares the leaf constraints too (type, enum, const, pattern, bounds, defaults).
F4  every rule id the package names, and the two_pass_tutor defaults, are compared with the code.
F5  the extractive generator's question-overlap threshold is a package value.
H3  the package's pipeline version, resolver and renderer ids, Idempotency-Key header, presentation plans and default
    plan are compared with the code, and /ready reports the code's values.
The tests read the shipped package (DEFAULT_PACKAGE_PATH). Each test fails if its defect comes back; the spec's review
history (18.4) names the round behind each group.
"""

from __future__ import annotations

import copy
import dataclasses
import inspect
import json
from pathlib import Path
import shutil
from typing import Literal, get_args

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy import exc as sa_exc
from sqlalchemy.orm import sessionmaker

from app.core.config import TWO_PASS_DEFAULT_DEVELOPMENT, TWO_PASS_DEFAULT_ELSEWHERE, Settings
from app.core.config_package import (
    DEFAULT_PACKAGE_PATH,
    ConfigPackageError,
    canonical_sha256,
    get_config_package,
    load_config_package,
    parse_config_package,
)
from app.core.db import Base
from app.core.schema_upgrades import run_schema_upgrades
from app.main import app
from app.services import ledger
from app.services.ledger import append_ledger_entry
from app.services.turn_idempotency import IDEMPOTENCY_HEADER
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline import shadow as shadow_module
from app.services.tutor_pipeline.contracts import EnvelopeSpan, EvidentialEnvelope, EvidentialInstructions, PresentationPlan
from app.services.tutor_pipeline.evidential import EXTRACTIVE_ID, ExtractiveD19Generator, evidential_prompt_hash
from app.services.tutor_pipeline.package_check import LEAF_KEYWORDS, check_tutor_pipeline_package, schema_path, structural_problems
from app.services.tutor_pipeline.pipeline import PIPELINE_VERSION
from app.services.tutor_pipeline.render import PLANS_LAYOUT, RENDERER_ID
from app.services.tutor_pipeline.resolve import RESOLVER_ID
from app.services.tutor_pipeline.text import sentences

from tutor_fakes import make_entry


PACKAGE = get_config_package(Settings())
PARAMS = PACKAGE.tutor_pipeline
RAW = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
API_ROOT = Path(__file__).resolve().parents[1]


def fresh_sessions(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False), engine


def write_package(tmp_path: Path, edit) -> Path:
    """A copy of the shipped package (DEFAULT_PACKAGE_PATH, package v3 since Phase 4) under its own name, with `edit`
    applied, its sidecar rewritten and its schema files alongside."""
    payload = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
    edit(payload)
    path = tmp_path / DEFAULT_PACKAGE_PATH.name
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.with_name(f"{path.name}.sha256").write_text(canonical_sha256(payload) + "\n", encoding="utf-8")
    shutil.copytree(DEFAULT_PACKAGE_PATH.parent / "schemas", tmp_path / "schemas", dirs_exist_ok=True)
    return path


def parsed(raw: dict):
    return parse_config_package(raw, path=DEFAULT_PACKAGE_PATH, sha256="", hash_verified=False)


# =============================================================================================================== C3


def test_c3_every_pd11_value_lives_in_the_package_marked_provisional():
    tutor = RAW["tutor_pipeline"]
    assert tutor["provisional"] is True and tutor["status"] == "provisional"
    assert "no plan value" in tutor["authority"] and "never a plan default" in tutor["authority"]
    assert (tutor["resolver"]["min_content_terms"], tutor["resolver"]["max_lookback"]) == (2, 4)
    assert tutor["resolver"]["continuation_cues"] and (tutor["retrieval"]["top_k"], tutor["retrieval"]["mode"]) == (4, "lexical")
    evidential = tutor["evidential"]
    assert (evidential["max_claims"], evidential["max_claims_per_span"], evidential["min_sentence_words"], evidential["max_sentence_chars"]) == (3, 2, 4, 1000)
    assert (tutor["pedagogical"]["presentation_plans"], tutor["pedagogical"]["default_plan"]) == (["concise", "stepwise", "socratic"], "concise")
    budgets = tutor["budgets"]
    assert budgets["provisional"] is True and "no plan value" in budgets["authority"]
    assert {key: budgets[key] for key in budgets if key not in {"provisional", "authority"}} == {
        "shadow_ms": 2000, "ledger_append_ms": 1500, "ledger_append_attempts": 3, "ledger_wait_grace_ms": 250,
        "ledger_append_workers": 4, "ledger_append_max_in_flight": 16,
    }
    assert tutor["idempotency"]["provisional"] is True and tutor["idempotency"]["ttl_hours"] == 24
    assert tutor["stop"]["phase2_bound_claim_ratio"] == 1.0
    # The settings no longer carry the budgets as code defaults; they are overrides only.
    assert (Settings().two_pass_shadow_budget_ms, Settings().tutor_ledger_append_budget_ms) == (None, None)
    for name in ("ledger_budget_ms", "ledger_params"):
        assert callable(getattr(ledger, name))
    for gone in ("APPEND_ATTEMPTS", "LEGACY_WAIT_GRACE_MS", "LEGACY_APPEND_WORKERS", "LEGACY_APPEND_MAX_IN_FLIGHT"):
        assert not hasattr(ledger, gone), gone
    assert inspect.signature(sentences).parameters["max_chars"].default is inspect.Parameter.empty


def _changed_budgets(payload):
    payload["tutor_pipeline"]["budgets"].update(shadow_ms=1234, ledger_append_ms=777, ledger_append_attempts=2, ledger_wait_grace_ms=40)


def test_c3_the_runtime_takes_the_budgets_and_attempts_from_the_package(tmp_path, monkeypatch, fresh_database_url):
    package = load_config_package(write_package(tmp_path, _changed_budgets), governed=False)
    settings = Settings()
    assert (ledger.ledger_budget_ms(settings, package), shadow_module.shadow_budget_ms(settings, package)) == (777, 1234)
    explicit = Settings(tutor_ledger_append_budget_ms=300, two_pass_shadow_budget_ms=400)
    assert (ledger.ledger_budget_ms(explicit, package), shadow_module.shadow_budget_ms(explicit, package)) == (300, 400)
    # append_ledger_entry's attempt count is the package's when the caller names none.
    monkeypatch.setattr(ledger, "get_config_package", lambda _settings=None: package)
    factory, engine = fresh_sessions(fresh_database_url)
    attempts = []

    def always_conflicting():
        session = factory()

        def commit():
            attempts.append(1)
            raise sa_exc.IntegrityError("INSERT", {}, Exception("duplicate seq (test)"))

        session.commit = commit
        return session

    try:
        with pytest.raises(ledger.LedgerAppendError):
            append_ledger_entry(make_entry(), session_factory=always_conflicting, budget_ms=5000)
        assert len(attempts) == 2
    finally:
        engine.dispose()
    # Package v1 pins no ledger parameters: the legacy record fails closed (counted), never on a code default.
    with pytest.raises(ledger.LedgerUnavailable):
        ledger.ledger_params(dataclasses.replace(package, tutor_pipeline=None))


@pytest.mark.parametrize("edit, message", [
    (lambda p: p["tutor_pipeline"]["budgets"].pop("provisional"), "budgets must be marked provisional"),
    (lambda p: p["tutor_pipeline"]["budgets"].update(ledger_append_ms=50), "ledger_append_ms"),
    (lambda p: p["tutor_pipeline"]["budgets"].update(ledger_append_max_in_flight=1), "ledger_append_max_in_flight"),
    (lambda p: p["tutor_pipeline"]["idempotency"].update(key_pattern="^.*$"), "anchored and bounded"),
    (lambda p: p["tutor_pipeline"]["idempotency"].pop("provisional"), "idempotency must be marked provisional"),
])
def test_c3_the_loader_refuses_a_budget_or_key_rule_outside_its_bounds(edit, message):
    payload = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
    edit(payload)
    with pytest.raises(ConfigPackageError, match=message):
        parse_config_package(payload, path=DEFAULT_PACKAGE_PATH, sha256="", hash_verified=False)


# =============================================================================================================== C4


def test_c4_the_package_records_the_retention_decision_as_open_and_the_ledger_as_retained():
    decision = PACKAGE.owner_decisions["PLAN-12.8"]
    assert (decision["state"], decision["behaviour"], decision["ratified"], decision["record"]) == ("open", "retain", False, "DI-45")
    assert PARAMS.ledger_retention == "retain"
    for edit in (lambda p: p["owner_decisions"]["PLAN-12.8"].update(state="decided"),
                 lambda p: p["owner_decisions"]["PLAN-12.8"].update(behaviour="delete-after-release-life-plus-24-months"),
                 lambda p: p["tutor_pipeline"]["ledger"].update(retention="release-life-plus-24-months"),
                 lambda p: p["owner_decisions"].pop("PLAN-12.8")):
        payload = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
        edit(payload)
        with pytest.raises(ConfigPackageError, match="PLAN-12.8"):
            parse_config_package(payload, path=DEFAULT_PACKAGE_PATH, sha256="", hash_verified=False)


# =============================================================================================================== D6


def test_d6_flag_policy_is_marked_provisional_and_the_loader_requires_it():
    assert RAW["flag_policy"]["provisional"] is True and "PD-10" in RAW["flag_policy"]["authority"]
    payload = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
    payload["flag_policy"].pop("provisional")
    with pytest.raises(ConfigPackageError, match="flag_policy must be marked provisional"):
        parse_config_package(payload, path=DEFAULT_PACKAGE_PATH, sha256="", hash_verified=False)
    # The new route limits are the existing routes' limits, recorded as PD-11 engineering parameters. Since spec 18.10
    # H5 POST /tutor/turns has no limit of its own: it shares POST /assistant/chat's window and limit.
    settings = Settings()
    assert settings.ledger_rate_limit == settings.spans_rate_limit and not hasattr(settings, "tutor_turns_rate_limit")
    source = (API_ROOT / "app" / "core" / "config.py").read_text(encoding="utf-8")
    assert "provisional (PD-11" in source


# =============================================================================================================== E2


def _package_copy(tmp_path: Path):
    """A copy of the shipped package (package v3 since Phase 4) under its own name, with its schema files."""
    shutil.copytree(PACKAGE.path.parent / "schemas", tmp_path / "schemas")
    raw = json.loads(PACKAGE.path.read_text(encoding="utf-8"))
    (tmp_path / PACKAGE.path.name).write_text(json.dumps(raw), encoding="utf-8")
    return raw


@pytest.mark.parametrize("name, edit", [
    ("EvidenceBundle", lambda schema: schema["$defs"]["EvidenceSpan"]["properties"].update(license_class={"type": "string"})),
    ("EvidenceBundle", lambda schema: schema["$defs"]["EvidenceSpan"]["properties"].update(span_id={"type": "integer"})),
    ("LedgerEntry", lambda schema: schema["properties"]["delivery"].update(enum=[*schema["properties"]["delivery"]["enum"], "anything"])),
    ("LedgerEntry", lambda schema: schema["properties"]["response_id"].pop("pattern")),
])
def test_e2_a_leaf_change_in_a_repinned_schema_file_is_a_package_problem(tmp_path, name, edit):
    raw = _package_copy(tmp_path)
    pin = raw["tutor_pipeline"]["schemas"][name]
    target = tmp_path / pin["path"]
    schema = json.loads(target.read_text(encoding="utf-8"))
    edit(schema)
    target.write_text(json.dumps(schema), encoding="utf-8")
    pin["sha256"] = canonical_sha256(schema)  # re-pinned, so only the structural comparison can catch it
    (tmp_path / PACKAGE.path.name).write_text(json.dumps(raw), encoding="utf-8")
    problems = check_tutor_pipeline_package(load_config_package(tmp_path / PACKAGE.path.name, governed=False), structural=True)
    assert problems == [f"schema {name}: the committed file's structure differs from the {name} model (a property, the required set or a constraint)"]


def test_e2_a_model_changed_without_write_schemas_is_a_package_problem(monkeypatch):
    class Widened(contracts.LedgerEntry):
        delivery: Literal["shadow", "delivered", "legacy", "anything"]

    class Unpatterned(contracts.LedgerEntry):
        response_id: str

    committed = json.loads(schema_path(PACKAGE, PARAMS.schemas["LedgerEntry"].path).read_text(encoding="utf-8"))
    assert structural_problems("LedgerEntry", committed) == []
    for model in (Widened, Unpatterned):
        monkeypatch.setitem(contracts.SCHEMA_MODELS, "LedgerEntry", model)
        generated = model.model_json_schema(mode="validation")
        # The property names and the required set are unchanged: only a leaf constraint moved.
        assert set(generated["properties"]) == set(committed["properties"]) and set(generated["required"]) == set(committed["required"])
        assert any("structure differs" in problem for problem in check_tutor_pipeline_package(PACKAGE, structural=True)), model.__name__
    # Annotations are not constraints: a changed title or description is no problem.
    monkeypatch.undo()
    annotated = json.loads(json.dumps(committed))
    annotated["title"], annotated["properties"]["delivery"]["title"] = "Renamed", "Renamed"
    assert structural_problems("LedgerEntry", annotated) == []
    assert {"type", "enum", "const", "pattern", "minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems", "default"} <= set(LEAF_KEYWORDS)
    assert not {"title", "description"} & set(LEAF_KEYWORDS)


# =============================================================================================================== F4


@pytest.mark.parametrize(
    ("block", "key", "value"),
    [
        ("retrieval", "near_miss_rule", "runner-up-margin-v2"),
        ("ledger", "chain", "some-other-chain"),
        ("ledger", "entry_schema", "ledger-entry-v7"),
        ("ledger", "record_hash_rule", "sha256(prev_hash||entry)-v9"),
    ],
)
def test_f4_every_rule_id_the_package_names_is_compared_with_the_code(block, key, value):
    assert check_tutor_pipeline_package(PACKAGE, structural=False) == []
    raw = copy.deepcopy(RAW)
    raw["tutor_pipeline"][block][key] = value
    problems = check_tutor_pipeline_package(parsed(raw), structural=False)
    assert any(f"tutor_pipeline.{block}.{key}" in problem for problem in problems), problems


def test_f4_the_two_pass_defaults_in_the_package_are_the_ones_settings_applies():
    policy = RAW["flag_policy"]["two_pass_tutor"]
    assert (policy["default_development"], policy["default_elsewhere"]) == (TWO_PASS_DEFAULT_DEVELOPMENT, TWO_PASS_DEFAULT_ELSEWHERE) == ("shadow", "off")
    assert Settings(environment="development").two_pass_tutor == policy["default_development"]
    assert Settings(environment="production").two_pass_tutor == policy["default_elsewhere"]
    for key, value in (("default_development", "off"), ("default_development", "on"), ("default_elsewhere", "shadow")):
        raw = copy.deepcopy(RAW)
        raw["flag_policy"]["two_pass_tutor"][key] = value
        with pytest.raises(ConfigPackageError, match=key):
            parsed(raw)


# =============================================================================================================== F5


def _overlap_package(value):
    raw = copy.deepcopy(RAW)
    if value is None:
        raw["tutor_pipeline"]["evidential"].pop("min_question_overlap_terms")
    else:
        raw["tutor_pipeline"]["evidential"]["min_question_overlap_terms"] = value
    return parsed(raw)


def test_f5_the_question_overlap_threshold_is_a_package_value():
    assert RAW["tutor_pipeline"]["evidential"]["min_question_overlap_terms"] == PARAMS.min_question_overlap_terms == 1
    for bad in (0, 21, None):
        with pytest.raises(ConfigPackageError, match="min_question_overlap_terms"):
            _overlap_package(bad)
    two = _overlap_package(2)
    # The value is hashed into the evidential prompt hash, so a changed threshold under the pinned hash is a problem.
    assert evidential_prompt_hash(PARAMS) == PARAMS.evidential_prompt_hash != evidential_prompt_hash(two.tutor_pipeline)
    assert any("evidential prompt hash" in problem for problem in check_tutor_pipeline_package(two, structural=False))
    envelope = EvidentialEnvelope(
        question="Why does routing depth matter?",
        corpus_version="corpus-test",
        evidence=(EnvelopeSpan(span_id="span-" + "a" * 64,
                               text="Routing is hard to do well in practice. Routing depth matters for every circuit we build."),),
        instructions=EvidentialInstructions(rule_id=EXTRACTIVE_ID, prompt_hash=PARAMS.evidential_prompt_hash, max_claims=3,
                                            max_claims_per_span=2, min_sentence_words=4),
    )
    assert [claim.text for claim in ExtractiveD19Generator(PACKAGE).propose(envelope).claims] == [
        "Routing is hard to do well in practice.", "Routing depth matters for every circuit we build."]
    assert [claim.text for claim in ExtractiveD19Generator(two).propose(envelope).claims] == ["Routing depth matters for every circuit we build."]
    source = (API_ROOT / "app" / "services" / "tutor_pipeline" / "evidential.py").read_text(encoding="utf-8")
    assert "self.params.min_question_overlap_terms" in source and "& question_terms]" not in source


# =============================================================================================================== H3


def _edited(edit) -> list[str]:
    raw = copy.deepcopy(RAW)
    edit(raw["tutor_pipeline"])
    package = parsed(raw)
    return check_tutor_pipeline_package(package, structural=False)


@pytest.mark.parametrize(
    ("name", "edit", "expected"),
    [
        ("resolver id", lambda t: t["resolver"].update(id="thread-resolver-v9"), "tutor_pipeline.resolver.id"),
        ("renderer", lambda t: t["pedagogical"].update(renderer="model-renderer-v2"), "tutor_pipeline.pedagogical.renderer"),
        ("idempotency header", lambda t: t["idempotency"].update(header="X-Request-Key"), "tutor_pipeline.idempotency.header"),
        ("pipeline version", lambda t: t.update(version="two-pass-v7"), "tutor_pipeline.version"),
        ("a fourth plan", lambda t: t["pedagogical"]["presentation_plans"].append("worked_example"), "presentation_plans"),
        ("a repeated plan", lambda t: t["pedagogical"]["presentation_plans"].append("concise"), "presentation_plans"),
        ("an unknown default plan", lambda t: (t["pedagogical"]["presentation_plans"].append("worked_example"),
                                               t["pedagogical"].update(default_plan="worked_example")), "default_plan"),
    ],
)
def test_h3_every_component_id_and_plan_the_package_names_is_compared_with_the_code(name, edit, expected):
    assert check_tutor_pipeline_package(PACKAGE, structural=False) == [] == check_tutor_pipeline_package(PACKAGE, structural=True)
    problems = _edited(edit)
    assert any(expected in problem for problem in problems), (name, problems)


def test_h3_the_code_values_the_package_must_match():
    tutor = RAW["tutor_pipeline"]
    assert (tutor["version"], tutor["resolver"]["id"], tutor["pedagogical"]["renderer"]) == (PIPELINE_VERSION, RESOLVER_ID, RENDERER_ID)
    assert tutor["idempotency"]["header"] == IDEMPOTENCY_HEADER == "Idempotency-Key"
    assert set(tutor["pedagogical"]["presentation_plans"]) == set(PLANS_LAYOUT) == set(get_args(PresentationPlan.model_fields["plan_id"].annotation))
    # The route reads the key from the header the package names.
    parameters = app.openapi()["paths"]["/tutor/turns"]["post"]["parameters"]
    headers = [p["name"] for p in parameters if p["in"] == "header"]
    assert IDEMPOTENCY_HEADER in headers and not [name for name in headers if "idempotency" in name.lower() and name != IDEMPOTENCY_HEADER]
    route_source = (API_ROOT / "app" / "api" / "routes" / "tutor.py").read_text(encoding="utf-8")
    assert "alias=turn_idempotency.IDEMPOTENCY_HEADER" in route_source and 'alias="Idempotency-Key"' not in route_source
    # /ready reports these values, so they are the code's.
    pipeline = TestClient(app).get("/ready").json()["tutor_pipeline"]
    assert (pipeline["version"], pipeline["resolver"], pipeline["renderer"]) == (PIPELINE_VERSION, RESOLVER_ID, RENDERER_ID)
    assert pipeline["presentation_plans"] == list(PLANS_LAYOUT)
