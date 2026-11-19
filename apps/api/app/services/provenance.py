"""Citation provenance over span identity (plan Phase 2 tasks 2.2-2.4, G; Phase 2 spec 2.3, 3.9, 4.15).

A native citation (schema 2) names a span record: span_id (also chunk_id), item id and version, offsets and the
sha256 of the full span text; corpus_version is a field, never an id input. Phase 1's evidence_provenance, which
hashed the corpus version into the id (E-45), is gone.

Reading a stored citation (AC-2-3 reading, spec 0.3): a v0, v1 or unresolved v2 citation reads back as
legacy_unresolved, provisional and labelled "unverified historical reference", never as resolved; a resolved v2
citation is re-verified against the resolver and downgraded if it no longer resolves. In a governed build a
citation of an item the manifest does not approve is withheld ([R13]).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.corpus_governance import CorpusRegistry
from app.core.structured_logging import FIELDS
from app.schemas import Citation, SearchResult

if TYPE_CHECKING:  # pragma: no cover
    from app.services.span_resolver import SpanResolver

LOGGER = logging.getLogger("qcai.citations")
UNRESOLVED_LABEL = "unverified historical reference"
CITATION_SCHEMA = 2


def provisional_flag(resolution: str, settings: Settings) -> bool:
    """AC-1-13 until lifted: only a resolved citation, and only with CITATION_PROVISIONAL_LIFT_ENABLED (plan G)."""
    return not (bool(settings.citation_provisional_lift_enabled) and resolution == "resolved")


def native_citation(result: SearchResult, *, corpus_version: str, settings: Settings) -> Citation:
    return Citation(
        chunk_id=result.span_id or result.chunk_id,
        span_id=result.span_id or result.chunk_id,
        corpus_version=corpus_version,
        content_hash=result.content_hash,
        source_title=result.source_title,
        source_kind=result.source_kind,
        section_title=result.title,
        excerpt=result.excerpt,
        timestamp_label=None,
        source_filename=result.source_filename,
        provisional=provisional_flag("resolved", settings),
        citation_schema=CITATION_SCHEMA,
        item_id=result.item_id,
        item_version=result.item_version,
        start=result.start,
        end=result.end,
        resolution="resolved",
        migration_status="native",
        near_floor=result.near_floor,
    )


def _unresolved(citation: Citation, reason: str | None, settings: Settings) -> Citation:
    return citation.model_copy(
        update={
            "resolution": "legacy_unresolved",
            "unresolved_reason": reason or citation.unresolved_reason,
            "label": UNRESOLVED_LABEL,
            "provisional": provisional_flag("legacy_unresolved", settings),
        }
    )


def label_stored_citation(
    raw: Any,
    *,
    resolver: "SpanResolver",
    db: Session | None,
    settings: Settings,
    registry: CorpusRegistry,
) -> Citation | None:
    """A stored citation as a learner may see it, or None when it is withheld."""
    if not isinstance(raw, dict):
        return None
    try:
        citation = Citation.model_validate(raw)
    except ValidationError:
        return None
    if settings.enforce_corpus_governance and citation.source_filename and not registry.is_public_asset(citation.source_filename):
        return None
    if citation.citation_schema != CITATION_SCHEMA:
        return _unresolved(citation, citation.unresolved_reason, settings)
    if citation.resolution != "resolved":
        return _unresolved(citation, citation.unresolved_reason, settings)
    if resolver.verify(citation, db) is None:
        LOGGER.warning(
            "A stored citation no longer resolves; shown as unverified",
            extra={FIELDS: {"event": "citations.unresolved_on_read"}},
        )
        return _unresolved(citation, "not_resolvable_on_read", settings)
    return citation.model_copy(update={"provisional": provisional_flag("resolved", settings), "label": None})


def is_withheld_unapproved(raw: Any, *, settings: Settings, registry: CorpusRegistry) -> bool:
    return bool(
        settings.enforce_corpus_governance
        and isinstance(raw, dict)
        and isinstance(raw.get("source_filename"), str)
        and raw["source_filename"]
        and not registry.is_public_asset(raw["source_filename"])
    )
