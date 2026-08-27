"""Citation existence and resolution metrics."""

from __future__ import annotations

from typing import Iterable, Mapping

from .statistics import wilson_interval


def citation_existence(claims: Iterable[Mapping[str, object]], resolvable_span_ids: set[str]) -> dict[str, float | int]:
    cited_ids = [
        span_id
        for claim in claims
        for span_id in claim.get("cited_span_ids", [])  # type: ignore[union-attr]
        if isinstance(span_id, str)
    ]
    return wilson_interval(sum(span_id in resolvable_span_ids for span_id in cited_ids), len(cited_ids))
