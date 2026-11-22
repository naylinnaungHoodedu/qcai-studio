"""The two-pass pipeline (plan Phase 3 A: "resolve, retrieve, compose, render, check"; spec 4.10).

    resolved question -> retrieval request -> evidence bundle -> evidential envelope -> claim plan   (evidential)
    -> bind (SpanResolver, bundle, sentence-verbatim, D-19 quotable) -> lock (claim_set_hash)
    -> render (PresentationPlan; at most 1 + max_regenerations attempts) -> subset check          (pedagogical)
    -> ledger entry (and append)

Learner state reaches neither pass: the evidential pass takes the resolved text, the lesson scope and the corpus
version; the renderer takes a PresentationPlan from a request hint or the package default (AC-3-1, invariant 1).
There is no delivered two-pass path (Phase 3 spec R-a; Phase 4 spec R-a): run() refuses any delivery but "shadow"
while TWO_PASS_DELIVERY_IMPLEMENTED is False, and nothing it returns reaches a learner (AC-3-6).

V1 (Phase 4 spec 4.13) runs inside the shadow, by v1_checks.mode:
  off      the Phase 3 composition exactly; the record is a ledger-entry-v1
  shadow   the Phase 3 composition decides the record; the V1 track runs alongside on the same bundle and envelope
           (reusing the generator's first proposal) and its VerificationRecord, with the comparison against the
           Phase 3 decision and the legacy decision, is the record's verification (ledger-entry-v2)
  enforce  retrieve, bundle and envelope as in Phase 3, then the V1 track decides the record: its claims, rendering,
           counts and decision (ledger-entry-v2); decision "answer" means a rendering passed V1, and whether any of it
           may be delivered is verification.final

V2 (Phase 5 spec 4.16) runs inside the V1 track, by v2_panel.mode (off whenever the shadow itself is off, outside
development by default):
  off      every path is Phase 4's exactly: no gateway is built and no cache is read
  shadow   the V2 track votes on each V1-passed candidate beside the Phase 4 decision, which decides every final; the
           record is a ledger-entry-v3 whose verification carries the V2 verdicts and the would-summary
  on       (V1 enforce only) V2 decides each V1-passed claim; the record's decision is abstain exactly when its
           verification's final is, and its rendering is the final rendering (ledger-entry-v3)
An explicit v2_hook (the Phase 4 seam) takes precedence: with it the pipeline builds no V2 track and its V2 mode is off.
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
from app.services.claim_gate import check_subset, displayed_span_ids
from app.services.contained_answers import ABSTENTION
from app.services.ledger import SCHEMA_REVISION, AppendedRecord, append_ledger_entry, budget_stamp, ledger_budget_ms
from app.services.span_resolver import SpanResolver
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline.bind import bind
from app.services.tutor_pipeline.contracts import (
    ClaimLedgerEntry,
    ClaimLedgerEntryV2,
    ClaimLedgerEntryV3,
    ClaimPlan,
    EvidenceBundle,
    EvidentialEnvelope,
    LedgerEntry,
    LedgerEntryV2,
    LedgerEntryV3,
    LockedClaimSet,
    PipelineCounts,
    PipelineCountsV2,
    PresentationPlan,
    PresentationRecord,
    Provenance,
    ProvenanceV2,
    ProvenanceV3,
    RenderedResponse,
    ResolvedQuestion,
    ResolvedQuestionRef,
    RetrievalRecord,
    RetrievalRequest,
    VerificationRecordV2,
    VersionStamps,
    sha256_hex,
)
from app.services.tutor_pipeline.evidential import ClaimGenerator, build_envelope, get_generator, no_envelope_reason
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
    # The decision of the legacy contained answer the learner received for the shadowed turn (V1's comparison and
    # D-20 replacement; Phase 4 spec 4.13). None for replay and fixture runs.
    legacy_decision: Literal["answer", "abstain"] | None = None


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
    # No learner-facing text: the rendered response is internal and never returned to a learner.
    # The V1 run (v1_checks.runner.V1Run) when V1 ran (shadow or enforce), else None.
    v1: Any = None


@dataclass(frozen=True)
class RenderAttempt:
    """One render attempt as the V1 post_render hook sees it (Phase 4 spec 4.11): the presentation and omitted
    claims it used, the coerced rendering (None when the renderer raised or its envelope was invalid), the subset
    check's result on it, the step that raised (render or subset_check) and the V1.9 envelope reason."""

    attempt: int
    presentation: PresentationPlan
    omit: frozenset[str]
    rendered: RenderedResponse | None
    subset: Any
    fault: str | None
    envelope_error: str | None


@dataclass(frozen=True)
class HookVerdict:
    accept: bool
    next_presentation: PresentationPlan | None = None
    next_omit: frozenset[str] | None = None
    reason: str | None = None
    stop: bool = False


def rendered_claim_ids(rendered: RenderedResponse) -> tuple[str, ...]:
    """The claim ids a rendering shows, in render order, each once."""
    return tuple(dict.fromkeys(segment.claim_id for segment in rendered.segments if segment.kind == "claim" and segment.claim_id))


def rendered_span_ids(rendered: RenderedResponse) -> tuple[str, ...]:
    """The span ids a rendering's citation segments display, in display order, each once (spec 18.7 E1). The subset
    check already requires rendered.citations to equal this list; the record is built from the segments anyway."""
    return tuple(span_id for span_id in displayed_span_ids(rendered) if span_id)


def render_checked(
    renderer: Renderer,
    locked: LockedClaimSet,
    presentation: PresentationPlan,
    *,
    max_regenerations: int,
    over: Callable[[], bool] | None = None,
    post_render: Callable[[RenderAttempt], HookVerdict] | None = None,
    omit: frozenset[str] = frozenset(),
) -> tuple[RenderedResponse | None, int, str | None]:
    """Plan 3.7: render, subset-check; on an unmapped factual sentence re-render, at most max_regenerations times,
    then abstain. Returns (the passing rendering or None, attempts made, abstention reason or None).

    An attempt that raises (in the renderer, or in the subset check on its output) is a failed attempt too, but it is
    not a subset-check failure: it logs tutor.two_pass.render_failed with the step and the error class, and when every
    attempt raised the run abstains with render_failed, never subset_check_failed (spec 18.12 J3). So a crashing
    renderer is told apart from the plan J case of a renderer that adds a claim, in the record and in "abstention by
    reason". A tampered locked set still propagates.

    With post_render (the V1 track, Phase 4 spec 4.11) each attempt's output is first re-validated as a
    RenderedResponse (V1.9 envelope; an invalid one is not a fault and is not subset-checked), then subset-checked
    through this module's check_subset, and the hook decides: accept, or reject with a reason, a next presentation
    plan and next omitted claims, or stop. The reason returned is the hook's for the last rejected attempt that was not
    a fault (render_failed when every attempt raised). omit is passed to the renderer only when it is not empty. With
    neither post_render nor omit the behaviour is Phase 3's exactly."""
    if post_render is not None or omit:
        return _render_with_hook(renderer, locked, presentation, max_regenerations=max_regenerations, over=over,
                                 post_render=post_render, omit=omit)
    attempts = 1 + max_regenerations
    faults = 0
    for attempt in range(1, attempts + 1):
        step = "render"
        try:
            candidate = renderer.render(locked, presentation, attempt=attempt)
            step = "subset_check"
            passed = check_subset(candidate, locked).passed
        except contracts.LockedClaimSetTampered:
            raise
        except Exception as exc:  # noqa: BLE001 - a fault is a failed attempt, logged and counted apart (spec 18.12 J3)
            faults += 1
            passed = False
            LOGGER.error(
                "Two-pass render attempt raised",
                extra={FIELDS: {"event": "tutor.two_pass.render_failed", "step": step, "render_attempt": attempt, "error": type(exc).__name__}},
            )
        if passed:
            return candidate, attempt, None
        if attempt < attempts and over is not None and over():
            return None, attempt, "budget_exceeded"
    return None, attempts, contracts.RENDER_FAILED if faults == attempts else "subset_check_failed"


def _render_with_hook(renderer, locked, presentation, *, max_regenerations, over, post_render, omit):
    from app.services.v1_checks.v1_9_schema_readability import check_v1_9_envelope

    attempts = 1 + max_regenerations
    current, current_omit = presentation, frozenset(omit)
    reason: str | None = None
    for attempt in range(1, attempts + 1):
        rendered = subset = fault = envelope_error = None
        step = "render"
        try:
            options = {"omit_claim_ids": current_omit} if current_omit else {}
            candidate = renderer.render(locked, current, attempt=attempt, **options)
            envelope, rendered = check_v1_9_envelope(candidate, attempt=attempt)
            if rendered is None:
                envelope_error = envelope.reason_code
            else:
                step = "subset_check"
                subset = check_subset(rendered, locked)
        except contracts.LockedClaimSetTampered:
            raise
        except Exception as exc:  # noqa: BLE001 - a fault is a failed attempt, logged and counted apart (spec 18.12 J3)
            fault, rendered, subset = step, None, None
            LOGGER.error(
                "Two-pass render attempt raised",
                extra={FIELDS: {"event": "tutor.two_pass.render_failed", "step": step, "render_attempt": attempt, "error": type(exc).__name__}},
            )
        verdict = post_render(RenderAttempt(attempt, current, current_omit, rendered, subset, fault, envelope_error)) if post_render else (
            HookVerdict(accept=subset is not None and subset.passed, reason=None if fault else "subset_check_failed"))
        if verdict.accept and rendered is not None:
            return rendered, attempt, None
        if verdict.reason is not None:
            reason = verdict.reason
        if verdict.stop:
            return None, attempt, reason
        if verdict.next_presentation is not None:
            current = verdict.next_presentation
        if verdict.next_omit is not None:
            current_omit = frozenset(verdict.next_omit)
        if attempt < attempts and over is not None and over():
            return None, attempt, "budget_exceeded"
    return None, attempts, reason or contracts.RENDER_FAILED


# A shadow run whose Phase 3 composition never called the generator: the V1 track proposes itself.
_NO_RAW = object()


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
        checker: Any = None,
        keyed_items: Any = None,
        misconceptions: Any = None,
        v2_hook: Any = None,
        gateway: Any = None,
        adapter_registry: Any = None,
        cache: Any = None,
        tool_host: Any = None,
        v2_clock: Callable[[], float] = time.monotonic,
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
        # Phase 4 (spec 4.13): the V1 track's checker, keyed items and misconception library. A package without a v1
        # block (v1 or v2) runs Phase 3 only.
        self.v1_params = self.package.v1
        self.v2_hook = v2_hook
        # Phase 5 (spec 4.16): the V2 track's gateway, adapter registry, evidential cache and tool host. Each defaults,
        # when V2 runs, to the process gateway, the environment's registry, the process cache and the default tool host;
        # nothing is built while the V2 mode is off.
        self.gateway, self.adapter_registry, self.cache, self.tool_host = gateway, adapter_registry, cache, tool_host
        self.v2_clock = v2_clock
        # The clock V1.3 times a checker call with (tests and the fixture runner inject one).
        self.v1_clock: Callable[[], float] = time.monotonic
        self.checker, self.keyed_items, self.misconceptions = checker, keyed_items, misconceptions
        if self.v1_params is not None:
            from app.services.quiz_keys import QuizKeySource, QuizKeyStore
            from app.services.v1_checks.v1_3_entailment import get_checker
            from app.services.v1_checks.v1_8_misconceptions import load_library

            if self.checker is None:
                self.checker = get_checker(self.package)
            if self.keyed_items is None:
                self.keyed_items = QuizKeySource(getattr(self.store, "quiz_keys", None) or QuizKeyStore(()))
            if self.misconceptions is None:
                self.misconceptions = load_library(self.package)

    def _over(self, started: float, budget_ms: int | None, step: str, *, event: str = "tutor.two_pass.budget_exceeded") -> bool:
        """Whether the shadow budget is spent at `step`, logging `event` when it is. The record's own composition logs
        tutor.two_pass.budget_exceeded; a shadow-mode V1 track, which runs after the Phase 3 decision is fixed, logs
        tutor.v1.budget_exceeded, so the Phase 3 signal still means the record itself overran (spec 4.13, 10.4)."""
        if budget_ms is None:
            return False
        elapsed_ms = (self.clock() - started) * 1000
        if elapsed_ms <= budget_ms:
            return False
        message = "Two-pass shadow exceeded its budget" if event == "tutor.two_pass.budget_exceeded" else "The shadow V1 track exceeded its budget"
        LOGGER.warning(
            message,
            extra={FIELDS: {"event": event, "step": step, "elapsed_ms": round(elapsed_ms, 3), "budget_ms": budget_ms}},
        )
        return True

    def v2_mode(self) -> Literal["off", "shadow", "on"]:
        """The V2 mode of this pipeline: off with an explicit v2_hook, else v2_panel.mode for its settings and gateway."""
        if self.v2_hook is not None:
            return "off"
        from app.services import v2_panel

        return v2_panel.mode(self.settings, self.package, gateway=self.gateway)

    def _v2_parts(self):
        """(gateway, adapter registry, cache, tool host) for one run while V2 runs: the injected ones, else the process
        gateway and cache (read per run, never kept on the pipeline), the environment's registry and the default tool host
        over that gateway."""
        from app.gateway.gateway import get_gateway
        from app.gateway.registry import registry_for
        from app.gateway.tools import ToolHost
        from app.services.v2_panel.cache import get_cache

        gateway = self.gateway if self.gateway is not None else get_gateway()
        registry = self.adapter_registry if self.adapter_registry is not None else registry_for(self.package, self.settings)
        cache = self.cache if self.cache is not None else get_cache()
        tools = self.tool_host if self.tool_host is not None else ToolHost.default(self, gateway)
        return gateway, registry, cache, tools

    def _propose(self, envelope: EvidentialEnvelope, *, keep: list | None = None) -> ClaimPlan:
        """The generator's plan, re-validated. With `keep`, the raw output (or the generator's exception) is appended,
        so a shadow V1 track judges the same first proposal (spec 4.13)."""
        try:
            raw = self.generator.propose(envelope)
        except Exception as exc:
            if keep is not None:
                keep.append(exc)
            raise
        if keep is not None:
            keep.append(raw)
        plan = ClaimPlan.model_validate(raw.model_dump(mode="json") if isinstance(raw, BaseModel) else raw)
        if plan.generator != self.generator.ref:
            raise ValueError("the claim plan names another generator")
        return plan

    def _envelope(self, request: RetrievalRequest, bundle: EvidenceBundle, started: float, budget_ms: int | None) -> tuple[EvidentialEnvelope | None, str | None]:
        """Phase 3 steps 2-3: the gate's abstention, the retrieve budget, then the envelope or why there is none."""
        if bundle.sufficiency.decision == "abstain":
            return None, bundle.sufficiency.reason
        if self._over(started, budget_ms, "retrieve"):
            return None, "budget_exceeded"
        envelope = build_envelope(request, bundle, store=self.store, params=self.params)
        if envelope is None:
            # no_quotable_evidence or no_whole_sentence: which cause emptied the envelope (spec 18.11 I1).
            return None, no_envelope_reason(bundle, store=self.store)
        return envelope, None

    def run(self, item: PipelineInput, *, budget_ms: int | None = None, record: bool = True) -> PipelineResult:
        if item.delivery != "shadow" and not contracts.TWO_PASS_DELIVERY_IMPLEMENTED:
            raise DeliveryNotImplemented("two-pass output is delivered only after the Phase 4 exit (AC-3-6); run it in shadow")
        from app.services import v1_checks

        mode = v1_checks.mode(self.settings, self.package)
        v2_mode = self.v2_mode() if mode != "off" else "off"
        params = self.params
        started = self.clock()
        request = build_request(item.resolved, lesson_slug=item.lesson_slug, corpus_version=self.store.corpus_version)
        bundle = retrieve(self.engine, request, top_k=params.top_k, registry=self.registry)
        envelope, reason = self._envelope(request, bundle, started, budget_ms)
        if mode == "enforce":
            v1 = self._v1(item, bundle, envelope, reason, started, budget_ms, mode="enforce", phase3_decision=None, v2_mode=v2_mode)
            decision: Literal["answer", "abstain"]
            if v2_mode == "on":
                # The record abstains exactly when V2's final does (Phase 5 spec 4.16; LedgerEntryV2's enforce rule).
                decision = "abstain" if v1.record.final == "abstain" else "answer"
                reason = None if decision == "answer" else v1.record.final_reason
            else:
                decision = "answer" if v1.rendered is not None else "abstain"
                reason = None if decision == "answer" else v1.decision.abstention_reason
            entry = self._entry_v2(item, decision, reason, bundle, v1.locked, v1.rendered, v1.record.render_attempts, v1.proposed,
                                   v1.dropped, budget_ms, v1=v1, presentation=v1.presentation)
            return self._finish(item, entry, decision, reason, request, bundle, envelope, v1.plan, v1.locked, v1.rendered,
                                v1.record.render_attempts, record, v1=v1)
        raws: list = []
        plan: ClaimPlan | None = None
        drafts: tuple = ()
        dropped: Counter = Counter()
        proposed = 0
        if reason is None and envelope is not None:
            try:
                plan = self._propose(envelope, keep=raws)
            except Exception:  # noqa: BLE001 - any generator fault or malformed plan abstains (R-11)
                reason = "claim_plan_invalid"
            else:
                from app.services.v2_panel.cache import claim_plan_key, plan_cacheable

                if v2_mode != "off" and plan_cacheable(self.generator):
                    # V1 shadow: Phase 3's first proposal, validated, is the generation-1 claim plan (Phase 5 spec 4.15).
                    self._v2_parts()[2].put("claim_plan", claim_plan_key(envelope, self.package, self.generator.ref), plan)
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
        decision = "answer" if rendered is not None and reason is None else "abstain"
        if mode == "off":
            entry = self._entry(item, decision, reason, bundle, locked, rendered, attempts, proposed, dropped, budget_ms)
            return self._finish(item, entry, decision, reason, request, bundle, envelope, plan, locked, rendered, attempts, record)
        # shadow: the record is the Phase 3 composition's; the V1 track judges the same bundle and first proposal.
        first_raw = raws[0] if raws else _NO_RAW
        no_envelope = bundle.sufficiency.reason if bundle.sufficiency.decision == "abstain" else (reason if envelope is None else None)
        v1 = self._v1(item, bundle, envelope, no_envelope, started, budget_ms, mode="shadow", phase3_decision=decision, first_raw=first_raw,
                      v2_mode=v2_mode)
        entry = self._entry_v2(item, decision, reason, bundle, locked, rendered, attempts, proposed, dropped, budget_ms, v1=v1,
                               presentation=item.presentation)
        return self._finish(item, entry, decision, reason, request, bundle, envelope, plan, locked, rendered, attempts, record, v1=v1)

    def _v1(self, item: PipelineInput, bundle, envelope, envelope_reason, started, budget_ms, *, mode, phase3_decision, first_raw=_NO_RAW,
            v2_mode="off"):
        from app.services.v1_checks.runner import _UNSET, V1Context, V1Track

        context = V1Context(resolved=item.resolved, lesson_slug=item.lesson_slug, presentation=item.presentation,
                            legacy_decision=item.legacy_decision)
        hook, cache = self.v2_hook, None
        if v2_mode != "off":
            from app.services.v2_panel.track import V2Track

            gateway, registry, cache, tools = self._v2_parts()
            hook = V2Track(self, context, mode=v2_mode, gateway=gateway, adapter_registry=registry, cache=cache, tools=tools,
                           settings=self.settings, clock=self.v2_clock,
                           budget_over=lambda step: self._over(started, budget_ms, step, event="tutor.v2.budget_exceeded"))
        track = V1Track(self, checker=self.checker, keyed_items=self.keyed_items, library=self.misconceptions, v2_hook=hook,
                        clock=self.v1_clock, cache=cache if mode == "enforce" else None)
        # In enforce the V1 track is the record's composition; in shadow it runs after the record's decision.
        event = "tutor.two_pass.budget_exceeded" if mode == "enforce" else "tutor.v1.budget_exceeded"
        return track.run(
            context, bundle, envelope,
            envelope_reason=envelope_reason,
            first_raw=_UNSET if first_raw is _NO_RAW else first_raw,
            budget_over=lambda step: self._over(started, budget_ms, step, event=event),
            mode=mode,
            phase3_decision=phase3_decision,
        )

    def _finish(self, item, entry, decision, reason, request, bundle, envelope, plan, locked, rendered, attempts, record, *, v1=None) -> PipelineResult:
        params = self.params
        appended: AppendedRecord | None = None
        if record:
            LEDGER_METRICS.attempt(item.delivery)
            try:
                appended = append_ledger_entry(entry, session_factory=self.session_factory, budget_ms=ledger_budget_ms(self.settings, self.package),
                                               attempts=params.ledger_append_attempts)
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
            v1=v1,
        )

    def _provenance(self, bundle) -> Provenance:
        params = self.params
        return Provenance(
            generator_model_id=self.generator.ref.model_id,
            evidential_prompt_hash=self.generator.ref.prompt_hash,
            pedagogical_prompt_hash=params.pedagogical_prompt_hash,
            corpus_version=bundle.corpus_version,
            threshold_set_version=bundle.sufficiency.threshold_version,
        )

    def _entry_fields(self, item, decision, reason, bundle, locked, rendered, attempts, budget_ms, presentation: PresentationPlan) -> dict:
        """The fields a v1 and a v2 record share (everything but claims, provenance, verification and counts)."""
        package = self.package
        sufficiency = bundle.sufficiency
        return dict(
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
            span_ids=locked.span_ids,
            presentation=(
                PresentationRecord(
                    plan_id=presentation.plan_id,
                    source=presentation.source,
                    renderer_id=self.renderer.renderer_id,
                    attempts=attempts,
                    subset_check="passed" if rendered is not None else "failed",
                    # What the passing rendering showed (spec 18.6 D4): never the locked claims it left out, and
                    # the spans its citation segments display, not the renderer's own list (spec 18.7 E1).
                    rendered_claim_ids=rendered_claim_ids(rendered) if rendered is not None else (),
                    rendered_span_ids=rendered_span_ids(rendered) if rendered is not None else (),
                )
                if attempts
                else None
            ),
            rendered_text_sha256=sha256_hex(rendered.text if decision == "answer" and rendered is not None else ABSTENTION),
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
                budgets=budget_stamp(self.settings, package, shadow_ms=budget_ms),
            ),
        )

    def _entry(self, item, decision, reason, bundle, locked, rendered, attempts, proposed, dropped, budget_ms) -> LedgerEntry:
        provenance = self._provenance(bundle)
        claims = tuple(
            ClaimLedgerEntry(claim_id=claim.claim_id, response_id=item.response_id, text=claim.text, span_ids=claim.span_ids, provenance=provenance)
            for claim in locked.claims
        )
        return LedgerEntry(
            **self._entry_fields(item, decision, reason, bundle, locked, rendered, attempts, budget_ms, item.presentation),
            claims=claims,
            provenance=provenance,
            counts=PipelineCounts(
                proposed_claims=proposed,
                bound_claims=len(locked.claims),
                dropped=dict(sorted(dropped.items())),
                render_attempts=attempts,
            ),
        )

    def _entry_v2(self, item, decision, reason, bundle, locked, rendered, attempts, proposed, dropped, budget_ms, *, v1,
                  presentation: PresentationPlan) -> LedgerEntryV2:
        """A ledger-entry-v2 record (Phase 4 spec 4.13): the v1 fields, ProvenanceV2 naming the V1.3 checker, claims with
        their entailment score (enforce only, from a real checker), the V1 VerificationRecord and PipelineCountsV2. With
        a V2 verification record (Phase 5) it is a ledger-entry-v3 (_entry_v3)."""
        if isinstance(v1.record, VerificationRecordV2):
            return self._entry_v3(item, decision, reason, bundle, locked, rendered, attempts, proposed, dropped, budget_ms, v1=v1,
                                  presentation=presentation)
        base = self._provenance(bundle)
        provenance = ProvenanceV2(**base.model_dump(exclude={"v1_3_checker_model_id"}), v1_3_checker_model_id=v1.record.policy.checker_model_id)
        scores = v1.scores if v1.record.mode == "enforce" else {}
        claims = tuple(
            ClaimLedgerEntryV2(claim_id=claim.claim_id, response_id=item.response_id, text=claim.text, span_ids=claim.span_ids,
                               entailment_score=scores.get(claim.claim_id), provenance=provenance)
            for claim in locked.claims
        )
        return LedgerEntryV2(
            **self._entry_fields(item, decision, reason, bundle, locked, rendered, attempts, budget_ms, presentation),
            claims=claims,
            provenance=provenance,
            verification=v1.record,
            counts=PipelineCountsV2(
                proposed_claims=proposed,
                bound_claims=len(locked.claims),
                dropped=dict(sorted(dropped.items())),
                render_attempts=attempts,
            ),
        )

    def _entry_v3(self, item, decision, reason, bundle, locked, rendered, attempts, proposed, dropped, budget_ms, *, v1,
                  presentation: PresentationPlan) -> LedgerEntryV3:
        """A ledger-entry-v3 record (Phase 5 spec 4.16): the v2 fields, ProvenanceV3 filling every plan 7.4 provenance
        field from the package, and the VerificationRecordV2."""
        block = v1.record.v2
        base = self._provenance(bundle)
        provenance = ProvenanceV3(**base.model_dump(exclude={"v1_3_checker_model_id", "panel_weights_version", "routing_table_version",
                                                             "tool_contract_version"}),
                                  v1_3_checker_model_id=v1.record.policy.checker_model_id, panel_weights_version=block.panel_weights_version,
                                  routing_table_version=block.routing_table_version, tool_contract_version=block.tool_contract_version)
        scores = v1.scores if v1.record.mode == "enforce" else {}
        claims = tuple(
            ClaimLedgerEntryV3(claim_id=claim.claim_id, response_id=item.response_id, text=claim.text, span_ids=claim.span_ids,
                               entailment_score=scores.get(claim.claim_id), provenance=provenance)
            for claim in locked.claims
        )
        return LedgerEntryV3(
            **self._entry_fields(item, decision, reason, bundle, locked, rendered, attempts, budget_ms, presentation),
            claims=claims,
            provenance=provenance,
            verification=v1.record,
            counts=PipelineCountsV2(
                proposed_claims=proposed,
                bound_claims=len(locked.claims),
                dropped=dict(sorted(dropped.items())),
                render_attempts=attempts,
            ),
        )
