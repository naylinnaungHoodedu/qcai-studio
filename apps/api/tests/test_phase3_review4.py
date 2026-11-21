"""Phase 3, fourth review round (2026-11-19; Phase 3 spec 18.7). Each test fails if its defect comes back.

E1  the ledger's rendered_span_ids is what the citation segments displayed; the subset check refuses a citation
    list that is not exactly the displayed spans (rule segment-exact-whitespace-v3).
E2  the schema guard compares the leaf constraints too (type, enum, const, pattern, bounds, defaults).
E3  the replay README and the spec say where the bound-claim ratio is reported, and count 299 items.
E4  F-2 (zero learner-state fields in evidential-pass prompts) is recorded with how it was taken.
E5  a request that rolls back is never a ledger attempt, so it never lowers the coverage SLI.
E6  a turn without a record after the ledger began recording reads as a missing record, not a legacy turn (since
    spec 18.8 F10/F12 the turn's own ledger_record_expected says so; start-up writes no marker).
E7  an Idempotency-Key whose request died mid-turn is released after a short lease, not the 24-hour TTL.
E8  the text helpers' docstring says the subset check never folds.
E9  the migration's refusal and docstring name the in-image worker and an absolute downgrade target.
E10 the rollback runbook checks the stamp and uses an absolute target; Alembic connects through the Cloud SQL
    connector in production.
E11 TUTOR_LEDGER_ENABLED=false writes nothing and changes nothing on the tutor surface.
E12 the rollback export can be restored, so its deletion rule is reachable; the runbook says what the drop costs.
E13 ledger coverage is measurable across instances: an attempted line per delivery, surface on appended lines,
    and the observability tables name every stop signal.
E14 the spec's conflict 29 and section 12 say what the code and the page do now.
E15 public /ready carries no shadow field that changes with a run's outcome.
(E16 and E17, the evidence panel's abstention copy and contrast, are in the frontend tests.)

Isolation (spec M17): chain and migration tests use fresh_database_url. No skips: dialect-specific steps branch inside.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import logging
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
from typing import Literal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect as sa_inspect, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.api.routes import assistant as assistant_route
from app.api.routes import qa as qa_route
from app.core.config import Settings
from app.core.config_package import canonical_sha256, get_config_package, load_config_package
from app.core.db import Base, SessionLocal, get_db
from app.core.schema_upgrades import run_schema_upgrades
from app.db_models import ResponseLedgerHead, ResponseLedgerRecord, TutorMessage, TutorThread, TutorTurn, TutorTurnIdempotency
from app.main import app
from app.services import claim_gate, ledger, turn_idempotency
from app.services.ledger import (
    GENESIS_HASH,
    LedgerAppendError,
    LedgerRestoreRefused,
    append_ledger_entry,
    export_ledger,
    ledger_started_at,
    record_hash_for,
    restore_ledger,
    verify_response_ledger,
)
from app.services.qa_engine import QAEngine
from app.services.retrieval_engine import RetrievalEngine
from app.services.store import get_course_store, get_retrieval_engine
from app.services.teaching_assistant import TeachingAssistantService
from app.services.tutor_orchestrator import TutorOrchestrator
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline import pipeline as pipeline_module
from app.services.tutor_pipeline.contracts import PresentationPlan, sha256_hex
from app.services.tutor_pipeline.metrics import LEDGER_METRICS, LICENSE_METRICS, PUBLIC_SHADOW_FIELDS, TWO_PASS_METRICS
from app.services.tutor_pipeline.package_check import LEAF_KEYWORDS, check_tutor_pipeline_package, schema_path, structural_problems
from app.services.tutor_pipeline.pipeline import PipelineInput, TwoPassPipeline, rendered_span_ids
from app.services.tutor_pipeline.render import TemplateRenderer
from app.services.tutor_pipeline.resolve import LearnerTurn, resolve_turns
from app.workers import response_ledger as ledger_worker
from tutor_fakes import FAULT_MODES, FaultyRenderer, _relayout, make_entry

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
BEP_ROOT = REPO_ROOT.parent / "BEP-2-12"
SPEC = (REPO_ROOT / "docs" / "architecture" / "phase3-implementation-spec.md").read_text(encoding="utf-8")
RUNBOOK = (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8")
OBSERVABILITY = (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8")
REPLAY_README = (REPO_ROOT / "docs" / "evaluation" / "phase3" / "README.md").read_text(encoding="utf-8")
MIGRATION = (API_ROOT / "alembic" / "versions" / "20261119_phase3_response_ledger.py").read_text(encoding="utf-8")
PACKAGE = get_config_package(Settings())
PARAMS = PACKAGE.tutor_pipeline
IN_DOMAIN = "How does graph shrinking reduce routing overhead?"
# A query whose two-pass answer has several claims on several spans (spec 18.10 H1: the graph-shrinking query now
# answers with one whole sentence, because its other spans start or end inside the sentences it matched).
MULTI_CLAIM = "Explain why quantum logistics needs both problem reduction before execution and routing control during compilation."
HEADER_SUBSET = ("content-type", "cache-control", "x-assistant-provider", "x-assistant-model")
PHASE2_REVISION = "20261119_phase2_corpus_spans"
PHASE3_REVISION = "20261119_phase3_response_ledger"
PHASE3_TABLES = {"response_ledger", "response_ledger_head", "tutor_turn_idempotency"}
client = TestClient(app)


def demo(prefix: str, role: str = "learner") -> dict[str, str]:
    return {"x-demo-user": f"{prefix}-{uuid4().hex[:12]}", "x-demo-role": role, "x-forwarded-for": f"review4-{uuid4().hex}"}


def fresh(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "x-forwarded-for": f"review4-{uuid4().hex}"}


def records(**where) -> list[ResponseLedgerRecord]:
    with SessionLocal() as db:
        query = select(ResponseLedgerRecord).order_by(ResponseLedgerRecord.seq)
        for column, value in where.items():
            query = query.where(getattr(ResponseLedgerRecord, column) == value)
        return list(db.scalars(query))


def orchestrator_for(settings: Settings) -> TutorOrchestrator:
    return TutorOrchestrator(TeachingAssistantService(RetrievalEngine(get_course_store(), settings), settings), settings)


def without_ids(body: dict) -> dict:
    return {key: value for key, value in body.items() if key not in {"thread_id", "turn_id"}}


def fresh_sessions(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False), engine


@pytest.fixture
def clean_metrics():
    LEDGER_METRICS.reset()
    TWO_PASS_METRICS.reset()
    yield
    LEDGER_METRICS.reset()
    TWO_PASS_METRICS.reset()


def _run(pipeline: TwoPassPipeline, query: str):
    resolved = resolve_turns([], LearnerTurn(f"message-{uuid4()}", query), package=pipeline.package)
    return pipeline.run(PipelineInput(resolved=resolved, lesson_slug=None, presentation=PresentationPlan(plan_id="concise", source="request"),
                                      response_id=f"shadow-{uuid4()}", delivery="shadow", shadowed_response_id=f"turn-{uuid4()}"), record=False)


# ============================================================================================================ E1


class _StaleCitations:
    """The reviewer's renderer: leaves the last claim line (and its markers) out, but keeps the citation list."""

    renderer_id = "template-renderer-v1"

    def render(self, locked, plan, *, attempt):
        rendered = TemplateRenderer().render(locked, plan, attempt=attempt)
        last_line = max(segment.line for segment in rendered.segments if segment.kind == "claim")
        kept = [segment for segment in rendered.segments if segment.line != last_line]
        return _relayout(rendered, kept, rendered.citations)


def test_e1_a_rendering_that_lists_a_span_it_never_shows_never_answers(monkeypatch):
    settings = Settings()
    engine = RetrievalEngine(get_course_store(), settings)
    full = _run(TwoPassPipeline(engine, settings), MULTI_CLAIM)
    assert full.decision == "answer" and len(full.locked.claims) >= 2
    # On the reviewer's query the last claim's span is cited by no other claim, so the stale list names an unshown span.
    probe = _StaleCitations().render(full.locked, PresentationPlan(plan_id="concise", source="request"), attempt=1)
    assert set(probe.citations) - set(claim_gate.displayed_span_ids(probe)), "the query no longer has a span shown only by its last claim"
    assert check_subset_problems(probe, full.locked) == ("citation_list_mismatch",)
    # Spec 18.11 I2: the pipeline half runs on the same several-claim query (on the graph-shrinking query, one claim
    # since 18.10 H1, the stale renderer dropped the only claim and also failed no_claim_rendered), and every attempt is
    # refused by the stale list alone.
    seen = _spy_subset_problems(monkeypatch)
    stale = _run(TwoPassPipeline(engine, settings, renderer=_StaleCitations()), MULTI_CLAIM)
    assert (stale.decision, stale.abstention_reason, stale.render_attempts) == ("abstain", "subset_check_failed", 3)
    assert seen == [("citation_list_mismatch",)] * 3, seen
    assert stale.entry.presentation.rendered_span_ids == () and stale.entry.presentation.subset_check == "failed"


def check_subset_problems(rendered, locked) -> tuple[str, ...]:
    return claim_gate.check_subset(rendered, locked).problems


def _spy_subset_problems(monkeypatch) -> list[tuple[str, ...]]:
    """The problem codes of every subset check the pipeline runs (spec 18.11 I2)."""
    seen: list[tuple[str, ...]] = []
    check = claim_gate.check_subset

    def spy(rendered, locked):
        result = check(rendered, locked)
        seen.append(result.problems)
        return result

    monkeypatch.setattr(pipeline_module, "check_subset", spy)
    return seen


def test_e1_the_record_names_the_displayed_spans_even_if_a_check_let_a_stale_list_through(monkeypatch):
    settings = Settings()
    engine = RetrievalEngine(get_course_store(), settings)
    # Defence in depth: even a subset check that passed the stale list could not make the record name the unshown span.
    monkeypatch.setattr(pipeline_module, "check_subset", lambda rendered, locked: claim_gate.SubsetCheckResult(True, (), 0, 0, 0))
    result = _run(TwoPassPipeline(engine, settings, renderer=_StaleCitations()), MULTI_CLAIM)
    assert result.decision == "answer"
    displayed = tuple(dict.fromkeys(segment.span_id for segment in result.rendered.segments if segment.kind == "citation"))
    assert result.entry.presentation.rendered_span_ids == displayed == rendered_span_ids(result.rendered)
    assert set(result.rendered.citations) - set(displayed)  # the renderer's own list named more


def test_e1_the_rule_id_names_the_new_behaviour_and_the_fault_modes_include_it(monkeypatch):
    assert claim_gate.SUBSET_CHECK_RULE == "segment-exact-whitespace-v3" == PARAMS.subset_check
    assert "citation_list_mismatch" in claim_gate.PROBLEM_CODES
    assert "undisplayed_citation" in FAULT_MODES
    settings = Settings()
    engine = RetrievalEngine(get_course_store(), settings)
    # Spec 18.11 I2: on the several-claim query the fault leaves a claim line out (on the one-claim graph-shrinking
    # query it fell back to listing a shown span twice), and exact refuses any fallback.
    seen = _spy_subset_problems(monkeypatch)
    always = FaultyRenderer(TemplateRenderer(), [True, True, True], random.Random(5), modes=("undisplayed_citation",), outside_sentence="x",
                            outside_span_id="span-" + "9" * 64, exact=True)
    result = _run(TwoPassPipeline(engine, settings, renderer=always), MULTI_CLAIM)
    assert (result.decision, result.abstention_reason) == ("abstain", "subset_check_failed")
    assert always.placed == ["undisplayed_citation"] * 3 and seen == [("citation_list_mismatch",)] * 3, (always.placed, seen)
    for path in ("docs/adr/ADR-001-grounding-separation.md", "docs/adr/ADR-005-abstention-gate.md", "docs/evaluation/phase3/README.md"):
        assert "segment-exact-whitespace-v3" in (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert "citation_list_mismatch" in SPEC


# ============================================================================================================ E2


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


# ============================================================================================================ E3


def test_e3_the_replay_readme_and_the_spec_say_where_the_ratio_is_reported():
    assert "reported live in `/ready`" not in REPLAY_README and "abstains on all 298 items" not in REPLAY_README
    assert "abstains on all 299 items" in REPLAY_README and "`tutor.two_pass.shadow`" in REPLAY_README
    conflict_11 = next(line for line in SPEC.splitlines() if "Phase 2 defined no such SLI. **Resolution:**" in line)
    assert "and `/ready` report the two-pass ratio" not in conflict_11 and "not on public `/ready`" in conflict_11


# ============================================================================================================ E4


def test_e4_f2_is_recorded_with_the_method_it_was_taken_by():
    di_49 = next(line for line in SPEC.split("## 16.", 1)[1].split("## 17.", 1)[0].splitlines() if line.startswith("| DI-49 |"))
    assert "F-2" in di_49 and "AC-3-1" in di_49 and "static check of logged prompts" in di_49
    history = SPEC.split("### 18.4 Review history", 1)[1]
    assert "<br>E4 F-2 recorded: `test_e4_*`" in history
    register = BEP_ROOT / "00_meta" / "DEFERRED_ITEMS_REGISTER.md"
    if register.exists():  # the evidence package sits beside the repository on the workstation; CI has the spec only
        rows = [line for line in register.read_text(encoding="utf-8").splitlines() if line.startswith("| DI-") and "F-2" in line]
        assert rows and "AC-3-1" in rows[0] and "static check of logged prompts" in rows[0]
        assert "F-2" in (BEP_ROOT / "phase03" / "PHASE_RECORD.md").read_text(encoding="utf-8")


# ============================================================================================================ E5


def _raise(*args, **kwargs):
    raise RuntimeError("prepare fault (test)")


def _failing_commit_db():
    db = SessionLocal()

    def commit():
        raise OperationalError("COMMIT", {}, Exception("the database went away (test)"))

    db.commit = commit
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.mark.parametrize("prepare_fails", [False, True])
def test_e5_a_request_that_rolls_back_is_never_a_ledger_attempt(clean_metrics, monkeypatch, prepare_fails):
    headers = demo("e5")
    assert client.post("/assistant/chat", headers=fresh(headers), json={"message": IN_DOMAIN}).status_code == 200
    assert client.post("/qa/ask", headers=fresh(headers), json={"question": IN_DOMAIN}).status_code == 200
    before = LEDGER_METRICS.snapshot()
    assert (before["attempted"]["legacy"], before["appended"]["legacy"], before["legacy_coverage_rate"]) == (2, 2, 1.0)
    if prepare_fails:
        monkeypatch.setattr(TutorOrchestrator, "_legacy_delivery", _raise)
        monkeypatch.setattr("app.services.qa_engine.legacy_delivery_for", _raise)
    app.dependency_overrides[get_db] = _failing_commit_db
    try:
        failing = TestClient(app, raise_server_exceptions=False)
        assert failing.post("/assistant/chat", headers=fresh(headers), json={"message": IN_DOMAIN}).status_code >= 500
        assert failing.post("/qa/ask", headers=fresh(headers), json={"question": IN_DOMAIN}).status_code >= 500
    finally:
        app.dependency_overrides.pop(get_db, None)
    after = LEDGER_METRICS.snapshot()
    # Nothing was delivered, so nothing was attempted, appended or lost: the rate and the stop are unchanged.
    assert after == before
    assert client.get("/ready").json()["slis"]["tutor_ledger"]["legacy_coverage_rate"] == 1.0


# ============================================================================================================ E6


def _owner_and_reviewer_reads(turn_id: str, headers: dict[str, str]) -> list[dict]:
    reviewer = demo("e6-reviewer", role="reviewer")
    return [client.get(f"/ledger/responses/{turn_id}", headers=fresh(who)).json() for who in (headers, reviewer)]


def test_e6_a_lost_record_after_the_ledger_started_is_not_reported_as_a_legacy_turn(monkeypatch, clean_metrics):
    headers = demo("e6")

    def lost(*args, **kwargs):
        raise LedgerAppendError("the append failed (test)")

    monkeypatch.setattr(ledger, "append_ledger_entry", lost)
    response = client.post("/assistant/chat", headers=fresh(headers), json={"message": IN_DOMAIN})
    assert response.status_code == 200 and LEDGER_METRICS.snapshot()["write_stop"] is True
    turn_id = response.json()["turn_id"]
    assert records(response_id=turn_id) == []
    # Spec 18.8 F12: the turn itself says it expected a record, so the read names the loss.
    expected = {"response_id": turn_id, "verdict": "no-verdict", "recorded": False, "legacy_turn": False, "unrecorded_reason": "missing",
                "record": None}
    assert _owner_and_reviewer_reads(turn_id, headers) == [expected, expected]


def test_e6_a_turn_from_before_the_ledger_started_is_still_a_legacy_turn():
    # Spec 18.8 F12: a turn an image that keeps no ledger created (before Phase 3, or in a rollback window) leaves
    # ledger_record_expected null, whenever it was created: such a turn is a legacy turn, never a lost record.
    headers = demo("e6-legacy")
    turn_id = f"turn-{uuid4()}"
    with SessionLocal() as db:
        thread = TutorThread(id=f"thread-{uuid4()}", user_id=headers["x-demo-user"], title="pre-ledger")
        db.add(thread)
        db.flush()
        db.add(TutorTurn(id=turn_id, thread_id=thread.id, user_id=headers["x-demo-user"], resolved_query="q", retrieval_mode="lexical", provider="none",
                         model="m", decision="abstain", decision_reason="no_approved_span", citations=[], claims=[], corpus_version="c",
                         policy_version="cs595-v1", created_at=datetime.now(UTC)))
        db.commit()
    expected = {"response_id": turn_id, "verdict": "no-verdict", "recorded": False, "legacy_turn": True, "unrecorded_reason": "earlier_image",
                "record": None}
    assert _owner_and_reviewer_reads(turn_id, headers) == [expected, expected]


def test_e6_the_first_append_writes_the_start_and_the_head_keeps_it(fresh_database_url):
    # Spec 18.8 F10: start-up writes no marker any more; the first append creates the head with its started_at, and
    # the head may never move it.
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        with factory() as db:
            assert ledger_started_at(db) is None and db.get(ResponseLedgerHead, ledger.CHAIN) is None
        start = datetime(2026, 6, 1, tzinfo=UTC)
        first = append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000, now=start)
        with factory() as db:
            head = db.get(ResponseLedgerHead, ledger.CHAIN)
            assert (head.seq, head.record_hash) == (1, first.record_hash) and ledger_started_at(db) == start
            assert ledger._utc(head.started_at) == start and verify_response_ledger(db).ok
        append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000, now=start + timedelta(hours=1))
        with factory() as db:
            assert ledger_started_at(db) == start
        # The head may not move its start, even on a valid forward step.
        second = make_entry()
        entry = ledger.entry_bytes(second).decode("utf-8")
        digest = sha256_hex(entry.encode("utf-8"))
        with factory() as db:
            last = ledger.chain_head(db)
        at = start + timedelta(hours=2)
        record_hash = record_hash_for(seq=last[0] + 1, created_at=at, prev_hash=last[1], entry_sha256=digest)
        with pytest.raises(Exception, match="moves forward only"):
            with factory() as db:
                db.execute(ledger.insert(ResponseLedgerRecord).values(
                    seq=last[0] + 1, response_id=second.response_id, delivery=second.delivery, decision=second.decision, shadowed_response_id=None,
                    claim_set_hash=None, entry_schema=second.entry_schema, entry=entry, entry_sha256=digest, prev_hash=last[1],
                    record_hash=record_hash, created_at=at))
                db.execute(ledger.update(ResponseLedgerHead).where(ResponseLedgerHead.chain == ledger.CHAIN)
                           .values(seq=last[0] + 1, record_hash=record_hash, updated_at=at, started_at=at))
                db.commit()
    finally:
        engine.dispose()


def test_e6_a_head_table_from_an_earlier_build_gains_started_at(fresh_database_url):
    connect_args = {"check_same_thread": False} if fresh_database_url.startswith("sqlite") else {}
    engine = create_engine(fresh_database_url, connect_args=connect_args)
    try:
        Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables if table.name != "response_ledger_head"])
        stamp = "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME"
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE TABLE response_ledger_head (chain VARCHAR(32) PRIMARY KEY, seq INTEGER NOT NULL, record_hash VARCHAR(64) NOT NULL, "
                f"updated_at {stamp} NOT NULL)")
        run_schema_upgrades(engine)
        assert "started_at" in {column["name"] for column in sa_inspect(engine).get_columns("response_ledger_head")}
        run_schema_upgrades(engine)  # idempotent
    finally:
        engine.dispose()


def test_e6_start_up_writes_no_ledger_marker_whatever_the_setting(monkeypatch, fresh_database_url):
    # Spec 18.8 F10: a revision deployed with no traffic starts while the earlier image still serves every learner, so
    # start-up must not mark the ledger as recording; the first append does, and each turn says what it expects.
    from app import main as main_module

    factory, engine = fresh_sessions(fresh_database_url)
    try:
        monkeypatch.setattr(main_module, "engine", engine)
        monkeypatch.setattr(main_module, "SessionLocal", factory)
        # Only the schema and ledger steps are under test: the corpus checks and the retention run are left out.
        monkeypatch.setattr(main_module, "_check_corpus_before_any_table", lambda: None)
        monkeypatch.setattr(main_module, "run_retention_cleanup", lambda db: None)
        for enabled in (True, False):
            monkeypatch.setattr(main_module, "settings", Settings(tutor_ledger_enabled=enabled))
            main_module._initialize_database()
            with factory() as db:
                assert db.get(ResponseLedgerHead, ledger.CHAIN) is None and ledger_started_at(db) is None
        assert not hasattr(ledger, "mark_ledger_started") and not hasattr(main_module, "mark_ledger_started")
    finally:
        engine.dispose()


# ============================================================================================================ E7


def _idempotent_turn(headers: dict[str, str], key: str):
    return client.post("/tutor/turns", headers={**fresh(headers), "Idempotency-Key": key}, json={"message": IN_DOMAIN})


def _claim(user_id: str, key: str, *, age: timedelta) -> None:
    digest = turn_idempotency.request_sha256(message=IN_DOMAIN, thread_id=None, lesson_slug=None, presentation_plan=None)
    with SessionLocal() as db:
        db.add(TutorTurnIdempotency(user_id=user_id, key_sha256=sha256_hex(key), request_sha256=digest, created_at=datetime.now(UTC) - age))
        db.commit()


def test_e7_an_abandoned_claim_is_released_after_its_lease_and_a_live_one_still_answers_409():
    assert PARAMS.idempotency_lease_seconds == 600 < PARAMS.idempotency_ttl_hours * 3600
    headers = demo("e7")
    user_id = headers["x-demo-user"]
    live_key, dead_key = f"live-{uuid4().hex}", f"dead-{uuid4().hex}"
    _claim(user_id, live_key, age=timedelta(seconds=30))
    _claim(user_id, dead_key, age=timedelta(seconds=PARAMS.idempotency_lease_seconds + 60))
    assert _idempotent_turn(headers, live_key).status_code == 409
    renewed = _idempotent_turn(headers, dead_key)
    assert renewed.status_code == 200 and "idempotent-replayed" not in renewed.headers
    with SessionLocal() as db:
        row = db.scalars(select(TutorTurnIdempotency).where(TutorTurnIdempotency.user_id == user_id,
                                                            TutorTurnIdempotency.key_sha256 == sha256_hex(dead_key))).one()
        assert row.turn_id == renewed.json()["turn_id"] and row.response_body is not None
    # The retry is then remembered as usual.
    again = _idempotent_turn(headers, dead_key)
    assert again.status_code == 200 and again.headers["idempotent-replayed"] == "true" and again.json() == renewed.json()


def test_e7_the_lease_is_a_provisional_package_value_shorter_than_the_ttl(tmp_path):
    raw = json.loads(PACKAGE.path.read_text(encoding="utf-8"))
    block = raw["tutor_pipeline"]["idempotency"]
    assert block["provisional"] is True and block["in_progress_lease_seconds"] == 600
    from app.core.config_package import ConfigPackageError, parse_config_package

    for value in (block["ttl_hours"] * 3600, 30, None):
        payload = json.loads(json.dumps(raw))
        if value is None:
            payload["tutor_pipeline"]["idempotency"].pop("in_progress_lease_seconds")
        else:
            payload["tutor_pipeline"]["idempotency"]["in_progress_lease_seconds"] = value
        with pytest.raises(ConfigPackageError):
            parse_config_package(payload, path=PACKAGE.path, sha256="", hash_verified=False)


# ============================================================================================================ E8


def test_e8_the_text_helpers_say_the_subset_check_never_folds():
    source = (API_ROOT / "app" / "services" / "tutor_pipeline" / "text.py").read_text(encoding="utf-8")
    docstring = source.split('"""')[1]
    assert "(binding and the subset check)" not in docstring and "never folds" in docstring
    package_check = (API_ROOT / "app" / "services" / "tutor_pipeline" / "package_check.py").read_text(encoding="utf-8")
    assert "a floor and a major-version" in package_check


# ============================================================================================================ E9


def test_e9_the_migration_names_the_worker_and_an_absolute_target():
    assert "scripts/verify_ledger.py --export" not in MIGRATION and "downgrade -1" not in MIGRATION
    assert "python -m app.workers.response_ledger --export" in MIGRATION
    assert f"downgrade {PHASE2_REVISION}" in MIGRATION
    conflict_22 = next(line for line in SPEC.splitlines() if line.startswith("**22. Plan G"))
    # The resolution states the current rule only; the superseded `downgrade -1` wording is in no current text.
    assert "scripts/verify_ledger.py --export" not in conflict_22 and "app.workers.response_ledger --export" in conflict_22
    assert "downgrade -1" not in conflict_22 and "--restore" in conflict_22 and "Corrected in" not in conflict_22
    assert "is measured by `verify_ledger.py --coverage-since`" not in SPEC
    assert "alembic -x allow_ledger_drop=true downgrade -1" not in RUNBOOK


# =========================================================================================================== E10


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": database_url, "ENVIRONMENT": "development", "PYTHONUNBUFFERED": "1"}
    env.pop("CLOUD_SQL_CONNECTION_NAME", None)
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=API_ROOT, env=env, capture_output=True, text=True, timeout=180)


def _tables(engine) -> set[str]:
    """The application's tables (Alembic's own version table aside: a refused command may create it empty)."""
    try:
        return set(sa_inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def _stamp(engine) -> list[str]:
    try:
        with engine.connect() as connection:
            if "alembic_version" not in sa_inspect(connection).get_table_names():
                return []
            return [row[0] for row in connection.execute(text("SELECT version_num FROM alembic_version"))]
    finally:
        engine.dispose()


def test_e10_the_absolute_downgrade_target_is_safe_in_every_stamp_state_the_runbook_allows(fresh_database_url):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    downgrade = ("-x", "allow_ledger_drop=true", "downgrade", PHASE2_REVISION)
    factory, engine = fresh_sessions(fresh_database_url)  # create_all plus the schema upgrades, as a Phase 3 deploy does
    try:
        append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
        engine.dispose()
        everything = _tables(engine)
        # No stamp (Alembic never ran): the target is refused and nothing is dropped. "-1" would also fail here.
        refused = _alembic(fresh_database_url, *downgrade)
        assert refused.returncode != 0 and "not a valid downgrade target" in (refused.stdout + refused.stderr)
        assert _tables(engine) == everything and _stamp(engine) == []
        # Stamped at Phase 2 (its job ran, Phase 3's did not): a no-op. "-1" here reversed the Phase 2 revision and
        # dropped corpus_spans while the ledger stayed.
        assert _alembic(fresh_database_url, "stamp", PHASE2_REVISION).returncode == 0
        assert _alembic(fresh_database_url, *downgrade).returncode == 0
        assert _tables(engine) == everything and _stamp(engine) == [PHASE2_REVISION]
        # The runbook's path for a create_all schema: compare it with the models, stamp the Phase 3 revision, then go down.
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata) == []
        engine.dispose()
        assert _alembic(fresh_database_url, "stamp", PHASE3_REVISION).returncode == 0
        checked = _alembic(fresh_database_url, "check")  # the runbook's comparison once stamped: nothing pending
        assert checked.returncode == 0 and "No new upgrade operations detected" in (checked.stdout + checked.stderr), checked.stderr[-2000:]
        kept = _alembic(fresh_database_url, "downgrade", PHASE2_REVISION)
        assert kept.returncode != 0 and "export first" in kept.stderr and "app.workers.response_ledger --export" in kept.stderr
        assert _tables(engine) == everything
        dropped = _alembic(fresh_database_url, *downgrade)
        assert dropped.returncode == 0, dropped.stderr[-2000:]
        assert _tables(engine) == everything - PHASE3_TABLES and "corpus_spans" in _tables(engine) and _stamp(engine) == [PHASE2_REVISION]
    finally:
        engine.dispose()


def test_e10_alembic_connects_through_the_cloud_sql_connector_and_the_runbook_checks_the_stamp():
    env_source = (API_ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "settings.cloud_sql_connection_name" in env_source and "from app.core.db import engine as connectable" in env_source
    rollback = RUNBOOK.split("**Roll back**", 1)[1]
    assert "alembic current" in rollback and f"downgrade {PHASE2_REVISION}" in rollback and "downgrade -1" not in rollback
    assert "A digest rollback needs no downgrade" in rollback and "alembic check" in rollback
    assert "CLOUD_SQL_CONNECTION_NAME" in rollback


# =========================================================================================================== E11


def test_e11_the_kill_switch_writes_nothing_and_changes_nothing_on_the_tutor_surface(monkeypatch, clean_metrics):
    headers = demo("e11")
    on = orchestrator_for(Settings())
    off = orchestrator_for(Settings(tutor_ledger_enabled=False))
    for route, body in (("/assistant/chat", {"message": "Why does routing depth matter?"}), ("/tutor/turns", {"message": "Why does routing depth matter?"})):
        monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda: on)
        reference = client.post(route, headers=fresh(headers), json=body)
        before = LEDGER_METRICS.snapshot()
        monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda: off)
        switched = client.post(route, headers=fresh(headers), json=body)
        assert reference.status_code == switched.status_code == 200, route
        assert records(response_id=reference.json()["turn_id"]) and records(response_id=switched.json()["turn_id"]) == []
        assert records(shadowed_response_id=switched.json()["turn_id"]) == []  # the shadow is off with the ledger (effective mode)
        assert LEDGER_METRICS.snapshot() == before, route  # no attempt, append or failure counted
        assert without_ids(switched.json()) == without_ids(reference.json()), route
        for name in HEADER_SUBSET:
            assert switched.headers.get(name) == reference.headers.get(name), (route, name)


# =========================================================================================================== E12


def _drop_and_recreate_the_ledger(engine) -> None:
    tables = [Base.metadata.tables[name] for name in ("response_ledger_head", "response_ledger")]
    Base.metadata.drop_all(engine, tables=tables)
    Base.metadata.create_all(engine, tables=tables)
    run_schema_upgrades(engine)


def test_e12_an_exported_ledger_restores_byte_for_byte_and_its_logged_head_still_verifies(fresh_database_url, tmp_path, monkeypatch):
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        for delivery in ("legacy", "shadow", "legacy"):
            last = append_ledger_entry(make_entry(delivery=delivery), session_factory=factory, budget_ms=5000)
        export = tmp_path / "ledger-export.jsonl"
        with factory() as db:
            assert export_ledger(db, export) == 3
            before = [(row.seq, row.entry, row.entry_sha256, row.prev_hash, row.record_hash) for row in db.scalars(select(ResponseLedgerRecord).order_by(ResponseLedgerRecord.seq))]
        _drop_and_recreate_the_ledger(engine)  # what the allow_ledger_drop downgrade and a re-applied upgrade leave
        with factory() as db:
            assert restore_ledger(db, export) == (3, (3, last.record_hash))
        with factory() as db:
            after = [(row.seq, row.entry, row.entry_sha256, row.prev_hash, row.record_hash) for row in db.scalars(select(ResponseLedgerRecord).order_by(ResponseLedgerRecord.seq))]
            assert after == before
            check = verify_response_ledger(db, expected_head=(3, last.record_hash))
            assert check.ok and check.head_row == (3, last.record_hash)
            # The restored chain keeps its own start: its first record's time.
            assert ledger_started_at(db) == min(ledger._utc(row.created_at) for row in db.scalars(select(ResponseLedgerRecord)))
            with pytest.raises(LedgerRestoreRefused, match="already holds records"):
                restore_ledger(db, export)
        appended = append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
        assert appended.seq == 4  # appends continue the restored chain
        # The in-image worker runs the same restore, then the usual check against the exported head.
        _drop_and_recreate_the_ledger(engine)
        monkeypatch.setattr(ledger_worker, "SessionLocal", factory)
        assert ledger_worker.main(["--restore", str(export), "--expect-head", f"3:{last.record_hash}"]) == 0
        assert ledger_worker.main(["--restore", str(export)]) == 1  # refused: no longer empty
        assert ledger_worker.main(["--restore", str(export), "--export", str(tmp_path / "x.jsonl")]) == 2
    finally:
        engine.dispose()


@pytest.mark.parametrize("tamper", ["entry", "record_hash", "gap", "not_json"])
def test_e12_a_tampered_export_is_refused_and_nothing_is_written(fresh_database_url, tmp_path, tamper):
    factory, engine = fresh_sessions(fresh_database_url)
    try:
        for _ in range(3):
            append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
        export = tmp_path / "ledger-export.jsonl"
        with factory() as db:
            export_ledger(db, export)
        lines = export.read_text(encoding="utf-8").splitlines()
        second = json.loads(lines[1])
        if tamper == "entry":
            second["entry"] = second["entry"].replace("Routing", "Rerouting")
            lines[1] = json.dumps(second)
        elif tamper == "record_hash":
            second["record_hash"] = "f" * 64
            lines[1] = json.dumps(second)
        elif tamper == "gap":
            del lines[1]
        else:
            lines[1] = "{not json"
        export.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _drop_and_recreate_the_ledger(engine)
        with factory() as db:
            with pytest.raises(LedgerRestoreRefused):
                restore_ledger(db, export)
        with factory() as db:
            assert db.scalar(select(ResponseLedgerRecord.seq).limit(1)) is None and ledger.chain_head(db) in (None, (0, GENESIS_HASH))
    finally:
        engine.dispose()


def test_e12_the_runbook_says_what_the_drop_costs_and_how_the_export_is_retired():
    rollback = RUNBOOK.split("**Roll back**", 1)[1]
    assert "--restore" in rollback and "retired chain" in rollback and "owner decision" in rollback
    assert "is optional" in rollback or "needs no downgrade" in rollback
    # The deletion rule is reachable: restore, then the exported head verifies.
    assert "once `python -m app.workers.response_ledger --restore" in rollback


# =========================================================================================================== E13


def _events(caplog, name: str) -> list[dict]:
    return [record.json_fields for record in caplog.records if getattr(record, "json_fields", {}).get("event") == name]


def test_e13_every_committed_delivery_logs_an_attempt_and_qa_lines_say_their_surface(caplog, clean_metrics):
    headers = demo("e13")
    with caplog.at_level(logging.INFO, logger="qcai.tutor"):
        assert client.post("/assistant/chat", headers=fresh(headers), json={"message": IN_DOMAIN}).status_code == 200
        tutor_attempts, tutor_appends = _events(caplog, "tutor.ledger.attempted"), [e for e in _events(caplog, "tutor.ledger.appended") if e["delivery"] == "legacy"]
        # Spec 18.8 F1 and F11: the attempted line also says what was delivered and names its attempt, and the
        # attempt's terminal line carries the same id.
        assert len(tutor_attempts) == 1 and len(tutor_appends) == 1
        attempt = dict(tutor_attempts[0])
        assert attempt.pop("attempt") == tutor_appends[0]["attempt"]
        assert attempt.pop("decision") in {"answer", "abstain"} and set(attempt) == {"event", "delivery", "abstention_reason"}
        assert (attempt["event"], attempt["delivery"]) == ("tutor.ledger.attempted", "legacy")
        assert "surface" not in tutor_appends[0]
        caplog.clear()
        assert client.post("/qa/ask", headers=fresh(headers), json={"question": IN_DOMAIN}).status_code == 200
        (qa_attempt,) = _events(caplog, "tutor.ledger.attempted")
        (qa_append,) = _events(caplog, "tutor.ledger.appended")
        assert (qa_attempt["delivery"], qa_attempt["surface"], qa_attempt["attempt"]) == ("legacy", "qa", qa_append["attempt"])
        assert qa_append["surface"] == "qa" and qa_append["delivery"] == "legacy"


def test_e13_the_observability_tables_measure_coverage_and_name_every_stop_signal():
    phase3 = OBSERVABILITY.split("## Phase 3 SLIs", 1)[1]
    assert "| Ledger write failures (0) |" in phase3 and "| Ledger coverage (100%) | `jsonPayload.event=\"tutor.ledger.append_failed\"`" not in phase3
    coverage = next(line for line in phase3.splitlines() if line.startswith("| Ledger coverage (100%)"))
    assert "tutor.ledger.attempted" in coverage and "tutor.ledger.appended" in coverage and "surface" in coverage
    assert any(line.startswith("| Deferred appends") and "tutor.ledger.append_deferred" in line for line in phase3.splitlines())
    assert any(line.startswith("| Non-public spans excluded") and "tutor.evidence.non_public_excluded" in line for line in phase3.splitlines())
    integrity = next(line for line in phase3.splitlines() if line.startswith("| Chain integrity"))
    assert 'resource.type="cloud_run_job"' in integrity
    for field in ("tutor_ledger_enabled", "ledger_route_enabled", "evidence_panel_enabled", "tutor_turns_route_enabled"):
        assert f"`{field}`" in phase3, field
    assert "| `tutor.ledger.attempted` |" in phase3


# =========================================================================================================== E14


def test_e14_the_spec_says_what_the_code_and_the_page_do_now():
    conflict_29 = next(line for line in SPEC.splitlines() if "under a total deadline" in line)
    assert "ledger_wait_grace_ms" in conflict_29 and "(default 1500)" not in conflict_29 and "Corrected in" not in conflict_29
    # The superseded constant survives in no current text: only the review history may name it.
    assert "LEGACY_WAIT_GRACE_MS" not in SPEC.split("### 18.4 Review history", 1)[0]
    section_12 = SPEC.split("## 12. Frontend", 1)[1].split("## 13. Tests", 1)[0]
    row = next(line for line in section_12.splitlines() if "MOD `src/lib/privacy-disclosures.ts`" in line)
    for needed in ("can be matched to the learner's Q&A history while it is kept", "deleting the account deletes the tutor turns and the Q&A history",
                   "older than one year", "Kept as an audit record; the retention period is an open owner decision."):
        assert needed in row, needed
    assert "tutor history removes the link" not in row and "Superseded" not in row
    assert "`abstain`: \"No answer: no approved course passage matched this question closely enough\"" in section_12


# =========================================================================================================== E15


def test_e15_public_ready_carries_no_shadow_field_that_changes_with_a_runs_outcome(clean_metrics):
    LICENSE_METRICS.reset()
    before = client.get("/ready").json()["slis"]
    response = client.post("/assistant/chat", headers=fresh(demo("e15")), json={"message": IN_DOMAIN})
    assert response.status_code == 200
    after = client.get("/ready").json()["slis"]
    assert set(after["two_pass_shadow"]) == set(PUBLIC_SHADOW_FIELDS) == {"scheduled", "phase2_bound_claim_ratio_baseline"}
    ledger_block = after["tutor_ledger"]
    assert set(ledger_block["attempted"]) == set(ledger_block["appended"]) == set(ledger_block["failed"]) == {"legacy"}
    assert set(ledger_block["non_public_spans_excluded"]) == {"legacy", "qa"}
    # Only what the turn itself did changes: one shadow scheduled, one legacy record.
    assert after["two_pass_shadow"]["scheduled"] == before["two_pass_shadow"]["scheduled"] + 1
    assert ledger_block["appended"]["legacy"] == before["tutor_ledger"]["appended"]["legacy"] + 1
    # The shadow's outcome stays in process.
    detail = TWO_PASS_METRICS.snapshot(PARAMS.phase2_bound_claim_ratio)
    assert {"completed", "failed", "bound_claim_ratio_stop"} <= set(detail) and LEDGER_METRICS.snapshot()["attempted"]["shadow"] >= 0
    for hidden in ("completed", "failed", "bound_claim_ratio_stop", "decisions", "bound_claim_ratio"):
        assert hidden not in after["two_pass_shadow"]
    assert "/ready` `slis.two_pass_shadow` holds only `scheduled` and `phase2_bound_claim_ratio_baseline`" in OBSERVABILITY
