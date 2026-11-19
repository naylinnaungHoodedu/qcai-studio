"""The two-pass pipeline (plan Phase 3 A: "resolve, retrieve, compose, render, check"; spec 4.10).

    resolved question -> retrieval request -> evidence bundle -> evidential envelope -> claim plan   (evidential)
    -> bind (SpanResolver, bundle, sentence-verbatim, D-19 quotable) -> lock (claim_set_hash)
    -> render (PresentationPlan; at most 1 + max_regenerations attempts) -> subset check          (pedagogical)
    -> ledger entry (and append)

Learner state reaches neither pass: the evidential pass takes the resolved text, the lesson scope and the corpus
version; the renderer takes a PresentationPlan from a request hint or the package default (AC-3-1, invariant 1).
Phase 3 has no delivered two-pass path (spec R-a): run() refuses any delivery but "shadow" while
TWO_PASS_DELIVERY_IMPLEMENTED is False, and nothing it returns reaches a learner (AC-3-6).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
import logging
import time
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.core.db import SessionLocal
from app.core.structured_logging import FIELDS
from app.services.claim_gate import check_subset
from app.services.contained_answers import ABSTENTION
from app.services.ledger import SCHEMA_REVISION, AppendedRecord, append_ledger_entry
from app.services.span_resolver import SpanResolver
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline.bind import bind
from app.services.tutor_pipeline.contracts import (
    ClaimLedgerEntry,
    ClaimPlan,
    EvidenceBundle,
    EvidentialEnvelope,
    LedgerEntry,
    LockedClaimSet,
    PipelineCounts,
    PresentationPlan,
    PresentationRecord,
    Provenance,
    RenderedResponse,
    ResolvedQuestion,
    ResolvedQuestionRef,
    RetrievalRecord,
    RetrievalRequest,
    VersionStamps,
    sha256_hex,
)
from app.services.tutor_pipeline.evidential import ClaimGenerator, build_envelope, get_generator
from app.services.tutor_pipeline.lock import lock
from app.services.tutor_pipeline.metrics import LEDGER_METRICS
from app.services.tutor_pipeline.render import Renderer, TemplateRenderer
from app.services.tutor_pipeline.retrieve import build_request, retrieve

LOGGER = logging.getLogger("qcai.tutor")
PIPELINE_VERSION = "two-pass-v1"


class PipelineUnavailable(RuntimeError):
    """The configuration package has no tutor_pipeline block (a v1 package)."""


class DeliveryNotImplemented(RuntimeError):
    """Two-pass delivery is Phase 4's, behind V1 (plan 13.6; spec R-a, conflict 31)."""


class LedgerWriteFailed(RuntimeError):
    """The pipeline's ledger append failed (a plan L stop condition); the cause is chained."""


@dataclass(frozen=True)
class PipelineInput:
    resolved: ResolvedQuestion
    lesson_slug: str | None
    presentation: PresentationPlan
    response_id: str
    delivery: Literal["shadow"]
    shadowed_response_id: str


@dataclass(frozen=True)
class PipelineResult:
    response_id: str
    decision: Literal["answer", "abstain"]
    abstention_reason: str | None
    request: RetrievalRequest
    bundle: EvidenceBundle
    envelope: EvidentialEnvelope | None
    plan: ClaimPlan | None
    locked: LockedClaimSet
    rendered: RenderedResponse | None
    render_attempts: int
    entry: LedgerEntry
    appended: AppendedRecord | None
    # No learner-facing text: the rendered response is internal and never returned to a learner in Phase 3.


def render_checked(
    renderer: Renderer,
    locked: LockedClaimSet,
    presentation: PresentationPlan,
    *,
    max_regenerations: int,
    over: Callable[[], bool] | None = None,
) -> tuple[RenderedResponse | None, int, str | None]:
    """Plan 3.7: render, subset-check; on an unmapped factual sentence re-render, at most max_regenerations times,
    then abstain. Returns (the passing rendering or None, attempts made, abstention reason or None)."""
    for attempt in range(1, 2 + max_regenerations):
        try:
            candidate = renderer.render(locked, presentation, attempt=attempt)
            passed = check_subset(candidate, locked).passed
        except contracts.LockedClaimSetTampered:
            raise
        except Exception:  # noqa: BLE001 - a renderer fault is a failed attempt
            passed = False
        if passed:
            return candidate, attempt, None
        if attempt < 1 + max_regenerations and over is not None and over():
            return None, attempt, "budget_exceeded"
    return None, 1 + max_regenerations, "subset_check_failed"


class TwoPassPipeline:
    def __init__(
        self,
        engine: Any,
        settings: Settings,
        *,
        generator: ClaimGenerator | None = None,
        renderer: Renderer | None = None,
        session_factory: Callable[[], Session] = SessionLocal,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.package = get_config_package(settings)
        if self.package.tutor_pipeline is None:
            raise PipelineUnavailable("the configuration package has no tutor_pipeline block (package v2 is required)")
        self.params = self.package.tutor_pipeline
        self.engine = engine
        self.settings = settings
        self.store = engine.store
        self.resolver = SpanResolver(self.store)
        self.registry = self.resolver.registry
        self.manifest_sha256 = self.registry.manifest_sha256
        self.generator: ClaimGenerator = generator if generator is not None else get_generator(self.package)
        self.renderer: Renderer = renderer if renderer is not None else TemplateRenderer(self.package)
        self.session_factory = session_factory
        self.clock = clock

    def _over(self, started: float, budget_ms: int | None, step: str) -> bool:
        if budget_ms is None:
            return False
        elapsed_ms = (self.clock() - started) * 1000
        if elapsed_ms <= budget_ms:
            return False
        LOGGER.warning(
            "Two-pass shadow exceeded its budget",
            extra={FIELDS: {"event": "tutor.two_pass.budget_exceeded", "step": step, "elapsed_ms": round(elapsed_ms, 3), "budget_ms": budget_ms}},
        )
        return True

    def _propose(self, envelope: EvidentialEnvelope) -> ClaimPlan:
        raw = self.generator.propose(envelope)
        plan = ClaimPlan.model_validate(raw.model_dump(mode="json") if isinstance(raw, BaseModel) else raw)
        if plan.generator != self.generator.ref:
            raise ValueError("the claim plan names another generator")
        return plan

    def run(self, item: PipelineInput, *, budget_ms: int | None = None, record: bool = True) -> PipelineResult:
        if item.delivery != "shadow" and not contracts.TWO_PASS_DELIVERY_IMPLEMENTED:
            raise DeliveryNotImplemented("two-pass output is delivered only after the Phase 4 exit (AC-3-6); run it in shadow")
        params = self.params
        started = self.clock()
        request = build_request(item.resolved, lesson_slug=item.lesson_slug, corpus_version=self.store.corpus_version)
        bundle = retrieve(self.engine, request, top_k=params.top_k, registry=self.registry)
        envelope: EvidentialEnvelope | None = None
        plan: ClaimPlan | None = None
        drafts: tuple = ()
        dropped: Counter = Counter()
        proposed = 0
        reason: str | None = None
        if bundle.sufficiency.decision == "abstain":
            reason = bundle.sufficiency.reason
        elif self._over(started, budget_ms, "retrieve"):
            reason = "budget_exceeded"
        if reason is None:
            envelope = build_envelope(request, bundle, store=self.store, params=params)
            if envelope is None:
                reason = "no_quotable_evidence"
        if reason is None and envelope is not None:
            try:
                plan = self._propose(envelope)
            except Exception:  # noqa: BLE001 - any generator fault or malformed plan abstains (R-11)
                reason = "claim_plan_invalid"
            else:
                proposed = len(plan.claims)
                if not plan.claims:
                    reason = "no_claims"
                elif self._over(started, budget_ms, "generate"):
                    reason = "budget_exceeded"
                    # Bind never runs: the claims are counted as skipped, never as binding failures, so a slow
                    # generator does not trip the plan L bound-claim stop (bound_claim_ratio_terms).
                    dropped[contracts.BUDGET_SKIPPED] = proposed
        if reason is None and plan is not None:
            bound = bind(plan, bundle, resolver=self.resolver, store=self.store, registry=self.registry, params=params)
            drafts, dropped, proposed = bound.bound, bound.dropped, bound.proposed
            if not drafts:
                reason = "no_bound_claims"
            elif self._over(started, budget_ms, "bind"):
                reason = "budget_exceeded"
        locked = lock(
            drafts,
            bundle=bundle,
            generator=self.generator.ref if plan is not None else None,
            evidential_prompt_hash=self.generator.ref.prompt_hash if plan is not None else None,
            pedagogical_prompt_hash=params.pedagogical_prompt_hash,
            resolver=item.resolved.resolver,
            package=self.package,
        )
        rendered: RenderedResponse | None = None
        attempts = 0
        if reason is None:
            rendered, attempts, reason = render_checked(
                self.renderer,
                locked,
                item.presentation,
                max_regenerations=params.max_regenerations,
                over=lambda: self._over(started, budget_ms, "render"),
            )
        decision: Literal["answer", "abstain"] = "answer" if rendered is not None and reason is None else "abstain"
        entry = self._entry(item, decision, reason, bundle, locked, rendered, attempts, proposed, dropped)
        appended: AppendedRecord | None = None
        if record:
            LEDGER_METRICS.attempt(item.delivery)
            try:
                appended = append_ledger_entry(entry, session_factory=self.session_factory, budget_ms=self.settings.tutor_ledger_append_budget_ms)
            except Exception as exc:  # noqa: BLE001 - counted by the shadow runner (plan L stop)
                raise LedgerWriteFailed("the two-pass ledger record could not be appended") from exc
            LEDGER_METRICS.appended(item.delivery, duplicate=appended.duplicate)
        return PipelineResult(
            response_id=item.response_id,
            decision=decision,
            abstention_reason=reason if decision == "abstain" else None,
            request=request,
            bundle=bundle,
            envelope=envelope,
            plan=plan,
            locked=locked,
            rendered=rendered,
            render_attempts=attempts,
            entry=entry,
            appended=appended,
        )

    def _entry(self, item, decision, reason, bundle, locked, rendered, attempts, proposed, dropped) -> LedgerEntry:
        params = self.params
        package = self.package
        provenance = Provenance(
            generator_model_id=self.generator.ref.model_id,
            evidential_prompt_hash=self.generator.ref.prompt_hash,
            pedagogical_prompt_hash=params.pedagogical_prompt_hash,
            corpus_version=bundle.corpus_version,
            threshold_set_version=bundle.sufficiency.threshold_version,
        )
        claims = tuple(
            ClaimLedgerEntry(claim_id=claim.claim_id, response_id=item.response_id, text=claim.text, span_ids=claim.span_ids, provenance=provenance)
            for claim in locked.claims
        )
        sufficiency = bundle.sufficiency
        return LedgerEntry(
            response_id=item.response_id,
            delivery=item.delivery,
            shadowed_response_id=item.shadowed_response_id,
            pipeline=PIPELINE_VERSION,
            decision=decision,
            abstention_reason=reason if decision == "abstain" else None,
            resolved_question=ResolvedQuestionRef(resolver=item.resolved.resolver, source_turn_ids=item.resolved.source_turn_ids),
            retrieval=RetrievalRecord(
                corpus_version=bundle.corpus_version,
                index_version=bundle.index_version,
                gate=sufficiency.gate,
                threshold_version=sufficiency.threshold_version,
                floor=sufficiency.floor,
                margin=sufficiency.margin,
                mode=bundle.retrieval_mode,
                evidence_scope="retrieved",
                sufficiency=sufficiency,
                evidence=bundle.spans,
            ),
            claim_set_hash=locked.claim_set_hash,
            claims=claims,
            span_ids=locked.span_ids,
            presentation=(
                PresentationRecord(
                    plan_id=item.presentation.plan_id,
                    source=item.presentation.source,
                    renderer_id=self.renderer.renderer_id,
                    attempts=attempts,
                    subset_check="passed" if rendered is not None else "failed",
                )
                if attempts
                else None
            ),
            rendered_text_sha256=sha256_hex(rendered.text if decision == "answer" and rendered is not None else ABSTENTION),
            provenance=provenance,
            versions=VersionStamps(
                pipeline_version=PIPELINE_VERSION,
                code_sha=self.settings.git_sha,
                schema_revision_expected=SCHEMA_REVISION,
                config_package_version=package.package_version,
                config_package_sha256=package.sha256,
                manifest_sha256=self.manifest_sha256,
                span_scheme=package.span_scheme,
                policy_version=self.settings.grounding_policy_version,
                resolver_id=item.resolved.resolver.model_id,
                generator_id=self.generator.ref.generator_id,
                renderer_id=self.renderer.renderer_id,
            ),
            counts=PipelineCounts(
                proposed_claims=proposed,
                bound_claims=len(locked.claims),
                dropped=dict(sorted(dropped.items())),
                render_attempts=attempts,
            ),
        )
