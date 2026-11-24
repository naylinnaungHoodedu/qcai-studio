"""Model change, commissioning and re-commissioning (plan Phase 9 task 4, AC-9-5, AC-12-4; paper Sec. VII-B; spec 4.8).

A version change of a candidate multiplies its alpha and beta by the deflation (0.3) in every context and in its prior,
caps its rating at C (shadow and verification only), resets both its charts and opens a hold. Only a recorded
`recommission_pass` (a shadow golden regression in which every query gave a completed verdict and none failed its first
pass: rule every-item-generated-no-failed-first-pass-v1) lifts the cap; a failing one changes a counter only, and elapsed time never lifts it. `commission` sets the prior from a
commissioning run (alpha0 = 1 + clean, beta0 = 1 + failed, Qbar0 = its mean Q) and is refused for a model with outcomes.

regression_run is the worker's shadow regression (impure: it runs the two-pass pipeline over the recommission queries with
the development fakes; record=False, so it writes nothing) and recommission_queries reads the recommission set (golden-set-v1,
found in the checkout or in the API image, which copies it; its sha256 and item count must be the package's); every
other function is a pure state transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import localcontext
import hashlib
from pathlib import Path
from typing import Any

from app.services.ranking.cusum import cluster_stream, model_stream
from app.services.ranking.numeric import CTX, D, q, to_str
from app.services.ranking.state import Params
from app.services.ranking.trust import trust


def hold_id(cause: str, stream: str, seq: int) -> str:
    return "h-" + hashlib.sha256(f"{cause}|{stream}|{int(seq)}".encode("utf-8")).hexdigest()[:16]


def has_outcomes(state: dict, model: str) -> bool:
    return any(int(context["models"].get(model, {}).get("n", 0)) > 0 or any(item["model"] == model for item in context["pending"])
               for context in state["contexts"].values())


def model_change(state: dict, params: Params, payload: dict, seq: int, derived: list) -> None:
    model = payload["adapter_id"]
    entry = state["models"][model]
    with localcontext(CTX):
        factor = params.deflation
        entry["prior"]["alpha"] = to_str(q(D(entry["prior"]["alpha"]) * factor))
        entry["prior"]["beta"] = to_str(q(D(entry["prior"]["beta"]) * factor))
        for context in state["contexts"].values():
            item = context["models"].get(model)
            if item is None:
                continue
            item["alpha"] = to_str(q(D(item["alpha"]) * factor))
            item["beta"] = to_str(q(D(item["beta"]) * factor))
            item["T"] = to_str(trust(item["alpha"], item["beta"], params.quantile))
    entry["version"] = payload["to_version"]
    entry["capped"] = True
    entry["cusum"] = {"S": "0", "n": 0}
    for stream in [name for name in state["cluster_cusum"] if name.startswith(f"{model}|")]:
        state["cluster_cusum"][stream] = {"S": "0", "n": 0}
    identifier = hold_id("model_change", model_stream(model), seq)
    state["holds"][identifier] = {"stream": model_stream(model), "cause": "model_change", "contexts": ["*"], "models": [model]}
    derived.append(("hold", {"hold_id": identifier, "cause": "model_change", "contexts": ["*"], "models": [model]}))


def refusal(state: dict, kind: str, payload: dict) -> str | None:
    """Why an operator input would be refused (None when it applies): unknown_model, has_outcomes (a commission only) or
    version_mismatch. The controller counts a refused input in `refused_inputs`; scan.append_inputs raises
    RankingInputRefused before it appends one, so the worker exits 2 and writes nothing."""
    entry = state["models"].get(payload["adapter_id"])
    if entry is None:
        return "unknown_model"
    if kind == "commission" and has_outcomes(state, payload["adapter_id"]):
        return "has_outcomes"
    if payload["version"] != entry["version"]:
        return "version_mismatch"
    return None


def commission(state: dict, params: Params, payload: dict) -> bool:
    model = payload["adapter_id"]
    entry = state["models"].get(model)
    if refusal(state, "commission", payload) is not None:
        state["counts"]["refused_inputs"] += 1
        return False
    entry["prior"] = {"alpha": to_str(1 + int(payload["clean"])), "beta": to_str(1 + int(payload["failed"])), "qbar": to_str(D(payload["mean_q"]))}
    entry["commissioned"] = True
    for context in state["contexts"].values():
        context["models"].pop(model, None)
    return True


def recommission(state: dict, payload: dict, *, passed: bool) -> None:
    entry = state["models"].get(payload["adapter_id"])
    if refusal(state, "recommission_pass" if passed else "recommission_fail", payload) is not None:
        state["counts"]["refused_inputs"] += 1
        return
    if passed:
        entry["capped"] = False
        state["counts"]["recommission_passes"] += 1
    else:
        state["counts"]["recommission_fails"] += 1


# ------------------------------------------------------------------------------------------------- the regression


@dataclass(frozen=True)
class RunResult:
    adapter_id: str
    version: str
    clean: int
    failed: int
    generated: int
    skipped: int
    mean_q: str
    run_sha256: str
    passed: bool


def regression_run(model: Any, *, package: Any, queries: list[str] | None = None) -> RunResult:
    """The shadow golden regression (spec 4.8): every recommission query through the two-pass pipeline with generator_for(model)
    and the development fakes (V1 enforce, the gateway in shadow, EHMF shadow, V3 and ranking off); outcome_of on each record.
    It writes nothing (record=False) and reads no database: its own gateway (an in-memory daily budget), its own evidential
    cache, and a clear V3 stop (the regression has no V3 queue, so the tier-1 hold an unreadable queue causes does not apply)."""
    from app.core.config import Settings
    from app.core.config_package import canonical_sha256
    from app.services.ranking.contexts import span_modules
    from app.services.ranking.generators import generator_for
    from app.services.ranking.models import candidates
    from app.services.ranking.quality import quality
    from app.services.ranking.signals import outcome_of
    from app.services.ranking.types import Outcome
    from app.services.retrieval_engine import RetrievalEngine
    from app.services.store import get_course_store
    from app.services.tutor_pipeline.pipeline import TwoPassPipeline

    settings = Settings(environment="development", v1_pipeline="enforce", model_gateway="shadow", ehmf="shadow", v3_queue="off", ranking="off")
    params = package.ranking
    if queries is None:
        queries = recommission_queries(package)
    store = get_course_store()
    from app.gateway.budget import DailyBudget
    from app.gateway.gateway import ModelGateway
    from app.services.v2_panel.cache import ProcessEvidentialCache

    gateway = ModelGateway(budget=DailyBudget(int(package.gateway.daily_units.get("development", 0))))
    pipeline = TwoPassPipeline(RetrievalEngine(store, settings), settings, generator=generator_for(model, package=package, settings=settings),
                               gateway=gateway, cache=ProcessEvidentialCache(), v3_stop=lambda: False)
    modules = span_modules(store)
    known = {item.adapter_id: item for item in candidates(package, settings)}
    known[model.adapter_id] = model
    outcomes = []
    clean = failed = generated = skipped = 0
    total_q = D(0)
    for index, query in enumerate(queries):
        result = _run_query(pipeline, query, index)
        verdict = outcome_of(result.entry, ledger_seq=index + 1, created_at="2026-11-23T00:00:00Z", candidates=known, modules=modules,
                             corpus_version=store.corpus_version, package=package)
        if isinstance(verdict, Outcome):
            generated += 1
            clean += verdict.y
            failed += 1 - verdict.y
            signals = {name: getattr(verdict.signals, name) for name in ("V", "S", "K", "H", "F")}
            value = quality(signals, {name: D(weight) for name, weight in params.block["quality"]["weights"].items()})
            with localcontext(CTX):
                total_q += value
            outcomes.append({"index": index, "y": verdict.y, "q": to_str(value)})
        else:
            skipped += 1
            outcomes.append({"index": index, "skip": verdict.reason})
    with localcontext(CTX):
        mean_q = to_str(q(total_q / generated)) if generated else to_str(params.block["quality"]["initial_qbar"])
    run_sha256 = canonical_sha256({"model": model.as_dict(), "package_sha256": package.sha256, "golden_set_sha256": params.golden_set_sha256,
                                   "outcomes": outcomes})
    # Rule every-item-generated-no-failed-first-pass-v1: the set passes only when every query gave a completed verdict
    # (no skip of any reason) and no first pass failed.
    passed = bool(queries) and failed == 0 and skipped == 0 and generated == len(queries)
    return RunResult(model.adapter_id, model.model_version, clean, failed, generated, skipped, mean_q, run_sha256, passed)


class RecommissionSetError(RuntimeError):
    """The recommission set cannot be read, or its sha256 or item count differs from the package's (fail closed)."""

    def __init__(self, problem: str) -> None:
        super().__init__(f"the recommission set is unavailable: {problem}")
        self.problem = problem


def recommission_set_path(relative: str, *, start: Path | None = None) -> Path:
    """The first ancestor directory of this module holding `relative` (the package's golden_set path): the repository root
    in a checkout, /app in the API image (apps/api/Dockerfile copies the file to /app/<relative>). Missing: RecommissionSetError."""
    for directory in (start or Path(__file__)).resolve().parents:
        candidate = directory / relative
        if candidate.is_file():
            return candidate
    raise RecommissionSetError("missing")


def recommission_queries(package: Any, *, start: Path | None = None) -> list[str]:
    import json

    from app.core.config_package import canonical_sha256

    params = package.ranking
    path = recommission_set_path(params.golden_set_path, start=start)
    try:
        golden = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecommissionSetError("unreadable") from exc
    if canonical_sha256(golden) != params.golden_set_sha256 or len(golden.get("items", ())) != params.golden_set_items:
        raise RecommissionSetError("sha256_or_count_mismatch")
    return [item["query"] for item in golden["items"]]


def _run_query(pipeline: Any, query: str, index: int) -> Any:
    from uuid import UUID

    from app.services.tutor_pipeline.contracts import PresentationPlan
    from app.services.tutor_pipeline.pipeline import PipelineInput
    from app.services.tutor_pipeline.resolve import LearnerTurn, resolve_turns

    resolved = resolve_turns([], LearnerTurn(f"message-{UUID(int=index + 1)}", query), package=pipeline.package)
    return pipeline.run(PipelineInput(resolved=resolved, lesson_slug=None, presentation=PresentationPlan(plan_id="concise", source="request"),
                                      response_id=f"shadow-{UUID(int=index + 1)}", delivery="shadow",
                                      shadowed_response_id=f"turn-{UUID(int=index + 1)}", legacy_decision="answer"), record=False)


__all__ = ["RecommissionSetError", "RunResult", "cluster_stream", "commission", "has_outcomes", "hold_id", "model_change", "recommission", "recommission_queries", "recommission_set_path", "refusal", "regression_run"]
