"""Idempotency-Key on POST /tutor/turns (plan 7.3 "mutations carry client keys"; DI-40; Phase 3 spec 7.13).

A client that retries a POST /tutor/turns with the same Idempotency-Key gets the first turn's response back instead
of a second turn. The key is optional; when sent it must match the package's tutor_pipeline.idempotency.key_pattern
(bounded; 422 otherwise). It is scoped to the caller: the same key from another principal is another key. Only its
sha256 is stored, with the sha256 of the request (message, thread, lesson scope, presentation plan):
  - same caller, same key, same request, first turn done   -> its response, header Idempotent-Replayed: true
  - same caller, same key, same request, first still running -> 409
  - same caller, same key, a different request              -> 422
A key is remembered for ttl_hours; after that the same key starts a new turn and its expired row is replaced. Rows are
user-keyed (erasure deletes them; guest retention deletes a guest's with its other data) and otherwise live as long
as the turn they answer for, as the other tutor tables do. The row is claimed
and committed before the turn runs, filled in the turn's own transaction and released if the turn fails, so two
concurrent requests with one key never create two turns. The route stays development-only (spec conflict 4).
"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import re

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config_package import TutorPipelineParams, canonical_sha256
from app.db_models import TutorTurnIdempotency

REPLAYED_HEADER = "Idempotent-Replayed"


def _utc(value: datetime) -> datetime:
    from app.services.ledger import _utc as ledger_utc

    return ledger_utc(value)


def parse_key(raw: str | None, params: TutorPipelineParams | None) -> str | None:
    """The validated key, or None when none was sent. 422 for a malformed or oversized key."""
    if raw is None:
        return None
    if params is None:
        raise HTTPException(status_code=422, detail="Idempotency-Key needs configuration package v2.")
    if not re.fullmatch(params.idempotency_key_pattern, raw):
        raise HTTPException(status_code=422, detail="Idempotency-Key is malformed or too long.")
    return raw


def key_sha256(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def request_sha256(*, message: str, thread_id: str | None, lesson_slug: str | None, presentation_plan: str | None) -> str:
    return canonical_sha256({"message": message, "thread_id": thread_id, "lesson_slug": lesson_slug, "presentation_plan": presentation_plan})


def find(db: Session, user_id: str, key_digest: str, *, now: datetime, ttl_hours: int) -> TutorTurnIdempotency | None:
    """The caller's live record of this key; an expired one is deleted (flushed) so the key can be used again."""
    row = db.scalars(
        select(TutorTurnIdempotency).where(TutorTurnIdempotency.user_id == user_id, TutorTurnIdempotency.key_sha256 == key_digest)
    ).first()
    if row is not None and _utc(row.created_at) < now - timedelta(hours=ttl_hours):
        db.delete(row)
        db.flush()
        return None
    return row


def answer_for(row: TutorTurnIdempotency, request_digest: str) -> JSONResponse:
    """What a request that found an existing record of its key gets: 422, 409 or the first response."""
    headers = {"Cache-Control": "no-store"}
    if row.request_sha256 != request_digest:
        return JSONResponse(status_code=422, content={"detail": "This Idempotency-Key was already used with a different request."}, headers=headers)
    if row.response_body is None:
        return JSONResponse(status_code=409, content={"detail": "A request with this Idempotency-Key is still being processed."}, headers=headers)
    body = json.loads(row.response_body)
    headers[REPLAYED_HEADER] = "true"
    for name, field in (("x-assistant-provider", "provider"), ("x-assistant-model", "model")):
        if isinstance(body.get(field), str):
            headers[name] = body[field]
    return JSONResponse(status_code=200, content=body, headers=headers)
