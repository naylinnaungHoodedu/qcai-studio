"""Selection (paper Algorithm 1 lines 1-12; spec 4.5) and the state views it reads.

E is the candidates whose gateway availability is null and whose live rating permits the context's tier (a C or D model
is never eligible; a capped model is at most C). An empty E is the fallback: the decision abstains and names no model
(Algorithm 1 lines 2-3; AC-9-6). Otherwise g is the incumbent when it is in E, else the argmax of R over E (ties by the
smaller adapter id); replacing a set incumbent is a switch, setting the first is not. With a seeded draw u < eps_s a
Thompson draw over the challengers (the non-incumbent models in E or rated C, capped ones included and gateway-unavailable
ones excluded) names h = argmax theta * Qbar - penalties, theta = F^-1_Beta(u_m; alpha, beta): a shadow exploration that is
recorded and never delivered (plan 6.4 "shadow output never delivered").
"""

from __future__ import annotations

from decimal import Decimal, localcontext

from app.services.ranking.numeric import CTX, ZERO, beta_quantile, q, to_str, uniform
from app.services.ranking.score import cost_share, score
from app.services.ranking.state import Params
from app.services.ranking.trust import permits, rating, trust
from app.services.ranking.types import Context, Decision


def ensure_context(state: dict, key: str) -> dict:
    contexts = state["contexts"]
    if key not in contexts:
        contexts[key] = {"incumbent": None, "batch_seq": 0, "pending": [], "pending_since": None, "streaks": {}, "models": {}}
    return contexts[key]


def prior_state(state: dict, params: Params, model: str) -> dict:
    prior = state["models"][model]["prior"]
    return {"alpha": prior["alpha"], "beta": prior["beta"], "T": to_str(trust(prior["alpha"], prior["beta"], params.quantile)),
            "qbar": prior["qbar"], "n": 0, "cost_mean": to_str(state["models"][model]["cost_units"]), "latency_mean": None}


def ensure_models(state: dict, params: Params, key: str) -> dict:
    """The context's state, with a model state (from the model's prior) for every candidate."""
    context = ensure_context(state, key)
    for model in sorted(state["models"]):
        if model not in context["models"]:
            context["models"][model] = prior_state(state, params, model)
    return context


def available(state: dict, model: str) -> bool:
    return state["availability"].get(model) is None


def live_rating(state: dict, params: Params, key: str, model: str) -> str:
    return rating(state["contexts"][key]["models"][model]["T"], params.ratings, capped=bool(state["models"][model]["capped"]))


def a_available(state: dict, params: Params, key: str) -> bool:
    tier = Context.from_key(key).tier
    for model in sorted(state["contexts"][key]["models"]):
        if model in state["models"] and available(state, model) and not state["models"][model]["capped"]:
            if live_rating(state, params, key, model) == "A" and permits("A", tier, a_available=True, permissions=params.tier_permissions,
                                                                         b_tier_1_when_no_a=params.b_tier_1_when_no_a):
                return True
    return False


def eligible(state: dict, params: Params, key: str, model: str, *, a_avail: bool | None = None) -> bool:
    if model not in state["models"] or not available(state, model):
        return False
    tier = Context.from_key(key).tier
    if a_avail is None:
        a_avail = a_available(state, params, key)
    return permits(live_rating(state, params, key, model), tier, a_available=a_avail, permissions=params.tier_permissions,
                   b_tier_1_when_no_a=params.b_tier_1_when_no_a)


def eligible_set(state: dict, params: Params, key: str) -> tuple[str, ...]:
    a_avail = a_available(state, params, key)
    return tuple(model for model in sorted(state["contexts"][key]["models"]) if eligible(state, params, key, model, a_avail=a_avail))


def max_cost(state: dict) -> int:
    return max((int(model["cost_units"]) for model in state["models"].values()), default=0)


def penalty(state: dict, params: Params, model: str) -> Decimal:
    u = cost_share(int(state["models"][model]["cost_units"]), max_cost(state))
    with localcontext(CTX):
        return q(params.lambda_u * u + params.lambda_l * ZERO)


def ranking_score(state: dict, params: Params, key: str, model: str) -> Decimal:
    entry = state["contexts"][key]["models"][model]
    u = cost_share(int(state["models"][model]["cost_units"]), max_cost(state))
    return score(entry["T"], entry["qbar"], u=u, latency_excess=ZERO, lambda_u=params.lambda_u, lambda_l=params.lambda_l)


def argmax(values: dict) -> str | None:
    """The key with the largest value, ties by the smaller key (comparisons only: no arithmetic outside CTX)."""
    if not values:
        return None
    top = max(values.values())
    return min(key for key, value in values.items() if value == top)


def best(state: dict, params: Params, key: str, models) -> str | None:
    return argmax({model: ranking_score(state, params, key, model) for model in models})


def select(state: dict, params: Params, key: str, *, ledger_seq: int) -> tuple[Decision, str]:
    """Algorithm 1 lines 1-12 for one request: (decision, u_explore text). Reads the state only (ensure_models first)."""
    context = state["contexts"][key]
    eligible_models = eligible_set(state, params, key)
    u = uniform(params.seed, "explore", key, str(int(ledger_seq)))
    if not eligible_models:
        return Decision("fallback", None, (), None, "abstain"), to_str(u)
    incumbent = context["incumbent"]
    chosen = incumbent if incumbent in eligible_models else best(state, params, key, eligible_models)
    explore = None
    if u < params.eps_s:
        challengers = [model for model in sorted(context["models"]) if model != chosen and available(state, model)
                       and (model in eligible_models or live_rating(state, params, key, model) == "C")]
        draws = {}
        for model in challengers:
            entry = context["models"][model]
            theta = beta_quantile(uniform(params.seed, "theta", key, str(int(ledger_seq)), model), entry["alpha"], entry["beta"])
            with localcontext(CTX):
                value = q(theta * Decimal(entry["qbar"])) - penalty(state, params, model)
            draws[model] = value
        explore = argmax(draws)
    return Decision("incumbent", chosen, eligible_models, explore, "generate"), to_str(u)
