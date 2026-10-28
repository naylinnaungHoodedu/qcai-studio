from __future__ import annotations

from typing import Iterable, Mapping

from .statistics import wilson_interval


def correct_abstention(outcomes: Iterable[Mapping[str, object]]) -> dict[str, float | int]:
    """Score abstention for answerability labels; answerable items must not abstain."""
    records = list(outcomes)
    correct = sum(
        bool(record.get("abstained")) == (not bool(record.get("expected_answerable")))
        for record in records
    )
    return wilson_interval(correct, len(records))


def abstention_by_turn_depth(outcomes: Iterable[Mapping[str, object]]) -> dict[int, dict[str, float | int]]:
    grouped: dict[int, list[Mapping[str, object]]] = {}
    for outcome in outcomes:
        depth = outcome.get("turn_depth", 1)
        if not isinstance(depth, int) or depth < 1:
            raise ValueError("turn_depth must be a positive integer.")
        grouped.setdefault(depth, []).append(outcome)
    return {depth: correct_abstention(group) for depth, group in sorted(grouped.items())}
