"""The ranking controller: one pure transition per input event (spec 4.9).

apply(state, event) -> (state', derived) is total over INPUT_KINDS and reads only the event and the state (which carries
the parameters and the candidates): no database, clock, environment, gateway, LLM or randomness beyond numeric.uniform.
`derived` lists the (kind, payload) of every derived event the input caused, in order; the scan appends them right after
the input, and the replay recomputes and compares them byte for byte (AC-9-8). Control rows (checkpoint, stop,
clear_stop) are never passed here.

  outcome        time-close the context's open batch if due, select (Algorithm 1), the CUSUM updates and alarms, then
                 pending, then the count close
  skipped        its counter only (AC-9-1)
  tick           time-close every due batch, in context-key order
  availability   update, then the fast trip on every incumbent
  model_seen     add the candidate with the uncommissioned prior
  model_change   deflation, cap, chart resets and a hold (4.8)
  commission     the commissioning prior (refused for a model with outcomes)
  recommission_* lift the cap (pass) or count (fail)
  feedback       set F on a pending outcome, else count late_feedback (never trust, the CUSUM or the selection; AC-9-2)
  hold_release   remove the hold
  config         replace the parameters and their sha256
"""

from __future__ import annotations

import copy
from decimal import localcontext

from app.services.ranking import batch as batches
from app.services.ranking import cusum
from app.services.ranking import recommission as rc
from app.services.ranking.numeric import CTX, D, ZERO, to_str
from app.services.ranking.selection import ensure_context, ensure_models, select
from app.services.ranking.state import canonical, params_of, sha256_hex
from app.services.ranking.types import Context
from app.services.ranking.vocabulary import INPUT_KINDS, SKIP_REASONS


class RankingInputError(ValueError):
    """An input event the controller cannot apply (a malformed log): the replay reports it as a mismatch."""


def apply(state: dict, event: dict) -> tuple[dict, list[tuple[str, dict]]]:
    """The pure transition: a new state and the derived events; `state` is not modified."""
    new_state = copy.deepcopy(state)
    derived = apply_in_place(new_state, event)
    return new_state, derived


def apply_in_place(state: dict, event: dict) -> list[tuple[str, dict]]:
    kind, payload, seq = event["kind"], event["payload"], int(event["seq"])
    if kind not in INPUT_KINDS:
        raise RankingInputError(f"{kind!r} is not an input kind")
    derived: list[tuple[str, dict]] = []
    if kind == "config":
        if sha256_hex(canonical(payload["parameters"])) != payload["parameters_sha256"]:
            raise RankingInputError("a config event's parameters do not match their sha256")
        state["parameters"] = copy.deepcopy(payload["parameters"])
        state["parameters_sha256"] = payload["parameters_sha256"]
        state["last_input_seq"] = seq
        return derived
    params = params_of(state)
    if kind == "model_seen":
        _model_seen(state, params, payload["model"])
    elif kind == "availability":
        state["availability"].update({name: reason for name, reason in sorted(payload["models"].items())})
        for key in sorted(state["contexts"]):
            if state["contexts"][key]["incumbent"] is not None:
                batches.fast_trip(state, params, key, derived)
    elif kind == "model_change":
        rc.model_change(state, params, payload, seq, derived)
    elif kind == "commission":
        rc.commission(state, params, payload)
    elif kind in ("recommission_pass", "recommission_fail"):
        rc.recommission(state, payload, passed=kind == "recommission_pass")
    elif kind == "skipped":
        if payload["reason"] not in SKIP_REASONS:
            raise RankingInputError(f"unknown skip reason {payload['reason']!r}")
        state["counts"]["skipped"][payload["reason"]] += 1
    elif kind == "feedback":
        _feedback(state, payload)
    elif kind == "hold_release":
        state["holds"].pop(payload["hold_id"], None)
    elif kind == "tick":
        for key in sorted(state["contexts"]):
            if batches.due(state["contexts"][key], payload["at"], params.seconds):
                batches.close(state, params, key, "time", derived)
    elif kind == "outcome":
        _outcome(state, params, payload, seq, derived)
    state["last_input_seq"] = seq
    return derived


def _model_seen(state: dict, params, model: dict) -> None:
    adapter_id = model["adapter_id"]
    if adapter_id in state["models"]:
        return
    state["models"][adapter_id] = {
        "version": model["model_version"], "family": model["family"], "provider": model["provider"], "model_id": model["model_id"],
        "cost_units": int(model["cost_units_per_call"]), "commissioned": False, "capped": False,
        "prior": {"alpha": to_str(params.uncommissioned_alpha), "beta": to_str(params.uncommissioned_beta), "qbar": to_str(params.initial_qbar)},
        "cusum": {"S": "0", "n": 0},
    }
    state["availability"].setdefault(adapter_id, None)


def _feedback(state: dict, payload: dict) -> None:
    for key in sorted(state["contexts"]):
        for item in state["contexts"][key]["pending"]:
            if int(item["ledger_seq"]) == int(payload["ledger_seq"]):
                item["signals"]["F"] = to_str(D(payload["F"]))
                return
    state["counts"]["late_feedback"] += 1


def _outcome(state: dict, params, payload: dict, seq: int, derived: list) -> None:
    context_value = Context(**payload["context"])
    key = context_value.key()
    model = payload["model"]
    if model not in state["models"]:
        raise RankingInputError(f"an outcome names an unknown model {model!r}")
    context = ensure_context(state, key)
    if batches.due(context, payload["created_at"], params.seconds):
        batches.close(state, params, key, "time", derived)
    context = ensure_models(state, params, key)
    # Algorithm 1 for the request this record answers (spec conflict 1: evaluated when the scan reads it).
    decision, u_explore = select(state, params, key, ledger_seq=int(payload["ledger_seq"]))
    state["counts"]["requests"] += 1
    if decision.kind == "fallback":
        state["counts"]["fallbacks"] += 1
    else:
        previous = context["incumbent"]
        if previous != decision.model:
            if previous is not None or params.first_incumbent_is_switch:
                state["counts"]["switches"] += 1
            context["incumbent"] = decision.model
        if decision.explore is not None:
            state["counts"]["explorations"] += 1
    derived.append(("select", {"ledger_seq": int(payload["ledger_seq"]), "context": key, "eligible": list(decision.eligible), "kind": decision.kind,
                               "model": decision.model, "explore": decision.explore, "u_explore": u_explore}))
    _cusum(state, params, payload, seq, derived, model=model, cluster=context_value.cluster)
    item = copy.deepcopy(payload)
    item["signals"] = {name: (None if value is None else to_str(D(value))) for name, value in sorted(item["signals"].items())}
    context["pending"].append(item)
    if context["pending_since"] is None:
        context["pending_since"] = payload["created_at"]
    if len(context["pending"]) >= params.responses:
        batches.close(state, params, key, "count", derived)


def _cusum(state: dict, params, payload: dict, seq: int, derived: list, *, model: str, cluster: str) -> None:
    a, b = cusum.constants(params.p0, params.p1)
    error = 1 - int(payload["y"])
    charts = [(cusum.model_stream(model), state["models"][model]["cusum"], ["*"])]
    cluster_key = f"{model}|{cluster}"
    chart = state["cluster_cusum"].setdefault(cluster_key, {"S": "0", "n": 0})
    charts.append((cusum.cluster_stream(model, cluster), chart, [cluster]))
    for stream, chart, contexts in charts:
        statistic = cusum.update(chart["S"], error, a, b)
        chart["n"] = int(chart["n"]) + 1
        chart["S"] = to_str(statistic)
        with localcontext(CTX):
            fired = statistic > params.h
        if not fired:
            continue
        open_hold = next((identifier for identifier, hold in sorted(state["holds"].items()) if hold["stream"] == stream), None)
        sustained = open_hold is not None
        identifier = open_hold or rc.hold_id("alarm", stream, seq)
        derived.append(("alarm", {"stream": stream, "scope": "model" if contexts == ["*"] else "model_cluster", "statistic": to_str(statistic),
                                  "p0": to_str(params.p0), "p1": to_str(params.p1), "h": to_str(params.h), "observations": int(chart["n"]),
                                  "hold_id": identifier, "sustained": sustained, "created_at": payload["created_at"]}))
        state["counts"]["alarms"] += 1
        if sustained:
            state["counts"]["sustained"] += 1
        else:
            state["holds"][identifier] = {"stream": stream, "cause": "alarm", "contexts": contexts, "models": [model]}
            derived.append(("hold", {"hold_id": identifier, "cause": "alarm", "contexts": contexts, "models": [model]}))
        chart["S"], chart["n"] = to_str(ZERO), 0
