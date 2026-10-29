from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.auth import AuthUser
from app.core.config import Settings
from app.core.corpus_governance import CorpusGovernanceError, CorpusRegistry
from app.core.db import SessionLocal
from app.db_models import TutorTurn
from app.main import app
from app.schemas import AssistantChatRequest, AssistantChatResponse, Citation, LearnerRecordOperationInput
from app.services.learner_record import apply_learner_record_operations, read_learner_record
from app.services.tutor_orchestrator import TutorOrchestrator


def _operation(operation_id: str, replica_id: str, counter: int, operation_type: str, payload: dict):
    return LearnerRecordOperationInput(
        operation_id=operation_id,
        replica_id=replica_id,
        logical_counter=counter,
        operation_type=operation_type,
        payload=payload,
    )


def test_learner_record_merges_divergent_replicas_without_losing_completion():
    user_id = f"record-{uuid4()}"
    with SessionLocal() as db:
        first = [
            _operation("op-alpha-mastery", "replica-alpha", 1, "mastery_set", {"skill_id": "routing", "value": 0.4}),
            _operation("op-alpha-complete", "replica-alpha", 2, "complete_item", {"item_id": "lesson:routing"}),
            _operation("op-alpha-attempt", "replica-alpha", 3, "increment_attempt", {"item_id": "lesson:routing"}),
            _operation("op-alpha-cursor", "replica-alpha", 4, "set_cursor", {"value": "lesson:routing"}),
        ]
        second = [
            _operation("op-beta-mastery", "replica-beta", 1, "mastery_set", {"skill_id": "routing", "value": 0.8}),
            _operation("op-beta-complete", "replica-beta", 2, "complete_item", {"item_id": "lesson:optimization"}),
            _operation("op-beta-attempt", "replica-beta", 3, "increment_attempt", {"item_id": "lesson:routing"}),
            _operation("op-beta-cursor", "replica-beta", 4, "set_cursor", {"value": "lesson:optimization"}),
        ]
        receipts, state = apply_learner_record_operations(db, user_id, [*second, *first])
        db.commit()

        assert {receipt["status"] for receipt in receipts} == {"applied"}
        assert state.mastery["routing"] == 0.8
        assert state.completed_item_ids == ["lesson:optimization", "lesson:routing"]
        assert state.attempt_counts["lesson:routing"] == 2
        assert state.cursor == "lesson:optimization"

        replay_receipts, replay_state = apply_learner_record_operations(db, user_id, list(reversed([*first, *second])))
        db.commit()
        assert {receipt["status"] for receipt in replay_receipts} == {"duplicate"}
        assert replay_state == state


def test_learner_record_rejects_payload_mutation_for_an_existing_operation_id():
    user_id = f"record-{uuid4()}"
    with SessionLocal() as db:
        apply_learner_record_operations(
            db,
            user_id,
            [_operation("op-replay", "replica-alpha", 1, "complete_item", {"item_id": "lesson:routing"})],
        )
        db.commit()
        with pytest.raises(HTTPException) as exc_info:
            apply_learner_record_operations(
                db,
                user_id,
                [_operation("op-replay", "replica-alpha", 1, "complete_item", {"item_id": "lesson:other"})],
            )
        assert exc_info.value.status_code == 409


def test_persistent_tutor_stores_resolved_follow_up_and_claim_provenance():
    class StubAssistant:
        def chat(self, _message: str, **_kwargs):
            return AssistantChatResponse(
                answer="unused local provider answer",
                citations=[
                    Citation(
                        chunk_id="routing-span-v1",
                        source_title="Routing source",
                        source_kind="document",
                        section_title="Routing overhead",
                        excerpt="Routing overhead grows when constrained hardware connectivity forces additional swap operations.",
                        source_filename="routing.docx",
                    )
                ],
                retrieval_mode="lexical",
                provider="local-grounded-fallback",
                model="test-model",
                grounded=True,
            )

    user = AuthUser(user_id=f"tutor-{uuid4()}", email="learner@example.edu", role="learner", provider="local")
    orchestrator = TutorOrchestrator(StubAssistant(), Settings())
    with SessionLocal() as db:
        first = orchestrator.chat(db, user, AssistantChatRequest(message="Why does routing overhead matter?"))
        second = orchestrator.chat(
            db,
            user,
            AssistantChatRequest(message="Why does that work?", thread_id=first.thread_id),
        )
        db.commit()

        assert first.thread_id == second.thread_id
        assert first.decision == "answer"
        assert first.grounded is False
        assert "unused local provider answer" not in first.answer
        assert "Routing overhead grows when constrained hardware connectivity" in first.answer
        assert first.claims and first.claims[0].cited_span_ids == ["routing-span-v1"]
        persisted = db.scalars(select(TutorTurn).where(TutorTurn.id == second.turn_id)).one()
        assert "Previous question: Why does routing overhead matter?" in persisted.resolved_query
        assert persisted.policy_version == "cs595-v1"


def test_tutor_delivers_no_generated_text_and_passes_no_learner_state():
    # D-19 / AC-1-14: a generated answer with only summary citations is withheld; no learner state is sent.
    received = {}

    class GeneratingAssistant:
        def chat(self, _message: str, **kwargs):
            received.update(kwargs)
            return AssistantChatResponse(
                answer="A confident generated paragraph that no span supports.",
                citations=[
                    Citation(chunk_id="v1", source_title="Lecture", source_kind="video", section_title="Ch 1", excerpt="An authored chapter summary."),
                    Citation(chunk_id="l1", source_title="Lesson", source_kind="lesson", section_title="Notes", excerpt="Authored lesson notes."),
                ],
                retrieval_mode="lexical",
                provider="vertex-ai-api-key",
                model="test-model",
                grounded=True,
            )

    user = AuthUser(user_id=f"tutor-{uuid4()}", email="learner@example.edu", role="learner", provider="local")
    with SessionLocal() as db:
        response = TutorOrchestrator(GeneratingAssistant(), Settings()).chat(db, user, AssistantChatRequest(message="Why?"))
        db.commit()

    assert response.decision == "abstain"
    assert response.grounded is False
    assert "confident generated paragraph" not in response.answer
    assert response.citations == []
    assert "pedagogical_context" not in received


def test_production_corpus_registry_requires_explicit_public_asset(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        """{
  \"schema_version\": \"1.0\",
  \"items\": [{
    \"id\": \"open-1\", \"version\": \"v1\", \"source\": \"Example\",
    \"license\": \"CC-BY-4.0\", \"permitted_use\": \"public\",
    \"public_service\": true, \"asset_filenames\": [\"open.docx\"]
  }]
}""",
        encoding="utf-8",
    )
    registry = CorpusRegistry(
        Settings(environment="production", enforce_corpus_governance=True, corpus_manifest_path=str(manifest))
    )
    registry.assert_public_assets_ready(["open.docx"])
    assert registry.is_public_asset("open.docx") is True
    with pytest.raises(CorpusGovernanceError):
        registry.assert_public_assets_ready(["restricted.docx"])


def test_learner_record_api_requires_a_durable_session_and_accepts_idempotent_operations():
    account_client = TestClient(app)
    email = f"record-{uuid4().hex[:12]}@example.edu"
    registered = account_client.post("/auth/register", json={"email": email, "password": "correct-horse-battery-staple"})
    assert registered.status_code == 201
    csrf = account_client.cookies.get("qcai_auth_csrf")
    response = account_client.post(
        "/learner-record/operations",
        headers={"origin": "http://localhost:3000", "x-qcai-csrf": csrf},
        json={
            "operations": [
                {
                    "operation_id": "op-api-route-1",
                    "replica_id": "replica-api-route",
                    "logical_counter": 1,
                    "operation_type": "complete_item",
                    "payload": {"item_id": "lesson:routing"},
                }
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["record"]["completed_item_ids"] == ["lesson:routing"]
    assert account_client.get("/learner-record").status_code == 200
    guest_response = TestClient(app).get("/learner-record", headers={"x-demo-user": "guest-test", "x-demo-role": "learner"})
    assert guest_response.status_code == 403
