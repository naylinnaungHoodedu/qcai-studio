"""The controller state, its canonical bytes and the parameters it carries (spec 3.3).

The state is a JSON-able dict whose every number is the to_str() text of a Decimal (or an int count). canonical() is
UTF-8 JSON with sorted keys and separators (",", ":"); state_sha256 is the sha256 of those bytes. The state carries the
canonical ranking block in force (set by a `config` input), so the controller reads its parameters from the state and
the replay from the event log, never from the package file. The stop is not part of the state (spec conflict 22).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
import hashlib
import json
from typing import Any

from app.services.ranking.numeric import D
from app.services.ranking.vocabulary import SKIP_REASONS, STATE_SCHEMA

COUNTS = ("requests", "fallbacks", "explorations", "switches", "alarms", "sustained", "late_feedback", "recommission_passes",
          "recommission_fails", "refused_inputs")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def state_sha256(state: dict) -> str:
    return sha256_hex(canonical(state))


def empty_state() -> dict:
    return {
        "schema": STATE_SCHEMA,
        "parameters": None,
        "parameters_sha256": None,
        "last_input_seq": 0,
        "models": {},
        "cluster_cusum": {},
        "contexts": {},
        "holds": {},
        "availability": {},
        "counts": {"skipped": {reason: 0 for reason in SKIP_REASONS}, **{name: 0 for name in COUNTS}},
    }


@dataclass(frozen=True)
class Params:
    """The ranking block's values as Decimals (the package's ranking-params-v1)."""

    gamma: Decimal
    quantile: Decimal
    weights: dict
    eta: Decimal
    initial_qbar: Decimal
    ratings: dict
    tier_permissions: dict
    b_tier_1_when_no_a: bool
    eps_s: Decimal
    seed: str
    first_incumbent_is_switch: bool
    delta: Decimal
    n_d: int
    responses: int
    seconds: int
    p0: Decimal
    p1: Decimal
    h: Decimal
    deflation: Decimal
    uncommissioned_alpha: Decimal
    uncommissioned_beta: Decimal
    lambda_u: Decimal
    lambda_l: Decimal
    clusters: tuple


def params_of(state: dict) -> Params:
    if state.get("parameters") is None:
        raise ValueError("the ranking state has no parameters: the first input of a log is its config event")
    return _params(state["parameters_sha256"], canonical(state["parameters"]).decode("utf-8"))


@lru_cache(maxsize=64)
def _params(_sha: str, text: str) -> Params:
    block = json.loads(text)
    trust, quality, ratings = block["trust"], block["quality"], block["ratings"]
    permissions, selection, promotion = block["tier_permissions"], block["selection"], block["promotion"]
    batch, cusum, recommission, penalties = block["micro_batch"], block["cusum"], block["recommission"], block["penalties"]
    return Params(
        gamma=D(trust["gamma"]), quantile=D(trust["quantile"]),
        weights={name: D(value) for name, value in quality["weights"].items()}, eta=D(quality["eta"]),
        initial_qbar=D(quality["initial_qbar"]), ratings={name: D(value) for name, value in ratings.items()},
        tier_permissions={name: tuple(int(tier) for tier in permissions[name]) for name in ("A", "B", "C", "D")},
        b_tier_1_when_no_a=bool(permissions["B_tier_1_when_no_A"]), eps_s=D(selection["eps_s"]), seed=str(block["seed"]),
        first_incumbent_is_switch=bool(selection["first_incumbent_is_switch"]), delta=D(promotion["delta"]), n_d=int(promotion["n_d"]),
        responses=int(batch["responses"]), seconds=int(batch["seconds"]), p0=D(cusum["p0"]), p1=D(cusum["p1"]), h=D(cusum["h"]),
        deflation=D(recommission["deflation"]), uncommissioned_alpha=D(recommission["uncommissioned_prior"]["alpha"]),
        uncommissioned_beta=D(recommission["uncommissioned_prior"]["beta"]), lambda_u=D(penalties["lambda_u"]),
        lambda_l=D(penalties["lambda_l"]), clusters=tuple(block["contexts"]["clusters"]),
    )
