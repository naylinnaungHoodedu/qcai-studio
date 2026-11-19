"""Persist span identity in corpus_spans (plan Phase 2 task 2.2; Phase 2 spec 4.17).

Insert-if-missing on (span_id, item_version), text-free. Written by request-path write-through for the citations a
learner was given (SPAN_REGISTRY_WRITE_THROUGH, default on, not learner-visible) and by the explicit register and
migration jobs; never at start-up. The table is append-only, so a stored citation keeps resolving.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.db_models import CorpusSpan
from app.schemas import Citation
from app.services.spans import SpanRecord, sha256_text

if TYPE_CHECKING:  # pragma: no cover
    from app.services.content_assembler import CourseStore

REGISTERED_BY = ("write-through", "register-job", "migration")


def _row(record: SpanRecord, corpus_version: str, registered_by: str) -> dict:
    return {
        "span_id": record.span_id,
        "scheme": record.scheme,
        "item_id": record.item_id,
        "item_version": record.item_version,
        "item_kind": record.item_kind,
        "plane": record.plane,
        "section_ordinal": record.section_ordinal,
        "char_start": record.start,
        "char_end": record.end,
        "content_hash": record.content_hash,
        "source_title_hash": sha256_text(record.source_title),
        "section_title_hash": sha256_text(record.section_title),
        "legacy_key_lexical": record.legacy_keys[0],
        "legacy_key_semantic": record.legacy_keys[1],
        "corpus_version_first_seen": corpus_version,
        "registered_by": registered_by,
    }


def persist_spans(db: Session, records: Iterable[SpanRecord], *, corpus_version: str, registered_by: str) -> int:
    """Insert the spans not yet stored; returns how many rows were inserted. The caller commits."""
    if registered_by not in REGISTERED_BY:
        raise ValueError(f"Unknown registration source {registered_by!r}")
    rows = [_row(record, corpus_version, registered_by) for record in records if record.plane == "public"]
    if not rows:
        return 0
    dialect = db.get_bind().dialect.name
    module = postgresql if dialect == "postgresql" else sqlite
    inserted = 0
    for start in range(0, len(rows), 500):
        statement = module.insert(CorpusSpan).values(rows[start : start + 500])
        # RETURNING counts the rows actually inserted: psycopg reports rowcount -1 for this statement.
        statement = statement.on_conflict_do_nothing(index_elements=["span_id", "item_version"]).returning(CorpusSpan.id)
        inserted += len(db.execute(statement).all())
    return inserted


def persist_cited_spans(db: Session, citations: Iterable[Citation], store: "CourseStore", *, registered_by: str = "write-through") -> int:
    """Write-through of the resolved spans a response cited (no text). Off when the kill switch is off."""
    if not store.settings.span_registry_write_through:
        return 0
    records = []
    seen: set[str] = set()
    for citation in citations:
        if citation.resolution != "resolved" or not citation.span_id or citation.span_id in seen:
            continue
        record = store.span_registry.get(citation.span_id)
        if record is not None and record.content_hash == citation.content_hash:
            records.append(record)
            seen.add(citation.span_id)
    return persist_spans(db, records, corpus_version=store.corpus_version, registered_by=registered_by)
