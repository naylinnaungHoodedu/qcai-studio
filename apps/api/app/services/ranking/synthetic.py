"""Synthetic ranking streams for the replay report (plan Phase 9 F, J; spec 8.3). Numbers and identifiers only, never text;
no research item, ULQS item, gold label or licensed text (D-14, D-15, R-25). Engineering measurements on synthetic
streams, not E4 results (invariant 9): Table XVII's MR-1..MR-3 are never asserted as met.

Each scenario is a list of input events (config, model_seen, availability, commission, outcome, tick, ...) built from a
seed with numeric.uniform: two or more model families, record times 30 s apart, a tick every 100 requests. materialise()
folds them with the controller into the full log (inputs with their derived events and a final checkpoint), exactly as
the scan writes it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.services.ranking.controller import apply_in_place
from app.services.ranking.numeric import to_str, uniform
from app.services.ranking.state import canonical, empty_state, sha256_hex, state_sha256

EPOCH = datetime(2026, 11, 23, 0, 0, 0, tzinfo=UTC)
STEP_S = 30
TICK_EVERY = 100
SCENARIOS = ("flapping", "promotion", "outage", "drift", "model_change", "empty_eligible", "rating_only")


def at(index: int) -> str:
    return (EPOCH + timedelta(seconds=STEP_S * index)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def model(adapter_id: str, family: str, *, cost: int = 0, version: str = "2026-11-21") -> dict:
    return {"adapter_id": adapter_id, "family": family, "provider": "fake", "model_id": f"{adapter_id}-model", "model_version": version,
            "cost_units_per_call": cost}


class Stream:
    def __init__(self, block: dict, seed: str) -> None:
        self.block, self.seed, self.inputs, self.index = block, seed, [], 0
        self.add("config", {"package_version": "synthetic", "package_sha256": "0" * 64, "parameters_sha256": sha256_hex(canonical(block)),
                            "parameters": block})

    def add(self, kind: str, payload: dict) -> None:
        self.inputs.append({"kind": kind, "payload": payload})

    def models(self, *refs: dict, commission: tuple[int, int] = (40, 0)) -> None:
        for ref in refs:
            self.add("model_seen", {"model": ref})
        self.add("availability", {"models": {ref["adapter_id"]: None for ref in refs}})
        for ref in refs:
            self.add("commission", {"adapter_id": ref["adapter_id"], "version": ref["model_version"], "clean": commission[0],
                                    "failed": commission[1], "generated": sum(commission), "mean_q": "0.9", "run_sha256": "0" * 64})

    def outcome(self, adapter_id: str, *, p_error: str, cluster: str = "unscoped", tier: int = 2, v: str = "1", k: str = "1",
                h: str = "0") -> None:
        self.index += 1
        error = uniform(self.seed, "y", adapter_id, str(self.index)) < Decimal(p_error)
        self.add("outcome", {"ledger_seq": self.index, "created_at": at(self.index), "model": adapter_id,
                             "context": {"cluster": cluster, "task_type": "quiz_item" if tier == 1 else "explanation", "tier": tier},
                             "y": 0 if error else 1, "signals": {"V": v, "S": None, "K": k, "H": h, "F": None}, "cost_units": 0,
                             "latency_ms": None, "tier_source": "v2"})
        if self.index % TICK_EVERY == 0:
            self.add("tick", {"at": at(self.index)})


def build(block: dict, scenario: str) -> tuple[list[dict], dict]:
    """(input events, the scenario's expectations), deterministic from the scenario name."""
    seed = f"synthetic-{scenario}-v1"
    stream = Stream(block, seed)
    a, b = model("model-a", "family-a"), model("model-b", "family-b")
    meta: dict = {"shift_at": None}
    if scenario == "flapping":
        stream.models(a, b)
        for i in range(2000):
            stream.outcome(("model-a", "model-b")[i % 2], p_error="0.02")
    elif scenario == "promotion":
        stream.models(a, b)
        for i in range(600):
            stream.outcome("model-a", p_error="0.02", v="0.6", k="0.6")
            stream.outcome("model-b", p_error="0.01", v="1", k="1")
    elif scenario == "outage":
        stream.models(a, b)
        for i in range(300):
            stream.outcome(("model-a", "model-b")[i % 2], p_error="0.01", v="1" if i % 2 == 0 else "0.9")
        stream.add("availability", {"models": {"model-a": "down", "model-b": None}})
        for i in range(300):
            stream.outcome("model-b", p_error="0.01", v="0.9")
        stream.add("availability", {"models": {"model-a": None, "model-b": None}})
        for i in range(300):
            stream.outcome(("model-a", "model-b")[i % 2], p_error="0.01", v="1" if i % 2 == 0 else "0.9")
    elif scenario == "drift":
        stream.models(a, b)
        for i in range(1200):
            shifted = i >= 600
            if i == 600:
                meta["shift_at"] = stream.index + 1
            stream.outcome("model-a", p_error="0.15" if shifted else "0.05", cluster="nisq-hybrid-workflows")
            if i % 4 == 0:
                stream.outcome("model-b", p_error="0.05", cluster="industry-use-cases")
    elif scenario == "model_change":
        stream.models(a, b)
        for i in range(200):
            stream.outcome(("model-a", "model-b")[i % 2], p_error="0.01")
        stream.add("model_change", {"adapter_id": "model-b", "from_version": "2026-11-21", "to_version": "2026-11-22", "source": "registry"})
        for i in range(100):
            stream.outcome("model-a", p_error="0.01")
        stream.add("recommission_fail", {"adapter_id": "model-b", "version": "2026-11-22", "clean": 30, "failed": 2, "generated": 32,
                                         "run_sha256": "1" * 64})
        stream.add("recommission_pass", {"adapter_id": "model-b", "version": "2026-11-22", "clean": 40, "failed": 0, "generated": 40,
                                         "run_sha256": "2" * 64})
        for i in range(200):
            stream.outcome(("model-a", "model-b")[i % 2], p_error="0.01")
    elif scenario == "empty_eligible":
        stream.models(a, b)
        for i in range(100):
            stream.outcome(("model-a", "model-b")[i % 2], p_error="0.01")
        stream.add("availability", {"models": {"model-a": "down", "model-b": "kill_switch"}})
        for i in range(100):
            stream.outcome("model-a", p_error="0.01")
    elif scenario == "rating_only":
        stream.models(a, b)
        for i in range(60):
            stream.outcome(("model-a", "model-b")[i % 2], p_error="0.02")
            if i == 55:
                stream.add("feedback", {"ledger_seq": stream.index, "F": "0", "source": "rating"})
    else:
        raise ValueError(f"unknown scenario {scenario!r}")
    return [{"seq": index + 1, **event} for index, event in enumerate(stream.inputs)], meta


def materialise(inputs: list[dict]) -> list[dict]:
    """The full log as the scan writes it: each input, then its derived events, then a final checkpoint (seq renumbered)."""
    state = empty_state()
    log: list[dict] = []
    for event in inputs:
        seq = len(log) + 1
        log.append({"seq": seq, "kind": event["kind"], "payload": canonical(event["payload"]).decode("utf-8")})
        for kind, payload in apply_in_place(state, {"seq": seq, "kind": event["kind"], "payload": event["payload"]}):
            log.append({"seq": len(log) + 1, "kind": kind, "payload": canonical(payload).decode("utf-8")})
    log.append({"seq": len(log) + 1, "kind": "checkpoint", "payload": canonical({"state_sha256": state_sha256(state),
                                                                                 "last_input_seq": state["last_input_seq"]}).decode("utf-8")})
    return log


def measurements(log: list[dict], meta: dict) -> dict:
    """Switches per 1000 drift-free requests (the first incumbent is not a switch), false alarms per 1000 (before a shift),
    the detection delay (requests from the shift to the first later alarm), and the fallback, promotion and demotion counts."""
    import json

    selects = [json.loads(row["payload"]) for row in log if row["kind"] == "select"]
    shift = meta.get("shift_at")
    drift_free = [item for item in selects if shift is None or int(item["ledger_seq"]) < int(shift)]
    previous: dict = {}
    switches = 0
    for item in drift_free:
        if item["kind"] != "incumbent":
            continue
        last = previous.get(item["context"])
        if last is not None and last != item["model"]:
            switches += 1
        previous[item["context"]] = item["model"]
    alarms = [json.loads(row["payload"]) for row in log if row["kind"] == "alarm"]
    outcome_seqs = [json.loads(row["payload"])["ledger_seq"] for row in log if row["kind"] == "outcome"]
    alarm_ledger = []
    last_ledger = 0
    for row in log:
        if row["kind"] == "outcome":
            last_ledger = json.loads(row["payload"])["ledger_seq"]
        elif row["kind"] == "alarm":
            alarm_ledger.append(last_ledger)
    false_alarms = sum(1 for seq in alarm_ledger if shift is None or seq < int(shift))
    delay = None
    if shift is not None:
        later = [seq for seq in alarm_ledger if seq >= int(shift)]
        delay = (later[0] - int(shift) + 1) if later else None
    requests = len(drift_free)

    def per_1000(count: int, total: int) -> str:
        return to_str(Decimal(count) * 1000 / Decimal(total)) if total else "0"

    return {"requests": len(selects), "drift_free_requests": requests, "switches_drift_free": switches,
            "switches_per_1000_drift_free": per_1000(switches, requests),
            "false_alarms": false_alarms, "false_alarms_per_1000": per_1000(false_alarms, len([s for s in outcome_seqs if shift is None or s < int(shift)])),
            "alarms": len(alarms), "detection_delay": delay,
            "fallbacks": sum(1 for item in selects if item["kind"] == "fallback"),
            "promotions": sum(1 for row in log if row["kind"] == "promote"), "demotions": sum(1 for row in log if row["kind"] == "demote")}
