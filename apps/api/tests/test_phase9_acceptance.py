"""Phase 9 acceptance: verified-trust ranking and drift control (plan Phase 9 K AC-9-1 to AC-9-8, and the plan E, F, G, H, I,
J, L, P rows; Phase 9 spec 13.1). Hand-built event logs folded by the pure controller, development shadow records in fresh
in-memory databases, temporary package copies and the committed records; nothing is written into the checkout.
"""

from __future__ import annotations

import ast
import copy
from dataclasses import fields
from decimal import Decimal
import json
import logging
from pathlib import Path
import re
import subprocess
import sys

import pytest

from app.core.config import Settings
from app.core.config_package import DEFAULT_PACKAGE_PATH, ConfigPackageError, canonical_sha256, load_config_package
from app.services import ranking
from app.services.ranking import synthetic
from app.services.ranking.controller import apply
from app.services.ranking.models import candidates
from app.services.ranking.quality import f_from_rating
from app.services.ranking.selection import ensure_models
from app.services.ranking.selection import select as choose
from app.services.ranking.signals import outcome_of
from app.services.ranking.state import empty_state, params_of, state_sha256
from app.services.ranking.types import Context, Decision, Skip
from app.services.ranking.vocabulary import EVENT_KINDS, SKIP_REASONS
from ranking_fakes import (
    BLOCK,
    CLONE,
    FIXED_NOW,
    PACKAGE,
    REPO_ROOT,
    STATIC,
    TIER2,
    Log,
    apply_all,
    block_with,
    commission_static,
    derived_of,
    events_of,
    model,
    package_copy,
    ranking_settings,
    scan,
    shadow_record,
    stored_state,
)

API_ROOT = REPO_ROOT / "apps" / "api"
SPEC_PATH = REPO_ROOT / "docs" / "architecture" / "phase9-implementation-spec.md"
REPORT = REPO_ROOT / "docs" / "evaluation" / "phase9" / "ranking_replay_v1.json"
FIXTURES = REPO_ROOT / "docs" / "evaluation" / "phase9" / "hand_fixtures_v1.json"
A, B = model("model-a", "family-a"), model("model-b", "family-b")
# Every test module Phase 9 added or changed (git diff --name-only 512b8a6 -- apps/api/tests).
PHASE9_TEST_MODULES = (
    "test_phase9_acceptance.py", "test_ranking_units.py", "ranking_fakes.py", "conftest.py", "test_phase7_acceptance.py",
    "test_phase6_acceptance.py", "test_phase4_acceptance.py", "test_phase3_acceptance.py", "test_config_package.py", "test_ehmf_units.py",
    "test_response_ledger_migrations.py", "test_configuration_overrides.py",
)


def scripts_module(name: str):
    import importlib.util

    key = f"ranking_test_{name}"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, REPO_ROOT / "scripts" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


def spec_text() -> str:
    return SPEC_PATH.read_text(encoding="utf-8")


def models_of(state: dict, key: str) -> dict:
    return state["contexts"][key]["models"]


def trust_view(state: dict) -> dict:
    """Everything AC-9-1 and AC-9-2 say must not change: trust, Qbar, the charts, the streaks and the incumbents."""
    view = {"models": {name: {k: v for k, v in entry.items()} for name, entry in state["models"].items()}, "cluster_cusum": state["cluster_cusum"],
            "contexts": {}}
    for key, context in state["contexts"].items():
        view["contexts"][key] = {"incumbent": context["incumbent"], "streaks": context["streaks"], "batch_seq": context["batch_seq"],
                                 "models": {name: {k: entry[k] for k in ("alpha", "beta", "T", "qbar", "n")} for name, entry in context["models"].items()}}
    return view


KEY2 = "unscoped|explanation|2"


# ===================================================================================================== records


def _candidates(settings=None):
    return {item.adapter_id: item for item in candidates(PACKAGE, settings or ranking_settings())}


def _modules():
    from app.services.ranking.contexts import span_modules
    from app.services.store import get_course_store

    store = get_course_store()
    return span_modules(store), store.corpus_version


def _typed_entry():
    from ehmf_fakes import typed_record

    return typed_record(settings=Settings(model_gateway="shadow", ehmf="shadow", ranking="off"), legacy_decision="answer").entry


def _verdict(entry, **update):
    return entry.model_copy(update={"verification": entry.verification.model_copy(update=update)})


def _first_claim(entry, *, v2=None, v3=None, v1=None):
    verification = entry.verification
    verdict = verification.verdicts[0]
    changes = {}
    if v2 is not None:
        changes["v2"] = verdict.v2.model_copy(update=v2)
    if v3 is not None:
        changes["v3"] = v3
    if v1 is not None:
        changes["v1"] = v1
    verdicts = (verdict.model_copy(update=changes), *verification.verdicts[1:])
    return _verdict(entry, verdicts=verdicts)


def _outcome(entry, seq: int = 1):
    modules, corpus = _modules()
    return outcome_of(entry, ledger_seq=seq, created_at="2026-11-23T12:00:00.000000Z", candidates=_candidates(), modules=modules,
                      corpus_version=corpus, package=PACKAGE)


def skip_cases() -> dict:
    """One real record per skip reason (a development record, edited where only an edit gives that reason)."""
    from tutor_fakes import make_entry
    from v1_fakes import dev_pipeline, run

    entry = _typed_entry()
    provenance = entry.provenance.model_copy(update={"evidential_prompt_hash": "f" * 64})
    phase4 = run(dev_pipeline(Settings(model_gateway="off", ranking="off")), TIER2, legacy_decision="answer").entry
    return {
        "unparsed": None,
        "no_verification": make_entry(),
        "generator_unknown": entry.model_copy(update={"versions": entry.versions.model_copy(update={"generator_id": "unknown-generator"})}),
        "stale_version": entry.model_copy(update={"provenance": provenance}),
        "not_generated": _verdict(entry, generation_attempts=0),
        "budget_exceeded": _verdict(entry, final_reason="budget_exceeded"),
        "detector_down": _verdict(entry, final_reason="checker_unavailable"),
        "kill_switch": _verdict(entry, final_reason="v2_kill_switch"),
        "v2_withheld": _verdict(entry, final_reason="v2_degraded_withheld"),
        "no_v2_verdict": phase4,
        "panel_not_reached": _verdict(entry, v2=entry.verification.v2.model_copy(update={"panel_reached": False})),
        "corpus_conflict": _verdict(entry, final_reason="conflict_withheld"),
    }


_SKIPS: dict = {}


def skips() -> dict:
    if not _SKIPS:
        _SKIPS.update(skip_cases())
    return _SKIPS


# ===================================================================================================== AC-9-1


@pytest.mark.parametrize("reason", SKIP_REASONS)
def test_ac_9_1_an_event_without_a_completed_verdict_leaves_alpha_beta_and_qbar_unchanged(reason):
    result = _outcome(skips()[reason])
    assert isinstance(result, Skip) and result.reason == reason, result
    static = _candidates()[STATIC].as_dict()
    base = Log().models(static).batch(STATIC, 30).tick(30 * 40)
    before, _ = apply_all(base.events)
    after, derived = apply_all(base.add("skipped", {"ledger_seq": 99, "reason": reason, "model": result.model}).events)
    assert json.dumps(trust_view(after), sort_keys=True) == json.dumps(trust_view(before), sort_keys=True)
    assert derived == apply_all(base.events[:-1])[1]
    assert after["counts"]["skipped"][reason] == before["counts"]["skipped"][reason] + 1
    assert {k: v for k, v in after["counts"].items() if k != "skipped"} == {k: v for k, v in before["counts"].items() if k != "skipped"}
    # A control record with a completed verdict changes the state.
    control = _outcome(_typed_entry())
    assert not isinstance(control, Skip) and control.y == 1
    changed, _ = apply_all(Log().models(static).batch(STATIC, 30).tick(30 * 40).batch(STATIC, 25).events)
    assert models_of(changed, KEY2)[STATIC]["alpha"] != models_of(before, KEY2)[STATIC]["alpha"]


def test_ac_9_1_y_is_one_only_for_an_uncorrected_first_pass():
    entry = _typed_entry()
    assert _outcome(entry).y == 1
    cases = {
        "regeneration": _verdict(entry, cycle_count=1),
        "x1": _first_claim(entry, v2={"critical": True, "objections": 1}),
        "x2": _first_claim(entry, v3=entry.verification.verdicts[0].v3.model_copy(update={"escalation": "X2", "reasons": ("v2_correction_exhausted",)})),
        "v2_fail": _first_claim(entry, v2={"outcome": "fail"}),
        "misconception": _first_claim(entry, v3=entry.verification.verdicts[0].v3.model_copy(update={"reasons": ("v1_8_misconception",)})),
        "hard_fail": _verdict(entry, hard_fail=True),
        "v2_corrected": _verdict(entry, v2=entry.verification.v2.model_copy(update={"cycles": 1})),
        "v1_3_contradicted": _first_claim(entry, v1=tuple(result.model_copy(update={"reason_code": "contradicted"}) if result.check_id == "V1.3" else result
                                                          for result in entry.verification.verdicts[0].v1)),
    }
    for name, case in cases.items():
        result = _outcome(case)
        assert not isinstance(result, Skip) and result.y == 0, name
    # X4 alone (a V1.5 near-floor mark) and X3 (a learner flag, which never touches the record) leave y = 1.
    mark = next(check for check in entry.verification.checks if check.check_id == "V1.5").model_copy(update={"outcome": "mark", "reason_code": "near_miss"})
    assert _outcome(_verdict(entry, checks=(*entry.verification.checks, mark))).y == 1
    # No generator self-confidence: signals.py reads no ClaimPlan and no GeneratorRef.kind.
    tree = ast.parse((API_ROOT / "app" / "services" / "ranking" / "signals.py").read_text(encoding="utf-8"))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "ClaimPlan" not in names and "kind" not in names and "prompt_hash" not in names


# ===================================================================================================== AC-9-2


def test_ac_9_2_a_learner_rating_changes_only_f_i():
    log = Log().models(A, B)
    for _ in range(3):
        log.batch("model-a", 25).batch("model-b", 25, v="0.8")
    log.batch("model-a", 10)
    with_rating = copy.deepcopy(log).add("feedback", {"ledger_seq": log.ledger - 2, "F": str(f_from_rating(1)), "source": "rating"})
    for item in (log, with_rating):
        item.batch("model-a", 15)
    plain, plain_derived = apply_all(log.events)
    rated, rated_derived = apply_all(with_rating.events)
    a_plain, a_rated = models_of(plain, KEY2)["model-a"], models_of(rated, KEY2)["model-a"]
    assert a_plain["qbar"] != a_rated["qbar"]
    for field in ("alpha", "beta", "T", "n"):
        assert a_plain[field] == a_rated[field], field
    assert plain["models"] == rated["models"] and plain["cluster_cusum"] == rated["cluster_cusum"]
    assert plain["contexts"][KEY2]["incumbent"] == rated["contexts"][KEY2]["incumbent"]
    assert plain["contexts"][KEY2]["streaks"] == rated["contexts"][KEY2]["streaks"]
    for kind in ("promote", "demote", "alarm", "select"):
        assert [p for k, p in plain_derived if k == kind] == [p for k, p in rated_derived if k == kind], kind
    # Late feedback (the outcome's batch already closed) counts only late_feedback.
    late = copy.deepcopy(log).add("feedback", {"ledger_seq": 1, "F": "0", "source": "x3"})
    late_state, _ = apply_all(late.events)
    assert trust_view(late_state) == trust_view(plain) and late_state["counts"]["late_feedback"] == 1
    assert [str(f_from_rating(stars)) for stars in range(1, 6)] == ["0E-18", "0.250000000000000000", "0.500000000000000000",
                                                                     "0.750000000000000000", "1.000000000000000000"]


def test_ac_9_2_a_shadow_record_has_f_missing_and_no_feedback_is_appended_for_it():
    from sqlalchemy import select

    from app.db_models import ResponseLedgerRecord
    from app.services.v3.queue import upsert_item
    from app.services.v3.triggers import response_spec
    from v3_fakes import fresh_v3_sessions

    with fresh_v3_sessions() as (factory, _engine):
        result = shadow_record(factory)
        outcome = _outcome(result.entry)
        assert outcome.signals.F is None
        commission_static(factory)
        # An X3 item on the shadow record (as a learner flag would put on the legacy record): still no feedback input.
        with factory() as db:
            row = db.execute(select(ResponseLedgerRecord.__table__).where(ResponseLedgerRecord.seq == result.appended.seq)).first()
            upsert_item(db, record_row=row, spec=response_spec(result.entry, "X3"), entry=result.entry, package=PACKAGE, now=FIXED_NOW)
            db.commit()
        scan(factory)
        assert events_of(factory, "feedback") == []
        assert events_of(factory, "outcome")[0]["payload"]["signals"]["F"] is None


# ===================================================================================================== AC-9-3


def _promotion_log(block=None, *, batches: int, interrupt_at: int | None = None) -> Log:
    """model-a's first batch (quality 0.5) makes it the first incumbent; model-b's prior and its batches (quality 1) put
    R(b) - R(a) above the deadband at every context batch from a's on, so a's batch is the streak's first."""
    log = Log(block).models(A, B)
    log.batch("model-a", 25, v="0.5", k="0.5")
    for index in range(batches):
        v = "0" if interrupt_at == index else "1"
        log.batch("model-b", 25, v=v, k=v)
    return log


def _gaps(log: Log) -> list[Decimal]:
    """R(b) - R(a) after each context batch closes (the value the promotion rule compares with delta)."""
    from app.services.ranking.selection import ranking_score

    gaps = []
    outcomes = [index for index, event in enumerate(log.events) if event["kind"] == "outcome"]
    for count in range(25, len(outcomes) + 1, 25):
        state, _ = apply_all(log.events[: outcomes[count - 1] + 1])
        params = params_of(state)
        gaps.append(ranking_score(state, params, KEY2, "model-b") - ranking_score(state, params, KEY2, "model-a"))
    return gaps


def test_ac_9_3_a_challenger_ahead_by_the_active_deadband_is_promoted_only_after_the_active_debounce():
    # a's batch and one b batch are two context batches ahead: no promotion; a third promotes.
    assert all(gap > Decimal("0.05") for gap in _gaps(_promotion_log(batches=2)))
    assert derived_of(_promotion_log(batches=1).events, "promote") == []
    promoted = derived_of(_promotion_log(batches=2).events, "promote")
    assert len(promoted) == 1 and promoted[0]["from"] == "model-a" and promoted[0]["to"] == "model-b" and promoted[0]["streak"] == 3
    assert Decimal(promoted[0]["delta_seen"]) > Decimal("0.05")
    # An interruption (a batch with b no longer ahead) resets the streak: three more are needed.
    assert _gaps(_promotion_log(batches=3, interrupt_at=1))[2] <= Decimal("0.05")
    assert derived_of(_promotion_log(batches=3, interrupt_at=1).events, "promote") == []
    assert derived_of(_promotion_log(batches=4, interrupt_at=1).events, "promote") == []
    assert len(derived_of(_promotion_log(batches=5, interrupt_at=1).events, "promote")) == 1
    # A gap of exactly delta does not count (strictly greater): delta at the smallest of the three gaps blocks the
    # promotion, one quantum below it lets it through.
    smallest = min(_gaps(_promotion_log(batches=2)))
    exact = block_with(lambda block: block["promotion"].update(delta=str(smallest)))
    assert derived_of(_promotion_log(exact, batches=2).events, "promote") == []
    below = block_with(lambda block: block["promotion"].update(delta=str(smallest - Decimal("1e-18"))))
    assert len(derived_of(_promotion_log(below, batches=2).events, "promote")) == 1
    # A batch while h is not in E resets the streak.
    log = Log().models(A, B)
    log.batch("model-a", 25, v="0.5", k="0.5").batch("model-b", 25)   # a streak of 2
    log.add("availability", {"models": {"model-a": None, "model-b": "down"}}).batch("model-b", 25)   # b not in E: reset
    log.add("availability", {"models": {"model-a": None, "model-b": None}}).batch("model-b", 25).batch("model-b", 25)
    assert derived_of(log.events, "promote") == []
    assert apply_all(log.events)[0]["contexts"][KEY2]["streaks"]["model-b"] == 2
    # A lower-rated challenger is not promoted, however far ahead its score: b rated B (its commissioning prior, Qbar 1)
    # stays ahead of a rated A (Qbar falling to 0.3) for four context batches.
    low = Log().models(A, clean=2000, mean_q="1").models(B, clean=40, mean_q="1")
    for _ in range(4):
        low.batch("model-a", 25, v="0.3", k="0.3")
    state, derived = apply_all(low.events)
    from app.services.ranking.selection import live_rating

    params = params_of(state)
    assert (live_rating(state, params, KEY2, "model-a"), live_rating(state, params, KEY2, "model-b")) == ("A", "B")
    assert state["contexts"][KEY2]["streaks"]["model-b"] >= 3 and [p for k, p in derived if k == "promote"] == []
    # A package copy with delta 0.10 and n_d 2 is followed.
    changed = block_with(lambda block: block["promotion"].update(delta="0.10", n_d=2))
    assert len(derived_of(_promotion_log(changed, batches=2).events, "promote")) == 1


# ===================================================================================================== AC-9-4


def test_ac_9_4_trust_below_the_tier_threshold_demotes_immediately():
    log = Log().models(A, B)
    log.batch("model-a", 25).batch("model-b", 25, v="0.5", k="0.5")
    state, _ = apply_all(log.events)
    assert state["contexts"][KEY2]["incumbent"] == "model-a"
    log.batch("model-a", 25, y=0)  # one batch of failures takes T(a) below 0.90 at tier 2
    state, derived = apply_all(log.events)
    demotions = [p for k, p in derived if k == "demote"]
    assert len(demotions) == 1 and demotions[0]["from"] == "model-a" and Decimal(demotions[0]["T"]) < Decimal("0.90")
    assert demotions[0]["threshold"] == "0.9"
    decision, _ = choose(state, params_of(state), KEY2, ledger_seq=10_000)
    assert decision.model != "model-a"
    # A tier-1 B incumbent is demoted on the availability input that makes an A model available.
    key1 = "unscoped|quiz_item|1"
    tier1 = Log().models(A, clean=30).models(B, clean=200)   # a rated B (Beta(31, 1)), b rated A
    tier1.add("availability", {"models": {"model-a": None, "model-b": "down"}})
    tier1.batch("model-a", 3, tier=1)
    state, _ = apply_all(tier1.events)
    assert state["contexts"][key1]["incumbent"] == "model-a"
    tier1.add("availability", {"models": {"model-a": None, "model-b": None}})
    state, derived = apply_all(tier1.events)
    assert [p["from"] for k, p in derived if k == "demote"][-1:] == ["model-a"] and state["contexts"][key1]["incumbent"] == "model-b"


# ===================================================================================================== AC-9-5


def _clone_package(tmp_path: Path, version: str) -> object:
    def edit(payload):
        member = next(item for item in payload["gateway"]["registries"]["development"] if item["adapter_id"] == CLONE)
        member["model_version"] = version
    return load_config_package(package_copy(tmp_path / version, edit), governed=False)


def test_ac_9_5_a_model_version_change_deflates_caps_at_c_and_raises_x5_until_the_golden_regression_passes(tmp_path):
    from sqlalchemy import select

    from app.db_models import V3Event, V3ModelVersion
    from app.services.v3.scan import open_windows, run_scan as v3_scan
    from ranking_fakes import CLONE as clone_id
    from v3_fakes import fresh_v3_sessions

    bumped = _clone_package(tmp_path, "2026-11-22")
    with fresh_v3_sessions() as (factory, _engine):
        commission_static(factory)
        clone = _candidates()[clone_id]
        with factory() as db:
            from app.services.ranking.scan import append_inputs
            from v2_fakes import fresh_gateway

            append_inputs(db, [("commission", {"adapter_id": clone_id, "version": clone.model_version, "clean": 200, "failed": 0, "generated": 200,
                                               "mean_q": "0.9", "run_sha256": "0" * 64})], settings=ranking_settings(), package=PACKAGE, now=FIXED_NOW,
                          gateway=fresh_gateway())
            db.commit()
        before = stored_state(factory)
        before_prior = before["models"][clone_id]["prior"]
        settings = ranking_settings(config_package_path=str(bumped.path))
        scan(factory, settings=settings, package=bumped)
        state = stored_state(factory)
        entry = state["models"][clone_id]
        assert entry["capped"] is True and entry["version"] == "2026-11-22"
        assert Decimal(entry["prior"]["alpha"]) == Decimal(before_prior["alpha"]) * Decimal("0.3")
        assert Decimal(entry["prior"]["beta"]) == Decimal(before_prior["beta"]) * Decimal("0.3")
        from app.services.ranking.selection import live_rating

        params = params_of(state)
        working = copy.deepcopy(state)
        ensure_models(working, params, KEY2)
        assert live_rating(working, params, KEY2, clone_id) == "C"
        decision, _ = choose(working, params, KEY2, ledger_seq=1)
        assert clone_id not in decision.eligible
        with factory() as db:
            changes = [json.loads(payload) for (payload,) in db.execute(select(V3Event.payload).where(V3Event.kind == "model_change"))]
            assert [item["model_key"] for item in changes].count(f"generator:{clone_id}") == 1
            assert db.scalar(select(V3ModelVersion.model_version).where(V3ModelVersion.model_key == f"generator:{clone_id}")) == "fake-delta-verifier@2026-11-22"
            assert any(remaining > 0 for _seq, remaining in open_windows(db))
        # A following V3 scan over a record carrying the new version adds no second generator row.
        from app.services.ranking.generators import CloneGenerator
        from app.gateway.registry import registry_for

        spec = next(item for item in registry_for(bumped, settings).members if item.adapter_id == clone_id)
        shadow_record(factory, settings=Settings(environment="development", model_gateway="shadow", ehmf="shadow", ranking="off",
                                                 config_package_path=str(bumped.path)), generator=CloneGenerator(spec, bumped, settings=settings))
        v3_scan(settings=Settings(environment="development", v3_queue="shadow", config_package_path=str(bumped.path)), package=bumped,
                session_factory=factory, now=FIXED_NOW)
        with factory() as db:
            keys = [json.loads(payload)["model_key"] for (payload,) in db.execute(select(V3Event.payload).where(V3Event.kind == "model_change"))]
            assert keys.count(f"generator:{clone_id}") == 1
        # Time does not lift the cap; a failing recommission keeps it; a passing one lifts it.
        scan(factory, settings=settings, package=bumped, now=FIXED_NOW.replace(year=2027))
        assert stored_state(factory)["models"][clone_id]["capped"] is True
        from app.services.ranking.scan import append_inputs
        from v2_fakes import fresh_gateway

        for kind, expected in (("recommission_fail", True), ("recommission_pass", False)):
            with factory() as db:
                append_inputs(db, [(kind, {"adapter_id": clone_id, "version": "2026-11-22", "clean": 40, "failed": 0, "generated": 40,
                                           "run_sha256": "0" * 64})], settings=settings, package=bumped, now=FIXED_NOW, gateway=fresh_gateway())
                db.commit()
            assert stored_state(factory)["models"][clone_id]["capped"] is expected, kind


def test_ac_9_5_the_ranking_reuses_v3_s_model_change_for_a_version_v3_already_saw(tmp_path):
    # V3 sees the clone's records first (a baseline at 2026-11-21, then a change to 2026-11-22): the ranking scan's change to
    # that version reuses V3's event, so one change opens one X5 window (spec conflict 14).
    from sqlalchemy import select

    from app.db_models import V3Event
    from app.gateway.registry import registry_for
    from app.services.ranking.generators import CloneGenerator
    from app.services.v3.scan import run_scan as v3_scan
    from v3_fakes import fresh_v3_sessions

    bumped = _clone_package(tmp_path, "2026-11-22")
    with fresh_v3_sessions() as (factory, _engine):
        commission_static(factory)
        for package in (PACKAGE, bumped):
            settings = Settings(environment="development", model_gateway="shadow", ehmf="shadow", ranking="off", config_package_path=str(package.path))
            spec = next(item for item in registry_for(package, settings).members if item.adapter_id == CLONE)
            shadow_record(factory, settings=settings, generator=CloneGenerator(spec, package, settings=settings))
            v3_scan(settings=Settings(environment="development", v3_queue="shadow", config_package_path=str(package.path)), package=package,
                    session_factory=factory, now=FIXED_NOW)
        with factory() as db:
            before = [seq for seq, payload in db.execute(select(V3Event.seq, V3Event.payload).where(V3Event.kind == "model_change"))
                      if json.loads(payload)["model_key"] == f"generator:{CLONE}"]
        assert len(before) == 1
        scan(factory, settings=ranking_settings(config_package_path=str(bumped.path)), package=bumped)
        with factory() as db:
            after = [seq for seq, payload in db.execute(select(V3Event.seq, V3Event.payload).where(V3Event.kind == "model_change"))
                     if json.loads(payload)["model_key"] == f"generator:{CLONE}"]
        assert after == before
        change = events_of(factory, "model_change")
        assert len(change) == 1 and change[0]["v3_event_seq"] == before[0]


def test_ac_9_5_the_x5_window_raises_the_next_delivery_s_draw_to_one_in_five(tmp_path):
    from sqlalchemy import select

    from app.db_models import V3Draw
    from app.services.v3.scan import run_scan as v3_scan
    from v3_fakes import append_all, fresh_v3_sessions, synthetic_deliveries

    bumped = _clone_package(tmp_path, "2026-11-23")
    with fresh_v3_sessions() as (factory, _engine):
        commission_static(factory)
        scan(factory, settings=ranking_settings(config_package_path=str(bumped.path)), package=PACKAGE)
        scan(factory, settings=ranking_settings(config_package_path=str(bumped.path)), package=bumped)
        append_all(factory, synthetic_deliveries(1))
        v3_scan(settings=Settings(environment="development", v3_queue="shadow"), package=PACKAGE, session_factory=factory, now=FIXED_NOW)
        with factory() as db:
            draw = db.execute(select(V3Draw)).scalars().one()
            assert (draw.rate_numerator, draw.rate_denominator, draw.x5_active) == (1, 5, True)


# ===================================================================================================== AC-9-6


@pytest.mark.parametrize("cause", ["down", "stopped", "kill_switch", "disabled", "all_d"])
def test_ac_9_6_an_empty_eligible_set_delivers_no_unverified_text_and_enqueues_a_v3_item(cause):
    from sqlalchemy import func, select

    from app.db_models import ResponseLedgerRecord, V3QueueItem
    from app.services.ranking import hook
    from v2_fakes import fresh_gateway
    from v3_fakes import fresh_v3_sessions

    with fresh_v3_sessions() as (factory, _engine):
        shadow_record(factory)
        gateway = fresh_gateway()
        settings = ranking_settings()
        if cause == "stopped":
            gateway.stop("budget_breach")
        elif cause == "kill_switch":
            settings = ranking_settings(model_gateway_kill_switch="abstain_only")
        elif cause == "disabled":
            settings = ranking_settings(model_gateway_disabled_adapters=[CLONE])
        elif cause == "down":
            from v2_fakes import ScriptedFakeAdapter
            from app.gateway.registry import registry_for

            gateway = fresh_gateway(adapters={spec.adapter_id: ScriptedFakeAdapter(spec, down=spec.adapter_id == CLONE)
                                              for spec in registry_for(PACKAGE, settings).members})
        # The static candidate is ineligible too: commissioned with failures (rated D), or by the kill switch.
        commission_static(factory, settings=settings, clean=5, failed=20, gateway=gateway)
        scan(factory, settings=settings, gateway=gateway)
        selects = events_of(factory, "select")
        assert selects and all(item["payload"]["kind"] == "fallback" for item in selects)
        payload = selects[0]["payload"]
        assert payload["model"] is None and payload["eligible"] == [] and payload["explore"] is None
        assert set(payload) == {"ledger_seq", "context", "eligible", "kind", "model", "explore", "u_explore"}
        with factory() as db:
            items = db.execute(select(V3QueueItem.reasons, V3QueueItem.subject)).all()
            assert ("ranking_empty_eligible_set", "response") in [(row.reasons, row.subject) for row in items]
            ledger_rows = db.scalar(select(func.count()).select_from(ResponseLedgerRecord))
        decision = hook.select(Context("unscoped", "explanation", 2), ledger_seq=1, settings=settings, package=PACKAGE, session_factory=factory)
        assert isinstance(decision, Decision) and decision.kind == "fallback" and decision.action == "abstain" and decision.model is None
        assert [field.name for field in fields(Decision)] == ["kind", "model", "eligible", "explore", "action"]
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(ResponseLedgerRecord)) == ledger_rows
    # With V3 off the fallback row notes v3_off and no item is created.
    with fresh_v3_sessions() as (factory, _engine):
        shadow_record(factory)
        settings = ranking_settings(v3_queue="off", model_gateway_kill_switch="abstain_only")
        commission_static(factory, settings=settings, clean=5, failed=20)
        scan(factory, settings=settings)
        assert {item["note"] for item in events_of(factory, "select")} == {"v3_off"}


# ===================================================================================================== AC-9-7


def _drift_log(block=None, *, errors: int = 30) -> Log:
    log = Log(block).models(A, B)
    log.batch("model-a", 25).batch("model-b", 25, v="0.5", k="0.5")
    for index in range(errors):
        log.outcome("model-a", 0 if index % 2 == 0 else 1)
    return log


def test_ac_9_7_a_cusum_alarm_raises_the_audit_to_the_x5_rate_holds_promotions_and_never_demotes():
    alarms = derived_of(_drift_log().events, "alarm")
    assert alarms and alarms[0]["stream"] == "model:model-a" and alarms[0]["p0"] == "0.05" and alarms[0]["p1"] == "0.15" and alarms[0]["h"] == "4"
    assert Decimal(alarms[0]["statistic"]) > Decimal("4")
    # h = 3.0 alarms earlier.
    lower = block_with(lambda block: block["cusum"].update(h="3.0"))
    first_default = [i for i, (k, _p) in enumerate(apply_all(_drift_log().events)[1]) if k == "alarm"][0]
    first_lower = [i for i, (k, _p) in enumerate(apply_all(_drift_log(lower).events)[1]) if k == "alarm"][0]
    assert first_lower < first_default
    # An alarm never demotes: with a strong prior no demotion follows the alarm.
    strong = Log().models(A, B, clean=2000)
    strong.batch("model-a", 25, v="0.5", k="0.5")
    for index in range(30):
        strong.outcome("model-a", 0 if index % 2 == 0 else 1, v="0.5", k="0.5")
    state, derived = apply_all(strong.events)
    assert [p for k, p in derived if k == "alarm"] and [p for k, p in derived if k == "demote"] == []
    assert state["contexts"][KEY2]["incumbent"] == "model-a" and state["holds"]
    # Promotions hold while the hold is open, and follow once it is released.
    for _ in range(4):
        strong.batch("model-b", 25)
    assert [p for k, p in apply_all(strong.events)[1] if k == "promote"] == []
    held_state = apply_all(strong.events)[0]
    assert held_state["contexts"][KEY2]["streaks"]["model-b"] >= 3   # far enough ahead for long enough: only the hold blocks it
    released = copy.deepcopy(strong)
    for hold_id in sorted(held_state["holds"]):
        released.add("hold_release", {"hold_id": hold_id})
    released.batch("model-b", 25)
    assert len([p for k, p in apply_all(released.events)[1] if k == "promote"]) == 1


def test_ac_9_7_the_scan_records_the_alarm_through_phase_6_and_releases_the_hold_when_the_window_closes():
    from sqlalchemy import select

    from app.db_models import V3Draw, V3Event
    from app.services.v3.contracts import CusumAlarm
    from app.services.v3.scan import run_scan as v3_scan
    from app.services.v3.scan import window_remaining
    from v3_fakes import append_all, fresh_v3_sessions, synthetic_deliveries

    with fresh_v3_sessions() as (factory, _engine):
        commission_static(factory)
        # Records of the static generator whose first pass failed (a V1 regeneration) drive model:extractive-d19-v1 up.
        from tutor_fakes import make_entry  # noqa: F401 - the legacy records below come from v3_fakes

        for _ in range(12):
            result = shadow_record(factory)
        rows = events_of(factory)
        scan(factory)
        # Inject an alarm through the controller's own path: a log the scan would write for 30 failing outcomes.
        state = stored_state(factory)
        assert state["models"][STATIC]["commissioned"] is True and result is not None
        log = Log().models(_candidates()[STATIC].as_dict())
        for _ in range(30):
            log.outcome(STATIC, 0)
        alarm = derived_of(log.events, "alarm")[0]
        row = CusumAlarm(stream=alarm["stream"], p0=float(alarm["p0"]), p1=float(alarm["p1"]), h=float(alarm["h"]),
                         statistic=float(alarm["statistic"]), observations=alarm["observations"], raised_at=alarm["created_at"], source="phase9-cusum")
        from app.services.v3.events import record_cusum_alarm

        with factory() as db:
            seq = record_cusum_alarm(row, settings=ranking_settings(), package=PACKAGE, db=db, now=FIXED_NOW)
            db.rollback()
        with factory() as db:
            assert db.get(V3Event, seq) is None  # with db= the alarm is inserted in the caller's session and not committed
        seq = record_cusum_alarm(row, settings=ranking_settings(), package=PACKAGE, session_factory=factory, now=FIXED_NOW)
        with factory() as db:
            event = db.get(V3Event, seq)
            payload = json.loads(event.payload)
            assert event.kind == "cusum_alarm" and payload["source"] == "phase9-cusum" and payload["statistic"] >= payload["h"]
            assert window_remaining(db, seq) == int(PACKAGE.v3.x5_window_deliveries)
        append_all(factory, synthetic_deliveries(2))
        v3_scan(settings=Settings(environment="development", v3_queue="shadow"), package=PACKAGE, session_factory=factory, now=FIXED_NOW)
        with factory() as db:
            draws = db.execute(select(V3Draw).order_by(V3Draw.ledger_seq)).scalars().all()
            assert [(d.rate_numerator, d.rate_denominator) for d in draws][-2:] == [(1, 5), (1, 5)]
            assert window_remaining(db, seq) == int(PACKAGE.v3.x5_window_deliveries) - 2
        assert rows is not None


def test_ac_9_7_with_v3_off_the_hold_stays_open():
    from v3_fakes import fresh_v3_sessions

    with fresh_v3_sessions() as (factory, _engine):
        commission_static(factory)
        log_state = stored_state(factory)
        assert log_state["holds"] == {}
        # A hold whose X5 window never closes (no V3 draws while V3 is off) is never released by the scan.
        from app.services.ranking.scan import append_inputs
        from v2_fakes import fresh_gateway

        with factory() as db:
            append_inputs(db, [("model_change", {"adapter_id": STATIC, "from_version": "p-0", "to_version": log_state["models"][STATIC]["version"],
                                                 "source": "package"})], settings=ranking_settings(v3_queue="off"), package=PACKAGE, now=FIXED_NOW,
                          gateway=fresh_gateway())
            db.commit()
        state = stored_state(factory)
        assert len(state["holds"]) == 1
        scan(factory, settings=ranking_settings(v3_queue="off"))
        assert len(stored_state(factory)["holds"]) == 1 and events_of(factory, "hold_release") == []


# ===================================================================================================== AC-9-8


def _scanned_factory_log():
    return None


def test_ac_9_8_one_event_log_replayed_twice_gives_byte_identical_final_states():
    from sqlalchemy import insert

    from app.db_models import RankingEvent, RankingState
    from app.services.ranking.replay import check, compare, load_log, replay
    from app.services.ranking.state import canonical
    from app.services.ranking.vocabulary import STATE_KEY
    from app.workers.ranking import clear_stop, replay_check
    from v3_fakes import fresh_v3_sessions

    with fresh_v3_sessions() as (factory, _engine):
        commission_static(factory)
        for _ in range(3):
            shadow_record(factory)
        scan(factory)
        with factory() as db:
            rows, stored = load_log(db)
            assert check(db).ok
        first, second = replay(rows), replay(rows)
        assert canonical(first.state) == canonical(second.state) == stored.encode("utf-8")
        assert first.derived == second.derived and first.checkpoints == second.checkpoints
        code = ("import json, sys; sys.path.insert(0, sys.argv[1]); from app.services.ranking.replay import replay; "
                "from app.services.ranking.state import canonical; rows = json.load(sys.stdin); "
                "sys.stdout.write(canonical(replay(rows).state).decode())")
        other = subprocess.run([sys.executable, "-c", code, str(API_ROOT)], input=json.dumps(rows), capture_output=True, text=True, timeout=120)
        assert other.returncode == 0, other.stderr[-2000:]
        assert other.stdout == stored
        # A stop row does not change the replayed state.
        assert canonical(replay([*rows, {"seq": rows[-1]["seq"] + 1, "kind": "stop", "payload": "{}"}]).state) == canonical(first.state)
        # A deleted derived event (in a copy): a mismatch; and with the chain recomputed over the copy, still a mismatch,
        # found by the derived comparison itself.
        from app.services.ranking.replay import chain_sha256
        from app.services.ranking.vocabulary import GENESIS

        derived_index = next(index for index, row in enumerate(rows) if row["kind"] == "select")
        copy_rows = [dict(row) for index, row in enumerate(rows) if index != derived_index]
        assert not compare(copy_rows, stored).ok
        prev = GENESIS
        for row in copy_rows:
            row["prev_sha256"], row["sha256"] = prev, chain_sha256(prev, row["kind"], row["payload"])
            prev = row["sha256"]
        rechained = compare(copy_rows, stored)
        assert not rechained.ok and rechained.reason == "derived"
        # A tampered state: replay --check stops the ranking, the next scan is refused, clear-stop resyncs.
        with factory() as db:
            row = db.get(RankingState, STATE_KEY)
            row.payload = row.payload.replace('"requests":', '"requests":1')
            db.commit()
        ok, fields_ = replay_check(session_factory=factory, now=FIXED_NOW)
        assert not ok and fields_["reason"] == "state"
        assert events_of(factory)[-1]["kind"] == "stop" and events_of(factory)[-1]["payload"]["reason"] == "replay_mismatch"
        with pytest.raises(ranking.RankingStopped):
            scan(factory)
        assert clear_stop("fixed_data", session_factory=factory, now=FIXED_NOW)
        assert events_of(factory)[-1]["kind"] == "clear_stop"
        scan(factory)
        with factory() as db:
            assert check(db).ok
        # A wrong checkpoint: a mismatch.
        from app.services.ranking.scan import EventLog

        with factory() as db:
            log = EventLog(db, empty_state(), now=FIXED_NOW)
            log.control("checkpoint", {"state_sha256": "0" * 64, "last_input_seq": 0})
            db.commit()
        ok, fields_ = replay_check(session_factory=factory, now=FIXED_NOW)
        assert not ok and fields_["reason"] == "checkpoint"
        with factory() as db:
            db.execute(insert(RankingEvent).values(kind="tick", payload="{}", prev_sha256="0" * 64, sha256="1" * 64, observed_at=FIXED_NOW))
            db.commit()
            assert check(db).reason == "chain"


def test_ac_9_8_the_worker_replay_check_exits_1_on_a_mismatch_and_0_when_current():
    from app.db_models import RankingState
    from app.services.ranking.vocabulary import STATE_KEY
    from app.workers.ranking import main
    from v3_fakes import fresh_v3_sessions

    with fresh_v3_sessions() as (factory, _engine):
        commission_static(factory)
        shadow_record(factory)
        scan(factory)
        assert main(["replay", "--check"], session_factory=factory, now=FIXED_NOW) == 0
        with factory() as db:
            row = db.get(RankingState, STATE_KEY)
            row.payload = row.payload + " "
            db.commit()
        assert main(["replay", "--check"], session_factory=factory, now=FIXED_NOW) == 1
        assert main(["scan"], session_factory=factory, now=FIXED_NOW) == 2


# ===================================================================================================== plan J


def test_plan_j_hand_fixtures_beta_95_5_and_190_10():
    from app.services.ranking.package_check import hand_fixture_value

    assert hand_fixture_value(95, 5, "0.05") == "0.910"
    assert hand_fixture_value(190, 10, "0.05") == "0.922"
    committed = json.loads(FIXTURES.read_text(encoding="utf-8"))
    for fixture in committed["beta_lower_bounds"]:
        assert hand_fixture_value(fixture["alpha"], fixture["beta"], fixture["quantile"]) == fixture["lower_bound"]
    assert committed["beta_lower_bounds"][0]["lower_bound"] == "0.910" and committed["beta_lower_bounds"][1]["lower_bound"] == "0.922"
    from app.services.ranking.cusum import constants, update
    from app.services.ranking.numeric import to_str

    a, b = constants("0.05", "0.15")
    assert committed["cusum"]["A"] == to_str(a) and committed["cusum"]["B"] == to_str(b)
    statistic = "0"
    for step in committed["cusum"]["steps"]:
        statistic = to_str(update(statistic, step["e"], a, b))
        assert statistic == step["S"]
    from app.services.ranking.quality import ewma, quality
    from app.services.ranking.trust import update_trust

    worked = committed["worked_example"]
    alpha, beta, qbar = worked["alpha0"], worked["beta0"], worked["qbar0"]
    weights = {name: Decimal(value) for name, value in BLOCK["quality"]["weights"].items()}
    for step in worked["steps"]:
        alpha, beta = (to_str(value) for value in update_trust(alpha, beta, step["y"], "0.995"))
        signals = {name: (None if value is None else Decimal(value)) for name, value in step["signals"].items()}
        qbar = to_str(ewma(qbar, quality(signals, weights), "0.05"))
        assert (alpha, beta, qbar) == (step["alpha"], step["beta"], step["qbar"])


def test_plan_j_flapping_near_equal_models_switch_no_more_than_the_hysteresis_allows():
    inputs, meta = synthetic.build(BLOCK, "flapping")
    numbers = synthetic.measurements(synthetic.materialise(inputs), meta)
    assert int(numbers["switches_drift_free"]) * 1000 <= 2 * int(numbers["drift_free_requests"])
    # Without hysteresis (delta 0, n_d 1) the same streams switch more.
    loose = block_with(lambda block: block["promotion"].update(delta="0", n_d=1))
    inputs, meta = synthetic.build(loose, "flapping")
    looser = synthetic.measurements(synthetic.materialise(inputs), meta)
    assert int(looser["switches_drift_free"]) > int(numbers["switches_drift_free"])


def test_plan_j_outage_makes_a_model_ineligible_and_recovery_is_only_through_promotion():
    log = Log().models(A, B)
    log.batch("model-a", 25).batch("model-b", 25, v="0.9")
    log.add("availability", {"models": {"model-a": "down", "model-b": None}})
    state, derived = apply_all(log.events)
    assert [p["from"] for k, p in derived if k == "demote"] == ["model-a"] and state["contexts"][KEY2]["incumbent"] == "model-b"
    log.add("availability", {"models": {"model-a": None, "model-b": None}})
    log.batch("model-a", 25).batch("model-a", 25)
    state, derived = apply_all(log.events)
    assert state["contexts"][KEY2]["incumbent"] == "model-b" and [p for k, p in derived if k == "promote"] == []
    log.batch("model-a", 25)
    state, derived = apply_all(log.events)
    assert state["contexts"][KEY2]["incumbent"] == "model-a" and len([p for k, p in derived if k == "promote"]) == 1
    # Every model down: the fallback.
    log.add("availability", {"models": {"model-a": "down", "model-b": "down"}}).outcome("model-a")
    assert derived_of(log.events, "select")[-1]["kind"] == "fallback"


# ===================================================================================================== plan H


def test_plan_h_no_llm_decides_a_rank():
    # No language-model client anywhere in the ranking; the pure modules import no gateway at all (the scan reads gateway
    # availability, and the regression and the hook run the two-pass pipeline, whose V2 panel verifies: neither ranks).
    forbidden_modules = ("httpx", "requests", "openai", "anthropic", "google", "urllib", "app.services.learner_record", "app.services.learner_progress",
                         "app.services.learning_intelligence", "app.services.microlearning", "app.api", "app.core.auth", "random")
    pure = ("vocabulary", "numeric", "types", "state", "contexts", "signals", "trust", "quality", "score", "selection", "batch", "cusum",
            "controller", "replay", "synthetic")
    for path in sorted((API_ROOT / "app" / "services" / "ranking").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                assert not any(name == bad or name.startswith(bad + ".") for bad in forbidden_modules), (path.name, name)
                if path.stem in pure:
                    assert not name.startswith("app.gateway"), (path.name, name)
                    assert not name.startswith(("sqlalchemy", "app.core.db", "app.db_models", "time")) or path.stem == "replay", (path.name, name)
            if isinstance(node, ast.Attribute) and node.attr in ("generate", "verify", "complete", "chat"):
                raise AssertionError(f"{path.name} calls {node.attr}")


def test_plan_h_the_generator_never_sits_on_its_own_panel():
    from app.gateway.registry import GeneratorFamilyUnknown, generator_family, registry_for
    from app.services.ranking.generators import CloneGenerator
    from v1_fakes import run
    from v2_fakes import fresh_gateway, v2_pipeline

    settings = Settings(environment="development", model_gateway="shadow", ehmf="shadow", ranking="off")
    registry = registry_for(PACKAGE, settings)
    known = _candidates()
    assert set(known) == {STATIC, CLONE}
    for item in known.values():
        assert generator_family(PACKAGE, registry, item.adapter_id) == item.family
    with pytest.raises(GeneratorFamilyUnknown):
        generator_family(PACKAGE, registry, "unknown-generator")
    spec = next(member for member in registry.members if member.adapter_id == CLONE)
    pipeline = v2_pipeline(settings, gateway=fresh_gateway(), generator=CloneGenerator(spec, PACKAGE, settings=settings), v3_stop=lambda: False)
    entry = run(pipeline, TIER2, legacy_decision="answer").entry
    assert entry.versions.generator_id == CLONE and entry.verification.v2.generator_family == "fake-delta"
    assert "fake-delta" not in entry.verification.v2.members
    assert all("fake-delta" not in verdict.v2.members for verdict in entry.verification.verdicts if verdict.v2 is not None)


def test_plan_h_research_replay_only_in_the_research_environment(tmp_path):
    script = scripts_module("run_ranking_replay")
    assert script.main(["--check", str(REPO_ROOT / "lqs" / "replay.json")]) == 2
    private = PACKAGE.boundary.private_plane_globs[0].replace("**", "x").replace("*", "x")
    assert script.main(["--write", str(REPO_ROOT / private), "--allow-dirty"]) == 2
    source = (REPO_ROOT / "scripts" / "run_ranking_replay.py").read_text(encoding="utf-8")
    assert "DATABASE_URL" not in source and "SessionLocal" not in source and "--database" not in source
    # The synthetic streams, the fixtures and the report hold numbers and identifiers only: no string with a space outside
    # the documents' own about and evidence lines, and no text, query or claim field.
    tree = ast.parse((API_ROOT / "app" / "services" / "ranking" / "synthetic.py").read_text(encoding="utf-8"))
    docstrings = {id(node.body[0].value) for node in ast.walk(tree) if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
                  and node.body and isinstance(node.body[0], ast.Expr)}
    literals = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings]
    assert all(" " not in value or value.startswith("unknown scenario") for value in literals), [v for v in literals if " " in v]

    def strings(value, key=None):
        if isinstance(value, dict):
            for name, item in value.items():
                assert name not in ("text", "query", "claim", "claims"), name
                yield from strings(item, name)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item, key)
        elif isinstance(value, str) and key not in ("about", "evidence_class"):
            yield value

    for path in (FIXTURES, REPORT):
        assert all(" " not in value for value in strings(json.loads(path.read_text(encoding="utf-8")))), path.name


# ===================================================================================================== plan tasks


def test_plan_task_2_micro_batches_close_at_25_or_900_seconds_and_are_idempotent():
    log = Log().models(A)
    for index in range(24):
        log.outcome("model-a", t=index)
    log.tick(899)
    assert derived_of(log.events, "batch") == []
    log.tick(900)
    batches = derived_of(log.events, "batch")
    assert len(batches) == 1 and batches[0]["trigger"] == "time" and len(batches[0]["ledger_seqs"]) == 24
    # An outcome dated +900 s after the first pending one closes the earlier batch first.
    dated = Log().models(A)
    for index in range(5):
        dated.outcome("model-a", t=index)
    dated.outcome("model-a", t=900)
    batches = derived_of(dated.events, "batch")
    assert len(batches) == 1 and batches[0]["trigger"] == "time" and len(batches[0]["ledger_seqs"]) == 5
    count = Log().models(A).batch("model-a", 25)
    batches = derived_of(count.events, "batch")
    assert len(batches) == 1 and batches[0]["trigger"] == "count"
    # A rescan adds nothing (input_key ledger:<seq>; the cursor).
    from v3_fakes import fresh_v3_sessions

    with fresh_v3_sessions() as (factory, _engine):
        commission_static(factory)
        shadow_record(factory)
        scan(factory)
        before = [row for row in events_of(factory) if row["kind"] in ("outcome", "skipped")]
        scan(factory)
        assert [row for row in events_of(factory) if row["kind"] in ("outcome", "skipped")] == before
        from sqlalchemy import insert
        from sqlalchemy.exc import IntegrityError

        from app.db_models import RankingEvent

        with factory() as db:
            with pytest.raises(IntegrityError):
                db.execute(insert(RankingEvent).values(kind="skipped", payload="{}", prev_sha256="0" * 64, sha256="0" * 64, input_key=f"ledger:{before[0]['ledger_seq']}",
                                                       observed_at=FIXED_NOW))


def test_plan_task_1_trust_state_is_per_model_cluster_task_type_and_tier():
    from app.services.ranking.contexts import cluster_for, span_modules, task_type_for
    from app.services.store import get_course_store

    store = get_course_store()
    modules = span_modules(store)
    entry = _typed_entry()
    lesson_span = next(span_id for span_id, found in modules.items() if len(found) == 1)
    module_slug = next(iter(modules[lesson_span]))
    evidence = entry.retrieval.evidence[0].model_copy(update={"span_id": lesson_span})
    scoped = entry.model_copy(update={"retrieval": entry.retrieval.model_copy(update={"evidence": (evidence,)})})
    assert cluster_for(scoped, modules, store.corpus_version) == module_slug
    other_span = next(span_id for span_id, found in modules.items() if len(found) == 1 and module_slug not in found)
    mixed = scoped.model_copy(update={"retrieval": scoped.retrieval.model_copy(update={"evidence": (evidence, evidence.model_copy(update={"span_id": other_span}))})})
    assert cluster_for(mixed, modules, store.corpus_version) == "unscoped"
    empty = scoped.model_copy(update={"retrieval": scoped.retrieval.model_copy(update={"evidence": ()})})
    assert cluster_for(empty, modules, store.corpus_version) == "unscoped"
    assert cluster_for(scoped, modules, "corpus-other") == "unscoped"
    assert task_type_for(1, PACKAGE) == "quiz_item" and task_type_for(2, PACKAGE) == "explanation"
    # A new context starts from the model's prior.
    log = Log().models(A, clean=40)
    log.batch("model-a", 25, cluster="nisq-hybrid-workflows")
    state, _ = apply_all(log.outcome("model-a", cluster="industry-use-cases").events)
    fresh = models_of(state, "industry-use-cases|explanation|2")["model-a"]
    assert (fresh["alpha"], fresh["beta"], fresh["n"]) == ("41", "1", 0)
    assert models_of(state, "nisq-hybrid-workflows|explanation|2")["model-a"]["n"] == 25


def test_plan_task_6_cost_and_latency_penalties_are_operator_policy(tmp_path):
    assert BLOCK["penalties"] == {"lambda_u": "0", "lambda_l": "0", "cost_rule": "cost-units-over-max-v1", "latency_target_ms": None,
                                  "operator_policy": "D-06", "record": "PD-56"}
    known = _candidates()
    assert known[STATIC].cost_units_per_call == 0 and known[CLONE].cost_units_per_call == 1
    outcome = _outcome(_typed_entry())
    assert outcome.cost_units == 0 and outcome.latency_ms is None
    with pytest.raises(ConfigPackageError, match="lambda_u = lambda_l = 0"):
        load_config_package(package_copy(tmp_path, lambda payload: payload["ranking"]["penalties"].update(lambda_u="0.1")), governed=False)


def test_plan_f_the_parameter_package_is_provisional_and_the_controller_reads_it():
    assert BLOCK["provisional"] is True and BLOCK["parameters_version"] == "ranking-params-v1"
    assert BLOCK["trust"]["gamma"] == "0.995" and BLOCK["quality"]["weights"] == {"V": "0.35", "S": "0.30", "K": "0.15", "F": "0.20"}
    assert BLOCK["quality"]["eta"] == "0.05" and BLOCK["ratings"] == {"A": "0.95", "B": "0.90", "C": "0.80"}
    assert BLOCK["selection"]["eps_s"] == "0.05" and (BLOCK["promotion"]["delta"], BLOCK["promotion"]["n_d"]) == ("0.05", 3)
    assert (BLOCK["cusum"]["p0"], BLOCK["cusum"]["p1"], BLOCK["cusum"]["h"]) == ("0.05", "0.15", "4.0")
    assert BLOCK["recommission"]["deflation"] == "0.3" and BLOCK["recommission"]["golden_set"]["target_items"] == 50
    # A config event mid-log changes behaviour from that point; the replay uses the block in the log, not the file.
    log = _promotion_log(batches=2)
    changed = block_with(lambda block: block["promotion"].update(n_d=2))
    log.add("config", {"package_version": "test", "package_sha256": "0" * 64, "parameters_sha256": canonical_sha256(changed), "parameters": changed})
    log.batch("model-b", 25)
    state, derived = apply_all(log.events)
    assert state["parameters"]["promotion"]["n_d"] == 2 and len([p for k, p in derived if k == "promote"]) == 1
    tampered = copy.deepcopy(log.events)
    tampered[0]["payload"]["parameters_sha256"] = "0" * 64
    from app.services.ranking.controller import RankingInputError

    with pytest.raises(RankingInputError):
        apply_all(tampered)


def test_plan_f_the_replay_report_is_current(tmp_path):
    import time

    script = scripts_module("run_ranking_replay")
    started = time.perf_counter()
    assert script.main(["--check", str(REPORT)]) == 0
    assert time.perf_counter() - started < 60
    record = json.loads(REPORT.read_text(encoding="utf-8"))
    assert record["evidence_class"].startswith("engineering measurement on synthetic streams, not E4 results")
    assert [item["id"] for item in record["scenarios"]] == list(synthetic.SCENARIOS) and all(item["replays_equal"] for item in record["scenarios"])
    flapping = next(item for item in record["scenarios"] if item["id"] == "flapping")
    assert int(flapping["switches_drift_free"]) * 1000 <= 2 * int(flapping["drift_free_requests"])
    pinned = copy.deepcopy(record)
    pinned["pins"]["ranking_parameters"]["sha256"] = "0" * 64
    (tmp_path / "pins.json").write_text(json.dumps(pinned), encoding="utf-8")
    assert script.main(["--check", str(tmp_path / "pins.json")]) == 6
    drifted = copy.deepcopy(record)
    drifted["scenarios"][0]["derived_sha256"] = "0" * 64
    (tmp_path / "drift.json").write_text(json.dumps(drifted), encoding="utf-8")
    assert script.main(["--check", str(tmp_path / "drift.json")]) == 1


def test_plan_f_a_replay_mismatch_exits_7(monkeypatch):
    script = scripts_module("run_ranking_replay")
    from app.services.ranking import replay as replay_module

    original = replay_module.replay
    calls = {"n": 0}

    def flaky(events):
        calls["n"] += 1
        result = original(events)
        if calls["n"] % 2 == 0:
            result.state["counts"]["requests"] += 1
        return result

    monkeypatch.setattr(replay_module, "replay", flaky)
    assert script.main(["--check", str(REPORT)]) == 7


# ===================================================================================================== plan I


def test_plan_i_ready_reports_static_ranking_values_and_the_stop_and_no_count(monkeypatch):
    from sqlalchemy import event

    from app import main as main_module
    from app.core.db import engine
    from app.services.ranking.replay import reset_stop_cache

    fields_ = main_module._build_fields()
    assert {"ranking_mode", "ranking_setting", "phase9_exit_passed", "ranking"} <= set(fields_)
    block = fields_["ranking"]
    assert set(block) == {"version", "parameters_version", "parameters_sha256", "provisional", "cluster_rule", "active_task_types", "live_routing",
                          "decision", "hold", "shadow_generation", "stop", "available"}
    assert (block["live_routing"], block["decision"], block["hold"]) == ("refused", "D-28", "H11") and fields_["phase9_exit_passed"] is False
    statements = []

    def watch(_conn, _cursor, statement, *_args):
        statements.append(statement)

    off = Settings(environment="development", ranking="off")
    monkeypatch.setattr(main_module, "settings", off)
    reset_stop_cache()
    event.listen(engine, "before_cursor_execute", watch)
    try:
        assert main_module._ranking_fields(PACKAGE)["stop"] == {"stopped": None}
        assert not any("ranking_events" in statement for statement in statements)
        monkeypatch.setattr(main_module, "settings", ranking_settings())
        reset_stop_cache()
        statements.clear()
        main_module._ranking_fields(PACKAGE)
        assert [statement for statement in statements if "ranking_events" in statement]
        statements.clear()
        main_module._ranking_fields(PACKAGE)
        assert not [statement for statement in statements if "ranking_events" in statement]  # cached for stop_refresh_s
    finally:
        event.remove(engine, "before_cursor_execute", watch)
    for forbidden in ("requests", "fallbacks", "incumbent", "rating", "alpha"):
        assert forbidden not in json.dumps(block)


def test_plan_i_metrics_report_micro_batch_latency_switch_rate_fallback_rate_and_cost():
    from app.services.ranking.metrics import slis
    from v3_fakes import fresh_v3_sessions

    with fresh_v3_sessions() as (factory, _engine):
        commission_static(factory)
        for _ in range(2):
            shadow_record(factory)
        scan(factory)
        with factory() as db:
            body = slis(db, PACKAGE)
    assert {"micro_batch_latency_s", "switch_rate_per_1000", "fallback_rate", "exploration_share", "cost_units_mean", "latency", "ratings",
            "cusum", "skipped", "holds_open", "replay", "evidence_class"} <= set(body)
    assert body["evidence_class"] == "telemetry, not E4 results (invariant 9)" and body["latency"] is None
    assert body["cost_units_mean"] == {STATIC: "0"} and body["fallback_rate"] == "0"


# ===================================================================================================== plan L


def test_plan_l_rollback_to_static_assignment_keeps_the_event_log_alarms_and_x5_windows():
    from sqlalchemy import func, select

    from app.db_models import RankingEvent, V3Event
    from v3_fakes import fresh_v3_sessions

    with fresh_v3_sessions() as (factory, _engine):
        commission_static(factory)
        shadow_record(factory)
        scan(factory)
        with factory() as db:
            rows = db.scalar(select(func.count()).select_from(RankingEvent))
            windows = db.scalar(select(func.count()).select_from(V3Event))
        with pytest.raises(ranking.RankingOff):
            scan(factory, settings=ranking_settings(ranking="off"))
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(RankingEvent)) == rows
            assert db.scalar(select(func.count()).select_from(V3Event)) == windows
    assert ranking.mode(Settings(environment="development", ranking="off"), PACKAGE) == "off"


def test_plan_l_the_scan_refuses_while_the_static_generator_is_uncommissioned():
    from sqlalchemy import func, select

    from app.db_models import V3QueueItem
    from app.workers.ranking import main
    from v3_fakes import fresh_v3_sessions

    with fresh_v3_sessions() as (factory, _engine):
        shadow_record(factory)
        with pytest.raises(ranking.RankingUncommissioned):
            scan(factory)
        assert events_of(factory, "outcome") == [] and events_of(factory, "skipped") == []
        assert {row["kind"] for row in events_of(factory)} <= {"config", "model_seen", "availability", "checkpoint"}
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(V3QueueItem)) == 0
        assert main(["scan"], session_factory=factory, now=FIXED_NOW) == 2
        assert main(["commission", STATIC], session_factory=factory, now=FIXED_NOW) == 0
        commissioned = next(row for row in events_of(factory, "commission"))
        assert commissioned["payload"]["generated"] == 40 and commissioned["payload"]["failed"] == 0
        scan(factory)
        assert len(events_of(factory, "outcome")) == 1


def test_plan_l_the_scan_takes_the_ranking_then_the_v3_lock():
    source = (API_ROOT / "app" / "services" / "ranking" / "scan.py").read_text(encoding="utf-8")
    body = source.split("def _scan_once(", 1)[1]
    first, second = body.index("RANKING_SCAN_LOCK_KEY"), body.index("V3_SCAN_LOCK_KEY}")
    assert first < second < body.index("_load_state(db)")
    inputs = source.split("def append_inputs(", 1)[1]
    assert inputs.index("RANKING_SCAN_LOCK_KEY") < inputs.index("V3_SCAN_LOCK_KEY}") < inputs.index("_load_state(db)")
    from app.services.ranking.vocabulary import RANKING_SCAN_LOCK_KEY
    from app.services.v3.scan import V3_SCAN_LOCK_KEY

    assert RANKING_SCAN_LOCK_KEY == 7_401_209 and V3_SCAN_LOCK_KEY == 7_401_206
    # No other writer takes V3's lock and then the ranking lock.
    for path in (API_ROOT / "app").rglob("*.py"):
        if path.name != "scan.py" or "ranking" not in path.parts:
            assert "RANKING_SCAN_LOCK_KEY" not in path.read_text(encoding="utf-8") or path.name == "vocabulary.py", path


# ===================================================================================================== freeze


def test_freeze_ranking_is_off_outside_development_and_on_is_refused_everywhere():
    from pydantic import ValidationError

    production = Settings(environment="production", allowed_origins=["https://qantumlearn.academy"])
    staging = Settings(environment="staging", allowed_origins=["https://staging.example.test"], guest_token_secret="s" * 32)
    for settings in (production, staging):
        assert settings.ranking == "off" and ranking.mode(settings, PACKAGE) == "off" and settings.ranking_shadow_generation is False
    assert Settings(environment="development").ranking == "shadow"
    for options in ({"environment": "development"}, {"environment": "staging", "allowed_origins": ["https://staging.example.test"], "guest_token_secret": "s" * 32},
                    {"environment": "production", "allowed_origins": ["https://qantumlearn.academy"]}):
        with pytest.raises(ValidationError, match="D-28"):
            Settings(ranking="on", **options)
    with pytest.raises(ValidationError, match="development-only"):
        Settings(environment="staging", allowed_origins=["https://staging.example.test"], guest_token_secret="s" * 32, ranking_shadow_generation=True)
    assert PACKAGE.raw["flag_policy"]["ranking"]["default_elsewhere"] == "off" and PACKAGE.owner_decisions["D-28"]["state"] == "open"


def test_freeze_no_learner_path_changes_and_the_payload_golden_is_unchanged():
    capture = scripts_module("capture_public_payloads")
    assert capture.main(["--check", str(API_ROOT / "tests" / "data" / "phase4_public_payloads_v1.json")]) == 0
    from v3_fakes import fresh_v3_sessions

    def records(setting: str) -> list:
        with fresh_v3_sessions() as (factory, _engine):
            result = shadow_record(factory, settings=Settings(environment="development", model_gateway="shadow", ehmf="shadow", ranking=setting))
            entry = json.loads(result.entry.model_dump_json())
        for key in ("response_id", "shadowed_response_id"):
            entry.pop(key)
        entry["versions"].pop("code_sha")
        entry["claims"] = [{k: v for k, v in claim.items() if k != "response_id"} for claim in entry["claims"]]
        return json.dumps(entry, sort_keys=True)

    text = records("shadow")
    assert re.sub(r"(shadow|turn|message)-[0-9a-f-]{36}", "id", text) == re.sub(r"(shadow|turn|message)-[0-9a-f-]{36}", "id", records("off"))


# ===================================================================================================== plan G


def test_plan_g_shadow_generation_writes_only_undelivered_shadow_records(caplog):
    from sqlalchemy import select

    from app.db_models import ResponseLedgerRecord
    from app.services.ledger import ledger_provenance
    from app.services.ranking import hook
    from app.services.ranking.hook import guarded_after_shadow
    from v3_fakes import fresh_v3_sessions

    with fresh_v3_sessions() as (factory, _engine):
        commission_static(factory)
        clone = _candidates()[CLONE]
        from app.services.ranking.scan import append_inputs
        from v2_fakes import fresh_gateway

        with factory() as db:
            append_inputs(db, [("commission", {"adapter_id": CLONE, "version": clone.model_version, "clean": 200, "failed": 0, "generated": 200,
                                               "mean_q": "0.99", "run_sha256": "0" * 64})], settings=ranking_settings(), package=PACKAGE,
                          now=FIXED_NOW, gateway=fresh_gateway())
            db.commit()
        result = shadow_record(factory)
        settings = ranking_settings(ranking_shadow_generation=True)
        decision = hook.select(hook.context_of(result.entry, package=PACKAGE), ledger_seq=result.appended.seq, settings=settings, package=PACKAGE,
                               session_factory=factory)
        assert decision.kind == "incumbent"

        class Job:
            thread_id, user_message_id, lesson_slug, legacy_decision = "t", "m", None, "answer"
            shadowed_response_id = result.entry.shadowed_response_id
            from app.services.tutor_pipeline.contracts import PresentationPlan

            presentation = PresentationPlan(plan_id="concise", source="request")

        from unittest import mock

        from v2_fakes import v2_pipeline

        def factory_pipeline():
            return v2_pipeline(Settings(environment="development", model_gateway="shadow", ehmf="shadow", ranking="shadow"), gateway=fresh_gateway(),
                               session_factory=factory, v3_stop=lambda: False)

        with mock.patch("app.services.tutor_pipeline.resolve.resolve_thread", return_value=result.envelope_resolved if hasattr(result, "envelope_resolved") else None):
            from app.services.tutor_pipeline.resolve import LearnerTurn, resolve_turns

            resolved = resolve_turns([], LearnerTurn("message-00000000-0000-0000-0000-000000000001", TIER2), package=PACKAGE)
            with mock.patch("app.services.tutor_pipeline.resolve.resolve_thread", return_value=resolved):
                import time

                # The incumbent is the clone (the higher commissioning prior), so the hook runs one clone shadow record.
                if decision.model != CLONE and decision.explore is None:
                    pytest.skip("the commissioned incumbent is the static generator")
                guarded_after_shadow(Job, result, pipeline_factory=factory_pipeline, settings=settings, session_factory=factory, started=time.perf_counter())
        with factory() as db:
            rows = db.execute(select(ResponseLedgerRecord.delivery, ResponseLedgerRecord.entry).order_by(ResponseLedgerRecord.seq)).all()
        assert [row.delivery for row in rows] == ["shadow", "shadow"]
        assert json.loads(rows[1].entry)["versions"]["generator_id"] == CLONE
        with factory() as db:
            provenance = ledger_provenance(db, PACKAGE)
        assert provenance["problems"] == []
        # A raising clone is logged and swallowed.
        with caplog.at_level(logging.WARNING, logger="qcai.ranking"):
            guarded_after_shadow(Job, result, pipeline_factory=lambda: (_ for _ in ()).throw(RuntimeError("boom")), settings=settings,
                                 session_factory=factory, started=time.perf_counter())
        assert any(getattr(record, "event", None) == "ranking.shadow_generation_failed" or "shadow generation failed" in record.getMessage()
                   for record in caplog.records)
        # The scan's later select for the record draws what the hook drew.
        scan(factory)
        scanned = next(item for item in events_of(factory, "select") if item["ledger_seq"] == result.appended.seq)
        assert scanned["payload"]["explore"] == decision.explore


# ===================================================================================================== plan E


def test_plan_e_the_phase_9_revision_is_additive_reversible_and_keeps_its_rows():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    from app.services.ledger import SCHEMA_REVISION
    from v3_fakes import fresh_v3_sessions

    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [SCHEMA_REVISION] == ["20261123_phase9_ranking"]
    revision = script.get_revision(SCHEMA_REVISION)
    assert revision.down_revision == "20261123_phase7_ehmf"
    source = Path(revision.path).read_text(encoding="utf-8")
    assert "allow_ranking_drop" in source and "DROP FUNCTION" not in source
    with fresh_v3_sessions() as (factory, engine):
        from app.services.ranking.scan import EventLog

        with factory() as db:
            log = EventLog(db, empty_state(), now=FIXED_NOW)
            for kind in EVENT_KINDS:
                log.control(kind, {"kind": kind})
            db.commit()
        assert [row["kind"] for row in events_of(factory)] == list(EVENT_KINDS)
        for statement in ("UPDATE ranking_events SET note = 'x'", "DELETE FROM ranking_events", "UPDATE ranking_scans SET records = 1"):
            with pytest.raises(Exception, match="append-only|no such|0 rows") if "scans" in statement else pytest.raises(Exception, match="append-only"):
                with engine.begin() as connection:
                    connection.execute(text(statement))
                    if "scans" in statement:
                        raise RuntimeError("append-only (no scan row to update)")


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess:
    import os

    env = {**os.environ, "DATABASE_URL": database_url, "ENVIRONMENT": "development", "PYTHONUNBUFFERED": "1"}
    env.pop("CLOUD_SQL_CONNECTION_NAME", None)
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=API_ROOT, env=env, capture_output=True, text=True, timeout=240)


def test_plan_e_the_phase_9_downgrade_refuses_while_ranking_events_holds_rows_and_the_tables_refuse_truncate(fresh_database_url):
    from sqlalchemy import create_engine, text
    from sqlalchemy import inspect as sa_inspect

    from app.core.db import Base
    from app.core.schema_upgrades import run_schema_upgrades
    from app.services.ledger import SCHEMA_REVISION

    connect_args = {"check_same_thread": False} if fresh_database_url.startswith("sqlite") else {}
    engine = create_engine(fresh_database_url, connect_args=connect_args)
    phase9 = {"ranking_events", "ranking_scans", "ranking_states", "ranking_incumbents"}
    try:
        Base.metadata.create_all(engine)
        run_schema_upgrades(engine)
        others = set(sa_inspect(engine).get_table_names()) - phase9
        with engine.begin() as connection:
            for kind in EVENT_KINDS:  # every kind fits its column on this dialect (varchar(24) on PostgreSQL)
                connection.execute(text("INSERT INTO ranking_events (kind, payload, prev_sha256, sha256, observed_at) VALUES (:kind, '{}', :sha, :sha, :now)"),
                                   {"kind": kind, "sha": "0" * 64, "now": FIXED_NOW})
            connection.execute(text("INSERT INTO ranking_scans (from_seq, to_seq, records, outcomes, skipped, batches, alarms, fallbacks, package_version, "
                                    "package_sha256, created_at) VALUES (0, 0, 0, 0, 0, 0, 0, 0, '7.0.0', :sha, :now)"), {"sha": "0" * 64, "now": FIXED_NOW})
        statements = ["UPDATE ranking_events SET note = 'x'", "DELETE FROM ranking_events", "UPDATE ranking_scans SET records = 1", "DELETE FROM ranking_scans"]
        if engine.dialect.name == "postgresql":
            statements += ["TRUNCATE ranking_events", "TRUNCATE ranking_scans"]
        for statement in statements:
            with pytest.raises(Exception, match="append-only"):
                with engine.begin() as connection:
                    connection.execute(text(statement))
        engine.dispose()
        assert _alembic(fresh_database_url, "stamp", SCHEMA_REVISION).returncode == 0
        refused = _alembic(fresh_database_url, "downgrade", "20261123_phase7_ehmf")
        assert refused.returncode != 0 and f"ranking_events holds {len(EVENT_KINDS)} rows" in refused.stderr, refused.stderr[-2000:]
        assert "allow_ranking_drop=true" in refused.stderr and "python -m app.workers.ranking status" in refused.stderr
        assert phase9 <= set(sa_inspect(engine).get_table_names())
        engine.dispose()
        dropped = _alembic(fresh_database_url, "-x", "allow_ranking_drop=true", "downgrade", "20261123_phase7_ehmf")
        assert dropped.returncode == 0, dropped.stderr[-2000:]
        remaining = set(sa_inspect(engine).get_table_names())
        assert not (phase9 & remaining) and remaining - {"alembic_version"} == others - {"alembic_version"}
    finally:
        engine.dispose()


# ===================================================================================================== source and docs


def test_phase9_no_new_source_literal_starts_with_qcai_():
    prefix = "qcai" + "_"
    sources = [*(API_ROOT / "app" / "services" / "ranking").glob("*.py"), API_ROOT / "app" / "workers" / "ranking.py",
               REPO_ROOT / "scripts" / "run_ranking_replay.py", API_ROOT / "tests" / "ranking_fakes.py", API_ROOT / "tests" / "test_ranking_units.py",
               API_ROOT / "alembic" / "versions" / "20261123_phase9_ranking.py", Path(__file__)]
    offenders = []
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith(prefix):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def test_phase9_docs_quote_the_plan_and_state_the_current_rules():
    spec = spec_text()
    plan_p = "AC-9-1 to AC-9-8 green; staging shadow run; live routing OFF pending E4 [Decision D-28]."
    plan_l = "Flag to static assignment, alarms retained. Stop: a replay mismatch."
    assert plan_p in spec and "Stop: a replay mismatch." in spec
    adr = (REPO_ROOT / "docs" / "adr" / "ADR-011-verified-trust-ranking.md").read_text(encoding="utf-8")
    assert "[Risk R-23][Risk R-24][Risk R-20][Risk R-47]; residual: silent provider changes." in adr
    assert "If ranking does not beat static assignment (H4a), static assignment stays" in " ".join(adr.split())
    runbook = (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8")
    section = runbook.split("## Phase 9: verified-trust ranking (runbook)", 1)[1]
    for phrase in ("allow_ranking_drop", "commission", "clear-stop", "RANKING=off", "replay --check"):
        assert phrase in section, phrase
    assert plan_l in " ".join(section.split()) or "Flag to static assignment, alarms retained" in section
    head = spec.split("\n## 18. Review history\n", 1)[0]
    for number in range(50, 60):
        assert f"| PD-{number} |" in head
    for number in range(115, 129):
        assert f"| DI-{number} |" in head
    assert "### Renumbering the Phase 9 package (E16)" in spec
    for conflict in ("1. **Algorithm 1 line 6", "12. **Table X", "26. **Operational precondition"):
        assert conflict in spec, conflict


def test_phase9_docs_the_test_strategy_maps_every_test_module_the_phase_added():
    strategy = (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
    section = strategy.split("## Phase 9 acceptance map (plan Phase 9 K)", 1)[1]
    for name in PHASE9_TEST_MODULES:
        assert f"`{name}`" in section, name
    for ac in range(1, 9):
        assert f"AC-9-{ac}" in section
    assert "**Exit gate.**" in section


def test_phase9_spec_section_3_lists_the_code_s_fields():
    from app.services.ranking import types

    spec = spec_text()
    section = spec.split("### 3.2 Runtime types", 1)[1].split("### 3.4", 1)[0]
    for cls in (types.Context, types.ModelRef, types.Signals, types.Outcome, types.Skip, types.Decision):
        block = section.split(f"class {cls.__name__}", 1)[1].split("@dataclass", 1)[0]
        for field in fields(cls):
            assert re.search(rf"\b{field.name}\s*:", block), (cls.__name__, field.name)
    state_section = section.split("### 3.3", 1)[1]
    for key in empty_state():
        assert f'"{key}"' in state_section, key
    for key in empty_state()["counts"]:
        assert f'"{key}"' in state_section, key


def test_phase9_docs_the_spec_ends_in_one_review_history_table():
    spec = spec_text()
    head, history = spec.split("\n## 18. Review history\n", 1)
    assert "## 18." not in head and history.count("| Round | Commit |") == 1
    assert re.findall(r"\b[Rr]eview \d+\b(?![/.\d])", head) == []
    names = set()
    for path in (API_ROOT / "tests").glob("test_*.py"):
        names |= set(re.findall(r"^def (test_\w+)\(", path.read_text(encoding="utf-8"), flags=re.MULTILINE))
    for name in re.findall(r"`(test_[a-z0-9_]+)`", spec):
        assert name in names or name.endswith("_") or name.endswith("..."), name
    assert SPEC_PATH.read_bytes().count(b"\r\n") == 0
