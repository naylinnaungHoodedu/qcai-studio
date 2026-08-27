from __future__ import annotations

from typing import Iterable, Mapping

from .statistics import wilson_interval


def fabrication_rate(claims: Iterable[Mapping[str, object]]) -> dict[str, float | int]:
    records = list(claims)
    return wilson_interval(sum(record.get("category") == "fabricated" for record in records), len(records))
