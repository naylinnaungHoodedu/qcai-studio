from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import (
    AnalyticsEvent,
    ArenaProfile,
    BuilderRun,
    BuilderShare,
    LearningPulse,
    LearnerProfile,
    Note,
    PeerReview,
    ProjectSubmission,
    QAInteraction,
    QuizAttempt,
)
from app.schemas import (
    ActivityPoint,
    AdaptivePathRead,
    AdaptivePathStep,
    DashboardMetrics,
    LearnerProfileRead,
    LearningDashboardRead,
    LearningPulseRead,
    ModuleInsight,
    RecommendationCard,
    RealtimeFeedbackResponse,
    SkillGapItem,
    SkillGapReportRead,
)
from app.services.learner_progress import build_course_progress
from app.services.project_studio import PROJECT_CATALOG
from app.services.store import get_course_store


SKILL_LABELS = {
    "quantum_hardware": "Quantum hardware realism",
    "hybrid_architecture": "Hybrid workflow design",
    "optimization": "Optimization and reformulation",
    "applied_qcai": "Applied QC+AI architecture",
    "representation_xai": "Representation and explainability",
    "industry_strategy": "Industry and commercialization strategy",
    "roadmapping": "Roadmapping and systems direction",
}

DEFAULT_SELF_RATINGS = {skill_id: 2 for skill_id in SKILL_LABELS}

ROLE_PROFILES = {
    "Quantum ML Engineer": {
        "summary": "Builds hybrid QC+AI systems that respect hardware limits while embedding bounded quantum stages inside practical AI pipelines.",
        "targets": {
            "quantum_hardware": 4.4,
            "hybrid_architecture": 4.7,
            "optimization": 4.0,
            "applied_qcai": 4.8,
            "representation_xai": 4.0,
            "industry_strategy": 2.8,
            "roadmapping": 3.2,
        },
    },
    "Quantum Optimization Analyst": {
        "summary": "Specializes in problem reformulation, QUBO design, routing-aware optimization, and classical control around constrained quantum subroutines.",
        "targets": {
            "quantum_hardware": 4.1,
            "hybrid_architecture": 4.0,
            "optimization": 4.9,
            "applied_qcai": 3.7,
            "representation_xai": 2.6,
            "industry_strategy": 3.1,
            "roadmapping": 3.0,
        },
    },
    "QC+AI Product Strategist": {
        "summary": "Translates QC+AI capability, risk, and evidence into defensible adoption roadmaps, business cases, and stakeholder communication.",
        "targets": {
            "quantum_hardware": 3.0,
            "hybrid_architecture": 3.5,
            "optimization": 2.7,
            "applied_qcai": 3.5,
            "representation_xai": 2.8,
            "industry_strategy": 5.0,
            "roadmapping": 4.7,
        },
    },
    "Applied Quantum Systems Engineer": {
        "summary": "Owns end-to-end hybrid systems quality, from hardware-aware design decisions through operational roadmapping and validation.",
        "targets": {
            "quantum_hardware": 4.9,
            "hybrid_architecture": 4.6,
            "optimization": 4.0,
            "applied_qcai": 3.8,
            "representation_xai": 3.1,
            "industry_strategy": 3.2,
            "roadmapping": 4.2,
        },
    },
}

MODULE_SKILL_MAP = {
    "nisq-hybrid-workflows": {"quantum_hardware": 0.7, "hybrid_architecture": 0.9},
    "ai-for-quantum-hardware": {"quantum_hardware": 1.0, "hybrid_architecture": 0.7, "optimization": 1.2},
    "quantum-enhanced-applications": {"hybrid_architecture": 0.8, "applied_qcai": 1.1, "representation_xai": 0.4},
    "representation-explainability": {"representation_xai": 1.2, "applied_qcai": 0.4},
    "industry-use-cases": {"industry_strategy": 1.3, "applied_qcai": 0.4, "roadmapping": 0.3},
    "thermodynamics-roadmap": {"roadmapping": 1.3, "industry_strategy": 0.5, "quantum_hardware": 0.2},
}

PROJECT_SKILL_MAP = {
    "routing-rescue-playbook": {"quantum_hardware": 0.7, "hybrid_architecture": 0.6, "optimization": 1.0},
    "hybrid-clinical-decision-brief": {"applied_qcai": 1.0, "representation_xai": 0.7, "hybrid_architecture": 0.5},
    "post-quantum-migration-roadmap": {"industry_strategy": 0.9, "roadmapping": 1.0, "applied_qcai": 0.2},
}

RESOURCE_MAP = {
    "quantum_hardware": [
        {
            "title": "QC+AI Overview and the NISQ Reality",
            "summary": "Revisit the NISQ constraints that shape credible near-term system design.",
            "href": "/modules/nisq-hybrid-workflows",
            "recommendation_type": "module",
        },
        {
            "title": "AI for Quantum Hardware and Optimization",
            "summary": "Practice routing, graph shrinking, and qubit-budget thinking.",
            "href": "/modules/ai-for-quantum-hardware",
            "recommendation_type": "module",
        },
    ],
    "hybrid_architecture": [
        {
            "title": "Microlearning Drag-and-Drop Builder",
            "summary": "Rebuild dependency graphs to reinforce hybrid workflow ordering.",
            "href": "/builder",
            "recommendation_type": "game",
        },
        {
            "title": "Hybrid QC+AI Architectures in Practice",
            "summary": "Study how bounded quantum bottlenecks fit into classical application stacks.",
            "href": "/lessons/hybrid-applications-healthcare-vision",
            "recommendation_type": "lesson",
        },
    ],
    "optimization": [
        {
            "title": "Routing, Graph Shrinking, and Logistics under Hardware Constraints",
            "summary": "Tighten your optimization intuition around QUBO reformulation and routing overhead.",
            "href": "/lessons/ai4qc-routing-and-optimization",
            "recommendation_type": "lesson",
        },
        {
            "title": "AI & Quantum Challenge Arena",
            "summary": "Use timed challenge rounds to stress-test optimization and hardware reasoning.",
            "href": "/arena",
            "recommendation_type": "game",
        },
    ],
    "applied_qcai": [
        {
            "title": "Quantum-Enhanced AI in Vision, Healthcare, and Few-Shot Learning",
            "summary": "Compare realistic application patterns instead of generic quantum claims.",
            "href": "/modules/quantum-enhanced-applications",
            "recommendation_type": "module",
        },
        {
            "title": "Hybrid Clinical Decision Brief",
            "summary": "Turn architectural understanding into a peer-reviewed applied design artifact.",
            "href": "/projects",
            "recommendation_type": "project",
        },
    ],
    "representation_xai": [
        {
            "title": "Representation, Language, Compression, and Explainability",
            "summary": "Work through quINR, QuCoWE, and QGSHAP with a representation-first lens.",
            "href": "/modules/representation-explainability",
            "recommendation_type": "module",
        },
    ],
    "industry_strategy": [
        {
            "title": "Industry Use Cases",
            "summary": "Map sector-specific opportunity patterns and avoid one-size-fits-all claims.",
            "href": "/modules/industry-use-cases",
            "recommendation_type": "module",
        },
        {
            "title": "Post-Quantum Migration Roadmap",
            "summary": "Practice translating QC+AI opportunity and security urgency into an execution plan.",
            "href": "/projects",
            "recommendation_type": "project",
        },
    ],
    "roadmapping": [
        {
            "title": "Thermodynamic Quantum Agents and Future Directions",
            "summary": "Use the systems-level roadmap lesson to sharpen longer-range judgment.",
            "href": "/modules/thermodynamics-roadmap",
            "recommendation_type": "module",
        },
    ],
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _ensure_profile(db: Session, user_id: str) -> LearnerProfile:
    profile = db.scalars(select(LearnerProfile).where(LearnerProfile.user_id == user_id)).first()
    if profile:
        return profile
    profile = LearnerProfile(
        user_id=user_id,
        target_role="Quantum ML Engineer",
        weekly_goal_hours=4,
        preferred_pace="balanced",
        focus_area="hybrid_architecture",
        self_ratings=dict(DEFAULT_SELF_RATINGS),
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def _default_profile_record(user_id: str) -> LearnerProfile:
    return LearnerProfile(
        user_id=user_id,
        target_role="Quantum ML Engineer",
        weekly_goal_hours=4,
        preferred_pace="balanced",
        focus_area="hybrid_architecture",
        self_ratings=dict(DEFAULT_SELF_RATINGS),
    )


def _profile_read(profile: LearnerProfile) -> LearnerProfileRead:
    ratings = {**DEFAULT_SELF_RATINGS, **{key: int(value) for key, value in (profile.self_ratings or {}).items()}}
    return LearnerProfileRead(
        user_id=profile.user_id,
        target_role=profile.target_role,
        weekly_goal_hours=profile.weekly_goal_hours,
        preferred_pace=profile.preferred_pace,
        focus_area=profile.focus_area,
        self_ratings=ratings,
    )


def get_learner_profile(db: Session, user_id: str) -> LearnerProfileRead:
    profile = db.scalars(select(LearnerProfile).where(LearnerProfile.user_id == user_id)).first()
    return _profile_read(profile or _default_profile_record(user_id))


def update_learner_profile(
    db: Session,
    user_id: str,
    target_role: str,
    weekly_goal_hours: int,
    preferred_pace: str,
    focus_area: str | None,
    self_ratings: dict[str, int],
) -> LearnerProfileRead:
    profile = _ensure_profile(db, user_id)
    profile.target_role = target_role if target_role in ROLE_PROFILES else "Quantum ML Engineer"
    profile.weekly_goal_hours = weekly_goal_hours
    profile.preferred_pace = preferred_pace
    profile.focus_area = focus_area
    profile.self_ratings = {
        skill_id: max(1, min(5, int(self_ratings.get(skill_id, DEFAULT_SELF_RATINGS[skill_id]))))
        for skill_id in SKILL_LABELS
    }
    db.commit()
    db.refresh(profile)
    return _profile_read(profile)


def record_learning_pulse(
    db: Session,
    user_id: str,
    motivation_level: int,
    focus_level: int,
    energy_level: int,
    session_minutes: int,
    today_goal: str | None,
    blocker: str | None,
) -> LearningPulseRead:
    pulse = LearningPulse(
        user_id=user_id,
        motivation_level=motivation_level,
        focus_level=focus_level,
        energy_level=energy_level,
        session_minutes=session_minutes,
        today_goal=(today_goal or "").strip() or None,
        blocker=(blocker or "").strip() or None,
    )
    db.add(pulse)
    db.commit()
    db.refresh(pulse)
    return LearningPulseRead(
        id=pulse.id,
        motivation_level=pulse.motivation_level,
        focus_level=pulse.focus_level,
        energy_level=pulse.energy_level,
        session_minutes=pulse.session_minutes,
        today_goal=pulse.today_goal,
        blocker=pulse.blocker,
        created_at=pulse.created_at,
    )


def _list_recent_pulses(db: Session, user_id: str, limit: int = 6) -> list[LearningPulse]:
    return db.scalars(
        select(LearningPulse)
        .where(LearningPulse.user_id == user_id)
        .order_by(LearningPulse.created_at.desc(), LearningPulse.id.desc())
    ).all()[:limit]


def _estimate_recent_hours(db: Session, user_id: str, since: datetime) -> float:
    pulse_minutes = sum(
        pulse.session_minutes
        for pulse in db.scalars(
            select(LearningPulse).where(LearningPulse.user_id == user_id, LearningPulse.created_at >= since)
        ).all()
    )
    note_count = len(db.scalars(select(Note).where(Note.user_id == user_id, Note.created_at >= since)).all())
    quiz_count = len(db.scalars(select(QuizAttempt).where(QuizAttempt.user_id == user_id, QuizAttempt.created_at >= since)).all())
    qa_count = len(db.scalars(select(QAInteraction).where(QAInteraction.user_id == user_id, QAInteraction.created_at >= since)).all())
    project_count = len(
        db.scalars(select(ProjectSubmission).where(ProjectSubmission.user_id == user_id, ProjectSubmission.created_at >= since)).all()
    )
    review_count = len(
        db.scalars(select(PeerReview).where(PeerReview.reviewer_user_id == user_id, PeerReview.created_at >= since)).all()
    )
    builder_count = len(
        db.scalars(select(BuilderRun).where(BuilderRun.user_id == user_id, BuilderRun.created_at >= since)).all()
    )
    return round(
        (pulse_minutes / 60)
        + (note_count * 0.15)
        + (quiz_count * 0.25)
        + (qa_count * 0.1)
        + (project_count * 1.5)
        + (review_count * 0.5)
        + (builder_count * 0.35),
        1,
    )


def _daily_activity(db: Session, user_id: str) -> list[ActivityPoint]:
    today = datetime.now(UTC).date()
    since = datetime.combine(today - timedelta(days=6), datetime.min.time())
    event_counts: dict[str, int] = defaultdict(int)
    focus_totals: dict[str, list[int]] = defaultdict(list)
    motivation_totals: dict[str, list[int]] = defaultdict(list)

    record_groups = [
        db.scalars(select(Note).where(Note.user_id == user_id, Note.created_at >= since)).all(),
        db.scalars(select(QuizAttempt).where(QuizAttempt.user_id == user_id, QuizAttempt.created_at >= since)).all(),
        db.scalars(select(QAInteraction).where(QAInteraction.user_id == user_id, QAInteraction.created_at >= since)).all(),
        db.scalars(select(AnalyticsEvent).where(AnalyticsEvent.user_id == user_id, AnalyticsEvent.created_at >= since)).all(),
        db.scalars(select(ProjectSubmission).where(ProjectSubmission.user_id == user_id, ProjectSubmission.created_at >= since)).all(),
        db.scalars(select(PeerReview).where(PeerReview.reviewer_user_id == user_id, PeerReview.created_at >= since)).all(),
        db.scalars(select(BuilderRun).where(BuilderRun.user_id == user_id, BuilderRun.created_at >= since)).all(),
        db.scalars(select(BuilderShare).where(BuilderShare.user_id == user_id, BuilderShare.created_at >= since)).all(),
    ]
    for group in record_groups:
        for record in group:
            day_key = record.created_at.date().isoformat()
            event_counts[day_key] += 1

    for pulse in db.scalars(select(LearningPulse).where(LearningPulse.user_id == user_id, LearningPulse.created_at >= since)).all():
        day_key = pulse.created_at.date().isoformat()
        event_counts[day_key] += 1
        focus_totals[day_key].append(pulse.focus_level)
        motivation_totals[day_key].append(pulse.motivation_level)

    points: list[ActivityPoint] = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        day_key = day.isoformat()
        focus_values = focus_totals.get(day_key, [])
        motivation_values = motivation_totals.get(day_key, [])
        points.append(
            ActivityPoint(
                label=day.strftime("%a"),
                date=day_key,
                events=event_counts.get(day_key, 0),
                focus_level=round(sum(focus_values) / len(focus_values), 1) if focus_values else None,
                motivation_level=round(sum(motivation_values) / len(motivation_values), 1) if motivation_values else None,
            )
        )
    return points


def _active_streak(activity: list[ActivityPoint]) -> int:
    streak = 0
    for point in reversed(activity):
        if point.events <= 0:
            break
        streak += 1
    return streak


def _skill_levels(db: Session, user_id: str, profile: LearnerProfileRead) -> dict[str, float]:
    progress = build_course_progress(db, user_id)
    levels = {skill_id: float(profile.self_ratings.get(skill_id, DEFAULT_SELF_RATINGS[skill_id])) for skill_id in SKILL_LABELS}

    for module in progress.modules:
        evidence = (module.progress_percent / 100) * 1.2
        if module.average_score_percent is not None:
            evidence += (module.average_score_percent / 100) * 0.9
        for skill_id, weight in MODULE_SKILL_MAP.get(module.module_slug, {}).items():
            levels[skill_id] += evidence * weight

    arena_profile = db.scalars(select(ArenaProfile).where(ArenaProfile.player_id == user_id)).first()
    if arena_profile:
        levels["optimization"] += arena_profile.adaptive_level * 0.18
        levels["quantum_hardware"] += (arena_profile.skill_rating - 900) / 400

    builder_runs = db.scalars(select(BuilderRun).where(BuilderRun.user_id == user_id)).all()
    completed_builder_runs = sum(1 for run in builder_runs if run.status == "completed")
    levels["hybrid_architecture"] += min(1.2, completed_builder_runs * 0.18)

    submissions = db.scalars(select(ProjectSubmission).where(ProjectSubmission.user_id == user_id)).all()
    for submission in submissions:
        review_scores = [
            review.overall_score
            for review in db.scalars(select(PeerReview).where(PeerReview.submission_id == submission.id)).all()
        ]
        confidence_factor = 0.35 + ((submission.confidence_level - 1) * 0.07)
        quality_factor = (sum(review_scores) / len(review_scores) / 5) if review_scores else 0.65
        for skill_id, weight in PROJECT_SKILL_MAP.get(submission.project_slug, {}).items():
            levels[skill_id] += weight * confidence_factor * quality_factor

    return {skill_id: round(_clamp(level, 1.0, 5.0), 1) for skill_id, level in levels.items()}


def build_skill_gap_report(db: Session, user_id: str) -> SkillGapReportRead:
    profile = get_learner_profile(db, user_id)
    role = ROLE_PROFILES.get(profile.target_role, ROLE_PROFILES["Quantum ML Engineer"])
    skill_levels = _skill_levels(db, user_id, profile)
    gaps: list[SkillGapItem] = []
    strengths: list[str] = []
    for skill_id, target in role["targets"].items():
        current = skill_levels.get(skill_id, 1.0)
        gap = round(max(0.0, target - current), 1)
        if gap <= 0.5:
            strengths.append(f"{SKILL_LABELS[skill_id]} is already close to the role target.")
        gap_resources = RESOURCE_MAP.get(skill_id, [])[:2]
        gaps.append(
            SkillGapItem(
                skill_id=skill_id,
                label=SKILL_LABELS[skill_id],
                current_level=current,
                target_level=target,
                gap=gap,
                evidence=f"Current evidence blends your self-rating, tracked module mastery, games, and submitted project work for {SKILL_LABELS[skill_id].lower()}.",
                recommended_actions=[resource["title"] for resource in gap_resources],
            )
        )
    gaps.sort(key=lambda item: item.gap, reverse=True)
    readiness = round(
        sum(min(skill_levels.get(skill_id, 1.0), target) / target for skill_id, target in role["targets"].items())
        / len(role["targets"])
        * 100
    )
    recommendations: list[RecommendationCard] = []
    for gap in gaps[:3]:
        for resource in RESOURCE_MAP.get(gap.skill_id, [])[:2]:
            recommendations.append(
                RecommendationCard(
                    title=resource["title"],
                    summary=resource["summary"],
                    href=resource["href"],
                    recommendation_type=resource["recommendation_type"],
                    reason=f"Closes the largest current gap in {gap.label.lower()}.",
                    urgency="high" if gap.gap >= 1.5 else "medium",
                )
            )
    return SkillGapReportRead(
        target_role=profile.target_role,
        role_summary=role["summary"],
        readiness_percent=readiness,
        strengths=strengths[:3],
        gaps=gaps,
        recommendations=recommendations[:6],
    )


def build_adaptive_path(db: Session, user_id: str) -> AdaptivePathRead:
    profile = get_learner_profile(db, user_id)
    progress = build_course_progress(db, user_id)
    gap_report = build_skill_gap_report(db, user_id)
    activity = _daily_activity(db, user_id)
    if any(point.focus_level is not None for point in activity):
        recent_focus = round(
            sum(point.focus_level for point in activity if point.focus_level is not None)
            / sum(1 for point in activity if point.focus_level is not None),
            1,
        )
    else:
        recent_focus = 3.0
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7)
    weekly_hours = _estimate_recent_hours(db, user_id, since)
    if recent_focus < 2.8:
        pace_mode = "stabilize"
    elif weekly_hours >= profile.weekly_goal_hours and progress.progress_percent < 85:
        pace_mode = "accelerate"
    else:
        pace_mode = profile.preferred_pace

    store = get_course_store()
    ranked_modules = []
    top_gap_weights = {gap.skill_id: gap.gap for gap in gap_report.gaps}
    for module in progress.modules:
        if module.status == "completed":
            continue
        module_weight = sum(top_gap_weights.get(skill_id, 0.0) * weight for skill_id, weight in MODULE_SKILL_MAP.get(module.module_slug, {}).items())
        ranked_modules.append((module_weight, module))
    ranked_modules.sort(key=lambda item: item[0], reverse=True)

    steps: list[AdaptivePathStep] = []
    for step_number, (_, module) in enumerate(ranked_modules[:2], start=1):
        lesson_slug = store.modules[module.module_slug].lesson_slugs[0]
        steps.append(
            AdaptivePathStep(
                step_number=step_number,
                title=module.module_title,
                summary="Raise mastery in this module before pushing harder on projects or role-specific specialization.",
                href=f"/lessons/{lesson_slug}",
                recommendation_type="lesson",
                estimated_minutes=25 if pace_mode == "stabilize" else 40,
                intensity="recover" if pace_mode == "stabilize" else "stretch" if module.progress_percent >= 50 else "steady",
                reason=f"This module closes multiple skill gaps while matching your current role target of {profile.target_role}.",
            )
        )

    top_gap = gap_report.gaps[0]
    project = next(
        (
            item
            for item in PROJECT_CATALOG
            if PROJECT_SKILL_MAP.get(item["slug"], {}).get(top_gap.skill_id, 0) > 0
        ),
        PROJECT_CATALOG[0],
    )
    steps.append(
        AdaptivePathStep(
            step_number=len(steps) + 1,
            title=project["title"],
            summary=project["summary"],
            href="/projects",
            recommendation_type="project",
            estimated_minutes=60 if pace_mode == "accelerate" else 45,
            intensity="stretch" if top_gap.gap >= 1.2 else "steady",
            reason=f"Hands-on work is the fastest way to turn the gap in {top_gap.label.lower()} into evidence.",
        )
    )
    practice_href = "/arena" if top_gap.skill_id in {"optimization", "quantum_hardware"} else "/builder"
    practice_title = "AI & Quantum Challenge Arena" if practice_href == "/arena" else "Microlearning Drag-and-Drop Builder"
    steps.append(
        AdaptivePathStep(
            step_number=len(steps) + 1,
            title=practice_title,
            summary="Finish the cycle with a fast feedback loop that reinforces retention before the next module.",
            href=practice_href,
            recommendation_type="game",
            estimated_minutes=15,
            intensity="light" if pace_mode == "stabilize" else "steady",
            reason="Your path adapts toward short, repeatable reinforcement when immediate retrieval practice will help retention.",
        )
    )

    adaptation_summary = (
        f"Current pace mode is {pace_mode} because your weekly study volume is {weekly_hours}h against a {profile.weekly_goal_hours}h goal "
        f"and your recent focus signal is {recent_focus}/5."
    )
    return AdaptivePathRead(
        target_role=profile.target_role,
        pace_mode=pace_mode,
        adaptation_summary=adaptation_summary,
        steps=steps,
    )


def _module_insights(db: Session, user_id: str) -> list[ModuleInsight]:
    progress = build_course_progress(db, user_id)
    insights: list[ModuleInsight] = []
    for module in progress.modules:
        score = module.average_score_percent if module.average_score_percent is not None else 52 if module.visited_lessons else 28
        mastery = round(_clamp((module.progress_percent * 0.58) + (score * 0.42), 0, 100))
        if mastery >= 78:
            confidence = "solid"
        elif mastery >= 55:
            confidence = "developing"
        else:
            confidence = "fragile"
        risk_flag = None
        if module.status == "not_started":
            risk_flag = "No evidence recorded yet"
        elif mastery < 60:
            risk_flag = "Needs reinforcement before advanced project work"
        insights.append(
            ModuleInsight(
                module_slug=module.module_slug,
                module_title=module.module_title,
                mastery_percent=mastery,
                confidence_label=confidence,
                risk_flag=risk_flag,
                recommendation="Reinforce this module with the linked lesson, then move to a project or game surface for retrieval practice.",
            )
        )
    return insights


def _dashboard_recommendations(db: Session, user_id: str) -> list[RecommendationCard]:
    path = build_adaptive_path(db, user_id)
    gap_report = build_skill_gap_report(db, user_id)
    recommendations: list[RecommendationCard] = []
    for step in path.steps[:3]:
        recommendations.append(
            RecommendationCard(
                title=step.title,
                summary=step.summary,
                href=step.href,
                recommendation_type=step.recommendation_type,
                reason=step.reason,
                urgency="high" if step.intensity == "stretch" else "medium",
            )
        )
    for recommendation in gap_report.recommendations[:2]:
        if recommendation.href not in {item.href for item in recommendations}:
            recommendations.append(recommendation)
    return recommendations[:5]


def _coach_feedback(db: Session, user_id: str) -> RealtimeFeedbackResponse:
    path = build_adaptive_path(db, user_id)
    gap_report = build_skill_gap_report(db, user_id)
    recent_pulses = _list_recent_pulses(db, user_id, limit=2)
    latest_blocker = recent_pulses[0].blocker if recent_pulses and recent_pulses[0].blocker else None
    top_gap = gap_report.gaps[0]
    summary = (
        f"Your next leverage point is {top_gap.label.lower()}. "
        f"The current adaptive path is leaning toward {path.pace_mode} mode to keep progress sustainable."
    )
    if latest_blocker:
        summary += f" Latest blocker noted: {latest_blocker}."
    actions = [
        f"Complete the next path step: {path.steps[0].title}.",
        f"Use a 25-40 minute session focused on {top_gap.label.lower()} rather than broad review.",
        "Finish with one retrieval activity in the arena or builder to lock in the concept boundary.",
    ]
    return RealtimeFeedbackResponse(
        summary=summary,
        signal="stabilize" if path.pace_mode == "stabilize" else "advance",
        confidence_label="high" if top_gap.gap <= 1.0 else "medium",
        recommended_actions=actions,
        suggested_resources=_dashboard_recommendations(db, user_id)[:3],
    )


def build_learning_dashboard(db: Session, user_id: str) -> LearningDashboardRead:
    profile = get_learner_profile(db, user_id)
    progress = build_course_progress(db, user_id)
    activity = _daily_activity(db, user_id)
    pulses = _list_recent_pulses(db, user_id)
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7)
    weekly_hours = _estimate_recent_hours(db, user_id, since)
    focus_values = [pulse.focus_level for pulse in pulses]
    motivation_values = [pulse.motivation_level for pulse in pulses]
    focus_score = round(((sum(focus_values) / len(focus_values)) * 20)) if focus_values else 58
    motivation_score = round(((sum(motivation_values) / len(motivation_values)) * 20)) if motivation_values else 62
    active_days = sum(1 for point in activity if point.events > 0)
    consistency_score = round((active_days / len(activity)) * 100) if activity else 0
    momentum_score = round(_clamp(sum(point.events for point in activity) * 7, 0, 100))
    project_count = len(db.scalars(select(ProjectSubmission).where(ProjectSubmission.user_id == user_id)).all())
    review_count = len(db.scalars(select(PeerReview).where(PeerReview.reviewer_user_id == user_id)).all())

    return LearningDashboardRead(
        profile=profile,
        metrics=DashboardMetrics(
            progress_percent=progress.progress_percent,
            motivation_score=motivation_score,
            focus_score=focus_score,
            momentum_score=momentum_score,
            consistency_score=consistency_score,
            active_streak_days=_active_streak(activity),
            weekly_goal_hours=profile.weekly_goal_hours,
            weekly_goal_progress_percent=round(_clamp((weekly_hours / profile.weekly_goal_hours) * 100, 0, 160)),
            completed_lessons=progress.completed_lessons,
            projects_submitted=project_count,
            peer_reviews_completed=review_count,
        ),
        activity=activity,
        pulses=[
            LearningPulseRead(
                id=pulse.id,
                motivation_level=pulse.motivation_level,
                focus_level=pulse.focus_level,
                energy_level=pulse.energy_level,
                session_minutes=pulse.session_minutes,
                today_goal=pulse.today_goal,
                blocker=pulse.blocker,
                created_at=pulse.created_at,
            )
            for pulse in pulses
        ],
        module_insights=_module_insights(db, user_id),
        recommendations=_dashboard_recommendations(db, user_id),
        coach_feedback=_coach_feedback(db, user_id),
    )


def generate_realtime_feedback(
    db: Session,
    user_id: str,
    context_type: str,
    content: str,
    lesson_slug: str | None = None,
    project_slug: str | None = None,
    score: int | None = None,
) -> RealtimeFeedbackResponse:
    lowered = content.lower()
    resources: list[RecommendationCard] = []
    actions: list[str] = []
    signal = "advance"
    summary_parts = [f"Live {context_type.replace('_', ' ')} analysis is using your current role target and recent evidence."]
    if score is not None and score < 70:
        signal = "stabilize"
        summary_parts.append("Performance signal suggests reinforcement before adding more difficulty.")
        actions.append("Revisit the exact lesson section that the low-scoring concept belongs to and restate it in your own words.")
    if len(content.strip()) < 180:
        signal = "stabilize"
        summary_parts.append("The draft is still too thin to demonstrate reliable systems thinking.")
        actions.append("Add a more explicit architecture narrative, decision tradeoffs, and validation criteria.")
    topic_map = {
        "routing": "optimization",
        "qubo": "optimization",
        "graph": "optimization",
        "kernel": "applied_qcai",
        "health": "applied_qcai",
        "vision": "applied_qcai",
        "explain": "representation_xai",
        "shap": "representation_xai",
        "industry": "industry_strategy",
        "migration": "industry_strategy",
        "security": "industry_strategy",
        "thermodynamic": "roadmapping",
        "roadmap": "roadmapping",
    }
    matched_skills = {skill_id for token, skill_id in topic_map.items() if token in lowered}
    if lesson_slug == "ai4qc-routing-and-optimization":
        matched_skills.add("optimization")
    if project_slug == "post-quantum-migration-roadmap":
        matched_skills.update({"industry_strategy", "roadmapping"})
    if not matched_skills:
        matched_skills.add("hybrid_architecture")

    for skill_id in matched_skills:
        for resource in RESOURCE_MAP.get(skill_id, [])[:1]:
            resources.append(
                RecommendationCard(
                    title=resource["title"],
                    summary=resource["summary"],
                    href=resource["href"],
                    recommendation_type=resource["recommendation_type"],
                    reason=f"Detected a live need for stronger {SKILL_LABELS[skill_id].lower()}.",
                    urgency="high" if signal == "stabilize" else "medium",
                )
            )
    if not actions:
        actions.append("Keep the bounded quantum role explicit and avoid claiming end-to-end quantum replacement.")
    if "baseline" not in lowered:
        actions.append("Name the classical baseline or fallback path so the recommendation stays technically honest.")
    if "metric" not in lowered and "measure" not in lowered:
        actions.append("Define one success metric and one failure trigger before moving on.")

    profile = get_learner_profile(db, user_id)
    if len(summary_parts) == 1:
        summary_parts.append(
            f"The draft aligns best with your {profile.target_role} goal when it stays specific about architecture, evidence, and evaluation."
        )
    return RealtimeFeedbackResponse(
        summary=" ".join(summary_parts),
        signal=signal,
        confidence_label="medium" if signal == "stabilize" else "high",
        recommended_actions=actions[:3],
        suggested_resources=resources[:3],
    )
