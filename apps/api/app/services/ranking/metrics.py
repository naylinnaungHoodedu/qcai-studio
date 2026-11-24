"""The ranking SLIs (plan Phase 9 I "Micro-batch latency (F-3), switch rate (MR-3 is a Table XVII gate ...), fallback rate,
cost."; spec 4.13). Telemetry, not E4 results (invariant 9): MR-3 is never reported as met. Counts, rates, ids, hashes and
seq numbers only. Read-only; shown by python -m app.workers.ranking status and, reviewer-only, under `ranking` in
GET /v3/metrics.
"""

from __future__ import annotations

from datetime import UTC
from decimal import Decimal, localcontext
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.ranking.numeric import CTX, to_str

EVIDENCE_CLASS = "telemetry, not E4 results (invariant 9)"


def _percentile(values: list[Decimal], share: str) -> str | None:
    if not values:
        return None
    ordered = sorted(values)
    with localcontext(CTX):
        index = int((Decimal(share) * (len(ordered) - 1)).to_integral_value())
    return to_str(ordered[index])


def _per_1000(count: int, total: int) -> str:
    with localcontext(CTX):
        return to_str(Decimal(count) * 1000 / Decimal(total)) if total else "0"


def _mean(values: list[int]) -> str:
    with localcontext(CTX):
        return to_str(Decimal(sum(values)) / Decimal(len(values)))


def slis(db: Session, package: Any, *, window_events: int = 20000) -> dict:
    from app.db_models import RankingEvent, RankingState, ResponseLedgerRecord
    from app.services.ranking.replay import stopped
    from app.services.ranking.selection import live_rating
    from app.services.ranking.state import params_of
    from app.services.ranking.vocabulary import STATE_KEY

    rows = list(db.execute(select(RankingEvent.seq, RankingEvent.kind, RankingEvent.payload, RankingEvent.observed_at)
                           .order_by(RankingEvent.seq.desc()).limit(int(window_events))).all())[::-1]
    selects = [json.loads(row.payload) for row in rows if row.kind == "select"]
    batches = [(json.loads(row.payload), row.observed_at) for row in rows if row.kind == "batch"]
    last_seqs = sorted({max(payload["ledger_seqs"]) for payload, _ in batches if payload["ledger_seqs"]})
    created = dict(db.execute(select(ResponseLedgerRecord.seq, ResponseLedgerRecord.created_at).where(ResponseLedgerRecord.seq.in_(last_seqs))).all()) if last_seqs else {}
    latencies = []
    for payload, observed in batches:
        if not payload["ledger_seqs"]:
            continue
        stamp = created.get(max(payload["ledger_seqs"]))
        if stamp is None or observed is None:
            continue
        observed = observed if observed.tzinfo else observed.replace(tzinfo=UTC)
        stamp = stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)
        with localcontext(CTX):
            latencies.append(Decimal(str(round((observed - stamp).total_seconds(), 6))))
    per_context: dict[str, dict] = {}
    for item in selects:
        entry = per_context.setdefault(item["context"], {"requests": 0, "switches": 0, "last": None})
        entry["requests"] += 1
        if item["kind"] == "incumbent":
            if entry["last"] is not None and entry["last"] != item["model"]:
                entry["switches"] += 1
            entry["last"] = item["model"]
    outcomes = [json.loads(row.payload) for row in rows if row.kind == "outcome"]
    cost: dict[str, list[int]] = {}
    for item in outcomes:
        cost.setdefault(item["model"], []).append(int(item["cost_units"]))
    alarms = [json.loads(row.payload) for row in rows if row.kind == "alarm"]
    stored = db.get(RankingState, STATE_KEY)
    state = json.loads(stored.payload) if stored is not None else None
    ratings, charts, skipped, holds = {}, {}, {}, 0
    if state is not None and state.get("parameters") is not None:
        params = params_of(state)
        for key, context in sorted(state["contexts"].items()):
            ratings[key] = {"incumbent": context["incumbent"], **{model: live_rating(state, params, key, model) for model in sorted(context["models"])
                                                                  if model in state["models"]}}
        charts = {f"model:{name}": entry["cusum"]["S"] for name, entry in sorted(state["models"].items())}
        charts.update({f"model-cluster:{key.replace('|', ':')}": entry["S"] for key, entry in sorted(state["cluster_cusum"].items())})
        skipped = dict(state["counts"]["skipped"])
        holds = len(state["holds"])
    requests = len(selects)
    return {
        "micro_batch_latency_s": {"p50": _percentile(latencies, "0.5"), "p95": _percentile(latencies, "0.95"), "batches": len(latencies)},
        "switch_rate_per_1000": {key: _per_1000(entry["switches"], entry["requests"]) for key, entry in sorted(per_context.items())},
        "fallback_rate": _per_1000(sum(1 for item in selects if item["kind"] == "fallback"), requests) if requests else None,
        "exploration_share": _per_1000(sum(1 for item in selects if item.get("explore")), requests) if requests else None,
        "cost_units_mean": {model: _mean(values) for model, values in sorted(cost.items())},
        "latency": None,
        "ratings": ratings,
        "cusum": {"statistics": charts, "alarms": len(alarms), "alarms_per_1000_requests": _per_1000(len(alarms), requests),
                  "sustained": sum(1 for item in alarms if item["sustained"])},
        "skipped": skipped,
        "holds_open": holds,
        "requests": requests,
        "replay": {"stopped": stopped(db)},
        "rates": "fallback_rate and exploration_share are per 1000 requests",
        "evidence_class": EVIDENCE_CLASS,
    }
