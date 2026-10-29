"""Score floor for lexical search (plan Action 27, R-15, AC-1-11), approved as P1-D-04.

The question sets in data/score_floor_queries.json are the public fixtures measured in BEP-1/27_score_floor.
"""

import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import _initialize_database, app
from app.services import content_assembler
from app.services.contained_answers import ABSTENTION
from app.services.content_assembler import SCORE_FLOOR, SCORE_FLOOR_VERSION, IndexedChunk, _floor_score
from app.services.store import get_course_store


_initialize_database()
client = TestClient(app)
QUERIES = json.loads((Path(__file__).parent / "data" / "score_floor_queries.json").read_text(encoding="utf-8"))


def _chunk(title: str, excerpt: str) -> IndexedChunk:
    return IndexedChunk(
        chunk_id="lesson:doc:1",
        title=title,
        source_kind="document",
        source_title="Source",
        excerpt=excerpt,
        lesson_slug="lesson",
        score_boost=11.0,
    )


def test_floor_is_the_approved_value():
    # Changing either value needs a new measurement and approval (P1-D-04).
    assert (SCORE_FLOOR, SCORE_FLOOR_VERSION) == (6, "score-floor-p1-v1")


def test_floor_score_counts_whole_non_stopword_words_and_ignores_the_module_boost():
    chunk = _chunk("Nested Qubit Routing", "Routing adds SWAP gates, which increases circuit depth.")

    assert _floor_score({"routing"}, chunk, 0) == 5
    assert _floor_score({"routing", "depth"}, chunk, 0) == 7
    assert _floor_score({"rout"}, chunk, 0) == 0
    assert _floor_score({"routing"}, chunk, 4) == 9


def test_one_shared_word_does_not_return_a_passage():
    store = get_course_store()

    assert store.search("What is the meaning of life?") == []
    assert store.search("Define the word serendipity") == []
    assert store.search("How do I train my dog to sit?") == []


def test_off_topic_and_stopword_only_questions_return_no_result():
    # AC-1-11: the out-of-scope fixture returns no result above the floor.
    store = get_course_store()
    questions = QUERIES["off_topic"] + QUERIES["stopword_only"]

    leaked = [question for question in questions if store.search(question, top_k=20)]

    assert len(questions) == 124
    assert leaked == []


def test_capital_of_france_returns_nothing_from_search_and_abstains_on_learner_paths():
    question = "What is the capital of France?"
    search = client.get("/search", params={"query": question})
    assert search.status_code == 200
    assert search.json() == []

    headers = {"x-demo-user": f"floor-{uuid4().hex[:8]}", "x-demo-role": "learner"}
    for path, body in (("/qa/ask", {"question": question}), ("/assistant/chat", {"message": question})):
        response = client.post(path, headers=headers, json=body)
        assert response.status_code == 200
        data = response.json()
        assert data["decision"] == "abstain"
        assert data["answer"] == ABSTENTION
        assert data["citations"] == []


def _lesson_recall_at_5() -> int:
    store = get_course_store()
    return sum(
        bool(set(item["expected_lessons"]) & {result.lesson_slug for result in store.search(item["query"], top_k=5)})
        for item in QUERIES["in_domain"]
    )


def test_floor_does_not_lower_in_domain_recall(monkeypatch):
    # Action 27 stop condition "recall drops", measured against the ungated search in the same run.
    gated = _lesson_recall_at_5()
    monkeypatch.setattr(content_assembler, "SCORE_FLOOR", 0)
    ungated = _lesson_recall_at_5()

    assert len(QUERIES["in_domain"]) == 174
    assert gated >= ungated
