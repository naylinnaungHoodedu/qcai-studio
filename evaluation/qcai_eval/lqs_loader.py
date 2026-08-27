"""LQS parsing and freeze-gate validation (RevB §§8.1-8.2)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


STRATA = {
    "answerable_single_source",
    "answerable_multi_hop",
    "near_miss_outside_corpus",
    "out_of_scope_adversarial",
    "unanswerable_by_construction",
    "multi_turn",
    "progress_conditioned",
}


@dataclass(frozen=True)
class LQSItem:
    item_id: str
    stratum: str
    question: str
    expected_answerable: bool
    expected_span_ids: tuple[str, ...]
    mastery_levels: tuple[str, ...] = ()


def load_lqs(path: Path) -> list[LQSItem]:
    items: list[LQSItem] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            raw = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc.msg}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"LQS item at line {line_number} must be an object.")
        item = LQSItem(
            item_id=str(raw.get("id", "")),
            stratum=str(raw.get("stratum", "")),
            question=str(raw.get("question", "")).strip(),
            expected_answerable=raw.get("expected_answerable"),
            expected_span_ids=tuple(raw.get("expected_span_ids", [])),
            mastery_levels=tuple(raw.get("mastery_levels", [])),
        )
        items.append(item)
    return items


def validate_lqs(items: list[LQSItem], *, enforce_proposal_range: bool = True) -> None:
    ids = [item.item_id for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError("LQS item identifiers must be unique.")
    if enforce_proposal_range and not 120 <= len(items) <= 200:
        raise ValueError(f"RevB requires 120-200 LQS items; found {len(items)}.")
    present_strata: set[str] = set()
    for item in items:
        if not item.item_id or not item.question:
            raise ValueError("LQS items require a non-empty id and question.")
        if item.stratum not in STRATA:
            raise ValueError(f"Unsupported LQS stratum: {item.stratum!r}")
        if not isinstance(item.expected_answerable, bool):
            raise ValueError(f"{item.item_id}: expected_answerable must be boolean.")
        if len(set(item.expected_span_ids)) != len(item.expected_span_ids) or not all(item.expected_span_ids):
            raise ValueError(f"{item.item_id}: expected span IDs must be unique non-empty strings.")
        if item.expected_answerable and not item.expected_span_ids:
            raise ValueError(f"{item.item_id}: answerable items require expected span IDs.")
        if item.stratum == "progress_conditioned" and item.mastery_levels != ("low", "medium", "high"):
            raise ValueError(f"{item.item_id}: progress-conditioned items require low/medium/high replays.")
        present_strata.add(item.stratum)
    if enforce_proposal_range and present_strata != STRATA:
        raise ValueError(f"LQS must cover every RevB stratum; missing {sorted(STRATA - present_strata)}.")
