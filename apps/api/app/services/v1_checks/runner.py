"""The V1 track of the two-pass pipeline (plan 7.2 L6 stages; plan Phase 4 D; Phase 4 spec 4.11).

    V1.5 on the bundle (abstain | mark | pass)
    generation loop, 1 + v1.max_generation_regenerations attempts, on each candidate claim plan:
        V1.9 plan schema -> V1.1 resolution -> V1.2 binding and polarity -> lock -> V1.3 entailment -> V1.7 -> V1.8
        a hard fail of V1.9 or V1.1 regenerates (a new candidate, judged from the start) or ends in a V1HardFail;
        no claims, no bound claim or an unavailable checker abstain at once
    render loop (pipeline.render_checked with a post_render hook), 1 + v1.max_render_regenerations attempts:
        V1.9 envelope -> V1.4 (the Phase 3 subset check, through the pipeline's check_subset seam) -> V1.6 -> V1.9 band
        an attempt is accepted iff all four pass; a V1.6 failure re-renders with the socratic plan and leaves the keyed
        claims out (or abstains with keyed_answer_leak when nothing would be left); a band miss re-renders
    aggregate (aggregate.py) -> consult_v2 (an explicit V2 hook, the Phase 4 seam) -> VerificationRecord

With the Phase 5 V2 track as its hook (v2_panel.track.V2Track; Phase 5 spec 4.13, 4.14) run() instead:
    every candidate has its own run state (no earlier candidate's results reach accepted_results), and only a
    V1Passed reaches the track (aggregate.v2_outcome; plan rule 1, invariant 3)
    shadow  one V2 vote per candidate beside the Phase 4 decision, which decides every final
    on      failing claims are corrected at most MAX_CORRECTION_CYCLES times (rules.CORRECTION_RULES, plan 5.8): a claim
            whose objections are all EHMF type E is re-rendered only (the same candidate, Socratic, a fresh post-render
            hook; a "re_render" cycle when every failing claim is such a claim); any other failing claim is revised
            through the generator's optional revise(), else re-verified unchanged, every pair a cache hit (a "revise"
            cycle); a changed plan is a new candidate that every V1 check judges from the start, with fresh state;
            still failing after two cycles, a claim abstains with escalation X2. A claim the V2 track marks critical at
            tier 1 that fails in any cycle is held for the rest of the response (the X1 sticky hold, Phase 6 spec 4.13):
            it is never given to revise(), it stays pending in every later cycle even when a later tally passes (an
            objector that left the panel), and after the last cycle it ends abstained with X2, or withheld when its last
            outcome is V2-withheld; its objection stays in the record. Then the final rendering of the deliverable
            claims (fresh post-render hook), and the alignment item, whose failure is type E and re-renders only (sharing
            the two cycles)
    -> build_record_v2 -> VerificationRecordV2
The correction loop's only bound is the EHMF correction guard (ehmf.correction.CorrectionGuard, max_cycles from the
package; Phase 7 spec 4.4): before each cycle the runner asks begin_cycle(cycles + 1), and a third cycle is refused, so
the claims it would have corrected abstain with X2. With EHMF shadow or on (Phase 7; development only by default) the
runner also records each cycle's claim and span sets, refuses a re-render that changes either (the response abstains,
ehmf_set_changed; AC-7-4) and builds a VerificationRecordV4 with the ehmf block (ehmf.record). Under EHMF on each
detector call is guarded (ehmf.detectors): a detector that raises abstains the response with ehmf_detector_down.
The generation-1 claim plan is read from and written to the evidential cache (v2_panel.cache) when a V2 track runs in
enforce; a regeneration and a correction candidate bypass it, and a cached plan whose candidate hard-fails V1.9 or
V1.1 is evicted. V1 latency is measured without the V2 time.

The claims D-20 withholds (V1.3 flags, V1.8 matches, the claims of a withheld V1.7 conflict) are left out of the
rendering when some claim is left to show; when every claim is withheld every claim is rendered, recorded and never
deliverable. Under MODEL_GATEWAY=on V1.3 flags route to V2 and stay in the rendering. The track never writes the
ledger and returns nothing to a learner: the pipeline records its verification record on the shadow ledger record
(AC-3-6).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
import logging
import time
from typing import TYPE_CHECKING, Any, Literal

from app.core.structured_logging import FIELDS
from app.services.tutor_pipeline.bind import whole_sentences
from app.services.tutor_pipeline.contracts import (
    BUDGET_SKIPPED,
    UNRESOLVABLE_CANDIDATE,
    CheckResult,
    ClaimPlan,
    DisclosureBlock,
    EvidenceBundle,
    EvidentialEnvelope,
    LockedClaimSet,
    PresentationPlan,
    RenderedResponse,
    ResolvedQuestion,
    V1Policy,
    VerificationRecord,
)
from app.services.tutor_pipeline.lock import lock
from app.services.v1_checks.aggregate import (
    V1Abstained,
    V1Decision,
    V1HardFail,
    V1Passed,
    build_record,
    consult_v2,
    labels_for,
    passed_verdicts,
    v2_outcome,
    withheld_claim_ids,
)
from app.services.v1_checks.metrics import V1_METRICS
from app.services.v1_checks.results import make_result
from app.services.v1_checks.rules import MS_PER_S, RULES_VERSION, SCORE_DIGITS
from app.services.v1_checks.v1_1_resolution import check_v1_1, resolution_problem
from app.services.v1_checks.v1_2_binding import BindingCheck, check_v1_2
from app.services.v1_checks.v1_3_entailment import check_v1_3
from app.services.v1_checks.v1_4_subset import v1_4_result
from app.services.v1_checks.v1_5_abstention import check_v1_5
from app.services.v1_checks.v1_6_keyed_answers import assessment_items, check_v1_6, keyed_claim_ids
from app.services.v1_checks.v1_7_conflicts import check_v1_7
from app.services.v1_checks.v1_8_misconceptions import check_v1_8
from app.services.v1_checks.v1_9_schema_readability import check_v1_9_plan, check_v1_9_readability

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config_package import V1Params
    from app.services.tutor_pipeline.pipeline import RenderAttempt, TwoPassPipeline

LOGGER = logging.getLogger("qcai.tutor")
_UNSET: Any = object()


@dataclass(frozen=True)
class V1Context:
    resolved: ResolvedQuestion
    lesson_slug: str | None
    presentation: PresentationPlan
    legacy_decision: str | None


@dataclass(frozen=True)
class V1Run:
    decision: V1Decision
    record: VerificationRecord
    plan: ClaimPlan | None
    bind: BindingCheck | None
    locked: LockedClaimSet
    rendered: RenderedResponse | None
    presentation: PresentationPlan
    latency_ms: float
    # What an enforce record counts: the final candidate's proposed claims and drops (zero when bind never ran on it).
    proposed: int = 0
    dropped: Counter = field(default_factory=Counter)
    scores: dict = field(default_factory=dict)
    # The last V2 outcome (v2_panel.track.V2Outcome) when a V2 track ran, else None.
    v2: Any = None


class _RenderHook:
    """The post_render hook: V1.9 envelope, V1.4, V1.6 and the V1.9 band on every attempt (spec 4.11 step 5)."""

    def __init__(self, track: "V1Track", ctx: V1Context, locked: LockedClaimSet, items) -> None:
        self.track = track
        self.ctx = ctx
        self.locked = locked
        self.items = items
        self.results: list[CheckResult] = []
        self.keyed_omitted: frozenset[str] = frozenset()
        self.accepted_presentation: PresentationPlan | None = None
        self.last_hard = False
        self.last_failing: tuple[CheckResult, ...] = ()
        self.attempts = 0

    def __call__(self, attempt: "RenderAttempt"):
        from app.services.tutor_pipeline.pipeline import HookVerdict

        v1 = self.track.v1
        number = attempt.attempt
        self.attempts = number
        if attempt.fault is not None:
            fault = v1_4_result(None, fault=attempt.fault, attempt=number)
            self.results.append(fault)
            if not self.last_failing:
                self.last_hard, self.last_failing = True, (fault,)
            return HookVerdict(accept=False)
        if attempt.envelope_error is not None or attempt.rendered is None:
            invalid = make_result("V1.9", "post_render", number, "response_envelope_invalid")
            self.results.append(invalid)
            self.last_hard, self.last_failing = True, (invalid,)
            return HookVerdict(accept=False, reason="response_envelope_invalid")
        rendered = attempt.rendered
        guard = self.track._guard
        checks = (
            make_result("V1.9", "post_render", number, "schema_valid"),
            guard("V1.4", v1_4_result, attempt.subset, fault=None, attempt=number),
            guard("V1.6", check_v1_6, rendered, self.items, v1=v1, attempt=number),
            guard("V1.9", check_v1_9_readability, rendered, v1=v1, attempt=number),
        )
        self.results.extend(checks)
        if all(result.outcome == "pass" for result in checks):
            self.accepted_presentation = attempt.presentation
            return HookVerdict(accept=True)
        _envelope, subset, keyed, band = checks
        if subset.outcome == "hard_fail":
            reason, failing = "subset_check_failed", subset
        elif keyed.outcome == "hard_fail":
            reason, failing = "keyed_answer_leak", keyed
        else:
            reason, failing = "readability_out_of_band", band
        self.last_hard, self.last_failing = failing.outcome == "hard_fail", (failing,)
        if keyed.outcome != "hard_fail":
            return HookVerdict(accept=False, reason=reason)
        keyed_ids = keyed_claim_ids(self.locked, self.items, v1=v1)
        omit = frozenset(attempt.omit) | keyed_ids
        self.keyed_omitted = self.keyed_omitted | keyed_ids
        if all(claim.claim_id in omit for claim in self.locked.claims):
            self.last_hard, self.last_failing = True, (keyed,)
            return HookVerdict(accept=False, reason="keyed_answer_leak", stop=True)
        socratic = PresentationPlan(plan_id=v1.socratic_plan, source=self.ctx.presentation.source)
        return HookVerdict(accept=False, reason=reason, next_presentation=socratic, next_omit=omit)


class V1Track:
    def __init__(self, pipeline: "TwoPassPipeline", *, checker=None, keyed_items=None, library=None, v2_hook=None,
                 v1: "V1Params | None" = None, clock: Callable[[], float] = time.monotonic, cache: Any = None,
                 ehmf_mode: str = "off") -> None:
        self.pipeline = pipeline
        # Phase 7: "off" (Phase 6 exactly), "shadow" (typed v4 record and the set check) or "on" (also the detector guard).
        self.ehmf_mode = ehmf_mode if getattr(getattr(pipeline, "package", None), "ehmf", None) is not None else "off"
        self.v1 = v1 if v1 is not None else pipeline.v1_params
        if self.v1 is None:
            raise ValueError("the configuration package has no v1 block (package v3 is required)")
        self.checker = checker if checker is not None else pipeline.checker
        self.keyed_items = keyed_items if keyed_items is not None else pipeline.keyed_items
        self.library = library if library is not None else pipeline.misconceptions
        self.v2_hook = v2_hook
        self.clock = clock
        # The evidential cache for the generation-1 claim plan (only with a V2 track in enforce; Phase 5 spec 4.15).
        self.cache = cache
        # Under MODEL_GATEWAY=on V1.3 flags route to V2, so the rendering keeps them (Phase 5 spec 4.16).
        self.v1_3_routes_to_v2 = getattr(v2_hook, "is_v2_track", False) and getattr(v2_hook, "mode", None) == "on"

    def policy(self) -> V1Policy:
        return V1Policy(
            rules_version=RULES_VERSION,
            rules_hash=self.v1.rules_hash,
            checker_hosting=self.v1.checker_hosting,
            checker_model_id=self.checker.checker_model_id,
            misconception_library_version=self.library.version,
            misconception_library_sha256=self.library.sha256,
            d20_interim=self.v1.d20_rule,
        )

    # ------------------------------------------------------------------------------------------------ helpers

    def _propose(self, envelope: EvidentialEnvelope) -> object:
        try:
            return self.pipeline.generator.propose(envelope)
        except Exception as exc:  # noqa: BLE001 - a generator fault is an invalid plan (V1.9)
            return exc

    def _lock(self, drafts, bundle: EvidenceBundle, ctx: V1Context, *, has_plan: bool) -> LockedClaimSet:
        pipeline = self.pipeline
        return lock(
            drafts,
            bundle=bundle,
            generator=pipeline.generator.ref if has_plan else None,
            evidential_prompt_hash=pipeline.generator.ref.prompt_hash if has_plan else None,
            pedagogical_prompt_hash=pipeline.params.pedagogical_prompt_hash,
            resolver=ctx.resolved.resolver,
            package=pipeline.package,
        )

    def _sentences_of(self, span_id: str) -> tuple[str, ...]:
        params = self.pipeline.params
        record = self.pipeline.store.span_registry.get(span_id)
        if record is None:
            return ()
        return tuple(sentence.text for sentence in
                     whole_sentences(record, self.pipeline.store, min_words=params.min_sentence_words, max_chars=params.max_sentence_chars))

    def _span_texts(self, locked: LockedClaimSet) -> dict[str, str]:
        registry = self.pipeline.store.span_registry
        return {span_id: record.text for span_id in locked.span_ids if (record := registry.get(span_id)) is not None}

    def _guard(self, detector: str, fn, *args, **kwargs):
        """Under EHMF=on, a detector call that raises becomes DetectorDown(detector) (Phase 7 spec 4.3); else the call."""
        if self.ehmf_mode != "on":
            return fn(*args, **kwargs)
        from app.services.ehmf.detectors import guarded

        return guarded(detector, fn, *args, **kwargs)

    def _subset_check(self, rendered, locked):
        """The post-render subset check (V1.4's detector), guarded under EHMF=on (Phase 7 spec 4.3): a raise is then
        DetectorDown("V1.4"), never a render fault. Read from the pipeline module at call time."""
        from app.services.tutor_pipeline import pipeline as pipeline_module

        return self._guard("V1.4", pipeline_module.check_subset, rendered, locked)

    def _check_library(self) -> None:
        if self.ehmf_mode == "on" and (self.library is None or getattr(self.library, "available", True) is False):
            from app.services.ehmf.detectors import DetectorDown

            raise DetectorDown("V1.8")

    # ---------------------------------------------------------------------------------------------------- run

    def run(
        self,
        ctx: V1Context,
        bundle: EvidenceBundle,
        envelope: EvidentialEnvelope | None,
        *,
        envelope_reason: str | None = None,
        first_raw: object = _UNSET,
        budget_over: Callable[[str], bool] = lambda step: False,
        mode: Literal["shadow", "enforce"],
        phase3_decision: str | None,
    ) -> V1Run:
        if getattr(self.v2_hook, "is_v2_track", False):
            return self._run_v2(ctx, bundle, envelope, envelope_reason=envelope_reason, first_raw=first_raw, budget_over=budget_over,
                                mode=mode, phase3_decision=phase3_decision)
        started = time.perf_counter()
        state = _RunState(empty=self._lock((), bundle, ctx, has_plan=False))
        decision = self._decide(ctx, bundle, envelope, envelope_reason, first_raw, budget_over, state)
        decision = consult_v2(self.v2_hook, decision)
        record = build_record(decision, mode=mode, policy=self.policy(), locked=state.locked, disclosure=state.disclosure,
                              phase3_decision=phase3_decision, legacy_decision=ctx.legacy_decision)
        latency_ms = (time.perf_counter() - started) * MS_PER_S
        self._observe(record, latency_ms, bundle, state.locked)
        passed = isinstance(decision, V1Passed)
        return V1Run(
            decision=decision,
            record=record,
            plan=state.plan,
            bind=state.binding,
            locked=state.locked,
            rendered=decision.rendered if passed else None,
            presentation=decision.presentation if passed else ctx.presentation,
            latency_ms=latency_ms,
            proposed=state.proposed,
            dropped=state.binding.dropped if state.binding is not None else Counter(state.unbound),
            scores=dict(state.scores),
        )

    def _decide(self, ctx, bundle, envelope, envelope_reason, first_raw, budget_over, state: "_RunState", *,
                regenerate: bool = True) -> V1Decision:
        v1 = self.v1
        pipeline = self.pipeline
        results = state.results
        sufficiency = self._guard("V1.5", check_v1_5, bundle.sufficiency, x4_margin=v1.x4_margin[bundle.sufficiency.gate])
        results.append(sufficiency)
        if sufficiency.outcome == "abstain":
            return V1Abstained(results=tuple(results), generation_attempts=0, render_attempts=0, abstention_reason=bundle.sufficiency.reason)
        if envelope is None:
            return V1Abstained(results=tuple(results), generation_attempts=0, render_attempts=0,
                               abstention_reason=envelope_reason or "no_quotable_evidence")
        stopwords = pipeline.package.retrieval.stopwords
        attempts = 1 + v1.max_generation_regenerations if regenerate else 1
        generation = 0
        for generation in range(1, attempts + 1):
            if generation > 1 and budget_over("generate"):
                return V1Abstained(results=tuple(results), generation_attempts=generation - 1, render_attempts=0, abstention_reason="budget_exceeded")
            state.reset_candidate()
            state.attempt = generation
            cache_key, cached = self._cached_plan(envelope) if generation == 1 and first_raw is _UNSET and regenerate else (None, None)
            raw = first_raw if generation == 1 and first_raw is not _UNSET else (cached if cached is not None else self._propose(envelope))
            schema, plan = check_v1_9_plan(raw, generator_ref=pipeline.generator.ref, attempt=generation)
            results.append(schema)
            if cache_key is not None:
                if plan is None and cached is not None:
                    self.cache.evict("claim_plan", cache_key)
                elif plan is not None and cached is None:
                    self.cache.put("claim_plan", cache_key, plan)
            if plan is None:
                if generation < attempts:
                    continue
                return V1HardFail(results=tuple(results), failing=(schema,), generation_attempts=generation, render_attempts=0,
                                  abstention_reason="claim_plan_invalid")
            state.plan = plan
            # A valid plan stamps its generator on the lock even when nothing binds (as Phase 3's lock does).
            state.locked = self._lock((), bundle, ctx, has_plan=True)
            if not plan.claims:
                return V1Abstained(results=tuple(results), generation_attempts=generation, render_attempts=0, abstention_reason="no_claims")
            if budget_over("generate"):
                # As in Phase 3: bind never runs, so the claims are counted as skipped, never as binding failures.
                state.proposed, state.unbound = len(plan.claims), Counter({BUDGET_SKIPPED: len(plan.claims)})
                return V1Abstained(results=tuple(results), generation_attempts=generation, render_attempts=0, abstention_reason="budget_exceeded")
            resolution = self._guard("V1.1", check_v1_1, plan, bundle, resolver=pipeline.resolver, attempt=generation)
            results.append(resolution)
            if resolution.outcome == "hard_fail":
                if cache_key is not None:
                    self.cache.evict("claim_plan", cache_key)
                if generation < attempts:
                    continue
                # V1.1 judges the candidate whole, so none of its claims is bound: each is counted under
                # unresolvable_citation (proposed == bound + dropped holds, and the plan L bound-claim ratio sees them).
                state.proposed, state.unbound = len(plan.claims), Counter({UNRESOLVABLE_CANDIDATE: len(plan.claims)})
                return V1HardFail(results=tuple(results), failing=(resolution,), generation_attempts=generation, render_attempts=0,
                                  abstention_reason="unresolvable_citation")
            binding = self._guard("V1.2", check_v1_2, plan, bundle, resolver=pipeline.resolver, store=pipeline.store, registry=pipeline.registry,
                                  params=pipeline.params, v1=v1, stopwords=stopwords, attempt=generation)
            results.extend(binding.results)
            state.binding, state.proposed = binding, len(plan.claims)
            if not binding.drafts:
                return V1Abstained(results=tuple(results), generation_attempts=generation, render_attempts=0, abstention_reason="no_bound_claims")
            state.locked = self._lock(binding.drafts, bundle, ctx, has_plan=True)
            if budget_over("bind"):
                return V1Abstained(results=tuple(results), generation_attempts=generation, render_attempts=0, abstention_reason="budget_exceeded")
            entailment = self._guard("V1.3", check_v1_3, state.locked, self._span_texts(state.locked), checker=self.checker, v1=v1,
                                     attempt=generation, clock=self.clock, scores=state.scores)
            results.extend(entailment)
            if any(result.outcome == "abstain" for result in entailment):
                return V1Abstained(results=tuple(results), generation_attempts=generation, render_attempts=0,
                                   abstention_reason="checker_unavailable")
            conflict, state.disclosure = self._guard("V1.7", check_v1_7, state.locked, bundle, sentences_of=self._sentences_of, v1=v1,
                                                     stopwords=stopwords, attempt=generation)
            results.append(conflict)
            self._check_library()
            results.extend(self._guard("V1.8", check_v1_8, state.locked, self.library, attempt=generation))
            break
        state.pre_render, state.generation = tuple(results), generation
        return self._render(ctx, state, generation, budget_over, stopwords)

    def _cached_plan(self, envelope: EvidentialEnvelope) -> tuple[str | None, ClaimPlan | None]:
        from app.services.v2_panel.cache import claim_plan_key, plan_cacheable

        if self.cache is None or envelope is None or not plan_cacheable(self.pipeline.generator):
            return None, None

        key = claim_plan_key(envelope, self.pipeline.package, self.pipeline.generator.ref)
        return key, self.cache.get("claim_plan", key)

    def _render(self, ctx, state: "_RunState", generation: int, budget_over, stopwords, *, presentation: PresentationPlan | None = None,
                omit_extra: frozenset[str] = frozenset()) -> V1Decision:
        """Render the candidate's locked claims with a fresh post-render hook. The decision's results are the candidate's
        pre-render results and this rendering's post-render results only (a re-render never mixes in an earlier one)."""
        from app.services.tutor_pipeline.pipeline import render_checked

        v1 = self.v1
        locked = state.locked
        results = list(state.pre_render) if state.pre_render is not None else state.results
        withheld = withheld_claim_ids(results, state.disclosure, v1_3_routes_to_v2=self.v1_3_routes_to_v2)
        claim_ids = {claim.claim_id for claim in locked.claims}
        omit = frozenset() if claim_ids <= withheld else frozenset(withheld & claim_ids)
        if omit_extra:
            omit = frozenset(omit | omit_extra) & frozenset(claim_ids)
        items = assessment_items(ctx.resolved.text, self.keyed_items, v1=v1, stopwords=stopwords)
        hook = _RenderHook(self, ctx, locked, items)
        start_presentation = presentation or ctx.presentation
        rendered, attempts, reason = render_checked(
            self.pipeline.renderer, locked, start_presentation, max_regenerations=v1.max_render_regenerations,
            over=lambda: budget_over("render"), post_render=hook, omit=omit, subset_check=self._subset_check,
        )
        results.extend(hook.results)
        if rendered is not None:
            presentation = hook.accepted_presentation or start_presentation
            verdicts, final, final_reason = passed_verdicts(
                locked=locked, rendered=rendered, results=tuple(results), disclosure=state.disclosure,
                keyed_omitted=hook.keyed_omitted, generation_attempts=generation, render_attempts=attempts,
            )
            return V1Passed(locked=locked, rendered=rendered, presentation=presentation, results=tuple(results), verdicts=verdicts,
                            disclosure=state.disclosure, labels=labels_for(results, state.disclosure), generation_attempts=generation,
                            render_attempts=attempts, final=final, final_reason=final_reason)
        reason = reason or "render_failed"
        if reason != "budget_exceeded" and hook.last_hard:
            return V1HardFail(results=tuple(results), failing=hook.last_failing, generation_attempts=generation, render_attempts=attempts,
                              abstention_reason=reason)
        return V1Abstained(results=tuple(results), generation_attempts=generation, render_attempts=attempts, abstention_reason=reason)

    # ------------------------------------------------------------------------------------------------- V2

    def _run_v2(self, ctx, bundle, envelope, *, envelope_reason, first_raw, budget_over, mode, phase3_decision) -> V1Run:
        """The run with the Phase 5 V2 track as its hook (Phase 5 spec 4.13, 4.14)."""
        from app.services.ehmf.correction import CorrectionGuard, CorrectionLimit
        from app.services.ehmf.detectors import DetectorDown
        from app.services.tutor_pipeline.contracts import V2Correction
        from app.services.v2_panel.aggregate import _record_fields_v2
        from app.services.v2_panel.metrics import V2_METRICS
        from app.services.v2_panel.voting import presentation_only

        track = self.v2_hook
        started = time.perf_counter()
        state = _RunState(empty=self._lock((), bundle, ctx, has_plan=False))
        outcome, cycles, corrections, exhausted = None, 0, [], frozenset()
        ehmf = _EhmfRun(self, guard=CorrectionGuard(max_cycles=self._max_cycles()))
        ehmf.state = state
        held: set[str] = set()
        alignment, alignment_failed, alignment_missing = None, False, False
        try:
            decision = self._decide(ctx, bundle, envelope, envelope_reason, first_raw, budget_over, state)
            decision, outcome, cycles, exhausted, alignment, alignment_failed, alignment_missing = self._v2_loop(
                ctx, bundle, envelope, budget_over, state, decision, corrections, held, ehmf, V2Correction, V2_METRICS, presentation_only,
                CorrectionLimit)
        except DetectorDown as down:
            state = ehmf.state
            ehmf.detector_down = (down.detector,)
            outcome = None
            decision = V1Abstained(results=tuple(state.results), generation_attempts=state.attempt, render_attempts=0,
                                   abstention_reason="ehmf_detector_down")
            LOGGER.warning("An EHMF detector is down: the response abstains", extra={FIELDS: {
                "event": "tutor.ehmf.detector_down", "detector": down.detector}})
            cycles = len(corrections)
            ehmf.pad(corrections, state.locked)
        state = ehmf.state
        passed = isinstance(decision, V1Passed)
        fields = _record_fields_v2(decision, mode=mode, policy=self.policy(), locked=state.locked, disclosure=state.disclosure,
                                   phase3_decision=phase3_decision, legacy_decision=ctx.legacy_decision, track=track,
                                   outcome=outcome if passed else None, cycles=cycles, corrections=tuple(corrections), exhausted=exhausted,
                                   alignment=alignment, alignment_failed=alignment_failed, alignment_missing=alignment_missing)
        record = ehmf.build(fields)
        latency_ms = max((time.perf_counter() - started) * MS_PER_S - track.latency_ms, 0.0)
        self._observe(record, latency_ms, bundle, state.locked)
        track.finish(record, passed=passed)
        return V1Run(
            decision=decision,
            record=record,
            plan=state.plan,
            bind=state.binding,
            locked=state.locked,
            rendered=decision.rendered if passed else None,
            presentation=decision.presentation if passed else ctx.presentation,
            latency_ms=latency_ms,
            proposed=state.proposed,
            dropped=state.binding.dropped if state.binding is not None else Counter(state.unbound),
            scores=dict(state.scores),
            v2=outcome if passed else None,
        )

    def _max_cycles(self) -> int:
        """The correction bound: the package's ehmf.max_cycles (v2.correction.max_cycles) from v6, else Phase 5's."""
        from app.services.v2_panel.rules import MAX_CORRECTION_CYCLES

        params = getattr(self.pipeline.package, "ehmf", None)
        return params.max_cycles if params is not None else MAX_CORRECTION_CYCLES

    def _v2_loop(self, ctx, bundle, envelope, budget_over, state, decision, corrections, held, ehmf, V2Correction, V2_METRICS,
                 presentation_only, CorrectionLimit):
        track = self.v2_hook
        outcome, cycles, exhausted = None, 0, frozenset()
        while True:
            track.cycle = cycles
            outcome = self._guard("V2", v2_outcome, track, decision)
            if outcome is None or outcome.mode == "shadow":
                break
            failing = outcome.failing()
            # The X1 sticky hold (Phase 6 spec 4.13): a critical tier-1 claim that failed in any cycle stays pending
            # while its outcome is a pass, so a later tally that passes (its objector left the panel) never delivers it.
            held |= {claim_id for claim_id in failing if outcome.claims[claim_id].critical and outcome.claims[claim_id].tier == 1}
            pending = frozenset(failing) | frozenset(claim_id for claim_id in held
                                                    if claim_id in outcome.claims and outcome.claims[claim_id].outcome == "pass")
            if not pending:
                break
            try:
                ehmf.guard.begin_cycle(cycles + 1)
            except CorrectionLimit:
                ehmf.refused_cycle(cycles + 1)
                exhausted = pending
                break
            cycles += 1
            correction_started = time.perf_counter()
            # Plan 5.8 "Type E re-renders only": a claim whose objections are all type E (presentation) is never revised;
            # a held claim is never revised either (it is re-verified unchanged).
            presentation = frozenset(claim_id for claim_id in failing if claim_id not in held and presentation_only(outcome.objection_types(claim_id)))
            content = tuple(claim_id for claim_id in failing if claim_id not in presentation and claim_id not in held)
            plan, revised = self._correction_plan(decision, content, outcome) if content else (None, [])
            corrections.append(V2Correction(cycle=cycles, kind="revise" if content or pending & held else "re_render",
                                            failed_claim_ids=tuple(sorted(pending)), revised_claim_ids=tuple(sorted(revised))))
            before = decision
            if revised:
                # A new candidate, judged by every V1 check from the start with fresh state (Phase 4 R-d); a hard fail
                # or an abstention ends the loop with no further V2 call. Its rendering re-renders the type E claims too.
                state = _RunState(empty=self._lock((), bundle, ctx, has_plan=False))
                ehmf.state = state
                decision = self._decide(ctx, bundle, envelope, None, plan, budget_over, state, regenerate=False)
            elif presentation:
                # The same candidate rendered again (Socratic, a fresh post-render hook); a V1 failure of the rendering
                # ends the loop with no further V2 call.
                socratic = PresentationPlan(plan_id=self.v1.socratic_plan, source=ctx.presentation.source)
                decision = self._render(ctx, state, state.generation, budget_over, self.pipeline.package.retrieval.stopwords, presentation=socratic)
            decision = ehmf.cycle(cycles, corrections[-1].kind, before, decision, outcome, pending)
            V2_METRICS.correction((time.perf_counter() - correction_started) * MS_PER_S)
            if ehmf.set_changed:
                return decision, None, cycles, exhausted, None, False, False
        alignment, alignment_failed, alignment_missing = None, False, False
        if isinstance(decision, V1Passed) and outcome is not None and outcome.mode == "on":
            decision, alignment, cycles, alignment_failed, alignment_missing = self._final_rendering(
                ctx, state, decision, outcome, exhausted, cycles, corrections, budget_over, ehmf=ehmf)
            if ehmf.set_changed:
                alignment = None
        return decision, outcome, cycles, exhausted, alignment, alignment_failed, alignment_missing

    def _correction_plan(self, decision: V1Passed, failing, outcome) -> tuple[ClaimPlan, list[str]]:
        """The next candidate's claim plan: each failing claim given here (those with an objection of a type other than
        E) revised against its cited spans when the generator can revise (an optional revise(claim_text, span_texts,
        ehmf_type), given the first such type in family order), else unchanged; every other claim unchanged."""
        from app.services.tutor_pipeline.contracts import ProposedClaim

        generator = self.pipeline.generator
        revise = getattr(generator, "revise", None)
        registry = self.pipeline.store.span_registry
        claims, revised = [], []
        for claim in decision.locked.claims:
            text = claim.text
            if claim.claim_id in failing and callable(revise):
                ehmf = next(ehmf for ehmf in outcome.objection_types(claim.claim_id) if ehmf != "E")
                spans = tuple(record.text for span_id in claim.span_ids if (record := registry.get(span_id)) is not None)
                proposal = revise(claim.text, spans, ehmf)
                if proposal and proposal != claim.text:
                    text = proposal
                    revised.append(claim.claim_id)
            claims.append(ProposedClaim(text=text, span_ids=claim.span_ids))
        return ClaimPlan(generator=generator.ref, claims=tuple(claims)), revised

    def _final_rendering(self, ctx, state, decision: V1Passed, outcome, exhausted, cycles: int, corrections: list, budget_over, *,
                         ehmf: "_EhmfRun | None" = None):
        """Mode on: render the deliverable claims once more when they differ from what V1's accepted rendering shows
        (not a correction cycle), then the alignment item on it; a Type E failure re-renders only (Socratic, the same
        omissions), sharing the cycles. Returns (decision, alignment, cycles, alignment_failed, alignment_missing)."""
        from app.services.ehmf.correction import CorrectionGuard, CorrectionLimit
        from app.services.tutor_pipeline.contracts import V2Correction
        from app.services.v1_checks.v1_6_keyed_answers import assessment_items as items_for
        from app.services.v2_panel.aggregate import v1_excluded

        if ehmf is None:
            ehmf = _EhmfRun(self, guard=CorrectionGuard(max_cycles=self._max_cycles()))

        track = self.v2_hook
        stopwords = self.pipeline.package.retrieval.stopwords
        items = items_for(ctx.resolved.text, self.keyed_items, v1=self.v1, stopwords=stopwords)
        excluded = v1_excluded(decision, items, self.v1)
        deliverable = frozenset(claim_id for claim_id, verdict in outcome.claims.items() if verdict.outcome == "pass") - exhausted - excluded
        if not deliverable:
            return decision, None, cycles, False, False
        omit_extra = frozenset(claim.claim_id for claim in decision.locked.claims) - deliverable

        def shown(rendering) -> frozenset[str]:
            return frozenset(segment.claim_id for segment in rendering.segments if segment.kind == "claim" and segment.claim_id)

        if shown(decision.rendered) != deliverable:
            rendered = self._render(ctx, state, state.generation, budget_over, stopwords, presentation=decision.presentation, omit_extra=omit_extra)
            if not isinstance(rendered, V1Passed):
                return rendered, None, cycles, False, False
            decision = rendered
        while True:
            alignment = self._guard("alignment", track.align, decision.rendered, decision.locked)
            if alignment is None:
                return decision, None, cycles, False, True
            if alignment.outcome == "pass":
                return decision, alignment, cycles, False, False
            try:
                ehmf.guard.begin_cycle(cycles + 1)
            except CorrectionLimit:
                ehmf.refused_cycle(cycles + 1)
                return decision, alignment, cycles, True, False
            cycles += 1
            corrections.append(V2Correction(cycle=cycles, kind="re_render", failed_claim_ids=tuple(sorted(shown(decision.rendered)))))
            socratic = PresentationPlan(plan_id=self.v1.socratic_plan, source=ctx.presentation.source)
            before = decision
            rendered = self._render(ctx, state, state.generation, budget_over, stopwords, presentation=socratic, omit_extra=omit_extra)
            rendered = ehmf.cycle(cycles, "re_render", before, rendered, None, (), types=("E",))
            if ehmf.set_changed or not isinstance(rendered, V1Passed):
                return rendered, None, cycles, False, False
            decision = rendered

    # ---------------------------------------------------------------------------------------------- observe

    def _observe(self, record: VerificationRecord, latency_ms: float, bundle: EvidenceBundle, locked: LockedClaimSet) -> None:
        resolver = self.pipeline.resolver
        delivering = {verdict.claim_id for verdict in record.verdicts if verdict.final == "deliver"}
        delivered = [span_id for claim in locked.claims if claim.claim_id in delivering for span_id in claim.span_ids]
        resolved = sum(1 for span_id in delivered if resolution_problem(span_id, bundle, resolver) is None)
        V1_METRICS.run(record, latency_ms=latency_ms, delivered_span_ids=len(delivered), delivered_resolved=resolved,
                       budget_ms=self.v1.p95_budget_ms)
        outcomes: dict[str, dict[str, int]] = {}
        for result in record.checks:
            outcomes.setdefault(result.check_id, Counter())[result.outcome] += 1
        LOGGER.info(
            "V1 run",
            extra={FIELDS: {
                "event": "tutor.v1.run",
                "mode": record.mode,
                "final": record.final,
                "final_reason": record.final_reason,
                "hard_fail": record.hard_fail,
                "generation_attempts": record.generation_attempts,
                "render_attempts": record.render_attempts,
                "cycle_count": record.cycle_count,
                "outcomes": {check: dict(counts) for check, counts in sorted(outcomes.items())},
                # Claims whose verdict is withhold, for any reason (V1.3, V1.8, a withheld V1.7 conflict, V1.6 omission).
                # The V1.3 flag rate is outcomes["V1.3"]["flag"] over its flag plus pass results (spec 10.3).
                "withheld_claims": sum(1 for verdict in record.verdicts if verdict.final == "withhold"),
                "v3_intents": sum(1 for verdict in record.verdicts if verdict.v3 is not None),
                "disclosure": record.disclosure is not None,
                "latency_ms": round(latency_ms, SCORE_DIGITS),
                "gate": bundle.sufficiency.gate,
            }},
        )
        comparison = record.comparison
        for name, reference, agrees in (("phase3", comparison.phase3_decision, comparison.agrees_phase3),
                                        ("legacy", comparison.legacy_decision, comparison.agrees_legacy)):
            if reference is not None and agrees is False:
                V1_METRICS.disagreement(name)
                LOGGER.info("V1 disagrees with the shadowed decision",
                            extra={FIELDS: {"event": "tutor.v1.disagreement", "with": name, "v1_outcome": comparison.v1_outcome,
                                            "reference": reference}})


@dataclass
class _RunState:
    empty: LockedClaimSet
    results: list[CheckResult] = field(default_factory=list)
    plan: ClaimPlan | None = None
    binding: BindingCheck | None = None
    proposed: int = 0
    # The final candidate's claims that bind never judged (budget_exceeded, unresolvable_citation), by reason.
    unbound: Counter = field(default_factory=Counter)
    locked: LockedClaimSet | None = None
    disclosure: DisclosureBlock | None = None
    scores: dict = field(default_factory=dict)
    # The accepted candidate's pre-render results and generation attempt, which every rendering of it starts from.
    pre_render: tuple | None = None
    generation: int = 0
    # The generation attempt in progress (an EHMF detector-down abstention names it).
    attempt: int = 0

    def __post_init__(self) -> None:
        self.locked = self.empty

    def reset_candidate(self) -> None:
        """A regeneration is a new candidate: nothing of the previous one is carried over."""
        self.plan, self.binding, self.proposed, self.unbound, self.locked, self.disclosure = None, None, 0, Counter(), self.empty, None
        self.scores.clear()


class _EhmfRun:
    """The EHMF state of one V2 run (Phase 7 spec 4.4, 4.6): the correction guard, each cycle's record (its claim and
    span sets before and after, its finding types), the set check and the detector state. With EHMF off it only holds
    the guard (the loop's bound) and the record is the Phase 5/6 VerificationRecordV2."""

    def __init__(self, track: "V1Track", *, guard: Any) -> None:
        self.track = track
        self.guard = guard
        self.mode = track.ehmf_mode
        self.corrections: list = []
        self.detector_down: tuple[str, ...] = ()
        self.set_changed = False
        self.state: Any = None

    def refused_cycle(self, cycle: int) -> None:
        if self.mode != "off":
            LOGGER.warning("A correction cycle beyond the bound was refused", extra={FIELDS: {
                "event": "tutor.ehmf.correction_refused", "cycle": cycle, "reason": "cycle_limit"}})

    def pad(self, corrections: list, locked: Any) -> None:
        """A detector that went down inside a cycle ended it: that cycle is recorded as ended (no set after)."""
        if self.mode == "off":
            return
        from app.services.ehmf.correction import claim_set_sha256, span_set_sha256
        from app.services.tutor_pipeline.contracts import EhmfCorrection

        while len(self.corrections) < len(corrections):
            cycle = corrections[len(self.corrections)]
            self.corrections.append(EhmfCorrection(cycle=cycle.cycle, kind=cycle.kind, types=(), claim_set_before=claim_set_sha256(locked),
                                                   span_set_before=span_set_sha256(locked), outcome="ended"))

    def cycle(self, number: int, kind: str, before: Any, after: Any, outcome: Any, pending, *, types: tuple[str, ...] | None = None) -> Any:
        """Record one cycle; under EHMF shadow or on refuse a re-render that changed the claim or span set (AC-7-4): the
        decision becomes the response abstention ehmf_set_changed. Returns the decision to continue with."""
        if self.mode == "off":
            return after
        from app.services.ehmf.correction import claim_set_sha256, span_set_sha256
        from app.services.tutor_pipeline.contracts import EhmfCorrection

        if types is None:
            types = _objection_finding_types(outcome, pending)
        locked_before = before.locked
        passed = isinstance(after, V1Passed)
        after_claims = claim_set_sha256(after.locked) if passed else None
        after_spans = span_set_sha256(after.locked) if passed else None
        outcome_name = "applied" if passed else "ended"
        if passed and kind == "re_render" and not self.guard.check_re_render(locked_before, after.locked):
            outcome_name = "refused_set_changed"
        self.corrections.append(EhmfCorrection(cycle=number, kind=kind, types=tuple(sorted(set(types))),
                                               claim_set_before=claim_set_sha256(locked_before), claim_set_after=after_claims,
                                               span_set_before=span_set_sha256(locked_before), span_set_after=after_spans,
                                               outcome=outcome_name))
        if outcome_name != "refused_set_changed":
            return after
        self.set_changed = True
        LOGGER.warning("A re-render changed the claim or span set: the response abstains", extra={FIELDS: {
            "event": "tutor.ehmf.correction_refused", "cycle": number, "reason": "set_changed"}})
        return V1Abstained(results=tuple(before.results), generation_attempts=before.generation_attempts,
                           render_attempts=before.render_attempts, abstention_reason="ehmf_set_changed")

    def build(self, fields: dict) -> Any:
        from app.services.tutor_pipeline.contracts import VerificationRecordV2

        if self.mode == "off":
            return VerificationRecordV2(**fields)
        from app.services.ehmf.record import build_record_v4

        track = self.track
        pipeline = track.pipeline
        absent = ("V1.3",) if getattr(track.checker, "checker_model_id", None) == "none" else ()
        down = self.detector_down
        if not down and any(result.check_id == "V1.3" and result.reason_code == "checker_unavailable" for result in fields["checks"]):
            down = ("V1.3",)
        library = track.library
        record = build_record_v4(fields, mode=self.mode, package=pipeline.package, manifest=_manifest_of(pipeline),
                                 corrections=tuple(self.corrections), detector_down=down, detector_absent=absent,
                                 library=library)
        return record


def _objection_finding_types(outcome: Any, pending) -> tuple[str, ...]:
    """The finding types of the pending claims' objecting family verdicts in a V2 outcome (CONTRADICTED A, else B2)."""
    from app.services.v2_panel.voting import family_verdict

    types = set()
    claims = getattr(outcome, "claims", {}) or {}
    for claim_id in pending:
        verdict = claims.get(claim_id)
        if verdict is None:
            continue
        by_family: dict[str, list] = {}
        for vote in sorted(verdict.votes, key=lambda item: (item.family, item.span_id)):
            by_family.setdefault(vote.family, []).append((vote.verdict, vote.ehmf_type))
        for family in by_family:
            folded, _reported = family_verdict(by_family[family])
            if folded == "CONTRADICTED":
                types.add("A")
            elif folded == "NOT_ENOUGH_INFO":
                types.add("B2")
    return tuple(sorted(types))


def _manifest_of(pipeline: Any) -> Any:
    from app.services.ehmf.conflicts import manifest_items

    override = getattr(pipeline, "ehmf_manifest", None)
    if override is not None:
        return override
    return manifest_items(getattr(getattr(pipeline, "registry", None), "manifest_path", None))
