"""Phase 3, fifth review round (2026-11-19; Phase 3 spec 18.8). Each test fails if its defect comes back.

F1  plan I "abstention by reason" over delivered responses: a legacy record keeps the gate's own reason and
    sufficiency, the attempted line and public /ready count delivered decisions by reason.
F2  the replay record names its code by content (in test_phase3_acceptance.py).
F3  the Q&A answer carries the evidence panel in development only (E-46 names the Q&A citation cards).
F4  every rule id the package names, and the two_pass_tutor defaults, are compared with the code.
F5  the extractive generator's question-overlap threshold is a package value.
F6  PD-09 and owner_decisions.D-12 say H6 blocks the provider interim path; D-19 runs instead.
F7  records: the reader-roles comment, the fault-mode counts.
F8  start-up's trigger guard never deadlocks a live ledger append; no DDL when current; deadlocks are retried.
F9  the compose field's light-theme contrast (in the frontend tests).
F10 start-up writes no ledger marker (and test_phase3_review4.py E6, rewritten).
F11 every legacy attempt ends in exactly one terminal log line carrying its attempt id.
F12 each turn says whether it expects a record, so rollback-window turns are not lost records.
F13 a request past its Idempotency-Key lease can never make a second turn for its key.
F14 the runbook's forward Alembic step checks the stamp.
F15 BEP records (where the evidence package is present).
F16 repository docs: spec 18.7's exit items, section 16, 8.3, 11.4 and the ratio wording.

Isolation (spec M17): chain and migration tests use fresh_database_url. Dialect-specific steps branch inside.
"""

from __future__ import annotations

from collections import Counter
import copy
from datetime import UTC, datetime, timedelta
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect as sa_inspect, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import assistant as assistant_route
from app.api.routes import qa as qa_route
from app.api.routes import tutor as tutor_route
from app.core import schema_upgrades
from app.core.config import TWO_PASS_DEFAULT_DEVELOPMENT, TWO_PASS_DEFAULT_ELSEWHERE, Settings
from app.core.config_package import DEFAULT_PACKAGE_PATH, ConfigPackageError, get_config_package, parse_config_package
from app.core.db import Base, SessionLocal
from app.core.schema_upgrades import RESPONSE_LEDGER_FUNCTION_BODIES, RESPONSE_LEDGER_POSTGRES_TRIGGERS, RESPONSE_LEDGER_TRIGGERS, run_schema_upgrades
from app.db_models import ResponseLedgerRecord, TutorThread, TutorTurn, TutorTurnIdempotency
from app.main import app
from app.services import ledger, turn_idempotency
from app.services.content_assembler import CourseStore
from app.services.ledger import (
    LegacyDelivery,
    LegacyPreparationFailed,
    append_ledger_entry,
    delivered_abstention_reason,
    ledger_coverage,
    record_legacy_delivery,
    sqlstate,
    verify_response_ledger,
)
from app.services.qa_engine import QAEngine
from app.services.retrieval_engine import RetrievalEngine
from app.services.store import get_course_store, get_retrieval_engine
from app.services.teaching_assistant import TeachingAssistantService
from app.services.tutor_orchestrator import TutorOrchestrator
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline.contracts import EnvelopeSpan, EvidentialEnvelope, EvidentialInstructions
from app.services.tutor_pipeline.evidential import EXTRACTIVE_ID, ExtractiveD19Generator, evidential_prompt_hash
from app.services.tutor_pipeline.metrics import LEDGER_METRICS, TWO_PASS_METRICS
from app.services.tutor_pipeline.package_check import check_tutor_pipeline_package
from tutor_fakes import FAULT_MODES, make_entry

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
BEP_ROOT = REPO_ROOT.parent / "BEP-2-12"
SPEC = (REPO_ROOT / "docs" / "architecture" / "phase3-implementation-spec.md").read_text(encoding="utf-8")
RUNBOOK = (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8")
OBSERVABILITY = (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8")
TEST_STRATEGY = (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
REPO_MANIFEST = REPO_ROOT / "corpus" / "public" / "manifest.json"
PACKAGE = get_config_package(Settings())
PARAMS = PACKAGE.tutor_pipeline
RAW = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
IN_DOMAIN = "How does graph shrinking reduce routing overhead?"
FLOOR_MISS = "What is the capital of France?"
STOPWORDS_ONLY = "the and of"
PHASE2_REVISION = "20261119_phase2_corpus_spans"
PHASE3_REVISION = "20261119_phase3_response_ledger"
PHASE3_TABLES = ("response_ledger", "response_ledger_head", "tutor_turn_idempotency")
client = TestClient(app)


def demo(prefix: str, role: str = "learner") -> dict[str, str]:
    return {"x-demo-user": f"{prefix}-{uuid4().hex[:12]}", "x-demo-role": role, "x-forwarded-for": f"review5-{uuid4().hex}"}


def fresh(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "x-forwarded-for": f"review5-{uuid4().hex}"}


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


def orchestrator_for(settings: Settings) -> TutorOrchestrator:
    return TutorOrchestrator(TeachingAssistantService(RetrievalEngine(get_course_store(), settings), settings), settings)


def parsed(raw: dict):
    return parse_config_package(raw, path=DEFAULT_PACKAGE_PATH, sha256="", hash_verified=False)


def _events(caplog, name: str) -> list[dict]:
    return [dict(record.json_fields) for record in caplog.records if getattr(record, "json_fields", {}).get("event") == name]


def _legacy(response_id: str | None = None) -> LegacyDelivery:
    return LegacyDelivery(
        response_id=response_id or f"turn-{uuid4()}", decision="abstain", reason="no_approved_span", claims=(), quoted=(), retrieved=None,
        answer_sha256="c" * 64, retrieval_mode="lexical-extractive-lexically-screened", provider="none", model="extractive-lexically-screened",
        corpus_version="corpus-test", index_version="index-test", gate="p1-floor", threshold_version="score-floor-p1-v1", floor=6.0, margin=0.0,
        policy_version="cs595-v1",
    )


def _turn(db: Session, thread: TutorThread, *, expected: bool | None) -> str:
    turn_id = f"turn-{uuid4()}"
    db.add(TutorTurn(id=turn_id, thread_id=thread.id, user_id=thread.user_id, resolved_query="q", retrieval_mode="lexical", provider="none",
                     model="m", decision="abstain", decision_reason="no_approved_span", citations=[], claims=[], corpus_version="c",
                     policy_version="p", created_at=datetime.now(UTC), ledger_record_expected=expected))
    return turn_id


@pytest.fixture
def clean_metrics():
    LEDGER_METRICS.reset()
    TWO_PASS_METRICS.reset()
    yield
    LEDGER_METRICS.reset()
    TWO_PASS_METRICS.reset()


# ============================================================================================================ F1


def _governed_qa_engine() -> QAEngine:
    settings = Settings(environment="production", enforce_corpus_governance=True, corpus_manifest_path=str(REPO_MANIFEST))
    return QAEngine(RetrievalEngine(CourseStore(settings), settings), settings)


def test_f1_a_floor_miss_a_stopword_query_and_a_d31_non_approval_give_three_delivered_reasons(monkeypatch, caplog, clean_metrics):
    dev = QAEngine(get_retrieval_engine(), Settings())
    cases = (("floor miss", dev, FLOOR_MISS), ("stopwords only", dev, STOPWORDS_ONLY), ("not approved under D-31", _governed_qa_engine(), IN_DOMAIN))
    headers = demo("f1")
    seen = {}
    for label, engine, question in cases:
        monkeypatch.setattr(qa_route, "get_qa_engine", lambda engine=engine: engine)
        before = {row.seq for row in records()}
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="qcai.tutor"):
            response = client.post("/qa/ask", headers=fresh(headers), json={"question": question})
        assert response.status_code == 200 and response.json()["decision"] == "abstain", label
        (row,) = [row for row in records() if row.seq not in before]
        entry = json.loads(row.entry)
        (attempt,) = _events(caplog, "tutor.ledger.attempted")
        assert (attempt["decision"], attempt["abstention_reason"]) == ("abstain", entry["abstention_reason"]), label
        seen[label] = (entry["abstention_reason"], entry["retrieval"]["sufficiency"])
    # The gate returned nothing on the first two, and its reason is kept; it matched passages on the third, and none
    # of them was approved (D-31): only that one is no_approved_span.
    assert seen["floor miss"][0] in {"no_match", "insufficient_coverage", "below_floor"}
    assert seen["stopwords only"][0] == "no_query_terms"
    assert seen["not approved under D-31"][0] == "no_approved_span"
    assert len({reason for reason, _ in seen.values()}) == 3
    for label in ("floor miss", "stopwords only"):
        assert (seen[label][1]["decision"], seen[label][1]["reason"]) == ("abstain", seen[label][0])
    assert seen["not approved under D-31"][1]["decision"] in {"answer", "near_miss"}
    # Public /ready counts what was delivered, by reason (a legacy decision is no shadow output).
    delivered = client.get("/ready").json()["slis"]["tutor_ledger"]["delivered"]
    assert delivered["by_surface"]["qa"]["decisions"] == {"answer": 0, "abstain": 3}
    assert delivered["by_surface"]["qa"]["abstention_by_reason"] == {reason: 1 for reason, _ in sorted(seen.values())}
    assert delivered["abstention_rate"] == 1.0 and delivered["by_surface"]["tutor"]["abstention_rate"] is None


def test_f1_the_tutor_record_carries_the_gates_reason_and_the_learners_response_is_unchanged(caplog, clean_metrics):
    headers = demo("f1-tutor")
    with caplog.at_level(logging.INFO, logger="qcai.tutor"):
        response = client.post("/assistant/chat", headers=fresh(headers), json={"message": FLOOR_MISS})
    body = response.json()
    assert response.status_code == 200 and body["decision"] == "abstain"
    assert body["decision_reason"] == "no_approved_span"  # the learner's response is today's
    (row,) = records(response_id=body["turn_id"])
    entry = json.loads(row.entry)
    assert entry["abstention_reason"] in contracts.GATE_ABSTENTION_REASONS
    assert entry["retrieval"]["sufficiency"]["reason"] == entry["abstention_reason"]
    (attempt,) = _events(caplog, "tutor.ledger.attempted")
    assert attempt["abstention_reason"] == entry["abstention_reason"] and "surface" not in attempt
    tutor = LEDGER_METRICS.public_snapshot()["delivered"]["by_surface"]["tutor"]
    assert tutor["decisions"] == {"answer": 0, "abstain": 1} and tutor["abstention_by_reason"] == {entry["abstention_reason"]: 1}
    with SessionLocal() as db:
        assert db.get(TutorTurn, body["turn_id"]).decision_reason == "no_approved_span"


def test_f1_the_delivered_reason_rule():
    class Contained:
        def __init__(self, decision):
            self.decision = decision

    class Retrieval:
        def __init__(self, results, reason):
            self.results, self.reason = results, reason

    assert delivered_abstention_reason(Contained("answer"), Retrieval([], "no_match")) is None
    for reason in contracts.GATE_ABSTENTION_REASONS:
        assert delivered_abstention_reason(Contained("abstain"), Retrieval([], reason)) == reason
    # Passages matched but none quotable, an unknown reason, or no retrieval side channel: no_approved_span.
    assert delivered_abstention_reason(Contained("abstain"), Retrieval([object()], "evidence")) == "no_approved_span"
    assert delivered_abstention_reason(Contained("abstain"), Retrieval([], "something_else")) == "no_approved_span"
    assert delivered_abstention_reason(Contained("abstain"), None) == "no_approved_span"
    observability = OBSERVABILITY.split("## Phase 3 SLIs", 1)[1]
    assert any(line.startswith("| Delivered abstention by reason") and "jsonPayload.abstention_reason" in line for line in observability.splitlines())


# ============================================================================================================ F3


def test_f3_the_qa_answer_carries_the_evidence_panel_in_development_only(monkeypatch):
    headers = demo("f3")
    on = client.post("/qa/ask", headers=fresh(headers), json={"question": IN_DOMAIN})
    body = on.json()
    assert on.status_code == 200 and body["decision"] == "answer"
    panel = body["evidence"]
    assert (panel["panel_schema"], panel["decision"], panel["labels"], panel["verdict"]) == ("evidence-panel-v1", "answer", ["lexically_screened"], "no-verdict")
    assert [span["span_id"] for span in panel["spans"]] == [citation["span_id"] for citation in body["citations"]]
    assert "grounded" not in json.dumps(panel).lower()
    abstained = client.post("/qa/ask", headers=fresh(headers), json={"question": FLOOR_MISS}).json()
    assert (abstained["evidence"]["decision"], abstained["evidence"]["labels"], abstained["evidence"]["spans"]) == ("abstain", [], [])
    # With the switch off the body is today's, byte for byte: the panel-on body without its evidence key.
    monkeypatch.setattr(qa_route, "get_qa_engine", lambda: QAEngine(get_retrieval_engine(), Settings(evidence_panel_enabled=False)))
    off = client.post("/qa/ask", headers=fresh(headers), json={"question": IN_DOMAIN})
    assert b'"evidence"' not in off.content
    stripped = {key: value for key, value in body.items() if key != "evidence"}
    assert off.content == json.dumps(stripped, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    # Outside development the switch is off by default (D-05), so production bodies keep today's keys.
    production = Settings(environment="production")
    assert production.evidence_panel_enabled is False
    assert "evidence" not in QAEngine(get_retrieval_engine(), production).ask(IN_DOMAIN).model_dump(mode="json")
    register = BEP_ROOT / "00_meta" / "DEFERRED_ITEMS_REGISTER.md"
    if register.exists():
        row = next(line for line in register.read_text(encoding="utf-8").splitlines() if line.startswith("| DI-34 |"))
        assert "the Q&A panel" not in row.split("(Revised", 1)[0] and "built in development" in row


# ============================================================================================================ F4


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


# ============================================================================================================ F5


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


# ============================================================================================================ F6


def test_f6_hold_h6_blocks_the_provider_interim_path_and_d19_runs_instead():
    path = RAW["owner_decisions"]["D-12"]["path"]
    assert "hold H6 blocks the provider interim path" in path and "runs D-19 extractive mode instead" in path
    assert "the D-19 extractive generator is the interim path" not in path
    register = BEP_ROOT / "00_meta" / "PROVISIONAL_DEFAULTS_REGISTER.md"
    if register.exists():
        row = next(line for line in register.read_text(encoding="utf-8").splitlines() if line.startswith("| PD-09 |"))
        current = row.split("(Corrected in 18.8 F6", 1)[0]
        assert "H6 blocks the provider interim path" in current and "D-19 extractive mode instead" in current
        assert "is the Phase 3 interim path" not in current


# ============================================================================================================ F7


def test_f7_the_records_say_what_the_code_does():
    authorization = (API_ROOT / "app" / "core" / "authorization.py").read_text(encoding="utf-8")
    assert "so outside development only owners read (PD-12)" not in authorization
    assert "the route answers 404 to everyone, owners included" in authorization
    ac33 = next(line for line in TEST_STRATEGY.splitlines() if line.startswith("| AC-3-3"))
    assert f"({len(FAULT_MODES)} failure modes" in ac33 and len(FAULT_MODES) == 12
    record = BEP_ROOT / "phase03" / "PHASE_RECORD.md"
    if record.exists():
        text_ = record.read_text(encoding="utf-8")
        subset = next(line for line in text_.splitlines() if line.startswith("- `claim_gate.py` is now the subset checker"))
        assert "`segment-exact-whitespace-v3`" in subset.split("(", 1)[0]
        assert "(11 since the third review round)" not in text_ and "12 fault modes" in text_


# ============================================================================================================ F8


class _PausingSession(Session):
    """Pauses an append right after it locked the chain head (SELECT ... FOR UPDATE), until released."""

    paused: threading.Event
    resume: threading.Event

    def execute(self, statement, *args, **kwargs):
        result = super().execute(statement, *args, **kwargs)
        if getattr(statement, "_for_update_arg", None) is not None and not self.paused.is_set():
            self.paused.set()
            assert self.resume.wait(30)
        return result


def _waiting_on_a_lock(engine) -> int:
    with engine.connect() as connection:
        return int(connection.exec_driver_sql(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'").scalar() or 0)


def test_f8_a_start_up_that_recreates_the_guards_never_deadlocks_a_live_append(fresh_database_url, monkeypatch):
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        if engine.dialect.name != "postgresql":
            # SQLite serialises writers and has no lock order to get wrong: start-up and appends simply alternate.
            append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
            run_schema_upgrades(engine)
            append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
            with factory() as db:
                assert verify_response_ledger(db).ok
            return
        append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
        paused, resume = threading.Event(), threading.Event()
        pausing = type("Pausing", (_PausingSession,), {"paused": paused, "resume": resume})
        outcome: dict[str, object] = {}

        def append():
            try:
                outcome["append"] = append_ledger_entry(make_entry(), session_factory=sessionmaker(bind=engine, class_=pausing), budget_ms=30000)
            except Exception as exc:  # noqa: BLE001 - reported below
                outcome["append"] = exc

        def start_up():
            try:
                run_schema_upgrades(engine)
                outcome["start_up"] = "ok"
            except Exception as exc:  # noqa: BLE001 - reported below
                outcome["start_up"] = exc

        appender = threading.Thread(target=append)
        appender.start()
        assert paused.wait(30)  # the append holds the chain head
        # A start-up whose guards differ from the catalogs (a new image), so it re-creates them now.
        monkeypatch.setattr(schema_upgrades, "postgres_guard_current", lambda *args: False)
        starter = threading.Thread(target=start_up)
        starter.start()
        deadline = time.monotonic() + 30
        while _waiting_on_a_lock(engine) == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert _waiting_on_a_lock(engine) >= 1  # start-up waits for the head, holding nothing the append needs
        resume.set()
        appender.join(60)
        starter.join(60)
        assert outcome["start_up"] == "ok", outcome
        assert isinstance(outcome["append"], ledger.AppendedRecord) and outcome["append"].seq == 2, outcome
        monkeypatch.undo()
        with factory() as db:
            assert verify_response_ledger(db).ok
    finally:
        engine.dispose()


def test_f8_a_start_up_with_current_guards_runs_no_ddl_and_a_drifted_guard_is_recreated(fresh_database_url):
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        if engine.dialect.name != "postgresql":
            with engine.connect() as connection:
                names = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
            assert set(schema_upgrades.RESPONSE_LEDGER_SQLITE_TRIGGERS) <= names
            return
        assert {(trigger.name, trigger.table) for trigger in RESPONSE_LEDGER_TRIGGERS} == set(RESPONSE_LEDGER_POSTGRES_TRIGGERS)
        append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
        with engine.connect() as connection:
            assert schema_upgrades.postgres_guard_current(connection, RESPONSE_LEDGER_FUNCTION_BODIES, RESPONSE_LEDGER_TRIGGERS)
        # Another session holds what an in-flight append holds: start-up must not wait for it.
        holder = engine.connect()
        transaction = holder.begin()
        holder.exec_driver_sql("LOCK TABLE response_ledger_head, response_ledger IN ROW EXCLUSIVE MODE")
        finished = threading.Event()
        threading.Thread(target=lambda: (run_schema_upgrades(engine), finished.set()), daemon=True).start()
        try:
            assert finished.wait(30), "start-up waited for a lock although its guards were current"
        finally:
            transaction.rollback()
            holder.close()
        # Drift: a changed function body and a disabled trigger are each re-created by the next start.
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE OR REPLACE FUNCTION response_ledger_append_only() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN RETURN NULL; END$$")
            connection.exec_driver_sql("ALTER TABLE response_ledger DISABLE TRIGGER response_ledger_links_to_chain")
        with engine.connect() as connection:
            assert not schema_upgrades.postgres_guard_current(connection, RESPONSE_LEDGER_FUNCTION_BODIES, RESPONSE_LEDGER_TRIGGERS)
        run_schema_upgrades(engine)
        with engine.connect() as connection:
            assert schema_upgrades.postgres_guard_current(connection, RESPONSE_LEDGER_FUNCTION_BODIES, RESPONSE_LEDGER_TRIGGERS)
        with pytest.raises(Exception, match="append-only"):
            with factory() as db:
                db.execute(text("DELETE FROM response_ledger"))
                db.commit()
    finally:
        engine.dispose()


class _Orig(Exception):
    def __init__(self, code: str, *, style: str):
        super().__init__({"C": code, "M": "test"} if style == "pg8000" else "test")
        if style == "psycopg":
            self.sqlstate = code


@pytest.mark.parametrize("style", ["psycopg", "pg8000"])
def test_f8_a_deadlock_or_serialization_failure_is_retried_within_the_budget(fresh_database_url, style):
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        assert sqlstate(OperationalError("SELECT", {}, _Orig("40P01", style=style))) == "40P01"
        for code in ("40P01", "40001"):
            failures = [OperationalError("SELECT", {}, _Orig(code, style=style))]

            class Flaky(Session):
                def execute(self, statement, *args, **kwargs):
                    if failures:
                        raise failures.pop()
                    return super().execute(statement, *args, **kwargs)

            appended = append_ledger_entry(make_entry(), session_factory=sessionmaker(bind=engine, class_=Flaky), budget_ms=5000, attempts=3)
            assert appended.duplicate is False and failures == []
        # Any other database error is still raised at once (fail open quickly).
        other = [OperationalError("SELECT", {}, _Orig("55P03", style=style))]

        class Locked(Session):
            def execute(self, statement, *args, **kwargs):
                if other:
                    raise other.pop()
                return super().execute(statement, *args, **kwargs)

        with pytest.raises(OperationalError):
            append_ledger_entry(make_entry(), session_factory=sessionmaker(bind=engine, class_=Locked), budget_ms=5000, attempts=3)
        with factory() as db:
            assert verify_response_ledger(db).count == 2
    finally:
        engine.dispose()


def test_f8_new_columns_are_added_outside_the_guard_transaction():
    source = (API_ROOT / "app" / "core" / "schema_upgrades.py").read_text(encoding="utf-8")
    run = source.split("def run_schema_upgrades", 1)[1]
    assert run.index("_add_missing_columns(engine)") < run.index("with engine.begin() as connection:")
    assert "lock_timeout" in source.split("def _add_missing_columns", 1)[1].split("def run_schema_upgrades", 1)[0]


# ============================================================================================================ F10


def test_f10_the_ledger_route_ignores_start_up_time(monkeypatch):
    # A turn the earlier image served after the new revision started (before traffic moved) is no lost record.
    headers = demo("f10")
    with SessionLocal() as db:
        thread = TutorThread(id=f"thread-{uuid4()}", user_id=headers["x-demo-user"], title="no-traffic window")
        db.add(thread)
        db.flush()
        turn_id = _turn(db, thread, expected=None)
        db.commit()
    body = client.get(f"/ledger/responses/{turn_id}", headers=fresh(headers)).json()
    assert (body["recorded"], body["legacy_turn"], body["unrecorded_reason"]) == (False, True, "earlier_image")
    main_source = (API_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "mark_ledger_started" not in main_source and "start_marker_failed" not in OBSERVABILITY


# ============================================================================================================ F11


def _terminal_lines(caplog) -> Counter:
    lines = [*_events(caplog, "tutor.ledger.appended"), *_events(caplog, "tutor.ledger.append_failed")]
    return Counter(line["attempt"] for line in lines if line.get("delivery") == "legacy")


def test_f11_every_attempt_ends_in_exactly_one_terminal_line_with_its_id(fresh_database_url, monkeypatch, caplog, clean_metrics):
    factory, engine = fresh_sessions(fresh_database_url)
    real_append = ledger.append_ledger_entry
    try:
        with caplog.at_level(logging.INFO, logger="qcai.tutor"):
            # appended
            assert record_legacy_delivery(_legacy(), settings=Settings(), session_factory=factory) is not None
            # failed in the append
            monkeypatch.setattr(ledger, "append_ledger_entry", lambda *a, **k: (_ for _ in ()).throw(OperationalError("INSERT", {}, Exception("down"))))
            assert record_legacy_delivery(_legacy(), settings=Settings(), session_factory=factory) is None
            # refused (too many in flight)
            monkeypatch.setattr(ledger.LEGACY_APPENDS, "submit", lambda *a, **k: None)
            assert record_legacy_delivery(_legacy(), settings=Settings(), session_factory=factory) is None
            monkeypatch.undo()
            # failed at the prepare stage
            assert record_legacy_delivery(LegacyPreparationFailed(error=RuntimeError("prepare"), decision="abstain", reason="no_match"),
                                          settings=Settings(), session_factory=factory) is None
            # deferred, then appended after the request stopped waiting
            gate = threading.Event()

            def slow(entry, **kwargs):
                assert gate.wait(30)
                return real_append(entry, **{**kwargs, "budget_ms": 5000})

            monkeypatch.setattr(ledger, "append_ledger_entry", slow)
            assert record_legacy_delivery(_legacy(), settings=Settings(tutor_ledger_append_budget_ms=200), session_factory=factory) is None
            (deferred,) = _events(caplog, "tutor.ledger.append_deferred")
            assert _terminal_lines(caplog)[deferred["attempt"]] == 0  # not terminal
            gate.set()
            assert ledger.LEGACY_APPENDS.drain(30)
        attempts = [line["attempt"] for line in _events(caplog, "tutor.ledger.attempted")]
        terminals = _terminal_lines(caplog)
        assert len(attempts) == len(set(attempts)) == 5 and all(re.fullmatch(r"[0-9a-f]{32}", attempt) for attempt in attempts)
        assert set(terminals) == set(attempts) and set(terminals.values()) == {1}
        (late,) = [line for line in _events(caplog, "tutor.ledger.appended") if line["attempt"] == deferred["attempt"]]
        assert late["duplicate"] is False
        snapshot = LEDGER_METRICS.snapshot()
        assert (snapshot["attempted"]["legacy"], snapshot["appended"]["legacy"], snapshot["failed"]["legacy"]) == (5, 2, 3)
    finally:
        engine.dispose()


def test_f11_the_coverage_stop_reads_terminal_lines_not_windows():
    phase3 = OBSERVABILITY.split("## Phase 3 SLIs", 1)[1]
    coverage = next(line for line in phase3.splitlines() if line.startswith("| Ledger coverage (100%)"))
    assert "exactly one terminal line" in coverage and "`attempt`" in coverage
    assert "an append still running at the window's end counts in the next" not in coverage.split("(spec 18.8 F11", 1)[0]
    stops = RUNBOOK.split("**Stop conditions** (plan Phase 3 L):", 1)[1].split("On a stop:", 1)[0]
    assert "no terminal line" in stops and "is not a loss" in stops
    assert "it is a stop only when its attempt ends in `tutor.ledger.append_failed`" in stops


# ============================================================================================================ F12


def test_f12_a_kill_switch_turn_says_so_and_a_default_turn_expects_a_record(monkeypatch, clean_metrics):
    headers = demo("f12")
    on = client.post("/assistant/chat", headers=fresh(headers), json={"message": IN_DOMAIN}).json()
    monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda: orchestrator_for(Settings(tutor_ledger_enabled=False)))
    off = client.post("/assistant/chat", headers=fresh(headers), json={"message": IN_DOMAIN}).json()
    with SessionLocal() as db:
        assert db.get(TutorTurn, on["turn_id"]).ledger_record_expected is True
        assert db.get(TutorTurn, off["turn_id"]).ledger_record_expected is False
    reviewer = demo("f12-reviewer", role="reviewer")
    for who in (headers, reviewer):
        body = client.get(f"/ledger/responses/{off['turn_id']}", headers=fresh(who)).json()
        assert (body["recorded"], body["legacy_turn"], body["unrecorded_reason"]) == (False, False, "ledger_disabled")
        recorded = client.get(f"/ledger/responses/{on['turn_id']}", headers=fresh(who)).json()
        assert (recorded["recorded"], recorded["unrecorded_reason"]) == (True, None)


def test_f12_the_worker_splits_unrecorded_turns_by_what_they_expected(fresh_database_url):
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        since = datetime.now(UTC) - timedelta(minutes=1)
        with factory() as db:
            thread = TutorThread(id=f"thread-{uuid4()}", user_id=f"review5-{uuid4().hex[:8]}", title="t")
            db.add(thread)
            db.flush()
            recorded = _turn(db, thread, expected=True)
            for expected in (True, None, False):
                _turn(db, thread, expected=expected)
            db.commit()
        append_ledger_entry(make_entry(recorded), session_factory=factory, budget_ms=5000)
        with factory() as db:
            coverage = ledger_coverage(db, since)
        assert (coverage["turns_since"], coverage["unrecorded"], coverage["not_expected_earlier_image"], coverage["ledger_disabled"]) == (4, 1, 1, 1)
    finally:
        engine.dispose()


def test_f12_existing_tables_gain_the_new_columns(fresh_database_url):
    connect_args = {"check_same_thread": False} if fresh_database_url.startswith("sqlite") else {}
    engine = create_engine(fresh_database_url, connect_args=connect_args)
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE tutor_turns DROP COLUMN ledger_record_expected")
            connection.exec_driver_sql("ALTER TABLE tutor_turn_idempotency DROP COLUMN claim_token")
        for _ in range(2):  # idempotent
            run_schema_upgrades(engine)
            inspector = sa_inspect(engine)
            assert "ledger_record_expected" in {column["name"] for column in inspector.get_columns("tutor_turns")}
            assert "claim_token" in {column["name"] for column in inspector.get_columns("tutor_turn_idempotency")}
    finally:
        engine.dispose()


def test_f12_the_runbook_records_the_rollback_window():
    rollback = RUNBOOK.split("**Roll back**", 1)[1]
    assert "Record the rollback window" in rollback and "earlier_image" in rollback
    assert "from then on every delivery is expected to have a record" not in RUNBOOK.split("(Corrected in 18.8 F10", 1)[0]


# ============================================================================================================ F13


def _key_row(user_id: str, key: str) -> TutorTurnIdempotency:
    with SessionLocal() as db:
        return db.scalars(select(TutorTurnIdempotency).where(TutorTurnIdempotency.user_id == user_id,
                                                             TutorTurnIdempotency.key_sha256 == turn_idempotency.key_sha256(key))).one()


def test_f13_a_request_past_its_lease_cannot_make_a_second_turn_for_its_key(monkeypatch):
    headers = demo("f13")
    user_id, key = headers["x-demo-user"], f"lease-{uuid4().hex}"
    real = tutor_route.deliver_tutor_turn
    outcome: dict[str, object] = {}

    def outlives_its_lease(*args, **kwargs):
        if not outcome:
            outcome["started"] = True  # the retry below passes through here too, and runs normally
            # The claim ages past its lease while this request still runs, and a retry takes the key over.
            with SessionLocal() as db:
                db.execute(update(TutorTurnIdempotency)
                           .where(TutorTurnIdempotency.user_id == user_id, TutorTurnIdempotency.key_sha256 == turn_idempotency.key_sha256(key))
                           .values(created_at=datetime.now(UTC) - timedelta(seconds=PARAMS.idempotency_lease_seconds + 60)))
                db.commit()
            outcome["retry"] = client.post("/tutor/turns", headers={**fresh(headers), "Idempotency-Key": key}, json={"message": IN_DOMAIN})
        return real(*args, **kwargs)

    monkeypatch.setattr(tutor_route, "deliver_tutor_turn", outlives_its_lease)
    late = client.post("/tutor/turns", headers={**fresh(headers), "Idempotency-Key": key}, json={"message": IN_DOMAIN})
    retry = outcome["retry"]
    assert retry.status_code == 200 and "idempotent-replayed" not in retry.headers
    assert (late.status_code, late.json()["detail"], late.headers["cache-control"]) == (409, turn_idempotency.SUPERSEDED, "no-store")
    with SessionLocal() as db:
        turns = list(db.scalars(select(TutorTurn.id).where(TutorTurn.user_id == user_id)))
    assert turns == [retry.json()["turn_id"]]  # one key, one turn
    row = _key_row(user_id, key)
    assert row.turn_id == retry.json()["turn_id"] and json.loads(row.response_body) == retry.json()
    monkeypatch.undo()
    again = client.post("/tutor/turns", headers={**fresh(headers), "Idempotency-Key": key}, json={"message": IN_DOMAIN})
    assert again.status_code == 200 and again.headers["idempotent-replayed"] == "true" and again.json() == retry.json()


def test_f13_the_claim_token_guards_a_reused_id_a_late_release_and_a_concurrent_fill(fresh_database_url, monkeypatch):
    factory, engine = fresh_sessions(fresh_database_url)
    key, request = "k" * 64, "r" * 64
    now = datetime.now(UTC)
    old = now - timedelta(seconds=PARAMS.idempotency_lease_seconds + 60)
    lease = {"ttl_hours": PARAMS.idempotency_ttl_hours, "lease_seconds": PARAMS.idempotency_lease_seconds}
    try:
        with factory() as db:
            first = turn_idempotency.new_claim(user_id="u", key_digest=key, request_digest=request, now=old)
            db.add(first)
            db.commit()
            held_first = TutorTurnIdempotency(id=first.id, claim_token=first.claim_token)
        # A retry replaces the abandoned claim; its row takes the same id, as SQLite reused ids before AUTOINCREMENT.
        with factory() as db:
            assert turn_idempotency.find(db, "u", key, now=now, **lease) is None
            second = turn_idempotency.new_claim(user_id="u", key_digest=key, request_digest=request, now=now)
            second.id = held_first.id
            db.add(second)
            db.commit()
            held_second = TutorTurnIdempotency(id=second.id, claim_token=second.claim_token)
        assert held_first.id == held_second.id and held_first.claim_token != held_second.claim_token
        with factory() as db:
            with pytest.raises(turn_idempotency.ClaimLost):
                turn_idempotency.fill(db, held_first, turn_id="turn-late", response_body="{}")
            db.rollback()
            turn_idempotency.release(db, held_first)  # the late request's release leaves the retry's claim alone
            db.commit()
        with factory() as db:
            row = db.scalars(select(TutorTurnIdempotency)).one()
            assert (row.claim_token, row.turn_id, row.response_body) == (held_second.claim_token, None, None)
            turn_idempotency.fill(db, held_second, turn_id="turn-retry", response_body='{"ok":true}')
            db.commit()
        with factory() as db:
            with pytest.raises(turn_idempotency.ClaimLost):  # a filled claim is never filled twice
                turn_idempotency.fill(db, held_second, turn_id="turn-again", response_body="{}")
        # A claim that is filled while a retry decides it is abandoned is kept: the conditional delete misses it, and
        # the retry reads the filled record.
        with factory() as db:
            db.execute(update(TutorTurnIdempotency).values(turn_id=None, response_body=None, created_at=old))
            db.commit()
        real_lookup = turn_idempotency._lookup
        calls = []

        def lookup(db, user_id, key_digest):
            row = real_lookup(db, user_id, key_digest)
            if not calls:
                with factory() as other:
                    other.execute(update(TutorTurnIdempotency).values(turn_id="turn-filled", response_body='{"filled":true}'))
                    other.commit()
            calls.append(row)
            return row

        monkeypatch.setattr(turn_idempotency, "_lookup", lookup)
        with factory() as db:
            found = turn_idempotency.find(db, "u", key, now=now, **lease)
            assert found is not None and found.turn_id == "turn-filled"
        assert len(calls) == 2
    finally:
        engine.dispose()


def test_f13_the_lease_is_a_liveness_bound_and_the_runbook_records_the_request_timeout():
    source = (API_ROOT / "app" / "services" / "turn_idempotency.py").read_text(encoding="utf-8")
    assert "Safety does not depend on any timeout" in source and "were it still running, its commit would find the claim gone" not in source
    assert "Read the service's request timeout" in RUNBOOK and "timeoutSeconds" in RUNBOOK
    register = BEP_ROOT / "00_meta" / "PROVISIONAL_DEFAULTS_REGISTER.md"
    if register.exists():
        row = next(line for line in register.read_text(encoding="utf-8").splitlines() if line.startswith("| PD-11 |"))
        assert "min_question_overlap_terms" in row and "claim token" in row


# ============================================================================================================ F14


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": database_url, "ENVIRONMENT": "development", "PYTHONUNBUFFERED": "1"}
    env.pop("CLOUD_SQL_CONNECTION_NAME", None)
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=API_ROOT, env=env, capture_output=True, text=True, timeout=180)


def test_f14_the_forward_alembic_step_runs_only_on_a_phase2_stamp(fresh_database_url):
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        # A Phase 2 database: no Phase 3 tables and no ledger_record_expected, stamped at the Phase 2 revision.
        Base.metadata.drop_all(engine, tables=[Base.metadata.tables[name] for name in PHASE3_TABLES])
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE tutor_turns DROP COLUMN ledger_record_expected")
        engine.dispose()
        assert _alembic(fresh_database_url, "stamp", PHASE2_REVISION).returncode == 0
        upgraded = _alembic(fresh_database_url, "upgrade", PHASE3_REVISION)  # the runbook's gated step
        assert upgraded.returncode == 0, upgraded.stderr[-2000:]
        checked = _alembic(fresh_database_url, "check")
        assert checked.returncode == 0 and "No new upgrade operations detected" in (checked.stdout + checked.stderr), checked.stderr[-2000:]
        assert set(PHASE3_TABLES) <= set(sa_inspect(engine).get_table_names())
        engine.dispose()
        # The same database without a stamp, as create_all leaves one: "upgrade head" replays every revision against
        # tables that exist and fails, which is why the runbook skips the job then.
        assert _alembic(fresh_database_url, "stamp", "base").returncode == 0
        refused = _alembic(fresh_database_url, "upgrade", "head")
        assert refused.returncode != 0
    finally:
        engine.dispose()
    before = RUNBOOK.split("## Phase 3", 1)[1].split("**Before the release:**", 1)[1].split("**Deploy**", 1)[0]
    assert "Check the stamp first" in before and "`alembic current`" in before
    assert f"`alembic upgrade {PHASE3_REVISION}`" in before and before.index("`alembic current`") < before.index(f"`alembic upgrade {PHASE3_REVISION}`")
    assert "(`alembic upgrade head`)" not in before


# ============================================================================================================ F15


def test_f15_the_bep_records_say_what_the_code_does():
    # The evidence package lives beside the repository, not in it (CI has none): checked where present.
    if not (BEP_ROOT / "phase03" / "PHASE_RECORD.md").exists():
        return
    pin = (API_ROOT / "app" / "config_package" / "v2.json.sha256").read_text(encoding="utf-8").strip()
    record = (BEP_ROOT / "phase03" / "PHASE_RECORD.md").read_text(encoding="utf-8")
    pointer = next(line for line in record.splitlines() if line.startswith("**Configuration package v2**"))
    # The pointer names the current pin and the round section that holds it (the fifth round's until the pin moved in
    # the seventh, spec 18.10).
    named = re.search(r'is in "(\w+ review round)" below', pointer)
    assert pin[:8] in pointer and named, pointer
    assert pin in record.split(f"## {named.group(1)} (", 1)[1].split("\n## ", 1)[0]
    built = record.split("## What was built", 1)[1].split("## Acceptance criteria", 1)[0]
    assert "also trimmed `slis.two_pass_shadow` to fields that describe no single run)" not in built
    assert "citation_list_mismatch" in built
    notes = (BEP_ROOT / "phase03" / "CLOSURE_EVIDENCE_NOTES.md").read_text(encoding="utf-8")
    assert "## Fourth review round" in notes and "## Fifth review round" in notes
    assert "the current pin is in the third-round section below" not in notes
    register = (BEP_ROOT / "00_meta" / "DEFERRED_ITEMS_REGISTER.md").read_text(encoding="utf-8")
    di40 = next(line for line in register.splitlines() if line.startswith("| DI-40 |"))
    assert "in_progress_lease_seconds" in di40 and "claim token" in di40
    status = (BEP_ROOT / "00_meta" / "STATUS.md").read_text(encoding="utf-8")
    row = next(line for line in status.splitlines() if line.startswith("| 3 |"))
    assert "phase03/PHASE_RECORD.md" in row and "exit NOT passed" in row
    assert "Three review lenses" not in status and "four lenses" in status


# ============================================================================================================ F16


def _event_names(table_text: str) -> set[str]:
    names = set()
    for line in table_text.splitlines():
        match = re.match(r"\| `(tutor\.[a-z_.]+)` \|", line)
        if match:
            names.add(match.group(1))
    return names


def test_f16_the_spec_and_the_runbook_say_what_the_code_does():
    intro = SPEC.split("### 18.7 Fourth review round", 1)[1].split("**Production changes**", 1)[0]
    assert "DI-50" in intro and "Two exit items were added" in intro
    section_16 = SPEC.split("## 16. Provisional defaults", 1)[1].split("## 17.", 1)[0]
    assert "**Revised in 18.7" in section_16 and "**Revised in 18.8" in section_16
    alembic_block = SPEC.split("### 8.3 Alembic", 1)[1].split("### 8.4", 1)[0]
    assert "create the three tables" in alembic_block and "create both tables" not in alembic_block.split("(Corrected in 18.8 F16", 1)[0]
    # 11.4 names every event the code logs, and so does observability.md.
    logged = set()
    for path in (API_ROOT / "app").rglob("*.py"):
        logged |= set(re.findall(r'"(tutor\.(?:ledger|two_pass|evidence)\.[a-z_]+)"', path.read_text(encoding="utf-8")))
    section_11_4 = SPEC.split("### 11.4 Structured log events", 1)[1].split("## 12.", 1)[0]
    observability = OBSERVABILITY.split("## Phase 3 SLIs", 1)[1]
    assert logged == _event_names(section_11_4) == _event_names(observability), (logged, _event_names(section_11_4), _event_names(observability))
    assert "as `/ready` counts them" not in OBSERVABILITY
    shadow = (API_ROOT / "app" / "services" / "tutor_pipeline" / "shadow.py").read_text(encoding="utf-8")
    assert "exactly as /ready and the replay count them" not in shadow
    metrics = (API_ROOT / "app" / "services" / "tutor_pipeline" / "metrics.py").read_text(encoding="utf-8")
    assert "tests and operators" not in metrics
