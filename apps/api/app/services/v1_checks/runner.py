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
    aggregate (aggregate.py) -> consult_v2 (no hook before Phase 5) -> VerificationRecord

The claims D-20 withholds (V1.3 flags, V1.8 matches, the claims of a withheld V1.7 conflict) are left out of the
rendering when some claim is left to show; when every claim is withheld every claim is rendered, recorded and never
deliverable. The track never writes the ledger and returns nothing to a learner: the pipeline records its
VerificationRecord on the shadow ledger record (AC-3-6).
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
        checks = (
            make_result("V1.9", "post_render", number, "schema_valid"),
            v1_4_result(attempt.subset, fault=None, attempt=number),
            check_v1_6(rendered, self.items, v1=v1, attempt=number),
            check_v1_9_readability(rendered, v1=v1, attempt=number),
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
                 v1: "V1Params | None" = None, clock: Callable[[], float] = time.monotonic) -> None:
        self.pipeline = pipeline
        self.v1 = v1 if v1 is not None else pipeline.v1_params
        if self.v1 is None:
            raise ValueError("the configuration package has no v1 block (package v3 is required)")
        self.checker = checker if checker is not None else pipeline.checker
        self.keyed_items = keyed_items if keyed_items is not None else pipeline.keyed_items
        self.library = library if library is not None else pipeline.misconceptions
        self.v2_hook = v2_hook
        self.clock = clock

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

    def _decide(self, ctx, bundle, envelope, envelope_reason, first_raw, budget_over, state: "_RunState") -> V1Decision:
        v1 = self.v1
        pipeline = self.pipeline
        results = state.results
        sufficiency = check_v1_5(bundle.sufficiency)
        results.append(sufficiency)
        if sufficiency.outcome == "abstain":
            return V1Abstained(results=tuple(results), generation_attempts=0, render_attempts=0, abstention_reason=bundle.sufficiency.reason)
        if envelope is None:
            return V1Abstained(results=tuple(results), generation_attempts=0, render_attempts=0,
                               abstention_reason=envelope_reason or "no_quotable_evidence")
        stopwords = pipeline.package.retrieval.stopwords
        attempts = 1 + v1.max_generation_regenerations
        generation = 0
        for generation in range(1, attempts + 1):
            if generation > 1 and budget_over("generate"):
                return V1Abstained(results=tuple(results), generation_attempts=generation - 1, render_attempts=0, abstention_reason="budget_exceeded")
            state.reset_candidate()
            raw = first_raw if generation == 1 and first_raw is not _UNSET else self._propose(envelope)
            schema, plan = check_v1_9_plan(raw, generator_ref=pipeline.generator.ref, attempt=generation)
            results.append(schema)
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
            resolution = check_v1_1(plan, bundle, resolver=pipeline.resolver, attempt=generation)
            results.append(resolution)
            if resolution.outcome == "hard_fail":
                if generation < attempts:
                    continue
                # V1.1 judges the candidate whole, so none of its claims is bound: each is counted under
                # unresolvable_citation (proposed == bound + dropped holds, and the plan L bound-claim ratio sees them).
                state.proposed, state.unbound = len(plan.claims), Counter({UNRESOLVABLE_CANDIDATE: len(plan.claims)})
                return V1HardFail(results=tuple(results), failing=(resolution,), generation_attempts=generation, render_attempts=0,
                                  abstention_reason="unresolvable_citation")
            binding = check_v1_2(plan, bundle, resolver=pipeline.resolver, store=pipeline.store, registry=pipeline.registry,
                                 params=pipeline.params, v1=v1, stopwords=stopwords, attempt=generation)
            results.extend(binding.results)
            state.binding, state.proposed = binding, len(plan.claims)
            if not binding.drafts:
                return V1Abstained(results=tuple(results), generation_attempts=generation, render_attempts=0, abstention_reason="no_bound_claims")
            state.locked = self._lock(binding.drafts, bundle, ctx, has_plan=True)
            if budget_over("bind"):
                return V1Abstained(results=tuple(results), generation_attempts=generation, render_attempts=0, abstention_reason="budget_exceeded")
            entailment = check_v1_3(state.locked, self._span_texts(state.locked), checker=self.checker, v1=v1, attempt=generation,
                                    clock=self.clock, scores=state.scores)
            results.extend(entailment)
            if any(result.outcome == "abstain" for result in entailment):
                return V1Abstained(results=tuple(results), generation_attempts=generation, render_attempts=0,
                                   abstention_reason="checker_unavailable")
            conflict, state.disclosure = check_v1_7(state.locked, bundle, sentences_of=self._sentences_of, v1=v1, stopwords=stopwords,
                                                    attempt=generation)
            results.append(conflict)
            results.extend(check_v1_8(state.locked, self.library, attempt=generation))
            break
        return self._render(ctx, state, generation, budget_over, stopwords)

    def _render(self, ctx, state: "_RunState", generation: int, budget_over, stopwords) -> V1Decision:
        from app.services.tutor_pipeline.pipeline import render_checked

        v1 = self.v1
        locked = state.locked
        results = state.results
        withheld = withheld_claim_ids(results, state.disclosure)
        claim_ids = {claim.claim_id for claim in locked.claims}
        omit = frozenset() if claim_ids <= withheld else frozenset(withheld & claim_ids)
        items = assessment_items(ctx.resolved.text, self.keyed_items, v1=v1, stopwords=stopwords)
        hook = _RenderHook(self, ctx, locked, items)
        rendered, attempts, reason = render_checked(
            self.pipeline.renderer, locked, ctx.presentation, max_regenerations=v1.max_render_regenerations,
            over=lambda: budget_over("render"), post_render=hook, omit=omit,
        )
        results.extend(hook.results)
        if rendered is not None:
            presentation = hook.accepted_presentation or ctx.presentation
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
                "flagged_claims": sum(1 for verdict in record.verdicts if verdict.final == "withhold"),
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

    def __post_init__(self) -> None:
        self.locked = self.empty

    def reset_candidate(self) -> None:
        """A regeneration is a new candidate: nothing of the previous one is carried over."""
        self.plan, self.binding, self.proposed, self.unbound, self.locked, self.disclosure = None, None, 0, Counter(), self.empty, None
        self.scores.clear()
