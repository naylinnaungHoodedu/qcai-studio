from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user
from app.core.db import get_db
from app.db_models import AnalyticsEvent, Note, QAInteraction, QuizAttempt
from app.schemas import (
    CourseOverview,
    CourseProgress,
    LessonDetail,
    LessonProgress,
    ModuleProgress,
    NoteCreate,
    NoteRead,
    QuizAttemptCreate,
    QuizAttemptRead,
)
from app.services.store import get_course_store

router = APIRouter(prefix="/content", tags=["content"])


@router.get("/course", response_model=CourseOverview)
def get_course():
    return get_course_store().overview


@router.get("/modules/{module_slug}")
def get_module(module_slug: str):
    store = get_course_store()
    module = store.modules.get(module_slug)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found.")
    lessons = [store.lessons[slug] for slug in module.lesson_slugs]
    return {"module": module, "lessons": lessons}


@router.get("/lessons/{lesson_slug}", response_model=LessonDetail)
def get_lesson(lesson_slug: str):
    store = get_course_store()
    lesson = store.lessons.get(lesson_slug)
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found.")
    return lesson


def _score_percent(score: int | None, question_count: int) -> float | None:
    if score is None or question_count <= 0:
        return None
    return round((score / question_count) * 100, 1)


@router.get("/progress", response_model=CourseProgress)
def get_progress(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    store = get_course_store()
    notes = db.scalars(select(Note).where(Note.user_id == user.user_id).order_by(Note.created_at.desc())).all()
    quiz_attempts = db.scalars(
        select(QuizAttempt).where(QuizAttempt.user_id == user.user_id).order_by(QuizAttempt.created_at.desc())
    ).all()
    analytics_events = db.scalars(
        select(AnalyticsEvent).where(AnalyticsEvent.user_id == user.user_id).order_by(AnalyticsEvent.created_at.desc())
    ).all()
    qa_interactions = db.scalars(
        select(QAInteraction).where(QAInteraction.user_id == user.user_id).order_by(QAInteraction.created_at.desc())
    ).all()

    note_counts: dict[str, int] = {}
    quiz_by_lesson: dict[str, list[QuizAttempt]] = {}
    analytics_counts: dict[str, int] = {}
    qa_counts: dict[str, int] = {}

    for record in notes:
        note_counts[record.lesson_slug] = note_counts.get(record.lesson_slug, 0) + 1
    for record in quiz_attempts:
        quiz_by_lesson.setdefault(record.lesson_slug, []).append(record)
    for record in analytics_events:
        if record.lesson_slug:
            analytics_counts[record.lesson_slug] = analytics_counts.get(record.lesson_slug, 0) + 1
    for record in qa_interactions:
        if record.lesson_slug:
            qa_counts[record.lesson_slug] = qa_counts.get(record.lesson_slug, 0) + 1

    lesson_progress_by_slug: dict[str, LessonProgress] = {}
    ordered_lessons: list[LessonProgress] = []

    for module in store.overview.modules:
        for lesson_slug in module.lesson_slugs:
            lesson = store.lessons[lesson_slug]
            note_count = note_counts.get(lesson_slug, 0)
            attempts = quiz_by_lesson.get(lesson_slug, [])
            quiz_attempt_count = len(attempts)
            best_score = max((attempt.score for attempt in attempts), default=None)
            best_score_percent = _score_percent(best_score, len(lesson.quiz_questions))
            analytics_count = analytics_counts.get(lesson_slug, 0)
            qa_count = qa_counts.get(lesson_slug, 0)
            visited = note_count > 0 or quiz_attempt_count > 0 or analytics_count > 0 or qa_count > 0
            completed = note_count > 0 and best_score_percent is not None and best_score_percent >= 70
            status = "completed" if completed else "in_progress" if visited else "not_started"

            progress = LessonProgress(
                lesson_slug=lesson.slug,
                lesson_title=lesson.title,
                module_slug=lesson.module_slug,
                status=status,
                visited=visited,
                note_count=note_count,
                quiz_attempts=quiz_attempt_count,
                qa_questions=qa_count,
                analytics_events=analytics_count,
                best_score=best_score,
                best_score_percent=best_score_percent,
            )
            lesson_progress_by_slug[lesson.slug] = progress
            ordered_lessons.append(progress)

    modules: list[ModuleProgress] = []
    for module in store.overview.modules:
        related_progress = [lesson_progress_by_slug[slug] for slug in module.lesson_slugs if slug in lesson_progress_by_slug]
        total_lessons = len(related_progress)
        visited_lessons = sum(1 for item in related_progress if item.visited)
        completed_lessons = sum(1 for item in related_progress if item.status == "completed")
        in_progress_lessons = sum(1 for item in related_progress if item.status == "in_progress")
        progress_percent = round((((completed_lessons) + (0.5 * in_progress_lessons)) / total_lessons) * 100) if total_lessons else 0
        scored_lessons = [item.best_score_percent for item in related_progress if item.best_score_percent is not None]
        average_score_percent = round(sum(scored_lessons) / len(scored_lessons), 1) if scored_lessons else None
        status = (
            "completed"
            if total_lessons and completed_lessons == total_lessons
            else "in_progress"
            if visited_lessons
            else "not_started"
        )
        modules.append(
            ModuleProgress(
                module_slug=module.slug,
                module_title=module.title,
                status=status,
                total_lessons=total_lessons,
                visited_lessons=visited_lessons,
                completed_lessons=completed_lessons,
                progress_percent=progress_percent,
                average_score_percent=average_score_percent,
            )
        )

    total_lessons = len(ordered_lessons)
    visited_lessons = sum(1 for item in ordered_lessons if item.visited)
    completed_lessons = sum(1 for item in ordered_lessons if item.status == "completed")
    in_progress_lessons = sum(1 for item in ordered_lessons if item.status == "in_progress")
    progress_percent = round((((completed_lessons) + (0.5 * in_progress_lessons)) / total_lessons) * 100) if total_lessons else 0

    return CourseProgress(
        user_id=user.user_id,
        total_lessons=total_lessons,
        visited_lessons=visited_lessons,
        completed_lessons=completed_lessons,
        progress_percent=progress_percent,
        modules=modules,
        lessons=ordered_lessons,
        recent_notes=[
            NoteRead(
                id=record.id,
                body=record.body,
                lesson_slug=record.lesson_slug,
                anchor_type=record.anchor_type,
                anchor_value=record.anchor_value,
                created_at=record.created_at,
            )
            for record in notes[:5]
        ],
        recent_quiz_attempts=[
            QuizAttemptRead(
                id=record.id,
                lesson_slug=record.lesson_slug,
                score=record.score,
                created_at=record.created_at,
            )
            for record in quiz_attempts[:5]
        ],
    )


@router.get("/lessons/{lesson_slug}/notes", response_model=list[NoteRead])
def list_notes(
    lesson_slug: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    records = db.scalars(
        select(Note).where(Note.lesson_slug == lesson_slug, Note.user_id == user.user_id).order_by(Note.created_at.desc())
    ).all()
    return [
        NoteRead(
            id=record.id,
            body=record.body,
            lesson_slug=record.lesson_slug,
            anchor_type=record.anchor_type,
            anchor_value=record.anchor_value,
            created_at=record.created_at,
        )
        for record in records
    ]


@router.post("/lessons/{lesson_slug}/notes", response_model=NoteRead)
def create_note(
    lesson_slug: str,
    payload: NoteCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    note_body = payload.body.strip()
    if not note_body:
        raise HTTPException(status_code=422, detail="Note body cannot be empty.")
    record = Note(
        user_id=user.user_id,
        lesson_slug=lesson_slug,
        body=note_body,
        anchor_type=payload.anchor_type,
        anchor_value=payload.anchor_value,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return NoteRead(
        id=record.id,
        body=record.body,
        lesson_slug=record.lesson_slug,
        anchor_type=record.anchor_type,
        anchor_value=record.anchor_value,
        created_at=record.created_at,
    )


@router.post("/quiz-attempts")
def record_quiz_attempt(
    payload: QuizAttemptCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    record = QuizAttempt(
        user_id=user.user_id,
        lesson_slug=payload.lesson_slug,
        score=payload.score,
        responses=payload.responses,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"status": "saved", "attempt_id": record.id, "score": record.score}
