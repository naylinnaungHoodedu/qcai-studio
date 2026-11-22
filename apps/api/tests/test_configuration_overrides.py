"""Phase 3: every configuration relaxation outside development raises config.override, and the budgets in force are
stamped and reported (spec 6, 11.3).

C2  every config.override key is recorded under production settings, one relaxation at a time, and an AST scan finds
    no key without its case.
D5  the budgets in force are stamped on every record and reported on /ready, and an override raises config.override.
Each test fails if its defect comes back; the spec's review history (18.4) names the round behind each group.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
from pathlib import Path
import shutil
import textwrap
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app import main as main_module
from app.core.config import Settings
from app.core.config_package import DEFAULT_PACKAGE_PATH, canonical_sha256, get_config_package
from app.main import app
from app.services import claim_gate
from app.services.ledger import build_legacy_entry
from app.services.retrieval_engine import RetrievalEngine
from app.services.store import get_course_store
from app.services.tutor_pipeline.contracts import PresentationPlan
from app.services.tutor_pipeline.pipeline import PipelineInput, TwoPassPipeline
from app.services.tutor_pipeline.resolve import LearnerTurn, resolve_turns
from app.services.tutor_pipeline.shadow import shadow_budget_ms


PACKAGE = get_config_package(Settings())
PARAMS = PACKAGE.tutor_pipeline
IN_DOMAIN = "How does graph shrinking reduce routing overhead?"
client = TestClient(app)


def write_package(tmp_path: Path, edit) -> Path:
    """A copy of the shipped package (DEFAULT_PACKAGE_PATH, package v4 since Phase 5) under its own name, with `edit`
    applied, its sidecar rewritten and its schema files alongside."""
    payload = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
    edit(payload)
    path = tmp_path / DEFAULT_PACKAGE_PATH.name
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.with_name(f"{path.name}.sha256").write_text(canonical_sha256(payload) + "\n", encoding="utf-8")
    shutil.copytree(DEFAULT_PACKAGE_PATH.parent / "schemas", tmp_path / "schemas", dirs_exist_ok=True)
    return path


def _run(pipeline: TwoPassPipeline, query: str, *, budget_ms: int | None = None):
    resolved = resolve_turns([], LearnerTurn(f"message-{uuid4()}", query), package=pipeline.package)
    return pipeline.run(PipelineInput(resolved=resolved, lesson_slug=None, presentation=PresentationPlan(plan_id="concise", source="request"),
                                      response_id=f"shadow-{uuid4()}", delivery="shadow", shadowed_response_id=f"turn-{uuid4()}"),
                        budget_ms=budget_ms, record=False)


# =============================================================================================================== C2


PRODUCTION = {"environment": "production", "allowed_origins": ["https://qantumlearn.academy"],
              "guest_token_secret": "a-production-like-secret-of-sufficient-length"}
SETTING_RELAXATIONS = {
    "demo_auth_enabled": {"enable_demo_auth": True},
    "corpus_governance_disabled": {"enforce_corpus_governance": False},
    "retrieval_gate_bm25": {"retrieval_gate": "bm25f-v1"},
    "p1_floor_recall_stop_overridden": {"allow_p1_floor_with_documents": True},
    "semantic_retrieval_enabled": {"semantic_retrieval_enabled": True},
    "span_resolver_route_enabled": {"span_resolver_route_enabled": True},
    "citation_provisional_lift_enabled": {"citation_provisional_lift_enabled": True},
    "two_pass_tutor_shadow": {"two_pass_tutor": "shadow"},
    "tutor_ledger_disabled": {"tutor_ledger_enabled": False},
    "ledger_route_enabled": {"ledger_route_enabled": True},
    "evidence_panel_enabled": {"evidence_panel_enabled": True},
    # Review round 3 (spec 18.6 D5): an environment override of a PD-11 budget.
    "shadow_budget_overridden": {"two_pass_shadow_budget_ms": 1000},
    "ledger_append_budget_overridden": {"tutor_ledger_append_budget_ms": 1000},
    # Phase 5: the V2 panel in shadow outside development, and a provider egress opt-in (D-23).
    "model_gateway_shadow": {"model_gateway": "shadow"},
    "model_egress_opt_in": {"model_egress_providers": ["openai-embeddings"]},
}
PACKAGE_RELAXATIONS = {"config_package_path_overridden": {"is_default_path": False}, "config_package_hash_unverified": {"hash_verified": False}}
# Phase 4: a relaxation Settings refuse outside development before the Phase 4 exit (V1_PIPELINE=enforce). The alert
# still names it, should a build ever run with it, so it has its own case (built without validation).
# Phase 5: MODEL_GATEWAY=on, refused outside development before the Phase 5 exit (and without V1_PIPELINE=enforce).
REFUSED_RELAXATIONS = {"v1_pipeline_enforce": {"v1_pipeline": "enforce"}, "model_gateway_on": {"model_gateway": "on"}}


def _override_details(monkeypatch, settings: Settings, package=None) -> dict | None:
    recorded = []
    monkeypatch.setattr(main_module, "IS_PRODUCTION", True)
    monkeypatch.setattr(main_module, "settings", settings)
    if package is not None:
        monkeypatch.setattr(main_module, "get_config_package", lambda _settings=None: package)
    monkeypatch.setattr(main_module, "record_security_event", lambda *args, **kwargs: recorded.append((args, kwargs)))
    main_module._record_configuration_overrides()
    if not recorded:
        return None
    ((args, kwargs),) = recorded
    assert args[:2] == ("config.override", "warning") and kwargs["actor_role"] == "system"
    return kwargs["details"]


def test_c2_production_defaults_record_no_override(monkeypatch):
    assert _override_details(monkeypatch, Settings(**PRODUCTION)) is None


@pytest.mark.parametrize("key", sorted(SETTING_RELAXATIONS))
def test_c2_each_settings_relaxation_is_recorded_under_its_own_key(monkeypatch, key):
    assert _override_details(monkeypatch, Settings(**PRODUCTION, **SETTING_RELAXATIONS[key])) == {key: True}


@pytest.mark.parametrize("key", sorted(REFUSED_RELAXATIONS))
def test_c2_each_refused_relaxation_is_refused_and_still_recorded_under_its_own_key(monkeypatch, key):
    with pytest.raises(ValueError):
        Settings(**PRODUCTION, **REFUSED_RELAXATIONS[key])
    assert _override_details(monkeypatch, Settings(**PRODUCTION).model_copy(update=REFUSED_RELAXATIONS[key])) == {key: True}


@pytest.mark.parametrize("key", sorted(PACKAGE_RELAXATIONS))
def test_c2_each_package_relaxation_is_recorded_under_its_own_key(monkeypatch, key):
    settings = Settings(**PRODUCTION)
    package = dataclasses.replace(get_config_package(settings), **PACKAGE_RELAXATIONS[key])
    assert _override_details(monkeypatch, settings, package) == {key: True}


def test_c2_a_package_named_by_path_is_recorded_through_the_real_loader(monkeypatch, tmp_path):
    path = write_package(tmp_path, lambda payload: None)
    assert _override_details(monkeypatch, Settings(**PRODUCTION, config_package_path=str(path))) == {"config_package_path_overridden": True}


def test_c2_all_relaxations_at_once_record_every_key(monkeypatch):
    combined = {name: value for relaxation in SETTING_RELAXATIONS.values() for name, value in relaxation.items()}
    settings = Settings(**PRODUCTION, **combined)
    package = dataclasses.replace(get_config_package(settings), is_default_path=False, hash_verified=False)
    assert _override_details(monkeypatch, settings, package) == {key: True for key in (*SETTING_RELAXATIONS, *PACKAGE_RELAXATIONS)}


def test_c2_every_key_the_alert_can_emit_has_a_case_here():
    """A key added to (or removed from) _record_configuration_overrides without a case here fails this test."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(main_module._record_configuration_overrides)))
    keys = {
        node.elts[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Tuple) and len(node.elts) == 2 and isinstance(node.elts[0], ast.Constant) and isinstance(node.elts[0].value, str)
    }
    assert keys == set(SETTING_RELAXATIONS) | set(PACKAGE_RELAXATIONS) | set(REFUSED_RELAXATIONS)


# =============================================================================================================== D5


def test_d5_every_record_stamps_the_budgets_in_force_and_whether_they_were_overridden():
    from app.services.ledger import LegacyDelivery

    delivery = LegacyDelivery(response_id=f"turn-{uuid4()}", decision="abstain", reason="no_approved_span", claims=(), quoted=(), retrieved=None,
                              answer_sha256="0" * 64, retrieval_mode="lexical", provider="none", model="m", corpus_version="c", index_version="i",
                              gate="p1-floor", threshold_version="score-floor-p1-v1", floor=6.0, margin=0.0, policy_version="p")
    packaged = build_legacy_entry(delivery, settings=Settings(), package=PACKAGE, manifest_sha256=None).versions.budgets
    assert (packaged.shadow_ms, packaged.ledger_append_ms, packaged.overridden) == (None, PARAMS.ledger_append_budget_ms, ())
    overridden = build_legacy_entry(delivery, settings=Settings(tutor_ledger_append_budget_ms=700), package=PACKAGE, manifest_sha256=None)
    assert (overridden.versions.budgets.ledger_append_ms, overridden.versions.budgets.overridden) == (700, ("ledger_append_ms",))
    # A shadow record stamps the shadow budget it ran under.
    settings = Settings(two_pass_shadow_budget_ms=1500)
    result = _run(TwoPassPipeline(RetrievalEngine(get_course_store(), settings), settings), IN_DOMAIN, budget_ms=shadow_budget_ms(settings, PACKAGE))
    assert (result.entry.versions.budgets.shadow_ms, result.entry.versions.budgets.overridden) == (1500, ("shadow_ms",))
    unbounded = _run(TwoPassPipeline(RetrievalEngine(get_course_store(), Settings()), Settings()), IN_DOMAIN)
    assert (unbounded.entry.versions.budgets.shadow_ms, unbounded.entry.versions.budgets.overridden) == (None, ())


def test_d5_ready_reports_the_budgets_and_an_override_is_alerted(monkeypatch):
    body = client.get("/ready").json()
    assert body["tutor_pipeline"]["budgets"] == {"shadow_ms": PARAMS.shadow_budget_ms, "ledger_append_ms": PARAMS.ledger_append_budget_ms, "overridden": []}
    assert body["tutor_pipeline"]["subset_check"] == claim_gate.SUBSET_CHECK_RULE == PARAMS.subset_check
    recorded = []
    production = {"environment": "production", "allowed_origins": ["https://qantumlearn.academy"],
                  "guest_token_secret": "a-production-like-secret-of-sufficient-length"}
    monkeypatch.setattr(main_module, "IS_PRODUCTION", True)
    monkeypatch.setattr(main_module, "settings", Settings(**production, two_pass_shadow_budget_ms=900, tutor_ledger_append_budget_ms=300))
    monkeypatch.setattr(main_module, "record_security_event", lambda *args, **kwargs: recorded.append(kwargs["details"]))
    main_module._record_configuration_overrides()
    assert recorded == [{"shadow_budget_overridden": True, "ledger_append_budget_overridden": True}]
    assert main_module._budget_fields(PACKAGE) == {"shadow_ms": 900, "ledger_append_ms": 300, "overridden": ["shadow_ms", "ledger_append_ms"]}
