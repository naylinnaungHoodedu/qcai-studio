"""Retrieval sufficiency metrics for lexical and semantic arms."""

from __future__ import annotations

from typing import Mapping, Sequence

from .statistics import wilson_interval


def retrieval_sufficiency(expected: Mapping[str, set[str]], returned: Mapping[str, Sequence[str]]) -> dict[str, float | int]:
    scored_ids = [item_id for item_id, spans in expected.items() if spans]
    successful = sum(bool(expected[item_id] & set(returned.get(item_id, []))) for item_id in scored_ids)
    return wilson_interval(successful, len(scored_ids))
