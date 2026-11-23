"""Phase 5 correction cycles (plan Phase 5 task 5.8 "Correction: two cycles, then abstain and mark X2 when critical; Type E
re-renders only"; AC-5-7; plan 7.2 "--fail--> correct, re-verify, <= 2 cycles, else abstain + enqueue V3 (X2)"; Phase
5 spec 4.13, 4.14, conflict 6)."""

from __future__ import annotations

from app.core.config import Settings
from app.services.tutor_pipeline.bind import whole_sentences
from app.services.tutor_pipeline.evidential import ExtractiveD19Generator
from app.services.tutor_pipeline.render import TemplateRenderer
from v1_fakes import MULTI_CLAIM, ScriptedChecker, UnmappedRenderer, dev_pipeline, run
from v2_fakes import RevisingGenerator, adapters_of, claim_key, fresh_gateway, make_registry, v2_pipeline

TIER2 = "Why do the sources repeatedly emphasize hybrid loops instead of end-to-end quantum models?"
QUERIES = (TIER2, MULTI_CLAIM, "What makes a QC+AI claim plausible in the NISQ era?", "What does a quantum kernel add in the aneurysm classification example?")


def contradicting(registry, claim):
    """Every member contradicts this claim on each of its spans."""
    script = {claim_key(claim.text, span_id): ("CONTRADICTED", "A") for span_id in claim.span_ids}
    return adapters_of(registry, **{spec.adapter_id: {"script": script} for spec in registry.members})


def revisable():
    """(query, claim, revision): a locked claim and another whole sentence of its own span, which binds as a claim."""
    pipeline = dev_pipeline()
    params = pipeline.params
    for query in QUERIES:
        result = run(pipeline, query)
        texts = {claim.text for claim in result.locked.claims}
        for claim in result.locked.claims:
            record = pipeline.store.span_registry.get(claim.span_ids[0])
            for sentence in whole_sentences(record, pipeline.store, min_words=params.min_sentence_words, max_chars=params.max_sentence_chars):
                if sentence.text not in texts:
                    return query, claim, sentence.text
    raise AssertionError("no revisable claim in the queries")


def test_a_revised_claim_is_a_new_candidate_judged_by_v1_from_the_start_and_delivered_when_it_passes():
    query, claim, revision = revisable()
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    adapters = contradicting(registry, claim)
    base = dev_pipeline()
    generator = RevisingGenerator(ExtractiveD19Generator(base.package), {claim.text: revision})
    result = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=registry, generator=generator), query)
    verification = result.entry.verification
    assert verification.v2.cycles == 1 and [item.kind for item in verification.v2.corrections] == ["revise"]
    assert verification.v2.corrections[0].revised_claim_ids == (claim.claim_id,)
    assert claim.claim_id not in {verdict.claim_id for verdict in verification.verdicts}
    assert revision in {item.text for item in result.entry.claims} and verification.final == "deliver"
    # Fresh V1 state: the record holds the new candidate's own pre-render results, one generation attempt.
    assert verification.generation_attempts == 1 and sum(1 for check in verification.checks if check.check_id == "V1.1") == 1
    assert generator.proposals == 1 and generator.revised == [(claim.text, "A")]


def test_an_unrevisable_claim_is_re_verified_unchanged_from_the_cache_and_abstains_with_x2_after_two_cycles():
    pipeline = dev_pipeline()
    claims = run(pipeline, TIER2).locked.claims
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    adapters = contradicting(registry, claims[1])
    v2 = v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=registry)
    result = run(v2, TIER2)
    verification = result.entry.verification
    block = verification.v2
    assert block.cycles == 2 and [item.kind for item in block.corrections] == ["revise", "revise"]
    assert all(item.revised_claim_ids == () for item in block.corrections)
    # Cycles 1 and 2 re-verified every pair from the cache: three claims x three members once, plus the alignment item.
    assert block.calls == 9 + 3 and block.cache_hits == 2 * 9 and all(adapter.calls == 4 for adapter in adapters.values())
    by_id = {verdict.claim_id: verdict for verdict in verification.verdicts}
    failed = by_id[claims[1].claim_id]
    assert failed.final == "abstain" and failed.v3.escalation == "X2" and "v2_correction_exhausted" in failed.v3.reasons
    assert failed.v2.cycle == 2 and all(vote.cached for vote in failed.v2.votes)
    assert {by_id[claims[0].claim_id].final, by_id[claims[2].claim_id].final} == {"deliver"} and verification.final == "deliver"
    # The final rendering shows the deliverable claims only.
    shown = {segment.claim_id for segment in result.rendered.segments if segment.kind == "claim"}
    assert shown == {claims[0].claim_id, claims[2].claim_id} and result.entry.presentation.rendered_claim_ids == tuple(
        claim.claim_id for claim in claims if claim.claim_id in shown)


def test_every_rendering_is_judged_with_a_fresh_post_render_hook():
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    leaky = adapters_of(registry, **{"fake-alpha-v1": {"alignment": {"rating": 3, "leakage": True}}})
    result = run(v2_pipeline(gateway=fresh_gateway(adapters=leaky), registry=registry), TIER2)
    verification = result.entry.verification
    assert [item.kind for item in verification.v2.corrections] == ["re_render", "re_render"]
    post = [check for check in verification.checks if check.stage == "post_render"]
    assert {check.attempt for check in post} == set(range(1, verification.render_attempts + 1))
    assert sum(1 for check in post if check.check_id == "V1.4") == verification.render_attempts  # this rendering's attempts only
    assert verification.final == "abstain" and verification.final_reason == "v2_alignment_failed"
    assert all(verdict.final == "abstain" and verdict.v3.escalation == "X2" for verdict in verification.verdicts)


class LaterUnmapped:
    """The template renderer for the first render call; every later call adds an unmapped sentence (V1.4 hard fail)."""

    def __init__(self, package) -> None:
        self.inner = TemplateRenderer(package)
        self.renderer_id = self.inner.renderer_id
        self.unmapped = UnmappedRenderer(self.inner, None)
        self.calls = 0

    def render(self, locked, plan, *, attempt, **options):
        self.calls += 1
        return (self.inner if self.calls == 1 else self.unmapped).render(locked, plan, attempt=attempt, **options)


def test_a_corrected_candidate_that_hard_fails_v1_ends_with_no_further_v2_call():
    query, claim, revision = revisable()
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    adapters = contradicting(registry, claim)
    base = dev_pipeline()
    generator = RevisingGenerator(ExtractiveD19Generator(base.package), {claim.text: revision})
    pipeline = v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=registry, generator=generator, renderer=LaterUnmapped(base.package))
    result = run(pipeline, query)
    verification = result.entry.verification
    assert verification.hard_fail and verification.final == "abstain" and result.decision == "abstain"
    assert verification.v2.panel_reached and verification.v2.cycles == 1
    assert all(verdict.v2 is None for verdict in verification.verdicts) and verification.v2.alignment is None
    claims = len(run(dev_pipeline(), query).locked.claims)
    assert all(adapter.calls == claims for adapter in adapters.values())  # one consult, of the first candidate only


def test_v1_3_flags_route_to_v2_only_under_on():
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    on = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters_of(registry)), registry=registry), TIER2).entry.verification
    shadow = run(v2_pipeline(Settings(model_gateway="shadow"), gateway=fresh_gateway(adapters=adapters_of(registry)), registry=registry),
                 TIER2).entry.verification
    flagged = lambda verdict: any(check.check_id == "V1.3" and check.outcome == "flag" for check in verdict.v1)  # noqa: E731
    assert all(flagged(verdict) for verdict in on.verdicts) and all(flagged(verdict) for verdict in shadow.verdicts)
    assert {verdict.final for verdict in on.verdicts} == {"deliver"} and {verdict.final for verdict in shadow.verdicts} == {"withhold"}
    assert all(verdict.v3 is None for verdict in on.verdicts) and all("v1_3_flag" in verdict.v3.reasons for verdict in shadow.verdicts)


def test_in_shadow_v1_withholds_and_renders_a_v1_3_flagged_claim_as_with_v2_off():
    # A checker that supports the first claim and flags the rest: in shadow V1's rendering omits the flagged claims as
    # with MODEL_GATEWAY off (D-20), so the V2 shadow changes neither the record's decision nor what it rendered.
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    entries = {}
    for setting in ("off", "shadow"):
        checker = ScriptedChecker([("SUPPORTED", 0.99), ("NOT_ENOUGH_INFO", 0.1)])
        pipeline = (dev_pipeline(Settings(model_gateway="off"), checker=checker) if setting == "off" else
                    v2_pipeline(Settings(model_gateway="shadow"), gateway=fresh_gateway(adapters=adapters_of(registry)), registry=registry,
                                checker=checker))
        entries[setting] = run(pipeline, MULTI_CLAIM, legacy_decision="answer").entry
    off, shadow = entries["off"], entries["shadow"]
    assert [verdict.final for verdict in off.verification.verdicts] == ["deliver", "withhold", "withhold"]
    assert shadow.verification.v2.mode == "shadow"
    assert [verdict.final for verdict in shadow.verification.verdicts] == [verdict.final for verdict in off.verification.verdicts]
    assert shadow.presentation.rendered_claim_ids == off.presentation.rendered_claim_ids and len(off.presentation.rendered_claim_ids) == 1
    assert shadow.rendered_text_sha256 == off.rendered_text_sha256



# ------------------------------------------------------------------------------------- Phase 6: the X1 sticky hold


def _critical_case():
    import v3_fakes

    base = dev_pipeline()
    target = next(claim for claim in v3_fakes.critical_claims_of(base) if claim.claim_id == v3_fakes.CRITICAL_CLAIMS[0])
    return base, target


def test_a_critical_tier_1_claim_is_never_revised_and_ends_with_x2():
    # Phase 6 spec 4.13: a claim the development registry marks critical at tier 1 that fails is held: never given to
    # revise(), re-verified unchanged in every cycle, abstained with X2 after the last; the other claims are unaffected.
    import v3_fakes

    base, target = _critical_case()
    sentence = target.text + " A revision the generator would offer."
    generator = RevisingGenerator(ExtractiveD19Generator(base.package), {target.text: sentence})
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    adapters = v3_fakes.objecting_adapters(registry, "fake-beta-v1", {target.text: tuple(target.span_ids)})
    result = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=registry, generator=generator), v3_fakes.CRITICAL_QUERY)
    verification = result.entry.verification
    held = next(verdict for verdict in verification.verdicts if verdict.claim_id == target.claim_id)
    assert generator.revised == [] and sentence not in {claim.text for claim in result.entry.claims}
    assert held.v2.critical is True and held.v2.tier == 1 and held.final == "abstain" and held.v3.escalation == "X2"
    assert verification.v2.cycles == 2 and [item.kind for item in verification.v2.corrections] == ["revise", "revise"]
    assert all(item.failed_claim_ids == (target.claim_id,) and item.revised_claim_ids == () for item in verification.v2.corrections)
    assert verification.final == "deliver" and {verdict.final for verdict in verification.verdicts if verdict.claim_id != target.claim_id} == {"deliver"}


def test_a_critical_tier_1_claim_stays_held_when_its_objector_leaves_the_panel():
    # The objector fails its next call and leaves the panel, so the claim's next tally passes 1oo2 (REDUCED-2): the hold
    # keeps it pending to the last cycle and it abstains with X2 instead of being delivered (Phase 6 spec conflict 1).
    import v3_fakes

    base, target = _critical_case()
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    adapters = v3_fakes.objecting_adapters(registry, "fake-beta-v1", {target.text: tuple(target.span_ids)}, fail_calls=(4,))
    result = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=registry, cache=v3_fakes.NoCache()), v3_fakes.CRITICAL_QUERY)
    verification = result.entry.verification
    held = next(verdict for verdict in verification.verdicts if verdict.claim_id == target.claim_id)
    assert (held.v2.mode, held.v2.outcome, held.v2.objections) == ("REDUCED-2", "pass", 0)
    assert held.final == "abstain" and held.v3.escalation == "X2" and verification.v2.cycles == 2
    assert target.claim_id not in {segment.claim_id for segment in result.rendered.segments if segment.kind == "claim"}
    # A non-critical tier-2 claim whose objector leaves the panel is delivered once it passes, as in Phase 5.
    claims = run(dev_pipeline(), TIER2).locked.claims
    adapters = v3_fakes.objecting_adapters(registry, "fake-beta-v1", {claims[1].text: tuple(claims[1].span_ids)})
    plain = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=registry), TIER2).entry.verification
    assert next(verdict for verdict in plain.verdicts if verdict.claim_id == claims[1].claim_id).v2.critical is False
