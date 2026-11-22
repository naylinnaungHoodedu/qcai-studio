from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user
from app.core.config import get_settings
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
    QuizAttemptResult,
    LearnerRecordOperationInput,
)
from app.services.learner_record import apply_learner_record_operations
from app.services.learner_record_sync import SERVER_REPLICA, begin_server_assessment
from app.services.learner_progress import build_course_progress
from app.services.quiz_keys import score_attempt
from app.services.store import get_course_store
from app.services.text_utils import sanitize_user_text

router = APIRouter(prefix="/content", tags=["content"])
PUBLIC_CONTENT_CACHE_CONTROL = "public, max-age=300, stale-while-revalidate=60"


def _public_content_head_response() -> Response:
    return Response(status_code=200, headers={"Cache-Control": PUBLIC_CONTENT_CACHE_CONTROL})


@router.get("/course", response_model=CourseOverview)
def get_course(response: Response):
    response.headers["Cache-Control"] = PUBLIC_CONTENT_CACHE_CONTROL
    return get_course_store().overview


@router.head("/course")
def head_course():
    return _public_content_head_response()


@router.get("/modules/{module_slug}")
def get_module(module_slug: str, response: Response):
    store = get_course_store()
    module = store.modules.get(module_slug)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found.")
    response.headers["Cache-Control"] = PUBLIC_CONTENT_CACHE_CONTROL
    lessons = [store.lessons[slug] for slug in module.lesson_slugs]
    return {"module": module, "lessons": lessons}


@router.head("/modules/{module_slug}")
def head_module(module_slug: str):
    store = get_course_store()
    if module_slug not in store.modules:
        raise HTTPException(status_code=404, detail="Module not found.")
    return _public_content_head_response()


@router.get("/lessons/{lesson_slug}", response_model=LessonDetail)
def get_lesson(lesson_slug: str, response: Response):
    store = get_course_store()
    lesson = store.lessons.get(lesson_slug)
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found.")
    response.headers["Cache-Control"] = PUBLIC_CONTENT_CACHE_CONTROL
    return lesson


@router.head("/lessons/{lesson_slug}")
def head_lesson(lesson_slug: str):
    store = get_course_store()
    if lesson_slug not in store.lessons:
        raise HTTPException(status_code=404, detail="Lesson not found.")
    return _public_content_head_response()


@router.get("/progress", response_model=CourseProgress)
def get_progress(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return build_course_progress(db, user.user_id)


@router.get("/lessons/{lesson_slug}/notes", response_model=list[NoteRead])
def list_notes(
    lesson_slug: str,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    records = db.scalars(
        select(Note).where(Note.lesson_slug == lesson_slug, Note.user_id == user.user_id).order_by(Note.created_at.desc())
    ).all()[offset : offset + limit]
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
    note_body = sanitize_user_text(payload.body)
    if not note_body:
        raise HTTPException(status_code=422, detail="Note body cannot be empty.")
    record = Note(
        user_id=user.user_id,
        lesson_slug=lesson_slug,
        body=note_body,
        anchor_type=sanitize_user_text(payload.anchor_type or "", preserve_newlines=False) or None,
        anchor_value=sanitize_user_text(payload.anchor_value or "", preserve_newlines=False) or None,
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


@router.post("/quiz-attempts", response_model=QuizAttemptResult)
def record_quiz_attempt(
    payload: QuizAttemptCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    store = get_course_store()
    lesson = store.lessons.get(payload.lesson_slug)
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found.")
    # Scored on the server (task 1.2, E-110) against the server-side keys; the lesson payload carries none (R-42).
    keys = store.quiz_keys.for_lesson(payload.lesson_slug)
    score, responses, feedback = score_attempt(keys, payload.responses)
    durable = user.provider not in {"guest", "demo"}
    server_clock = (
        begin_server_assessment(db, user.user_id, payload.lesson_slug)
        if durable and get_settings().learner_sync == "on" else None
    )
    record = QuizAttempt(
        user_id=user.user_id,
        lesson_slug=payload.lesson_slug,
        score=score,
        responses=responses,
    )
    db.add(record)
    db.flush()
    # Durable identities write the same outcome to the authoritative record.
    # Guest/demo behavior remains a non-cross-device preview surface.
    if durable:
        question_count = len(keys)
        mastery = round(min(1.0, score / question_count), 6) if question_count else 0.0
        base_counter = record.id * 2 if server_clock is None else server_clock
        operation_prefix = "quiz" if server_clock is None else "quiz-v2"
        operations = [
            LearnerRecordOperationInput(
                operation_id=f"{operation_prefix}-{record.id}-mastery",
                replica_id=SERVER_REPLICA,
                logical_counter=base_counter + 1,
                operation_type="mastery_set",
                payload={"skill_id": f"lesson:{payload.lesson_slug}", "value": mastery},
            ),
            LearnerRecordOperationInput(
                operation_id=f"{operation_prefix}-{record.id}-attempt",
                replica_id=SERVER_REPLICA,
                logical_counter=base_counter + 2,
                operation_type="increment_attempt",
                payload={"item_id": f"lesson:{payload.lesson_slug}", "delta": 1},
            ),
        ]
        if mastery >= 0.7:
            operations.append(
                LearnerRecordOperationInput(
                    operation_id=f"{operation_prefix}-{record.id}-complete",
                    replica_id=SERVER_REPLICA,
                    logical_counter=base_counter + 3,
                    operation_type="complete_item",
                    payload={"item_id": f"lesson:{payload.lesson_slug}"},
                )
            )
        apply_learner_record_operations(db, user.user_id, operations)
    db.commit()
    db.refresh(record)
    # The model answers and rubrics, only after a saved attempt and only for the questions it answered (Phase 4 spec 4.14).
    return QuizAttemptResult(attempt_id=record.id, score=record.score, feedback=feedback)
