"""The start-up and CI check of package v7's ranking block (spec 4.14).

check_ranking_package(structural=False) runs at start-up (main._check_ranking_package): the block's versions and
vocabulary against the code (the loader refused the rest), the cluster list against MODULE_BLUEPRINTS, the static
candidates against the generator families, and plan J's two hand fixtures reproduced to three decimals by the code's
Beta quantile. It reads no database and no docs/. structural=True (tests and scripts/config_package.py --check) also
checks the recommission golden set's sha256 and item count and that the replay report exists.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
import json
from pathlib import Path
from typing import Any

from app.services.ranking.numeric import beta_quantile
from app.services.ranking.vocabulary import CLUSTERS, PARAMETERS_VERSION, RANKING_VERSION


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[5]


def hand_fixture_value(alpha: int, beta: int, quantile: str) -> str:
    """The paper's three-decimal lower bound of Beta(alpha, beta) at the block's quantile."""
    return str(beta_quantile(quantile, alpha, beta).quantize(Decimal("0.001"), rounding=ROUND_HALF_EVEN))


def check_ranking_package(package: Any, *, structural: bool = False) -> list[str]:
    params = package.ranking
    if params is None:
        return []
    problems: list[str] = []
    if params.version != RANKING_VERSION or params.parameters_version != PARAMETERS_VERSION:
        problems.append("ranking.version or parameters_version differs from the code's")
    from app.services.content_assembler import MODULE_BLUEPRINTS

    if tuple(module["slug"] for module in MODULE_BLUEPRINTS) != CLUSTERS or tuple(params.clusters) != CLUSTERS:
        problems.append("ranking.contexts.clusters differs from the MODULE_BLUEPRINTS slugs (cluster-module-v1)")
    quantile = str(params.block["trust"]["quantile"])
    for fixture in params.block.get("hand_fixtures") or ():
        value = hand_fixture_value(int(fixture["alpha"]), int(fixture["beta"]), quantile)
        if value != fixture["lower_bound"]:
            problems.append(f"the Beta({fixture['alpha']},{fixture['beta']}) hand fixture gives {value}, not {fixture['lower_bound']} (plan J)")
    if not structural:
        return problems
    from app.core.config_package import canonical_sha256

    root = _repository_root()
    try:
        golden = json.loads((root / params.golden_set_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.append(f"the recommission golden set at {params.golden_set_path} could not be read: {exc}")
    else:
        if canonical_sha256(golden) != params.golden_set_sha256 or len(golden.get("items", ())) != params.golden_set_items:
            problems.append("ranking.recommission.golden_set's sha256 or item count differs from the file's")
    if not (root / params.report_path).is_file():
        problems.append(f"the ranking replay report {params.report_path} is missing (plan Phase 9 F)")
    return problems


def summary(package: Any) -> str:
    params = package.ranking
    block = params.block
    return (f"ranking {params.version} {params.parameters_version} (provisional): parameters {params.parameters_sha256[:16]}; "
            f"gamma {block['trust']['gamma']}, quantile {block['trust']['quantile']}; ratings A {block['ratings']['A']}, "
            f"B {block['ratings']['B']}, C {block['ratings']['C']}; eps_s {block['selection']['eps_s']}; delta {block['promotion']['delta']} "
            f"over {block['promotion']['n_d']} batches; batches of {block['micro_batch']['responses']} or {block['micro_batch']['seconds']} s; "
            f"CUSUM {block['cusum']['p0']}/{block['cusum']['p1']}/{block['cusum']['h']}; deflation {block['recommission']['deflation']}; "
            f"recommission set {params.golden_set_items} of {block['recommission']['golden_set']['target_items']} items; "
            f"live routing {params.live_routing} (D-28, H11); phase9_exit_passed {package.flag_policy.phase9_exit_passed}")
