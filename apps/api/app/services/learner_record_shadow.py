"""Read trusted assessment history at the pedagogical boundary."""

from collections.abc import Callable
from dataclasses import dataclass
import os
from time import monotonic as planner_clock
from typing import Literal

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.core.client_identity import keyed_digest
from app.core.phase8_settings import COMPLETION_THRESHOLD, PLANNER_BUDGET_MS
from app.db_models import LearnerAdaptationStop, LearnerAssessmentFact, QuizAttempt
from app.services.learner_record_identity import find_subject
from app.services.learner_record_lock import insert_for
from app.services.learner_record_metrics import observe_planner_stop
from app.services.learner_record_planner import LearnerPresentation, PlanId, plan_presentation
from app.services.learner_record_privacy import read_consent


STOP_REASONS = ("invariance", "evidential-state")


@dataclass(frozen=True)
class StopChange:
    outcome: Literal["inserted", "already-stopped", "deleted", "unchanged"]
    reason: str | None = None


def stop_adaptation(db: Session, reason: str) -> StopChange:
    if reason not in STOP_REASONS:
        raise ValueError("Unknown adaptation stop reason.")
    insert = (insert_for(db)(LearnerAdaptationStop).values(control_id="planner", reason=reason)
              .on_conflict_do_nothing(index_elements=["control_id"]).returning(LearnerAdaptationStop.reason))
    current = select(LearnerAdaptationStop.reason).where(LearnerAdaptationStop.control_id == "planner").with_for_update()
    for _ in range(3):
        inserted = db.scalar(insert)
        if inserted is not None:
            return StopChange("inserted", inserted)
        stored = db.scalar(current)
        if stored is not None:
            return StopChange("already-stopped", stored)
        # A concurrent clear can remove the conflicting row before the read acquires its lock.
    raise RuntimeError("The planner stop changed concurrently. Retry the command.")


def clear_adaptation_stop(db: Session) -> StopChange:
    removed = db.scalar(delete(LearnerAdaptationStop).where(LearnerAdaptationStop.control_id == "planner")
                        .returning(LearnerAdaptationStop.reason))
    return StopChange("deleted", removed) if removed is not None else StopChange("unchanged")


def _stop_actor_digest(db: Session) -> str:
    if db.get_bind().dialect.name == "postgresql":
        login = db.execute(text("SELECT session_user")).scalar_one()
        principal = f"postgresql:{login}"
    elif hasattr(os, "geteuid"):
        principal = f"posix:{os.geteuid()}"
    else:
        try:
            principal = f"windows:{os.getlogin()}"
        except OSError as exc:
            raise RuntimeError("Cannot identify the local operating-system account.") from exc
    return keyed_digest(principal, "planner-stop-actor")


def change_adaptation_stop(
    session_factory: Callable[[], Session], reason: str | None, *, actor_role: Literal["operator", "harness"],
) -> StopChange:
    """Commit an actual stop transition and its audit event together."""
    from app.services.security_log import stage_security_event

    with session_factory() as db:
        change = clear_adaptation_stop(db) if reason is None else stop_adaptation(db, reason)
        if change.outcome in {"inserted", "deleted"}:
            event_type = "learner.harness.stop" if change.outcome == "inserted" else "learner.harness.clear"
            stage_security_event(db, event_type, "success", actor_role=actor_role,
                                 subject_digest=_stop_actor_digest(db),
                                 details={"outcome": change.outcome, "reason": change.reason})
        db.commit()
        return change


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
