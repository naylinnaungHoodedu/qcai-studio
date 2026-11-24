"""The gateway hook (plan Phase 9 E "gateway hook (Phase 5)"; spec 4.12): a read-only selection API for development shadow
generation. It never changes which generator serves a learner: static assignment generates every learner-path record.

select() reads the stored controller state (ranking_states "_state") and gives Algorithm 1's decision for a context and a
ledger seq, without writing anything; it refuses unless the ranking mode is shadow. The ledger seq is the shadow record's
own, so the scan's later `select` for that record draws the same exploration.

after_shadow() is called by tutor_pipeline.shadow.run_shadow after a successful shadow run, in its own try, only when
RANKING_SHADOW_GENERATION is true (development only) and the mode is shadow: a fallback decision runs nothing; otherwise
it runs at most one more two-pass shadow run, for the exploration challenger if one was drawn, else for the incumbent when
it is not the record's generator, with the same learner-free input, a new shadow- id, delivery "shadow", the same
shadowed_response_id and the shadow budget that remains. The V2 panel excludes the clone's family (Panel.build with the
generator's family), and a candidate whose family does not resolve is refused. A fault is logged
(ranking.shadow_generation_failed) and counted, never marks the original shadow run failed and never reaches a learner.
"""

from __future__ import annotations

import copy
import json
import logging
import time
from typing import Any
from uuid import uuid4

from app.core.structured_logging import FIELDS

LOGGER = logging.getLogger("qcai.ranking")
SHADOW_GENERATION = {"runs": 0, "skipped": 0, "failed": 0}


def context_of(entry: Any, *, package: Any, store: Any = None) -> Any:
    from app.services.ranking.contexts import cluster_for, span_modules, task_type_for, tier_for
    from app.services.ranking.types import Context

    if store is None:
        from app.services.store import get_course_store

        store = get_course_store()
    tier, _source = tier_for(entry, package)
    return Context(cluster_for(entry, span_modules(store), store.corpus_version), task_type_for(tier, package), tier)


def select(context: Any, *, ledger_seq: int, settings: Any, package: Any, session_factory: Any = None) -> Any:
    """Algorithm 1's decision from the stored state (None when no state is stored yet). Read-only."""
    from app.services import ranking
    from app.services.ranking.selection import ensure_models
    from app.services.ranking.selection import select as choose
    from app.services.ranking.state import params_of
    from app.services.ranking.vocabulary import STATE_KEY

    if ranking.mode(settings, package) != "shadow":
        raise ranking.RankingOff("RANKING is not shadow")
    if session_factory is None:
        from app.core.db import SessionLocal

        session_factory = SessionLocal
    from app.db_models import RankingState

    with session_factory() as db:
        row = db.get(RankingState, STATE_KEY)
        if row is None:
            return None
        state = json.loads(row.payload)
    if state.get("parameters") is None:
        return None
    state = copy.deepcopy(state)
    params = params_of(state)
    key = context.key()
    ensure_models(state, params, key)
    decision, _u = choose(state, params, key, ledger_seq=int(ledger_seq))
    return decision


def after_shadow(job: Any, result: Any, *, pipeline_factory: Any, settings: Any, session_factory: Any, started: float, store: Any = None) -> None:
    from app.services import ranking
    from app.services.ranking.generators import generator_for
    from app.services.ranking.models import candidates
    from app.services.tutor_pipeline.pipeline import PipelineInput
    from app.services.tutor_pipeline.resolve import resolve_thread
    from app.services.tutor_pipeline.shadow import shadow_budget_ms

    if not settings.ranking_shadow_generation:
        return
    pipeline = pipeline_factory()
    package = pipeline.package
    if ranking.mode(settings, package) != "shadow" or result.appended is None:
        SHADOW_GENERATION["skipped"] += 1
        return
    decision = select(context_of(result.entry, package=package, store=store), ledger_seq=int(result.appended.seq), settings=settings,
                      package=package, session_factory=session_factory)
    if decision is None or decision.kind == "fallback":
        SHADOW_GENERATION["skipped"] += 1
        return
    generator_id = result.entry.versions.generator_id
    chosen = decision.explore or (decision.model if decision.model != generator_id else None)
    known = {model.adapter_id: model for model in candidates(package, settings)}
    if chosen is None or chosen not in known:
        SHADOW_GENERATION["skipped"] += 1
        return
    remaining = shadow_budget_ms(settings, package) - int((time.perf_counter() - started) * 1000)
    if remaining <= 0:
        SHADOW_GENERATION["skipped"] += 1
        return
    pipeline.generator = generator_for(known[chosen], package=package, settings=settings)
    with session_factory() as db:
        resolved = resolve_thread(db, job.thread_id, job.user_message_id, package=package)
    pipeline.run(PipelineInput(resolved=resolved, lesson_slug=job.lesson_slug, presentation=job.presentation, response_id=f"shadow-{uuid4()}",
                               delivery="shadow", shadowed_response_id=job.shadowed_response_id, legacy_decision=job.legacy_decision),
                 budget_ms=remaining)
    SHADOW_GENERATION["runs"] += 1
    LOGGER.info("Ranking shadow generation", extra={FIELDS: {"event": "ranking.shadow_generation", "model": chosen,
                                                               "explore": decision.explore is not None}})


def guarded_after_shadow(job: Any, result: Any, **kwargs: Any) -> None:
    """after_shadow in its own try: a fault is counted and logged and never reaches the original shadow run or a learner."""
    try:
        after_shadow(job, result, **kwargs)
    except Exception as exc:  # noqa: BLE001 - shadow generation never changes the shadow run or the learner's response
        SHADOW_GENERATION["failed"] += 1
        LOGGER.warning("Ranking shadow generation failed", extra={FIELDS: {"event": "ranking.shadow_generation_failed", "error": type(exc).__name__}})
