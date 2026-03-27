from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import AnalyticsEvent, Note, QAInteraction, QuizAttempt
from app.schemas import CourseProgress, LessonProgress, ModuleProgress, NoteRead, QuizAttemptRead
from app.services.store import get_course_store


def _score_percent(score: int | None, question_count: int) -> float | None:
    if score is None or question_count <= 0:
        return None
    return round((score / question_count) * 100, 1)


def build_course_progress(db: Session, user_id: str) -> CourseProgress:
    store = get_course_store()
    notes = db.scalars(select(Note).where(Note.user_id == user_id).order_by(Note.created_at.desc())).all()
    quiz_attempts = db.scalars(
        select(QuizAttempt).where(QuizAttempt.user_id == user_id).order_by(QuizAttempt.created_at.desc())
    ).all()
    analytics_events = db.scalars(
        select(AnalyticsEvent).where(AnalyticsEvent.user_id == user_id).order_by(AnalyticsEvent.created_at.desc())
    ).all()
    qa_interactions = db.scalars(
        select(QAInteraction).where(QAInteraction.user_id == user_id).order_by(QAInteraction.created_at.desc())
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
        user_id=user_id,
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
