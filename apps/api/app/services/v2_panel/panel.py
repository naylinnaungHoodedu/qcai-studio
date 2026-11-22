"""The generator-excluded panel (plan Phase 5 tasks 5.3, 5.5; AC-5-1, AC-5-2; R-20; invariant 4; Phase 5 spec 3.4, 4.2).

Panel = families minus family(g), "enforced by gateway types": Panel.build walks the eligible verifiers in registry
order, skips the generator's family and any family already taken (one adapter per family, R-d), and stops at
MAX_MEMBERS; Panel.__post_init__ refuses a panel holding family(g), two members of one family or more than three
members, so no code path can hold such a panel. Eligibility precedes the panel, so a spare family is drawn only when a
member family is ineligible, and a family's second adapter represents it only when its first is ineligible.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.gateway.registry import AdapterSpec
from app.services.v2_panel.rules import MAX_MEMBERS


class PanelError(ValueError):
    """A panel that would hold the generator's family, a family twice or more than three members (AC-5-1, AC-5-2)."""


@dataclass(frozen=True)
class Panel:                     # constructed only by Panel.build; __post_init__ refuses family(g) (AC-5-1)
    generator_family: str
    members: tuple[AdapterSpec, ...]     # at most MAX_MEMBERS, one per family, registry order

    def __post_init__(self) -> None:
        families = [member.family for member in self.members]
        if self.generator_family in families:
            raise PanelError("a panel never holds the generator's family (AC-5-1)")
        if len(families) != len(set(families)):
            raise PanelError("a panel holds one member per family (AC-5-2)")
        if len(families) > MAX_MEMBERS:
            raise PanelError(f"a panel holds at most {MAX_MEMBERS} members")
        if any("verify" not in member.capabilities for member in self.members):
            raise PanelError("every panel member verifies")

    @classmethod
    def build(cls, eligible: Sequence[AdapterSpec], *, generator_family: str, max_members: int = MAX_MEMBERS) -> "Panel":
        chosen: list[AdapterSpec] = []
        taken: set[str] = set()
        for spec in eligible:
            if len(chosen) >= max_members:
                break
            if "verify" not in spec.capabilities or spec.family == generator_family or spec.family in taken:
                continue
            taken.add(spec.family)
            chosen.append(spec)
        return cls(generator_family=generator_family, members=tuple(chosen))

    def families(self) -> tuple[str, ...]:
        return tuple(member.family for member in self.members)
