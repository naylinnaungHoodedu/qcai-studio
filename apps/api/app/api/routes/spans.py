"""GET /spans/{span_id}: read-only span resolution (plan Phase 2 task 2.4; Phase 2 spec 2.6, conflict 8), and its
plan 7.3 alias GET /evidence/spans/{span_id} (Phase 3 spec 7.13: "public license_class only").

Always registered, so the authorization matrix stays static, but 404 unless SPAN_RESOLVER_ROUTE_ENABLED (on in
development, off elsewhere while the D-05 freeze holds). It returns span metadata, and the excerpt only for a
servable span (current, public plane, a bound document the manifest approves), which D-31 makes none. Every
miss is the same 404 with Cache-Control: no-store: a disabled route, a malformed or unknown id, a non-public
plane, or, in a governed build, a document span of an item that is not approved. No credential is read.
license_class is derived from the resolved span's plane and the manifest (CorpusRegistry.license_class), never
labelled: a span whose class is not public is the same 404 (plan 7.3 "public license_class only"; 7.5 "defense in
depth"), even if the resolver ever returned one.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.corpus_governance import get_corpus_registry
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.schemas import SpanResolution
from app.services.span_resolver import SPAN_ID_PATTERN
from app.services.store import get_course_store, get_span_resolver

router = APIRouter(prefix="/spans", tags=["spans"])
evidence_router = APIRouter(prefix="/evidence", tags=["evidence"])
SPAN_CACHE_CONTROL = "public, max-age=300, stale-while-revalidate=60"
NOT_FOUND = {"detail": "Span not found."}
# The two paths share one SPANS_RATE_LIMIT window per client (slowapi otherwise keeps one window per endpoint, which
# would let a client alternating between the paths make twice the limit of span lookups).
SPANS_RATE_LIMIT_SCOPE = "span-resolver"


def _not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content=NOT_FOUND, headers={"Cache-Control": "no-store"})


def _resolve_span(span_id: str, request: Request, response: Response, db: Session):
    settings = get_settings()
    if not settings.span_resolver_route_enabled or not SPAN_ID_PATTERN.match(span_id):
        return _not_found()
    resolved = get_span_resolver().resolve(span_id, db)
    if resolved is None:
        return _not_found()
    registry = get_corpus_registry(settings)
    license_class = registry.license_class(plane=resolved.plane, item_id=resolved.item_id)
    if license_class is None:
        return _not_found()
    if settings.enforce_corpus_governance and resolved.kind == "document" and not registry.is_servable_item(resolved.item_id):
        return _not_found()
    response.headers["Cache-Control"] = SPAN_CACHE_CONTROL
    return SpanResolution(
        span_id=resolved.span_id,
        scheme=resolved.scheme,
        item_id=resolved.item_id,
        item_version=resolved.item_version,
        kind=resolved.kind,
        plane=resolved.plane,
        section_ordinal=resolved.section_ordinal,
        start=resolved.start,
        end=resolved.end,
        content_hash=resolved.content_hash,
        servable=resolved.servable,
        current=resolved.current,
        registered=resolved.registered,
        corpus_version_first_seen=resolved.corpus_version_first_seen,
        corpus_version=get_course_store().corpus_version,
        excerpt=resolved.text if resolved.servable else None,
        license_class=license_class,
    )


@router.get("/{span_id}", response_model=SpanResolution, responses={404: {"description": "Span not found."}})
@limiter.shared_limit(lambda: get_settings().spans_rate_limit, scope=SPANS_RATE_LIMIT_SCOPE)
def resolve_span(span_id: str, request: Request, response: Response, db: Session = Depends(get_db)):
    return _resolve_span(span_id, request, response, db)


@evidence_router.get("/spans/{span_id}", response_model=SpanResolution, responses={404: {"description": "Span not found."}})
@limiter.shared_limit(lambda: get_settings().spans_rate_limit, scope=SPANS_RATE_LIMIT_SCOPE)
def resolve_evidence_span(span_id: str, request: Request, response: Response, db: Session = Depends(get_db)):
    return _resolve_span(span_id, request, response, db)
