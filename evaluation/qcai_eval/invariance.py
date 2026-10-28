"""RQ2 factual-claim/cited-span invariance evaluator."""

from __future__ import annotations

from typing import Iterable, Mapping

from .statistics import wilson_interval


def invariance_violations(replays: Mapping[str, Iterable[Mapping[str, object]]]) -> dict[str, object]:
    violating: list[str] = []
    for item_id, item_replays in replays.items():
        normalized = []
        for replay in item_replays:
            claims = frozenset(str(value).strip() for value in replay.get("factual_claims", []) if str(value).strip())
            spans = frozenset(str(value).strip() for value in replay.get("cited_span_ids", []) if str(value).strip())
            normalized.append((claims, spans))
        if len(normalized) != 3:
            raise ValueError(f"{item_id} requires exactly three mastery replays.")
        if len(set(normalized)) != 1:
            violating.append(item_id)
    return {"violating_item_ids": violating, "rate": wilson_interval(len(violating), len(replays))}
