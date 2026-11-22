"""Deterministic pedagogical planning over server-scored learner state."""

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from math import fsum, isfinite
from typing import Literal


PlanId = Literal["concise", "stepwise", "socratic"]
PLANNER_VERSION = "learner-planner-v1"
FOUNDATION_THRESHOLD = 0.4
ADVANCED_THRESHOLD = 0.75


@dataclass(frozen=True, slots=True)
class LearnerPresentation:
    plan_id: PlanId
    lesson_order: tuple[str, ...]
    planner_version: str = PLANNER_VERSION


def plan_presentation(
    course_order: Sequence[str],
    *,
    server_mastery: Mapping[str, float],
    completed_lessons: Set[str],
    attempt_counts: Mapping[str, int],
    default_plan: PlanId,
    adaptation_allowed: bool,
) -> LearnerPresentation:
    """Choose a style and review order from course-local, trusted inputs."""
    static_order = tuple(course_order)
    if not adaptation_allowed:
        return LearnerPresentation(default_plan, static_order)

    observed = {}
    for lesson in static_order:
        score = server_mastery.get(lesson)
        if score is not None and isfinite(score) and 0 <= score <= 1:
            observed[lesson] = score
    if not observed:
        return LearnerPresentation(default_plan, static_order)

    average = fsum(observed.values()) / len(observed)
    plan_id: PlanId
    if average < FOUNDATION_THRESHOLD:
        plan_id = "stepwise"
    elif average < ADVANCED_THRESHOLD:
        plan_id = "concise"
    else:
        plan_id = "socratic"

    # Preserve the teaching sequence among unfinished lessons. For review,
    # revisit weakly mastered lessons first and retain course order on ties.
    unfinished = tuple(lesson for lesson in static_order if lesson not in completed_lessons)
    review = sorted(
        (lesson for lesson in static_order if lesson in completed_lessons),
        key=lambda lesson: (
            observed.get(lesson, 0.0),
            -attempt_counts.get(lesson, 0),
        ),
    )
    return LearnerPresentation(plan_id, (*unfinished, *review))
