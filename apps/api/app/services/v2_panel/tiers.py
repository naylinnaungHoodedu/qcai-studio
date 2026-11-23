"""Claim tiers (plan Phase 5 task 5.6; rule context-tier-v1, provisional, PD-25; Phase 5 spec 4.8, conflict 8).

Tier 1 when the turn is an assessment context (V1.6's assessment_items over the resolved text is non-empty), else the
package's default tier (2, the default tutor answer). Tier 3 is the paper's opt-in expert mode, which does not exist
(v2.tiers.expert_mode is null), so no shipped claim is tier 3. Learner state never sets a tier (invariant 1); the
paper's novice-learner tier waits for the Phase 8 learner model (DI-82). Every claim of a response has the same tier.
critical_for reads package v5's v3.critical_claims registry for the environment (empty outside development while D-25 is
open; synthetic in development, PD-33), and package v4's v2.correction.critical_registry for a package without a v3
block; X1 is Phase 6's trigger (app.services.v3.triggers).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config_package import ConfigPackage


def tier_for(items: Any, package: "ConfigPackage", *, expert: bool = False) -> int:
    v2 = package.v2
    if items:
        return v2.assessment_tier
    if expert and v2.expert_mode:
        return 3
    return v2.default_tier


def critical_for(claim_id: str, package: "ConfigPackage", *, environment: str) -> bool:
    if package.v3 is not None:
        return claim_id in set(package.v3.critical_registry_for(environment.lower()))
    return claim_id in set(package.v2.critical_registry)
