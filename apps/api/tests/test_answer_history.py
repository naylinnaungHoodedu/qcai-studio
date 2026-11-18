"""Answers stored before containment are withheld from learners (R-16; plan section 5.3, task 1.11; Release R1.2).

The 2026-11-17 exit-gate re-assessment found /qa/history and the tutor threads re-serving answers that the
2026-04-05 build had generated and marked grounded. Those rows stay stored but are never shown again.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.db_models import QAInteraction, TutorMessage, TutorThread
from app.main import app
from app.services.answer_history import CONTAINMENT_STARTED_AT, WITHDRAWN_ANSWER, stored_before_containment
from app.services.tutor_orchestrator import TutorOrchestrator

BEFORE = datetime(2026, 4, 6, 9, 0, tzinfo=UTC)
AFTER = CONTAINMENT_STARTED_AT + timedelta(minutes=5)
OLD_ANSWER = "Routing depth is fully explained by the sources (grounded)."
OLD_CITATION = {
    "chunk_id": "doc-old-0001",
    "source_title": "Old source",
    "source_kind": "document",
    "section_title": "Old section",
    "excerpt": "An old excerpt.",
}


def _learner() -> tuple[str, dict[str, str]]:
    user_id = f"history-{uuid4().hex[:10]}"
    return user_id, {"x-demo-user": user_id, "x-demo-role": "learner", "x-forwarded-for": f"203.0.113.{uuid4().int % 250 + 1}"}


@pytest.mark.parametrize(
    ("created_at", "withheld"),
    [
        (BEFORE, True),
        (CONTAINMENT_STARTED_AT - timedelta(seconds=1), True),
        (CONTAINMENT_STARTED_AT, False),
        (AFTER, False),
        (BEFORE.replace(tzinfo=None), True),  # SQLite returns naive UTC values
        (AFTER.replace(tzinfo=None), False),
        (None, True),
    ],
)
def test_an_answer_is_withheld_only_when_stored_before_containment(created_at, withheld):
    assert stored_before_containment(created_at) is withheld


def test_qa_history_withholds_pre_containment_answers_and_their_citations():
    user_id, headers = _learner()
    lesson = "ai4qc-routing-and-optimization"
    with SessionLocal() as db:
        db.add_all(
            [
                QAInteraction(user_id=user_id, lesson_slug=lesson, question="Old question?", answer=OLD_ANSWER, citations=[OLD_CITATION], created_at=BEFORE),
                QAInteraction(user_id=user_id, lesson_slug=lesson, question="New question?", answer="A contained answer.", citations=[], created_at=AFTER),
            ]
        )
        db.commit()

    response = TestClient(app).get("/qa/history", params={"lesson_slug": lesson, "limit": 5}, headers=headers)

    assert response.status_code == 200
    new, old = response.json()
    assert (new["question"], new["answer"], new["withdrawn"]) == ("New question?", "A contained answer.", False)
    assert (old["question"], old["answer"], old["citations"], old["withdrawn"]) == ("Old question?", WITHDRAWN_ANSWER, [], True)
    assert OLD_ANSWER not in response.text and "doc-old-0001" not in response.text


def _thread_with_old_and_new_replies(user_id: str) -> str:
    thread_id = f"thread-{uuid4()}"
    with SessionLocal() as db:
        db.add(TutorThread(id=thread_id, user_id=user_id, title="Routing", created_at=BEFORE, updated_at=AFTER))
        db.flush()  # the thread row must exist before its messages (foreign key)
        db.add_all(
            [
                TutorMessage(id=f"message-{uuid4()}", thread_id=thread_id, role="user", content="Old question?", created_at=BEFORE),
                TutorMessage(id=f"message-{uuid4()}", thread_id=thread_id, role="assistant", content=OLD_ANSWER, created_at=BEFORE + timedelta(seconds=1)),
                TutorMessage(id=f"message-{uuid4()}", thread_id=thread_id, role="user", content="New question?", created_at=AFTER),
                TutorMessage(id=f"message-{uuid4()}", thread_id=thread_id, role="assistant", content="A contained reply.", created_at=AFTER + timedelta(seconds=1)),
            ]
        )
        db.commit()
    return thread_id


def test_a_tutor_thread_withholds_pre_containment_replies_and_keeps_the_learners_messages():
    user_id, headers = _learner()
    thread_id = _thread_with_old_and_new_replies(user_id)

    response = TestClient(app).get(f"/assistant/threads/{thread_id}", headers=headers)

    assert response.status_code == 200
    messages = [(m["role"], m["content"], m["withdrawn"]) for m in response.json()["messages"]]
    assert messages == [
        ("user", "Old question?", False),
        ("assistant", WITHDRAWN_ANSWER, True),
        ("user", "New question?", False),
        ("assistant", "A contained reply.", False),
    ]
    assert OLD_ANSWER not in response.text


def test_a_withheld_reply_never_feeds_a_new_tutor_turn():
    user_id, _ = _learner()
    thread_id = _thread_with_old_and_new_replies(user_id)
    orchestrator = TutorOrchestrator(assistant=None, settings=get_settings())
    with SessionLocal() as db:
        thread = db.get(TutorThread, thread_id)
        _, history = orchestrator._resolve_query(db, thread, "And why?", [])

    assert [(item.role, item.content) for item in history] == [
        ("user", "Old question?"),
        ("user", "New question?"),
        ("assistant", "A contained reply."),
    ]


def test_a_new_tutor_thread_is_not_labelled_grounded():
    _, headers = _learner()
    response = TestClient(app).post("/assistant/threads", json={}, headers={**headers, "origin": "http://localhost:3000"})
    assert response.status_code in {200, 201}, response.text
    assert response.json()["title"] == "New Tutor thread"
