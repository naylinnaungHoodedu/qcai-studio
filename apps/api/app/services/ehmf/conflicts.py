"""Conflict precedence and disclosure (plan Phase 7 D task 3, F "conflict template"; Phase 7 spec 4.2; PD-42).

precedence-v1 ("newer peer-reviewed over older, primary over secondary", E-79) names a winner only when both items
carry complete Content-Owner source metadata (source_year, peer_reviewed, source_role on the corpus manifest item; never
inferred from file names or text) and a rule orders the pair. No item carries the metadata today (DI-107), so every
conflict is metadata_incomplete. The result is recorded only: precedence never changes which claims are delivered or
withheld, in any mode (spec conflict 24; applying a winner is DI-111). Every detected conflict is disclosed with both
spans when the V1.7 policy is disclose (template conflict-disclosure-v2: the conflict kinds and the public item ids, no
span text), and a disclosed conflict's Type D weighs D_disclosed (0, plan Phase 7 A "D 0.6 (0 when disclosed)"); an
undisclosed one stays a V1.7 conflict_withheld and weighs D. Conflicts with a source outside the public corpus are not
detected: only cited spans are compared (plan M residual).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import functools
import json
from pathlib import Path
from typing import Any, Literal

SOURCE_METADATA_FIELDS = ("source_year", "peer_reviewed", "source_role")


@dataclass(frozen=True)
class SourceMetadata:
    source_year: int | None
    peer_reviewed: bool | None
    source_role: Literal["primary", "secondary"] | None

    def complete(self) -> bool:
        return self.source_year is not None and self.peer_reviewed is not None and self.source_role is not None


@dataclass(frozen=True)
class Precedence:
    winner_item_id: str | None
    basis: str


UNKNOWN = SourceMetadata(None, None, None)


def metadata_for(item_id: str, manifest_items: Mapping[str, Mapping[str, Any]]) -> SourceMetadata:
    """The item's source metadata from its manifest entry: each field None unless the Content Owner supplied it."""
    raw = manifest_items.get(item_id) or {}
    year, reviewed, role = raw.get("source_year"), raw.get("peer_reviewed"), raw.get("source_role")
    return SourceMetadata(
        source_year=year if isinstance(year, int) and not isinstance(year, bool) else None,
        peer_reviewed=reviewed if isinstance(reviewed, bool) else None,
        source_role=role if role in ("primary", "secondary") else None,
    )


@functools.lru_cache(maxsize=4)
def _manifest_items_cached(path: str, mtime_ns: int) -> Mapping[str, Mapping[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {item["id"]: item for item in payload.get("items", []) if isinstance(item, dict) and isinstance(item.get("id"), str)}


def manifest_items(path: Path | str | None) -> Mapping[str, Mapping[str, Any]]:
    """The manifest's items by id (cached per path and modification time); {} without a manifest."""
    if path is None:
        return {}
    try:
        mtime = Path(path).stat().st_mtime_ns
    except OSError:
        return {}
    return _manifest_items_cached(str(path), mtime)


def precedence(a: SourceMetadata, b: SourceMetadata, *, item_a: str, item_b: str) -> Precedence:
    """precedence-v1 over two items' metadata (spec 4.2)."""
    if not a.complete() or not b.complete():
        return Precedence(None, "metadata_incomplete")
    r1 = None
    if a.peer_reviewed and b.peer_reviewed and a.source_year != b.source_year:
        r1 = item_a if a.source_year > b.source_year else item_b
    r2 = None
    if a.source_role != b.source_role:
        r2 = item_a if a.source_role == "primary" else item_b
    if r1 is None and r2 is None:
        return Precedence(None, "no_rule_applies")
    if r1 is not None and r2 is not None:
        return Precedence(r1, "both_rules") if r1 == r2 else Precedence(None, "rules_disagree")
    return Precedence(r1, "newer_peer_reviewed") if r1 is not None else Precedence(r2, "primary_over_secondary")


def ehmf_conflicts(disclosure: Any, *, manifest: Mapping[str, Mapping[str, Any]], weights: Mapping[str, str]) -> tuple[Any, ...]:
    """One EhmfConflict per conflict of the V1.7 disclosure block, in order."""
    from app.services.tutor_pipeline.contracts import EhmfConflict

    if disclosure is None:
        return ()
    disclosed = disclosure.policy == "disclose"
    conflicts = []
    for pair in disclosure.conflicts:
        item_a, item_b = pair.item_ids
        result = precedence(metadata_for(item_a, manifest), metadata_for(item_b, manifest), item_a=item_a, item_b=item_b)
        conflicts.append(EhmfConflict(kind=pair.kind, span_ids=pair.span_ids, item_ids=pair.item_ids, claim_ids=pair.claim_ids,
                                      winner_item_id=result.winner_item_id, basis=result.basis, disclosed=disclosed,
                                      d_weight=weights["D_disclosed"] if disclosed else weights["D"]))
    return tuple(conflicts)


def disclosure_text(conflicts: tuple[Any, ...], *, template_id: str, template_text: str, template_sha256: str) -> Any:
    """The filled conflict-disclosure-v2 template for the disclosed conflicts, or None when none is disclosed."""
    from app.services.tutor_pipeline.contracts import EhmfDisclosure

    shown = [conflict for conflict in conflicts if conflict.disclosed]
    if not shown:
        return None
    kinds = ", ".join(sorted({conflict.kind for conflict in shown}))
    items = " and ".join(sorted({item for conflict in shown for item in conflict.item_ids}))
    basis = ", ".join(sorted({conflict.basis for conflict in shown}))
    text = template_text.format(kinds=kinds, items=items, basis=basis)
    return EhmfDisclosure(template=template_id, template_sha256=template_sha256, text=text)
