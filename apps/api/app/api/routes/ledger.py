"""GET /ledger/responses/{response_id}: one tutor response's ledger record (plan 7.3 "owner or reviewer"; Phase 3
spec 9, conflicts 5 and 27).

Always registered, so the authorization matrix stays static, but 404 unless LEDGER_ROUTE_ENABLED (on in
development, off elsewhere while the D-05 freeze holds). The turn's owner reads its own legacy record without the
chain position fields. A turn with no record reads as recorded false, verdict "no-verdict" (plan G; nothing is
written), and the turn's own ledger_record_expected says why (spec 18.8 F10, F12): legacy_turn true and
unrecorded_reason "earlier_image" for a turn an image that keeps no ledger created (before Phase 3, or one served
during a rollback window or before traffic moved to a Phase 3 revision); unrecorded_reason "ledger_disabled" for a
turn made while TUTOR_LEDGER_ENABLED was off; "missing" for a turn that expected a record and has none (an append
that failed, was refused, or was deferred and then failed), so a lost record is never shown as a pre-ledger turn
(plan L, "a ledger write fails"; spec 18.7 E6). A legacy record whose delivered quotations conflict under the V1.7 rule
of the package in force at read time carries their labels (`conflicts`, evidence_panel.record_conflicts; AC-4-6,
Phase 4 spec 4.15 item 3), for its owner and for the reviewer alike; the record's versions name the package in force
at delivery, and nothing stores the labels that delivery showed (DI-68). The reviewer role (LEDGER_READER_ROLES; plan 7.3
"owner or reviewer", nothing wider), where the reviewer gate admits it (app.core.reviewer_access.reviewer_admitted:
development, or a staffed reviewer pool; outside development no reviewer is admitted while D-18 is open, and such a
caller reads as an owner, Phase 6 spec 4.12), reads any record, shadow records included, with the chain fields; each
such read is a security event (plan 7.6). Any other role, admin included, is an owner reader only. A learner never
sees a shadow record (AC-3-6): every miss is the same 404 with Cache-Control: no-store.
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user
from app.core.authorization import LEDGER_READER_ROLES
from app.core.config import get_settings
from app.core.config_package import get_config_package
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.core.reviewer_access import reviewer_admitted
from app.db_models import ResponseLedgerRecord, TutorTurn
from app.schemas import LedgerClaimRead, LedgerRecordRead, LedgerResponseRead
from app.services.evidence_panel import record_conflicts
from app.services.ledger import _utc
from app.services.security_log import record_security_event, route_template
from app.services.store import get_course_store
from app.services.tutor_pipeline.contracts import RESPONSE_ID

router = APIRouter(prefix="/ledger", tags=["ledger"])
RESPONSE_ID_PATTERN = re.compile(RESPONSE_ID)
NOT_FOUND = {"detail": "Response not found."}


def _not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content=NOT_FOUND, headers={"Cache-Control": "no-store"})


def _unrecorded(response_id: str, turn: TutorTurn) -> LedgerResponseRead:
    """A turn with no ledger record, by what the turn itself expected (spec 18.8 F12)."""
    expected = turn.ledger_record_expected
    reason = "earlier_image" if expected is None else "missing" if expected else "ledger_disabled"
    return LedgerResponseRead(response_id=response_id, recorded=False, legacy_turn=expected is None, unrecorded_reason=reason)


def _record(row: ResponseLedgerRecord, *, reviewer: bool) -> LedgerRecordRead:
    entry = json.loads(row.entry)
    conflicts = None
    if row.delivery == "legacy":
        spans = get_course_store().span_registry
        conflicts = record_conflicts(entry, get_config_package(get_settings()),
                                     item_of=lambda span_id: getattr(spans.get(span_id), "item_id", None))
    return LedgerRecordRead(
        response_id=row.response_id,
        delivery=row.delivery,
        decision=row.decision,
        abstention_reason=entry.get("abstention_reason"),
        created_at=_utc(row.created_at),
        claim_set_hash=row.claim_set_hash,
        span_ids=list(entry.get("span_ids") or []),
        claims=[LedgerClaimRead(claim_id=claim["claim_id"], text=claim["text"], span_ids=list(claim["span_ids"])) for claim in entry.get("claims") or []],
        retrieval=entry.get("retrieval") or {},
        presentation=entry.get("presentation"),
        provenance=entry.get("provenance") or {},
        versions=entry.get("versions") or {},
        resolved_question=entry.get("resolved_question"),
        conflicts=conflicts,
        seq=row.seq if reviewer else None,
        prev_hash=row.prev_hash if reviewer else None,
        record_hash=row.record_hash if reviewer else None,
        entry_sha256=row.entry_sha256 if reviewer else None,
        shadowed_response_id=row.shadowed_response_id if reviewer else None,
    )


@router.get("/responses/{response_id}", response_model=LedgerResponseRead, responses={404: {"description": "Response not found."}})
@limiter.limit(lambda: get_settings().ledger_rate_limit)
def read_ledger_response(
    response_id: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    settings = get_settings()
    if not settings.ledger_route_enabled or not RESPONSE_ID_PATTERN.match(response_id):
        return _not_found()
    row = db.scalars(select(ResponseLedgerRecord).where(ResponseLedgerRecord.response_id == response_id)).first()
    result: LedgerResponseRead | None = None
    if user.role in LEDGER_READER_ROLES and reviewer_admitted(settings):
        if row is not None:
            result = LedgerResponseRead(response_id=response_id, recorded=True, legacy_turn=False, record=_record(row, reviewer=True))
        elif response_id.startswith("turn-") and (turn := db.get(TutorTurn, response_id)) is not None:
            result = _unrecorded(response_id, turn)
        record_security_event(
            "ledger.reviewer_read",
            "success",
            connection=request,
            actor_role=user.role,
            subject=user.user_id,
            details={"route": route_template(request), "delivery": row.delivery if row is not None else "none"},
        )
    elif response_id.startswith("turn-"):
        # A shadow id is 404 for every non-reviewer, whether or not it exists (AC-3-6).
        turn = db.get(TutorTurn, response_id)
        if turn is not None and turn.user_id == user.user_id:
            if row is not None and row.delivery != "shadow":
                result = LedgerResponseRead(response_id=response_id, recorded=True, legacy_turn=False, record=_record(row, reviewer=False))
            elif row is None:
                result = _unrecorded(response_id, turn)
    if result is None:
        return _not_found()
    response.headers["Cache-Control"] = "no-store"
    return result
