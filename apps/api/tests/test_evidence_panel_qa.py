"""Phase 3: the Q&A answer carries the evidence panel in development only (plan task 3.8; D-05; spec 12).

F3  the panel lists the answer's citations and never says grounded; with the switch off (its default outside
    development) the body is today's, byte for byte.
Each test fails if its defect comes back; the spec's review history (18.4) names the round behind each group.
"""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.routes import qa as qa_route
from app.core.config import Settings
from app.main import app
from app.services.qa_engine import QAEngine
from app.services.store import get_retrieval_engine


IN_DOMAIN = "How does graph shrinking reduce routing overhead?"
FLOOR_MISS = "What is the capital of France?"
client = TestClient(app)


def demo(prefix: str, role: str = "learner") -> dict[str, str]:
    return {"x-demo-user": f"{prefix}-{uuid4().hex[:12]}", "x-demo-role": role, "x-forwarded-for": f"review5-{uuid4().hex}"}


def fresh(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "x-forwarded-for": f"review5-{uuid4().hex}"}


# =============================================================================================================== F3


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
