"""The V3 routes (plan Phase 6 D tasks 1-3, E "Escalation and adjudication modules and tables (API)", H; AC-6-6, AC-6-7;
Phase 6 spec section 9).

Always registered, so the authorization matrix stays static. The reviewer routes need the closed role `reviewer`
(app.core.reviewer_access), a dependency that runs before the route's body: a caller of any other role, a guest
included, gets 403 and one authz.denied security event in every environment and whatever V3_QUEUE says, and outside
development every caller gets 403 and authz.denied while the reviewer pool (D-18) is unstaffed. Only an admitted
reviewer (development) reaches the body, which answers 404 unless V3_QUEUE is shadow or on. Reviewers see claim text and
public, quotable span text, span ids and keyed digests only, never a learner identifier. A successful reviewer call
records one v3.* security event; a 404, 409, 422 or 503 outcome records none. The learner flag route (POST /v3/flags)
answers 404 unless the environment is development and V3_QUEUE is shadow or on: the caller's own tutor turn (another
learner's, a missing and a pre-ledger turn get the same 404); it sets F_i = 0 and queues the response (X3), and changes
no verdict and no ledger row. Mutations carry client keys (plan 7.3): adjudicate and apply take a client_key (a repeat
returns duplicate true and writes nothing); a flag is idempotent per learner and turn; a claim is idempotent for its
lease holder. A write the database kept refusing (queue.V3Busy: a SQLite lock that outlasted the retries) answers 503.
Every response is Cache-Control: no-store.
"""

from __future__ import annotations

from datetime import UTC, datetime
import re

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user
from app.core.config import Settings, get_settings
from app.core.config_package import get_config_package
from app.core.corpus_governance import get_corpus_registry
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.core.reviewer_access import require_reviewer
from app.services import v3
from app.services.security_log import record_security_event, route_template
from app.services.store import get_course_store
from app.services.v3.contracts import ITEM_ID, AdjudicationRequest, ApplyRequest, FlagRequest
from app.services.v3.queue import V3Busy, V3Conflict, V3NotFound, iso

router = APIRouter(prefix="/v3", tags=["v3"])
ITEM_ID_PATTERN = re.compile(ITEM_ID)
NO_STORE = {"Cache-Control": "no-store"}
V3_FLAG_RATE_LIMIT_SCOPE = "v3-flag"
ORDER = ["priority desc", "enqueued_at", "item_id"]


def _not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Not Found"}, headers=NO_STORE)


def _conflict(reason: str) -> JSONResponse:
    status = 422 if reason == "labels_do_not_match_subject" else 409
    return JSONResponse(status_code=status, content={"detail": reason}, headers=NO_STORE)


def _busy() -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "busy"}, headers={**NO_STORE, "Retry-After": "1"})


def _ok(content) -> JSONResponse:
    return JSONResponse(status_code=200, content=content, headers=NO_STORE)


def _off(settings: Settings) -> bool:
    return v3.mode(settings, get_config_package(settings)) == "off"


def flag_intake_open(settings: Settings) -> bool:
    """The learner flag intake runs in development only, and only while V3 is on or in shadow (DI-97)."""
    return settings.environment.lower() == "development" and not _off(settings)


def _event(name: str, request: Request, user: AuthUser, **details) -> None:
    record_security_event(name, "success", connection=request, actor_role=user.role, subject=user.user_id,
                          details={"route": route_template(request), **details})


def _now() -> datetime:
    return datetime.now(UTC)


def _sources(settings: Settings):
    return get_course_store(), get_corpus_registry(settings)


@router.post("/flags", responses={404: {"description": "Not Found"}, 409: {"description": "not_recorded_yet"}, 503: {"description": "busy"}})
@limiter.shared_limit(lambda: get_settings().v3_flag_rate_limit, scope=V3_FLAG_RATE_LIMIT_SCOPE)
def flag_response(request: Request, response: Response, payload: FlagRequest, db: Session = Depends(get_db),
                  user: AuthUser = Depends(get_current_user), settings: Settings = Depends(get_settings)):
    if not flag_intake_open(settings):
        return _not_found()
    from app.services.v3.feedback import record_flag

    try:
        _, duplicate = record_flag(db, user_id=user.user_id, response_id=payload.response_id, settings=settings,
                                   package=get_config_package(settings), now=_now())
    except V3NotFound:
        return _not_found()
    except V3Conflict as exc:
        return _conflict(exc.reason)
    except V3Busy:
        return _busy()
    except v3.V3Off:
        return _not_found()
    return _ok({"status": "recorded", "f_i": 0.0, "duplicate": duplicate})


@router.get("/queue", responses={404: {"description": "Not Found"}})
def read_queue(request: Request, state: str | None = Query(default=None, pattern="^(queued|claimed|adjudicated|applied)$"),
               limit: int = Query(default=50, ge=1, le=100), db: Session = Depends(get_db), user: AuthUser = Depends(require_reviewer),
               settings: Settings = Depends(get_settings)):
    if _off(settings):
        return _not_found()
    from app.services.v3.queue import list_queue
    from app.services.v3.views import item_view

    now = _now()
    store, corpus = _sources(settings)
    rows = list_queue(db, state=state, limit=limit, now=now)
    items = [item_view(db, row, store=store, corpus_registry=corpus, now=now).model_dump(mode="json") for row in rows]
    _event("v3.queue_read", request, user, count=len(items))
    return _ok({"items": items, "order": ORDER})


@router.post("/scan", responses={404: {"description": "Not Found"}, 503: {"description": "busy"}})
def scan(request: Request, user: AuthUser = Depends(require_reviewer), settings: Settings = Depends(get_settings)):
    if _off(settings):
        return _not_found()
    from dataclasses import asdict

    from app.services.v3.scan import run_scan

    try:
        result = run_scan(settings=settings, package=get_config_package(settings), limit=500)
    except v3.V3Off:
        return _not_found()
    except V3Busy:
        return _busy()
    body = asdict(result)
    _event("v3.scan_run", request, user, **{key: value for key, value in body.items() if key != "done"})
    return _ok(body)


@router.get("/items/{item_id}", responses={404: {"description": "Not Found"}})
def read_item(item_id: str, request: Request, db: Session = Depends(get_db), user: AuthUser = Depends(require_reviewer),
              settings: Settings = Depends(get_settings)):
    if _off(settings) or not ITEM_ID_PATTERN.match(item_id):
        return _not_found()
    from app.services.v3.queue import get_item
    from app.services.v3.views import item_view

    row = get_item(db, item_id)
    if row is None:
        return _not_found()
    store, corpus = _sources(settings)
    body = item_view(db, row, store=store, corpus_registry=corpus, now=_now()).model_dump(mode="json")
    body["final_gold_seq"] = row.final_gold_seq
    _event("v3.item_read", request, user, item_id=item_id)
    return _ok(body)


@router.post("/items/{item_id}/claim", responses={404: {"description": "Not Found"}, 409: {"description": "A workflow conflict."},
                                                  503: {"description": "busy"}})
def claim(item_id: str, request: Request, db: Session = Depends(get_db), user: AuthUser = Depends(require_reviewer),
          settings: Settings = Depends(get_settings)):
    if _off(settings) or not ITEM_ID_PATTERN.match(item_id):
        return _not_found()
    from app.services.v3.queue import claim_item

    store, corpus = _sources(settings)
    try:
        lease = claim_item(db, item_id, user_id=user.user_id, now=_now(), package=get_config_package(settings), store=store, corpus_registry=corpus)
    except V3NotFound:
        return _not_found()
    except V3Conflict as exc:
        return _conflict(exc.reason)
    except V3Busy:
        return _busy()
    _event("v3.item_claimed", request, user, item_id=item_id, review_round=lease.review_round)
    return _ok({"item_id": item_id, "state": "claimed", "review_round": lease.review_round, "lease_expires_at": iso(lease.lease_expires_at)})


@router.post("/items/{item_id}/adjudicate", responses={404: {"description": "Not Found"}, 409: {"description": "A workflow conflict."},
                                                       422: {"description": "The labels do not match the item's subject."},
                                                       503: {"description": "busy"}})
def adjudicate(item_id: str, payload: AdjudicationRequest, request: Request, db: Session = Depends(get_db),
               user: AuthUser = Depends(require_reviewer), settings: Settings = Depends(get_settings)):
    if _off(settings) or not ITEM_ID_PATTERN.match(item_id):
        return _not_found()
    from app.services.v3 import queue

    store, corpus = _sources(settings)
    try:
        result = queue.adjudicate(db, item_id, payload, user_id=user.user_id, now=_now(), package=get_config_package(settings), store=store,
                                  corpus_registry=corpus)
    except V3NotFound:
        return _not_found()
    except V3Conflict as exc:
        return _conflict(exc.reason)
    except V3Busy:
        return _busy()
    _event("v3.item_adjudicated", request, user, item_id=item_id, review_round=result.review_round, duplicate=result.duplicate)
    return _ok({"item_id": item_id, "gold_seq": result.gold_seq, "record_hash": result.record_hash, "review_round": result.review_round,
                "state": result.state, "duplicate": result.duplicate})


@router.post("/items/{item_id}/apply", responses={404: {"description": "Not Found"}, 409: {"description": "A workflow conflict."},
                                                  503: {"description": "busy"}})
def apply(item_id: str, payload: ApplyRequest, request: Request, db: Session = Depends(get_db), user: AuthUser = Depends(require_reviewer),
          settings: Settings = Depends(get_settings)):
    if _off(settings) or not ITEM_ID_PATTERN.match(item_id):
        return _not_found()
    from app.services.v3.queue import apply_item

    try:
        result = apply_item(db, item_id, payload, user_id=user.user_id, now=_now())
    except V3NotFound:
        return _not_found()
    except V3Conflict as exc:
        return _conflict(exc.reason)
    except V3Busy:
        return _busy()
    _event("v3.item_applied", request, user, item_id=item_id, duplicate=result.duplicate)
    return _ok({"item_id": item_id, "state": "applied", "final_gold_seq": result.final_gold_seq, "duplicate": result.duplicate})


@router.get("/metrics", responses={404: {"description": "Not Found"}})
def metrics(request: Request, db: Session = Depends(get_db), user: AuthUser = Depends(require_reviewer), settings: Settings = Depends(get_settings)):
    if _off(settings):
        return _not_found()
    from app.services.v3.metrics import slis

    body = slis(db, get_config_package(settings), now=_now())
    _event("v3.metrics_read", request, user)
    return _ok(body)
