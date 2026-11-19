"""The read-only span resolver (plan Phase 2 task 2.4: "span to item, version, offsets"; spec 4.16).

It resolves a span id from the current build first, then from the append-only corpus_spans table, so a stored
citation keeps resolving after its span leaves the current corpus. It never resolves a non-public plane and
takes no learner input (invariant 1). A span is servable (its text may be returned) only when it is current,
public-plane, of a bound document whose item the manifest approves; under D-31 none is.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.corpus_governance import CorpusRegistry, get_corpus_registry
from app.db_models import CorpusSpan
from app.schemas import Citation

if TYPE_CHECKING:  # pragma: no cover
    from app.services.content_assembler import CourseStore

SPAN_ID_PATTERN = re.compile(r"^span-[0-9a-f]{64}$")


@dataclass(frozen=True)
class ResolvedSpan:
    span_id: str
    scheme: str
    item_id: str
    item_version: str
    kind: str
    plane: str
    section_ordinal: int
    start: int
    end: int
    content_hash: str
    corpus_version_first_seen: str | None
    current: bool
    registered: bool
    servable: bool
    text: str | None


class SpanResolver:
    def __init__(self, store: "CourseStore") -> None:
        self.store = store
        self._registry: CorpusRegistry | None = None

    @property
    def registry(self) -> CorpusRegistry:
        if self._registry is None:
            self._registry = get_corpus_registry(self.store.settings)
        return self._registry

    def _servable(self, item_id: str, kind: str, plane: str, current: bool, source_filename: str | None) -> bool:
        return bool(
            current
            and plane == "public"
            and kind == "document"
            and source_filename
            and self.registry.is_bound(source_filename)
            and self.registry.is_servable_item(item_id)
        )

    def _rows(self, span_id: str, db: Session | None) -> list[CorpusSpan]:
        if db is None:
            return []
        try:
            return list(db.scalars(select(CorpusSpan).where(CorpusSpan.span_id == span_id).order_by(CorpusSpan.id.asc())).all())
        except SQLAlchemyError:
            return []

    def resolve_current(self, span_id: str) -> ResolvedSpan | None:
        return self.resolve(span_id, None)

    def resolve(self, span_id: str, db: Session | None = None) -> ResolvedSpan | None:
        if not isinstance(span_id, str) or not SPAN_ID_PATTERN.match(span_id):
            return None
        rows = self._rows(span_id, db)
        record = self.store.span_registry.get(span_id)
        if record is not None:
            if record.plane != "public":  # pragma: no cover - SpanRecord.plane is always public
                return None
            first_seen = rows[0].corpus_version_first_seen if rows else self.store.corpus_version
            return ResolvedSpan(
                span_id=record.span_id,
                scheme=record.scheme,
                item_id=record.item_id,
                item_version=record.item_version,
                kind=record.item_kind,
                plane=record.plane,
                section_ordinal=record.section_ordinal,
                start=record.start,
                end=record.end,
                content_hash=record.content_hash,
                corpus_version_first_seen=first_seen,
                current=True,
                registered=bool(rows),
                servable=self._servable(record.item_id, record.item_kind, record.plane, True, record.source_filename),
                text=record.text,
            )
        public_rows = [row for row in rows if row.plane == "public"]
        if not public_rows:
            return None
        latest, earliest = public_rows[-1], public_rows[0]
        return ResolvedSpan(
            span_id=latest.span_id,
            scheme=latest.scheme,
            item_id=latest.item_id,
            item_version=latest.item_version,
            kind=latest.item_kind,
            plane=latest.plane,
            section_ordinal=latest.section_ordinal,
            start=latest.char_start,
            end=latest.char_end,
            content_hash=latest.content_hash,
            corpus_version_first_seen=earliest.corpus_version_first_seen,
            current=False,
            registered=True,
            servable=False,
            text=None,
        )

    def verify(self, citation: Citation, db: Session | None = None) -> ResolvedSpan | None:
        """The span a citation names, if it resolves with an equal content hash (and item, when given)."""
        resolved = self.resolve(citation.span_id or citation.chunk_id, db)
        if resolved is None or resolved.content_hash != citation.content_hash:
            return None
        if citation.item_id and citation.item_id != resolved.item_id:
            return None
        return resolved
