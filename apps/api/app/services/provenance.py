"""Content-addressed evidence provenance for citation-bearing Tutor responses."""

from __future__ import annotations

import hashlib
import json

from app.core.config import Settings
from app.core.corpus_governance import get_corpus_registry


def evidence_provenance(
    *,
    settings: Settings,
    chunk_id: str,
    source_title: str,
    source_kind: str,
    excerpt: str,
    timestamp_label: str | None,
) -> tuple[str, str, str]:
    """Return immutable content-addressed span ID, content hash, and corpus version."""
    normalized_excerpt = " ".join(excerpt.split())
    content_hash = hashlib.sha256(normalized_excerpt.encode("utf-8")).hexdigest()
    corpus_version = get_corpus_registry(settings).corpus_version
    identity = json.dumps(
        {
            "corpus_version": corpus_version,
            "chunk_id": chunk_id,
            "source_title": source_title,
            "source_kind": source_kind,
            "timestamp_label": timestamp_label,
            "content_hash": content_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"span-{hashlib.sha256(identity.encode('utf-8')).hexdigest()}", content_hash, corpus_version
