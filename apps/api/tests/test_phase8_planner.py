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
