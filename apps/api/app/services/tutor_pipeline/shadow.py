"""two_pass_tutor in shadow (plan Phase 3 G; AC-3-6; Phase 3 spec 4.11 and conflict 2).

"two_pass_tutor MUST run shadow-only until the Phase 4 exit; zero outputs reach learners." Three independent locks:
1. Settings refuse TWO_PASS_TUTOR=on while configuration package flag_policy.phase4_exit_passed is false.
2. effective_mode downgrades "on" to "shadow" while TWO_PASS_DELIVERY_IMPLEMENTED is False (no V1 module exists).
3. TwoPassPipeline.run refuses any delivery but "shadow", and LedgerEntry refuses "delivered".
The shadow runs as a background task after the learner's response is sent: it writes a shadow ledger record and
returns nothing to the learner. A shadow failure (an exception, the budget, a ledger write) is caught, counted and
logged; it never changes the learner's response.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
import time
from typing import TYPE_CHECKING, Literal

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.config_package import ConfigPackage
from app.core.db import SessionLocal
from app.core.structured_logging import FIELDS
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline.contracts import PresentationPlan
from app.services.tutor_pipeline.metrics import TWO_PASS_METRICS

if TYPE_CHECKING:  # pragma: no cover
    from app.services.tutor_pipeline.pipeline import TwoPassPipeline

LOGGER = logging.getLogger("qcai.tutor")
# Set (or cleared) by the start-up package check (main._check_corpus_before_any_table); a reason keeps the
# effective mode off and /ready reports tutor_pipeline.available false.
PIPELINE_UNAVAILABLE_REASON: str | None = None
_ON_DOWNGRADE_LOGGED = False


def delivery_implemented() -> bool:
    return bool(contracts.TWO_PASS_DELIVERY_IMPLEMENTED)


@dataclass(frozen=True)
class ShadowJob:
    """Identifiers only: the shadow reads the learner's turns from the database itself (resolve_thread)."""

    shadow_response_id: str
    shadowed_response_id: str
    thread_id: str
    user_message_id: str
    lesson_slug: str | None
    presentation: PresentationPlan


def effective_mode(settings: Settings, package: ConfigPackage) -> Literal["off", "shadow"]:
    global _ON_DOWNGRADE_LOGGED
    if package.tutor_pipeline is None or PIPELINE_UNAVAILABLE_REASON is not None:
        return "off"
    if not settings.tutor_ledger_enabled or settings.two_pass_tutor in (None, "off"):
        return "off"
    if settings.two_pass_tutor == "on" and not delivery_implemented():
        if not _ON_DOWNGRADE_LOGGED:
            _ON_DOWNGRADE_LOGGED = True
            LOGGER.warning(
                "TWO_PASS_TUTOR=on runs in shadow until two-pass delivery exists (Phase 4)",
                extra={FIELDS: {"event": "tutor.two_pass.on_downgraded"}},
            )
        return "shadow"
    return "shadow"


def run_shadow(
    job: ShadowJob,
    *,
    pipeline_factory: Callable[[], "TwoPassPipeline"],
    settings: Settings,
    session_factory: Callable[[], Session] = SessionLocal,
) -> None:
    """Run the two-pass pipeline in shadow for one delivered turn. Never raises."""
    from app.services.ledger import record_ledger_failure
    from app.services.tutor_pipeline.pipeline import LedgerWriteFailed, PipelineInput
    from app.services.tutor_pipeline.resolve import resolve_thread

    started = time.perf_counter()
    step = "pipeline"
    try:
        pipeline = pipeline_factory()
        step = "resolve"
        with session_factory() as db:
            resolved = resolve_thread(db, job.thread_id, job.user_message_id, package=pipeline.package)
        step = "pipeline"
        result = pipeline.run(
            PipelineInput(
                resolved=resolved,
                lesson_slug=job.lesson_slug,
                presentation=job.presentation,
                response_id=job.shadow_response_id,
                delivery="shadow",
                shadowed_response_id=job.shadowed_response_id,
            ),
            budget_ms=settings.two_pass_shadow_budget_ms,
        )
    except LedgerWriteFailed as exc:
        TWO_PASS_METRICS.failed("ledger")
        record_ledger_failure("shadow", "append", exc.__cause__ or exc)
        LOGGER.error("Two-pass shadow run failed", extra={FIELDS: {"event": "tutor.two_pass.shadow_failed", "step": "ledger",
                                                                     "error": type(exc.__cause__ or exc).__name__}})
        return
    except Exception as exc:  # noqa: BLE001 - a shadow fault never reaches the learner
        TWO_PASS_METRICS.failed(step)
        LOGGER.error("Two-pass shadow run failed", extra={FIELDS: {"event": "tutor.two_pass.shadow_failed", "step": step,
                                                                     "error": type(exc).__name__}})
        return
    entry = result.entry
    TWO_PASS_METRICS.completed(decision=result.decision, reason=result.abstention_reason, counts=entry.counts, attempts=result.render_attempts)
    LOGGER.info(
        "Two-pass shadow run",
        extra={
            FIELDS: {
                "event": "tutor.two_pass.shadow",
                "decision": result.decision,
                "reason": result.abstention_reason,
                "proposed": entry.counts.proposed_claims,
                "bound": entry.counts.bound_claims,
                "dropped": dict(entry.counts.dropped),
                "attempts": result.render_attempts,
                "plan_id": job.presentation.plan_id,
                "gate": entry.retrieval.gate,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "seq": result.appended.seq if result.appended else None,
            }
        },
    )
