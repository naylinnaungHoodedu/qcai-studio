from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user
from app.core.db import get_db
from app.db_models import Note, QuizAttempt
from app.schemas import (
    CourseOverview,
    CourseProgress,
    LessonDetail,
    NoteCreate,
    NoteRead,
    QuizAttemptCreate,
    QuizAttemptRead,
)
from app.services.learner_progress import build_course_progress
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

@router.get("/progress", response_model=CourseProgress)
def get_progress(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return build_course_progress(db, user.user_id)


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
