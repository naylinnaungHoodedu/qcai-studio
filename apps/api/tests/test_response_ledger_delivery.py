"""Phase 3: what the ledger records of each delivered response, and what the ledger route says of a turn without a
record (plan Phase 3 I; spec 4.12, 7.13, 11.3-11.4).

E5  a request that rolls back is never a ledger attempt, so it never lowers the coverage SLI.
E6  a turn without a record after the ledger began recording reads as a missing record; a turn from an image that
    keeps no ledger is a legacy turn.
E11 TUTOR_LEDGER_ENABLED=false writes nothing and changes nothing on the tutor surface.
E13 every committed delivery logs an attempted line, and the Q&A lines say their surface.
F1  plan I "abstention by reason" over delivered responses: a legacy record keeps the gate's own reason and
    sufficiency, and the attempted line and public /ready count delivered decisions by reason.
F10 the ledger route ignores start-up time.
F11 every legacy attempt ends in exactly one terminal log line carrying its attempt id.
F12 each turn says whether it expects a record, so a kill-switch turn is not a lost record.
Each test fails if its defect comes back; the spec's review history (18.4) names the round behind each group.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
import json
import logging
from pathlib import Path
import re
import threading
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import assistant as assistant_route
from app.api.routes import qa as qa_route
from app.core.config import Settings
from app.core.db import Base, SessionLocal, get_db
from app.core.schema_upgrades import run_schema_upgrades
from app.db_models import ResponseLedgerRecord, TutorThread, TutorTurn
from app.main import app
from app.services import ledger
from app.services.content_assembler import CourseStore
from app.services.ledger import LedgerAppendError, LegacyDelivery, LegacyPreparationFailed, delivered_abstention_reason, record_legacy_delivery
from app.services.qa_engine import QAEngine
from app.services.retrieval_engine import RetrievalEngine
from app.services.store import get_course_store, get_retrieval_engine
from app.services.teaching_assistant import TeachingAssistantService
from app.services.tutor_orchestrator import TutorOrchestrator
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline.metrics import LEDGER_METRICS, TWO_PASS_METRICS


IN_DOMAIN = "How does graph shrinking reduce routing overhead?"
HEADER_SUBSET = ("content-type", "cache-control", "x-assistant-provider", "x-assistant-model")
client = TestClient(app)
API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
OBSERVABILITY = (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8")
REPO_MANIFEST = REPO_ROOT / "corpus" / "public" / "manifest.json"
FLOOR_MISS = "What is the capital of France?"
STOPWORDS_ONLY = "the and of"


def demo(prefix: str, role: str = "learner") -> dict[str, str]:
    return {"x-demo-user": f"{prefix}-{uuid4().hex[:12]}", "x-demo-role": role, "x-forwarded-for": f"ledger-delivery-{uuid4().hex}"}


def fresh(headers: dict[str, str]) -> dict[str, str]:
    # A distinct client address per request keeps the per-address limits apart.
    return {**headers, "x-forwarded-for": f"ledger-delivery-{uuid4().hex}"}


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


@pytest.fixture
def clean_metrics():
    LEDGER_METRICS.reset()
    TWO_PASS_METRICS.reset()
    yield
    LEDGER_METRICS.reset()
    TWO_PASS_METRICS.reset()


def _events(caplog, name: str) -> list[dict]:
    return [dict(record.json_fields) for record in caplog.records if getattr(record, "json_fields", {}).get("event") == name]


def fresh_sessions(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False), engine


def _legacy(response_id: str | None = None) -> LegacyDelivery:
    return LegacyDelivery(
        response_id=response_id or f"turn-{uuid4()}", decision="abstain", reason="no_approved_span", claims=(), quoted=(), retrieved=None,
        answer_sha256="c" * 64, retrieval_mode="lexical-extractive-lexically-screened", provider="none", model="extractive-lexically-screened",
        corpus_version="corpus-test", index_version="index-test", gate="p1-floor", threshold_version="score-floor-p1-v1", floor=6.0, margin=0.0,
        policy_version="cs595-v1",
    )


def _turn(db: Session, thread: TutorThread, *, expected: bool | None, age: timedelta = timedelta(0)) -> str:
    turn_id = f"turn-{uuid4()}"
    db.add(TutorTurn(id=turn_id, thread_id=thread.id, user_id=thread.user_id, resolved_query="q", retrieval_mode="lexical", provider="none",
                     model="m", decision="abstain", decision_reason="no_approved_span", citations=[], claims=[], corpus_version="c",
                     policy_version="p", created_at=datetime.now(UTC) - age, ledger_record_expected=expected))
    return turn_id


# =============================================================================================================== E5


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


# =============================================================================================================== E6


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


# ============================================================================================================== E11


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


# ============================================================================================================== E13


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


# =============================================================================================================== F1


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


# ============================================================================================================== F10


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


# ============================================================================================================== F11


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


# ============================================================================================================== F12


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
