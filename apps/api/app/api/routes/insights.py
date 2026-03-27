from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user
from app.core.db import get_db
from app.schemas import (
    AdaptivePathRead,
    LearnerProfileRead,
    LearnerProfileUpdate,
    LearningDashboardRead,
    LearningPulseCreate,
    LearningPulseRead,
    RealtimeFeedbackRequest,
    RealtimeFeedbackResponse,
    SkillGapReportRead,
)
from app.services.learning_intelligence import (
    build_adaptive_path,
    build_learning_dashboard,
    build_skill_gap_report,
    generate_realtime_feedback,
    get_learner_profile,
    record_learning_pulse,
    update_learner_profile,
)


router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("/dashboard", response_model=LearningDashboardRead)
def read_learning_dashboard(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return build_learning_dashboard(db, user.user_id)


@router.get("/profile", response_model=LearnerProfileRead)
def read_learner_profile(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return get_learner_profile(db, user.user_id)


@router.put("/profile", response_model=LearnerProfileRead)
def save_learner_profile(
    payload: LearnerProfileUpdate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return update_learner_profile(
        db,
        user.user_id,
        payload.target_role,
        payload.weekly_goal_hours,
        payload.preferred_pace,
        payload.focus_area,
        payload.self_ratings,
    )


@router.post("/check-ins", response_model=LearningPulseRead)
def create_learning_check_in(
    payload: LearningPulseCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return record_learning_pulse(
        db,
        user.user_id,
        payload.motivation_level,
        payload.focus_level,
        payload.energy_level,
        payload.session_minutes,
        payload.today_goal,
        payload.blocker,
    )


@router.get("/path", response_model=AdaptivePathRead)
def read_adaptive_path(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return build_adaptive_path(db, user.user_id)


@router.get("/skill-gap", response_model=SkillGapReportRead)
def read_skill_gap_report(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return build_skill_gap_report(db, user.user_id)


@router.post("/realtime-feedback", response_model=RealtimeFeedbackResponse)
def create_realtime_feedback(
    payload: RealtimeFeedbackRequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return generate_realtime_feedback(
        db,
        user.user_id,
        payload.context_type,
        payload.content,
        payload.lesson_slug,
        payload.project_slug,
        payload.score,
    )
