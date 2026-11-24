"""Read trusted assessment history at the pedagogical boundary."""

from time import monotonic as planner_clock

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.phase8_settings import COMPLETION_THRESHOLD, PLANNER_BUDGET_MS
from app.db_models import LearnerAdaptationStop, LearnerAssessmentFact, QuizAttempt
from app.services.learner_record_identity import find_subject
from app.services.learner_record_lock import insert_for
from app.services.learner_record_metrics import observe_planner_stop
from app.services.learner_record_planner import LearnerPresentation, PlanId, plan_presentation
from app.services.learner_record_privacy import read_consent


def stop_adaptation(db: Session, reason: str) -> None:
    if reason not in {"invariance", "evidential-state"}:
        raise ValueError("Unknown adaptation stop reason.")
    db.execute(insert_for(db)(LearnerAdaptationStop).values(control_id="planner", reason=reason)
               .on_conflict_do_nothing(index_elements=["control_id"]))


def clear_adaptation_stop(db: Session) -> None:
    db.execute(delete(LearnerAdaptationStop).where(LearnerAdaptationStop.control_id == "planner"))


def shadow_presentation(
    db: Session, provider: str, identifier: str, course_order: tuple[str, ...], default_plan: PlanId,
) -> LearnerPresentation:
    stopped = db.get(LearnerAdaptationStop, "planner", populate_existing=True) is not None
    observe_planner_stop(stopped)
    if stopped or not read_consent(db, provider, identifier)["adaptation"]:
        return LearnerPresentation(default_plan, course_order)
    subject = find_subject(db, provider, identifier) or identifier
    attempts = dict(db.execute(select(QuizAttempt.lesson_slug, func.count()).where(
        QuizAttempt.user_id == identifier, QuizAttempt.lesson_slug.in_(course_order),
    ).group_by(QuizAttempt.lesson_slug)).all())
    # The locked server writer is the only creator of assessment facts.
    mastery = dict(db.execute(select(LearnerAssessmentFact.lesson_slug, func.max(LearnerAssessmentFact.mastery)).where(
        LearnerAssessmentFact.user_id == subject, LearnerAssessmentFact.lesson_slug.in_(course_order),
        LearnerAssessmentFact.mastery.between(0, 1),
    ).group_by(LearnerAssessmentFact.lesson_slug)).all())
    return plan_presentation(
        course_order, server_mastery=mastery,
        completed_lessons={name for name, score in mastery.items() if score >= COMPLETION_THRESHOLD},
        attempt_counts=attempts, default_plan=default_plan, adaptation_allowed=True,
    )
