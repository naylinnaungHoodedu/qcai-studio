"""Phase 3 hardening (2026-11-19, second review round; Phase 3 spec 18.5). Each test fails if its defect comes back.

C1  license_class is derived from the span's plane and the manifest, and a span that is not public is never emitted.
C2  every config.override key is recorded under production settings, one relaxation at a time.
C3  the PD-11 values live in configuration package v2 (budgets included), not in code constants.
C4  plan 12.8 (ledger retention) is an open decision: the package says "retain" and no job deletes a ledger row.
C7  pg8000, the production driver, raises the PEP 249 class psycopg raises for the same SQLSTATE.
C8  every /qa/ask delivery is ledgered, bounded and fail-open, with no learner text or identifier.
C9  POST /tutor/turns honours an Idempotency-Key, scoped to the caller.
C10 sentences-v2 keeps abbreviations, initials and numbers inside their sentence.
C12 a thread's messages are timezone-aware UTC and strictly ordered, also under concurrency on PostgreSQL.
(C5 and C6 are in test_rate_limit.py and test_demo_seed.py; C11 in the frontend tests.)

Isolation (spec M17): concurrency and retention tests use fresh_database_url. Demo ids are uuid4-based. No skips:
dialect-specific assertions branch inside the test.
"""

from __future__ import annotations

import ast
import dataclasses
from datetime import UTC, datetime, timedelta
import inspect
import json
from pathlib import Path
import re
import shutil
import textwrap
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy import exc as sa_exc
from sqlalchemy.orm import sessionmaker

from app import main as main_module
from app.api.routes import qa as qa_route
from app.api.routes import spans as spans_route
from app.api.routes import tutor as tutor_route
from app.core import db as db_module
from app.core.auth import AuthUser
from app.core.config import Settings
from app.core.config_package import (
    DEFAULT_PACKAGE_PATH,
    ConfigPackageError,
    canonical_sha256,
    get_config_package,
    load_config_package,
    parse_config_package,
)
from app.core.corpus_governance import CorpusRegistry, get_corpus_registry
from app.core.db import Base, SessionLocal, engine as session_engine
from app.core.schema_upgrades import run_schema_upgrades
from app.db_models import QAInteraction, ResponseLedgerHead, ResponseLedgerRecord, TutorMessage, TutorTurn, TutorTurnIdempotency
from app.main import app
from app.schemas import AssistantChatRequest
from app.services import ledger, retention, tutor_orchestrator as orchestrator_module, turn_idempotency
from app.services.contained_answers import contain_answer
from app.services.erasure import erase_user, user_keyed_tables
from app.services.ledger import append_ledger_entry, build_legacy_entry, legacy_delivery_for, verify_response_ledger
from app.services.provenance import native_citation
from app.services.qa_engine import QAEngine
from app.services.retention import run_retention_cleanup
from app.services.retrieval_engine import RetrievalEngine
from app.services.store import get_course_store, get_retrieval_engine, get_span_resolver
from app.services.teaching_assistant import TeachingAssistantService
from app.services.tutor_orchestrator import TutorOrchestrator
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline import shadow as shadow_module
from app.services.tutor_pipeline.contracts import RetrievalRequest, sha256_hex
from app.services.tutor_pipeline.metrics import LEDGER_METRICS, LICENSE_METRICS
from app.services.tutor_pipeline.package_check import check_tutor_pipeline_package
from app.services.tutor_pipeline.retrieve import retrieve
from app.services.tutor_pipeline.text import SENTENCE_RULE, sentences, split_sentences
from tutor_fakes import FailingLedger, make_entry

DATA = Path(__file__).parent / "data"
QUERIES = json.loads((DATA / "score_floor_queries.json").read_text(encoding="utf-8"))
PACKAGE = get_config_package(Settings())
PARAMS = PACKAGE.tutor_pipeline
RAW = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
HEADER_SUBSET = ("content-type", "cache-control")
IN_DOMAIN = "Why does routing depth matter?"
client = TestClient(app)


def demo(prefix: str, role: str = "learner") -> dict[str, str]:
    return {"x-demo-user": f"{prefix}-{uuid4().hex[:12]}", "x-demo-role": role, "x-forwarded-for": f"hardening-{uuid4().hex}"}


def fresh(headers: dict[str, str]) -> dict[str, str]:
    # A distinct client address per request keeps the per-address limits apart.
    return {**headers, "x-forwarded-for": f"hardening-{uuid4().hex}"}


def records(**where) -> list[ResponseLedgerRecord]:
    with SessionLocal() as db:
        query = select(ResponseLedgerRecord).order_by(ResponseLedgerRecord.seq)
        for column, value in where.items():
            query = query.where(getattr(ResponseLedgerRecord, column) == value)
        return list(db.scalars(query))


def fresh_sessions(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False), engine


def write_package(tmp_path: Path, edit) -> Path:
    """A copy of package v2 with `edit` applied, its sidecar rewritten and its schema files alongside."""
    payload = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
    edit(payload)
    path = tmp_path / "v2.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "v2.json.sha256").write_text(canonical_sha256(payload) + "\n", encoding="utf-8")
    shutil.copytree(DEFAULT_PACKAGE_PATH.parent / "schemas", tmp_path / "schemas", dirs_exist_ok=True)
    return path


@pytest.fixture
def clean_metrics():
    LEDGER_METRICS.reset()
    LICENSE_METRICS.reset()
    yield


class ForcedSpans:
    """The course store's span registry with some records replaced: spans that the upstream guards (the span builder
    refuses non-public items, the index takes only indexable files) should never let exist."""

    def __init__(self, base, forced: dict) -> None:
        self.base, self.forced = base, forced

    def get(self, span_id):
        return self.forced.get(span_id) or self.base.get(span_id)

    def __getattr__(self, name):
        return getattr(self.base, name)


# ============================================================================================================ C1


def test_c1_the_license_class_is_derived_from_the_records_plane_and_the_manifest(monkeypatch):
    registry = get_corpus_registry(Settings())
    record = next(r for r in get_course_store().span_registry.records if r.item_kind == "document")
    assert registry.license_class(plane=record.plane, item_id=record.item_id, source_filename=record.source_filename) == "public"
    for plane in ("private", None, "", "PUBLIC"):
        assert registry.license_class(plane=plane, item_id=record.item_id, source_filename=record.source_filename) is None
    monkeypatch.setattr(registry, "is_private_item", lambda item_id: item_id == record.item_id)
    assert registry.license_class(plane="public", item_id=record.item_id) is None
    monkeypatch.setattr(registry, "is_private_item", lambda item_id: False)
    monkeypatch.setattr(registry, "is_private_plane", lambda filename: filename == record.source_filename)
    assert registry.license_class(plane="public", item_id=record.item_id, source_filename=record.source_filename) is None


def test_c1_a_forced_non_public_record_never_reaches_the_bundle_and_is_counted(monkeypatch, clean_metrics):
    settings = Settings()
    store = get_course_store()
    engine = RetrievalEngine(store, settings)
    registry = get_corpus_registry(settings)
    request = RetrievalRequest(text=IN_DOMAIN, corpus_version=store.corpus_version)
    baseline = retrieve(engine, request, top_k=4, registry=registry)
    assert len(baseline.spans) >= 2 and {span.license_class for span in baseline.spans} == {"public"}
    victim = baseline.spans[0].span_id
    monkeypatch.setattr(store, "span_registry", ForcedSpans(store.span_registry, {victim: dataclasses.replace(store.span_registry.get(victim), plane="private")}))
    bundle = retrieve(engine, request, top_k=4, registry=registry)
    assert [span.span_id for span in bundle.spans] == [span.span_id for span in baseline.spans[1:]]
    assert {span.license_class for span in bundle.spans} == {"public"}
    assert LICENSE_METRICS.snapshot()["two_pass"] == 1
    # Every result forced: nothing quotable is left, so the bundle abstains (never "evidence" with no span).
    everything = {span.span_id: dataclasses.replace(store.span_registry.get(span.span_id), plane="private") for span in baseline.spans}
    monkeypatch.setattr(store, "span_registry", ForcedSpans(store.span_registry.base, everything))
    empty = retrieve(engine, request, top_k=4, registry=registry)
    assert (empty.spans, empty.sufficiency.decision, empty.sufficiency.reason) == ((), "abstain", "no_quotable_evidence")
    # A manifest that moves the item to the private plane excludes it too, whatever the record says.
    monkeypatch.setattr(store, "span_registry", store.span_registry.base)
    item_id = store.span_registry.get(victim).item_id
    monkeypatch.setattr(registry, "is_private_item", lambda candidate: candidate == item_id)
    assert all(store.span_registry.get(span.span_id).item_id != item_id for span in retrieve(engine, request, top_k=4, registry=registry).spans)


def test_c1_the_span_routes_refuse_a_span_whose_class_is_not_public_even_if_the_resolver_returns_it(monkeypatch):
    record = next(r for r in get_course_store().span_registry.records if r.item_kind == "document")
    paths = (f"/spans/{record.span_id}", f"/evidence/spans/{record.span_id}")
    for path in paths:
        served = client.get(path, headers={"x-forwarded-for": f"hardening-{uuid4().hex}"})
        assert served.status_code == 200 and served.json()["license_class"] == "public"
    real = get_span_resolver()

    class LeakyResolver:
        def __init__(self, plane: str) -> None:
            self.plane = plane

        def resolve(self, span_id, db=None):
            resolved = real.resolve(span_id, db)
            return dataclasses.replace(resolved, plane=self.plane) if resolved is not None else None

    monkeypatch.setattr(spans_route, "get_span_resolver", lambda: LeakyResolver("private"))
    for path in paths:
        refused = client.get(path, headers={"x-forwarded-for": f"hardening-{uuid4().hex}"})
        assert (refused.status_code, refused.json(), refused.headers["cache-control"]) == (404, {"detail": "Span not found."}, "no-store")
    # The resolver says public, but the manifest puts the item on the private plane: the route's own gate refuses it.
    monkeypatch.setattr(spans_route, "get_span_resolver", lambda: LeakyResolver("public"))
    monkeypatch.setattr(CorpusRegistry, "is_private_item", lambda self, item_id: item_id == record.item_id)
    for path in paths:
        assert client.get(path, headers={"x-forwarded-for": f"hardening-{uuid4().hex}"}).status_code == 404


def _contained(settings: Settings):
    store = get_course_store()
    hits = [hit for hit in store.search(IN_DOMAIN, top_k=8) if hit.source_kind == "document"]
    citations = [native_citation(hit, corpus_version=store.corpus_version, settings=settings) for hit in hits]
    return contain_answer(citations, get_corpus_registry(settings), store.span_registry, settings=settings)


def test_c1_the_legacy_record_never_labels_or_records_a_non_public_quotation(clean_metrics):
    settings = Settings()
    store = get_course_store()
    registry = get_corpus_registry(settings)
    contained = _contained(settings)
    assert contained.decision == "answer" and len(contained.claims) >= 2
    victim = contained.claims[0].cited_span_ids[0]
    forced = SimpleNamespace(index=store.index, index_version=store.index_version, gate=store.gate,
                             span_registry=ForcedSpans(store.span_registry, {victim: dataclasses.replace(store.span_registry.get(victim), plane="private")}))
    delivery = legacy_delivery_for(response_id=f"turn-{uuid4()}", contained=contained, retrieval=None, store=forced, registry=registry,
                                   retrieval_mode="lexical", provider="none", model="test", policy_version="test", surface="tutor")
    citing = sum(1 for claim in contained.claims if victim in claim.cited_span_ids)
    assert victim not in {span.span_id for span in delivery.quoted} and delivery.dropped_not_public == citing
    entry = build_legacy_entry(delivery, settings=settings, package=PACKAGE, manifest_sha256=None)
    assert entry.counts.dropped == {"not_public": citing}
    assert victim not in entry.span_ids and all(victim not in claim.span_ids for claim in entry.claims)
    assert entry.retrieval.evidence and {span.license_class for span in entry.retrieval.evidence} == {"public"}
    assert LICENSE_METRICS.snapshot()["legacy"] == 1
    # Unforced, the same answer records every quotation.
    plain = legacy_delivery_for(response_id=f"turn-{uuid4()}", contained=contained, retrieval=None, store=store, registry=registry,
                                retrieval_mode="lexical", provider="none", model="test", policy_version="test", surface="tutor")
    assert plain.dropped_not_public == 0 and len(plain.claims) == len(contained.claims)


# ============================================================================================================ C2

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
}
PACKAGE_RELAXATIONS = {"config_package_path_overridden": {"is_default_path": False}, "config_package_hash_unverified": {"hash_verified": False}}
# Phase 4: a relaxation Settings refuse outside development before the Phase 4 exit (V1_PIPELINE=enforce). The alert
# still names it, should a build ever run with it, so it has its own case (built without validation).
REFUSED_RELAXATIONS = {"v1_pipeline_enforce": {"v1_pipeline": "enforce"}}


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


# ============================================================================================================ C3


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


# ============================================================================================================ C4


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


def test_c4_no_retention_or_erasure_job_deletes_a_ledger_row(fresh_database_url):
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        old = datetime(2001, 1, 1, tzinfo=UTC)
        for _ in range(3):
            append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000, now=old)
        with factory() as db:
            before = [(row.seq, row.record_hash) for row in db.scalars(select(ResponseLedgerRecord).order_by(ResponseLedgerRecord.seq))]
            head = db.get(ResponseLedgerHead, ledger.CHAIN)
            head_before = (head.seq, head.record_hash)
        with factory() as db:
            run_retention_cleanup(db, now=datetime(2100, 1, 1, tzinfo=UTC))  # every other rule's cutoff is long past
        with factory() as db:
            after = [(row.seq, row.record_hash) for row in db.scalars(select(ResponseLedgerRecord).order_by(ResponseLedgerRecord.seq))]
            head = db.get(ResponseLedgerHead, ledger.CHAIN)
            assert after == before and len(after) == 3 and (head.seq, head.record_hash) == head_before
            assert verify_response_ledger(db).ok
    finally:
        engine.dispose()
    source = inspect.getsource(retention)
    assert "ResponseLedger" not in source.replace("# No rule touches response_ledger", "")
    assert not {"response_ledger", "response_ledger_head"} & {table.name for table in user_keyed_tables()}


# ============================================================================================================ C7


@pytest.mark.parametrize("code, expected", [
    ("23514", sa_exc.IntegrityError), ("23503", sa_exc.IntegrityError), ("23502", sa_exc.IntegrityError),
    ("22P02", sa_exc.DataError), ("22001", sa_exc.DataError),
    ("55P03", sa_exc.OperationalError), ("57014", sa_exc.OperationalError), ("40001", sa_exc.OperationalError),
])
def test_c7_a_pg8000_server_error_takes_the_class_psycopg_gives_its_sqlstate(code, expected):
    import pg8000.dbapi

    original = pg8000.dbapi.ProgrammingError({"S": "ERROR", "C": code, "M": "test"})
    context = SimpleNamespace(dialect=SimpleNamespace(driver="pg8000"), is_disconnect=False, original_exception=original,
                              sqlalchemy_exception=sa_exc.ProgrammingError("SELECT 1", {}, original), statement="SELECT 1", parameters={})
    replaced = db_module.classify_pg8000_errors(context)
    assert type(replaced) is expected and replaced.orig is original and replaced.statement == "SELECT 1"


def test_c7_other_errors_and_other_drivers_are_left_as_raised():
    import pg8000.dbapi

    def context(driver, code, wrapped_class=sa_exc.ProgrammingError, disconnect=False):
        original = pg8000.dbapi.ProgrammingError({"C": code, "M": "test"})
        return SimpleNamespace(dialect=SimpleNamespace(driver=driver), is_disconnect=disconnect, original_exception=original,
                               sqlalchemy_exception=wrapped_class("SELECT 1", {}, original), statement="SELECT 1", parameters={})

    assert db_module.classify_pg8000_errors(context("pg8000", "42601")) is None  # a syntax error stays ProgrammingError
    assert db_module.classify_pg8000_errors(context("pg8000", "23505", sa_exc.IntegrityError)) is None  # already right
    assert db_module.classify_pg8000_errors(context("psycopg", "23514")) is None
    assert db_module.classify_pg8000_errors(context("pg8000", "08006", disconnect=True)) is None


def test_c7_constraint_and_data_errors_are_the_same_class_on_every_driver():
    table = f"hardening_check_{uuid4().hex[:8]}"
    with SessionLocal() as db:
        db.execute(text(f"CREATE TEMP TABLE {table} (value integer CHECK (value > 0))"))
        db.execute(text(f"INSERT INTO {table} VALUES (1)"))
        with pytest.raises(sa_exc.IntegrityError):  # psycopg CheckViolation; pg8000 re-classified from ProgrammingError
            db.execute(text(f"INSERT INTO {table} VALUES (-1)"))
        db.rollback()
        if session_engine.dialect.name == "postgresql":
            with pytest.raises(sa_exc.DataError):
                db.execute(text("SELECT CAST('not a number' AS integer)"))
            db.rollback()
        else:  # SQLite casts leniently; the temp table outlives the rollback of the failed insert there
            db.execute(text(f"DROP TABLE IF EXISTS {table}"))
            db.commit()


# ============================================================================================================ C8


def _ask(headers: dict[str, str], question: str):
    return client.post("/qa/ask", headers=fresh(headers), json={"question": question})


def _new_rows(before: set[int]) -> list[ResponseLedgerRecord]:
    return [row for row in records() if row.seq not in before]


def test_c8_every_qa_answer_and_abstention_is_ledgered_and_the_chain_verifies(clean_metrics):
    headers = demo("qa-ledger")
    before = {row.seq for row in records()}
    answered = _ask(headers, IN_DOMAIN)
    abstained = _ask(headers, QUERIES["off_topic"][0])
    assert (answered.status_code, answered.json()["decision"], abstained.json()["decision"]) == (200, "answer", "abstain")
    rows = _new_rows(before)
    assert [row.response_id[:3] for row in rows] == ["qa-", "qa-"]
    answer_entry, abstain_entry = (json.loads(row.entry) for row in rows)
    assert (answer_entry["delivery"], answer_entry["pipeline"], answer_entry["decision"]) == ("legacy", "legacy-contained-v1", "answer")
    assert answer_entry["rendered_text_sha256"] == sha256_hex(answered.json()["answer"])
    cited = {citation["span_id"] for citation in answered.json()["citations"]}
    assert answer_entry["span_ids"] and set(answer_entry["span_ids"]) <= cited
    assert answer_entry["retrieval"]["evidence_scope"] == "retrieved" and answer_entry["versions"]["generator_id"] == "contained-answers-v1"
    assert (abstain_entry["decision"], abstain_entry["claims"]) == ("abstain", [])
    # Spec 18.8 F1: the record keeps the gate's own reason for an off-topic question (the gate returned nothing),
    # with the gate's sufficiency decision; no_approved_span is for retrieved passages none of which could be quoted.
    sufficiency = abstain_entry["retrieval"]["sufficiency"]
    assert sufficiency["decision"] == "abstain" and abstain_entry["abstention_reason"] == sufficiency["reason"]
    assert abstain_entry["abstention_reason"] in contracts.GATE_ABSTENTION_REASONS
    assert answer_entry["retrieval"]["sufficiency"]["decision"] in {"answer", "near_miss"}
    with SessionLocal() as db:
        assert verify_response_ledger(db).ok
    qa = LEDGER_METRICS.snapshot()["legacy_by_surface"]["qa"]
    assert (qa["attempted"], qa["appended"], qa["failed"], qa["coverage_rate"]) == (2, 2, 0, 1.0)


def test_c8_the_qa_response_is_byte_identical_with_the_ledger_on_off_or_failing(monkeypatch, clean_metrics):
    headers = demo("qa-bytes")
    on = _ask(headers, IN_DOMAIN)
    count = len(records())
    monkeypatch.setattr(qa_route, "get_qa_engine", lambda: QAEngine(get_retrieval_engine(), Settings(tutor_ledger_enabled=False)))
    off = _ask(headers, IN_DOMAIN)
    assert len(records()) == count  # the kill switch writes nothing
    monkeypatch.undo()
    failing = FailingLedger()
    monkeypatch.setattr(ledger, "append_ledger_entry", failing)
    failed = _ask(headers, IN_DOMAIN)
    assert failing.calls == 1 and len(records()) == count
    assert on.status_code == off.status_code == failed.status_code == 200
    assert on.content == off.content == failed.content
    for name in HEADER_SUBSET:
        assert on.headers.get(name) == off.headers.get(name) == failed.headers.get(name), name
    assert LEDGER_METRICS.snapshot()["legacy_by_surface"]["qa"]["failed"] == 1 and LEDGER_METRICS.snapshot()["write_stop"] is True


def test_c8_erasure_removes_the_qa_rows_and_leaves_an_unlinkable_ledger_record_only_a_reviewer_reads():
    headers = demo("qa-erasure")
    user_id = headers["x-demo-user"]
    marker = f"zq{uuid4().hex[:10]}"
    before = {row.seq for row in records()}
    assert _ask(headers, f"{IN_DOMAIN} {marker}").status_code == 200
    (row,) = _new_rows(before)
    assert row.response_id.startswith("qa-") and marker not in row.entry and user_id not in row.entry
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(QAInteraction).where(QAInteraction.user_id == user_id)) == 1
        erase_user(db, user_id)
        db.commit()
        assert db.scalar(select(func.count()).select_from(QAInteraction).where(QAInteraction.user_id == user_id)) == 0
        assert verify_response_ledger(db).ok
    (kept,) = records(response_id=row.response_id)
    assert kept.record_hash == row.record_hash
    # No learner link is stored, so the asker reads nothing; a reviewer reads the record.
    assert client.get(f"/ledger/responses/{row.response_id}", headers=fresh(headers)).status_code == 404
    reviewed = client.get(f"/ledger/responses/{row.response_id}", headers=demo("qa-reviewer", role="reviewer"))
    assert reviewed.status_code == 200 and reviewed.json()["record"]["delivery"] == "legacy"


# ============================================================================================================ C9

TURN = {"message": IN_DOMAIN}


def _turn(headers: dict[str, str], body: dict, key: str | None = None, browser: TestClient = client):
    extra = {"Idempotency-Key": key} if key is not None else {}
    return browser.post("/tutor/turns", headers={**fresh(headers), **extra}, json=body)


def _turns_of(user_id: str) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(TutorTurn).where(TutorTurn.user_id == user_id)) or 0


def _key_rows(user_id: str) -> list[TutorTurnIdempotency]:
    with SessionLocal() as db:
        return list(db.scalars(select(TutorTurnIdempotency).where(TutorTurnIdempotency.user_id == user_id)))


def test_c9_a_retried_post_with_the_same_key_returns_the_first_turn_and_creates_no_second():
    headers = demo("idem")
    user_id = headers["x-demo-user"]
    key = f"retry-{uuid4().hex}"
    first = _turn(headers, TURN, key)
    again = _turn(headers, TURN, key)
    assert first.status_code == again.status_code == 200
    assert again.json() == first.json() and again.headers["idempotent-replayed"] == "true" and "idempotent-replayed" not in first.headers
    assert again.headers["x-assistant-model"] == first.headers["x-assistant-model"]
    assert _turns_of(user_id) == 1 and len(records(response_id=first.json()["turn_id"])) == 1
    (row,) = _key_rows(user_id)
    assert row.key_sha256 == sha256_hex(key) and key not in json.dumps([row.key_sha256, row.request_sha256, row.response_body])
    # Without a key every POST is a new turn, as before.
    assert _turn(headers, TURN).json()["turn_id"] != first.json()["turn_id"] and _turns_of(user_id) == 2


def test_c9_a_key_is_scoped_to_its_caller_and_a_changed_body_is_refused():
    learner, other = demo("idem-scope"), demo("idem-scope-other")
    key = f"shared-{uuid4().hex}"
    mine = _turn(learner, TURN, key)
    theirs = _turn(other, TURN, key)
    assert mine.status_code == theirs.status_code == 200 and mine.json()["turn_id"] != theirs.json()["turn_id"]
    assert "idempotent-replayed" not in theirs.headers and _turns_of(other["x-demo-user"]) == 1
    changed = _turn(learner, {"message": "What is QUBO optimization in logistics?"}, key)
    assert (changed.status_code, changed.json()) == (422, {"detail": "This Idempotency-Key was already used with a different request."})
    assert _turn(learner, {**TURN, "presentation_plan": "socratic"}, key).status_code == 422
    assert _turns_of(learner["x-demo-user"]) == 1


@pytest.mark.parametrize("key", ["short", "x" * 129, "has space inside", "slash/inside-key", "semi;colon-key", ""])
def test_c9_a_malformed_or_oversized_key_is_refused_before_anything_is_written(key):
    headers = demo("idem-bad")
    response = _turn(headers, TURN, key)
    assert response.status_code == 422 and _turns_of(headers["x-demo-user"]) == 0 and _key_rows(headers["x-demo-user"]) == []


def test_c9_a_disabled_route_answers_404_whatever_the_key(monkeypatch):
    production = Settings(**PRODUCTION)
    monkeypatch.setattr(tutor_route, "get_settings", lambda: production)
    for key in ("x" * 300, f"valid-{uuid4().hex}"):
        response = _turn(demo("idem-off"), TURN, key)
        assert (response.status_code, response.json()) == (404, {"detail": "Not Found"})


def test_c9_a_retry_while_the_first_still_runs_gets_409_and_a_failed_turn_releases_its_key():
    headers = demo("idem-409")
    user_id = headers["x-demo-user"]
    key = f"running-{uuid4().hex}"
    digest = turn_idempotency.request_sha256(message=IN_DOMAIN, thread_id=None, lesson_slug=None, presentation_plan=None)
    with SessionLocal() as db:
        db.add(TutorTurnIdempotency(user_id=user_id, key_sha256=sha256_hex(key), request_sha256=digest, created_at=datetime.now(UTC)))
        db.commit()
    running = _turn(headers, TURN, key)
    assert running.status_code == 409 and _turns_of(user_id) == 0
    # A turn that fails (a thread the caller does not own) releases its claim, so the key can be used again.
    owner = demo("idem-409-owner")
    thread_id = client.post("/assistant/threads", headers=fresh(owner), json={"title": "not yours"}).json()["id"]
    failed_key = f"failing-{uuid4().hex}"
    assert _turn(headers, {**TURN, "thread_id": thread_id}, failed_key).status_code == 404
    assert [row.key_sha256 for row in _key_rows(user_id)] == [sha256_hex(key)]


def test_c9_concurrent_requests_with_one_key_create_one_turn():
    headers = demo("idem-race")
    user_id = headers["x-demo-user"]
    key = f"race-{uuid4().hex}"
    results: list = []
    if session_engine.dialect.name == "postgresql":
        barrier = threading.Barrier(3)

        def worker():
            browser = TestClient(app)  # one client per thread
            barrier.wait()
            results.append(_turn(headers, TURN, key, browser))

        workers = [threading.Thread(target=worker) for _ in range(3)]
        for thread in workers:
            thread.start()
        for thread in workers:
            thread.join(60)
    else:  # in-memory SQLite shares one connection across threads (StaticPool, spec M17): one after the other
        results.extend(_turn(headers, TURN, key) for _ in range(3))
    statuses = sorted(response.status_code for response in results)
    assert len(results) == 3 and set(statuses) <= {200, 409} and 200 in statuses
    assert _turns_of(user_id) == 1
    turn_ids = {response.json()["turn_id"] for response in results if response.status_code == 200}
    assert len(turn_ids) == 1


def test_c9_a_key_expires_after_the_package_ttl_and_erasure_deletes_its_record():
    headers = demo("idem-expiry")
    user_id = headers["x-demo-user"]
    key = f"expired-{uuid4().hex}"
    expired_at = datetime.now(UTC) - timedelta(hours=PARAMS.idempotency_ttl_hours, minutes=5)
    digest = turn_idempotency.request_sha256(message=IN_DOMAIN, thread_id=None, lesson_slug=None, presentation_plan=None)
    with SessionLocal() as db:
        db.add(TutorTurnIdempotency(user_id=user_id, key_sha256=sha256_hex(key), request_sha256=digest, turn_id=f"turn-{uuid4()}",
                                    response_body="{}", created_at=expired_at))
        db.commit()
    renewed = _turn(headers, TURN, key)
    assert renewed.status_code == 200 and "idempotent-replayed" not in renewed.headers and _turns_of(user_id) == 1
    assert [row.turn_id for row in _key_rows(user_id)] == [renewed.json()["turn_id"]]
    # User-keyed: erasure deletes it, and guest retention covers it (test_erasure_retention walks every such table).
    assert "tutor_turn_idempotency" in {table.name for table in user_keyed_tables()}
    with SessionLocal() as db:
        erase_user(db, user_id)
        db.commit()
    assert _key_rows(user_id) == []


# =========================================================================================================== C10


@pytest.mark.parametrize("text, expected", [
    ("Hybrid solvers help on hard instances, e.g. vehicle routing with time windows. They also scale.",
     ["Hybrid solvers help on hard instances, e.g. vehicle routing with time windows.", "They also scale."]),
    ("A kernel is a similarity measure, i.e. an inner product in feature space. It is learned.",
     ["A kernel is a similarity measure, i.e. an inner product in feature space.", "It is learned."]),
    ("Tesi et al. explicitly target jet images from CMS Open Data. The model is hybrid.",
     ["Tesi et al. explicitly target jet images from CMS Open Data.", "The model is hybrid."]),
    ("As shown in Fig. 3 the error falls with depth. The next figure differs.",
     ["As shown in Fig. 3 the error falls with depth.", "The next figure differs."]),
    ("The update follows Eq. (2) and converges quickly. We stop there.", ["The update follows Eq. (2) and converges quickly.", "We stop there."]),
    ("Sec. 4 describes the routing heuristic in detail. It is greedy.", ["Sec. 4 describes the routing heuristic in detail.", "It is greedy."]),
    ("Quantum vs. classical baselines were compared on one dataset. Both converged.",
     ["Quantum vs. classical baselines were compared on one dataset.", "Both converged."]),
    ("Dr. Preskill coined the term NISQ for these devices. It stuck.", ["Dr. Preskill coined the term NISQ for these devices.", "It stuck."]),
    ("This follows J. Preskill closely in spirit. Others disagree.", ["This follows J. Preskill closely in spirit.", "Others disagree."]),
    ("Schuld, M., & Petruccione, F. (2021). Machine learning with quantum computers.",
     ["Schuld, M., & Petruccione, F. (2021).", "Machine learning with quantum computers."]),
    ("The gate fidelity reached 99.5 percent on average. Errors remain.", ["The gate fidelity reached 99.5 percent on average.", "Errors remain."]),
    ("Install version 1.2.3 of the toolkit before running. Then rerun it.", ["Install version 1.2.3 of the toolkit before running.", "Then rerun it."]),
    ("Python 3.11 is required by this module. Earlier releases fail.", ["Python 3.11 is required by this module.", "Earlier releases fail."]),
    ("Routing uses approx. ten swaps per layer here. That is cheap.", ["Routing uses approx. ten swaps per layer here.", "That is cheap."]),
    # Real boundaries still split.
    ("The circuit is deep. The noise grows.", ["The circuit is deep.", "The noise grows."]),
    ("Is it fast? Yes, on small inputs.", ["Is it fast?", "Yes, on small inputs."]),
    ("It works! Then it stops.", ["It works!", "Then it stops."]),
    ("Routing ends at step 3. Then mapping starts.", ["Routing ends at step 3.", "Then mapping starts."]),
    ("Gates, measurements, etc. The rest follows.", ["Gates, measurements, etc.", "The rest follows."]),
])
def test_c10_sentences_v2_keeps_abbreviations_initials_and_numbers_inside_their_sentence(text, expected):
    assert split_sentences(text) == expected


ABBREVIATION_ENDINGS = ("e.g.", "i.e.", "et al.", "Fig.", "Figs.", "Eq.", "Eqs.", "Sec.", "vs.", "Dr.", "Prof.", "cf.", "approx.")


def test_c10_no_dev_corpus_sentence_ends_at_an_abbreviation_any_more():
    def cut_at_abbreviation(parts: list[str]) -> int:
        return sum(1 for part in parts if part.endswith(ABBREVIATION_ENDINGS))

    documents = [record for record in get_course_store().span_registry.records if record.item_kind == "document"]
    # sentences-v1 cut after every ". " (the rule this one replaced).
    old_rule = sum(cut_at_abbreviation([part for part in re.split(r"(?<=[.!?])\s+", " ".join(r.text.split())) if part]) for r in documents)
    assert old_rule > 0  # the corpus does hold such sentences, so this test can fail
    assert sum(cut_at_abbreviation(split_sentences(r.text)) for r in documents) == 0


def test_c10_the_package_names_the_codes_sentence_rule_and_a_mismatch_is_a_package_problem():
    assert SENTENCE_RULE == PARAMS.sentence_rule == "sentences-v2"
    assert check_tutor_pipeline_package(PACKAGE, structural=False) == []
    stale = dataclasses.replace(PACKAGE, tutor_pipeline=dataclasses.replace(PARAMS, sentence_rule="sentences-v1"))
    assert any("sentence_rule" in problem for problem in check_tutor_pipeline_package(stale, structural=False))
    assert sentences("Short. A sentence of enough words here.", min_words=4, max_chars=PARAMS.max_sentence_chars) == ["A sentence of enough words here."]


# =========================================================================================================== C12


def _thread_messages(factory, thread_id: str) -> list[TutorMessage]:
    with factory() as db:
        return list(db.scalars(select(TutorMessage).where(TutorMessage.thread_id == thread_id).order_by(TutorMessage.created_at, TutorMessage.id)))


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _assert_strict_pairs(messages: list[TutorMessage], turns: int, dialect: str) -> None:
    assert [message.role for message in messages] == ["user", "assistant"] * turns
    times = [_as_utc(message.created_at) for message in messages]
    assert all(earlier < later for earlier, later in zip(times, times[1:]))
    assert all(times[index + 1] - times[index] == timedelta(microseconds=1) for index in range(0, len(times), 2))
    if dialect == "postgresql":
        # timestamptz comes back aware, in the session's time zone (not UTC on every cluster): the instants compare.
        assert all(message.created_at.tzinfo is not None for message in messages)


def test_c12_messages_stay_strictly_ordered_when_the_clock_stalls_or_goes_back(monkeypatch):
    base = datetime.now(UTC).replace(microsecond=0)
    clock = iter([base, base, base - timedelta(seconds=5)])
    monkeypatch.setattr(orchestrator_module, "_utc_now", lambda: next(clock))
    headers = demo("order-clock")
    first = client.post("/assistant/chat", headers=fresh(headers), json={"message": IN_DOMAIN}).json()
    for question in ("Why does it matter?", "What about graph shrinking?"):
        assert client.post("/assistant/chat", headers=fresh(headers), json={"message": question, "thread_id": first["thread_id"]}).status_code == 200
    messages = _thread_messages(SessionLocal, first["thread_id"])
    _assert_strict_pairs(messages, 3, session_engine.dialect.name)
    # The first turn took the clock's UTC instant; the later two, the thread's latest message plus 1 microsecond.
    assert [_as_utc(message.created_at) - base for message in messages] == [timedelta(microseconds=n) for n in range(6)]
    detail = client.get(f"/assistant/threads/{first['thread_id']}", headers=fresh(headers)).json()
    assert [message["id"] for message in detail["messages"]] == [message.id for message in messages]
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"] * 3


def test_c12_concurrent_turns_of_one_thread_keep_a_strict_order_on_postgresql(fresh_database_url, monkeypatch):
    factory, engine = fresh_sessions(fresh_database_url)
    settings = Settings(two_pass_tutor="off", tutor_ledger_enabled=False)
    orchestrator = TutorOrchestrator(TeachingAssistantService(RetrievalEngine(get_course_store(), settings), settings), settings)
    user = AuthUser(user_id=f"order-{uuid4().hex[:12]}", email=None, role="learner", provider="demo")
    stalled = datetime.now(UTC)
    monkeypatch.setattr(orchestrator_module, "_utc_now", lambda: stalled)  # every turn asks for the same instant
    try:
        with factory() as db:
            thread_id = orchestrator.create_thread(db, user, "order").id
            db.commit()
        turns = 6
        errors: list[BaseException] = []

        def worker(index: int) -> None:
            try:
                with factory() as db:
                    orchestrator.chat(db, user, AssistantChatRequest(message=f"{IN_DOMAIN} ({index})", thread_id=thread_id))
                    db.commit()
            except BaseException as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

        if engine.dialect.name == "postgresql":
            barrier = threading.Barrier(turns)
            workers = [threading.Thread(target=lambda index=index: (barrier.wait(), worker(index))) for index in range(turns)]
            for thread in workers:
                thread.start()
            for thread in workers:
                thread.join(120)
        else:  # SQLite (development and tests) serialises writers; the order rule is the same, one turn after another
            for index in range(turns):
                worker(index)
        assert errors == []
        messages = _thread_messages(factory, thread_id)
        _assert_strict_pairs(messages, turns, engine.dialect.name)
        with factory() as db:
            turn_times = sorted(_as_utc(turn.created_at) for turn in db.scalars(select(TutorTurn).where(TutorTurn.thread_id == thread_id)))
        assert turn_times == [_as_utc(message.created_at) for message in messages if message.role == "user"]
    finally:
        engine.dispose()
