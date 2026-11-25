"""Phase 8 pure planner tests using synthetic, course-local state."""

import pytest

from app.services.learner_record_planner import LearnerPresentation, PLANNER_VERSION, plan_presentation


CONSENT_TEST_COURSE = ("first", "second", "third")


def _seed_adaptable_assessments(db, owner):
    from app.db_models import LearnerAssessmentFact, QuizAttempt

    attempts = [QuizAttempt(user_id=owner, lesson_slug=slug, score=0, responses={}) for slug in CONSENT_TEST_COURSE]
    db.add_all(attempts)
    db.flush()
    db.add_all(
        LearnerAssessmentFact(attempt_id=attempt.id, user_id=owner, lesson_slug=attempt.lesson_slug, mastery=mastery)
        for attempt, mastery in zip(attempts, (0.7, 0.1, 0.1), strict=True)
    )
    db.flush()


@pytest.mark.parametrize(
    ("mastery", "expected"),
    [(0.1, "stepwise"), (0.4, "concise"), (0.5, "concise"), (0.75, "socratic"), (0.9, "socratic")],
)
def test_phase8_planner_uses_the_provisional_mastery_bands(mastery, expected):
    result = plan_presentation(
        ("intro", "next"),
        server_mastery={"intro": mastery, "unrelated": 1.0},
        completed_lessons=set(),
        attempt_counts={},
        default_plan="concise",
        adaptation_allowed=True,
    )
    assert (result.plan_id, result.lesson_order, result.planner_version) == (
        expected,
        ("intro", "next"),
        PLANNER_VERSION,
    )


def test_phase8_planner_preserves_unfinished_order_and_prioritizes_review():
    result = plan_presentation(
        ("intro", "a", "review", "b", "practice", "closing"),
        server_mastery={"intro": 0.8, "review": 0.2, "practice": 0.2, "closing": 0.2},
        completed_lessons={"intro", "practice", "review", "closing", "unrelated"},
        attempt_counts={"review": 1, "practice": 3, "closing": 3},
        default_plan="socratic",
        adaptation_allowed=True,
    )
    assert result.lesson_order == ("a", "b", "practice", "closing", "review", "intro")


@pytest.mark.parametrize(
    ("allowed", "mastery"),
    [(False, {"intro": 0.9}), (True, {}), (True, {"intro": float("nan")})],
)
def test_phase8_planner_uses_static_order_without_consent_or_valid_mastery(allowed, mastery):
    result = plan_presentation(
        ("intro", "next"),
        server_mastery=mastery,
        completed_lessons={"intro"},
        attempt_counts={"intro": 2},
        default_plan="concise",
        adaptation_allowed=allowed,
    )
    assert (result.plan_id, result.lesson_order) == ("concise", ("intro", "next"))


@pytest.mark.parametrize("consent", ["missing", "withdrawn", "older-version", "current"])
def test_plan_j_planner_without_adaptation_consent_serves_the_static_order(consent):
    from uuid import uuid4

    from app.core.config import Settings
    from app.core.db import SessionLocal
    from app.db_models import LearnerConsent
    from app.services.learner_record_privacy import set_consent
    from app.services.learner_record_shadow import shadow_presentation

    settings = Settings(_env_file=None, environment="development")
    principal = f"demo-{uuid4().hex}"
    order = CONSENT_TEST_COURSE
    expected = LearnerPresentation("stepwise", (*order[1:], order[0])) if consent == "current" else (
        LearnerPresentation("concise", order)
    )
    with SessionLocal() as db:
        _seed_adaptable_assessments(db, principal)
        if consent != "missing":
            assert set_consent(db, "demo", principal, "adaptation", True, settings)["adaptation"]
        if consent == "withdrawn":
            assert not set_consent(db, "demo", principal, "adaptation", False, settings)["adaptation"]
        elif consent == "older-version":
            db.get(LearnerConsent, (principal, "adaptation")).consent_version = "older-fixture-version"
            db.flush()
        else:
            assert (db.get(LearnerConsent, (principal, "adaptation")) is None) == (consent == "missing")
        assert shadow_presentation(db, "demo", principal, order, "concise") == expected


@pytest.mark.parametrize("condition", ["fault", "slow", "sql", "off", "no-consent", "wall-clock-delay"])
def test_plan_j_planner_down_timeout_or_flag_off_serves_the_static_order_and_logs_degraded(monkeypatch, caplog, condition):
    from time import sleep
    from types import SimpleNamespace
    from uuid import uuid4

    from sqlalchemy import text

    from app.core.auth import AuthUser
    from app.core.config import Settings
    from app.core.config_package import get_config_package
    from app.core.db import SessionLocal
    from app.core.structured_logging import FIELDS
    from app.services import learner_record_shadow, tutor_orchestrator

    settings = Settings(_env_file=None, learner_planner="off" if condition == "off" else "shadow")
    package = get_config_package(settings)
    model = tutor_orchestrator.TutorOrchestrator(None, settings)
    monkeypatch.setattr(model, "_store", lambda: SimpleNamespace(lessons=dict.fromkeys(CONSENT_TEST_COURSE)))
    seen = []
    presentations = []
    original = learner_record_shadow.shadow_presentation

    def planner(db, *args):
        seen.append(condition)
        if condition == "fault":
            raise RuntimeError("fixture fault")
        if condition == "sql":
            db.execute(text("SELECT 1 FROM phase8_missing_fixture_table"))
        if condition == "wall-clock-delay":
            sleep(0.2)
        presentation = original(db, *args)
        presentations.append(presentation)
        return presentation

    monkeypatch.setattr(learner_record_shadow, "shadow_presentation", planner)
    if condition == "slow":
        clock = iter([0, 1])
        monkeypatch.setattr(learner_record_shadow, "planner_clock", lambda: next(clock, 1))
    else:
        monkeypatch.setattr(learner_record_shadow, "planner_clock", lambda: 0.0)
    principal = f"demo-{uuid4().hex}"
    default_plan = package.tutor_pipeline.default_plan
    with SessionLocal() as db:
        if condition == "no-consent":
            _seed_adaptable_assessments(db, principal)
        result = model._shadow_followup("turn-fixture", "thread-fixture", "message-fixture", None, None,
                                       db=db, learner=AuthUser(principal, None, "learner", "demo"))
        assert result is not None and result.presentation.plan_id == default_plan
        assert db.scalar(text("SELECT 1")) == 1
    if condition == "no-consent":
        assert presentations == [LearnerPresentation(default_plan, CONSENT_TEST_COURSE)]
    assert seen == ([] if condition == "off" else [condition])
    degraded = [getattr(row, FIELDS) for row in caplog.records if
                getattr(row, FIELDS, {}).get("event") == "learner.planner.degraded"]
    assert len(degraded) == int(condition in {"fault", "slow", "sql"})
    assert all(set(row) == {"event", "error"} for row in degraded)


def test_phase8_shadow_planner_failure_leaves_the_http_answer_and_job_intact(monkeypatch):
    from uuid import uuid4

    from fastapi.testclient import TestClient

    from app.api.routes import assistant
    from app.core.config import get_settings
    from app.core.config_package import get_config_package
    from app.main import app
    from app.services import learner_record_shadow

    def fault(*args):
        raise RuntimeError("fixture fault")

    jobs = []
    monkeypatch.setattr(learner_record_shadow, "shadow_presentation", fault)
    monkeypatch.setattr(assistant, "run_turn_followups", lambda response, *_: jobs.append(response._followups.shadow))
    settings = get_settings()
    browser = TestClient(app)
    bodies = []
    for mode in ("off", "shadow"):
        monkeypatch.setattr(settings, "learner_planner", mode)
        headers = {"x-demo-user": f"fixture-{uuid4().hex}", "x-demo-role": "learner"}
        response = browser.post("/assistant/chat", json={"message": "Why does routing depth matter?"}, headers=headers)
        assert response.status_code == 200
        value = response.json()
        assert browser.get(f"/assistant/threads/{value['thread_id']}", headers=headers).status_code == 200
        bodies.append(value)
    common = {"thread_id", "turn_id", "message_id", "created_at"}
    assert [{k: v for k, v in body.items() if k not in common} for body in bodies][0] == {
        k: v for k, v in bodies[1].items() if k not in common
    }
    default = get_config_package(settings).tutor_pipeline.default_plan
    assert [job.presentation.plan_id for job in jobs] == [default, default]


def test_plan_d_task_3_the_planner_ignores_client_and_self_rated_mastery(monkeypatch, fresh_database_url):
    from types import SimpleNamespace
    from uuid import uuid4

    from fastapi import Request
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.api.routes import content
    from app.core.auth import AuthUser
    from app.core.config import Settings, get_settings
    from app.db_models import Base, LearnerAssessmentFact, LearnerProfile, LearnerRecord
    from app.schemas import QuizAttemptCreate
    from app.services.learner_record_privacy import set_consent
    from app.services.learner_record_shadow import shadow_presentation

    principal = f"fixture-{uuid4().hex}"
    order = ("first", "second")
    settings = get_settings()
    monkeypatch.setattr(settings, "learner_identity", "off")
    monkeypatch.setattr(settings, "learner_sync", "on")
    store = SimpleNamespace(lessons={"first": object()}, quiz_keys=SimpleNamespace(for_lesson=lambda _: list(range(10))))
    monkeypatch.setattr(content, "get_course_store", lambda: store)
    monkeypatch.setattr(content, "score_attempt", lambda *_: (1, {}, []))
    engine = create_engine(fresh_database_url)
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            set_consent(db, "auth0", principal, "adaptation", True, Settings(_env_file=None))
            db.add(LearnerRecord(user_id=principal, mastery={"lesson:first": 0.9}))
            db.add(LearnerProfile(user_id=principal, self_ratings={"first": 0.9}))
            db.commit()
            plan = shadow_presentation(db, "auth0", principal, order, "concise")
            assert (plan.plan_id, plan.lesson_order) == ("concise", order)
            assert db.query(LearnerAssessmentFact).count() == 0
            attempt = content.record_quiz_attempt(
                Request({"type": "http", "method": "POST", "path": "/content/quiz-attempts"}),
                QuizAttemptCreate(lesson_slug="first", responses={}), db, AuthUser(principal, None, "learner", "auth0"),
            )
            assert db.get(LearnerAssessmentFact, attempt.attempt_id).mastery == 0.1
            assert shadow_presentation(db, "auth0", principal, order, "concise").plan_id == "stepwise"
    finally:
        engine.dispose()
