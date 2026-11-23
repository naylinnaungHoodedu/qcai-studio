"""Phase 5 acceptance: the provider-neutral gateway and the V2 panel (plan Phase 5 K AC-5-1 to AC-5-11, and its D, E, F, G,
H, I, L and P rows; plan 7.8 invariants 3, 4, 6, 10; plan 13.6; docs/architecture/phase5-implementation-spec.md 13.1).

Every model call here goes to a deterministic fake family (no network: conftest's guard refuses a non-loopback socket),
and the HTTP adapter runs only over httpx.MockTransport. Learner ids are uuid4 demo ids. Security events are read in seq
order.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib.util
import itertools
import json
import logging
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import traceback
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.config_package import DEFAULT_PACKAGE_PATH, ConfigPackageError, get_config_package, parse_config_package
from app.core.db import SessionLocal
from app.db_models import ResponseLedgerRecord, SecurityEvent
from app.gateway.adapters import AdapterError, HttpJsonAdapter
from app.gateway.budget import DailyBudget
from app.gateway.contracts import AlignmentInstructions, AlignmentRequest, ReadabilityBand, VerdictInstructions, VerdictRequest, VerdictSpan
from app.gateway.embeddings import EMBEDDING_PROBLEMS
from app.gateway.gateway import GatewayStopped, ModelGateway, get_gateway
from app.gateway.policy import PolicyContext
from app.gateway.registry import AdapterRegistry, registry_for
from app.gateway.tools import ToolHost
from app.main import app
from app.services import ledger
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline.contracts import LedgerEntryV2, LedgerEntryV3, V2ClaimVerdict, VerificationRecord, VerificationRecordV2
from app.services.tutor_pipeline.evidential import ExtractiveD19Generator
from app.services.v2_panel import rules
from app.services.v2_panel.panel import Panel, PanelError
from app.services.v2_panel.voting import family_verdict, tally
from tutor_fakes import ScriptedGenerator
from v1_fakes import MULTI_CLAIM, RaisingChecker, SupportedVoter, dev_pipeline, run, temp_package
from v2_fakes import (
    FAMILIES,
    FakeAlphaGenerator,
    FakeSecretStore,
    FamilyGenerator,
    RevisingGenerator,
    adapters_of,
    captured,
    claim_key,
    fake_spec,
    fresh_gateway,
    make_registry,
    v2_pipeline,
)

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
SPEC_PATH = REPO_ROOT / "docs" / "architecture" / "phase5-implementation-spec.md"


def spec_text() -> str:
    return SPEC_PATH.read_text(encoding="utf-8")


PACKAGE = get_config_package(Settings())
client = TestClient(app)
TIER2 = "Why do the sources repeatedly emphasize hybrid loops instead of end-to-end quantum models?"
TWO_CLAIMS = "What problem does SAC solve inside the augmented Lagrangian workflow?"
DATA = json.loads((API_ROOT / "tests" / "data" / "score_floor_queries.json").read_text(encoding="utf-8"))
OFF_TOPIC = list(DATA["off_topic"])
THREE = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
FOUR = make_registry(FAMILIES)


def demo(prefix: str) -> dict[str, str]:
    return {"x-demo-user": f"{prefix}-{uuid4().hex[:12]}", "x-demo-role": "learner", "x-forwarded-for": f"phase5-{uuid4().hex}"}


def fresh(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "x-forwarded-for": f"phase5-{uuid4().hex}"}


def judged(entry) -> dict:
    return {verdict.claim_id: verdict.v2 for verdict in entry.verification.verdicts if verdict.v2 is not None}


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"phase5_{name}", REPO_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def security_events(event_type: str, after: int = 0) -> list[SecurityEvent]:
    with SessionLocal() as db:
        return list(db.scalars(select(SecurityEvent).where(SecurityEvent.seq > after, SecurityEvent.event_type == event_type).order_by(SecurityEvent.seq)))


def last_security_seq() -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(func.max(SecurityEvent.seq))) or 0)


def contradicting(registry: AdapterRegistry, claim, members=None) -> dict:
    script = {claim_key(claim.text, span_id): ("CONTRADICTED", "A") for span_id in claim.span_ids}
    chosen = members or [spec.adapter_id for spec in registry.members]
    return adapters_of(registry, **{adapter_id: {"script": script} for adapter_id in chosen})


@pytest.fixture(scope="module")
def fixture_report():
    return load_script("run_v2_fixtures").compute(commit_source=lambda: "test")


# ======================================================================================================== AC-5-1


def test_ac_5_1_the_panel_never_holds_the_generator_s_family_for_any_registry_ordering():
    families = ("fa", "fb", "fc", "fd")
    registries = checked = 0
    for size in range(1, 6):
        for order in itertools.product(families, repeat=size):
            registries += 1
            specs = [fake_spec(family, adapter_id=f"{family}-{index}") for index, family in enumerate(order)]
            for eligible_mask in itertools.product((True, False), repeat=min(3, size)):
                eligible = [spec for index, spec in enumerate(specs) if index >= 3 or eligible_mask[index]]
                for generator in (*families, "outside"):
                    panel = Panel.build(eligible, generator_family=generator)
                    held = [member.family for member in panel.members]
                    assert generator not in held and len(held) == len(set(held)) and len(held) <= 3
                    expected, taken = [], set()
                    for spec in eligible:
                        if spec.family != generator and spec.family not in taken and len(expected) < 3:
                            taken.add(spec.family)
                            expected.append(spec.adapter_id)
                    assert [member.adapter_id for member in panel.members] == expected
                    checked += 1
    assert registries == 1364 and checked > 50000


def test_ac_5_1_a_panel_with_the_generator_s_family_cannot_be_built_or_recorded():
    with pytest.raises(PanelError):
        Panel(generator_family="fake-alpha", members=(fake_spec("fake-alpha"),))
    vote = {"verifier_model_id": "m", "verifier_model_version": "2026-11-21", "family": "fake-alpha", "verifier_prompt_hash": "0" * 64,
            "verdict": "SUPPORTED", "ehmf_type": None, "span_id": "span-" + "a" * 64, "cached": False}
    with pytest.raises(ValidationError, match="generator's family"):
        V2ClaimVerdict(tier=2, rule="withhold-queue-v3", generator_family="fake-alpha", mode="REDUCED-1", members=("fake-alpha",), votes=(vote,),
                       objections=0, split=False, outcome="withheld", cycle=0)
    registry = make_registry(FAMILIES, generator_family="fake-alpha")
    adapters = adapters_of(registry)
    generator = FakeAlphaGenerator(ExtractiveD19Generator(PACKAGE))
    entry = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=registry, generator=generator), TIER2).entry
    block = entry.verification.v2
    assert block.generator_family == "fake-alpha" and block.members == ("fake-beta", "fake-delta", "fake-gamma")
    assert adapters["fake-alpha-v1"].calls == 0 and all(vote.family != "fake-alpha" for verdict in judged(entry).values() for vote in verdict.votes)
    payload = entry.verification.model_dump(mode="json")
    payload["v2"]["members"] = sorted(["fake-alpha", *payload["v2"]["members"][:2]])
    with pytest.raises(ValidationError, match="excludes the generator"):
        VerificationRecordV2.model_validate(payload)
    # An unknown generator family fails closed: no panel, every eligible claim withheld, no call.
    unknown = FamilyGenerator(ExtractiveD19Generator(PACKAGE), "unregistered-generator")
    adapters = adapters_of(THREE)
    entry = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=THREE, generator=unknown), TIER2).entry
    assert entry.verification.v2.members == () and all(adapter.calls == 0 for adapter in adapters.values())
    assert {verdict.outcome for verdict in judged(entry).values()} == {"withheld"} and entry.verification.final == "withhold"


# ======================================================================================================== AC-5-2


def test_ac_5_2_two_verifiers_of_one_family_yield_one_vote():
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"), duplicate="fake-beta")
    adapters = adapters_of(registry)
    entry = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=registry), TIER2).entry
    assert entry.verification.v2.members == ("fake-alpha", "fake-beta", "fake-gamma") and adapters["fake-beta-2"].calls == 0
    for verdict in judged(entry).values():
        assert [vote.family for vote in verdict.votes].count("fake-beta") == len({vote.span_id for vote in verdict.votes})
        assert len(verdict.members) == 3
    adapters = adapters_of(registry)
    settings = Settings(model_gateway="on", model_gateway_disabled_adapters=["fake-beta-1"])
    entry = run(v2_pipeline(settings, gateway=fresh_gateway(adapters=adapters), registry=registry), TIER2).entry
    assert adapters["fake-beta-1"].calls == 0 and adapters["fake-beta-2"].calls > 0 and "fake-beta" in entry.verification.v2.members
    verdict = next(iter(judged(entry).values())).model_dump(mode="json")
    verdict["votes"] = [verdict["votes"][1], dict(verdict["votes"][1])]
    with pytest.raises(ValidationError, match="one vote per family and span"):
        V2ClaimVerdict.model_validate(verdict)


# ======================================================================================================== AC-5-3

FORBIDDEN_KEYS = {"vote", "votes", "verdict_of", "family", "generator", "model"}


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _keys(item)}
    return set()


def test_ac_5_3_captured_verifier_prompts_hold_no_generator_identity_votes_learner_ids_text_or_history():
    gateway = get_gateway()
    marker = f"marker{uuid4().hex[:10]}"
    first_question = f"Why does routing depth matter on sparse hardware {marker}?"
    texts, ids = [first_question], []
    with captured(gateway) as requests:
        for path in ("/assistant/chat", "/tutor/turns"):
            headers = demo("p5-capture")
            first = client.post(path, json={"message": first_question}, headers=fresh(headers)).json()
            follow = "And why does it matter for compilation?"
            second = client.post(path, json={"message": follow, "thread_id": first["thread_id"]}, headers=fresh(headers)).json()
            assert first.get("turn_id") and second.get("turn_id"), (first, second)
            texts.append(follow)
            ids += [headers["x-demo-user"], first["thread_id"], first["turn_id"], second["turn_id"]]
        for query in (TIER2, MULTI_CLAIM):
            pipeline = v2_pipeline(gateway=gateway, registry=registry_for(PACKAGE, Settings()))
            result = run(pipeline, query)
            texts.append(query)
            ids += [result.entry.response_id, result.entry.shadowed_response_id, *result.entry.resolved_question.source_turn_ids]
    assert requests and {request.item for request in requests} == {"claim", "alignment"}
    others = [spec for spec in registry_for(PACKAGE, Settings()).members]
    for request in requests:
        payload = request.model_dump(mode="json")
        text = json.dumps(payload)
        assert not (_keys(payload) & FORBIDDEN_KEYS), _keys(payload) & FORBIDDEN_KEYS
        for value in ("extractive-d19-v1", "extractive-d19", *(spec.adapter_id for spec in others), *(spec.model_id for spec in others)):
            assert value not in text, value
        for value in (*ids, *texts, marker):
            assert value not in text, value
        assert "@" not in text


def test_ac_5_3_objective_and_band_appear_only_in_the_alignment_item_payload():
    pipeline = v2_pipeline(registry=THREE, gateway=fresh_gateway(adapters=adapters_of(THREE)))
    slug, lesson = next((slug, lesson) for slug, lesson in pipeline.store.lessons.items()
                        if run(pipeline, TIER2, lesson_slug=slug).rendered is not None)
    pipeline = v2_pipeline(registry=THREE, gateway=fresh_gateway(adapters=adapters_of(THREE)))  # a cold cache: every pair is a call
    with captured(pipeline.gateway) as requests:
        result = run(pipeline, TIER2, lesson_slug=slug)
    assert result.entry.verification.v2.alignment is not None
    claims = [request for request in requests if request.item == "claim"]
    alignments = [request for request in requests if request.item == "alignment"]
    assert claims and alignments
    for request in claims:
        payload = request.model_dump(mode="json")
        assert not ({"objective", "band"} & _keys(payload)) and lesson.summary not in json.dumps(payload)
    for request in alignments:
        assert request.objective == lesson.summary and request.band == ReadabilityBand(min_grade=PACKAGE.v1.readability_min,
                                                                                       max_grade=PACKAGE.v1.readability_max)


def test_ac_5_3_every_verifier_gets_the_same_prompt_and_tool_surface():
    gateway = fresh_gateway(adapters=adapters_of(THREE))
    pipeline = v2_pipeline(gateway=gateway, registry=THREE)
    pipeline.tool_host = ToolHost.default(pipeline, gateway)
    entries = [run(pipeline, query).entry for query in (TIER2, MULTI_CLAIM, TWO_CLAIMS)]
    with captured(gateway) as requests:
        entries.append(run(pipeline, "What makes a QC+AI claim plausible in the NISQ era?").entry)
    votes = [vote for entry in entries for verdict in judged(entry).values() for vote in verdict.votes]
    assert votes and {vote.verifier_prompt_hash for vote in votes} == {rules.verifier_prompt_hash()}
    assert {entry.verification.v2.tool_contract_version for entry in entries} == {"mcp-tools-v1"}
    assert len({request.instructions.model_dump_json() for request in requests if request.item == "claim"}) == 1
    fresh_votes = sum(1 for vote in votes if not vote.cached)
    assert pipeline.tool_host.calls[("verifier", "verification.verdict")] == fresh_votes
    assert pipeline.tool_host.calls[("verifier", "corpus.span_text")] == len(votes)


# ======================================================================================================== AC-5-4


def test_ac_5_4_one_objection_fails_tier_1_and_passes_tier_2_and_not_enough_info_objects():
    for objection in ("CONTRADICTED", "NOT_ENOUGH_INFO"):
        assert tally("1oo3", ["SUPPORTED", "SUPPORTED", objection]) == "fail" and tally("2oo3", ["SUPPORTED", "SUPPORTED", objection]) == "pass"
    for query, tier, expected in ((MULTI_CLAIM, 1, "fail"), (TIER2, 2, "pass")):
        claim = run(dev_pipeline(), query).locked.claims[0]
        for objection in ("CONTRADICTED", "NOT_ENOUGH_INFO"):
            script = {claim_key(claim.text, span_id): (objection, "A") for span_id in claim.span_ids}
            adapters = adapters_of(THREE, **{"fake-gamma-v1": {"script": script}})
            entry = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=THREE), query).entry
            verdict = judged(entry)[claim.claim_id]
            assert (verdict.tier, verdict.outcome, verdict.objections) == (tier, expected, 1), (query, objection)
            final = {item.claim_id: item.final for item in entry.verification.verdicts}[claim.claim_id]
            assert final == ("abstain" if expected == "fail" else "deliver")


# ======================================================================================================== AC-5-5


def test_ac_5_5_a_v1_hard_fail_or_abstention_makes_no_gateway_call():
    clean = [(claim.text, list(claim.span_ids)) for claim in run(dev_pipeline(), MULTI_CLAIM).plan.claims]
    forged = [(clean[0][0], ["span-" + "e" * 64]), *clean[1:]]
    cases = (
        ("hard fail", MULTI_CLAIM, {"generator": ScriptedGenerator([forged])}),
        ("V1.5 abstain", OFF_TOPIC[0], {}),
        ("checker unavailable", MULTI_CLAIM, {"checker": RaisingChecker()}),
    )
    for name, query, options in cases:
        adapters = adapters_of(THREE)
        entry = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=THREE, **options), query).entry
        verification = entry.verification
        assert all(adapter.calls == 0 for adapter in adapters.values()), name
        assert all(verdict.v2 is None for verdict in verification.verdicts) and not verification.v2.panel_reached, name
        assert verification.final == "abstain" and verification.v2.calls == 0, name
    assert verification.final_reason == "checker_unavailable"


# ======================================================================================================== AC-5-6


@pytest.mark.parametrize("down, mode, banner", [
    ((), "FULL", None),
    (("fake-gamma-v1", "fake-delta-v1"), "REDUCED-2", "degraded-reduced-2-v1"),
    (("fake-beta-v1", "fake-gamma-v1", "fake-delta-v1"), "REDUCED-1", "degraded-reduced-1-v1"),
    (("fake-alpha-v1", "fake-beta-v1", "fake-gamma-v1", "fake-delta-v1"), "ZERO", "degraded-zero-v1"),
])
def test_ac_5_6_fault_injection_one_two_and_three_providers_down(down, mode, banner):
    adapters = adapters_of(FOUR, **{adapter_id: {"down": True} for adapter_id in down})
    entry = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=FOUR), TIER2, legacy_decision="answer").entry
    verification = entry.verification
    verdicts = judged(entry).values()
    assert {verdict.mode for verdict in verdicts} == {mode} and verification.v2.degraded_mode == mode
    assert verification.v2.banner == banner and (("degraded" in verification.labels) == (banner is not None))
    rule = rules.RULE_MATRIX[mode][2]
    assert {verdict.rule for verdict in verdicts} == {rule}
    if mode in ("FULL", "REDUCED-2"):
        assert {verdict.outcome for verdict in verdicts} == {"pass"} and verification.final == "deliver"
    else:
        # D-29 (a): REDUCED-1 withholds and queues tiers 1 and 2; ZERO withholds and queues every claim; no call either way.
        assert {verdict.outcome for verdict in verdicts} == {"withheld"} and all(not verdict.votes for verdict in verdicts)
        assert all(adapter.calls == 0 for adapter in adapters.values())
        assert (verification.final, verification.final_reason, verification.replacement) == ("withhold", "v2_degraded_withheld", "extractive_d19")
        assert all("v2_degraded_withheld" in verdict.v3.reasons and verdict.v3.escalation is None for verdict in verification.verdicts)
    if mode == "REDUCED-1":
        # A tier-3 claim follows its rule (equal weights) on the remaining verifier (an in-memory overlay: no shipped tier 3).
        pipeline = v2_pipeline(gateway=fresh_gateway(adapters=adapters_of(FOUR, **{adapter_id: {"down": True} for adapter_id in down})),
                               registry=FOUR)
        pipeline.package = dataclasses.replace(pipeline.package, v2=dataclasses.replace(pipeline.package.v2, default_tier=3))
        tier3 = run(pipeline, TIER2).entry
        assert {(verdict.tier, verdict.rule, verdict.outcome, len(verdict.votes)) for verdict in judged(tier3).values()} == {
            (3, "equal-weights-share-v1", "pass", 1)} and tier3.verification.final == "deliver"


def test_ac_5_6_a_mid_response_loss_and_each_kill_switch():
    adapters = adapters_of(THREE, **{"fake-beta-v1": {"fail_calls": {1}}})
    entry = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=THREE), TIER2).entry
    assert [verdict.mode for verdict in judged(entry).values()] == ["REDUCED-2"] * 3
    assert all(not vote.cached for verdict in judged(entry).values() for vote in verdict.votes)
    outcomes = {}
    for switch in ("abstain_only", "pre_verified_only"):
        adapters = adapters_of(THREE)
        settings = Settings(model_gateway="on", model_gateway_kill_switch=switch, ehmf="off")  # the v3 record this test judges (Phase 7)
        entry = run(v2_pipeline(settings, gateway=fresh_gateway(adapters=adapters), registry=THREE), TIER2, legacy_decision="answer").entry
        verification = entry.verification
        assert verification.final_reason == "v2_kill_switch" and all(adapter.calls == 0 for adapter in adapters.values())
        assert (verification.v2.kill_switch, verification.v2.degraded_mode, verification.v2.calls) == (switch, "ZERO", 0)
        outcomes[switch] = (verification.final, verification.replacement, verification.v2.banner, entry.decision,
                            sorted((verdict.final, verdict.v2.outcome if verdict.v2 else None) for verdict in verification.verdicts))
        # The record's rules: a kill switch abstains with v2_kill_switch, and only a kill switch gives that reason.
        payload = verification.model_dump(mode="json")
        withheld = {**payload, "final": "withhold", "replacement": "extractive_d19",
                    "verdicts": [{**verdict, "final": "withhold"} for verdict in payload["verdicts"]]}
        with pytest.raises(ValidationError, match="a kill switch abstains"):
            VerificationRecordV2.model_validate(withheld)
        with pytest.raises(ValidationError, match="only a kill switch gives the reason v2_kill_switch"):
            VerificationRecordV2.model_validate({**payload, "v2": {**payload["v2"], "kill_switch": "none"}})
    # Plan 13.6 "abstain-only, pre-verified-only" and plan 5.11 "pre-verified module content (stage 4) or abstain and
    # queue": abstain-only abstains whatever the legacy decision was (here an answer), and no pre-verified store exists
    # (v4 v2.degraded.pre_verified_source is null, DI-83), so pre-verified-only abstains and queues too: the two records
    # differ only in the switch they name, and every claim abstains with its V2 withholding queued (spec 4.10).
    assert PACKAGE.v2.pre_verified_source is None
    assert outcomes["abstain_only"] == outcomes["pre_verified_only"]
    assert outcomes["abstain_only"][:4] == ("abstain", "none", "degraded-zero-v1", "abstain")
    assert {final for final, _ in outcomes["abstain_only"][4]} == {"abstain"}


def _store_down(*args, **kwargs):
    from sqlalchemy.exc import OperationalError

    raise OperationalError("SELECT 1", {}, Exception("database unavailable"))


@pytest.mark.parametrize("mode", ["on", "shadow"])
def test_ac_5_6_a_shared_store_failure_fails_closed_and_every_response_keeps_its_ledger_record(mode, monkeypatch, caplog):
    # Plan P "ledger verdicts for 100% of test responses (F-1)" and fault injection (plan J): a database fault in the
    # process gateway's shared budget (DatabaseBudget) or the shared cache (DatabaseEvidentialCache) never escapes the V2
    # track. A budget that cannot be read makes every member ineligible, and one that cannot be written makes each member
    # unavailable at its first call, so the response runs on to ZERO and keeps its record; a cache that cannot be read or
    # written is a miss. No case stops the gateway.
    from app.gateway.controls import DatabaseBudget
    from app.services.retrieval_engine import RetrievalEngine
    from app.services.store import get_course_store
    from app.services.tutor_pipeline.pipeline import TwoPassPipeline
    from app.services.v2_panel import cache as cache_module

    caplog.set_level(logging.WARNING)
    settings = Settings(model_gateway=mode)

    def pipeline():  # the process gateway and the process cache, as the shadow runner builds them
        return TwoPassPipeline(RetrievalEngine(get_course_store(), settings), settings)

    with SessionLocal() as db:
        before = int(db.scalar(select(func.max(ResponseLedgerRecord.seq))) or 0)
    entries = {}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(DatabaseBudget, "remaining", _store_down)
        entries["unreadable budget"] = run(pipeline(), TIER2, legacy_decision="answer", record=True).entry
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(DatabaseBudget, "reserve", _store_down)
        entries["unwritable budget"] = run(pipeline(), TIER2, legacy_decision="answer", record=True).entry
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cache_module, "_engine", _store_down)
        entries["cache down"] = run(pipeline(), TIER2, legacy_decision="answer", record=True).entry
    # Unreadable: no member is eligible (ZERO). Unwritable: each member called is refused before it is sent and leaves
    # the panel, so the claims are withheld with no call once the rule withholds (REDUCED-1, tier 2).
    for case, modes in (("unreadable budget", {"ZERO"}), ("unwritable budget", {"REDUCED-1"})):
        verification = entries[case].verification
        assert {verdict.mode for verdict in judged(entries[case]).values()} == modes and verification.v2.calls == 0, case
        assert {verdict.outcome for verdict in judged(entries[case]).values()} == {"withheld"}, case
        assert verification.final == "withhold" and verification.v2.gateway_state == "open", case
    cached = entries["cache down"].verification
    assert {verdict.mode for verdict in judged(entries["cache down"]).values()} == {"FULL"} and cached.v2.calls > 0
    assert cached.v2.cache_hits == 0 and cached.final == ("deliver" if mode == "on" else "withhold")
    with SessionLocal() as db:
        recorded = list(db.scalars(select(ResponseLedgerRecord.response_id).where(ResponseLedgerRecord.seq > before)))
    assert sorted(recorded) == sorted(entry.response_id for entry in entries.values())  # F-1: every response has its record
    events = [getattr(record, "json_fields", {}).get("event") for record in caplog.records]
    assert "gateway.budget_unavailable" in events and "tutor.v2.cache_unavailable" in events and "gateway.stopped" not in events
    assert get_gateway().state == "open"


def test_ac_5_6_the_degraded_banners_claim_no_check_the_learner_does_not_get():
    # Plan 5.9 "with visible banner": a banner names what the learner gets. With no pre-verified source the ZERO path
    # withholds and queues, and the learner gets the D-19 answer (verbatim approved passages) or an abstention, never
    # checked content; no banner says grounded (D-19: grounded is always false).
    banners = PACKAGE.v2.banners
    assert set(banners) == set(rules.BANNER_IDS) and PACKAGE.v2.pre_verified_source is None
    zero = set(re.findall(r"[a-z]+", banners["degraded-zero-v1"].lower()))
    assert "quoted course passages or no answer" in banners["degraded-zero-v1"] and not ({"checked", "verified", "grounded"} & zero)
    assert all("grounded" not in text.lower() for text in banners.values())


# ======================================================================================================== AC-5-7


def test_ac_5_7_a_claim_failing_two_correction_cycles_is_abstained_and_marked_x2():
    claims = run(dev_pipeline(), TIER2).locked.claims
    generator = RevisingGenerator(ExtractiveD19Generator(PACKAGE))
    with SessionLocal() as db:
        before = int(db.scalar(select(func.max(ResponseLedgerRecord.seq))) or 0)
    result = run(v2_pipeline(gateway=fresh_gateway(adapters=contradicting(THREE, claims[1])), registry=THREE, generator=generator), TIER2,
                 record=True)
    verification = result.entry.verification
    by_id = {verdict.claim_id: verdict for verdict in verification.verdicts}
    failed = by_id[claims[1].claim_id]
    assert verification.v2.cycles == 2 and failed.final == "abstain" and failed.v3.escalation == "X2"
    assert len(generator.revised) == 2 and verification.final == "deliver"
    with SessionLocal() as db:
        intents = [item for item in ledger.pending_v3_intents(db, after_seq=before) if item["claim_id"] == claims[1].claim_id]
    assert intents and intents[0]["escalation"] == "X2" and "v2_correction_exhausted" in intents[0]["reasons"]
    # The extractive generator cannot revise: the failed claim is re-verified unchanged (every pair a cache hit).
    adapters = contradicting(THREE, claims[1])
    entry = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=THREE), TIER2).entry
    assert all(adapter.calls == len(claims) + 1 for adapter in adapters.values())
    assert {item.claim_id: item.final for item in entry.verification.verdicts}[claims[1].claim_id] == "abstain"


def test_ac_5_7_a_type_e_objection_re_renders_only():
    generator = RevisingGenerator(ExtractiveD19Generator(PACKAGE))
    adapters = adapters_of(THREE, **{"fake-beta-v1": {"alignment": {"rating": 3, "leakage": True}}})
    result = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=THREE, generator=generator), TIER2)
    verification = result.entry.verification
    assert generator.proposals == 1 and generator.revised == []  # no new claim plan
    assert [item.kind for item in verification.v2.corrections] == ["re_render", "re_render"]
    assert verification.final_reason == "v2_alignment_failed" and result.decision == "abstain"
    assert result.entry.presentation.plan_id == "socratic"


def test_ac_5_7_a_claim_level_type_e_objection_is_re_rendered_and_never_revised():
    # Plan 5.8 "Type E re-renders only": every member objects to one claim with EHMF type E (presentation).
    claims = run(dev_pipeline(), TIER2).locked.claims
    assert len(claims) >= 3

    def scripted(claim, verdict, ehmf):
        return {claim_key(claim.text, span_id): (verdict, ehmf) for span_id in claim.span_ids}

    generator = RevisingGenerator(ExtractiveD19Generator(PACKAGE))
    adapters = adapters_of(THREE, **{spec.adapter_id: {"script": scripted(claims[1], "NOT_ENOUGH_INFO", "E")} for spec in THREE.members})
    result = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=THREE, generator=generator), TIER2)
    verification = result.entry.verification
    assert [(item.kind, item.failed_claim_ids, item.revised_claim_ids) for item in verification.v2.corrections] == [
        ("re_render", (claims[1].claim_id,), ())] * 2
    assert generator.revised == [] and generator.proposals == 1  # re-rendered twice, never revised, no new plan
    by_id = {item.claim_id: item for item in verification.verdicts}
    assert by_id[claims[1].claim_id].final == "abstain" and by_id[claims[1].claim_id].v3.escalation == "X2"
    assert verification.final == "deliver" and result.entry.presentation.plan_id == "socratic"
    # A type E objection beside a type A one is a content fault: the claim is revised, given the type A (family order).
    generator = RevisingGenerator(ExtractiveD19Generator(PACKAGE))
    mixed = {"fake-alpha-v1": {"script": scripted(claims[1], "NOT_ENOUGH_INFO", "E")},
             "fake-beta-v1": {"script": scripted(claims[1], "CONTRADICTED", "A")},
             "fake-gamma-v1": {"script": scripted(claims[1], "NOT_ENOUGH_INFO", "E")}}
    result = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters_of(THREE, **mixed)), registry=THREE, generator=generator), TIER2)
    assert [item.kind for item in result.entry.verification.v2.corrections] == ["revise", "revise"]
    assert generator.revised == [(claims[1].text, "A")] * 2
    # One cycle with a presentation-only claim and a content claim revises the content claim only.
    generator = RevisingGenerator(ExtractiveD19Generator(PACKAGE))
    both = {spec.adapter_id: {"script": {**scripted(claims[1], "NOT_ENOUGH_INFO", "E"), **scripted(claims[2], "CONTRADICTED", "B")}}
            for spec in THREE.members}
    result = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters_of(THREE, **both)), registry=THREE, generator=generator), TIER2)
    corrections = result.entry.verification.v2.corrections
    assert [item.kind for item in corrections] == ["revise", "revise"]
    assert all(set(item.failed_claim_ids) == {claims[1].claim_id, claims[2].claim_id} for item in corrections)
    assert generator.revised == [(claims[2].text, "B")] * 2


# ======================================================================================================== AC-5-8


def test_ac_5_8_a_repeated_claim_span_pair_hits_the_cache_and_a_configuration_bump_misses(tmp_path):
    from app.services.v2_panel.cache import ProcessEvidentialCache

    cache = ProcessEvidentialCache()
    adapters = adapters_of(THREE)
    pipeline = v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=THREE, cache=cache)
    first = run(pipeline, TIER2).entry
    calls = {name: adapter.calls for name, adapter in adapters.items()}
    second = run(pipeline, TIER2).entry
    assert all(not vote.cached for verdict in judged(first).values() for vote in verdict.votes)
    assert all(vote.cached for verdict in judged(second).values() for vote in verdict.votes)
    assert {name: adapter.calls - calls[name] for name, adapter in adapters.items()} == {name: 1 for name in adapters}  # alignment only
    bumped = temp_package(tmp_path, edit=lambda raw: raw.update(package_version="6.0.1"))  # a bump within the shipped major (v6, Phase 7)
    settings = Settings(model_gateway="on", config_package_path=str(bumped))
    other = v2_pipeline(settings, gateway=fresh_gateway(adapters=adapters), registry=THREE, cache=cache)
    assert other.package.sha256 != pipeline.package.sha256
    third = run(other, TIER2).entry
    assert all(not vote.cached for verdict in judged(third).values() for vote in verdict.votes)


# ======================================================================================================== AC-5-9

KEY = f"provider-key-{uuid4().hex}"


def _http_gateway(responses):
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = responses[min(len(seen) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item() if callable(item) else item  # a factory builds a response the client decodes only on receipt

    spec = fake_spec("test-family", provider="test-provider", endpoint="https://verifier.invalid/v1/verdicts", auth_header="authorization-bearer",
                     secret_ref="TEST_PROVIDER_KEY", max_retries=1)
    adapter = HttpJsonAdapter(spec, secret_store=FakeSecretStore({"TEST_PROVIDER_KEY": KEY}), transport=httpx.MockTransport(handler),
                              sleep=lambda seconds: None)
    return spec, fresh_gateway(adapters={spec.adapter_id: adapter}), seen


@pytest.mark.parametrize("responses", [
    [httpx.Response(401, json={"error": f"invalid key {KEY}"})],
    [httpx.Response(500)],
    [httpx.ReadTimeout("slow")],
    [httpx.Response(200, content=b"<html>not json</html>")],
    # A body the client cannot decode: httpx.DecodingError is a RequestError but no TransportError.
    [lambda: httpx.Response(200, headers={"content-encoding": "gzip"}, content=b"not gzip at all")],
])
def test_ac_5_9_a_provider_error_leaves_no_key_authorization_header_or_query_in_logs_or_exceptions(responses, caplog):
    pipeline = dev_pipeline()
    claim = run(pipeline, TIER2).locked.claims[0]
    record = pipeline.store.span_registry.get(claim.span_ids[0])
    request = VerdictRequest(claim_text=claim.text, span=VerdictSpan(span_id=record.span_id, text=record.text),
                             instructions=VerdictInstructions(prompt_hash=rules.verifier_prompt_hash(), tool_contract_version="mcp-tools-v1"))
    spec, gateway, seen = _http_gateway(responses)
    for name in ("", "httpx", "httpcore", "qcai.gateway"):
        caplog.set_level(logging.DEBUG, logger=name or None)
    with pytest.raises(AdapterError) as excinfo:
        gateway.verify(spec, request, context=PolicyContext(store=pipeline.store, corpus_registry=pipeline.registry))
    error = excinfo.value
    assert seen and seen[0].headers["authorization"] == f"Bearer {KEY}" and not seen[0].url.query
    assert error.__cause__ is None and error.__context__ is None
    # The formatted traceback from the gateway down (the test frame names this test, whose name says "authorization").
    rendered = [str(error), repr(error), "".join(traceback.format_tb(error.__traceback__.tb_next)) + "".join(traceback.format_exception_only(error))]
    lines = [record.getMessage() for record in caplog.records] + [json.dumps(getattr(record, "json_fields", {})) for record in caplog.records]
    for text in rendered + lines:
        assert KEY not in text and "Bearer" not in text and "Authorization" not in text and "authorization" not in text and "?" not in text
    assert gateway.state == "open"  # no gateway secret reached a log line
    with pytest.raises(ValueError, match="never travel in the URL"):
        HttpJsonAdapter(dataclasses.replace(spec, endpoint="https://verifier.invalid/v1?key=abc"), secret_store=FakeSecretStore({}))


def test_ac_5_9_calls_stop_at_the_daily_budget(caplog):
    caplog.set_level(logging.WARNING, logger="qcai.gateway")
    adapters = adapters_of(THREE)
    gateway = ModelGateway(budget=DailyBudget(5), adapters=adapters)
    pipeline = v2_pipeline(gateway=gateway, registry=THREE)
    assert len(run(dev_pipeline(), TWO_CLAIMS).locked.claims) == 2
    start = last_security_seq()
    entry = run(pipeline, TWO_CLAIMS).entry
    assert sum(adapter.calls for adapter in adapters.values()) == 5
    alerts = [record.json_fields for record in caplog.records if getattr(record, "json_fields", {}).get("event") == "gateway.budget_alert"]
    assert alerts == [{"event": "gateway.budget_alert", "share": "4/5", "daily_units": 5, "spent": 4}]
    assert (gateway.state, gateway.stop_reason) == ("stopped", "budget_breach")
    events = security_events("gateway.stopped", start)
    assert [(event.outcome, event.actor_role, event.details.get("reason")) for event in events] == [("denied", "system", "budget_breach")]
    modes = [verdict.mode for verdict in judged(entry).values()]
    assert modes == ["FULL", "ZERO"] and entry.verification.v2.gateway_state == "stopped"
    assert pipeline.v2_mode() == "off"
    after = run(pipeline, TWO_CLAIMS).entry
    assert after.entry_schema == "ledger-entry-v2" and sum(adapter.calls for adapter in adapters.values()) == 5


# ======================================================================================================= AC-5-10

UNPINNED = {
    "missing version": lambda member: member.pop("model_version"),
    "preview": lambda member: member.update(model_id="fake-alpha-preview"),
    "latest": lambda member: member.update(model_id="fake-alpha-latest"),
    "exp": lambda member: member.update(model_id="fake-alpha-exp"),
    "alias": lambda member: member.update(model_version="alias"),
    "non-pinned form": lambda member: member.update(model_version="stable-1"),
    "glued preview": lambda member: member.update(model_id="fakealpha3preview"),
    "glued latest": lambda member: member.update(model_id="fakealpha4latest"),
    "impossible date": lambda member: member.update(model_version="2026-13-45"),
    "unstripped version": lambda member: member.update(model_version=" 001 "),
}


def _package_copy(tmp_path: Path, edit) -> Path:
    """A copy of the shipped package (schemas included) with `edit` applied and its sidecar rewritten, unparsed."""
    import shutil

    from app.core.config_package import canonical_sha256

    raw = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
    edit(raw)
    path = tmp_path / "package" / DEFAULT_PACKAGE_PATH.name
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(DEFAULT_PACKAGE_PATH.parent / "schemas", path.parent / "schemas", dirs_exist_ok=True)
    path.write_text(json.dumps(raw), encoding="utf-8")
    path.with_name(DEFAULT_PACKAGE_PATH.name + ".sha256").write_text(canonical_sha256(raw) + "\n", encoding="utf-8")
    return path


def _startup(extra: dict[str, str]) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if key not in {"V1_PIPELINE", "CONFIG_PACKAGE_PATH", "ENFORCE_CORPUS_GOVERNANCE", "MODEL_GATEWAY"}}
    env.update({"PYTHONUNBUFFERED": "1", **extra})
    return subprocess.run([sys.executable, "-c", "from app.main import _initialize_database; _initialize_database()"], cwd=API_ROOT, env=env,
                          capture_output=True, text=True, timeout=240)


@pytest.mark.parametrize("name", sorted(UNPINNED))
def test_ac_5_10_an_unpinned_identifier_makes_start_up_fail(name, tmp_path, fresh_database_url):
    path = _package_copy(tmp_path, lambda raw: UNPINNED[name](raw["gateway"]["registries"]["development"][0]))
    raw = json.loads(path.read_text(encoding="utf-8"))
    with pytest.raises(ConfigPackageError, match="unpinned"):
        parse_config_package(raw, path=path, sha256="0" * 64, hash_verified=False)
    completed = _startup({"DATABASE_URL": fresh_database_url, "ENVIRONMENT": "development", "CONFIG_PACKAGE_PATH": str(path)})
    assert completed.returncode != 0 and "unpinned" in completed.stderr, completed.stderr[-500:]
    retired = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
    retired["gateway"]["registries"]["development"][0].update(model_id="gemini-3.1-flash-lite-preview", model_version="2026-01-01")
    with pytest.raises(ConfigPackageError, match="unpinned"):
        parse_config_package(retired, path=DEFAULT_PACKAGE_PATH, sha256="0" * 64, hash_verified=False)


def test_ac_5_10_an_unpinned_embedding_model_makes_start_up_fail(tmp_path, fresh_database_url):
    # The embedding egress's model is package v4's gateway.embeddings (PD-26), under the same pinning rule as every
    # registry member: an unpinned identifier there stops the load and start-up too.
    path = _package_copy(tmp_path, lambda raw: raw["gateway"]["embeddings"].update(model_id="text-embedding-3-small", model_version="latest"))
    completed = _startup({"DATABASE_URL": fresh_database_url, "ENVIRONMENT": "development", "CONFIG_PACKAGE_PATH": str(path)})
    assert completed.returncode != 0 and "gateway.embeddings is unpinned" in completed.stderr, completed.stderr[-500:]


# ======================================================================================================= AC-5-11


def test_ac_5_11_two_learners_share_only_evidential_entries_and_a_model_change_misses(monkeypatch):
    from app.services.tutor_pipeline.contracts import ClaimPlan
    from app.services.tutor_pipeline.render import TemplateRenderer
    from app.services.v2_panel.cache import get_cache

    renders = []
    real_render = TemplateRenderer.render
    monkeypatch.setattr(TemplateRenderer, "render", lambda self, *args, **kwargs: renders.append(1) or real_render(self, *args, **kwargs))
    cache = get_cache()
    learners = [demo("p5-cache-a"), demo("p5-cache-b")]
    bodies = []
    for index, headers in enumerate(learners):
        before = cache.snapshot()
        renders_before = len(renders)
        bodies.append(client.post("/tutor/turns", json={"message": TIER2}, headers=fresh(headers)).json())
        after = cache.snapshot()
        assert len(renders) > renders_before  # every learner's response is rendered, never served from the cache
        if index == 1:
            assert after["claim_plan"]["hits"] > before["claim_plan"]["hits"] and after["verdict"]["hits"] > before["verdict"]["hits"]
    values = cache.values("claim_plan") + cache.values("verdict")
    assert values and all(isinstance(value, (ClaimPlan, contracts.SCHEMA_MODELS["V2AdapterVerdict"])) for value in values)
    dumped = json.dumps([value.model_dump(mode="json") for value in values]) + json.dumps(cache.keys("claim_plan") + cache.keys("verdict"))
    for headers, body in zip(learners, bodies):
        assert headers["x-demo-user"] not in dumped and body["thread_id"] not in dumped and body["turn_id"] not in dumped
    assert TIER2 not in dumped and "These sentences are quoted" not in dumped
    # A model change misses: a registry whose fake-alpha names a new model version.
    changed = AdapterRegistry(name="development", members=tuple(
        dataclasses.replace(spec, model_version="2026-12-01") if spec.family == "fake-alpha" else spec for spec in THREE.members))
    adapters = adapters_of(changed)
    entry = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=changed, cache=cache), TIER2).entry
    votes = [vote for verdict in judged(entry).values() for vote in verdict.votes]
    assert all(not vote.cached for vote in votes if vote.family == "fake-alpha") and any(vote.cached for vote in votes if vote.family != "fake-alpha")
    # The same question under another lesson scope misses the claim-plan entry.
    pipeline = v2_pipeline(gateway=fresh_gateway(adapters=adapters_of(THREE)), registry=THREE, cache=cache)
    plans_before = cache.snapshot()["claim_plan"]
    slug = next(slug for slug in pipeline.store.lessons if run(pipeline, TIER2, lesson_slug=slug).envelope is not None)
    assert cache.snapshot()["claim_plan"]["misses"] > plans_before["misses"] and slug


# ========================================================================================================= plan P


def test_plan_p_f_1_every_fixture_response_carries_ledger_verdicts(fixture_report):
    assert fixture_report["result"] == "pass", fixture_report["problems"]
    names = [block["name"] for block in fixture_report["scenarios"]]
    assert names == ["all_up", "one_down", "two_down", "three_down"]
    for block, mode in zip(fixture_report["scenarios"], ("FULL", "REDUCED-2", "REDUCED-1", "ZERO")):
        assert block["responses"] == 298 and block["f1"]["rate"] == "298/298", block["name"]
        assert block["v2_after_v1_fail"] == 0 and block["deliver_without_pass"] == 0
        assert set(key for key, count in block["modes"].items() if count) == {mode}, block["name"]
    assert fixture_report["cache_pass"]["f1"]["rate"] == "298/298" and fixture_report["cache_pass"]["verdict_hits"] > 0
    assert fixture_report["cache_pass"]["claim_plan_hits"] > 0
    # Each scenario's calls are its claim items plus its alignment items (one per member and FULL-delivered response).
    for block in fixture_report["scenarios"]:
        assert block["calls"] == block["calls_by_item"]["claim"] + block["calls_by_item"]["alignment"], block["name"]
    all_up = fixture_report["scenarios"][0]
    assert all_up["calls_by_item"]["alignment"] == 3 * all_up["modes"]["FULL"]
    # The repeat pass casts every verdict from the cache: its only calls are the alignment items, which are never cached.
    cache_pass = fixture_report["cache_pass"]
    assert cache_pass["verdict_calls"] == 0 and cache_pass["alignment_calls"] == all_up["calls_by_item"]["alignment"]
    assert cache_pass["verdict_hits"] == all_up["calls_by_item"]["claim"]
    assert fixture_report["payload_fields"]["claim"] == ["claim_text", "instructions", "item", "request_schema", "span"]


def test_plan_p_the_committed_v2_fixture_report_matches_a_fresh_run_and_names_its_evidence_class(fixture_report):
    runner = load_script("run_v2_fixtures")
    committed = json.loads((REPO_ROOT / "docs" / "evaluation" / "phase5" / "v2_fixture_report_v1.json").read_text(encoding="utf-8"))

    def comparable(report):
        stripped = runner._strip_volatile(report)
        stripped.pop("inputs", None)  # inside a test process the imported-module map also holds what other tests imported
        return stripped

    assert comparable(committed) == comparable(fixture_report)
    # The record's module map matches the checkout, and every module it lists is one this run imported, unchanged
    # (`run_v2_fixtures.py --check`, a process of its own, compares the whole map).
    assert runner.input_problems(committed["inputs"]) == []
    fresh = fixture_report["inputs"]["files"]
    assert all(fresh.get(path) == digest for path, digest in committed["inputs"]["files"].items())
    assert committed["evidence_class"].startswith("fixture measurements, not research results") and committed["public_corpus_only"] is True
    assert committed["config_package"] == {"version": PACKAGE.package_version, "sha256": PACKAGE.sha256}
    assert runner.exit_code(dict(committed, result="breach")) == 5 and runner.exit_code(dict(committed, result="stop")) == 3


# ================================================================================================ plan G and L


def test_plan_g_model_gateway_defaults_and_refusals(monkeypatch, fresh_database_url):
    from app import main as main_module
    import app.gateway as gateway_package

    production = {"environment": "production", "allowed_origins": ["https://qantumlearn.academy"]}
    assert Settings().model_gateway == "shadow" and Settings(**production).model_gateway == "off"
    with pytest.raises(ValidationError, match="needs V1_PIPELINE=enforce"):
        Settings(model_gateway="on", v1_pipeline="shadow")
    with pytest.raises(ValidationError, match="needs V1_PIPELINE=enforce|phase4_exit_passed"):
        Settings(**production, model_gateway="on")
    exited = dataclasses.replace(PACKAGE, flag_policy=dataclasses.replace(PACKAGE.flag_policy, phase4_exit_passed=True, phase4_exit_evidence="x"))
    monkeypatch.setattr("app.core.config_package.get_config_package", lambda settings=None: exited)
    with pytest.raises(ValidationError, match="phase5_exit_passed"):
        Settings(**production, v1_pipeline="enforce", model_gateway="on")
    both = dataclasses.replace(exited, flag_policy=dataclasses.replace(exited.flag_policy, phase5_exit_passed=True, phase5_exit_evidence="y"))
    monkeypatch.setattr("app.core.config_package.get_config_package", lambda settings=None: both)
    allowed = Settings(**production, v1_pipeline="enforce", model_gateway="on")
    assert allowed.model_gateway == "on"
    recorded = []
    monkeypatch.setattr(main_module, "IS_PRODUCTION", True)
    monkeypatch.setattr(main_module, "settings", allowed)
    monkeypatch.setattr(main_module, "get_config_package", lambda _settings=None: both)
    monkeypatch.setattr(main_module, "record_security_event", lambda *args, **kwargs: recorded.append(kwargs["details"]))
    main_module._record_configuration_overrides()
    assert recorded and recorded[0].get("model_gateway_on") is True
    monkeypatch.undo()
    # A gateway package problem other than pinning stops a governed start-up only when the gateway is requested.
    broken = dataclasses.replace(PACKAGE, tools=dataclasses.replace(PACKAGE.tools, sha256="0" * 64))
    for requested, stops in (("shadow", True), ("off", False)):
        monkeypatch.setattr(main_module, "settings", Settings(enforce_corpus_governance=True, model_gateway=requested))
        try:
            if stops:
                with pytest.raises(ConfigPackageError, match="gateway: tools"):
                    main_module._check_gateway_package(broken)
            else:
                main_module._check_gateway_package(broken)
                assert gateway_package.GATEWAY_UNAVAILABLE_REASON is not None
                assert main_module._gateway_fields(PACKAGE)["available"] is False
                from app.services import v2_panel

                assert v2_panel.mode(Settings(), PACKAGE) == "off"
        finally:
            gateway_package.GATEWAY_UNAVAILABLE_REASON = None
    completed = _startup({"DATABASE_URL": fresh_database_url, "ENVIRONMENT": "production", "MODEL_GATEWAY": "on", "V1_PIPELINE": "shadow",
                          "ALLOWED_ORIGINS": "https://qantumlearn.academy", "GUEST_TOKEN_SECRET": "a-production-like-secret-of-sufficient-length"})
    assert completed.returncode != 0 and "MODEL_GATEWAY=on" in completed.stderr, completed.stderr[-500:]


def test_plan_l_flag_off_returns_to_phase_4(monkeypatch):
    import app.gateway.gateway as gateway_module
    import app.services.v2_panel.cache as cache_module

    def refuse(*args, **kwargs):
        raise AssertionError("with MODEL_GATEWAY off no gateway or cache is built or read")

    monkeypatch.setattr(gateway_module, "get_gateway", refuse)
    monkeypatch.setattr(cache_module, "get_cache", refuse)
    off = run(dev_pipeline(Settings(model_gateway="off")), MULTI_CLAIM, legacy_decision="answer").entry
    assert type(off) is LedgerEntryV2 and type(off.verification) is VerificationRecord
    voter = SupportedVoter()
    hooked = run(dev_pipeline(Settings(model_gateway="on"), v2_hook=voter), MULTI_CLAIM, legacy_decision="answer").entry
    assert type(hooked) is LedgerEntryV2 and voter.calls == 1
    for entry in (off, hooked):
        assert (entry.verification.final, entry.verification.final_reason, entry.verification.replacement) == (
            "withhold", "d20_interim_withhold", "extractive_d19")
    assert [verdict.final for verdict in off.verification.verdicts] == [verdict.final for verdict in hooked.verification.verdicts]


def test_plan_g_shadow_dual_run_records_v2_beside_the_unchanged_v1_decision(caplog):
    caplog.set_level(logging.INFO, logger="qcai.tutor")
    off = run(dev_pipeline(Settings(model_gateway="off")), TIER2, legacy_decision="answer").entry
    shadow = run(v2_pipeline(Settings(model_gateway="shadow"), gateway=fresh_gateway(adapters=adapters_of(THREE)), registry=THREE), TIER2,
                 legacy_decision="answer").entry
    # Since Phase 7 the development default (EHMF=shadow) types the shadow: a ledger-entry-v4, which extends v3.
    assert isinstance(shadow, LedgerEntryV3) and shadow.entry_schema == "ledger-entry-v4" and shadow.verification.v2.mode == "shadow"
    for name in ("final", "final_reason", "replacement", "labels"):
        assert getattr(shadow.verification, name) == getattr(off.verification, name), name
    assert [verdict.final for verdict in shadow.verification.verdicts] == [verdict.final for verdict in off.verification.verdicts]
    summary = shadow.verification.v2.shadow
    assert summary.would_deliver == len(judged(shadow)) and shadow.verification.v2.cycles == 0
    disagreements = [record.json_fields for record in caplog.records if getattr(record, "json_fields", {}).get("event") == "tutor.v2.disagreement"]
    assert disagreements == [{"event": "tutor.v2.disagreement", "v1_final": "withhold", "v2_would": "deliver"}]


def test_plan_l_a_payload_violation_stops_the_gateway_with_a_security_event():
    pipeline = dev_pipeline()
    result = run(pipeline, TIER2)
    claim = result.locked.claims[0]
    record = pipeline.store.span_registry.get(claim.span_ids[0])
    instructions = VerdictInstructions(prompt_hash=rules.verifier_prompt_hash(), tool_contract_version="mcp-tools-v1")
    from app.services.tutor_pipeline.render import layout_text

    segments = list(result.rendered.segments)
    segments[0] = segments[0].model_copy(update={"text": "A segment no template wrote."})
    forged = result.rendered.model_copy(update={"segments": tuple(segments), "text": layout_text(segments)})
    cases = {
        "unknown span": (VerdictRequest(claim_text=claim.text, span=VerdictSpan(span_id="span-" + "f" * 64, text=record.text), instructions=instructions),
                         PolicyContext(store=pipeline.store, corpus_registry=pipeline.registry)),
        "identifier": (VerdictRequest.model_construct(request_schema="v2-verdict-request-v1", item="claim", claim_text="Write to learner@example.edu",
                                                      span=VerdictSpan(span_id=record.span_id, text=record.text), instructions=instructions),
                       PolicyContext(store=pipeline.store, corpus_registry=pipeline.registry)),
        "non-template segment": (AlignmentRequest(rendered_text=forged.text, band=ReadabilityBand(min_grade=-4.0, max_grade=64.0),
                                                  instructions=AlignmentInstructions(prompt_hash=rules.alignment_prompt_hash(),
                                                                                     tool_contract_version="mcp-tools-v1")),
                                 PolicyContext(store=pipeline.store, corpus_registry=pipeline.registry, rendering=forged, locked=result.locked)),
    }
    for name, (request, context) in cases.items():
        start = last_security_seq()
        gateway = fresh_gateway(adapters=adapters_of(THREE))
        call = gateway.align if isinstance(request, AlignmentRequest) else gateway.verify
        with pytest.raises(GatewayStopped):
            call(THREE.members[0], request, context=context)
        assert (gateway.state, gateway.stop_reason) == ("stopped", "payload_violation"), name
        assert len(security_events("gateway.stopped", start)) == 1, name
        later = v2_pipeline(gateway=gateway, registry=THREE)
        assert later.v2_mode() == "off" and run(later, TIER2).entry.entry_schema == "ledger-entry-v2", name


def test_plan_l_a_secret_reaching_a_log_stops_the_gateway():
    from app.core.log_redaction import install_log_redaction

    secret = f"gateway-secret-{uuid4().hex}"
    gateway = fresh_gateway(adapters=adapters_of(THREE))
    install_log_redaction([secret], owner="gateway")
    start = last_security_seq()
    logging.getLogger("qcai.test.secret").warning("a provider response echoed %s", secret)
    # The listener only set a flag: no stop, no event, no database write inside the logging call.
    assert gateway.state == "open" and security_events("gateway.stopped", start) == []
    assert gateway.eligible(THREE.verifiers(), settings=Settings()) == []
    assert (gateway.state, gateway.stop_reason) == ("stopped", "secret_in_logs") and len(security_events("gateway.stopped", start)) == 1


def test_plan_l_a_stop_is_shared_by_every_instance_and_lasts_until_an_operator_clears_it(caplog):
    # Plan L "Stop on a payload violation, secret in logs or budget breach.": a stop on one instance is written to the
    # registry's shared stop; another instance, and a new process, adopts it (no second security event) and its V2 mode
    # and /ready say off and stopped; only the operator's command clears it, with its own security event. A running
    # instance that stopped never reopens: after the clear only a new process starts open (a new revision).
    from app.gateway.controls import DatabaseStopStore
    from app.gateway.gateway import process_gateway_state, reset_process_gateway
    from app.services import v2_panel
    from app.workers import gateway_stop

    caplog.set_level(logging.INFO)
    start = last_security_seq()
    one = ModelGateway(budget=DailyBudget(10), adapters=adapters_of(THREE), stop_store=DatabaseStopStore("development"))
    other = ModelGateway(budget=DailyBudget(10), adapters=adapters_of(THREE), stop_store=DatabaseStopStore("development"))
    one.stop("payload_violation")
    assert len(security_events("gateway.stopped", start)) == 1 and other.state == "open"
    assert other.eligible(THREE.verifiers(), settings=Settings()) == [] and (other.state, other.stop_reason) == ("stopped", "payload_violation")
    assert v2_panel.mode(Settings(model_gateway="on"), PACKAGE, gateway=ModelGateway(budget=DailyBudget(10), stop_store=DatabaseStopStore("development"))) == "off"
    assert len(security_events("gateway.stopped", start)) == 1  # adopted, not recorded again
    origins = [record.json_fields.get("origin") for record in caplog.records if getattr(record, "json_fields", {}).get("event") == "gateway.stopped"]
    assert origins == ["instance", "shared", "shared"]
    reset_process_gateway()  # a new process, as a restart or a new revision starts one: its gateway adopts the stop at once
    assert process_gateway_state() == ("open", None)  # none built yet: no read
    assert (get_gateway().state, get_gateway().stop_reason) == ("stopped", "payload_violation")
    reset_process_gateway()
    body = client.get("/ready").json()  # the V2 mode builds the process gateway, which reads the stop
    assert (body["gateway"]["state"], body["model_gateway"]) == ("stopped", "off") and "stop_reason" not in body["gateway"]
    assert DatabaseStopStore("staging").read() is None  # each registry's stop is its own
    assert gateway_stop.main([]) == 0 and DatabaseStopStore("development").read() == "payload_violation"  # a status read clears nothing
    assert gateway_stop.main(["--clear", "development"]) == 0 and DatabaseStopStore("development").read() is None
    cleared = security_events("gateway.stop_cleared", start)
    assert [(event.actor_role, event.details) for event in cleared] == [("operator", {"registry": "development", "reason": "payload_violation"})]
    # The clear removes the row only: the instances that stopped, or adopted the stop, keep it until they are replaced.
    for running in (one, other, get_gateway()):
        running.refresh()
        assert (running.state, running.stop_reason) == ("stopped", "payload_violation")
        assert running.eligible(THREE.verifiers(), settings=Settings()) == []
    assert client.get("/ready").json()["model_gateway"] == "off"
    reset_process_gateway()
    assert process_gateway_state() == ("open", None) and client.get("/ready").json()["model_gateway"] == "shadow"
    with pytest.raises(SystemExit):
        gateway_stop.main(["--clear", "elsewhere"])


def test_plan_h_only_public_quotable_spans_leave_and_gateway_and_v2_import_no_learner_module():
    from app.core.corpus_governance import get_corpus_registry
    from app.gateway.policy import PayloadPolicy, PayloadViolation
    from app.services.content_assembler import CourseStore

    governed = Settings(environment="production", enforce_corpus_governance=True, allowed_origins=["https://qantumlearn.academy"])
    store = CourseStore(governed)
    context = PolicyContext(store=store, corpus_registry=get_corpus_registry(governed))
    instructions = VerdictInstructions(prompt_hash=rules.verifier_prompt_hash(), tool_contract_version="mcp-tools-v1")
    for record in list(store.span_registry._by_id.values())[:10]:
        with pytest.raises(PayloadViolation):
            PayloadPolicy().check(VerdictRequest(claim_text="A claim.", span=VerdictSpan(span_id=record.span_id, text=record.text),
                                                 instructions=instructions), context)
    forbidden = ("learner_record", "learner_progress", "learning_intelligence", "microlearning", "app.core.auth", "app.api.routes",
                 "answer_history", "retrieval_legacy_p1")
    for root in (API_ROOT / "app" / "gateway", API_ROOT / "app" / "services" / "v2_panel"):
        for path in root.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else (
                    [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                for name in names:
                    assert not any(item in name for item in forbidden), (path.name, name)


# ===================================================================================================== plan E


REMOVED = ("_ask_vertex", "_vertex_client", "_vertex_endpoint", "_vertex_headers", "_vertex_provider_label", "_google_auth_bundle",
           "vertex_enabled", "vertex_api_key", "vertex_project_id", "_access_token", "_format_page_context", "_extract_text", "_sanitize_history",
           "vertex_ai_api_key", "vertex_ai_project_id", "vertex_ai_location", "vertex_ai_chat_model", "openai_chat_model")


def test_plan_e_the_legacy_provider_code_is_retired_and_no_production_path_reached_it(monkeypatch):
    import network_guard
    from app.services import teaching_assistant
    from app.services.retrieval_engine import RetrievalEngine
    from app.services.store import get_course_store
    from app.services.teaching_assistant import TeachingAssistantService

    for root in (API_ROOT / "app", REPO_ROOT / "scripts", API_ROOT / "alembic", REPO_ROOT / "evaluation"):
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                name = (node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else
                        node.attr if isinstance(node, ast.Attribute) else None)
                assert name not in REMOVED, (path, name)
    assert not (set(REMOVED) & set(Settings.model_fields))
    source = Path(teaching_assistant.__file__).read_text(encoding="utf-8")
    for removed in ("httpx", "google.auth", "aiplatform", "import os"):
        assert removed not in source, removed
    monkeypatch.setenv("VERTEX_AI_API_KEY", f"retired-key-{uuid4().hex}")
    network_guard.take_blocked()
    service = TeachingAssistantService(RetrievalEngine(get_course_store(), Settings()), Settings())
    assert service.chat("Why does routing depth matter?").provider == "none"
    body = client.post("/assistant/chat", json={"message": "Why does routing depth matter?"}, headers=demo("p5-retired")).json()
    assert body["provider"] == "none" and network_guard.take_blocked() == []
    # No tracked environment template still assigns a retired setting (a comment may name one).
    assert _templates_assigning(RETIRED_SETTINGS) == []


def _templates_assigning(names) -> list[str]:
    """`<template>: <name>` for each tracked env template line assigning one of names. Names only, never a value."""
    from app.gateway.retired import RETIRED_PROVIDER_SETTINGS

    assert set(names) == set(RETIRED_PROVIDER_SETTINGS)
    templates = [API_ROOT / ".env.example", REPO_ROOT / "apps" / "frontend" / ".env.example",
                 *sorted((REPO_ROOT / "infra" / "cloudrun").glob("*.env.example.yaml"))]
    found = []
    for path in templates:
        for line in path.read_text(encoding="utf-8").splitlines():
            assigned = re.match(r"\s*([A-Z][A-Z0-9_]*)\s*[=:]", line)
            if assigned and assigned.group(1) in names:
                found.append(f"{path.relative_to(REPO_ROOT).as_posix()}: {assigned.group(1)}")
    return found


RETIRED_SETTINGS = ("OPENAI_CHAT_MODEL", "VERTEX_AI_API_KEY", "VERTEX_AI_CHAT_MODEL", "VERTEX_AI_LOCATION", "VERTEX_AI_PROJECT_ID")


def test_plan_e_a_retired_setting_is_named_at_start_up_and_its_value_never_logged(monkeypatch, caplog):
    from app import main as main_module
    from app.core.log_redaction import REDACTED, install_log_redaction
    from app.gateway.retired import RETIRED_PROVIDER_SETTINGS, retired_secret_values, retired_settings_present

    value = f"retired-vertex-key-{uuid4().hex}"
    monkeypatch.setenv("VERTEX_AI_API_KEY", value)
    monkeypatch.setenv("VERTEX_AI_CHAT_MODEL", "gemini-3.1-flash-lite-preview")
    assert set(retired_settings_present()) >= {"VERTEX_AI_API_KEY", "VERTEX_AI_CHAT_MODEL"} and value in retired_secret_values()
    assert Settings().model_dump().keys().isdisjoint({name.lower() for name in RETIRED_PROVIDER_SETTINGS})
    install_log_redaction(retired_secret_values())
    caplog.set_level(logging.WARNING, logger="qcai.gateway")
    main_module._warn_retired_provider_settings()
    events = [record.json_fields for record in caplog.records if getattr(record, "json_fields", {}).get("event") == "gateway.retired_setting"]
    assert events and set(events[0]["names"]) >= {"VERTEX_AI_API_KEY", "VERTEX_AI_CHAT_MODEL"}
    logging.getLogger("qcai.test.retired").warning("echo %s", value)
    assert value not in caplog.text and REDACTED in caplog.text
    # Only the process environment is read: the module says so, and that a key kept only in a .env file is neither named
    # nor masked (no code reads one: the Settings field is gone and Settings ignore unknown keys).
    from app.gateway import retired

    assert "kept only in a .env file is neither named nor masked" in " ".join(retired.__doc__.split())


def test_plan_e_only_the_gateway_makes_model_egress():
    from test_gateway_egress_guard import ALLOWED_IMPORTS, scan

    # The one allow-list entry is the vector index client; the embedding egress and its key are the gateway's (spec 4.19).
    assert scan() == [] and ALLOWED_IMPORTS == {"app/services/retrieval_engine.py": {"pinecone"}}


def test_plan_e_d_23_provider_egress_needs_a_per_environment_per_provider_opt_in():
    from app.services.retrieval_engine import RetrievalEngine
    from app.services.store import get_course_store

    paid = fake_spec("paid-family", provider="test-provider", endpoint="https://verifier.invalid/v1", auth_header="x-api-key", secret_ref="TEST_KEY")
    gateway = fresh_gateway(adapters={})
    assert Settings().model_egress_providers == [] and Settings(environment="production", allowed_origins=["https://x.invalid"]).model_egress_providers == []
    assert gateway.ineligible_reason(paid, settings=Settings()) == "egress_refused"
    assert gateway.ineligible_reason(paid, settings=Settings(model_egress_providers="test-provider")) is None
    assert gateway.ineligible_reason(paid, settings=Settings(model_egress_providers='["other-provider"]')) == "egress_refused"
    with pytest.raises(ValidationError):
        Settings(model_egress_providers=["Not A Name"])
    keys = dict(pinecone_api_key="p" * 12, pinecone_index="i", semantic_retrieval_enabled=True)
    refused = RetrievalEngine(get_course_store(), Settings(**keys))._semantic_backend
    assert refused.enabled is False and refused.embedding_problem() == "egress_not_opted_in"
    # Opted in, the gateway still gives no embedder while the provider decisions are open (the shipped package).
    opted = RetrievalEngine(get_course_store(), Settings(**keys, model_egress_providers=["openai-embeddings"]))._semantic_backend
    assert opted.enabled is False and opted.embedding_problem() == "provider_open"


def test_plan_e_the_gateway_holds_the_embedding_key_and_gives_an_embedder_only_when_every_check_passes(monkeypatch):
    # Plan 7.1 "The gateway MUST be the sole holder of provider credentials": no Settings field holds OPENAI_API_KEY; the
    # gateway's secret store reads it. app.gateway.embeddings names the first check that fails: the environment's opt-in
    # (D-23), the provider decisions and the Q-15 review, a pinned model in package v4 gateway.embeddings, the registry's
    # budget, an open gateway and the key; once every one passes, plan H's bar remains: a query embedding would send the
    # learner's query text, so no provider embedder is ever given (spec 4.19).
    from app.gateway.embeddings import EMBEDDINGS_SECRET_REF, embedder_for, embedding_problem
    from app.gateway.secrets import PROVIDER_SECRET_REFS, provider_secret_values

    assert EMBEDDINGS_SECRET_REF in PROVIDER_SECRET_REFS and "openai_api_key" not in Settings.model_fields
    assert not {"openai_embedding_model", "openai_embedding_model_version"} & set(Settings.model_fields)  # package v4 holds them
    store = FakeSecretStore({EMBEDDINGS_SECRET_REF: "k" * 16})
    decided = {**PACKAGE.owner_decisions, "D-07": {"state": "decided"}, "D-12": {"state": "decided"}, "Q-09": {"state": "resolved"},
               "Q-15": {"state": "reviewed"}}
    closed = dataclasses.replace(PACKAGE, owner_decisions=decided)
    review_pending = dataclasses.replace(PACKAGE, owner_decisions={**decided, "Q-15": PACKAGE.owner_decisions["Q-15"]})

    def with_model(package, model_id, version):
        spec = dataclasses.replace(package.gateway.embeddings, model_id=model_id, model_version=version)
        return dataclasses.replace(package, gateway=dataclasses.replace(package.gateway, embeddings=spec))

    pinned = with_model(closed, "text-embedding-3-small", "2024-01-25")
    opted = {"model_egress_providers": ["openai-embeddings"]}
    gateway = fresh_gateway(10)
    cases = [
        (Settings(), PACKAGE, "egress_not_opted_in"),
        (Settings(**opted), PACKAGE, "provider_open"),
        (Settings(**opted), review_pending, "provider_open"),
        (Settings(**opted), closed, "unpinned"),
        (Settings(**opted), with_model(closed, "text-embedding-3-small", "latest"), "unpinned"),
        (Settings(**opted, environment="production", allowed_origins=["https://qantumlearn.academy"]), pinned, "no_budget"),
        (Settings(**opted), pinned, "learner_text"),
    ]
    for settings, package, expected in cases:
        assert embedding_problem(settings, package, secret_store=store, gateway=gateway) == expected, (expected, settings.model_egress_providers)
    assert embedding_problem(Settings(**opted), pinned, secret_store=FakeSecretStore(), gateway=gateway) == "not_configured"
    assert embedder_for(Settings(**opted), pinned, secret_store=store, gateway=gateway) is None
    assert embedder_for(Settings(**opted), PACKAGE, secret_store=store, gateway=gateway) is None
    gateway.stop("payload_violation")
    assert embedding_problem(Settings(**opted), pinned, secret_store=store, gateway=gateway) == "gateway_stopped"
    monkeypatch.setenv(EMBEDDINGS_SECRET_REF, "env-embedding-key-0123456789")
    assert provider_secret_values() == ["env-embedding-key-0123456789"]
    for path in (API_ROOT / "app" / "main.py", API_ROOT / "app" / "workers" / "common.py"):
        assert "*provider_secret_values()" in path.read_text(encoding="utf-8"), path.name


def test_plan_e_a_semantic_setting_without_the_d_23_opt_in_names_its_refusal(caplog):
    from app.gateway.egress import reset_refusal_log
    from app.main import SEMANTIC_INACTIVE_MESSAGES
    from app.services.retrieval_engine import RetrievalEngine
    from app.services.store import get_course_store

    reset_refusal_log()
    caplog.set_level(logging.WARNING, logger="qcai.gateway")
    keys = dict(pinecone_api_key="p" * 12, pinecone_index="i", semantic_retrieval_enabled=True)
    refused = RetrievalEngine(get_course_store(), Settings(**keys))
    assert refused.semantic_inactive_reason == "egress_not_opted_in"
    assert refused.sync_semantic_index() is False and refused.sync_semantic_index() is False
    lines = [record.json_fields for record in caplog.records if getattr(record, "json_fields", {}).get("event") == "gateway.egress_refused"]
    assert lines == [{"event": "gateway.egress_refused", "provider": "openai-embeddings", "adapter_id": None, "consumer": "semantic-retrieval"}]
    assert "openai-embeddings in MODEL_EGRESS_PROVIDERS" in SEMANTIC_INACTIVE_MESSAGES["egress_not_opted_in"]
    # Opted in, the shipped package's open decisions give no embedder; with a test's embedder and no index key, the
    # index is not configured; with the setting off, nothing is inactive.
    opted = RetrievalEngine(get_course_store(), Settings(**keys, model_egress_providers=["openai-embeddings"]))
    assert opted.semantic_inactive_reason == "provider_open" and "Q-15" in SEMANTIC_INACTIVE_MESSAGES["provider_open"]
    unconfigured = RetrievalEngine(get_course_store(), Settings(semantic_retrieval_enabled=True, pinecone_api_key=""), embedder=object())
    assert unconfigured.semantic_inactive_reason == "not_configured"
    assert RetrievalEngine(get_course_store(), Settings()).semantic_inactive_reason is None
    assert set(SEMANTIC_INACTIVE_MESSAGES) == {*EMBEDDING_PROBLEMS, "not_aligned"}
    reset_refusal_log()


@pytest.mark.parametrize("settings, reason", [
    ({"semantic_retrieval_enabled": True}, "egress_not_opted_in"),
    ({"semantic_retrieval_enabled": True, "model_egress_providers": ["openai-embeddings"]}, "provider_open"),
    ({}, None),
])
def test_plan_e_the_start_up_semantic_warning_names_its_reason(caplog, monkeypatch, settings, reason):
    # The lifespan's semantic.inactive line (main._warn_semantic_inactive) names why the setting is on and retrieval
    # stays lexical, with that reason's message; the lifespan runs it after the course store is built.
    import asyncio

    from app import main as main_module
    from app.main import SEMANTIC_INACTIVE_MESSAGES
    from app.services.retrieval_engine import RetrievalEngine
    from app.services.store import get_course_store

    engine = RetrievalEngine(get_course_store(), Settings(**settings))
    monkeypatch.setattr(main_module, "get_retrieval_engine", lambda: engine)
    for name in ("require_guest_token_secret", "_initialize_database", "_warn_retired_provider_settings", "_record_configuration_overrides"):
        monkeypatch.setattr(main_module, name, lambda *args, **kwargs: None)
    caplog.set_level(logging.WARNING, logger="qcai.api")

    async def start() -> None:
        async with main_module.lifespan(main_module.app):
            pass

    asyncio.run(start())
    lines = [(record.getMessage(), record.json_fields) for record in caplog.records
             if getattr(record, "json_fields", {}).get("event") == "semantic.inactive"]
    assert lines == ([] if reason is None else [(SEMANTIC_INACTIVE_MESSAGES[reason], {"event": "semantic.inactive", "reason": reason})])


def test_plan_e_no_real_provider_is_registered_in_any_shipped_registry():
    for name, members in PACKAGE.gateway.registries.items():
        assert all(spec.provider == "fake" for spec in members), name
        if name != "development":
            assert members == () and PACKAGE.gateway.daily_units[name] == 0, name
    for environment in ("production", "staging", "preview"):
        assert registry_for(PACKAGE, Settings.model_construct(environment=environment)).members == ()
    assert PACKAGE.raw["gateway"]["terms"] is None and PACKAGE.owner_decisions["D-12"]["state"] == "open"


def test_plan_d_five_tool_servers_have_versioned_contracts_and_the_learner_server_is_hidden():
    from app.gateway.tools import SERVERS, TOOLS, tool_contract_document

    assert SERVERS == ("analytics", "citation", "corpus", "learner", "verification") == tuple(PACKAGE.tools.servers)
    document = tool_contract_document()
    assert document["contract_version"] == "mcp-tools-v1" == PACKAGE.tools.version
    learner = next(tool for tool in TOOLS if tool.server == "learner")
    assert not (learner.roles & {"evidential", "verifier"})
    entry = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters_of(THREE)), registry=THREE), TIER2).entry
    assert entry.provenance.tool_contract_version == entry.verification.v2.tool_contract_version == "mcp-tools-v1"


# ===================================================================================================== plan I


def test_plan_i_ready_reports_package_v4_and_the_gateway_state_and_no_per_run_outcome():
    from app import main as main_module

    body = client.get("/ready").json()
    # The shipped package's version (4.0.0 with Phase 5, 5.0.0 since Phase 6); the gateway fields are v4's, which v5 keeps.
    assert body["config_package_version"] == PACKAGE.package_version and body["model_gateway"] == "shadow" and body["model_gateway_setting"] == "shadow"
    assert body["phase5_exit_passed"] is False
    gateway = body["gateway"]
    assert {key: gateway[key] for key in ("version", "registry", "state", "budget_daily_units", "tool_contract_version", "provisional",
                                          "available", "embeddings")} == {
        "version": "gateway-v1", "registry": "development", "state": "open", "budget_daily_units": 100000,
        "tool_contract_version": "mcp-tools-v1", "provisional": True, "available": True,
        "embeddings": {"provider": "openai-embeddings", "model_id": None, "model_version": None}}
    assert [member["adapter_id"] for member in gateway["members"]] == ["fake-alpha-v1", "fake-beta-v1", "fake-gamma-v1", "fake-delta-v1"]
    assert all(set(member) == {"adapter_id", "family", "provider", "model_id", "model_version", "capabilities"} for member in gateway["members"])
    before = main_module._build_fields()
    client.post("/assistant/chat", json={"message": "Why does routing depth matter?"}, headers=demo("p5-ready"))
    assert main_module._build_fields() == before
    assert not ({"calls", "cost_units", "spent", "spent_today", "cache_hits", "outcomes"} & set(gateway))
    # /ready is public (authorization matrix: GET /ready, public): the stop's reason (it may say a credential reached the
    # logs) and the operator's switches stay off it, on every body (ready, degraded, building).
    private = {"stop_reason", "kill_switch", "disabled_adapters", "egress_providers", "secret_ref", "endpoint"}
    switched = Settings(model_gateway_kill_switch="abstain_only", model_egress_providers=["openai-embeddings"],
                        model_gateway_disabled_adapters=["fake-beta-v1"])
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(main_module, "settings", switched)
        fields = main_module._build_fields()["gateway"]
    assert not (private & set(fields)) and not (private & set(gateway)) and "abstain_only" not in json.dumps(fields)
    assert not (private & set(gateway["embeddings"])) and all(not (private & set(member)) for member in gateway["members"])
    get_gateway().stop("budget_breach")
    stopped = client.get("/ready").json()
    assert (stopped["gateway"]["state"], stopped["model_gateway"]) == ("stopped", "off") and "budget_breach" not in json.dumps(stopped)


def test_plan_i_v2_metrics_report_completion_time_degraded_p95_cost_and_the_budget_event(caplog, monkeypatch):
    from app.services.v2_panel.metrics import V2_METRICS

    class Clock:
        now = 1000.0

        def __call__(self) -> float:
            return self.now

    clock = Clock()
    monkeypatch.setattr(V2_METRICS, "clock", clock)
    V2_METRICS.reset()
    caplog.set_level(logging.INFO)
    # An outage: every member down for the whole sequence, with a V1-abstained response in the middle. Completion is
    # 0 of 3 (each V1-passed response withheld its claims), and all of the time is ZERO's: the V1-abstained response,
    # which never reached the panel, neither moves the clock nor resets the mode.
    outage = v2_pipeline(gateway=fresh_gateway(adapters=adapters_of(THREE, **{spec.adapter_id: {"down": True} for spec in THREE.members})),
                         registry=THREE)
    run(outage, TIER2)
    clock.now += 0.3
    run(outage, OFF_TOPIC[0])
    clock.now += 0.6
    run(outage, TIER2)
    run(outage, TIER2)
    snapshot = V2_METRICS.detail_snapshot()
    assert snapshot["completion"] == {"passed_v1": 3, "completed": 0, "withheld": 3, "rate": "0/3"}
    assert snapshot["time_in_mode_s"] == {"ZERO": 0.9} and snapshot["modes"]["ZERO"] == 3
    lines = [record.json_fields for record in caplog.records if getattr(record, "json_fields", {}).get("event") == "tutor.v2.run"]
    assert [(line["passed_v1"], line["panel_reached"], line["panel_mode"], line["completed"]) for line in lines] == [
        (True, True, "ZERO", False), (False, False, None, False), (True, True, "ZERO", False), (True, True, "ZERO", False)]
    clock.now += 0.25
    assert V2_METRICS.detail_snapshot()["time_in_mode_s"] == {"ZERO": 1.15}  # the mode in force runs on to the snapshot
    V2_METRICS.reset()
    caplog.clear()
    caplog.set_level(logging.WARNING, logger="qcai.gateway")
    gateway = ModelGateway(budget=DailyBudget(30), adapters=adapters_of(THREE))
    pipeline = v2_pipeline(gateway=gateway, registry=THREE)
    for query in (TIER2, MULTI_CLAIM, OFF_TOPIC[0]):
        run(pipeline, query)
        clock.now += 1.0
    down = v2_pipeline(gateway=fresh_gateway(adapters=adapters_of(THREE, **{"fake-gamma-v1": {"down": True}})), registry=THREE)
    run(down, TIER2)
    snapshot = V2_METRICS.detail_snapshot(budget=gateway.budget.snapshot())
    assert snapshot["completion"] == {"passed_v1": 3, "completed": 3, "withheld": 0, "rate": "3/3"}
    assert snapshot["modes"]["FULL"] == 2 and snapshot["modes"]["REDUCED-2"] == 1 and snapshot["runs"]["on"] == 4
    assert snapshot["time_in_mode_s"] == {"FULL": 3.0, "REDUCED-2": 0.0} and snapshot["latency_ms"]["panel"] is not None
    assert snapshot["latency_ms"]["gateway_call"] and snapshot["cost_units"]["total"] > 0 and snapshot["cost_units"]["per_response_p95"] > 0
    assert snapshot["budget"]["daily_units"] == 30 and snapshot["budget"]["alerted"] is True
    assert any(getattr(record, "json_fields", {}).get("event") == "gateway.budget_alert" for record in caplog.records)


# ===================================================================================================== freeze and invariants


def test_freeze_public_payloads_with_shipped_non_development_settings_are_byte_identical_to_phase_4():
    capture = load_script("capture_public_payloads")
    committed = json.loads((API_ROOT / "tests" / "data" / "phase4_public_payloads_v1.json").read_text(encoding="utf-8"))
    assert committed["captured_on_app_tree"] == "98f7cc4" and committed["queries"]["count"] == 298
    fresh_capture = capture.compute()
    assert capture.differences(committed, fresh_capture) == []
    assert Settings(environment="production", allowed_origins=["https://qantumlearn.academy"]).model_gateway == "off"


def test_invariant_3_v2_never_overwrites_a_v1_hard_fail():
    from test_v2_correction import LaterUnmapped

    claims = run(dev_pipeline(), TIER2).locked.claims
    # The final rendering of the deliverable claims hard-fails V1.4: the record is that V1 decision's.
    pipeline = v2_pipeline(gateway=fresh_gateway(adapters=contradicting(THREE, claims[1])), registry=THREE, renderer=LaterUnmapped(PACKAGE))
    verification = run(pipeline, TIER2).entry.verification
    assert verification.hard_fail and verification.final == "abstain" and verification.v2.panel_reached
    assert all(verdict.v2 is None for verdict in verification.verdicts) and verification.v2.alignment is None
    payload = verification.model_dump(mode="json")
    v2 = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters_of(THREE)), registry=THREE), TIER2).entry.verification.model_dump(mode="json")
    payload["verdicts"][0]["v2"] = v2["verdicts"][0]["v2"]
    with pytest.raises(ValidationError, match="V2 never overwrites a V1 decision"):
        VerificationRecordV2.model_validate(payload)


def test_invariant_4_distinct_families_equal_votes():
    entry = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters_of(FOUR)), registry=FOUR), MULTI_CLAIM).entry
    claims = {claim.claim_id: claim for claim in entry.claims}
    for claim_id, verdict in judged(entry).items():
        families = sorted({vote.family for vote in verdict.votes})
        assert families == list(verdict.members) and entry.verification.v2.generator_family not in families
        assert len(verdict.votes) == len(families) * len(claims[claim_id].span_ids)
        for family in families:
            pairs = [(vote.verdict, vote.ehmf_type) for vote in verdict.votes if vote.family == family]
            assert family_verdict(pairs)[0] in rules.V2_VERDICTS


def test_invariant_6_no_v2_delivery_without_a_completed_passing_vote():
    generator = random.Random(20261121)
    queries = (TIER2, MULTI_CLAIM, TWO_CLAIMS)
    claims_of = {query: run(dev_pipeline(), query).locked.claims for query in queries}
    delivered = 0
    for _ in range(300):
        query = generator.choice(queries)
        options = {}
        for spec in FOUR.members:
            option = {}
            if generator.random() < 0.25:
                option["down"] = True
            if generator.random() < 0.25:
                option["fail_calls"] = {generator.randint(1, 4)}
            if generator.random() < 0.3:
                claim = generator.choice(claims_of[query])
                option["script"] = {claim_key(claim.text, span_id): (generator.choice(("CONTRADICTED", "NOT_ENOUGH_INFO")), "A")
                                    for span_id in claim.span_ids}
            if generator.random() < 0.1:
                option["alignment"] = {"rating": 2, "leakage": True}
            options[spec.adapter_id] = option
        entry = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters_of(FOUR, **options)), registry=FOUR), query).entry
        verification = entry.verification
        for verdict in verification.verdicts:
            if verdict.final == "deliver":
                delivered += 1
                assert verdict.v2 is not None and verdict.v2.outcome == "pass"
        assert (verification.final == "deliver") == any(verdict.final == "deliver" for verdict in verification.verdicts)
        assert entry.delivery == "shadow"
    assert delivered > 0


def test_invariant_10_every_vote_carries_its_prompt_hash_and_every_v3_record_its_provenance_fields():
    entry = run(v2_pipeline(gateway=fresh_gateway(adapters=adapters_of(THREE)), registry=THREE), MULTI_CLAIM).entry
    for name in ("generator_model_id", "evidential_prompt_hash", "pedagogical_prompt_hash", "v1_3_checker_model_id", "corpus_version",
                 "threshold_set_version", "panel_weights_version", "routing_table_version", "tool_contract_version"):
        assert getattr(entry.provenance, name) is not None, name
    assert all(vote.verifier_prompt_hash == entry.verification.v2.verifier_prompt_hash for verdict in judged(entry).values() for vote in verdict.votes)
    assert all(vote.verifier_prompt_hash == entry.verification.v2.alignment_prompt_hash for vote in entry.verification.v2.alignment.votes)
    assert PACKAGE.tutor_pipeline.unused_provenance_fields == ()


def test_freeze_v1_3_flags_route_to_v2_only_under_model_gateway_on():
    finals = {}
    for setting in ("off", "shadow", "on"):
        settings = Settings(model_gateway=setting)
        pipeline = (dev_pipeline(settings) if setting == "off" else
                    v2_pipeline(settings, gateway=fresh_gateway(adapters=adapters_of(THREE)), registry=THREE))
        entry = run(pipeline, TIER2, legacy_decision="answer").entry
        assert all(any(check.check_id == "V1.3" and check.outcome == "flag" for check in verdict.v1) for verdict in entry.verification.verdicts)
        finals[setting] = {verdict.final for verdict in entry.verification.verdicts}
    assert finals == {"off": {"withhold"}, "shadow": {"withhold"}, "on": {"deliver"}}


# ===================================================================================================== plan F


def test_plan_f_the_registry_matrix_payload_register_and_terms_record_match_the_package():
    registry_doc = (REPO_ROOT / "docs" / "architecture" / "gateway-registry.md").read_text(encoding="utf-8")
    assert "Generated from" not in registry_doc  # hand-maintained, and compared value by value below
    members = PACKAGE.gateway.registries["development"]
    assert f"| development | {', '.join(f'`{spec.adapter_id}`' for spec in members)} |" in registry_doc
    for spec in members:
        caps = spec.caps
        assert (f"| `{spec.adapter_id}` | `{spec.family}` | `{spec.model_id}` | {spec.model_version} | {', '.join(spec.capabilities)} | "
                f"{caps.max_tokens} tokens, {caps.timeout_ms} ms, {caps.max_retries} retr{'y' if caps.max_retries == 1 else 'ies'} | "
                f"{spec.cost_units_per_call} unit{'' if spec.cost_units_per_call == 1 else 's'} |") in registry_doc, spec.adapter_id
    units = PACKAGE.gateway.daily_units
    assert units["staging"] == units["production"] == units["default"] == 0
    assert f"development {units['development']} units; staging, production and default 0" in registry_doc
    numerator, denominator = PACKAGE.gateway.alert_share
    assert f"Alert at {numerator}/{denominator}." in registry_doc
    for name in ("staging", "production", "default"):
        assert f"| {name} | none |" in registry_doc and PACKAGE.gateway.registries[name] == ()
    # The embedding egress's entry (gateway.embeddings, PD-26): its model, caps and cost as the package holds them.
    embedding = PACKAGE.gateway.embeddings
    assert embedding.model_id is None and "model none" in registry_doc and f"provider `{embedding.provider}`" in registry_doc
    caps = embedding.caps
    assert (f"caps {caps.max_items} inputs per request, {caps.max_input_chars} characters per input, {caps.timeout_ms} ms, "
            f"{caps.max_retries} retries; {embedding.cost_units_per_item} unit per input and attempt") in registry_doc
    adr = (REPO_ROOT / "docs" / "adr" / "ADR-008-model-gateway-and-v2-panel.md").read_text(encoding="utf-8")
    for text in (registry_doc, adr, spec_text()):
        for mode, row in rules.RULE_MATRIX.items():
            line = next(line for line in text.splitlines() if line.startswith(f"| {mode} ("))
            for tier in (1, 2, 3):
                assert {"withhold-queue-v3": "withheld", "equal-weights-share-v1": "equal weights"}.get(row[tier], row[tier]) in line, (mode, tier)
    register = (REPO_ROOT / "docs" / "security" / "payload-register.md").read_text(encoding="utf-8")
    for model in (VerdictRequest, AlignmentRequest, VerdictSpan, VerdictInstructions, AlignmentInstructions, ReadabilityBand):
        for field in model.model_fields:
            assert f"`{field}`" in register, (model.__name__, field)
    for never in ("resolved question", "learner identifiers", "history", "generator identity", "other votes", "rationale"):
        assert never in register, never
    assert "Status: owner review pending (DI-71)" in register
    terms = (REPO_ROOT / "docs" / "security" / "provider-terms-record.md").read_text(encoding="utf-8")
    assert "Q-09 is unresolved; no provider terms are recorded; no provider is registered; package v4 `gateway.terms` is null" in terms
    assert PACKAGE.raw["gateway"]["terms"] is None


# ===================================================================================================== docs


def _code_fields(source: str, name: str) -> list[str]:
    node = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == name)
    return [ast.unparse(item) for item in node.body if isinstance(item, (ast.AnnAssign, ast.Assign))]


def test_phase5_spec_section_3_lists_the_code_s_fields():
    section = spec_text().split("## 3. Data shapes", 1)[1].split("## 4. Algorithms", 1)[0]
    paths = {"contracts": "services/tutor_pipeline/contracts.py", "gateway_contracts": "gateway/contracts.py", "registry": "gateway/registry.py",
             "panel": "services/v2_panel/panel.py", "track": "services/v2_panel/track.py", "cache": "services/v2_panel/cache.py"}
    sources = {name: (API_ROOT / "app" / path).read_text(encoding="utf-8") for name, path in paths.items()}
    classes = {name: {node.name for node in ast.parse(source).body if isinstance(node, ast.ClassDef)} for name, source in sources.items()}
    checked = 0
    for block in re.findall(r"```python\n(.*?)```", section, flags=re.DOTALL):
        for node in ast.parse(block).body:
            if not isinstance(node, ast.ClassDef):
                continue
            owner = next(name for name in paths if node.name in classes[name])
            listed = [ast.unparse(item) for item in node.body if isinstance(item, (ast.AnnAssign, ast.Assign))]
            assert listed == _code_fields(sources[owner], node.name), node.name
            checked += 1
    assert checked >= 25


def test_phase5_docs_quote_the_plan_and_state_the_current_rules():
    plan_l = "Flag off returns to Phase 4. Stop on a payload violation, secret in logs or budget breach."
    plan_m = "Residual: correlation unmeasured until E2."
    adr = (REPO_ROOT / "docs" / "adr" / "ADR-008-model-gateway-and-v2-panel.md").read_text(encoding="utf-8")
    runbook = (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8").split("## Phase 5: gateway and V2 (runbook)", 1)[1]
    spec = spec_text()
    assert plan_m in adr and plan_m in spec and plan_l in spec and "Flag off returns to Phase 4" in runbook
    head = spec.split("\n## 18. Review history\n", 1)[0]
    for number in range(22, 32):
        assert f"| PD-{number} |" in head, number
    for number in range(69, 89):
        assert f"| DI-{number} |" in head, number
    values = PACKAGE.owner_decisions["Q-22"]["provisional_values"]
    assert "v2.voting" in values and "PD-25" in PACKAGE.owner_decisions["Q-22"]["record"]
    assert "`provisional_until \"Q-22 (DI-52)\"`" in head
    for code_name in ("MODEL_GATEWAY", "MODEL_EGRESS_PROVIDERS", "MODEL_GATEWAY_DISABLED_ADAPTERS", "MODEL_GATEWAY_KILL_SWITCH"):
        assert code_name in head and code_name in runbook, code_name
    from test_phase3_docs import NARRATIVE

    assert NARRATIVE.findall(head) == []


def test_phase5_docs_the_runbooks_and_registers_state_the_gateway_s_operations_exactly():
    spec = spec_text()
    infra = REPO_ROOT / "infra" / "cloudrun"
    # The observability runbook's Phase 5 table: every row has the header's two cells, and every event of spec 10.4 is named.
    slis = (infra / "observability.md").read_text(encoding="utf-8").split("## Phase 5 SLIs: gateway and V2 (plan Phase 5 I)", 1)[1]
    rows = [line for line in slis.splitlines() if line.startswith("|")]
    assert rows[0] == "| SLI or event | Log-based metric or alert |"
    cells = [len(re.findall(r"(?<!\\)\|", line)) for line in rows]
    assert set(cells) == {3}, [line[:60] for line, count in zip(rows, cells) if count != 3]
    events = re.findall(r"^\| `([a-z0-9_.]+)`", spec.split("### 10.4 Log events", 1)[1].split("\n## 11.", 1)[0], flags=re.MULTILINE)
    named = [event for event in events if re.search(rf"(?<![\w.]){re.escape(event)}(?![\w.])", slis)]
    assert len(events) >= 13 and named == events, sorted(set(events) - set(named))
    assert "`model_gateway` (the effective mode) turns `off`" in slis and "Only `state` and `stop_reason` can change" not in slis
    # The deployment runbook: a stop is shared until the operator's command clears it, the flag stays the fallback, the
    # Phase 5 revision has its gated step, and the ledger export names its path.
    runbook = (infra / "deployment.md").read_text(encoding="utf-8").split("## Phase 5: gateway and V2 (runbook)", 1)[1]
    assert "every other instance adopts it" in runbook and "python -m app.workers.gateway_stop --clear REGISTRY" in runbook
    assert "set `MODEL_GATEWAY=off` on the service" in runbook and "it covers that one instance only" not in runbook and "DI-87" not in runbook
    assert "alembic upgrade 20261122_phase5_gateway_controls" in runbook and "alembic downgrade 20261119_phase3_response_ledger" in runbook
    assert "--export PATH" in runbook and "--export`" not in runbook
    adr8 = (REPO_ROOT / "docs" / "adr" / "ADR-008-model-gateway-and-v2-panel.md").read_text(encoding="utf-8")
    assert "The cache, the budget and the stop are per process" not in adr8 and "DI-77" not in adr8 and "DI-86" in adr8
    assert "shared by every instance through the application database" in adr8
    # The start-up semantic.inactive line: the Phase 2 spec's event row and the observability runbook's row give its
    # reason, and the deployment runbook's bullet names the opt-in, the refusal line and the start-up line.
    phase2 = (REPO_ROOT / "docs" / "architecture" / "phase2-implementation-spec.md").read_text(encoding="utf-8")
    row = next(line for line in phase2.splitlines() if line.startswith("| `semantic.inactive` |"))
    assert row.startswith("| `semantic.inactive` | `reason`") and "provider_open" in row and "not_aligned" in row
    observed = next(line for line in (infra / "observability.md").read_text(encoding="utf-8").splitlines() if '`event: "semantic.inactive"`' in line)
    assert "| `reason`" in observed and "| none |" not in observed and "provider_open" in observed
    bullet = next(line for line in runbook.splitlines() if line.startswith("- Semantic retrieval (`SEMANTIC_RETRIEVAL_ENABLED`"))
    assert "`openai-embeddings` in `MODEL_EGRESS_PROVIDERS`" in bullet and "`gateway.egress_refused`" in bullet and "`semantic.inactive` with its `reason`" in bullet
    # The payload register (Q-15, the owner's review input) states each field as the code sends it.
    register = (REPO_ROOT / "docs" / "security" / "payload-register.md").read_text(encoding="utf-8")
    assert "other claims of the response in a claim item (the alignment item's `rendered_text` is the whole rendering" in register
    assert "`{model, model_version, max_tokens, instructions, input}`" in register and "stops the gateway on anything else" not in register
    # The egress guard's host-string scope, as test_gateway_egress_guard.py scans it (HOST_ROOTS: .py files only; the
    # evaluation root holds evaluation/tests). Each text is compared with its line breaks and code marks folded, so a
    # phrase wrapped across lines cannot hide.
    from test_gateway_egress_guard import HOST_ROOTS

    assert [root.relative_to(REPO_ROOT).as_posix() for root in HOST_ROOTS] == ["apps/api/app", "scripts", "evaluation", "tools"]
    scope = "the Python files under apps/api/app, scripts, evaluation (its tests included) and tools"
    unscanned = "apps/api/tests, apps/frontend, infra and every non-Python file are not scanned"
    adr6 = (REPO_ROOT / "docs" / "adr" / "ADR-006-security-model.md").read_text(encoding="utf-8")
    gateway_doc = (API_ROOT / "app" / "gateway" / "__init__.py").read_text(encoding="utf-8")
    guard_doc = (API_ROOT / "tests" / "test_gateway_egress_guard.py").read_text(encoding="utf-8").split('"""', 2)[1]
    for text in (adr6, gateway_doc, guard_doc):
        flat = " ".join(text.split()).replace("`", "")
        for stale in ("anywhere else in the repository's code", "the frontend, infra and the tests are not scanned"):
            assert stale not in flat, stale
        assert scope in flat and unscanned in flat, text[:80]
    # Texts Phase 5 made false, edited in place (spec 7.6).
    phase3 = (REPO_ROOT / "docs" / "architecture" / "phase3-implementation-spec.md").read_text(encoding="utf-8")
    assert "Phase 5 wires one through the gateway" not in phase3 and "The Vertex helpers are unchanged; the provider path is Phase 5." not in phase3
    for path in (REPO_ROOT / "docs" / "adr" / "ADR-002-retrieval-architecture.md", REPO_ROOT / "docs" / "architecture" / "phase2-implementation-spec.md",
                 API_ROOT / "app" / "services" / "retrieval_engine.py", infra / "api-production.env.example.yaml"):
        assert "openai-embeddings" in path.read_text(encoding="utf-8"), path.name
    # The Phase 3 spec's test 31 and the Phase 4 spec's loader line state the current code; the cache keeps no learner text.
    phase4 = (REPO_ROOT / "docs" / "architecture" / "phase4-implementation-spec.md").read_text(encoding="utf-8")
    assert "`_build_fields()` makes no DB call." not in phase3 and "its only statements are the shared gateway stop's reads" in phase3
    assert "`schema_version in (1, 2, 3)`, and 4 since Phase 5 and 5 since Phase 6" in phase4
    cache_doc = " ".join((API_ROOT / "app" / "services" / "v2_panel" / "cache.py").read_text(encoding="utf-8").split('"""', 2)[1].split())
    assert "or any text: keys are hashes" not in cache_doc and "whose only text is corpus text" in cache_doc
    # A stopped instance never reopens: no text says the stop ends at the operator's clear (spec 4.5).
    stale = {API_ROOT / "app" / "gateway" / "gateway.py": "every call is refused until an operator clears the stop",
             API_ROOT / "app" / "core" / "config.py": "turns the effective mode off until an operator clears",
             infra / "observability.md": "every instance's V2 mode is off until an operator clears the stop",
             SPEC_PATH: "turns the effective mode off until an operator clears it"}
    for path, text in stale.items():
        assert text not in " ".join(path.read_text(encoding="utf-8").replace("#", " ").split()), path.name
    assert "a stopped instance stays stopped until it is replaced" in slis and "A running gateway never reopens" in " ".join(
        (API_ROOT / "app" / "gateway" / "gateway.py").read_text(encoding="utf-8").split())
    # The loggers each Phase 5 event logs on: test_phase5_docs_name_the_logger_each_phase5_event_logs_on.
    # The mutation-check record claims only the checks the commit messages and the phase record name (spec 13.5).
    mutation = spec.split("### 13.5 Mutation checks", 1)[1].split("\n## 14.", 1)[0]
    assert "The record of each check is in the commit messages and the BEP phase record." not in mutation
    assert "not yet mutation-checked" in mutation


LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}


def _code_loggers() -> dict[str, set[str | None]]:
    """Every literal `event` the API code logs, with the names of the loggers it is logged on, read from the source: a
    module-level `NAME = logging.getLogger("...")`, a logger a module imports by name from another app module, or a
    direct `logging.getLogger("...")` call. None stands for a receiver this reading cannot resolve."""

    def logger_name(node: ast.AST) -> str | None:
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "getLogger"
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "logging"
                and len(node.args) == 1 and isinstance(node.args[0], ast.Constant)):
            return node.args[0].value
        return None

    trees = {}
    for path in sorted((API_ROOT / "app").rglob("*.py")):
        parts = path.relative_to(API_ROOT).with_suffix("").parts
        trees[".".join(parts[:-1] if parts[-1] == "__init__" else parts)] = ast.parse(path.read_text(encoding="utf-8"))
    own = {module: {target.id: name for statement in tree.body if isinstance(statement, ast.Assign)
                    and (name := logger_name(statement.value)) for target in statement.targets if isinstance(target, ast.Name)}
           for module, tree in trees.items()}
    events: dict[str, set[str | None]] = {}
    for module, tree in trees.items():
        loggers = dict(own[module])
        for statement in tree.body:
            if isinstance(statement, ast.ImportFrom) and statement.module in own:
                loggers.update({alias.asname or alias.name: own[statement.module][alias.name]
                                for alias in statement.names if alias.name in own[statement.module]})
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in LOG_METHODS):
                continue
            receiver = node.func.value
            name = loggers.get(receiver.id) if isinstance(receiver, ast.Name) else logger_name(receiver)
            for keyword in node.keywords:
                for fields in keyword.value.values if keyword.arg == "extra" and isinstance(keyword.value, ast.Dict) else ():
                    for key, value in zip(fields.keys, fields.values) if isinstance(fields, ast.Dict) else ():
                        if isinstance(key, ast.Constant) and key.value == "event" and isinstance(value, ast.Constant):
                            events.setdefault(value.value, set()).add(name)
    return events


def _documented_loggers(text: str) -> dict[str, str]:
    """The loggers a text names: "`event` (on `logger`)", where a list of events joined by commas or "and" before one
    "(on `logger`)" names that logger for each; a `gateway.*` or `tutor.*` event the text does not name this way is on
    the logger the text gives its family."""
    assert "`qcai.gateway` (the `gateway.*` events)" in text and "`qcai.tutor` (the `tutor.*` events)" in text, text[:80]
    named: dict[str, str] = {}
    for group, logger in re.findall(r"((?:`[a-z0-9_.]+`(?:, | and ))*`[a-z0-9_.]+`) \(on `([a-z0-9_.]+)`\)", text):
        for event in re.findall(r"`([a-z0-9_.]+)`", group):
            assert named.setdefault(event, logger) == logger, (event, text[:80])
    return named


def test_phase5_docs_name_the_logger_each_phase5_event_logs_on(monkeypatch, caplog):
    # Spec 10.4, its 7.1 import rule and the observability runbook name the logger of every 10.4 event as the code logs
    # it: the gateway.* events on qcai.gateway (the start-up line gateway.retired_setting included) and the tutor.* events
    # on qcai.tutor, except the operator's gateway.stop_status (qcai.worker) and the start-up semantic.inactive
    # (qcai.api); the security events gateway.stopped and gateway.stop_cleared are on qcai.security. Read from the
    # source, then confirmed at run time for the start-up lines and the stop command.
    from app import main as main_module
    from app.services import security_log
    from app.services.retrieval_engine import RetrievalEngine
    from app.services.store import get_course_store
    from app.services.tutor_pipeline import pipeline
    from app.workers import gateway_stop

    spec = spec_text()
    table = spec.split("### 10.4 Log events", 1)[1].split("\n## 11.", 1)[0]
    events = re.findall(r"^\| `([a-z0-9_.]+)`", table, flags=re.MULTILINE)
    assert {"gateway.retired_setting", "gateway.stop_status", "semantic.inactive", "tutor.v2.budget_exceeded"} <= set(events)
    code = _code_loggers()
    for event in pipeline.BUDGET_EVENTS:  # the one event name the code passes in a variable (TwoPassPipeline._over)
        code.setdefault(event, set()).add(pipeline.LOGGER.name)
    loggers = {event: code.get(event, set()) for event in events}
    assert all(len(names) == 1 and None not in names for names in loggers.values()), loggers
    loggers = {event: next(iter(names)) for event, names in loggers.items()}
    assert (loggers["gateway.retired_setting"], loggers["gateway.stop_status"], loggers["semantic.inactive"]) == ("qcai.gateway", "qcai.worker", "qcai.api")
    # The start-up lines and the operator's command, run: each record's logger is the one the source gives.
    caplog.set_level(logging.INFO)
    monkeypatch.setenv("VERTEX_AI_CHAT_MODEL", "gemini-3.1-flash-lite-preview")
    main_module._warn_retired_provider_settings()
    engine = RetrievalEngine(get_course_store(), Settings(semantic_retrieval_enabled=True))
    monkeypatch.setattr(main_module, "get_retrieval_engine", lambda: engine)
    assert main_module._warn_semantic_inactive() == "egress_not_opted_in"
    assert gateway_stop.main([]) == 0
    seen: dict[str, set[str]] = {}
    for record in caplog.records:
        if event := getattr(record, "json_fields", {}).get("event"):
            seen.setdefault(event, set()).add(record.name)
    for event in ("gateway.retired_setting", "semantic.inactive", "gateway.stop_status"):
        assert seen.get(event) == {loggers[event]}, (event, seen.get(event))
    # Each text names those loggers; a stale sentence (a start-up line on another logger, or no exception named) fails.
    slis = (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8").split(
        "## Phase 5 SLIs: gateway and V2 (plan Phase 5 I)", 1)[1]
    texts = {
        "observability runbook": next(line for line in slis.splitlines() if line.startswith("The Phase 5 events log on")),
        "spec 10.4": next(line for line in table.splitlines() if line.startswith("The Phase 5 events log on")),
        "spec 7.1": next(line for line in spec.splitlines() if line.startswith("**Import rule.**")),
    }
    family = {"gateway.": "qcai.gateway", "tutor.": "qcai.tutor"}
    for name, text in texts.items():
        named = _documented_loggers(text)
        documented = {event: named.get(event) or next((logger for prefix, logger in family.items() if event.startswith(prefix)), None)
                      for event in events}
        assert documented == loggers, (name, {event: (documented[event], loggers[event]) for event in events if documented[event] != loggers[event]})
        assert set(named) <= set(events), (name, sorted(set(named) - set(events)))
    assert security_log.LOGGER.name == "qcai.security"
    for name in ("observability runbook", "spec 10.4"):
        assert "the security events `gateway.stopped` and `gateway.stop_cleared` log on `qcai.security`" in texts[name], name
    assert "All Phase 5 events log on `qcai.gateway` or `qcai.tutor`" not in slis


def _test_function_names() -> set[str]:
    names = set()
    for path in (API_ROOT / "tests").glob("test_*.py"):
        names |= set(re.findall(r"^(?:async )?def (test_\w+)\(", path.read_text(encoding="utf-8"), flags=re.MULTILINE))
    return names


# The modules that existed before Phase 5 and that Phase 5 changed (spec 13.2 additions, 13.3 changes): each has a row
# in the test strategy's second Phase 5 table, saying what the phase's change to it proves.
PHASE5_EXTENDED_MODULES = (
    "conftest.py", "test_api.py", "test_config_package.py", "test_configuration_overrides.py", "test_phase2_acceptance.py",
    "test_phase3_acceptance.py", "test_phase4_acceptance.py", "test_python_sources.py", "test_response_ledger.py",
    "test_response_ledger_migrations.py", "test_response_ledger_provenance.py", "test_tutor_retrieve_bind_lock.py",
    "test_v1_5_abstention.py", "test_v1_aggregate_and_runner.py", "v1_fakes.py",
)


def test_phase5_docs_the_test_strategy_maps_every_test_module_the_phase_added():
    strategy = (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
    phase_5 = strategy.split("## Phase 5 acceptance map", 1)[1].split("\n## ", 1)[0]
    files = phase_5.split("### Phase 5 test files", 1)[1]
    added_table, changed_table = files.split("### Phase 5 changes to existing test modules", 1)
    changed_table = changed_table.split("**Exit gate.**", 1)[0]

    def rows_of(table: str) -> dict[str, str]:
        return {match.group(1): match.group(2) for line in table.splitlines() if (match := re.match(r"\| `([^`]+)` \| (.+) \|$", line))}

    rows, changed = rows_of(added_table), rows_of(changed_table)
    tests = API_ROOT / "tests"
    expected = {path.name for pattern in ("test_phase5_*.py", "test_gateway_*.py", "test_v2_*.py", "v2_fakes.py", "network_guard.py")
                for path in tests.glob(pattern)}
    assert len([name for name in expected if name.startswith("test_gateway_")]) == 7 and len([name for name in expected if name.startswith("test_v2_")]) == 5
    assert sorted(rows) == sorted(expected), sorted(set(rows) ^ expected)
    assert sorted(changed) == sorted(PHASE5_EXTENDED_MODULES), sorted(set(changed) ^ set(PHASE5_EXTENDED_MODULES))
    assert all((tests / name).exists() for name in PHASE5_EXTENDED_MODULES)
    for name, text in {**rows, **changed}.items():
        assert len(text) > 80, name
    functions = _test_function_names()
    missing = [name for name in re.findall(r"`(test_[a-z0-9_]+)`", phase_5) if name not in functions]
    assert missing == []
    assert "**Exit gate.**" in phase_5 and "phase5_exit_passed" in phase_5


def test_phase5_docs_the_spec_ends_in_one_review_history_table():
    head, history = spec_text().split("\n## 18. Review history\n", 1)
    assert re.findall(r"^## (\d+)\. ", head, flags=re.MULTILINE) == [str(number) for number in range(18)]
    assert "\n## " not in history and "\n### " not in history and history.count("\n| Round |") == 1
    intro = history.split("\n| Round |", 1)[0]
    assert "may describe behaviour that a later round superseded" in intro and "sections 0-17 are authoritative" in intro
    rows = [line for line in history.splitlines() if line.startswith("| ") and not line.startswith(("| Round |", "|---"))]
    assert [row.split(" | ", 1)[0] for row in rows[:3]] == ["| Spec (pre-code)", "| Spec review 1 (pre-code)", "| Build"]
    functions = _test_function_names()
    for row in rows:
        round_name, commit, findings = row.split(" | ", 2)
        assert "pre-code" in round_name or re.search(r"`[0-9a-f]{7,40}`|the commit", commit), round_name
        for finding in findings.rstrip(" |").split("<br>"):
            names = re.findall(r"`(test_[a-z0-9_]+)`", finding)
            files = re.findall(r"`(test_[a-z0-9_]+\.py)`", finding)
            assert names or files, (round_name, finding[:60])
            assert all(name in functions for name in names), (round_name, names)
    assert re.findall(r"\b[Rr]eview \d+\b|\bround \d+\b", head) == []


def test_phase5_docs_the_records_name_the_merge_and_the_cited_main_run():
    # PR #37 was squash-merged as c34a8c1 (tree identical to 8aa4ff1); main run 45044415408 passed every job and is the
    # cited run (Phase 6 design E15). The spec's DI-74 row, its section 17 exit bullet and the test strategy's Phase 5 exit
    # paragraph name the merge, the merged tree and that run, none keeps a pre-merge phrase, and the exit stays not passed.
    spec = spec_text()
    head = spec.split("\n## 18. Review history\n", 1)[0]
    exit_block = head.split("**Exit (plan P).**", 1)[1]
    strategy = (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
    texts = {
        "DI-74": next(line for line in head.splitlines() if line.startswith("| DI-74 |")),
        "spec 17": next(line for line in exit_block.splitlines() if line.startswith("- The AC tests and F-1")),
        "test strategy": next(line for line in strategy.split("## Phase 5 acceptance map", 1)[1].splitlines() if line.startswith("**Exit gate.**")),
    }
    for name, text in texts.items():
        for fact in ("`c34a8c1`", "`8aa4ff1`", "45044415408"):
            assert fact in text, (name, fact)
        for stale in ("the cited run follows the merge", "each later commit needs its own run", "the cited run must be on `main`"):
            assert stale not in text, (name, stale)
    assert "The exit is not passed." in texts["DI-74"] and texts["DI-74"].endswith("| Eng / PI | Open |")
    assert "The exit is not passed." in texts["test strategy"]
    assert "- `phase5_exit_passed` stays `false`." in exit_block
    assert "| Merge | `c34a8c1` |" in spec.split("\n## 18. Review history\n", 1)[1]


# ===================================================================================================== plan 13.6


def test_plan_13_6_flag_combinations_never_disable_v1_or_deliver_unverified_text():
    from app.services import tutor_pipeline, v1_checks, v2_panel

    checked = refused = 0
    for environment, two_pass, v1, gateway, switch, egress in itertools.product(
            ("development", "production"), ("off", "shadow", "on"), ("off", "shadow", "enforce"), ("off", "shadow", "on"),
            ("none", "abstain_only", "pre_verified_only"), ([], ["test-provider"])):
        options = dict(environment=environment, two_pass_tutor=two_pass, v1_pipeline=v1, model_gateway=gateway, model_gateway_kill_switch=switch,
                       model_egress_providers=egress, allowed_origins=["https://qantumlearn.academy"])
        expected_refusal = (two_pass == "on" or (gateway == "on" and v1 != "enforce")
                            or (environment == "production" and (v1 in ("off", "enforce") or gateway == "on")))
        try:
            settings = Settings(**options)
        except ValidationError:
            refused += 1
            assert expected_refusal, options
            continue
        assert not expected_refusal, options
        checked += 1
        package = get_config_package(settings)
        if environment == "production":
            assert v1_checks.mode(settings, package) != "off" and tutor_pipeline.effective_mode(settings, package) != "on"
            # V2 is off outside development unless MODEL_GATEWAY=shadow is set explicitly (a config.override); either way
            # the registry is empty and the budget 0, so no call can be made and the record is a shadow record only.
            mode = v2_panel.mode(settings, package)
            assert mode == "off" or (mode == "shadow" and gateway == "shadow" and two_pass == "shadow"), options
            registry = registry_for(package, settings)
            assert registry.members == () and package.gateway.daily_units[registry.name] == 0
    assert checked and refused
    with SessionLocal() as db:
        assert not list(db.scalars(select(ResponseLedgerRecord).where(ResponseLedgerRecord.delivery == "delivered")))
    assert contracts.TWO_PASS_DELIVERY_IMPLEMENTED is False
