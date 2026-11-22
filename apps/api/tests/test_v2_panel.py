"""Phase 5 V2 panel: construction, eligibility, mid-response loss, kill switches, the alignment rule and tiers (plan Phase 5
tasks 5.3, 5.5, 5.6, 5.9, 5.11; R-20, R-21; Phase 5 spec 4.2, 4.8, 4.11, 4.12)."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.v2_panel.panel import Panel, PanelError
from v1_fakes import MULTI_CLAIM, run
from v2_fakes import adapters_of, fake_spec, fresh_gateway, make_registry, v2_pipeline

TIER2 = "Why do the sources repeatedly emphasize hybrid loops instead of end-to-end quantum models?"
FOUR = ("fake-alpha", "fake-beta", "fake-gamma", "fake-delta")


def judged(entry):
    return {verdict.claim_id: verdict.v2 for verdict in entry.verification.verdicts if verdict.v2 is not None}


def test_panel_build_excludes_the_generator_family_keeps_one_member_per_family_and_at_most_three():
    specs = [fake_spec("fake-alpha"), fake_spec("fake-alpha", adapter_id="fake-alpha-2"), fake_spec("fake-beta"), fake_spec("fake-gamma"),
             fake_spec("fake-delta"), fake_spec("fake-epsilon", capabilities=("generate",))]
    panel = Panel.build(specs, generator_family="fake-beta")
    assert panel.families() == ("fake-alpha", "fake-gamma", "fake-delta") and panel.members[0].adapter_id == "fake-alpha-v1"
    assert Panel.build(specs, generator_family="none", max_members=2).families() == ("fake-alpha", "fake-beta")
    for members, message in (((fake_spec("fake-beta"),), "generator's family"),
                             ((fake_spec("fake-alpha"), fake_spec("fake-alpha", adapter_id="fake-alpha-2")), "one member per family"),
                             (tuple(fake_spec(family) for family in ("a1", "b1", "c1", "d1")), "at most 3"),
                             ((fake_spec("fake-epsilon", capabilities=("generate",)),), "verifies")):
        with pytest.raises(PanelError, match=message):
            Panel(generator_family="fake-beta", members=members)


def test_each_eligibility_reason_drops_an_adapter_before_the_panel():
    registry = make_registry(FOUR)
    alpha = registry.members[0]
    cases = {
        "kill_switch": (Settings(model_gateway_kill_switch="abstain_only"), {}),
        "disabled": (Settings(model_gateway_disabled_adapters=["fake-alpha-v1"]), {}),
        "down": (Settings(), {"fake-alpha-v1": {"down": True}}),
    }
    for reason, (settings, options) in cases.items():
        gateway = fresh_gateway(adapters=adapters_of(registry, **options))
        assert gateway.ineligible_reason(alpha, settings=settings) == reason, reason
    assert fresh_gateway(0).ineligible_reason(alpha, settings=Settings()) == "budget"
    stopped = fresh_gateway()
    stopped.state = "stopped"
    assert stopped.ineligible_reason(alpha, settings=Settings()) == "stopped"
    paid = fake_spec("paid-family", provider="test-provider", endpoint="https://x.invalid/v1", auth_header="x-api-key", secret_ref="K1")
    assert fresh_gateway().ineligible_reason(paid, settings=Settings()) == "egress_refused"


def test_eligibility_precedes_the_panel_so_a_spare_family_or_a_second_adapter_represents_a_lost_one():
    registry = make_registry(FOUR)
    settings = Settings(model_gateway="on", model_gateway_disabled_adapters=["fake-gamma-v1"])
    entry = run(v2_pipeline(settings, gateway=fresh_gateway(adapters=adapters_of(registry)), registry=registry), TIER2).entry
    assert entry.verification.v2.members == ("fake-alpha", "fake-beta", "fake-delta") and entry.verification.v2.degraded_mode == "FULL"
    duplicated = make_registry(("fake-alpha", "fake-beta", "fake-gamma"), duplicate="fake-beta")
    adapters = adapters_of(duplicated)
    settings = Settings(model_gateway="on", model_gateway_disabled_adapters=["fake-beta-1"])
    entry = run(v2_pipeline(settings, gateway=fresh_gateway(adapters=adapters), registry=duplicated), TIER2).entry
    assert entry.verification.v2.members == ("fake-alpha", "fake-beta", "fake-gamma")
    assert adapters["fake-beta-1"].calls == 0 and adapters["fake-beta-2"].calls > 0


def test_a_member_lost_mid_response_leaves_the_panel_and_the_claim_is_re_tallied_from_memory():
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    adapters = adapters_of(registry, **{"fake-gamma-v1": {"fail_calls": {2}}})
    entry = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=registry), TIER2).entry
    verdicts = [entry.verification.verdicts[index].v2 for index in range(3)]
    assert [verdict.mode for verdict in verdicts] == ["FULL", "REDUCED-2", "REDUCED-2"]
    assert [verdict.rule for verdict in verdicts] == ["2oo3", "1oo2", "1oo2"]
    assert verdicts[1].members == ("fake-alpha", "fake-beta") and all(not vote.cached for verdict in verdicts for vote in verdict.votes)
    # Three claim calls each to alpha and beta (claim 2's pairs were held in memory: no second call), one alignment call each.
    assert (adapters["fake-alpha-v1"].calls, adapters["fake-beta-v1"].calls, adapters["fake-gamma-v1"].calls) == (4, 4, 2)
    block = entry.verification.v2
    assert block.degraded_mode == "REDUCED-2" and "degraded" in entry.verification.labels and block.banner == "degraded-reduced-2-v1"


@pytest.mark.parametrize("switch", ["abstain_only", "pre_verified_only"])
def test_a_kill_switch_runs_the_zero_path_with_no_call(switch):
    registry = make_registry(FOUR)
    adapters = adapters_of(registry)
    settings = Settings(model_gateway="on", model_gateway_kill_switch=switch)
    entry = run(v2_pipeline(settings, gateway=fresh_gateway(adapters=adapters), registry=registry), TIER2, legacy_decision="answer").entry
    verification = entry.verification
    assert all(adapter.calls == 0 for adapter in adapters.values()) and verification.v2.calls == 0
    assert all(verdict.mode == "ZERO" and verdict.outcome == "withheld" and not verdict.votes for verdict in judged(entry).values())
    assert (verification.final, verification.final_reason, verification.replacement) == ("withhold", "v2_kill_switch", "extractive_d19")
    assert verification.v2.kill_switch == switch and verification.v2.banner == "degraded-zero-v1"


def test_the_alignment_item_fails_when_any_member_flags_leakage_and_ratings_never_gate():
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    low = adapters_of(registry, **{"fake-beta-v1": {"alignment": {"rating": 1, "leakage": False}}})
    entry = run(v2_pipeline(gateway=fresh_gateway(adapters=low), registry=registry), TIER2).entry
    assert entry.verification.v2.alignment.outcome == "pass" and entry.verification.final == "deliver"
    assert [vote.rating for vote in entry.verification.v2.alignment.votes] == [4, 1, 4]
    leaky = adapters_of(registry, **{"fake-gamma-v1": {"alignment": {"rating": 5, "leakage": True}}})
    entry = run(v2_pipeline(gateway=fresh_gateway(adapters=leaky), registry=registry), TIER2).entry
    assert entry.verification.v2.alignment.outcome == "fail" and entry.verification.final_reason == "v2_alignment_failed"


def test_the_track_computes_the_tier_from_the_assessment_context():
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    tier_1 = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters_of(registry)), registry=registry), MULTI_CLAIM).entry
    tier_2 = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters_of(registry)), registry=registry), TIER2).entry
    assert {verdict.tier for verdict in judged(tier_1).values()} == {1} and {verdict.rule for verdict in judged(tier_1).values()} == {"1oo3"}
    assert {verdict.tier for verdict in judged(tier_2).values()} == {2} and {verdict.rule for verdict in judged(tier_2).values()} == {"2oo3"}


def test_with_no_member_left_for_the_alignment_item_the_claims_are_withheld():
    # Every member answers the three claim items, then fails the alignment item (its fourth call): no alignment verdict
    # exists, so no claim is delivered; each would-be-delivered claim is withheld and queued (conflict 34).
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    adapters = adapters_of(registry, **{spec.adapter_id: {"fail_calls": {4}} for spec in registry.members})
    entry = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=registry), TIER2, legacy_decision="answer").entry
    verification = entry.verification
    assert {verdict.outcome for verdict in judged(entry).values()} == {"pass"} and verification.v2.alignment is None
    assert (verification.final, verification.final_reason, verification.replacement) == ("withhold", "v2_degraded_withheld", "extractive_d19")
    assert all(verdict.final == "withhold" and "v2_degraded_withheld" in verdict.v3.reasons for verdict in verification.verdicts)


def test_each_shadow_budget_stop_logs_its_own_event_and_message(caplog):
    # The V2 track's budget stop (step "verify") is the V2 panel's, not the V1 track's (Phase 5 spec 4.12, 10.4).
    import logging

    from v1_fakes import dev_pipeline

    pipeline = dev_pipeline()
    started = pipeline.clock() - 10.0
    with caplog.at_level(logging.WARNING, logger="qcai.tutor"):
        for event, step in (("tutor.two_pass.budget_exceeded", "render"), ("tutor.v1.budget_exceeded", "bind"), ("tutor.v2.budget_exceeded", "verify")):
            assert pipeline._over(started, 1000, step, event=event) is True
        assert pipeline._over(pipeline.clock(), 1000, "verify", event="tutor.v2.budget_exceeded") is False
    lines = [(record.getMessage(), record.json_fields["event"], record.json_fields["step"]) for record in caplog.records]
    assert lines == [("Two-pass shadow exceeded its budget", "tutor.two_pass.budget_exceeded", "render"),
                     ("The shadow V1 track exceeded its budget", "tutor.v1.budget_exceeded", "bind"),
                     ("The V2 panel exceeded the shadow budget", "tutor.v2.budget_exceeded", "verify")]
