"""Micro-batches, promotion and demotion (plan Phase 9 tasks 2-3, AC-9-3, AC-9-4; paper Algorithm 1 lines 13-21; spec 4.6).

A context's outcomes wait in `pending` until a batch closes: on count (`responses`, 25) or on time (`seconds`, 900, from
the first pending outcome's record time), checked when the next outcome's record time arrives and at the scan's `tick`
(rule record-time-and-scan-tick-v1: no scheduler exists). close() then, in order:
  1. in ledger order, updates each outcome's model: trust (eqs. (5)-(6)), Qbar (eq. (9)), n and the cost EWMA;
  2. recomputes T (eq. (7)) of each touched model and emits `batch`;
  3. promotion: for each challenger h != g with state in the context, the streak rises when h is eligible and
     R(h) - R(g) > delta (strictly), else resets to 0; h is promoted when its streak reaches n_d, its rating is at least
     g's and no open hold covers the context with g or h (AC-9-3); a promotion resets every streak; no incumbent, no
     promotion;
  4. the fast trip: an incumbent whose live rating no longer permits the tier, or that is unavailable, is demoted at once
     (no debounce, whatever the holds) to the argmax of R over E without it, or to none (AC-9-4).
A CUSUM alarm never demotes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import localcontext

from app.services.ranking.numeric import CTX, D, q, to_str
from app.services.ranking.quality import ewma, quality
from app.services.ranking.selection import (
    a_available, available, best, eligible, eligible_set, ensure_models, live_rating, ranking_score)
from app.services.ranking.state import Params
from app.services.ranking.trust import permits, threshold, trust, update_trust
from app.services.ranking.types import Context
from app.services.ranking.vocabulary import RATINGS


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("a ranking time names its timezone")
    return parsed.astimezone(UTC)


def due(context: dict, at: str, seconds: int) -> bool:
    since = context.get("pending_since")
    return bool(context["pending"]) and since is not None and parse_time(at) >= parse_time(since) + timedelta(seconds=int(seconds))


def held(state: dict, key: str, models: tuple[str, ...]) -> bool:
    cluster = Context.from_key(key).cluster
    for hold in state["holds"].values():
        if set(hold["models"]) & set(models) and ("*" in hold["contexts"] or cluster in hold["contexts"]):
            return True
    return False


def close(state: dict, params: Params, key: str, trigger: str, derived: list) -> None:
    context = ensure_models(state, params, key)
    outcomes = sorted(context["pending"], key=lambda item: int(item["ledger_seq"]))
    touched = []
    for outcome in outcomes:
        model = outcome["model"]
        entry = context["models"][model]
        alpha, beta = update_trust(entry["alpha"], entry["beta"], int(outcome["y"]), params.gamma)
        signals = {name: (None if value is None else D(value)) for name, value in outcome["signals"].items()}
        entry["alpha"], entry["beta"] = to_str(alpha), to_str(beta)
        entry["qbar"] = to_str(ewma(entry["qbar"], quality(signals, params.weights), params.eta))
        entry["cost_mean"] = to_str(ewma(entry["cost_mean"], D(int(outcome["cost_units"])), params.eta))
        entry["n"] = int(entry["n"]) + 1
        if model not in touched:
            touched.append(model)
    states = {}
    for model in sorted(touched):
        entry = context["models"][model]
        entry["T"] = to_str(trust(entry["alpha"], entry["beta"], params.quantile))
        states[model] = {"alpha": entry["alpha"], "beta": entry["beta"], "T": entry["T"],
                         "rating": live_rating(state, params, key, model), "qbar": entry["qbar"]}
    context["batch_seq"] = int(context["batch_seq"]) + 1
    derived.append(("batch", {"context": key, "batch_seq": context["batch_seq"], "ledger_seqs": [int(item["ledger_seq"]) for item in outcomes],
                              "trigger": trigger, "states": states}))
    context["pending"], context["pending_since"] = [], None
    _promote(state, params, key, derived)
    fast_trip(state, params, key, derived)


def _promote(state: dict, params: Params, key: str, derived: list) -> None:
    context = state["contexts"][key]
    incumbent = context["incumbent"]
    if incumbent is None:
        context["streaks"] = {}
        return
    a_avail = a_available(state, params, key)
    incumbent_score = ranking_score(state, params, key, incumbent)
    incumbent_rank = RATINGS.index(live_rating(state, params, key, incumbent))
    for challenger in sorted(context["models"]):
        if challenger == incumbent:
            continue
        with localcontext(CTX):
            gap = q(ranking_score(state, params, key, challenger) - incumbent_score)
        if eligible(state, params, key, challenger, a_avail=a_avail) and gap > params.delta:
            context["streaks"][challenger] = int(context["streaks"].get(challenger, 0)) + 1
        else:
            context["streaks"][challenger] = 0
        streak = context["streaks"][challenger]
        if (streak >= params.n_d and RATINGS.index(live_rating(state, params, key, challenger)) <= incumbent_rank
                and not held(state, key, (incumbent, challenger))):
            derived.append(("promote", {"context": key, "from": incumbent, "to": challenger, "streak": streak, "delta_seen": to_str(gap)}))
            context["incumbent"] = challenger
            context["streaks"] = {model: 0 for model in sorted(context["models"]) if model != challenger}
            state["counts"]["switches"] += 1
            return


def fast_trip(state: dict, params: Params, key: str, derived: list) -> None:
    context = ensure_models(state, params, key)
    incumbent = context["incumbent"]
    if incumbent is None or incumbent not in state["models"]:
        return
    tier = Context.from_key(key).tier
    a_avail = a_available(state, params, key)
    grade = live_rating(state, params, key, incumbent)
    allowed = permits(grade, tier, a_available=a_avail, permissions=params.tier_permissions, b_tier_1_when_no_a=params.b_tier_1_when_no_a)
    if allowed and available(state, incumbent):
        return
    replacement = best(state, params, key, [model for model in eligible_set(state, params, key) if model != incumbent])
    limit = threshold(tier, a_available=a_avail, ratings=params.ratings, permissions=params.tier_permissions,
                      b_tier_1_when_no_a=params.b_tier_1_when_no_a)
    derived.append(("demote", {"context": key, "from": incumbent, "to": replacement, "T": context["models"][incumbent]["T"],
                               "threshold": to_str(limit), "rating": grade, "available": available(state, incumbent)}))
    context["incumbent"] = replacement
    context["streaks"] = {}
    state["counts"]["switches"] += 1
