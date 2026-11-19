"""Score floor for lexical search (plan Action 27, R-15, AC-1-11), approved as P1-D-04.

The question sets in data/score_floor_queries.json are the public fixtures measured in BEP-1/27_score_floor.

Phase 2: the P1 floor is the "p1-floor" gate, the default outside development, applied to the span index; the
development default is "bm25f-v1". The module-level tests run in development (bm25f-v1); the governed siblings
run the same assertions on the governed D-31 store with p1-floor, so AC-1-11 stays evidenced for what ships.
"""

import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

import pytest

from app.core.config import Settings
from app.core.config_package import canonical_sha256, get_config_package
from app.core.corpus_governance import get_corpus_registry
from app.main import _initialize_database, app
from app.services.contained_answers import ABSTENTION
from app.services.content_assembler import SCORE_FLOOR, SCORE_FLOOR_VERSION, CourseStore, IndexedChunk, _floor_score
from app.services.qa_engine import QAEngine
from app.services.retrieval_engine import RetrievalEngine
from app.services.retrieval_legacy_p1 import build_legacy_chunks, legacy_search
from app.services.store import get_course_store
from app.services.teaching_assistant import TeachingAssistantService


_initialize_database()
client = TestClient(app)
QUERIES = json.loads((Path(__file__).parent / "data" / "score_floor_queries.json").read_text(encoding="utf-8"))
REPO_MANIFEST = Path(__file__).resolve().parents[3] / "corpus" / "public" / "manifest.json"
GOVERNED = Settings(
    environment="production", enforce_corpus_governance=True, corpus_manifest_path=str(REPO_MANIFEST), retrieval_gate="p1-floor"
)


@pytest.fixture(scope="module")
def governed_store() -> CourseStore:
    # What a governed build serves under D-31: the committed manifest approves nothing, the shipped gate is p1-floor.
    store = CourseStore(GOVERNED)
    assert store.gate == "p1-floor" and store.chunks
    return store


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
    # The configuration package carries the same approved floor as the p1-floor gate.
    package = get_config_package(Settings())
    assert (package.p1_floor["floor"], package.p1_floor["version"]) == (SCORE_FLOOR, SCORE_FLOOR_VERSION)
    # The bm25f-v1 floor and margin are the calibration record's selection, pinned by the record's hash.
    record = json.loads((Path(__file__).resolve().parents[3] / package.abstention.calibration_record).read_text(encoding="utf-8"))
    assert (package.abstention.floor, package.abstention.margin) == (record["selection"]["floor"], record["selection"]["margin"])
    assert package.abstention.calibration_record_sha256 == canonical_sha256(record)


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


def test_one_shared_word_does_not_return_a_passage_from_the_governed_p1_floor_store(governed_store):
    assert governed_store.search("What is the meaning of life?") == []
    assert governed_store.search("Define the word serendipity") == []
    assert governed_store.search("How do I train my dog to sit?") == []


def test_off_topic_and_stopword_only_questions_return_no_result_from_the_governed_p1_floor_store(governed_store):
    questions = QUERIES["off_topic"] + QUERIES["stopword_only"]

    leaked = [question for question in questions if governed_store.search(question, top_k=20)]

    assert len(questions) == 124
    assert leaked == []


def test_capital_of_france_abstains_on_the_governed_p1_floor_learner_paths(governed_store):
    question = "What is the capital of France?"
    engine = RetrievalEngine(governed_store, GOVERNED)

    assert governed_store.search(question) == []
    for response in (
        QAEngine(engine, GOVERNED).ask(question),
        TeachingAssistantService(engine, GOVERNED).chat(question),
    ):
        assert (response.decision, response.answer, response.citations) == ("abstain", ABSTENTION, [])


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


def _legacy_recall_at_5(chunks, score_floor: int) -> int:
    return sum(
        bool(set(item["expected_lessons"]) & {r.lesson_slug for r in legacy_search(chunks, item["query"], top_k=5, score_floor=score_floor)})
        for item in QUERIES["in_domain"]
    )


def test_floor_does_not_lower_in_domain_recall():
    # Action 27 stop condition "recall drops", measured against the ungated search in the same run, on the
    # algorithm Phase 1 approved (floor 6 against floor 0, every asset served as development serves them).
    # Phase 2 runs that algorithm from the frozen pre-migration module: patching content_assembler.SCORE_FLOOR no
    # longer reaches the development store (bm25f-v1), so the old patch would have passed without testing anything.
    # What ships outside development, p1-floor over the span index, is covered by test_phase2_acceptance (AC-2-5).
    settings = Settings()
    registry = get_corpus_registry(settings)
    chunks = build_legacy_chunks(settings, registry.served(settings.source_documents), registry.served(settings.source_videos))
    gated = _legacy_recall_at_5(chunks, SCORE_FLOOR)
    ungated = _legacy_recall_at_5(chunks, 0)

    assert len(QUERIES["in_domain"]) == 174
    assert gated >= ungated
