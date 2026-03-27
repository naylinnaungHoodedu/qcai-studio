from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import PeerReview, ProjectSubmission
from app.schemas import (
    PeerReviewRead,
    ProjectBrief,
    ProjectRubricCriterion,
    ProjectSubmissionRead,
    ReviewQueueItem,
)
from app.services.text_utils import sanitize_user_text


PROJECT_CATALOG = [
    {
        "slug": "routing-rescue-playbook",
        "title": "Routing Rescue Playbook",
        "summary": "Design a hardware-aware rescue plan for a logistics QUBO that is failing because routing depth and graph size exceed the available quantum budget.",
        "difficulty": "intermediate",
        "estimated_hours": 4,
        "deliverable": "Architecture memo with routing strategy, graph-shrinking plan, and validation checkpoints.",
        "linked_lessons": ["nisq-reality-overview", "ai4qc-routing-and-optimization"],
        "rubric": [
            {
                "id": "systems_grounding",
                "label": "Systems grounding",
                "description": "Shows concrete awareness of routing overhead, sparsity, and hardware bottlenecks.",
            },
            {
                "id": "optimization_design",
                "label": "Optimization design",
                "description": "Explains how reformulation, graph shrinking, or classical control loops improve tractability.",
            },
            {
                "id": "validation_plan",
                "label": "Validation plan",
                "description": "Includes realistic success metrics, fallbacks, and comparisons against a classical baseline.",
            },
        ],
    },
    {
        "slug": "hybrid-clinical-decision-brief",
        "title": "Hybrid Clinical Decision Brief",
        "summary": "Propose a hybrid QC+AI architecture for a safety-critical healthcare workflow without overstating quantum maturity.",
        "difficulty": "advanced",
        "estimated_hours": 5,
        "deliverable": "Clinical-design brief covering model boundaries, explainability, and deployment guardrails.",
        "linked_lessons": ["hybrid-applications-healthcare-vision", "representation-language-and-xai"],
        "rubric": [
            {
                "id": "application_fit",
                "label": "Application fit",
                "description": "Chooses a plausible quantum bottleneck instead of replacing the full workflow.",
            },
            {
                "id": "safety_explainability",
                "label": "Safety and explainability",
                "description": "Addresses explainability, failure modes, and human oversight in a regulated setting.",
            },
            {
                "id": "evidence_quality",
                "label": "Evidence quality",
                "description": "Grounds claims in the source material rather than generic quantum-advantage language.",
            },
        ],
    },
    {
        "slug": "post-quantum-migration-roadmap",
        "title": "Post-Quantum Migration Roadmap",
        "summary": "Draft a role-specific transition roadmap for a company that must prepare for store-now-decrypt-later risk while evaluating broader QC+AI opportunities.",
        "difficulty": "intermediate",
        "estimated_hours": 4,
        "deliverable": "Risk and execution roadmap with phased milestones, communication plan, and success criteria.",
        "linked_lessons": ["industry-use-cases", "thermodynamics-and-roadmap"],
        "rubric": [
            {
                "id": "risk_prioritization",
                "label": "Risk prioritization",
                "description": "Separates urgent migration risks from longer-horizon opportunity areas.",
            },
            {
                "id": "stakeholder_strategy",
                "label": "Stakeholder strategy",
                "description": "Shows how technical, regulatory, and commercial stakeholders are aligned.",
            },
            {
                "id": "roadmap_quality",
                "label": "Roadmap quality",
                "description": "Defines phases, dependencies, and measurable readiness checkpoints.",
            },
        ],
    },
]

_PROJECT_INDEX = {project["slug"]: project for project in PROJECT_CATALOG}


def _build_feedback(project_slug: str, solution_summary: str, implementation_notes: str) -> tuple[str, list[str]]:
    combined = f"{solution_summary} {implementation_notes}".lower()
    actions: list[str] = []
    if len(solution_summary.strip()) < 220:
        actions.append("Expand the submission with a clearer architecture narrative and explicit tradeoffs.")
    if "baseline" not in combined and "compare" not in combined:
        actions.append("Add a classical baseline or counterfactual so the proposal can be evaluated honestly.")
    if project_slug == "routing-rescue-playbook":
        if "routing" not in combined or "swap" not in combined:
            actions.append("Call out routing depth or SWAP overhead directly in the mitigation plan.")
        if "graph" not in combined and "qubo" not in combined:
            actions.append("Explain how the problem instance is compressed before quantum execution.")
    if project_slug == "hybrid-clinical-decision-brief":
        if "explain" not in combined and "human" not in combined:
            actions.append("Strengthen the safety case with human oversight and explainability controls.")
        if "kernel" not in combined and "bottleneck" not in combined:
            actions.append("Identify the exact bounded quantum role inside the classical pipeline.")
    if project_slug == "post-quantum-migration-roadmap":
        if "migration" not in combined and "transition" not in combined:
            actions.append("Frame the work as a migration program rather than a single deployment event.")
        if "risk" not in combined and "priority" not in combined:
            actions.append("Prioritize assets and timelines using a risk-ranked rollout order.")
    if not actions:
        actions.append("The draft is structurally strong. Tighten the evidence links and quantify validation criteria.")
    return actions[0], actions[:3]


def _project_brief(project: dict, submissions: list[ProjectSubmission], reviews: list[PeerReview]) -> ProjectBrief:
    submission_ids = {submission.id for submission in submissions if submission.project_slug == project["slug"]}
    review_count = sum(1 for review in reviews if review.submission_id in submission_ids)
    return ProjectBrief(
        slug=project["slug"],
        title=project["title"],
        summary=project["summary"],
        difficulty=project["difficulty"],
        estimated_hours=project["estimated_hours"],
        deliverable=project["deliverable"],
        linked_lessons=project["linked_lessons"],
        rubric=[ProjectRubricCriterion(**criterion) for criterion in project["rubric"]],
        submitted_count=sum(1 for submission in submissions if submission.project_slug == project["slug"]),
        peer_reviews_received=review_count,
    )


def list_project_catalog(db: Session) -> list[ProjectBrief]:
    submissions = db.scalars(select(ProjectSubmission).where(ProjectSubmission.is_deleted.is_(False))).all()
    reviews = db.scalars(select(PeerReview)).all()
    return [_project_brief(project, submissions, reviews) for project in PROJECT_CATALOG]


def create_project_submission(
    db: Session,
    user_id: str,
    project_slug: str,
    title: str,
    solution_summary: str,
    implementation_notes: str,
    confidence_level: int,
) -> ProjectSubmissionRead:
    project = _PROJECT_INDEX.get(project_slug)
    if not project:
        raise ValueError("Project not found.")
    clean_title = sanitize_user_text(title, preserve_newlines=False)
    clean_summary = sanitize_user_text(solution_summary)
    clean_notes = sanitize_user_text(implementation_notes)
    ai_summary, ai_recommendations = _build_feedback(project_slug, clean_summary, clean_notes)
    submission = ProjectSubmission(
        user_id=user_id,
        project_slug=project_slug,
        title=clean_title,
        solution_summary=clean_summary,
        implementation_notes=clean_notes,
        confidence_level=confidence_level,
        status="submitted",
        is_deleted=False,
        ai_feedback_summary=ai_summary,
        ai_recommendations=ai_recommendations,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return _submission_read(db, submission)


def _submission_read(db: Session, submission: ProjectSubmission) -> ProjectSubmissionRead:
    project = _PROJECT_INDEX.get(submission.project_slug)
    reviews = db.scalars(
        select(PeerReview).where(PeerReview.submission_id == submission.id).order_by(PeerReview.created_at.desc())
    ).all()
    average_score = round(sum(review.overall_score for review in reviews) / len(reviews), 1) if reviews else None
    return ProjectSubmissionRead(
        id=submission.id,
        project_slug=submission.project_slug,
        project_title=project["title"] if project else submission.project_slug,
        title=submission.title,
        solution_summary=submission.solution_summary,
        implementation_notes=submission.implementation_notes,
        confidence_level=submission.confidence_level,
        status=submission.status,
        ai_feedback_summary=submission.ai_feedback_summary,
        ai_recommendations=list(submission.ai_recommendations or []),
        average_peer_score=average_score,
        review_count=len(reviews),
        created_at=submission.created_at,
    )


def list_user_submissions(db: Session, user_id: str, limit: int = 12, offset: int = 0) -> list[ProjectSubmissionRead]:
    submissions = db.scalars(
        select(ProjectSubmission)
        .where(ProjectSubmission.user_id == user_id)
        .order_by(ProjectSubmission.created_at.desc(), ProjectSubmission.id.desc())
    ).all()[offset : offset + limit]
    return [_submission_read(db, submission) for submission in submissions]


def list_review_queue(db: Session, user_id: str, limit: int = 8, offset: int = 0) -> list[ReviewQueueItem]:
    submissions = db.scalars(
        select(ProjectSubmission)
        .where(
            ProjectSubmission.user_id != user_id,
            ProjectSubmission.status == "submitted",
            ProjectSubmission.is_deleted.is_(False),
        )
        .order_by(ProjectSubmission.created_at.desc(), ProjectSubmission.id.desc())
    ).all()
    existing_reviewed_ids = {
        review.submission_id
        for review in db.scalars(select(PeerReview).where(PeerReview.reviewer_user_id == user_id)).all()
    }
    items: list[ReviewQueueItem] = []
    for submission in submissions:
        if submission.id in existing_reviewed_ids:
            continue
        project = _PROJECT_INDEX.get(submission.project_slug)
        if not project:
            continue
        items.append(
            ReviewQueueItem(
                submission_id=submission.id,
                project_slug=submission.project_slug,
                project_title=project["title"],
                title=submission.title,
                author_id=submission.user_id,
                solution_summary=submission.solution_summary,
                implementation_notes=submission.implementation_notes,
                rubric=[ProjectRubricCriterion(**criterion) for criterion in project["rubric"]],
            )
        )
    return items[offset : offset + limit]


def submit_peer_review(
    db: Session,
    reviewer_user_id: str,
    submission_id: int,
    rubric_scores: dict[str, int],
    feedback: str,
) -> PeerReviewRead:
    submission = db.scalars(select(ProjectSubmission).where(ProjectSubmission.id == submission_id)).first()
    if not submission:
        raise ValueError("Submission not found.")
    if submission.is_deleted:
        raise ValueError("This submission has been retracted.")
    if submission.user_id == reviewer_user_id:
        raise ValueError("You cannot review your own submission.")
    existing = db.scalars(
        select(PeerReview).where(
            PeerReview.submission_id == submission_id,
            PeerReview.reviewer_user_id == reviewer_user_id,
        )
    ).first()
    if existing:
        raise ValueError("You have already reviewed this submission.")

    normalized_scores = {key: max(1, min(5, int(value))) for key, value in rubric_scores.items()}
    if not normalized_scores:
        raise ValueError("At least one rubric score is required.")
    overall_score = round(sum(normalized_scores.values()) / len(normalized_scores), 1)
    review = PeerReview(
        submission_id=submission_id,
        reviewer_user_id=reviewer_user_id,
        rubric_scores=normalized_scores,
        overall_score=overall_score,
        feedback=sanitize_user_text(feedback),
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return PeerReviewRead(
        id=review.id,
        submission_id=review.submission_id,
        reviewer_user_id=review.reviewer_user_id,
        overall_score=review.overall_score,
        feedback=review.feedback,
        created_at=review.created_at,
    )


def retract_project_submission(db: Session, user_id: str, submission_id: int) -> ProjectSubmissionRead:
    submission = db.scalars(
        select(ProjectSubmission).where(ProjectSubmission.id == submission_id, ProjectSubmission.user_id == user_id)
    ).first()
    if not submission:
        raise ValueError("Submission not found.")
    if submission.is_deleted:
        return _submission_read(db, submission)
    submission.is_deleted = True
    submission.status = "retracted"
    db.commit()
    db.refresh(submission)
    return _submission_read(db, submission)
