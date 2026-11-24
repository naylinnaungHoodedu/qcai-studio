"""Verified-trust ranking and drift control (plan Phase 9; docs/architecture/phase9-implementation-spec.md).

Modules: vocabulary (ids and kinds), numeric (exact Decimal arithmetic, the Beta quantile, seeded draws), types, state
(the canonical state and the parameters it carries), contexts (topic cluster, task type, tier), models (the candidates),
signals (completed verdicts into outcomes or skips), trust, quality and score (eqs. (5)-(10)), selection (Algorithm 1),
batch (micro-batches, promotion, demotion), cusum (eq. (11)), recommission (model change and commissioning), controller
(the pure transition), scan (the only writer of the ranking tables), replay (AC-9-8 and the stop), generators and hook
(development shadow generation), metrics, synthetic (the replay report's streams) and package_check.

The ranking is shadow-only under the freeze (D-05): static assignment (the package's generator_default) keeps
generating every record a learner path writes, and nothing here changes what a learner receives. No module decides a
rank with a language model (plan H); the pure modules import no database, gateway adapter, HTTP client or clock, and no
ranking module imports a learner-record, progress, intelligence, microlearning, auth or route module.

mode() is the ranking mode:
  off     no ranking block in the package, the start-up check found a problem, or RANKING is off (the default outside
          development): no scan, no hook, no /ready stop read; every event row, alarm and X5 window written stays
  shadow  the ranking scan (python -m app.workers.ranking scan) consumes ledger records (development default)
RANKING=on (live routing) is refused at settings construction while D-28 is open (plan Phase 9 G; hold H11).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config import Settings
    from app.core.config_package import ConfigPackage

# Set by the start-up check (app.main._check_ranking_package) when the package's ranking block disagrees with the code.
RANKING_UNAVAILABLE_REASON: str | None = None


class RankingOff(RuntimeError):
    """The ranking mode is off."""


class RankingStopped(RuntimeError):
    """The ranking log is stopped (a replay or state mismatch) until clear-stop."""


class RankingUncommissioned(RuntimeError):
    """A static candidate has no commission event: the scan consumes nothing (spec conflict 26)."""


def mode(settings: "Settings", package: "ConfigPackage") -> Literal["off", "shadow"]:
    if getattr(package, "ranking", None) is None or RANKING_UNAVAILABLE_REASON is not None:
        return "off"
    if (getattr(settings, "ranking", None) or "off") == "off":
        return "off"
    return "shadow"
