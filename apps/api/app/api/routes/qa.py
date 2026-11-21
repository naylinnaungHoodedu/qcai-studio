from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user
from app.core.db import get_db
from app.core.config import get_settings
from app.core.config_package import get_config_package
from app.core.rate_limit import limiter
from app.db_models import QAInteraction
from app.core.corpus_governance import get_corpus_registry
from app.schemas import QAHistoryItem, QARequest, QAResponse
from app.services.answer_history import WITHDRAWN_ANSWER, stored_before_containment
from app.services.evidence_panel import stored_conflicts
from app.services.ledger import LegacyDelivery, LegacyPreparationFailed, record_legacy_delivery
from app.services.provenance import is_withheld_unapproved, label_stored_citation
from app.services.retrieval_metrics import record_citations
from app.services.span_store import persist_cited_spans
from app.services.store import get_course_store, get_qa_engine, get_span_resolver
from app.services.text_utils import sanitize_user_text

router = APIRouter(prefix="/qa", tags=["qa"])


@router.post("/ask", response_model=QAResponse)
@limiter.limit(lambda: get_settings().qa_ask_rate_limit)
def ask_question(
    request: Request,
    response: Response,
    payload: QARequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    question = sanitize_user_text(payload.question)
    if not question:
        raise HTTPException(status_code=422, detail="Question cannot be empty.")
    response = get_qa_engine().ask(question, payload.lesson_slug, payload.top_k)
    db.add(
        QAInteraction(
            user_id=user.user_id,
            lesson_slug=payload.lesson_slug,
            question=question,
            answer=response.answer,
            citations=[citation.model_dump() for citation in response.citations],
        )
    )
    # Text-free identity of the cited spans, so these citations keep resolving (task 2.2).
    persist_cited_spans(db, response.citations, get_course_store())
    db.commit()
    # Plan task 3.8 / F-1: the delivery's ledger record, after the commit and before the answer leaves; bounded and
    # fail-open (ledger.record_legacy_delivery never raises and never changes the response). The attempt is counted
    # there, so an answer whose commit fails is never an attempt (spec 18.7 E5).
    delivery = getattr(response, "_ledger", None)
    if isinstance(delivery, (LegacyDelivery, LegacyPreparationFailed)):
        record_legacy_delivery(delivery)
    return response


@router.get("/history", response_model=list[QAHistoryItem])
def read_question_history(
    lesson_slug: str | None = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    filters = [QAInteraction.user_id == user.user_id]
    if lesson_slug:
        filters.append(QAInteraction.lesson_slug == lesson_slug)
    records = db.scalars(
        select(QAInteraction)
        .where(*filters)
        .order_by(QAInteraction.created_at.desc(), QAInteraction.id.desc())
    ).all()[offset : offset + limit]
    return [_history_item(record, db) for record in records]


def _history_item(record: QAInteraction, db: Session) -> QAHistoryItem:
    # An answer the uncontained build stored is withheld with its citations; the question stays (R-16).
    withdrawn = stored_before_containment(record.created_at)
    citations = []
    conflicts = None
    if not withdrawn:
        # Dual-read (plan Phase 2 G): v0/v1 citations come back labelled legacy_unresolved, never as resolved
        # (AC-2-3), and a governed build withholds citations of items the manifest does not approve ([R13]).
        settings = get_settings()
        registry = get_corpus_registry(settings)
        resolver = get_span_resolver()
        stored = record.citations or []
        labelled = [label_stored_citation(raw, resolver=resolver, db=db, settings=settings, registry=registry) for raw in stored]
        citations = [citation for citation in labelled if citation is not None]
        withheld = sum(1 for raw in stored if is_withheld_unapproved(raw, settings=settings, registry=registry))
        if withheld:
            record_citations("qa_history", 0, 0, withheld)
        # AC-4-6 where the answer is shown again: the V1.7 labels of its quotations (positions in the stored order,
        # which the answer's [n] numbering follows), whatever EVIDENCE_PANEL_ENABLED says (Phase 4 spec 4.15).
        conflicts = stored_conflicts(stored, get_config_package(settings))
    return QAHistoryItem(
        id=record.id,
        lesson_slug=record.lesson_slug,
        question=record.question,
        answer=WITHDRAWN_ANSWER if withdrawn else record.answer,
        citations=citations,
        created_at=record.created_at,
        withdrawn=withdrawn,
        conflicts=conflicts,
    )
