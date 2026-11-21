"""Quiz keys kept server-side (plan Phase 4 B "keyed answers outside public payloads"; R-42; Phase 4 spec 4.14, 7.7-7.8)."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.schemas import LessonDetail, QuizQuestion
from app.services.content_assembler import CourseStore
from app.services.quiz_keys import QuizKey, QuizKeySource, QuizKeyStore, score_attempt
from app.services.store import get_course_store

client = TestClient(app)


def _key(index: int, answer: str = "The answer text", explanation: str = "Why") -> QuizKey:
    return QuizKey(id=f"lesson-quiz-{index}", lesson_slug="lesson", question_type="short-answer", prompt=f"Prompt {index}", choices=(),
                   answer=answer, explanation=explanation)


def test_score_attempt_scores_exact_matches_and_gives_feedback_only_for_answered_questions():
    keys = (_key(1, "alpha beta"), _key(2, "gamma delta"), _key(3, "epsilon"))
    score, kept, feedback = score_attempt(keys, {"lesson-quiz-1": "alpha beta", "lesson-quiz-2": "wrong", "lesson-quiz-3": "  ",
                                                 "other": "ignored", "lesson-quiz-9": "x"})
    assert score == 1 and set(kept) == {"lesson-quiz-1", "lesson-quiz-2", "lesson-quiz-3"}
    assert [(item.question_id, item.answered, item.correct, item.answer) for item in feedback] == [
        ("lesson-quiz-1", True, True, "alpha beta"), ("lesson-quiz-2", True, False, "gamma delta"), ("lesson-quiz-3", False, None, None)]
    assert feedback[2].explanation is None
    long = score_attempt(keys, {"lesson-quiz-1": "x" * 5000})[1]
    assert len(long["lesson-quiz-1"]) == 2000
    assert score_attempt(keys, {"lesson-quiz-1": 7})[0] == 0 and score_attempt(keys, {"lesson-quiz-1": 7})[2][0].answered is False


def test_the_key_store_and_the_v1_6_source():
    store = QuizKeyStore([_key(1), QuizKey(id="other-quiz-1", lesson_slug="other", question_type="mcq", prompt="P", choices=("a", "b"),
                                          answer="b", explanation="b")])
    assert [key.id for key in store.for_lesson("lesson")] == ["lesson-quiz-1"] and store.for_lesson("none") == () and len(store) == 2
    items = QuizKeySource(store).items()
    assert [(item.item_id, item.answer, item.choices) for item in items] == [("lesson-quiz-1", "The answer text", ()), ("other-quiz-1", "b", ("a", "b"))]


def test_the_course_store_splits_public_questions_from_server_side_keys():
    store = get_course_store()
    keys = store.quiz_keys.all()
    assert len(keys) == 12 and len({key.lesson_slug for key in keys}) == 12
    assert set(QuizQuestion.model_fields) == {"id", "question_type", "prompt", "choices", "difficulty"}
    for slug, lesson in store.lessons.items():
        public = lesson.quiz_questions
        assert [question.id for question in public] == [key.id for key in store.quiz_keys.for_lesson(slug)]
        for question, key in zip(public, store.quiz_keys.for_lesson(slug)):
            assert (question.prompt, tuple(question.choices), question.question_type) == (key.prompt, key.choices, key.question_type)
            assert "answer" not in question.model_dump() and "explanation" not in question.model_dump()
    assert "answer" not in LessonDetail.model_json_schema()["$defs"]["QuizQuestion"]["properties"]


def test_the_module_route_serialises_lessons_without_keys():
    store = get_course_store()
    for slug in store.modules:
        body = client.get(f"/content/modules/{slug}").json()
        for lesson in body["lessons"]:
            for question in lesson["quiz_questions"]:
                assert set(question) == {"id", "question_type", "prompt", "choices", "difficulty"}


def test_rebuilding_the_content_keeps_both_halves():
    # admin/rebuild-content builds a new CourseStore through this same constructor (store.rebuild_course_store).
    import inspect

    from app.services import store as store_module

    assert "CourseStore(get_settings())" in inspect.getsource(store_module.get_course_store)
    assert "get_course_store()" in inspect.getsource(store_module.rebuild_course_store)
    before = [key.id for key in get_course_store().quiz_keys.all()]
    rebuilt = CourseStore(Settings())
    assert [key.id for key in rebuilt.quiz_keys.all()] == before
    assert all(lesson.quiz_questions for lesson in rebuilt.lessons.values())


def test_the_attempt_route_returns_feedback_for_answered_questions_only():
    store = get_course_store()
    slug = next(iter(store.lessons))
    keys = store.quiz_keys.for_lesson(slug)
    headers = {"x-demo-user": f"quiz-{uuid4().hex[:12]}", "x-demo-role": "learner", "x-forwarded-for": f"quiz-{uuid4().hex}"}
    response = client.post("/content/quiz-attempts", headers=headers, json={"lesson_slug": slug, "responses": {keys[0].id: keys[0].answer}})
    body = response.json()
    assert response.status_code == 200 and body["status"] == "saved" and body["score"] == 1
    assert [item["question_id"] for item in body["feedback"]] == [key.id for key in keys]
    assert body["feedback"][0] == {"question_id": keys[0].id, "answered": True, "correct": True, "answer": keys[0].answer, "explanation": keys[0].explanation}
