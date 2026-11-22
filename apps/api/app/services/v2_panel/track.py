"""The V2 track: the V1 track's V2 hook (plan Phase 5 tasks 5.3-5.11; plan 7.2 "[L6 V2 panel, tier rule]"; Phase 5
spec 4.2, 4.11, 4.12).

V2Track.consult(passed) judges one V1Passed candidate and returns a V2Outcome; only a V1Passed ever reaches it
(aggregate.v2_outcome; plan rule 1, invariant 3), so a V1 hard fail or abstention makes no gateway call (AC-5-5).
At the first consult of a response the track decides eligibility (ModelGateway.eligible, before any panel: R-b) and
builds the generator-excluded panel (Panel.build; AC-5-1, AC-5-2). Then, per V2-eligible claim (every locked claim but
the V1.8-matched ones, the claims of a withheld V1.7 conflict and the V1.6-omitted ones: V1.3 flags route to V2), in
locked order:
  mode = mode_for(members), rule = the package's routing table [mode][tier]
  withhold-queue-v3            the claim is withheld with no call (REDUCED-1 tiers 1-2 under D-29 (a), ZERO)
  otherwise, per member and cited span: the verdict cache, else verification.verdict through the tool host and the
  gateway; a member whose call is refused, fails after its retries, times out or returns output that fails its
  contract leaves the panel for the rest of the response, and the claim is re-tallied from the pairs held in memory
  under the new mode and rule (no cache query, no new call); a stopped gateway drops every member
  family verdicts (rule F) -> tally -> pass | fail | withheld
The claim item carries the claim text, one bound span (its id and resolved text, read through corpus.span_text) and
the fixed instructions: never the resolved question, another claim, the generator's identity or another vote (E5).
align(rendering) sends the alignment item to every remaining member (rule 1ooN-leakage-v1: fail iff any member flags
leakage; ratings are recorded and never gate). Every step logs enumerations and counts only.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import logging
import time
from typing import TYPE_CHECKING, Any, Literal, Protocol

from app.core.structured_logging import FIELDS
from app.gateway.adapters import AdapterError
from app.gateway.contracts import (
    AdapterVerdict,
    AlignmentInstructions,
    AlignmentRequest,
    ReadabilityBand,
    SpanRef,
    VerdictInstructions,
    VerdictRequest,
    VerdictSpan,
)
from app.gateway.gateway import GatewayRefused, GatewayStopped
from app.gateway.policy import PolicyContext
from app.gateway.registry import GeneratorFamilyUnknown, generator_family
from app.services.tutor_pipeline.contracts import AlignmentVote, V2Alignment, V2ClaimVerdict, V2Vote, sha256_hex
from app.services.v2_panel.cache import verdict_key
from app.services.v2_panel.panel import Panel
from app.services.v2_panel.rules import DEGRADED_MODES, matrix_from_package
from app.services.v2_panel.tiers import critical_for, tier_for
from app.services.v2_panel.voting import family_verdict, is_split, mode_for, objection_types, objections, tally

if TYPE_CHECKING:  # pragma: no cover
    from app.services.v1_checks.aggregate import V1Passed

LOGGER = logging.getLogger("qcai.tutor")
UNKNOWN_FAMILY = "unknown"


class ClaimReviser(Protocol):
    """An optional generator capability: revise a failed claim against its cited spans, or return None."""

    def revise(self, claim_text: str, span_texts: tuple[str, ...], ehmf_type: str) -> str | None: ...


@dataclass(frozen=True)
class V2Outcome:
    mode: Literal["shadow", "on"]
    generator_family: str
    members: tuple[str, ...]
    degraded_mode: str
    claims: Mapping[str, V2ClaimVerdict]      # eligible claims only
    alignment: V2Alignment | None
    calls: int
    cache_hits: int
    cost_units: int
    latency_ms: float
    gateway_state: str
    kill_switch: str

    def failing(self) -> tuple[str, ...]:
        return tuple(claim_id for claim_id, verdict in self.claims.items() if verdict.outcome == "fail")

    def objection_types(self, claim_id: str) -> tuple[str, ...]:
        """The EHMF types of one judged claim's objecting family verdicts, in family order (voting.objection_types)."""
        by_family: dict[str, list] = {}
        for vote in sorted(self.claims[claim_id].votes, key=lambda item: (item.family, item.span_id)):
            by_family.setdefault(vote.family, []).append((vote.verdict, vote.ehmf_type))
        return objection_types(by_family)


def worst_mode(modes) -> str:
    modes = list(modes)
    return max(modes, key=DEGRADED_MODES.index) if modes else "FULL"


class V2Track:
    """One response's V2 panel. A track is built per pipeline run; it holds the response's panel and counts."""

    is_v2_track = True

    def __init__(self, pipeline: Any, ctx: Any, *, mode: Literal["shadow", "on"], gateway: Any, adapter_registry: Any, cache: Any,
                 tools: Any, settings: Any, budget_over: Callable[[str], bool] = lambda step: False,
                 clock: Callable[[], float] = time.monotonic, package: Any = None) -> None:
        self.pipeline = pipeline
        self.ctx = ctx
        self.mode = mode
        self.gateway = gateway
        self.adapter_registry = adapter_registry
        self.cache = cache
        self.tools = tools
        self.settings = settings
        self.budget_over = budget_over
        self.clock = clock
        self.package = package if package is not None else pipeline.package
        v2 = self.package.v2
        self.table = {mode_name: dict(row) for mode_name, row in v2.matrix.items()}
        self.threshold = tuple(v2.tier3_threshold)
        self.verifier_prompt_hash = v2.verifier_prompt_hash
        self.alignment_prompt_hash = v2.alignment_prompt_hash
        self.tool_contract_version = self.package.tools.version
        self.kill_switch = settings.model_gateway_kill_switch or "none"
        self.resolved_question_sha256 = sha256_hex(ctx.resolved.text)
        self.started = False
        self.panel_reached = False
        self.members: list = []
        self.start_members: tuple[str, ...] = ()
        self.generator_family = UNKNOWN_FAMILY
        self.calls = self.cache_hits = self.cost_units = 0
        self.cycle = 0
        self.latency_ms = 0.0
        self.budget_exceeded = False
        self.consults = 0

    # ----------------------------------------------------------------------------------------------- panel

    def _begin(self) -> None:
        if self.started:
            return
        self.started = True
        gateway = self.gateway
        gateway.check_secret_flag()
        eligible = gateway.eligible(self.adapter_registry.verifiers(), settings=self.settings)
        try:
            family = generator_family(self.package, self.adapter_registry, self.pipeline.generator.ref.generator_id)
        except GeneratorFamilyUnknown:
            family, eligible = UNKNOWN_FAMILY, []
            LOGGER.warning("The V2 panel is unavailable: the generator's family is unknown",
                           extra={FIELDS: {"event": "tutor.v2.unavailable", "reason": "unknown_generator_family"}})
        panel = Panel.build(eligible, generator_family=family, max_members=self.package.v2.max_members)
        self.generator_family = family
        self.members = list(panel.members)
        self.start_members = tuple(sorted(panel.families()))
        if len(self.members) < self.package.v2.max_members:
            LOGGER.warning("The V2 panel is degraded", extra={FIELDS: {"event": "tutor.v2.degraded", "mode": mode_for(len(self.members)),
                                                                        "eligible": len(eligible)}})

    def _drop(self, member: Any) -> None:
        self.members = [spec for spec in self.members if spec.adapter_id != member.adapter_id]

    def _policy(self, rendering: Any = None, locked: Any = None) -> PolicyContext:
        pipeline = self.pipeline
        return PolicyContext(store=pipeline.store, corpus_registry=pipeline.registry, rendering=rendering, locked=locked,
                             lesson_slug=self.ctx.lesson_slug)

    # --------------------------------------------------------------------------------------------- consult

    def consult(self, passed: "V1Passed") -> "V2Outcome":
        from app.services.v1_checks.v1_6_keyed_answers import assessment_items
        from app.services.v2_panel.aggregate import v1_excluded

        started = self.clock()
        self._begin()
        self.panel_reached = True
        self.consults += 1
        pipeline = self.pipeline
        items = assessment_items(self.ctx.resolved.text, pipeline.keyed_items, v1=pipeline.v1_params, stopwords=self.package.retrieval.stopwords)
        tier = tier_for(items, self.package)
        excluded = v1_excluded(passed, items, pipeline.v1_params)
        claims: dict[str, V2ClaimVerdict] = {}
        for claim in passed.locked.claims:
            if claim.claim_id not in excluded:
                claims[claim.claim_id] = self._judge(claim, tier)
        alignment = None
        if self.mode == "shadow" and any(verdict.outcome == "pass" for verdict in claims.values()):
            alignment = self.align(passed.rendered, passed.locked)
        elapsed = (self.clock() - started) * 1000.0
        self.latency_ms += elapsed
        return V2Outcome(mode=self.mode, generator_family=self.generator_family, members=self.start_members,
                         degraded_mode=worst_mode(verdict.mode for verdict in claims.values()), claims=claims, alignment=alignment,
                         calls=self.calls, cache_hits=self.cache_hits, cost_units=self.cost_units, latency_ms=self.latency_ms,
                         gateway_state=self.gateway.state, kill_switch=self.kill_switch)

    def _request(self, claim: Any, span_id: str) -> tuple[VerdictRequest, Any]:
        span = self.tools.call("verifier", "corpus.span_text", SpanRef(span_id=span_id))
        try:
            request = VerdictRequest(claim_text=claim.text, span=VerdictSpan(span_id=span_id, text=span.text),
                                     instructions=VerdictInstructions(prompt_hash=self.verifier_prompt_hash,
                                                                      tool_contract_version=self.tool_contract_version))
        except ValueError:
            # A claim item the contract refuses (an identifier in its text) is a payload violation: the gateway stops.
            self.gateway.stop("payload_violation")
            raise GatewayStopped("the payload policy refused a request") from None
        return request, span

    def _pair(self, claim: Any, member: Any, span_id: str) -> tuple[AdapterVerdict, bool]:
        request, span = self._request(claim, span_id)
        pipeline = self.pipeline
        key = verdict_key(claim_text=claim.text, span_id=span_id, span_content_hash=span.content_hash, spec=member,
                          verifier_prompt_hash=self.verifier_prompt_hash, tool_contract_version=self.tool_contract_version,
                          resolved_question_sha256=self.resolved_question_sha256, corpus_version=pipeline.store.corpus_version,
                          package=self.package, generator_ref=pipeline.generator.ref)
        hit = self.cache.get("verdict", key)
        if hit is not None:
            self.cache_hits += 1
            return hit, True
        verdict = self.tools.call("verifier", "verification.verdict", request, adapter=member, policy=self._policy())
        self.calls += 1
        self.cost_units += member.cost_units_per_call
        self.cache.put("verdict", key, verdict)
        return verdict, False

    def _judge(self, claim: Any, tier: int) -> V2ClaimVerdict:
        pairs: dict[tuple[str, str], tuple[AdapterVerdict, bool]] = {}
        span_ids = sorted(claim.span_ids)
        while True:
            members = list(self.members)
            mode = mode_for(len(members))
            rule = self.table[mode][tier]
            families = tuple(sorted(member.family for member in members))
            common = dict(tier=tier, rule=rule, generator_family=self.generator_family, mode=mode, members=families,
                          critical=critical_for(claim.claim_id, self.package), cycle=self.cycle)
            if rule == "withhold-queue-v3":
                return V2ClaimVerdict(**common, votes=(), objections=0, split=False, outcome="withheld")
            lost = False
            for member in members:
                for span_id in span_ids:
                    if (member.adapter_id, span_id) in pairs:
                        continue
                    if self.budget_over("verify"):
                        self.budget_exceeded, self.members, lost = True, [], True
                        break
                    try:
                        pairs[(member.adapter_id, span_id)] = self._pair(claim, member, span_id)
                    except GatewayStopped:
                        self.members, lost = [], True
                        break
                    except (GatewayRefused, AdapterError):
                        self._drop(member)
                        pairs = {key: value for key, value in pairs.items() if key[0] != member.adapter_id}
                        lost = True
                        break
                if lost:
                    break
            if lost:
                continue
            family_verdicts = []
            votes = []
            for member in sorted(members, key=lambda spec: spec.family):
                member_pairs = [(pairs[(member.adapter_id, span_id)][0].verdict, pairs[(member.adapter_id, span_id)][0].ehmf_type)
                                for span_id in span_ids]
                family_verdicts.append(family_verdict(member_pairs)[0])
                for span_id in span_ids:
                    verdict, cached = pairs[(member.adapter_id, span_id)]
                    votes.append(V2Vote(verifier_model_id=member.model_id, verifier_model_version=member.model_version, family=member.family,
                                        verifier_prompt_hash=self.verifier_prompt_hash, verdict=verdict.verdict, ehmf_type=verdict.ehmf_type,
                                        span_id=span_id, cached=cached))
            outcome = tally(rule, family_verdicts, threshold=self.threshold)
            return V2ClaimVerdict(**common, votes=tuple(votes), objections=objections(family_verdicts), split=is_split(family_verdicts),
                                  outcome=outcome)

    # ---------------------------------------------------------------------------------------------- finish

    def panel_mode(self) -> str | None:
        """The worst mode this response's panel ran in: members only leave a panel within a response, so it is the mode
        of the members left at the end (ZERO with none); None when the panel was never reached."""
        return mode_for(len(self.members)) if self.panel_reached else None

    @staticmethod
    def completed(record: Any, *, passed: bool) -> bool:
        """Verification completion (plan Phase 5 I; spec 10.3): a V1-passed response whose every V2-eligible claim got a
        completed vote (pass or fail) and whose alignment item was judged when a claim passed. A withheld claim (REDUCED-1
        tiers 1-2, ZERO, a kill switch, a stop, the shadow budget) or an unjudged alignment item is not completed."""
        judged = [verdict.v2.outcome for verdict in record.verdicts if verdict.v2 is not None]
        if not passed or any(outcome == "withheld" for outcome in judged):
            return False
        return "pass" not in judged or record.v2.alignment is not None

    def finish(self, record: Any, *, passed: bool) -> None:
        """Log tutor.v2.run and count the response (enumerations and counts only)."""
        from collections import Counter

        from app.gateway.contracts import OutcomeEvent
        from app.services.v2_panel.metrics import V2_METRICS

        block = record.v2
        judged = [verdict for verdict in record.verdicts if verdict.v2 is not None]
        outcomes: dict[str, Counter] = {}
        for verdict in judged:
            outcomes.setdefault(str(verdict.v2.tier), Counter())[verdict.v2.outcome] += 1
        x2 = sum(1 for verdict in record.verdicts if verdict.v3 is not None and verdict.v3.escalation == "X2")
        withheld = sum(1 for verdict in record.verdicts if verdict.v3 is not None and "v2_degraded_withheld" in verdict.v3.reasons)
        completed = self.completed(record, passed=passed)
        panel_mode = self.panel_mode()
        V2_METRICS.run(mode=self.mode, panel_mode=panel_mode, passed_v1=passed, completed=completed, latency_ms=self.latency_ms,
                       cost_units=block.cost_units, x2=x2, degraded_withheld=withheld, budget_exceeded=self.budget_exceeded)
        if self.mode == "shadow" and block.shadow is not None and passed:
            summary = block.shadow
            would = ("deliver" if summary.would_deliver else "withhold" if summary.would_withhold else "abstain" if summary.would_fail
                     else record.final)
            if would != record.final:
                V2_METRICS.disagreement()
                LOGGER.info("V2 would decide otherwise than V1", extra={FIELDS: {"event": "tutor.v2.disagreement", "v1_final": record.final,
                                                                                 "v2_would": would}})
        LOGGER.info("V2 run", extra={FIELDS: {
            "event": "tutor.v2.run", "mode": self.mode, "degraded_mode": block.degraded_mode, "generator_family": self.generator_family,
            "members": list(self.start_members), "claims": len(judged), "outcomes": {tier: dict(counts) for tier, counts in sorted(outcomes.items())},
            "cycles": block.cycles, "x2": x2, "calls": block.calls, "cache_hits": block.cache_hits, "cost_units": block.cost_units,
            "latency_ms": round(self.latency_ms, 3), "alignment": block.alignment.outcome if block.alignment is not None else None,
            "passed_v1": passed, "panel_reached": self.panel_reached, "panel_mode": panel_mode, "completed": completed,
        }})
        if record.final in ("deliver", "withhold", "abstain"):
            try:
                self.tools.call("ledger", "analytics.record_outcome", OutcomeEvent(final=record.final, degraded_mode=block.degraded_mode,
                                                                                    calls=block.calls, cost_units=block.cost_units))
            except Exception:  # noqa: BLE001 - an analytics fault never changes the record
                pass

    # ------------------------------------------------------------------------------------------- alignment

    def align(self, rendered: Any, locked: Any) -> V2Alignment | None:
        """The alignment item over one rendering, sent to every remaining member; None when no member is left."""
        if rendered is None or not self.members:
            return None
        started = self.clock()
        v1 = self.pipeline.v1_params
        lesson = getattr(self.pipeline.store, "lessons", {}).get(self.ctx.lesson_slug) if self.ctx.lesson_slug else None
        request = AlignmentRequest(rendered_text=rendered.text, objective=getattr(lesson, "summary", None),
                                   band=ReadabilityBand(min_grade=v1.readability_min, max_grade=v1.readability_max),
                                   instructions=AlignmentInstructions(prompt_hash=self.alignment_prompt_hash,
                                                                      tool_contract_version=self.tool_contract_version))
        votes = []
        for member in list(self.members):
            try:
                verdict = self.tools.call("verifier", "verification.alignment", request, adapter=member,
                                          policy=self._policy(rendering=rendered, locked=locked))
            except GatewayStopped:
                self.members = []
                break
            except (GatewayRefused, AdapterError):
                self._drop(member)
                continue
            self.calls += 1
            self.cost_units += member.cost_units_per_call
            votes.append(AlignmentVote(verifier_model_id=member.model_id, verifier_model_version=member.model_version, family=member.family,
                                       verifier_prompt_hash=self.alignment_prompt_hash, rating=verdict.rating, leakage=verdict.leakage))
        self.latency_ms += (self.clock() - started) * 1000.0
        if not votes:
            return None
        votes.sort(key=lambda vote: vote.family)
        return V2Alignment(members=tuple(vote.family for vote in votes), votes=tuple(votes), rendered_text_sha256=sha256_hex(rendered.text),
                           outcome="fail" if any(vote.leakage for vote in votes) else "pass")
