"""Phase 8 pure planner tests using synthetic, course-local state."""

import pytest

from app.services.learner_record_planner import PLANNER_VERSION, plan_presentation


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


@pytest.mark.parametrize("condition", ["fault", "slow", "sql", "off", "no-consent"])
def test_plan_j_planner_down_timeout_or_flag_off_serves_the_static_order_and_logs_degraded(monkeypatch, caplog, condition):
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
    monkeypatch.setattr(model, "_store", lambda: SimpleNamespace(lessons={"first": object()}))
    seen = []
    original = learner_record_shadow.shadow_presentation

    def planner(db, *args):
        seen.append(condition)
        if condition == "fault":
            raise RuntimeError("fixture fault")
        if condition == "sql":
            db.execute(text("SELECT 1 FROM phase8_missing_fixture_table"))
        return original(db, *args)

    monkeypatch.setattr(learner_record_shadow, "shadow_presentation", planner)
    if condition == "slow":
        clock = iter([0, 1])
        import time
        with monkeypatch.context() as timer:
            timer.setattr(time, "monotonic", lambda: next(clock, 1))
            _assert_shadow(model, package, uuid4, SessionLocal, AuthUser)
    else:
        _assert_shadow(model, package, uuid4, SessionLocal, AuthUser)
    assert seen == ([] if condition == "off" else [condition])
    degraded = [getattr(row, FIELDS) for row in caplog.records if
                getattr(row, FIELDS, {}).get("event") == "learner.planner.degraded"]
    assert len(degraded) == int(condition in {"fault", "slow", "sql"})
    assert all(set(row) == {"event", "error"} for row in degraded)


def _assert_shadow(model, package, uuid4, session_factory, auth_user):
    from sqlalchemy import text

    with session_factory() as db:
        result = model._shadow_followup("turn-fixture", "thread-fixture", "message-fixture", None, None,
                                       db=db, learner=auth_user(f"demo-{uuid4().hex}", None, "learner", "demo"))
        assert result is not None and result.presentation.plan_id == package.tutor_pipeline.default_plan
        assert db.scalar(text("SELECT 1")) == 1


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
