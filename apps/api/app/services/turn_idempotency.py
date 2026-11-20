"""Idempotency-Key on POST /tutor/turns (plan 7.3 "mutations carry client keys"; DI-40; Phase 3 spec 7.13).

A client that retries a POST /tutor/turns with the same Idempotency-Key gets the first turn's response back instead
of a second turn. The key is optional; when sent it must match the package's tutor_pipeline.idempotency.key_pattern
(bounded; 422 otherwise). It is scoped to the caller: the same key from another principal is another key. Only its
sha256 is stored, with the sha256 of the request (message, thread, lesson scope, presentation plan):
  - same caller, same key, same request, first turn done   -> its response, header Idempotent-Replayed: true
  - same caller, same key, same request, first still running -> 409
  - same caller, same key, a different request              -> 422
A key is remembered for ttl_hours; after that the same key starts a new turn and its expired row is replaced. A claim
still in progress (no response yet) is held for in_progress_lease_seconds only (600 s, PD-11; spec 18.7 E7): the
route releases a failed turn's claim itself, but a process that dies mid-turn (a scale-in, an OOM, a crash) or a
release that fails leaves the claim behind, and without a lease every retry would get 409 for the whole TTL. 600 s is
twice Cloud Run's default 300 s request timeout; the service's configured timeout is read and recorded at each
release (infra/cloudrun/deployment.md), because the lease is only a liveness bound, not the safety argument.

Safety does not depend on any timeout (spec 18.8 F13). Each claim carries a random claim_token. The turn's own
transaction fills the claim with a conditional UPDATE (this id, this token, still no response), and the turn
commits only when that UPDATE changed exactly one row; a release deletes only its own token's row; replacing an
abandoned claim deletes it only while it still has no response and is still past the lease. So a request that runs
past the lease while a retry takes the key over finds its claim gone (PostgreSQL) or holding another token (SQLite,
which reused the deleted row's id before AUTOINCREMENT) and fails with 409: one key never yields two turns, and a
late request never overwrites, or releases, the retry's row. Rows are user-keyed (erasure deletes them; guest
retention deletes a guest's with its other data) and otherwise live as long as the turn they answer for, as the
other tutor tables do. The route stays development-only (spec conflict 4).
"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import re
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.config_package import TutorPipelineParams, canonical_sha256
from app.db_models import TutorTurnIdempotency

# The request header POST /tutor/turns reads the key from; configuration package v2 names it
# (tutor_pipeline.idempotency.header) and package_check requires the two to agree (spec 18.10 H3).
IDEMPOTENCY_HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotent-Replayed"
SUPERSEDED = "This request ran past its Idempotency-Key lease and a retry took the key over; that retry's turn stands."


class ClaimLost(HTTPException):
    """The claim this request held was replaced or removed before its turn committed (spec 18.8 F13): 409."""

    def __init__(self) -> None:
        super().__init__(status_code=409, detail=SUPERSEDED, headers={"Cache-Control": "no-store"})


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


def _lookup(db: Session, user_id: str, key_digest: str) -> TutorTurnIdempotency | None:
    return db.scalars(
        select(TutorTurnIdempotency)
        .where(TutorTurnIdempotency.user_id == user_id, TutorTurnIdempotency.key_sha256 == key_digest)
        .execution_options(populate_existing=True)
    ).first()


def find(db: Session, user_id: str, key_digest: str, *, now: datetime, ttl_hours: int, lease_seconds: int) -> TutorTurnIdempotency | None:
    """The caller's live record of this key. An expired one (older than ttl_hours), or an abandoned claim (no response
    and older than lease_seconds), is deleted so the key can be used again. The delete is conditional (spec 18.8 F13):
    an abandoned claim goes only while it still has no response, so a request that fills it concurrently keeps its
    turn, and the record is then read again and returned."""
    for _ in range(2):
        row = _lookup(db, user_id, key_digest)
        if row is None:
            return None
        created = _utc(row.created_at)
        expired_before = now - timedelta(hours=ttl_hours)
        lease_before = now - timedelta(seconds=lease_seconds)
        if created < expired_before:
            condition = (TutorTurnIdempotency.created_at < expired_before,)
        elif row.response_body is None and created < lease_before:
            condition = (TutorTurnIdempotency.response_body.is_(None), TutorTurnIdempotency.created_at < lease_before)
        else:
            return row
        removed = db.execute(
            delete(TutorTurnIdempotency).where(TutorTurnIdempotency.id == row.id, *condition).execution_options(synchronize_session=False)
        ).rowcount
        db.expunge(row)
        if removed:
            return None
        # The claim was filled (or replaced) in the meantime: read it again.
    return _lookup(db, user_id, key_digest)


def new_claim(*, user_id: str, key_digest: str, request_digest: str, now: datetime) -> TutorTurnIdempotency:
    return TutorTurnIdempotency(user_id=user_id, key_sha256=key_digest, request_sha256=request_digest, created_at=now, claim_token=uuid4().hex)


def fill(db: Session, claim: TutorTurnIdempotency, *, turn_id: str, response_body: str) -> None:
    """Fill this request's claim inside the turn's transaction, or raise ClaimLost (409) when the claim is no longer
    this request's: replaced by a retry after the lease, or removed (spec 18.8 F13). The turn then rolls back."""
    changed = db.execute(
        update(TutorTurnIdempotency)
        .where(TutorTurnIdempotency.id == claim.id, TutorTurnIdempotency.claim_token == claim.claim_token, TutorTurnIdempotency.response_body.is_(None))
        .values(turn_id=turn_id, response_body=response_body)
        .execution_options(synchronize_session=False)
    ).rowcount
    if changed != 1:
        raise ClaimLost()


def release(db: Session, claim: TutorTurnIdempotency) -> None:
    """Delete this request's own claim (its turn failed), and nothing else: never a retry's claim that took over the
    key, or reused the id (spec 18.8 F13)."""
    db.execute(
        delete(TutorTurnIdempotency)
        .where(TutorTurnIdempotency.id == claim.id, TutorTurnIdempotency.claim_token == claim.claim_token, TutorTurnIdempotency.response_body.is_(None))
        .execution_options(synchronize_session=False)
    )


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
