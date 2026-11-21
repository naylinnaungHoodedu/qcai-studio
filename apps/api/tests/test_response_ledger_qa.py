"""Phase 3: the Q&A surface's ledger records (plan task 3.8; R-22; spec 4.12).

C8  every /qa/ask delivery is ledgered, bounded and fail-open, with no learner text or identifier: the response is byte
    identical with the ledger on, off or failing, and erasure leaves an unlinkable record only a reviewer reads.
Each test fails if its defect comes back; the spec's review history (18.4) names the round behind each group.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from app.api.routes import qa as qa_route
from app.core.config import Settings
from app.core.db import SessionLocal
from app.db_models import QAInteraction, ResponseLedgerRecord
from app.main import app
from app.services import ledger
from app.services.erasure import erase_user
from app.services.ledger import verify_response_ledger
from app.services.qa_engine import QAEngine
from app.services.store import get_retrieval_engine
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline.contracts import sha256_hex
from app.services.tutor_pipeline.metrics import LEDGER_METRICS, LICENSE_METRICS

from tutor_fakes import FailingLedger


DATA = Path(__file__).parent / "data"
QUERIES = json.loads((DATA / "score_floor_queries.json").read_text(encoding="utf-8"))
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


@pytest.fixture
def clean_metrics():
    LEDGER_METRICS.reset()
    LICENSE_METRICS.reset()
    yield


# =============================================================================================================== C8


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
