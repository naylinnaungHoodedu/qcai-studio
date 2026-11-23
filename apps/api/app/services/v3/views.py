"""The reviewer's view of a queue item (plan Phase 6 H "Reviewers see public-corpus spans only, never learner identifiers
or private-corpus spans [Evidence E-95]"; Phase 6 spec 4.14; PD-36).

item_view reads the subject record's claims: a span is shown only when its record is public and quotable under the
corpus registry in force (contained_answers.span_is_quotable; under D-31 nothing is, so outside development nothing is
shown), and a claim's text only when all its spans are shown. An item is reviewable when every claim it covers is shown
(an abstention with no claim is reviewable); a record that does not parse shows no claim and is not reviewable. The view
carries the item id, its subject, the record's kind and decision, the triggers and reasons, held, the derived workflow
state, the round, whether it needs a double review, the enqueue time and age, a keyed digest of the response id, and the
claims: never a response, turn, thread, message or user id, an email, learner or rendered text, a vote, an objection
type, a severity, an exposure, a support share, a priority, a final, another round's label or a ledger seq (blind).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.v3.contracts import ClaimView, QueueItemView, SpanView
from app.services.v3.queue import iso, parse_entry, record_row, reviewable, span_shown, split, subject_claims, utc, workflow_state


def item_view(db: Session, row: Any, *, store: Any, corpus_registry: Any, now: datetime) -> QueueItemView:
    record = record_row(db, row.ledger_seq)
    entry = parse_entry(record)
    claims = subject_claims(row, entry) or ()
    views = []
    for claim in claims:
        spans = []
        for span_id in claim.span_ids:
            shown, text = span_shown(span_id, store=store, corpus_registry=corpus_registry)
            spans.append(SpanView(span_id=span_id, shown=shown, text=text))
        views.append(ClaimView(claim_id=claim.claim_id, text=claim.text if all(span.shown for span in spans) else None, spans=tuple(spans)))
    enqueued = utc(row.enqueued_at)
    return QueueItemView(
        item_id=row.item_id, subject=row.subject, record_kind=row.record_kind,
        decision=record.decision if record is not None else "abstain",
        triggers=tuple(sorted(split(row.triggers))), reasons=tuple(sorted(split(row.reasons))), held=bool(row.held),
        state=workflow_state(db, row, now=now), review_round=int(row.review_round), double_review=bool(row.double_review),
        reviewable=reviewable(row, entry, store=store, corpus_registry=corpus_registry), enqueued_at=iso(enqueued),
        age_s=max(0, int((utc(now) - enqueued).total_seconds())), response_digest=row.response_digest, claims=tuple(views),
    )
