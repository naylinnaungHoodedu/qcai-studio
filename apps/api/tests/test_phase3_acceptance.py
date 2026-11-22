"""Phase 3 acceptance: the provenance-first two-channel tutor (plan Phase 3 K, G, H, I, L; spec section 13.1).

Configurations (as Phase 2): "dev" is CourseStore(Settings()); "governed_empty" a production, governed build with the
committed manifest (D-31: nothing approved, authored spans only, so every two-pass run abstains); "all_public_approved"
the same with a temporary manifest approving every public-plane, bound item. Positive-path tests run on dev or
all-approved.

Readings (spec 0.3): every learner delivery is the legacy contained answer, ledgered as delivery "legacy" under the
TutorTurn id; every shadow run is ledgered as delivery "shadow" under a shadow- id naming that turn; "delivered" is
Phase 4's and refused. AC-3-4 is tested on every /assistant/chat and /tutor/turns response and its shadow record.
AC-3-6 "zero outputs reach a learner": the learner's body, the named header subset, stored messages, Q&A history and
thread detail equal those of the off mode; a learner reading a shadow record gets 404.

Isolation (spec M17): concurrency, tamper and trigger tests use fresh_database_url, never the shared StaticPool
session database. No skips: dialect-specific assertions branch on the dialect.
"""

from __future__ import annotations

import ast
from contextlib import contextmanager
import copy
from datetime import UTC, datetime
import importlib.util
import json
import logging
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, func, inspect as sa_inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.api.routes import assistant as assistant_route
from app.api.routes import ledger as ledger_route
from app.api.routes import spans as spans_route
from app.api.routes import tutor as tutor_route
from app.core.config import DEVELOPMENT_GUEST_TOKEN_SECRET, Settings, get_settings
from app.core.config_package import DEFAULT_PACKAGE_PATH, canonical_sha256, get_config_package
from app.core.corpus_governance import CorpusRegistry, get_corpus_registry
from app.core.db import Base, SessionLocal, engine as session_engine
from app.core.guest_tokens import GUEST_TOKEN_COOKIE, guest_csrf_for, issue_guest_token
from app.core.manifest_v2 import compute_corpus_version, with_all_public_approved
from app.core.schema_upgrades import RESPONSE_LEDGER_SQLITE_TRIGGERS, run_schema_upgrades
from app.core.source_assets import source_asset_id
from app.db_models import (
    LearnerProfile,
    Note,
    QAInteraction,
    QuizAttempt,
    ResponseLedgerHead,
    ResponseLedgerRecord,
    SecurityEvent,
    TutorMessage,
    TutorThread,
    TutorTurn,
)
from app.main import app
from app.schemas import LearnerRecordOperationInput
from app.services import ledger
from app.services.content_assembler import CourseStore
from app.services.erasure import erase_user, user_keyed_tables
from app.services.learner_record import apply_learner_record_operations
from app.services.ledger import (
    SCHEMA_REVISION,
    append_ledger_entry,
    ledger_canonical,
    verify_response_ledger,
)
from app.services.retrieval_engine import RetrievalEngine
from app.services.span_resolver import SpanResolver
from app.services.store import get_course_store
from app.services.teaching_assistant import TeachingAssistantService
from app.services.tutor_orchestrator import TutorOrchestrator
from app.services.tutor_pipeline import contracts, shadow as shadow_module
from app.services.tutor_pipeline import pipeline as pipeline_module
from app.services.tutor_pipeline.contracts import (
    LEARNER_STATE_FIELDS,
    EvidentialEnvelope,
    LedgerEntry,
    PresentationPlan,
    ResolvedQuestion,
    RetrievalRequest,
    sha256_hex,
)
from app.services.tutor_pipeline.evidential import ExtractiveD19Generator
from app.services.tutor_pipeline.lock import lock
from app.services.tutor_pipeline.metrics import LEDGER_METRICS, TWO_PASS_METRICS, TwoPassMetrics
from app.services.tutor_pipeline.pipeline import DeliveryNotImplemented, PipelineInput, TwoPassPipeline, render_checked
from app.services.tutor_pipeline.render import TEMPLATES, TemplateRenderer
from app.services.tutor_pipeline.resolve import LearnerTurn, ResolverInputError, resolve_thread, resolve_turns
from app.services.tutor_pipeline.shadow import ShadowJob, effective_mode, run_shadow
from app.services.tutor_pipeline.text import sentences
from app.services.claim_gate import check_subset
from tutor_fakes import FAULT_MODES, FAULT_SIGNATURES, FailingLedger, FaultyRenderer, ScriptedGenerator, SpyGenerator, make_entry

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
DATA = Path(__file__).parent / "data"
REPO_MANIFEST = REPO_ROOT / "corpus" / "public" / "manifest.json"
AC = json.loads((DATA / "score_floor_queries.json").read_text(encoding="utf-8"))
IN_DOMAIN = [item["query"] for item in AC["in_domain"]]
# A query whose two-pass answer locks several claims on several spans (spec 18.10 H1, 18.11 I2): a fault that moves a
# citation between claims, or leaves a claim line out, needs at least two claim lines citing distinct spans.
MULTI_CLAIM = "Explain why quantum logistics needs both problem reduction before execution and routing control during compilation."
OFF_TOPIC = AC["off_topic"]
ROUTING_DOCUMENT = "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx"
TRUSTED_ORIGIN = "http://localhost:3000"
GATES = ("p1-floor", "bm25f-v1")
HEADER_SUBSET = ("content-type", "cache-control", "x-assistant-provider", "x-assistant-model")
PACKAGE = get_config_package(Settings())
PARAMS = PACKAGE.tutor_pipeline
client = TestClient(app)
_TMP = tempfile.TemporaryDirectory(prefix="qcai-phase3-")
APPROVED_MANIFEST = Path(_TMP.name) / "all_public_approved" / "manifest.json"
APPROVED_MANIFEST.parent.mkdir(parents=True)
APPROVED_MANIFEST.write_text(json.dumps(with_all_public_approved(json.loads(REPO_MANIFEST.read_text(encoding="utf-8")))), encoding="utf-8")


# ------------------------------------------------------------------------------------------------------- helpers


def settings_for(config: str, gate: str | None = None, manifest: Path | None = None, **extra) -> Settings:
    if gate:
        extra["retrieval_gate"] = gate
    if config == "dev":
        return Settings(**extra)
    path = manifest or (REPO_MANIFEST if config == "governed_empty" else APPROVED_MANIFEST)
    return Settings(environment="production", enforce_corpus_governance=True, corpus_manifest_path=str(path), **extra)


_STORES: dict[tuple[str, str | None], CourseStore] = {}


def store_for(config: str, gate: str | None = None) -> CourseStore:
    key = (config, gate)
    if key not in _STORES:
        _STORES[key] = get_course_store() if (config, gate) in {("dev", None), ("dev", "bm25f-v1")} else CourseStore(settings_for(config, gate))
    return _STORES[key]


def demo(prefix: str, role: str = "learner") -> dict[str, str]:
    # uuid4-based demo ids; a distinct client address keeps per-address limits apart.
    return {"x-demo-user": f"{prefix}-{uuid4().hex[:12]}", "x-demo-role": role, "x-forwarded-for": f"phase3-{uuid4().hex}"}


def anonymous() -> dict[str, str]:
    return {"x-forwarded-for": f"phase3-{uuid4().hex}"}


def fresh(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "x-forwarded-for": f"phase3-{uuid4().hex}"}


def fresh_sessions(database_url: str) -> tuple[sessionmaker, Engine]:
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False), engine


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"phase3_{name}", REPO_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def edited_manifest(tmp_path: Path, edit, *, base: Path = REPO_MANIFEST) -> Path:
    payload = json.loads(base.read_text(encoding="utf-8"))
    edit(payload)
    payload["corpus_version"] = compute_corpus_version(payload["items"])
    path = tmp_path / f"manifest-{uuid4().hex[:8]}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def orchestrator_for(settings: Settings, store: CourseStore | None = None, assistant_class=TeachingAssistantService) -> TutorOrchestrator:
    engine = RetrievalEngine(store or get_course_store(), settings)
    return TutorOrchestrator(assistant_class(engine, settings), settings)


def records(**where) -> list[ResponseLedgerRecord]:
    with SessionLocal() as db:
        query = select(ResponseLedgerRecord).order_by(ResponseLedgerRecord.seq)
        for column, value in where.items():
            query = query.where(getattr(ResponseLedgerRecord, column) == value)
        return list(db.scalars(query))


def entry_of(row: ResponseLedgerRecord) -> dict:
    return json.loads(row.entry)


def without_ids(body: dict) -> dict:
    return {key: value for key, value in body.items() if key not in {"thread_id", "turn_id"}}


def chat(headers: dict[str, str], message: str, **extra):
    return client.post("/assistant/chat", headers=fresh(headers), json={"message": message, **extra})


def seed_learner(user_id: str, mastery: float, marker: str) -> None:
    with SessionLocal() as db:
        apply_learner_record_operations(db, user_id, [LearnerRecordOperationInput(
            operation_id=f"op-{uuid4().hex[:12]}", replica_id=f"replica-{uuid4().hex[:8]}", logical_counter=1,
            operation_type="mastery_set", payload={"skill_id": "routing", "value": mastery})])
        db.add(Note(user_id=user_id, lesson_slug="ai4qc-routing-and-optimization", body=f"My note {marker}"))
        db.add(QuizAttempt(user_id=user_id, lesson_slug="ai4qc-routing-and-optimization", score=int(mastery * 10), responses={"q": marker}))
        db.add(QAInteraction(user_id=user_id, lesson_slug=None, question=f"Earlier question {marker}", answer="Earlier answer", citations=[]))
        db.add(LearnerProfile(user_id=user_id, focus_area=f"Focus {marker}", self_ratings={"routing": mastery}))
        db.commit()


def walk(value, path: str = "$"):
    """Every (path, key, value) at any depth of a JSON-like value."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield path, key, item
            yield from walk(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from walk(item, f"{path}[{index}]")


@pytest.fixture
def clean_metrics():
    TWO_PASS_METRICS.reset()
    LEDGER_METRICS.reset()
    yield
    TWO_PASS_METRICS.reset()
    LEDGER_METRICS.reset()


def _run(pipeline: TwoPassPipeline, query: str, plan_id: str = "concise", *, record: bool = False, prior: list[str] = ()):
    turns = [LearnerTurn(f"message-{uuid4()}", text) for text in prior]
    resolved = resolve_turns(turns, LearnerTurn(f"message-{uuid4()}", query), package=pipeline.package)
    return pipeline.run(PipelineInput(resolved=resolved, lesson_slug=None, presentation=PresentationPlan(plan_id=plan_id, source="request"),
                                      response_id=f"shadow-{uuid4()}", delivery="shadow", shadowed_response_id=f"turn-{uuid4()}"), record=record)


def _document_sentences(store: CourseStore) -> list[tuple[str, str]]:
    return [
        (record.span_id, sentence)
        for record in store.span_registry.records
        if record.item_kind == "document"
        for sentence in sentences(record.text, min_words=PARAMS.min_sentence_words, max_chars=PARAMS.max_sentence_chars)
    ]


# ======================================================================================================== AC-3-1


def test_ac_3_1_the_retrieval_request_and_evidential_envelope_hold_only_allowlisted_fields():
    assert set(RetrievalRequest.model_fields) == {"text", "lesson_slug", "corpus_version"}
    assert set(EvidentialEnvelope.model_fields) == {"envelope_schema", "question", "corpus_version", "evidence", "instructions"}
    assert set(ResolvedQuestion.model_fields) == {"text", "resolver", "source_turn_ids", "contains_learner_state"}
    assert not (set(RetrievalRequest.model_fields) | set(EvidentialEnvelope.model_fields)) & set(LEARNER_STATE_FIELDS)
    request = {"text": "Why does routing depth matter?", "lesson_slug": None, "corpus_version": "corpus-x"}
    resolved = {"text": "q", "resolver": {"model_id": "thread-resolver-v1", "prompt_hash": "a" * 64}, "source_turn_ids": ["m1"]}
    envelope = {"question": "q", "corpus_version": "c", "evidence": [{"span_id": "span-" + "1" * 64, "text": "t"}],
                "instructions": {"rule_id": "r", "prompt_hash": "a" * 64, "max_claims": 3, "max_claims_per_span": 2, "min_sentence_words": 4}}
    RetrievalRequest(**request), ResolvedQuestion(**resolved), EvidentialEnvelope(**envelope)  # the clean shapes validate
    for field in LEARNER_STATE_FIELDS:
        for model, payload in ((RetrievalRequest, request), (EvidentialEnvelope, envelope), (ResolvedQuestion, resolved)):
            with pytest.raises(ValidationError):
                model(**{**payload, field: "learner state"})
        with pytest.raises(ValidationError):
            EvidentialEnvelope(**{**envelope, "instructions": {**envelope["instructions"], field: "x"}})
    with pytest.raises(ValidationError):
        ResolvedQuestion(**{**resolved, "contains_learner_state": True})


def test_ac_3_1_the_evidential_pass_takes_no_learner_input_and_imports_no_learner_module():
    import inspect

    from app.services import claim_gate
    from app.services.tutor_pipeline import bind, evidential, lock as lock_module, render, retrieve

    allowed = {"self", "resolved", "lesson_slug", "corpus_version", "engine", "request", "top_k", "registry", "query", "bundle", "store",
               "params", "envelope", "plan", "resolver", "drafts", "generator", "evidential_prompt_hash", "pedagogical_prompt_hash", "package",
               "rendered", "locked", "templates", "outcomes"}
    callables = [retrieve.build_request, retrieve.retrieve, RetrievalEngine.evidence, evidential.build_envelope, evidential.no_envelope_reason,
                 ExtractiveD19Generator.propose, bind.bind, lock_module.lock, claim_gate.check_subset]
    for function in callables:
        names = set(inspect.signature(function).parameters)
        assert names <= allowed, (function.__qualname__, names - allowed)
        assert "presentation" not in names and not (names & set(LEARNER_STATE_FIELDS)), function.__qualname__
    # The renderer is the only component that takes a PresentationPlan (plan 3.6). Phase 4: V1 may name locked claims for
    # it to leave out (omit_claim_ids; V1.6 and D-20), which is no learner input either.
    assert set(inspect.signature(TemplateRenderer.render).parameters) == {"self", "locked", "plan", "attempt", "omit_claim_ids"}
    forbidden = {"app.services.learner_record", "app.services.learner_progress", "app.services.learning_intelligence",
                 "app.services.microlearning", "app.core.auth", "app.services.answer_history", "app.services.retrieval_legacy_p1"}
    modules = list((API_ROOT / "app" / "services" / "tutor_pipeline").glob("*.py")) + [API_ROOT / "app" / "services" / "claim_gate.py"]
    assert len(modules) >= 14
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        bad = {name for name in imported if name in forbidden or name.startswith("app.api.routes")}
        assert not bad, (path.name, bad)
    assert {name for name in ("render",) if hasattr(render, "PEDAGOGICAL_PROMPT_HASH_INPUT")} == {"render"}


class _SpyAssistant(TeachingAssistantService):
    spy: SpyGenerator | None = None

    @property
    def pipeline(self):  # noqa: D401 - the spy generator wraps the extractive generator
        if getattr(self, "_spy_pipeline", None) is None:
            package = get_config_package(self.settings)
            type(self).spy = SpyGenerator(ExtractiveD19Generator(package))
            self._spy_pipeline = TwoPassPipeline(self.retrieval_engine, self.settings, generator=type(self).spy)
        return self._spy_pipeline


THREE_LEARNER_QUESTIONS = ["Why does routing depth matter?", "QUBO logistics", "What is the capital of France?", "quantum kernels for finance"]


def learner_independent(entry: dict) -> dict:
    """A shadow record without the fields that name its response, turn or messages: everything plan 7.8 invariant 1
    holds equal across learners (spec 18.12 J2)."""
    kept = {key: value for key, value in entry.items() if key not in ("response_id", "shadowed_response_id")}
    kept["claims"] = [{key: value for key, value in claim.items() if key != "response_id"} for claim in entry["claims"]]
    kept["resolved_question"] = {key: value for key, value in entry["resolved_question"].items() if key != "source_turn_ids"}
    return kept


def observe_three_learners(monkeypatch, *, assistant_class=None, prefix: str = "ac31", on_learner=None):
    """Plan 7.8 invariant 1's fixture: three learners (mastery 0.1, 0.5, 0.9, each with a note, a quiz attempt and
    markers in page_path and history) ask the same public-corpus questions. Per learner and question it records the
    retrieval call (request and top_k), the envelopes the generator was sent, the ClaimPlans it returned and the
    whole shadow record but its ids: the EvidenceBundle (every span field, the sufficiency, the threshold version,
    floor and margin), the locked claims and claim_set_hash, the decision, the abstention reason, the counts and the
    presentation (spec 18.12 J2). Returns (observed per learner, captured inputs, markers)."""
    assistant_class = assistant_class or _SpyAssistant
    monkeypatch.setattr(assistant_class, "spy", None)  # this run's spy only: the pipeline makes a new one on first use
    settings = Settings()
    orchestrator = orchestrator_for(settings, assistant_class=assistant_class)
    monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda: orchestrator)
    captured_requests: list[dict] = []
    real_retrieve = pipeline_module.retrieve
    monkeypatch.setattr(pipeline_module, "retrieve", lambda engine, request, **kw: captured_requests.append(
        {"request": request.model_dump(mode="json"), "top_k": kw.get("top_k")}) or real_retrieve(engine, request, **kw))
    legacy_calls: list[dict] = []
    real_search = RetrievalEngine.search
    monkeypatch.setattr(RetrievalEngine, "search", lambda self, query, lesson_slug=None, top_k=8, *, surface="search": legacy_calls.append(
        {"query": query, "lesson_slug": lesson_slug, "top_k": top_k}) or real_search(self, query, lesson_slug, top_k, surface=surface))
    markers, observed = [], []
    from app.services.v2_panel.cache import reset_process_cache

    for mastery in (0.1, 0.5, 0.9):
        if on_learner is not None:
            on_learner(mastery)
        # Each learner starts from a cold evidential cache: a record's V2 call and cache-hit counts are the process's
        # traffic history, not learner state (Phase 5 spec 4.15; AC-5-11 shares the cache across learners on purpose).
        reset_process_cache()
        headers = demo(f"{prefix}-{int(mastery * 10)}")
        marker = f"MARKER-{uuid4().hex}"
        markers.append(marker)
        seed_learner(headers["x-demo-user"], mastery, marker)
        per_learner = []
        for question in THREE_LEARNER_QUESTIONS:
            spy = assistant_class.spy
            start = len(spy.envelopes) if spy else 0
            response = chat(headers, question, page_path=f"/lessons/{marker}", history=[{"role": "user", "content": f"history {marker}"}])
            assert response.status_code == 200, response.text
            (shadow,) = records(shadowed_response_id=response.json()["turn_id"])
            entry = entry_of(shadow)
            spy = assistant_class.spy
            per_learner.append({
                "retrieve": captured_requests[-1],
                "envelopes": spy.envelopes[start:] if spy else [],
                "plans": spy.plans[start:] if spy else [],
                "record": learner_independent(entry),
            })
        observed.append(per_learner)
    spy = assistant_class.spy
    captured = {"requests": captured_requests, "envelopes": spy.envelopes if spy else [], "plans": spy.plans if spy else [], "legacy": legacy_calls}
    return observed, captured, markers


def test_ac_3_1_what_the_evidential_pass_receives_holds_zero_learner_state_under_three_learner_contexts(monkeypatch):
    observed, captured, markers = observe_three_learners(monkeypatch)
    # Invariant 1 (plan 7.8): identical retrieval request and top-k, envelopes, ClaimPlans, EvidenceBundle (threshold
    # and sufficiency included), locked claims, abstention decision and reason, counts and presentation.
    assert all(learner == observed[0] for learner in observed)
    assert any(item["envelopes"] and item["plans"] for item in observed[0])  # the evidential pass ran (not vacuous)
    assert any(item["record"]["decision"] == "abstain" for item in observed[0])  # an abstention is compared too
    assert all(len(item["envelopes"]) == len(item["plans"]) for item in observed[0])
    for _, key, value in walk(captured):
        assert key not in LEARNER_STATE_FIELDS, key
    serialised = json.dumps(captured)
    assert not any(marker in serialised for marker in markers)


def test_ac_3_1_post_tutor_turns_refuses_learner_state_fields():
    headers = demo("ac31-turns")
    for field, value in (("page_path", "/lessons/x"), ("history", [{"role": "user", "content": "x"}]), ("mastery", 0.9), ("user_id", "someone")):
        response = client.post("/tutor/turns", headers=fresh(headers), json={"message": "Why does routing depth matter?", field: value})
        assert response.status_code == 422, (field, response.text)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(TutorTurn).where(TutorTurn.user_id == headers["x-demo-user"])) == 0


# ======================================================================================================== AC-3-2


@pytest.mark.parametrize("gate", GATES)
@pytest.mark.parametrize("config", ["dev", "governed_empty", "all_public_approved"])
def test_ac_3_2_three_presentation_plans_give_the_same_claim_set_hash_and_span_set(config, gate):
    settings = settings_for(config, gate)
    store = store_for(config, gate)
    pipeline = TwoPassPipeline(RetrievalEngine(store, settings), settings)
    answered = 0
    for query in IN_DOMAIN[:40] + OFF_TOPIC[:10]:
        results = [_run(pipeline, query, plan_id) for plan_id in ("concise", "stepwise", "socratic")]
        assert len({result.locked.claim_set_hash for result in results}) == 1, query
        assert len({result.locked.span_ids for result in results}) == 1, query
        assert len({result.decision for result in results}) == 1, query
        assert [result.entry.presentation.plan_id for result in results if result.entry.presentation] == (
            ["concise", "stepwise", "socratic"] if results[0].decision == "answer" else [])
        if results[0].decision == "answer":
            answered += 1
            assert len({result.rendered.text for result in results}) == 3  # the plans really differ
    if config == "governed_empty":
        assert answered == 0  # D-31: nothing is quotable
    else:
        assert answered >= 25


def refuse_processes(monkeypatch) -> None:
    """Fail the test if anything starts a process (spec 18.10 H4): the record test and the committed-record check are
    said to run none, and the replay's only process is the informational commit, which the test supplies itself."""
    def refused(*args, **kwargs):
        raise AssertionError(f"a process was started: {args[:1]!r}")

    for owner, name in ((subprocess, "run"), (subprocess, "Popen"), (subprocess, "call"), (subprocess, "check_call"),
                        (subprocess, "check_output"), (os, "system"), (os, "popen")):
        monkeypatch.setattr(owner, name, refused)


def test_ac_3_2_the_replay_finds_no_mismatch_and_is_labelled_not_e3_or_lq1(tmp_path, monkeypatch):
    module = load_script("replay_tutor_plans")
    # Neither this test nor the committed-record check below runs a process (spec 18.9 G1, made true in 18.10 H4).
    refuse_processes(monkeypatch)
    report = module.compute(subset=60, commit_source=lambda: "0" * 40)
    assert report["commit"] == "0" * 40
    assert report["result"] == "pass" and all(configuration["mismatches"] == [] for configuration in report["configurations"])
    assert "NOT E3 or LQ-1" in report["evidence_class"] and report["public_corpus_only"] is True
    assert [(c["name"], c["gate"]) for c in report["configurations"]] == list(module.CONFIGURATIONS)
    regressions = module.regression_items()
    assert regressions and report["fixture"]["items"] == 60 and report["fixture"]["regressions"]["items"] == len(regressions)
    governed = report["configurations"][0]
    # The regression items are replayed in full beside the evenly spaced sample.
    assert governed["answered"] == 0 and governed["claim_set_hash_equal"] == governed["items"] == 60 + len(regressions)
    assert all(c["two_pass"]["bound_claim_ratio"] in (None, 1.0) for c in report["configurations"])
    assert all(c["answered_by_stratum"]["off_topic"] == c["answered_by_stratum"]["stopword_only"] == 0 for c in report["configurations"])
    # Review 2026-11-19: the overlapping-spans item answers once its two same-sentence claims merge.
    approved = report["configurations"][1]
    assert (approved["name"], approved["gate"]) == ("all_public_approved", "bm25f-v1")
    assert approved["answered_by_stratum"]["regression"] == len(regressions) and approved["two_pass"]["merged_claims"] >= 1
    assert "subset_check_failed" not in approved["abstention_by_reason"]
    serialised = json.dumps(report)
    assert not any(query in serialised for query in IN_DOMAIN + OFF_TOPIC if len(query) > 12)  # hashes only, never text
    assert not any(query in serialised for _, query in regressions)
    lqs = REPO_ROOT / "lqs" / "items.json"
    with pytest.raises(SystemExit, match="lqs"):
        module.fixture_items(lqs)
    # Spec 18.8 F2 (replacing the 18.7 E3 rule, which failed on main after the project's squash merges and never ran
    # in CI's shallow clone): the record names the code it replayed by content. The check is a function of its own so
    # that a real squash-merged repository runs exactly this check (18.9 G1, the next test but one).
    _, committed = _check_committed_replay_record()
    assert committed["config_package"]["sha256"] == PACKAGE.sha256
    listed = committed["inputs"]["files"]
    # This run imported at least what the record lists (it may import more: other tests share the process), with the
    # same text.
    assert {path: report["inputs"]["files"].get(path) for path in listed} == listed


REPLAY_RECORD = Path("docs") / "evaluation" / "phase3" / "three_plan_replay_v1.json"
# The package in force, which the replay record names (v3 since Phase 4).
PACKAGE_FILE = DEFAULT_PACKAGE_PATH.relative_to(REPO_ROOT)


def _check_committed_replay_record():
    """The committed replay record's provenance check (spec 18.8 F2, 18.9 G1) on the checkout at REPO_ROOT: the record
    names, by content, exactly the code checked out there. It asks git nothing, so it holds on the branch, on a
    squash-merged main that keeps the branch's objects and in a shallow clone alike. The squash-merge test runs this
    same function with REPO_ROOT, the loaded script and the working directory all in a real squash-merged repository.
    Returns the loaded script and the record."""
    module = load_script("replay_tutor_plans")
    committed = json.loads((REPO_ROOT / REPLAY_RECORD).read_text(encoding="utf-8"))
    package = json.loads((REPO_ROOT / PACKAGE_FILE).read_text(encoding="utf-8"))
    assert committed["result"] == "pass" and committed["config_package"]["sha256"] == canonical_sha256(package)
    # Every module the record lists has exactly the checked-out text, so the record can never describe code other
    # than what is checked out; --check (CI) compares the whole inputs block with a fresh run.
    problems = module.input_problems(committed["inputs"])
    assert problems == [], problems
    listed = committed["inputs"]["files"]
    # The two-pass pipeline's own modules (shadow.py schedules runs and package_check.py checks the package; the replay
    # needs neither).
    pipeline_modules = {f"apps/api/app/services/tutor_pipeline/{name}.py" for name in
                        ("bind", "contracts", "evidential", "lock", "pipeline", "render", "resolve", "retrieve", "text")}
    core = {module.SELF, "apps/api/app/services/contained_answers.py", "apps/api/app/services/retrieval_engine.py",
            "apps/api/app/core/config_package.py", "apps/api/app/services/claim_gate.py"} | pipeline_modules
    assert core <= set(listed), sorted(core - set(listed))
    # commit is informational: the HEAD the record was written on, + "-dirty" when written from a working tree.
    assert re.fullmatch(r"[0-9a-f]{40}(-dirty)?", committed["commit"]), committed["commit"]
    return module, committed


def test_ac_3_2_the_record_check_and_a_replay_with_its_own_commit_run_no_process(monkeypatch):
    # Spec 18.10 H4: spec 18.9 said the record check and the AC-3-2 record test run no process, but the test's
    # compute() ran git for the informational commit and the 18.9 scan saw only direct calls. The default commit is the
    # replay's only process (rev-parse and status, never a history question); a supplied commit source starts none.
    module = load_script("replay_tutor_plans")
    small = {"subset": 1, "configurations": (("governed_empty", "p1-floor"),), "regressions": None}
    started: list[list[str]] = []
    real_run = subprocess.run

    def spy(*args, **kwargs):
        started.append(list(args[0]))
        return real_run(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "run", spy)
        default = module.compute(**small)
    assert started and all(command[:2] in (["git", "rev-parse"], ["git", "status"]) for command in started), started
    assert re.fullmatch(r"([0-9a-f]{40}(-dirty)?|unknown)", default["commit"]), default["commit"]
    refuse_processes(monkeypatch)
    supplied = module.compute(**small, commit_source=lambda: "c" * 40)
    assert supplied["commit"] == "c" * 40 and supplied["result"] == "pass"
    _check_committed_replay_record()


def _squash_merged_main(tmp_path: Path) -> tuple[Path, str, int]:
    """A real git repository merged the way this project merges its pull requests (spec 18.9 G1): main; a branch with a
    code commit and then the replay record naming that commit; `git merge --squash` of the branch onto main, committed
    with one parent. The branch ref, and so every branch object, is kept, as on this workstation after every phase.
    Git runs with an empty global configuration and no system configuration.

    Returns the checkout, the commit the record names, and the exit code of `git merge-base --is-ancestor <that
    commit> HEAD`, the question the 18.7 E3 rule asked: it skipped on 128 (commit absent) and failed on 1."""
    root = tmp_path / "squashed"
    home = tmp_path / "git-home"
    root.mkdir()
    home.mkdir()
    (home / "gitconfig").write_text("", encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update({"HOME": str(home), "USERPROFILE": str(home), "XDG_CONFIG_HOME": str(home), "GIT_CONFIG_GLOBAL": str(home / "gitconfig"),
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"})

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=root, env=env, capture_output=True, text=True, timeout=60)

    def ok(*args: str) -> str:
        completed = git(*args)
        assert completed.returncode == 0, (args, completed.stdout, completed.stderr)
        return completed.stdout.strip()

    ok("init", "-q")
    ok("symbolic-ref", "HEAD", "refs/heads/main")
    (root / "MAIN.txt").write_text("main before the phase\n", encoding="utf-8")
    ok("add", "-A")
    ok("commit", "-q", "-m", "main before the phase")
    base = ok("rev-parse", "HEAD")
    ok("checkout", "-q", "-b", "phase")
    committed = json.loads((REPO_ROOT / REPLAY_RECORD).read_text(encoding="utf-8"))
    for relative in [*committed["inputs"]["files"], PACKAGE_FILE.as_posix()]:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPO_ROOT / relative).read_bytes().replace(b"\r\n", b"\n"))
    ok("add", "-A")
    ok("commit", "-q", "-m", "phase: code")
    code_commit = ok("rev-parse", "HEAD")
    (root / REPLAY_RECORD).parent.mkdir(parents=True, exist_ok=True)
    (root / REPLAY_RECORD).write_text(json.dumps({**committed, "commit": code_commit}, indent=1, ensure_ascii=False) + "\n",
                                      encoding="utf-8", newline="\n")
    ok("add", "-A")
    ok("commit", "-q", "-m", "phase: replay record")
    ok("checkout", "-q", "main")
    ok("merge", "--squash", "phase")
    ok("commit", "-q", "-m", "phase (#1)")
    # The shape the project's merges leave: one parent, the branch's tree, the branch's objects still present.
    assert ok("rev-list", "--parents", "-n", "1", "HEAD").split()[1:] == [base]
    assert ok("rev-parse", "HEAD^{tree}") == ok("rev-parse", "phase^{tree}")
    assert git("cat-file", "-e", code_commit + "^{commit}").returncode == 0
    return root, code_commit, git("merge-base", "--is-ancestor", code_commit, "HEAD").returncode


def test_ac_3_2_the_committed_record_check_passes_on_a_squash_merged_main_that_keeps_the_branch_objects(tmp_path, monkeypatch):
    # Spec 18.9 G1: a real squash merge, not a copied tree. The fixture holds the condition under which the 18.7 E3
    # rule failed on main: the commit the record names is present (exit 128 would mean absent, which that rule
    # skipped) and is not an ancestor of HEAD (exit 1).
    root, code_commit, ancestry = _squash_merged_main(tmp_path)
    assert ancestry == 1
    # Run the committed-record check of the AC-3-2 test inside the squashed checkout: REPO_ROOT, the script that
    # load_script loads (and so the script's own REPO_ROOT) and the working directory are all that checkout, so any
    # question about history the check asked would be asked of the squash-merged main, and fail there.
    monkeypatch.setattr(sys, "path", list(sys.path))  # the loaded script prepends its own roots
    monkeypatch.setitem(globals(), "REPO_ROOT", root)
    monkeypatch.chdir(root)
    module, committed = _check_committed_replay_record()
    assert Path(module.__file__).resolve() == (root / module.SELF).resolve() and module.REPO_ROOT == root.resolve()
    assert committed["commit"] == code_commit
    # The squash-merged main still refuses a stale record: a replayed module changed on main after the merge.
    first = sorted(committed["inputs"]["files"])[0]
    (root / first).write_bytes((root / first).read_bytes() + b"# changed on main after the merge\n")
    with pytest.raises(AssertionError, match="differs from the code the record replayed"):
        _check_committed_replay_record()


def test_ac_3_2_the_replay_inputs_check_needs_no_history_and_refuses_a_changed_or_missing_file(tmp_path):
    # Spec 18.8 F2 (renamed in 18.9 G1, which adds the real squash-merge test above): input_problems reads only file
    # contents. A copy of the listed files in a tree with no history passes; a changed, missing or unlisted-digest
    # file fails.
    module = load_script("replay_tutor_plans")
    committed = json.loads((REPO_ROOT / REPLAY_RECORD).read_text(encoding="utf-8"))
    inputs = committed["inputs"]
    assert inputs["rule"] == module.INPUTS_RULE == "imported-repository-modules-sha256-lf-v1"
    for relative in inputs["files"]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        # Another checkout may hold LF where this one holds CRLF (core.autocrlf): the digest reads both alike.
        target.write_bytes((REPO_ROOT / relative).read_bytes().replace(b"\r\n", b"\n"))
    assert module.input_problems(inputs, root=tmp_path) == []
    first = sorted(inputs["files"])[0]
    (tmp_path / first).write_bytes((tmp_path / first).read_bytes() + b"# changed\n")
    assert module.input_problems(inputs, root=tmp_path) == [f"{first} differs from the code the record replayed"]
    (tmp_path / first).unlink()
    assert module.input_problems(inputs, root=tmp_path) == [f"{first} is listed but missing"]
    assert "the inputs digest does not match its file map" in module.input_problems({**inputs, "sha256": "0" * 64})
    assert "unknown inputs rule 'x'" in module.input_problems({**inputs, "rule": "x"})


def test_ac_3_2_the_replay_record_names_its_commit_and_refuses_to_write_from_a_dirty_tree(monkeypatch, tmp_path):
    # Review 2026-11-19: the committed record named the pre-Phase-3 base commit, as it was written from an
    # uncommitted tree; a record now names HEAD only when the tree is clean.
    module = load_script("replay_tutor_plans")
    head = "a" * 40

    def git(status_stdout: str, status_code: int = 0):
        def fake(*args):
            if args[0] == "rev-parse":
                return subprocess.CompletedProcess(args, 0, head + "\n", "")
            return subprocess.CompletedProcess(args, status_code, status_stdout, "")
        return fake

    for stdout, code, expected in (("", 0, head), (" M scripts/replay_tutor_plans.py\n", 0, head + "-dirty"),
                                   ("?? apps/api/new_module.py\n", 0, head + "-dirty"), ("", 128, head + "-dirty")):
        monkeypatch.setattr(module, "_git", git(stdout, code))
        assert module._commit() == expected
    monkeypatch.setattr(module, "_git", git(" M apps/api/app/services/tutor_pipeline/bind.py\n"))
    monkeypatch.setattr(module, "compute", _raise("a dirty --write must be refused before the replay runs"))
    target = tmp_path / "record.json"
    assert module.main(["--write", str(target)]) == module.EXIT_DIRTY == 4 and not target.exists()


# ======================================================================================================== AC-3-3


def test_ac_3_3_every_factual_sentence_of_a_rendered_response_maps_to_a_locked_claim():
    settings = Settings()
    pipeline = TwoPassPipeline(RetrievalEngine(get_course_store(), settings), settings)
    checked = 0
    for query in IN_DOMAIN[:50]:
        for plan_id in ("concise", "stepwise", "socratic"):
            result = _run(pipeline, query, plan_id)
            if result.decision != "answer":
                continue
            check = check_subset(result.rendered, result.locked)
            assert check.passed and check.missing_claims == 0 and result.render_attempts == 1
            claim_segments = [segment for segment in result.rendered.segments if segment.kind == "claim"]
            locked_texts = {claim.claim_id: claim.text for claim in result.locked.claims}
            assert all(locked_texts[segment.claim_id] == segment.text for segment in claim_segments)  # verbatim locked text
            assert set(result.rendered.citations) <= set(result.locked.span_ids)
            checked += 1
    assert checked >= 75


def _random_locked(rng: random.Random, sentences: list[tuple[str, str]], store: CourseStore):
    from app.services.tutor_pipeline.bind import LockedClaimDraft, claim_id_for
    from app.services.tutor_pipeline.contracts import EvidenceBundle, EvidenceSpan, Sufficiency

    picks = rng.sample(sentences, rng.randint(1, 3))
    drafts, spans, seen = [], {}, set()
    for span_id, sentence in picks:
        if (sentence, span_id) in seen:
            continue
        seen.add((sentence, span_id))
        record = store.span_registry.get(span_id)
        drafts.append(LockedClaimDraft(claim_id=claim_id_for(sentence, [span_id]), text=sentence, span_ids=(span_id,),
                                       source_order=(record.item_id, record.start + max(0, record.text.find(sentence.split(" ", 1)[0])))))
        spans[span_id] = EvidenceSpan(span_id=span_id, item_id=record.item_id, item_version=record.item_version, kind="document", char_start=record.start,
                                      char_end=record.end, content_hash=record.content_hash, score=5.0, near_floor=False, license_class="public", quotable=True)
    drafts = list({draft.claim_id: draft for draft in drafts}.values())
    floor, margin, version = store.index.thresholds
    bundle = EvidenceBundle(corpus_version=store.corpus_version, index_version=store.index_version, retrieval_mode="lexical", spans=tuple(spans.values()),
                            sufficiency=Sufficiency(score=5.0, gate=store.gate, threshold_version=version, floor=floor, margin=margin, decision="answer",
                                                    reason="evidence"))
    return lock(drafts, bundle=bundle, generator=None, evidential_prompt_hash=None, pedagogical_prompt_hash=PARAMS.pedagogical_prompt_hash,
                resolver=contracts.ResolverRef(model_id="thread-resolver-v1", prompt_hash=PARAMS.resolver_prompt_hash), package=PACKAGE)


def test_ac_3_3_property_an_unmapped_sentence_regenerates_at_most_twice_then_abstains():
    rng = random.Random(20261119)
    store = get_course_store()
    sentences = _document_sentences(store)
    injected_modes: set[str] = set()
    placed_modes: set[str] = set()
    for trial in range(300):
        locked = _random_locked(rng, sentences, store)
        locked_texts = {claim.text for claim in locked.claims}
        outside_span, outside_sentence = next(item for item in (rng.choice(sentences) for _ in range(50)) if item[1] not in locked_texts)
        schedule = [rng.random() < 0.6 for _ in range(3)]
        renderer = FaultyRenderer(TemplateRenderer(), schedule, rng, outside_sentence=outside_sentence,
                                  outside_span_id=outside_span if outside_span not in locked.span_ids else "span-" + "9" * 64)
        plan = PresentationPlan(plan_id=rng.choice(("concise", "stepwise", "socratic")), source="request")
        rendered, attempts, reason = render_checked(renderer, locked, plan, max_regenerations=PARAMS.max_regenerations)
        injected_modes |= {mode for mode in renderer.injected if mode}
        placed_modes |= {mode for mode in renderer.placed if mode}
        first_clean = next((index + 1 for index, faulty in enumerate(schedule) if not faulty), None)
        if first_clean is None:
            assert (rendered, attempts, reason) == (None, 3, "subset_check_failed"), (trial, renderer.injected)
        else:
            assert rendered is not None and reason is None and attempts == first_clean, (trial, schedule, renderer.injected)
            assert check_subset(rendered, locked).passed
        assert attempts <= 1 + PARAMS.max_regenerations == 3
    assert injected_modes == set(FAULT_MODES)  # every failure mode was drawn (wrong_citation on one span falls back to invented)
    # ... and every one was placed as itself at least once, not only through a fallback (spec 18.11 I2).
    assert placed_modes >= set(FAULT_MODES), set(FAULT_MODES) - placed_modes


def _spy_subset_problems(monkeypatch) -> list[tuple[str, ...]]:
    """The problem codes of every subset check the pipeline runs (spec 18.11 I2)."""
    seen: list[tuple[str, ...]] = []

    def spy(rendered, locked):
        result = check_subset(rendered, locked)
        seen.append(result.problems)
        return result

    monkeypatch.setattr(pipeline_module, "check_subset", spy)
    return seen


@pytest.mark.parametrize("mode", FAULT_MODES)
def test_ac_3_3_a_renderer_that_adds_a_claim_a_citation_or_a_fact_in_a_connective_is_caught(mode, monkeypatch):
    settings = Settings()
    store = get_course_store()
    sentences = _document_sentences(store)
    engine = RetrievalEngine(store, settings)
    # Spec 18.11 I2: the graph-shrinking query locks one claim on one span since 18.10 H1, so wrong_citation fell back to
    # invented and undisplayed_citation left no claim line out. The several-claim query holds every fault as itself.
    query = MULTI_CLAIM
    baseline = _run(TwoPassPipeline(engine, settings), query)
    assert baseline.decision == "answer" and len(baseline.locked.claims) >= 2 and len(baseline.locked.span_ids) >= 2
    assert len({segment.line for segment in baseline.rendered.segments if segment.kind == "claim"}) >= 2
    seen = _spy_subset_problems(monkeypatch)
    always = FaultyRenderer(TemplateRenderer(), [True, True, True], random.Random(1), modes=(mode,), outside_sentence=sentences[-1][1],
                            outside_span_id="span-" + "9" * 64, exact=True)
    result = _run(TwoPassPipeline(engine, settings, renderer=always), query)
    assert (result.decision, result.abstention_reason, result.rendered, result.render_attempts) == ("abstain", "subset_check_failed", None, 3)
    assert result.entry.presentation.subset_check == "failed" and result.locked.claims  # the locked claims are kept, withheld
    # The named fault was placed as itself on every attempt, and the subset check refused it by the fault's own rule.
    assert always.placed == [mode, mode, mode] and len(seen) == 3, (always.placed, seen)
    assert all(FAULT_SIGNATURES[mode] in problems for problems in seen), seen
    if mode == "wrong_citation":  # a moved citation, not the invented claim it fell back to on one span
        assert all("unmapped_factual_sentence" not in problems for problems in seen), seen
    if mode == "undisplayed_citation":  # a claim line left out with its markers, the list kept: that rule alone
        assert seen == [("citation_list_mismatch",)] * 3, seen
    seen.clear()
    once = FaultyRenderer(TemplateRenderer(), [True, False], random.Random(1), modes=(mode,), outside_sentence=sentences[-1][1],
                          outside_span_id="span-" + "9" * 64, exact=True)
    recovered = _run(TwoPassPipeline(engine, settings, renderer=once), query)
    assert (recovered.decision, recovered.render_attempts) == ("answer", 2)
    assert once.placed == [mode, None] and FAULT_SIGNATURES[mode] in seen[0] and seen[1] == ()
    assert recovered.locked.claim_set_hash == result.locked.claim_set_hash == baseline.locked.claim_set_hash


def test_ac_3_3_the_overlap_gate_is_gone_and_claims_are_never_rebound():
    from app.services import claim_gate

    assert not hasattr(claim_gate, "ClaimGate") and not hasattr(claim_gate, "evidence_digest")
    settings = Settings()
    store = get_course_store()
    engine = RetrievalEngine(store, settings)
    # Spec 18.10 H1: a query with several whole-sentence spans (the graph-shrinking query now has one).
    query = "Explain why quantum logistics needs both problem reduction before execution and routing control during compilation."
    baseline = _run(TwoPassPipeline(engine, settings), query)
    assert baseline.decision == "answer" and len(baseline.envelope.evidence) >= 2

    def span_sentences(span) -> list[str]:
        return sentences(span.text, min_words=PARAMS.min_sentence_words, max_chars=PARAMS.max_sentence_chars)

    first, second, a_sentence = next(
        (x, y, s) for x in baseline.envelope.evidence for y in baseline.envelope.evidence if x.span_id != y.span_id
        for s in span_sentences(x) if s not in span_sentences(y)
    )
    whole = span_sentences(first)[-1]
    truncated = whole.split(", ")[0] + "." if ", " in whole else " ".join(whole.split()[:-2]) + "."
    outside = next(r for r in store.span_registry.records if r.item_kind == "document" and r.span_id not in {s.span_id for s in baseline.bundle.spans}
                   and sentences(r.text, min_words=4, max_chars=PARAMS.max_sentence_chars))
    scripted = ScriptedGenerator([[
        (a_sentence, (second.span_id,)),  # A's words citing B: dropped, never rebound to A
        (truncated, (first.span_id,)),  # a qualifying clause (or the last words) removed
        (sentences(outside.text, min_words=4, max_chars=PARAMS.max_sentence_chars)[0], (outside.span_id,)),  # outside the bundle
        (a_sentence, ()),  # unbound
        ("Quantum computers always beat classical routing.", (first.span_id,)),  # invented
    ]])
    result = _run(TwoPassPipeline(engine, settings, generator=scripted), query)
    assert (result.decision, result.abstention_reason) == ("abstain", "no_bound_claims")
    assert result.entry.counts.dropped == {"not_verbatim": 3, "outside_bundle": 1, "unbound": 1}
    assert result.locked.claims == () and result.entry.counts.bound_claims == 0
    malformed = _run(TwoPassPipeline(engine, settings, generator=ScriptedGenerator([{"plan_schema": "claim-plan-v1", "claims": [], "extra": 1}])), query)
    assert (malformed.decision, malformed.abstention_reason) == ("abstain", "claim_plan_invalid")


# ======================================================================================================== AC-3-4


def test_ac_3_4_every_delivered_tutor_response_has_a_ledger_record_and_the_chain_verifies():
    headers = demo("ac34")
    delivered = []
    for message in ("Why does routing depth matter?", "QUBO logistics", "What is the capital of France?", "quantum kernels for finance",
                    "How does graph shrinking reduce routing overhead?", "hello"):
        response = chat(headers, message)
        assert response.status_code == 200
        delivered.append(response.json())
    # Another learner for the /tutor/turns half: since spec 18.10 H5 both routes share one 8/minute window, and these
    # nine turns would exceed one learner's budget.
    second = demo("ac34t")
    for message, plan in (("Why does routing depth matter?", "stepwise"), ("What is the capital of France?", None), ("QUBO logistics", "socratic")):
        body = {"message": message, **({"presentation_plan": plan} if plan else {})}
        response = client.post("/tutor/turns", headers=fresh(second), json=body)
        assert response.status_code == 200 and response.json()["delivery"] == "legacy"
        delivered.append(response.json())
    assert {body["decision"] for body in delivered} == {"answer", "abstain"}
    for body in delivered:
        (record,) = records(response_id=body["turn_id"])
        entry = entry_of(record)
        assert (record.delivery, record.decision, record.shadowed_response_id) == ("legacy", body["decision"], None)
        assert entry["span_ids"] == sorted(citation["span_id"] for citation in body["citations"])
        assert entry["rendered_text_sha256"] == sha256_hex(body["answer"])
        assert [claim["text"] for claim in entry["claims"]] == [claim["text"] for claim in body["claims"]]
        assert entry["retrieval"]["evidence_scope"] == "retrieved"
        assert all(span["score"] is not None for span in entry["retrieval"]["evidence"])
        assert entry["verification"] is None and entry["provenance"]["v1_3_checker_model_id"] is None
        assert entry["versions"]["schema_revision_expected"] == SCHEMA_REVISION
        (shadow,) = records(shadowed_response_id=body["turn_id"])
        assert shadow.delivery == "shadow" and shadow.response_id.startswith("shadow-") and shadow.claim_set_hash
    with SessionLocal() as db:
        check = verify_response_ledger(db)
    assert check.ok, check.problems
    assert check.count >= 18 and check.head_row == (check.last_seq, check.head_hash)


def _thread_with_message(user_id: str, content: str) -> tuple[str, str]:
    with SessionLocal() as db:
        thread = TutorThread(id=f"thread-{uuid4()}", user_id=user_id, title="t")
        db.add(thread)
        db.flush()
        message = TutorMessage(id=f"message-{uuid4()}", thread_id=thread.id, role="user", content=content, created_at=datetime.now(UTC))
        db.add(message)
        db.commit()
        return thread.id, message.id


def _job(thread_id: str, message_id: str) -> ShadowJob:
    return ShadowJob(shadow_response_id=f"shadow-{uuid4()}", shadowed_response_id=f"turn-{uuid4()}", thread_id=thread_id, user_message_id=message_id,
                     lesson_slug=None, presentation=PresentationPlan(plan_id="concise", source="default"))


def test_ac_3_4_the_pipeline_refuses_delivered_mode_before_the_phase_4_exit(monkeypatch, clean_metrics):
    settings = Settings()
    pipeline = TwoPassPipeline(RetrievalEngine(get_course_store(), settings), settings)
    called, appended = [], []
    monkeypatch.setattr(pipeline_module, "retrieve", lambda *args, **kwargs: called.append(1))
    monkeypatch.setattr(pipeline_module, "append_ledger_entry", lambda *args, **kwargs: appended.append(1))
    resolved = resolve_turns([], LearnerTurn("m1", "Why does routing depth matter?"), package=PACKAGE)
    item = PipelineInput(resolved=resolved, lesson_slug=None, presentation=PresentationPlan(plan_id="concise", source="default"),
                         response_id=f"turn-{uuid4()}", delivery="delivered", shadowed_response_id="")  # type: ignore[arg-type]
    with pytest.raises(DeliveryNotImplemented):
        pipeline.run(item)
    assert called == [] and appended == []  # refused before any retrieval or append
    with pytest.raises(ValidationError, match="Phase 4"):
        make_entry(delivery="delivered")
    assert contracts.TWO_PASS_DELIVERY_IMPLEMENTED is False
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ResponseLedgerRecord).where(ResponseLedgerRecord.delivery == "delivered")) == 0
    # A ledger failure inside a shadow run reaches the runner, which counts it (plan L stop) and never raises.
    monkeypatch.undo()
    failing = FailingLedger()
    monkeypatch.setattr(pipeline_module, "append_ledger_entry", failing)
    thread_id, message_id = _thread_with_message(f"ac34-failing-{uuid4().hex[:8]}", "Why does routing depth matter?")
    run_shadow(_job(thread_id, message_id), pipeline_factory=lambda: TwoPassPipeline(RetrievalEngine(get_course_store(), settings), settings),
               settings=settings)
    assert failing.calls == 1
    assert TWO_PASS_METRICS.snapshot(1.0)["failed"]["ledger"] == 1
    snapshot = LEDGER_METRICS.snapshot()
    assert snapshot["failed"]["shadow"] == 1 and snapshot["write_stop"] is True


@contextmanager
def guards_lifted(engine: Engine):
    # Stand-in for an attacker with database rights: lift the triggers, then put them back.
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.exec_driver_sql("ALTER TABLE response_ledger DISABLE TRIGGER USER")
            connection.exec_driver_sql("ALTER TABLE response_ledger_head DISABLE TRIGGER USER")
        else:
            for name in RESPONSE_LEDGER_SQLITE_TRIGGERS:
                connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
    try:
        yield
    finally:
        if engine.dialect.name == "postgresql":
            with engine.begin() as connection:
                connection.exec_driver_sql("ALTER TABLE response_ledger ENABLE TRIGGER USER")
                connection.exec_driver_sql("ALTER TABLE response_ledger_head ENABLE TRIGGER USER")
        else:
            run_schema_upgrades(engine)


def _worker(database_url: str, *args: str) -> tuple[int, dict]:
    env = {**os.environ, "DATABASE_URL": database_url, "PYTHONUNBUFFERED": "1"}
    completed = subprocess.run([sys.executable, "-m", "app.workers.response_ledger", *args], cwd=API_ROOT, env=env, capture_output=True,
                               text=True, timeout=120)
    line = next(line for line in completed.stderr.splitlines() if '"job": "response_ledger"' in line)
    return completed.returncode, json.loads(line[line.index("{"):])


TAMPERS = {
    "edited_entry": ("UPDATE response_ledger SET entry = replace(entry, 'Routing adds', 'Routing removes') WHERE seq = 2",
                     "seq 2 entry does not match its entry_sha256"),
    "edited_record_hash": (f"UPDATE response_ledger SET record_hash = '{'f' * 64}' WHERE seq = 2", "seq 2 does not match its record_hash"),
    "edited_decision": ("UPDATE response_ledger SET decision = 'abstain' WHERE seq = 2", "seq 2 columns disagree with its entry"),
    "deleted_middle": ("DELETE FROM response_ledger WHERE seq = 2", "seq 2 to 2 missing"),
    "truncated_tail": ("DELETE FROM response_ledger WHERE seq = 4", "the chain head (seq 4) does not match the last record (seq 3)"),
    "forged_head": (None, "the chain no longer reaches the logged head seq 4"),
    "swapped_seq": (None, "seq 2 does not match its record_hash"),
    "unknown_schema": ("UPDATE response_ledger SET entry_schema = 'ledger-entry-v9' WHERE seq = 2", "seq 2 has an unknown entry_schema"),
}


@pytest.mark.parametrize("tamper", sorted(TAMPERS))
def test_ac_3_4_ledger_tamper_is_detected(tamper, fresh_database_url):
    factory, engine = fresh_sessions(fresh_database_url)
    verify = load_script("verify_ledger")
    try:
        for _ in range(4):
            append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
        with factory() as db:
            clean = verify_response_ledger(db)
        assert clean.ok and clean.count == 4
        assert verify.main(["--database-url", fresh_database_url]) == 0
        expected_head = None
        if tamper == "forged_head":
            returncode, report = _worker(fresh_database_url)  # the head the platform log keeps off the database
            assert returncode == 0
            expected_head = tuple(report["head_row"])
        statement, problem = TAMPERS[tamper]
        with guards_lifted(engine):
            with engine.begin() as connection:
                if tamper == "forged_head":
                    third = connection.execute(text("SELECT record_hash FROM response_ledger WHERE seq = 3")).scalar()
                    connection.execute(text("DELETE FROM response_ledger WHERE seq = 4"))
                    connection.execute(text("UPDATE response_ledger_head SET seq = 3, record_hash = :h"), {"h": third})
                elif tamper == "swapped_seq":
                    connection.execute(text("UPDATE response_ledger SET seq = 99 WHERE seq = 2"))
                    connection.execute(text("UPDATE response_ledger SET seq = 2 WHERE seq = 3"))
                    connection.execute(text("UPDATE response_ledger SET seq = 3 WHERE seq = 99"))
                else:
                    connection.execute(text(statement))
        with factory() as db:
            check = verify_response_ledger(db, expected_head=expected_head)
            assert not check.ok and problem in check.problems, check.problems
            if tamper == "forged_head":
                assert verify_response_ledger(db).ok  # internally consistent: only the logged head shows the rewrite
        args = ["--database-url", fresh_database_url] + (["--expect-head", f"{expected_head[0]}:{expected_head[1]}"] if expected_head else [])
        assert verify.main(args) == 1
        if tamper == "forged_head":
            returncode, report = _worker(fresh_database_url, "--expect-head", f"{expected_head[0]}:{expected_head[1]}")
            assert returncode == 1 and problem in report["problems"]
    finally:
        engine.dispose()


def test_ac_3_4_update_delete_and_truncate_are_refused_and_the_head_moves_forward_only(fresh_database_url):
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        appended = [append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000) for _ in range(2)]
        refused = [
            "UPDATE response_ledger SET decision = 'abstain' WHERE seq = 1",
            "DELETE FROM response_ledger WHERE seq = 2",
            "UPDATE response_ledger_head SET seq = 1",  # a rewind
            f"UPDATE response_ledger_head SET seq = 3, record_hash = '{'f' * 64}'",  # a head pointing at no record
            "DELETE FROM response_ledger_head",
        ]
        if engine.dialect.name == "postgresql":
            refused += ["TRUNCATE response_ledger", "TRUNCATE response_ledger_head"]
        for statement in refused:
            with factory() as db:
                with pytest.raises(DBAPIError) as raised:
                    db.execute(text(statement))
                db.rollback()
            message = str(raised.value)
            assert "append-only" in message or "forward only" in message, (statement, message)
        entry = make_entry()
        base = {"response_id": entry.response_id, "delivery": "legacy", "decision": "answer", "entry_schema": "ledger-entry-v1", "entry": "{}",
                "entry_sha256": "a" * 64, "record_hash": "b" * 64, "created_at": datetime.now(UTC)}
        for seq, prev in ((3, "c" * 64), (5, appended[-1].record_hash)):  # a wrong prev_hash, then a wrong seq
            with factory() as db:
                with pytest.raises(DBAPIError, match="extend the chain"):
                    db.execute(ResponseLedgerRecord.__table__.insert().values(seq=seq, prev_hash=prev, **base))
                db.rollback()
        if engine.dialect.name == "sqlite":
            with factory() as db:
                names = set(db.scalars(text("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name LIKE 'response_ledger%'")).all())
            assert names == set(RESPONSE_LEDGER_SQLITE_TRIGGERS)  # SQLite has no TRUNCATE; DELETE is refused instead
        with factory() as db:
            check = verify_response_ledger(db)
        assert check.ok and check.count == 2
    finally:
        engine.dispose()


def test_ac_3_4_appends_are_idempotent_on_response_id_and_a_changed_entry_is_refused(fresh_database_url):
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        entry = make_entry()
        first = append_ledger_entry(entry, session_factory=factory, budget_ms=5000)
        assert append_ledger_entry(entry, session_factory=factory, budget_ms=5000).duplicate is True
        with pytest.raises(ledger.LedgerConflict):
            append_ledger_entry(make_entry(entry.response_id, text="Another sentence entirely here."), session_factory=factory, budget_ms=5000)
        with factory() as db:
            assert verify_response_ledger(db).count == 1 and first.seq == 1
    finally:
        engine.dispose()


def test_ac_3_4_two_concurrent_appends_never_fork_the_chain(fresh_database_url):
    factory, engine = fresh_sessions(fresh_database_url)
    errors: list[BaseException] = []
    try:
        barrier = threading.Barrier(2)
        seqs: list[int] = []

        def racer() -> None:
            try:
                barrier.wait(timeout=30)
                seqs.append(append_ledger_entry(make_entry(), session_factory=factory, budget_ms=30000).seq)
            except BaseException as error:  # pragma: no cover - reported below
                errors.append(error)

        threads = [threading.Thread(target=racer) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        assert errors == [] and sorted(seqs) == [1, 2]

        def writer() -> None:
            try:
                for _ in range(10):
                    append_ledger_entry(make_entry(), session_factory=factory, budget_ms=30000)
            except BaseException as error:  # pragma: no cover - reported below
                errors.append(error)

        threads = [threading.Thread(target=writer) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        with factory() as db:
            check = verify_response_ledger(db)
        assert errors == []
        assert check.ok, check.problems
        assert (check.count, check.first_seq, check.last_seq) == (42, 1, 42)
    finally:
        engine.dispose()


def test_ac_3_4_ledger_rows_hold_no_learner_identifier_or_learner_text(caplog):
    headers = demo("ac34-privacy")
    marker = f"MARKER-{uuid4().hex}"
    with caplog.at_level(logging.INFO, logger="qcai.tutor"):
        first = chat(headers, f"Why does routing depth matter for {marker}?", page_path=f"/lessons/{marker}",
                     history=[{"role": "user", "content": marker}]).json()
        second = chat(headers, "Why?", thread_id=first["thread_id"]).json()
    turn_ids = [first["turn_id"], second["turn_id"]]
    rows = [row for turn_id in turn_ids for row in records(response_id=turn_id) + records(shadowed_response_id=turn_id)]
    assert len(rows) == 4
    for row in rows:
        stored = row.entry
        assert headers["x-demo-user"] not in stored and "@" not in stored and marker not in stored
        entry = entry_of(row)
        if entry["resolved_question"] is not None:
            assert set(entry["resolved_question"]) == {"resolver", "source_turn_ids", "contains_learner_state"}  # no text
    columns = {column["name"] for column in sa_inspect(session_engine).get_columns("response_ledger")}
    assert not [name for name in columns if any(word in name for word in ("user", "email", "learner", "guest", "account"))]
    tutor_records = [record for record in caplog.records if record.name == "qcai.tutor"]
    assert tutor_records
    for record in tutor_records:
        seen = record.getMessage() + json.dumps(getattr(record, "json_fields", {}), default=str)
        assert not any(prefix in seen for prefix in ("turn-", "shadow-", "thread-", "message-")), seen
        assert marker not in seen and headers["x-demo-user"] not in seen


def test_ac_3_4_erasure_leaves_ledger_rows_unlinkable():
    headers = demo("ac34-erasure")
    body = chat(headers, "Why does routing depth matter?").json()
    turn_id = body["turn_id"]
    assert client.get(f"/ledger/responses/{turn_id}", headers=headers).status_code == 200
    before = records(response_id=turn_id) + records(shadowed_response_id=turn_id)
    with SessionLocal() as db:
        erase_user(db, headers["x-demo-user"])
        db.commit()
        assert db.get(TutorTurn, turn_id) is None
        assert verify_response_ledger(db).ok
    after = records(response_id=turn_id) + records(shadowed_response_id=turn_id)
    assert [row.record_hash for row in after] == [row.record_hash for row in before] and len(after) == 2
    response = client.get(f"/ledger/responses/{turn_id}", headers=headers)
    assert (response.status_code, response.json()) == (404, {"detail": "Response not found."})


# ======================================================================================================== AC-3-5


def _user_message_ids(headers: dict[str, str], thread_id: str) -> list[str]:
    detail = client.get(f"/assistant/threads/{thread_id}", headers=headers).json()
    return [message["id"] for message in detail["messages"] if message["role"] == "user"]


def test_ac_3_5_a_follow_up_in_thread_a_references_only_thread_a_turns():
    learner, other = demo("ac35"), demo("ac35-other")
    a = chat(learner, "What is QUBO optimization in logistics?").json()
    b = chat(learner, "Explain routing depth under hardware constraints").json()
    chat(other, "Explain quantum kernels for finance")
    follow_up = chat(learner, "Why does it matter?", thread_id=a["thread_id"]).json()
    assert follow_up["thread_id"] == a["thread_id"] != b["thread_id"]
    a_messages = _user_message_ids(learner, a["thread_id"])
    b_messages = _user_message_ids(learner, b["thread_id"])
    (shadow,) = records(shadowed_response_id=follow_up["turn_id"])
    source = tuple(entry_of(shadow)["resolved_question"]["source_turn_ids"])
    assert source == (a_messages[0], a_messages[1])
    assert set(source) <= set(a_messages) and not set(source) & set(b_messages)
    with SessionLocal() as db:
        resolved = resolve_thread(db, a["thread_id"], a_messages[1], package=PACKAGE)
    assert resolved.text == "What is QUBO optimization in logistics?\nWhy does it matter?"
    assert "routing depth" not in resolved.text and resolved.source_turn_ids == source


def test_ac_3_5_the_resolver_reads_only_the_learners_own_user_turns():
    learner = demo("ac35-own")
    first = chat(learner, "What is QUBO optimization in logistics?").json()
    # A client-supplied history naming other text never contributes; nor does the assistant reply.
    follow = chat(learner, "Why?", thread_id=first["thread_id"], history=[{"role": "user", "content": "Explain routing depth under hardware constraints"},
                                                                          {"role": "assistant", "content": "Routing depth matters."}]).json()
    (shadow,) = records(shadowed_response_id=follow["turn_id"])
    user_ids = _user_message_ids(learner, first["thread_id"])
    assert tuple(entry_of(shadow)["resolved_question"]["source_turn_ids"]) == (user_ids[0], user_ids[1])
    other = chat(demo("ac35-else"), "Explain quantum kernels for finance").json()
    with SessionLocal() as db:
        assistant_id = db.scalar(select(TutorMessage.id).where(TutorMessage.thread_id == first["thread_id"], TutorMessage.role == "assistant"))
        with pytest.raises(ResolverInputError):
            resolve_thread(db, first["thread_id"], assistant_id, package=PACKAGE)
        with pytest.raises(ResolverInputError):
            resolve_thread(db, other["thread_id"], user_ids[0], package=PACKAGE)


def test_ac_3_5_the_resolver_is_deterministic_and_not_a_word_count_rule():
    anchor = LearnerTurn("m-anchor", "What is QUBO optimization in logistics?")
    assert resolve_turns([anchor], LearnerTurn("m-1", "How does QUBO routing work under noise?"), package=PACKAGE).source_turn_ids == ("m-1",)
    for follow_up in ("Why?", "And for finance?"):
        assert resolve_turns([anchor], LearnerTurn("m-2", follow_up), package=PACKAGE).source_turn_ids == ("m-anchor", "m-2")
    fillers = [LearnerTurn(f"m-f{index}", "ok") for index in range(4)]
    assert resolve_turns([anchor, *fillers], LearnerTurn("m-3", "Why?"), package=PACKAGE).source_turn_ids == ("m-3",)
    runs = {resolve_turns([anchor], LearnerTurn("m-2", "Why?"), package=PACKAGE) for _ in range(5)}
    assert len(runs) == 1
    assert PARAMS.resolver_prompt_hash == next(iter(runs)).resolver.prompt_hash


# ======================================================================================================== AC-3-6


def _startup(database_url: str, extra_env: dict[str, str]) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": database_url, "ENVIRONMENT": "development", "PYTHONUNBUFFERED": "1", **extra_env}
    return subprocess.run([sys.executable, "-c", "from app.main import _initialize_database; _initialize_database()"],
                          cwd=API_ROOT, env=env, capture_output=True, text=True, timeout=180)


def test_ac_3_6_settings_refuse_two_pass_tutor_on_before_the_phase_4_exit(fresh_database_url):
    for environment in ("development", "production"):
        with pytest.raises(ValidationError, match="phase4_exit_passed"):
            Settings(environment=environment, two_pass_tutor="on")
    assert Settings(environment="production").two_pass_tutor == "off" and Settings().two_pass_tutor == "shadow"
    assert Settings(environment="production").tutor_turns_route_enabled is False
    completed = _startup(fresh_database_url, {"TWO_PASS_TUTOR": "on"})
    assert completed.returncode != 0 and "phase4_exit_passed" in completed.stderr
    probe = create_engine(fresh_database_url)
    try:
        assert set(sa_inspect(probe).get_table_names()) == set()  # nothing started, no table touched
    finally:
        probe.dispose()


def _counts(user_id: str) -> tuple[int, int, int]:
    with SessionLocal() as db:
        threads = select(TutorThread.id).where(TutorThread.user_id == user_id)
        return (
            db.scalar(select(func.count()).select_from(TutorMessage).where(TutorMessage.thread_id.in_(threads))),
            db.scalar(select(func.count()).select_from(TutorTurn).where(TutorTurn.user_id == user_id)),
            db.scalar(select(func.count()).select_from(QAInteraction).where(QAInteraction.user_id == user_id)),
        )


PEDAGOGICAL_STRINGS = [template for _, template in TEMPLATES.values() if "{" not in template]


def test_ac_3_6_in_shadow_the_learner_response_is_byte_identical_to_the_legacy_contained_answer_and_a_shadow_record_exists(monkeypatch):
    modes = {"off": orchestrator_for(Settings(two_pass_tutor="off")), "shadow": orchestrator_for(Settings())}
    questions = ["Why does routing depth matter?", "QUBO logistics", "What is the capital of France?", "quantum kernels for finance",
                 "How does graph shrinking reduce routing overhead?", "hello", "What is QUBO optimization in logistics?"]
    observed: dict[str, list] = {"off": [], "shadow": []}
    for mode, orchestrator in modes.items():
        monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda orchestrator=orchestrator: orchestrator)
        for question in questions + ["FOLLOW-UP"]:
            headers = demo(f"ac36-{mode}")
            if question == "FOLLOW-UP":
                anchor = chat(headers, "What is QUBO optimization in logistics?").json()
                response = chat(headers, "Why does it matter?", thread_id=anchor["thread_id"])
            else:
                response = chat(headers, question)
            assert response.status_code == 200
            body = response.json()
            with SessionLocal() as db:
                stored = db.scalars(select(TutorMessage.content).where(TutorMessage.thread_id == body["thread_id"], TutorMessage.role == "assistant")
                                    .order_by(TutorMessage.created_at.desc())).first()
                qa = db.scalars(select(QAInteraction.answer).where(QAInteraction.user_id == headers["x-demo-user"]).order_by(QAInteraction.id.desc())).first()
            assert stored == body["answer"] == qa
            assert len(records(shadowed_response_id=body["turn_id"])) == (1 if mode == "shadow" else 0)
            detail = client.get(f"/assistant/threads/{body['thread_id']}", headers=headers).text
            history = client.get("/qa/history", headers=headers).text
            for surface in (response.text, detail, history):
                assert not any(template in surface for template in PEDAGOGICAL_STRINGS)
            observed[mode].append((ledger_canonical(without_ids(body)), {name: response.headers.get(name) for name in HEADER_SUBSET},
                                   _counts(headers["x-demo-user"])))
    assert observed["off"] == observed["shadow"]


def _guest() -> tuple[TestClient, dict[str, str]]:
    guest_id = f"guest-{uuid4().hex}"
    issued = int(time.time())
    browser = TestClient(app)
    browser.cookies.set(GUEST_TOKEN_COOKIE, issue_guest_token(DEVELOPMENT_GUEST_TOKEN_SECRET, guest_id, issued))
    return browser, {"origin": TRUSTED_ORIGIN, "x-qcai-csrf": guest_csrf_for(DEVELOPMENT_GUEST_TOKEN_SECRET, guest_id, issued),
                     "x-forwarded-for": f"phase3-{uuid4().hex}"}


def test_ac_3_6_a_learner_never_reads_a_shadow_record_and_a_reviewer_read_is_logged():
    owner, other, reviewer = demo("ac36-owner"), demo("ac36-other"), demo("ac36-reviewer", role="reviewer")
    body = chat(owner, "Why does routing depth matter?").json()
    (shadow,) = records(shadowed_response_id=body["turn_id"])
    missing = client.get(f"/ledger/responses/shadow-{uuid4()}", headers=owner)
    as_owner = client.get(f"/ledger/responses/{shadow.response_id}", headers=owner)
    assert (as_owner.status_code, as_owner.json(), as_owner.headers["cache-control"]) == (404, missing.json(), "no-store")
    own = client.get(f"/ledger/responses/{body['turn_id']}", headers=owner)
    assert own.status_code == 200 and own.headers["cache-control"] == "no-store"
    own_body = own.json()
    assert (own_body["verdict"], own_body["recorded"], own_body["legacy_turn"]) == ("no-verdict", True, False)
    assert all(own_body["record"][field] is None for field in ("seq", "prev_hash", "record_hash", "entry_sha256", "shadowed_response_id"))
    assert own_body["record"]["delivery"] == "legacy"
    assert client.get(f"/ledger/responses/{body['turn_id']}", headers=other).status_code == 404
    with SessionLocal() as db:
        start = db.scalar(select(func.max(SecurityEvent.seq))) or 0
    as_reviewer = client.get(f"/ledger/responses/{shadow.response_id}", headers=reviewer)
    assert as_reviewer.status_code == 200
    record = as_reviewer.json()["record"]
    assert (record["delivery"], record["shadowed_response_id"], record["seq"], record["record_hash"]) == (
        "shadow", body["turn_id"], shadow.seq, shadow.record_hash)
    with SessionLocal() as db:
        events = db.scalars(select(SecurityEvent).where(SecurityEvent.seq > start, SecurityEvent.event_type == "ledger.reviewer_read")
                            .order_by(SecurityEvent.seq)).all()
    assert len(events) == 1 and events[0].details == {"route": "/ledger/responses/{response_id}", "delivery": "shadow"}
    assert events[0].actor_role == "reviewer" and events[0].subject_digest and reviewer["x-demo-user"] not in json.dumps(events[0].details)
    # A guest owner reads their own record; a guest who is not the owner gets the missing-id 404.
    guest, guest_headers = _guest()
    guest_turn = guest.post("/assistant/chat", headers=guest_headers, json={"message": "Why does routing depth matter?"}).json()["turn_id"]
    assert guest.get(f"/ledger/responses/{guest_turn}").status_code == 200
    assert guest.get(f"/ledger/responses/{body['turn_id']}").status_code == 404


def test_ac_3_6_on_forced_past_settings_still_runs_shadow_only(tmp_path, monkeypatch, caplog):
    package_dir = tmp_path / "package"
    shutil.copytree(DEFAULT_PACKAGE_PATH.parent / "schemas", package_dir / "schemas")
    payload = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
    payload["flag_policy"].update(phase4_exit_passed=True, phase4_exit_evidence="test-only")
    # A copy of the shipped package (v3 since Phase 4) under its own name and sidecar.
    (package_dir / DEFAULT_PACKAGE_PATH.name).write_text(json.dumps(payload), encoding="utf-8")
    (package_dir / f"{DEFAULT_PACKAGE_PATH.name}.sha256").write_text(canonical_sha256(payload) + "\n", encoding="utf-8")
    forced = Settings(two_pass_tutor="on", config_package_path=str(package_dir / DEFAULT_PACKAGE_PATH.name))
    assert forced.two_pass_tutor == "on"
    monkeypatch.setattr(shadow_module, "_ON_DOWNGRADE_LOGGED", False)
    results = {}
    for mode, settings in (("off", Settings(two_pass_tutor="off")), ("on", forced)):
        orchestrator = orchestrator_for(settings)
        monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda orchestrator=orchestrator: orchestrator)
        with caplog.at_level(logging.WARNING, logger="qcai.tutor"):
            response = chat(demo(f"ac36-forced-{mode}"), "Why does routing depth matter?")
        assert response.status_code == 200
        results[mode] = (response.json(), {name: response.headers.get(name) for name in HEADER_SUBSET})
    assert ledger_canonical(without_ids(results["on"][0])) == ledger_canonical(without_ids(results["off"][0]))
    assert results["on"][1] == results["off"][1]
    turn_id = results["on"][0]["turn_id"]
    assert [row.delivery for row in records(shadowed_response_id=turn_id)] == ["shadow"]
    assert [row.delivery for row in records(response_id=turn_id)] == ["legacy"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ResponseLedgerRecord).where(ResponseLedgerRecord.delivery == "delivered")) == 0
    assert any(getattr(record, "json_fields", {}).get("event") == "tutor.two_pass.on_downgraded" for record in caplog.records)
    assert effective_mode(forced, get_config_package(forced)) == "shadow"


def test_ac_3_6_the_tutor_turns_route_is_404_outside_development(monkeypatch):
    production = Settings(environment="production")
    monkeypatch.setattr(tutor_route, "get_settings", lambda: production)
    headers = demo("ac36-route")
    with SessionLocal() as db:
        ledger_before = db.scalar(select(func.count()).select_from(ResponseLedgerRecord))
    response = client.post("/tutor/turns", headers=headers, json={"message": "Why does routing depth matter?"})
    assert (response.status_code, response.json(), response.headers["cache-control"]) == (404, {"detail": "Not Found"}, "no-store")
    assert _counts(headers["x-demo-user"]) == (0, 0, 0)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ResponseLedgerRecord)) == ledger_before
    app.dependency_overrides[get_settings] = lambda: Settings(environment="development", enable_demo_auth=False, allowed_origins=[TRUSTED_ORIGIN])
    try:
        assert TestClient(app).post("/tutor/turns", headers=anonymous(), json={"message": "Why?"}).status_code == 401
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_ac_3_6_flag_combinations_never_deliver_two_pass_output(monkeypatch):
    combinations = 0
    for environment in ("development", "production"):
        for mode in (None, "off", "shadow", "on"):
            for ledger_enabled in (True, False):
                for panel in (None, True, False):
                    for route in (None, True, False):
                        kwargs = {"environment": environment, "tutor_ledger_enabled": ledger_enabled, "evidence_panel_enabled": panel,
                                  "ledger_route_enabled": route}
                        if mode is not None:
                            kwargs["two_pass_tutor"] = mode
                        if mode == "on":
                            with pytest.raises(ValidationError):
                                Settings(**kwargs)
                            continue
                        settings = Settings(**kwargs)
                        combinations += 1
                        effective = effective_mode(settings, get_config_package(settings))
                        assert effective in {"off", "shadow"}
                        if environment != "development":
                            assert settings.tutor_turns_route_enabled is False and settings.two_pass_tutor == (mode or "off")
                        if not ledger_enabled:
                            assert effective == "off"
    assert combinations == 2 * 3 * 2 * 3 * 3
    calls: list[str] = []
    real_run = TwoPassPipeline.run
    monkeypatch.setattr(TwoPassPipeline, "run", lambda self, item, **kw: calls.append(item.delivery) or real_run(self, item, **kw))
    for settings in (Settings(two_pass_tutor="off"), Settings()):
        orchestrator = orchestrator_for(settings)
        monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda orchestrator=orchestrator: orchestrator)
        assert chat(demo("ac36-flags"), "Why does routing depth matter?").status_code == 200
    assert calls == ["shadow"]
    for path in (API_ROOT / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "delivery" and isinstance(node.value, ast.Constant):
                assert node.value.value != "delivered", path


# ================================================================================================ Plan L, I, G, H


class _SlowGenerator:
    def __init__(self, inner):
        self.inner, self.ref = inner, inner.ref

    def propose(self, envelope):
        time.sleep(0.3)
        return self.inner.propose(envelope)


class _SlowAssistant(TeachingAssistantService):
    @property
    def pipeline(self):
        return TwoPassPipeline(self.retrieval_engine, self.settings, generator=_SlowGenerator(ExtractiveD19Generator(get_config_package(self.settings))))


def _raise(message: str):
    def raiser(*args, **kwargs):
        raise RuntimeError(message)

    return raiser


FAILURES = ("pipeline", "shadow_append", "budget", "legacy_append", "prepare")


@pytest.mark.parametrize("failure", FAILURES)
def test_plan_l_a_shadow_or_ledger_failure_never_changes_the_learner_response_and_is_counted(failure, monkeypatch, caplog, clean_metrics):
    off = orchestrator_for(Settings(two_pass_tutor="off"))
    monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda: off)
    reference = chat(demo("planl-ref"), "Why does routing depth matter?")
    TWO_PASS_METRICS.reset()
    LEDGER_METRICS.reset()
    if failure == "budget":
        orchestrator = orchestrator_for(Settings(two_pass_shadow_budget_ms=100), assistant_class=_SlowAssistant)
    else:
        orchestrator = orchestrator_for(Settings())
    monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda: orchestrator)
    if failure == "pipeline":
        monkeypatch.setattr(TwoPassPipeline, "run", _raise("pipeline fault (test)"))
    elif failure == "shadow_append":
        monkeypatch.setattr(pipeline_module, "append_ledger_entry", FailingLedger())
    elif failure == "legacy_append":
        monkeypatch.setattr(ledger, "append_ledger_entry", FailingLedger())
    elif failure == "prepare":
        monkeypatch.setattr(TutorOrchestrator, "_legacy_delivery", _raise("prepare fault (test)"))
    with caplog.at_level(logging.INFO, logger="qcai.tutor"):
        response = chat(demo("planl"), "Why does routing depth matter?")
    assert response.status_code == 200
    assert ledger_canonical(without_ids(response.json())) == ledger_canonical(without_ids(reference.json()))
    # A legacy failure line also names its attempt (spec 18.8 F11); the fields compared below are the same as before.
    events = [{key: value for key, value in getattr(record, "json_fields", {}).items() if key != "attempt"} for record in caplog.records]
    slis = client.get("/ready").json()["slis"]
    # Public /ready carries no shadow field that changes with a run's outcome (review rounds 3 and 4, spec 18.6 D9 and
    # 18.7 E15) and only the legacy ledger counts; the per-run detail is the in-process snapshots (and each run's log
    # lines). The failures below are read there; the public blocks are compared with their public snapshots.
    assert set(slis["two_pass_shadow"]) == {"scheduled", "phase2_bound_claim_ratio_baseline"}
    shadow_slis, ledger_slis = TWO_PASS_METRICS.snapshot(PARAMS.phase2_bound_claim_ratio), LEDGER_METRICS.snapshot()
    assert {key: shadow_slis[key] for key in slis["two_pass_shadow"]} == slis["two_pass_shadow"]
    public_ledger = slis["tutor_ledger"]
    assert {key: value for key, value in public_ledger.items() if key != "non_public_spans_excluded"} == LEDGER_METRICS.public_snapshot()
    if failure == "pipeline":
        assert shadow_slis["failed"]["pipeline"] == 1
        assert {"event": "tutor.two_pass.shadow_failed", "step": "pipeline", "error": "RuntimeError"} in events
    elif failure == "shadow_append":
        assert shadow_slis["failed"]["ledger"] == 1 and ledger_slis["failed"]["shadow"] == 1 and ledger_slis["write_stop"] is True
        assert any(event.get("event") == "tutor.ledger.append_failed" and event.get("delivery") == "shadow" for event in events)
        # The stop is logged (and alerted on), but a learner reading public /ready cannot see their shadow's append fail.
        assert public_ledger["write_stop"] is False and set(public_ledger["failed"]) == {"legacy"}
    elif failure == "budget":
        assert shadow_slis["budget_exceeded"] == 1 and shadow_slis["abstention_by_reason"] == {"budget_exceeded": 1}
        assert any(event.get("event") == "tutor.two_pass.budget_exceeded" for event in events)
        (shadow,) = records(shadowed_response_id=response.json()["turn_id"])
        assert entry_of(shadow)["abstention_reason"] == "budget_exceeded"
        # Review 2026-11-19: a latency event is never a plan L binding stop, and the record's counts reconcile.
        counts = entry_of(shadow)["counts"]
        assert counts["proposed_claims"] == counts["bound_claims"] + sum(counts["dropped"].values())
        assert shadow_slis["bound_claim_ratio_stop"] is False and shadow_slis["bound_claims"] == shadow_slis["proposed_claims"]
    else:
        assert ledger_slis["failed"]["legacy"] == 1 and ledger_slis["write_stop"] is True and public_ledger["write_stop"] is True
        assert ledger_slis["legacy_coverage_rate"] == 0.0 == public_ledger["legacy_coverage_rate"]
        stage = "prepare" if failure == "prepare" else "append"
        assert {"event": "tutor.ledger.append_failed", "delivery": "legacy", "stage": stage, "error": "RuntimeError"} in events
        assert records(response_id=response.json()["turn_id"]) == []


def test_plan_l_flag_off_restores_the_labelled_legacy_path(monkeypatch):
    orchestrator = orchestrator_for(Settings(two_pass_tutor="off"))
    monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda: orchestrator)
    body = chat(demo("planl-off"), "Why does routing depth matter?").json()
    assert records(shadowed_response_id=body["turn_id"]) == []
    assert [row.delivery for row in records(response_id=body["turn_id"])] == ["legacy"]
    assert body["evidence"]["labels"] == ["lexically_screened"] and body["grounded"] is False


def _three_bound_one_unbound(package):
    def script(envelope):
        span = envelope.evidence[0]
        picked = sentences(span.text, min_words=PARAMS.min_sentence_words, max_chars=PARAMS.max_sentence_chars)[:3]
        return [(sentence, (span.span_id,)) for sentence in picked] + [(picked[0], ())]

    return ScriptedGenerator([script])


def test_plan_l_the_bound_claim_ratio_is_reported_and_a_drop_below_phase_2_is_a_stop(clean_metrics):
    empty = TwoPassMetrics().snapshot(1.0)
    assert (empty["bound_claim_ratio"], empty["bound_claim_ratio_stop"]) == (None, False)  # a null ratio is never a stop
    chat(demo("planl-ratio"), "Why does routing depth matter?")
    public = client.get("/ready").json()["slis"]["two_pass_shadow"]
    # Review round 4 (spec 18.7 E15): the stop flag left public /ready with the other per-run outcomes; the stop is
    # read from the in-process snapshot here and from the log-based ratio in production (observability.md).
    assert public["phase2_bound_claim_ratio_baseline"] == 1.0 and not {"bound_claim_ratio", "bound_claim_ratio_stop"} & set(public)
    healthy = TWO_PASS_METRICS.snapshot(PARAMS.phase2_bound_claim_ratio)
    assert (healthy["bound_claim_ratio"], healthy["bound_claim_ratio_stop"], healthy["phase2_bound_claim_ratio_baseline"]) == (1.0, False, 1.0)
    settings = Settings()
    TWO_PASS_METRICS.reset()
    thread_id, message_id = _thread_with_message(f"planl-{uuid4().hex[:8]}", "Why does routing depth matter?")
    run_shadow(_job(thread_id, message_id), settings=settings, pipeline_factory=lambda: TwoPassPipeline(
        RetrievalEngine(get_course_store(), settings), settings, generator=_three_bound_one_unbound(PACKAGE)))
    stopped = TWO_PASS_METRICS.snapshot(PARAMS.phase2_bound_claim_ratio)
    assert stopped["bound_claim_ratio"] < 1.0 and stopped["bound_claim_ratio_stop"] is True
    module = load_script("replay_tutor_plans")
    report = module.compute(subset=30, generator_factory=_three_bound_one_unbound)
    assert report["result"] == "stop" and module.exit_code(report) == module.EXIT_STOP == 3
    assert report["configurations"][0]["stop"] is False and report["configurations"][0]["two_pass"]["bound_claim_ratio"] is None


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _ClockedGenerator:
    """Moves the pipeline's clock on by 10 s while it proposes: the budget runs out after the generator returns."""

    def __init__(self, inner, clock: _FakeClock) -> None:
        self.inner, self.ref, self.clock = inner, inner.ref, clock

    def propose(self, envelope):
        self.clock.now += 10.0
        return self.inner.propose(envelope)


def test_plan_l_a_budget_overrun_after_generation_is_a_latency_event_not_a_bound_claim_stop(clean_metrics, caplog):
    # Review 2026-11-19: claims the generator proposed but bind never saw were counted as proposed and not bound, so
    # the bound-claim ratio read 0.0 and the plan L stop latched for the life of the process.
    settings = Settings()
    clock = _FakeClock()
    thread_id, message_id = _thread_with_message(f"planl-budget-{uuid4().hex[:8]}", "Why does routing depth matter?")
    job = _job(thread_id, message_id)
    with caplog.at_level(logging.WARNING, logger="qcai.tutor"):
        run_shadow(job, settings=settings, pipeline_factory=lambda: TwoPassPipeline(
            RetrievalEngine(get_course_store(), settings), settings, generator=_ClockedGenerator(ExtractiveD19Generator(PACKAGE), clock), clock=clock))
    steps = [record.json_fields.get("step") for record in caplog.records if getattr(record, "json_fields", {}).get("event") == "tutor.two_pass.budget_exceeded"]
    assert steps == ["generate"]
    (shadow,) = records(response_id=job.shadow_response_id)
    entry = entry_of(shadow)
    proposed = entry["counts"]["proposed_claims"]
    assert proposed > 0 and entry["abstention_reason"] == "budget_exceeded" and entry["claims"] == []
    assert entry["counts"] == {"proposed_claims": proposed, "bound_claims": 0, "dropped": {"budget_exceeded": proposed}, "render_attempts": 0}
    snapshot = TWO_PASS_METRICS.snapshot(PARAMS.phase2_bound_claim_ratio)
    assert (snapshot["budget_exceeded"], snapshot["abstention_by_reason"]) == (1, {"budget_exceeded": 1})
    assert (snapshot["proposed_claims"], snapshot["bound_claims"], snapshot["bound_claim_ratio"], snapshot["bound_claim_ratio_stop"]) == (0, 0, None, False)
    # A healthy run afterwards reports the true ratio, and the stop stays clear.
    thread_id, message_id = _thread_with_message(f"planl-budget-{uuid4().hex[:8]}", "Why does routing depth matter?")
    run_shadow(_job(thread_id, message_id), settings=settings, pipeline_factory=lambda: TwoPassPipeline(RetrievalEngine(get_course_store(), settings), settings))
    snapshot = TWO_PASS_METRICS.snapshot(PARAMS.phase2_bound_claim_ratio)
    assert snapshot["proposed_claims"] > 0 and (snapshot["bound_claim_ratio"], snapshot["bound_claim_ratio_stop"]) == (1.0, False)
    # The ledger contract itself refuses counts that do not reconcile.
    with pytest.raises(ValidationError, match="proposed_claims"):
        contracts.PipelineCounts(proposed_claims=proposed, bound_claims=0, dropped={}, render_attempts=0)


def test_ac_3_3_a_sentence_in_two_overlapping_spans_is_one_claim_and_the_honest_rendering_passes():
    # Review 2026-11-19: on the real public corpus this query abstained with subset_check_failed after three renders.
    (query,) = [item["query"] for item in json.loads((DATA / "phase3_replay_regressions.json").read_text(encoding="utf-8"))["items"]]
    settings = Settings()
    pipeline = TwoPassPipeline(RetrievalEngine(get_course_store(), settings), settings)
    results = [_run(pipeline, query, plan_id) for plan_id in ("concise", "stepwise", "socratic")]
    for result in results:
        assert (result.decision, result.render_attempts) == ("answer", 1)
        assert result.entry.counts.dropped.get("merged", 0) >= 1 and check_subset(result.rendered, result.locked).passed
        assert any(len(claim.span_ids) == 2 for claim in result.locked.claims)
        texts = [claim.text for claim in result.locked.claims]
        assert len(texts) == len(set(texts))  # the sentence is shown once, citing both spans
        rendered = [segment.text for segment in result.rendered.segments if segment.kind == "claim"]
        assert len(rendered) == len(set(rendered))
    assert len({result.locked.claim_set_hash for result in results}) == 1


def test_ac_3_6_the_ledger_readers_are_the_plans_reviewer_role_only():
    # Review 2026-11-19: plan 7.3 reads "(owner or reviewer)"; admin is not a ledger reader (PD-12 revised).
    from app.core.authorization import LEDGER_READER_ROLES

    assert LEDGER_READER_ROLES == ("reviewer",)
    learner, admin = demo("ledger-learner"), demo("ledger-admin", role="admin")
    body = chat(learner, "Why does routing depth matter?").json()
    (shadow,) = records(shadowed_response_id=body["turn_id"])
    with SessionLocal() as db:
        start = db.scalar(select(func.max(SecurityEvent.seq))) or 0
    missing = client.get(f"/ledger/responses/shadow-{uuid4()}", headers=admin)
    assert missing.status_code == 404
    for target in (shadow.response_id, body["turn_id"]):
        refused = client.get(f"/ledger/responses/{target}", headers=admin)
        assert (refused.status_code, refused.json(), refused.headers["cache-control"]) == (404, missing.json(), "no-store")
    own_turn = chat(admin, "Why does routing depth matter?").json()["turn_id"]
    own = client.get(f"/ledger/responses/{own_turn}", headers=admin)
    assert own.status_code == 200 and own.json()["record"]["delivery"] == "legacy"
    assert all(own.json()["record"][field] is None for field in ("seq", "prev_hash", "record_hash", "entry_sha256", "shadowed_response_id"))
    with SessionLocal() as db:
        reads = db.scalars(select(SecurityEvent).where(SecurityEvent.seq > start, SecurityEvent.event_type == "ledger.reviewer_read")
                            .order_by(SecurityEvent.seq)).all()
    assert reads == []


def test_the_chat_response_schemas_keep_every_field_in_openapi():
    # Review 2026-11-19: a wrap model_serializer made both response schemas a free-form object.
    from app.schemas import AssistantChatResponse, EvidencePanel, TutorTurnResponse

    document = app.openapi()
    schemas = document["components"]["schemas"]
    for name, model in (("AssistantChatResponse", AssistantChatResponse), ("TutorTurnResponse", TutorTurnResponse)):
        assert set(schemas[name]["properties"]) == set(model.model_fields), name
        assert set(model.model_json_schema(mode="serialization")["properties"]) == set(model.model_fields), name
        assert "additionalProperties" not in schemas[name]
    for path, name in (("/assistant/chat", "AssistantChatResponse"), ("/tutor/turns", "TutorTurnResponse")):
        content = document["paths"][path]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert content == {"$ref": f"#/components/schemas/{name}"}
    bare = AssistantChatResponse(answer="a", citations=[], retrieval_mode="lexical", provider="none", model="m")
    assert "evidence" not in bare.model_dump(mode="json") and '"evidence"' not in bare.model_dump_json()  # conflict 28 holds
    panel = bare.model_copy(update={"evidence": EvidencePanel(decision="abstain")})
    assert panel.model_dump(mode="json")["evidence"]["decision"] == "abstain"
    assert "evidence" not in TutorTurnResponse(**bare.model_dump()).model_dump(mode="json")


def test_plan_i_ready_reports_versions_ledger_head_and_two_pass_mode(monkeypatch):
    chat(demo("plani"), "Why does routing depth matter?")
    body = client.get("/ready").json()
    # The package in force (v3 since Phase 4).
    assert (body["config_package_version"], body["config_package_sha256"]) == (PACKAGE.package_version, PACKAGE.sha256)
    assert (body["two_pass_tutor"], body["two_pass_tutor_setting"], body["phase4_exit_passed"]) == ("shadow", "shadow", False)
    pipeline = body["tutor_pipeline"]
    assert (pipeline["resolver"], pipeline["generator"], pipeline["renderer"]) == (PARAMS.resolver_id, PARAMS.generator_default, PARAMS.renderer_id)
    assert pipeline["prompt_hashes"] == {"resolver": PARAMS.resolver_prompt_hash, "evidential": PARAMS.evidential_prompt_hash,
                                         "pedagogical": PARAMS.pedagogical_prompt_hash}
    assert pipeline["schemas_sha256"] == PARAMS.schemas_sha256 and pipeline["available"] is True and pipeline["max_regenerations"] == 2
    with SessionLocal() as db:
        head = db.scalar(select(ResponseLedgerHead.seq))
    assert head >= 2
    # Review 2026-11-19: /ready is public, so it says whether the head is readable, never its sequence number (the
    # all-time count of tutor responses, which only a reviewer's ledger read shows).
    assert body["ledger"] == {"chain": "tutor-responses", "status": "ok"}
    assert "head_seq" not in json.dumps(body) and f'"seq": {head}' not in json.dumps(body)
    assert {"tutor_ledger", "two_pass_shadow"} <= set(body["slis"])
    assert (body["tutor_ledger_enabled"], body["ledger_route_enabled"], body["evidence_panel_enabled"], body["tutor_turns_route_enabled"]) == (True,) * 4
    from app import main as main_module

    monkeypatch.setattr(main_module, "SessionLocal", _raise("_build_fields read the database"))
    fields = main_module._build_fields()
    assert fields["two_pass_tutor"] == "shadow" and fields["tutor_pipeline"]["version"] == "two-pass-v1"
    assert main_module._ledger_head() == {"chain": "tutor-responses", "status": "unavailable"}  # fails open


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": database_url, "ENVIRONMENT": "development", "PYTHONUNBUFFERED": "1"}
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=API_ROOT, env=env, capture_output=True, text=True, timeout=180)


def test_plan_g_the_alembic_revision_is_reversible_and_refuses_to_drop_a_non_empty_ledger(fresh_database_url):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    revisions, parents = set(), set()
    for path in (API_ROOT / "alembic" / "versions").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and isinstance(node.value, ast.Constant):
                if node.target.id == "revision":
                    revisions.add(node.value.value)
                elif node.target.id == "down_revision" and node.value.value:
                    parents.add(node.value.value)
    assert revisions - parents == {SCHEMA_REVISION} and len(SCHEMA_REVISION) <= 32  # the single head; fits alembic_version
    engine = create_engine(fresh_database_url)
    # Every table the Phase 3 revision creates (the Idempotency-Key records of POST /tutor/turns joined it, DI-40).
    ledger_tables = {"response_ledger", "response_ledger_head", "tutor_turn_idempotency"}
    try:
        Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables if table.name not in ledger_tables])
        # A Phase 2 database: tutor_turns has no ledger_record_expected yet (the revision adds it; spec 18.8 F12).
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE tutor_turns DROP COLUMN ledger_record_expected")
        for args in (("stamp", "20261119_phase2_corpus_spans"), ("upgrade", "head")):
            completed = _alembic(fresh_database_url, *args)
            assert completed.returncode == 0, completed.stderr[-2000:]
        run_schema_upgrades(engine)
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata) == []
        append_ledger_entry(make_entry(), session_factory=sessionmaker(bind=engine), budget_ms=5000)
        engine.dispose()
        refused = _alembic(fresh_database_url, "downgrade", "-1")
        assert refused.returncode != 0 and "export first" in refused.stderr
        assert ledger_tables <= set(sa_inspect(engine).get_table_names())
        engine.dispose()
        allowed = _alembic(fresh_database_url, "-x", "allow_ledger_drop=true", "downgrade", "-1")
        assert allowed.returncode == 0, allowed.stderr[-2000:]
        assert not ledger_tables & set(sa_inspect(engine).get_table_names())
        assert "ledger_record_expected" not in {column["name"] for column in sa_inspect(engine).get_columns("tutor_turns")}
    finally:
        engine.dispose()


def test_plan_g_legacy_turns_read_as_no_verdict():
    headers = demo("plang-legacy")
    turn_id = f"turn-{uuid4()}"
    with SessionLocal() as db:
        thread = TutorThread(id=f"thread-{uuid4()}", user_id=headers["x-demo-user"], title="pre-ledger")
        db.add(thread)
        db.flush()
        # Created by an image that keeps no ledger: ledger_record_expected stays null (spec 18.8 F12; review round 4,
        # 18.7 E6: a turn that expected a record and has none is a missing record, not a legacy turn, which
        # test_response_ledger_delivery.py covers).
        db.add(TutorTurn(id=turn_id, thread_id=thread.id, user_id=headers["x-demo-user"], resolved_query="q", retrieval_mode="lexical", provider="none",
                         model="m", decision="abstain", decision_reason="no_approved_span", citations=[], claims=[], corpus_version="c",
                         policy_version="cs595-v1", created_at=datetime(2026, 1, 1, tzinfo=UTC)))
        db.commit()
        before = (db.scalar(select(func.count()).select_from(ResponseLedgerRecord)), db.scalar(select(func.count()).select_from(TutorTurn)))
    response = client.get(f"/ledger/responses/{turn_id}", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"response_id": turn_id, "verdict": "no-verdict", "recorded": False, "legacy_turn": True,
                               "unrecorded_reason": "earlier_image", "record": None}
    with SessionLocal() as db:
        assert (db.scalar(select(func.count()).select_from(ResponseLedgerRecord)), db.scalar(select(func.count()).select_from(TutorTurn))) == before


def test_plan_h_private_plane_spans_never_reach_the_bundle_the_envelope_or_the_alias_route(tmp_path, monkeypatch):
    def privatise(payload):
        for item in payload["items"]:
            if ROUTING_DOCUMENT in item["asset_filenames"]:
                item["plane"] = "private"
                item["public_service"] = True

    approved_settings = settings_for("all_public_approved", "bm25f-v1")
    approved = store_for("all_public_approved", "bm25f-v1")
    private_settings = settings_for("all_public_approved", "bm25f-v1", manifest=edited_manifest(tmp_path, privatise, base=APPROVED_MANIFEST))
    private_store = CourseStore(private_settings)
    routing_item = source_asset_id(ROUTING_DOCUMENT, "document")
    before_pipeline = TwoPassPipeline(RetrievalEngine(approved, approved_settings), approved_settings)
    after_pipeline = TwoPassPipeline(RetrievalEngine(private_store, private_settings), private_settings)
    reached = 0
    routing_spans: set[str] = set()
    for query in IN_DOMAIN:
        before = _run(before_pipeline, query)
        hit = {span.span_id for span in before.bundle.spans if span.item_id == routing_item}
        if not hit:
            continue
        reached += 1
        routing_spans |= hit
        after = _run(after_pipeline, query)
        assert not any(span.item_id == routing_item for span in after.bundle.spans), query
        assert after.envelope is None or not {span.span_id for span in after.envelope.evidence} & hit
        assert not set(after.entry.span_ids) & hit
        if after.envelope is not None:
            quotable = {span.span_id for span in after.bundle.spans if span.quotable}
            assert {span.span_id for span in after.envelope.evidence} <= quotable
    assert reached >= 5  # the control: these queries did retrieve the item while it was public
    span_id = sorted(routing_spans)[0]
    monkeypatch.setattr(spans_route, "get_settings", lambda: approved_settings.model_copy(update={"span_resolver_route_enabled": True}))
    monkeypatch.setattr(spans_route, "get_span_resolver", lambda: SpanResolver(approved))
    assert client.get(f"/evidence/spans/{span_id}", headers=anonymous()).status_code == 200  # the control: public, approved, resolvable
    monkeypatch.setattr(spans_route, "get_settings", lambda: private_settings.model_copy(update={"span_resolver_route_enabled": True}))
    monkeypatch.setattr(spans_route, "get_span_resolver", lambda: SpanResolver(private_store))
    response = client.get(f"/evidence/spans/{span_id}", headers=anonymous())
    assert (response.status_code, response.headers["cache-control"]) == (404, "no-store")
    governed_settings = settings_for("governed_empty")
    governed = TwoPassPipeline(RetrievalEngine(store_for("governed_empty"), governed_settings), governed_settings)
    reasons = set()
    for query in IN_DOMAIN + OFF_TOPIC + AC["stopword_only"]:
        result = _run(governed, query)
        assert result.decision == "abstain" and result.envelope is None
        reasons.add(result.abstention_reason)
    assert reasons <= {"no_quotable_evidence", "no_query_terms", "no_match", "insufficient_coverage", "below_floor"}
    assert "no_quotable_evidence" in reasons


# ======================================================================================================== task 3.8


def test_task_3_8_the_evidence_panel_labels_the_contained_answer_and_never_says_grounded(monkeypatch):
    answered = chat(demo("t38"), "Why does routing depth matter?").json()
    abstained = chat(demo("t38"), "What is the capital of France?").json()
    assert answered["decision"] == "answer" and abstained["decision"] == "abstain"
    panel = answered["evidence"]
    assert (panel["panel_schema"], panel["decision"], panel["labels"], panel["verdict"]) == ("evidence-panel-v1", "answer", ["lexically_screened"], "no-verdict")
    assert panel["degraded"][0] == "extractive_only" and "citations_provisional" in panel["degraded"]
    assert [span["span_id"] for span in panel["spans"]] == [citation["span_id"] for citation in answered["citations"]]
    assert all(span["resolvable"] is True for span in panel["spans"])  # SPAN_RESOLVER_ROUTE_ENABLED in development
    assert (abstained["evidence"]["decision"], abstained["evidence"]["labels"], abstained["evidence"]["spans"]) == ("abstain", [], [])
    assert "grounded" not in json.dumps(panel).lower() and "grounded" not in json.dumps(abstained["evidence"]).lower()
    unresolvable = orchestrator_for(Settings(span_resolver_route_enabled=False))
    monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda: unresolvable)
    assert all(span["resolvable"] is False for span in chat(demo("t38"), "Why does routing depth matter?").json()["evidence"]["spans"])
    hidden = orchestrator_for(Settings(evidence_panel_enabled=False))
    monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda: hidden)
    assert "evidence" not in chat(demo("t38"), "Why does routing depth matter?").json()


def test_evidence_spans_alias_matches_the_resolver_route_and_is_off_when_the_flag_is_off(monkeypatch):
    store = get_course_store()
    authored = next(record for record in store.span_registry.records if record.item_kind == "authored")
    document = next(entry for entry in store.chunks if entry.item_kind == "document")
    for span_id in (authored.span_id, document.span_id):
        alias, original = client.get(f"/evidence/spans/{span_id}", headers=anonymous()), client.get(f"/spans/{span_id}", headers=anonymous())
        assert alias.status_code == original.status_code == 200
        assert alias.json() == original.json() and alias.json()["license_class"] == "public" and alias.json()["excerpt"] is None
        assert alias.headers["cache-control"] == original.headers["cache-control"]
    governed = settings_for("governed_empty")
    monkeypatch.setattr(spans_route, "get_settings", lambda: governed.model_copy(update={"span_resolver_route_enabled": True}))
    monkeypatch.setattr(spans_route, "get_span_resolver", lambda: SpanResolver(store))
    assert client.get(f"/evidence/spans/{document.span_id}", headers=anonymous()).status_code == 404  # D-31: not approved
    assert client.get(f"/evidence/spans/{authored.span_id}", headers=anonymous()).status_code == 200
    monkeypatch.setattr(spans_route, "get_settings", lambda: Settings(span_resolver_route_enabled=False))
    disabled = client.get(f"/evidence/spans/{authored.span_id}", headers=anonymous())
    assert (disabled.status_code, disabled.json(), disabled.headers["cache-control"]) == (404, {"detail": "Span not found."}, "no-store")


def test_the_span_route_and_its_alias_share_one_rate_limit_window(monkeypatch):
    # Review 2026-11-19: slowapi keeps one window per endpoint, so alternating the two paths doubled the budget.
    limited = Settings(spans_rate_limit="4/minute")
    monkeypatch.setattr(spans_route, "get_settings", lambda: limited)
    authored = next(record for record in get_course_store().span_registry.records if record.item_kind == "authored")
    headers = anonymous()
    paths = [f"/spans/{authored.span_id}", f"/evidence/spans/{authored.span_id}"]
    statuses = [client.get(paths[index % 2], headers=headers).status_code for index in range(4)]
    assert statuses == [200, 200, 200, 200]
    assert [client.get(path, headers=headers).status_code for path in paths] == [429, 429]
    # Another client has its own window.
    assert client.get(paths[1], headers=anonymous()).status_code == 200


def test_the_ledger_is_outside_erasure_and_guarded_at_start_up():
    assert not {"response_ledger", "response_ledger_head"} & {table.name for table in user_keyed_tables()}
    for table in ("response_ledger", "response_ledger_head"):
        assert not Base.metadata.tables[table].foreign_keys
    chat(demo("guard"), "Why does routing depth matter?")
    with SessionLocal() as db:
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(text("UPDATE response_ledger SET decision = 'abstain'"))
        db.rollback()
        with pytest.raises(DBAPIError, match="forward only"):
            db.execute(text("DELETE FROM response_ledger_head"))
        db.rollback()
        check = verify_response_ledger(db)
    assert check.ok, check.problems


def test_a_start_up_pipeline_problem_is_fatal_only_when_the_pipeline_is_requested(fresh_database_url, tmp_path):
    package_dir = tmp_path / "package"
    shutil.copytree(DEFAULT_PACKAGE_PATH.parent / "schemas", package_dir / "schemas")
    # The shipped package under its own name, with its own sidecar (v3 since Phase 4).
    shutil.copyfile(DEFAULT_PACKAGE_PATH, package_dir / DEFAULT_PACKAGE_PATH.name)
    shutil.copyfile(DEFAULT_PACKAGE_PATH.with_name(DEFAULT_PACKAGE_PATH.name + ".sha256"), package_dir / (DEFAULT_PACKAGE_PATH.name + ".sha256"))
    (package_dir / "schemas" / "claim-plan.v1.schema.json").unlink()
    governed = {"CONFIG_PACKAGE_PATH": str(package_dir / DEFAULT_PACKAGE_PATH.name), "ENFORCE_CORPUS_GOVERNANCE": "true", "CORPUS_MANIFEST_PATH": str(REPO_MANIFEST)}
    requested = _startup(fresh_database_url, {**governed, "TWO_PASS_TUTOR": "shadow"})
    assert requested.returncode != 0 and "tutor pipeline" in requested.stderr and "ClaimPlan" in requested.stderr
    probe = create_engine(fresh_database_url)
    try:
        assert set(sa_inspect(probe).get_table_names()) == set()
    finally:
        probe.dispose()
    off = _startup(fresh_database_url, {**governed, "TWO_PASS_TUTOR": "off"})
    assert off.returncode == 0, off.stderr[-2000:]
    assert "tutor.two_pass.unavailable" in off.stderr


def test_freeze_production_chat_responses_keep_todays_keys_and_bytes(monkeypatch):
    production = settings_for("governed_empty", allowed_origins=[TRUSTED_ORIGIN])
    assert (production.evidence_panel_enabled, production.two_pass_tutor) == (False, "off")
    governed = store_for("governed_empty")
    orchestrator = orchestrator_for(production, store=governed)
    monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda: orchestrator)
    response = chat(demo("freeze"), "Why does routing depth matter?")
    body = response.json()
    assert set(body) == {"answer", "citations", "retrieval_mode", "provider", "model", "grounded", "thread_id", "turn_id", "decision",
                         "decision_reason", "claims"}
    assert body["grounded"] is False and body["decision"] == "abstain"  # D-31: the governed build abstains
    plain = orchestrator_for(production, store=governed)
    monkeypatch.setattr(plain, "_legacy_followup", lambda *args, **kwargs: None)
    monkeypatch.setattr(plain, "_shadow_followup", lambda *args, **kwargs: None)
    monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda: plain)
    without = chat(demo("freeze"), "Why does routing depth matter?")

    def stripped(reply) -> bytes:
        data = reply.json()
        return reply.content.replace(data["thread_id"].encode(), b"").replace(data["turn_id"].encode(), b"")

    assert stripped(response) == stripped(without)  # byte for byte, ids aside
    assert records(response_id=body["turn_id"])[0].delivery == "legacy" and records(shadowed_response_id=body["turn_id"]) == []


def test_plan_l_a_held_ledger_lock_never_delays_the_learner_beyond_the_append_budget(monkeypatch, clean_metrics):
    from sqlalchemy.exc import IntegrityError, OperationalError

    settings = Settings(two_pass_tutor="off")
    orchestrator = orchestrator_for(settings)
    monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda: orchestrator)
    chat(demo("lock-warm"), "Why does routing depth matter?")  # the head row exists
    if session_engine.dialect.name == "postgresql":
        holder = session_engine.connect()
        transaction = holder.begin()
        holder.execute(text("SELECT seq FROM response_ledger_head WHERE chain = 'tutor-responses' FOR UPDATE"))
        try:
            LEDGER_METRICS.reset()
            started = time.monotonic()
            response = chat(demo("lock"), "Why does routing depth matter?")
            elapsed_ms = (time.monotonic() - started) * 1000
        finally:
            transaction.rollback()
            holder.close()
        assert response.status_code == 200 and response.json()["decision"] == "answer"
        # The bounded append (the package's budget, TUTOR_LEDGER_APPEND_BUDGET_MS unset) plus the chat itself.
        assert elapsed_ms < ledger.ledger_budget_ms(settings, get_config_package(settings)) + 500 + 1500
        assert LEDGER_METRICS.snapshot()["failed"]["legacy"] == 1
        assert records(response_id=response.json()["turn_id"]) == []
    # Both dialects: an IntegrityError is retried at most three times; a database error without a deadlock (40P01) or
    # serialization (40001) SQLSTATE is not retried (those two are, spec 18.8 F8; test_response_ledger_chain.py).
    for error, expected_attempts, raised in ((IntegrityError("INSERT", {}, Exception("race")), 3, ledger.LedgerAppendError),
                                             (OperationalError("SELECT", {}, Exception("lock timeout")), 1, OperationalError)):
        attempts = []

        def factory(error=error, attempts=attempts):
            session = SessionLocal()

            def commit():
                attempts.append(1)
                raise error

            session.commit = commit
            return session

        with pytest.raises(raised):
            append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
        assert len(attempts) == expected_attempts
