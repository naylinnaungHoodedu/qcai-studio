"""Read trusted assessment history at the pedagogical boundary."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db_models import LearnerAdaptationStop, LearnerAssessmentFact, QuizAttempt
from app.services.learner_record_identity import _insert_for, find_subject
from app.services.learner_record_planner import LearnerPresentation, PlanId, plan_presentation
from app.services.learner_record_privacy import read_consent


def stop_adaptation(db: Session, reason: str) -> None:
    if reason not in {"invariance", "evidential-state"}:
        raise ValueError("Unknown adaptation stop reason.")
    db.execute(_insert_for(db)(LearnerAdaptationStop).values(control_id="planner", reason=reason)
               .on_conflict_do_nothing(index_elements=["control_id"]))


def clear_adaptation_stop(db: Session) -> None:
    db.execute(delete(LearnerAdaptationStop).where(LearnerAdaptationStop.control_id == "planner"))


def shadow_presentation(
    db: Session, provider: str, identifier: str, course_order: tuple[str, ...], default_plan: PlanId,
) -> LearnerPresentation:
    if db.get(LearnerAdaptationStop, "planner") is not None or not read_consent(db, provider, identifier)["adaptation"]:
        return LearnerPresentation(default_plan, course_order)
    subject = find_subject(db, provider, identifier) or identifier
    attempts = dict.fromkeys(course_order, 0)
    for lesson in db.scalars(select(QuizAttempt.lesson_slug).where(QuizAttempt.user_id == identifier)):
        if lesson in attempts:
            attempts[lesson] += 1
    # The locked server writer is the only creator of assessment facts.
    mastery = {}
    for fact in db.scalars(select(LearnerAssessmentFact).where(
        LearnerAssessmentFact.user_id == subject,
    )):
        if fact.lesson_slug in attempts and 0 <= fact.mastery <= 1:
            mastery[fact.lesson_slug] = max(fact.mastery, mastery.get(fact.lesson_slug, 0.0))
    return plan_presentation(
        course_order, server_mastery=mastery, completed_lessons={name for name, score in mastery.items() if score >= 0.7},
        attempt_counts=attempts, default_plan=default_plan, adaptation_allowed=True,
    )
