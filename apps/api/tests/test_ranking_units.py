"""Phase 9 unit tests: the ranking numerics, signals, trust, quality, score, selection, CUSUM, the package loader's ranking
rules and the V3 helpers the ranking scan uses (Phase 9 spec 13.2). Pure functions and fresh in-memory databases."""

from __future__ import annotations

import ast
from decimal import Decimal, getcontext, localcontext
import json
import math

import pytest

from app.core.config_package import (
    DEFAULT_PACKAGE_PATH,
    EHMF_SCHEMA_VERSION,
    LATEST_SCHEMA_VERSION,
    RANKING_SCHEMA_VERSION,
    V7_PACKAGE_PATH,
    LEARNER_SCHEMA_VERSION,
    ConfigPackageError,
    load_config_package,
)
from app.services.ranking import numeric
from app.services.ranking.cusum import constants, update
from app.services.ranking.numeric import D, beta_quantile, log_gamma, reg_inc_beta, to_str, uniform
from app.services.ranking.quality import ewma, quality
from app.services.ranking.score import cost_share, score
from app.services.ranking.trust import permits, rating
from app.services.ranking.vocabulary import CLUSTERS, EVENT_KINDS, RANKING_FIRST_MAJOR
from ranking_fakes import BLOCK, PACKAGE, REPO_ROOT, Log, apply_all, model, package_copy

API_ROOT = REPO_ROOT / "apps" / "api"
PERMISSIONS = {"A": (1, 2, 3), "B": (2, 3), "C": (), "D": ()}
RATINGS = {"A": Decimal("0.95"), "B": Decimal("0.90"), "C": Decimal("0.80")}


# ------------------------------------------------------------------------------------------------- numerics


def test_log_gamma_matches_math_lgamma():
    for x in ("0.5", "1", "2.5", "7", "29.9", "41", "190.25", "1000"):
        assert abs(float(log_gamma(x)) - math.lgamma(float(x))) < 1e-12, x


def test_reg_inc_beta_endpoints_symmetry_and_the_quantile_is_monotone_and_bounded():
    assert reg_inc_beta("0", "3", "4") == 0 and reg_inc_beta("1", "3", "4") == 1
    for x in ("0.1", "0.4", "0.75"):
        left = reg_inc_beta(x, "3.5", "2")
        right = reg_inc_beta(str(1 - Decimal(x)), "2", "3.5")
        assert abs(left + right - 1) < Decimal("1e-20")
    previous = Decimal(0)
    for alpha in (5, 20, 60, 200):
        value = beta_quantile("0.05", alpha, 5)
        assert previous < value < 1
        previous = value
    assert beta_quantile("0.05", 40, 5) > beta_quantile("0.05", 40, 10)
    assert beta_quantile("0.05", 1, 1) == Decimal("0.05")


def test_numeric_refuses_a_float_and_gives_the_same_bytes_under_another_ambient_context():
    with pytest.raises(TypeError):
        D(0.5)
    with pytest.raises(TypeError):
        D(True)
    numeric._beta_quantile.cache_clear()
    reference = (to_str(beta_quantile("0.05", "95.5", "5.25")), to_str(quality({"V": D("0.3333"), "K": D("0.7"), "H": D("0.1"), "S": None, "F": None},
                                                                                  {k: D(v) for k, v in BLOCK["quality"]["weights"].items()})))
    numeric._beta_quantile.cache_clear()
    with localcontext() as ambient:
        ambient.prec = 5
        getcontext().rounding = "ROUND_DOWN"
        again = (to_str(beta_quantile("0.05", "95.5", "5.25")), to_str(quality({"V": D("0.3333"), "K": D("0.7"), "H": D("0.1"), "S": None, "F": None},
                                                                                {k: D(v) for k, v in BLOCK["quality"]["weights"].items()})))
        state_a, _ = apply_all(Log().models(model("m-a", "f-a"), model("m-b", "f-b")).batch("m-a", 30, v="0.3").batch("m-b", 30).events)
    assert again == reference
    state_b, _ = apply_all(Log().models(model("m-a", "f-a"), model("m-b", "f-b")).batch("m-a", 30, v="0.3").batch("m-b", 30).events)
    assert json.dumps(state_a, sort_keys=True) == json.dumps(state_b, sort_keys=True)
    assert to_str(Decimal("-0")) == "0" and to_str(Decimal("0E-18")) == "0" and to_str(Decimal("1.50")) == "1.5"


def test_the_bisection_takes_sixty_steps_and_the_draw_is_seeded():
    assert numeric.BISECTION_STEPS == 60
    assert uniform("seed", "a", "1") == uniform("seed", "a", "1") != uniform("seed", "a", "2")
    assert Decimal(0) <= uniform("seed", "x") < 1
    source = (API_ROOT / "app" / "services" / "ranking" / "numeric.py").read_text(encoding="utf-8")
    assert "import random" not in source and "from random" not in source


# ------------------------------------------------------------------------------------------------- signals, trust, quality, score


def test_k_is_one_minus_the_normalised_vote_entropy():
    from app.services.ranking.signals import vote_agreement

    assert vote_agreement(["SUPPORTED", "SUPPORTED", "SUPPORTED"]) == 1
    assert vote_agreement(["SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_INFO"]) == 0
    two_one = 1 - (-(Decimal(2) / 3 * (Decimal(2) / 3).ln() + Decimal(1) / 3 * (Decimal(1) / 3).ln())) / Decimal(3).ln()
    assert abs(vote_agreement(["SUPPORTED", "SUPPORTED", "CONTRADICTED"]) - two_one) < Decimal("1e-17")


def test_quality_renormalises_over_the_present_signals_and_the_score_subtracts_the_penalties():
    weights = {k: D(v) for k, v in BLOCK["quality"]["weights"].items()}
    assert quality({"V": D(1), "S": None, "K": D(0), "F": None, "H": None}, weights) == D("0.7")
    assert quality({"V": D(1), "S": None, "K": D(1), "F": None, "H": D("0.5")}, weights) == D("0.5")
    # Every value is quantised to 1e-18 (q()): a third stays at 18 places.
    third = quality({"V": D(1), "S": None, "K": None, "F": None, "H": D("0.333333333333333333333333")}, weights)
    assert third == D("0.666666666666666667") and third.as_tuple().exponent == -18
    assert quality({"V": None, "S": None, "K": None, "F": None, "H": None}, weights) == 0
    assert ewma("0.5", "1", "0.05") == D("0.525")
    assert cost_share(1, 0) == 0 and cost_share(1, 4) == D("0.25")
    assert score("0.9", "0.8", u="0.5", latency_excess="0", lambda_u="0.1", lambda_l="0") == D("0.67")


def test_rating_and_tier_permissions_follow_sec_vii_b():
    assert [rating(D(t), RATINGS, capped=False) for t in ("0.96", "0.95", "0.94", "0.90", "0.85", "0.80", "0.79")] == ["A", "A", "B", "B", "C", "C", "D"]
    assert rating(D("0.99"), RATINGS, capped=True) == "C" and rating(D("0.5"), RATINGS, capped=True) == "D"
    assert permits("A", 1, a_available=True, permissions=PERMISSIONS, b_tier_1_when_no_a=True)
    assert permits("B", 1, a_available=False, permissions=PERMISSIONS, b_tier_1_when_no_a=True)
    assert not permits("B", 1, a_available=True, permissions=PERMISSIONS, b_tier_1_when_no_a=True)
    assert not permits("C", 3, a_available=False, permissions=PERMISSIONS, b_tier_1_when_no_a=True)


def test_selection_breaks_ties_by_adapter_id_and_the_first_incumbent_is_no_switch():
    from app.services.ranking.selection import argmax

    assert argmax({"m-b": D(1), "m-a": D(1), "m-c": D("0.5")}) == "m-a"
    state, derived = apply_all(Log().models(model("m-b", "f-b"), model("m-a", "f-a")).outcome("m-a").events)
    selects = [payload for kind, payload in derived if kind == "select"]
    assert selects[0]["model"] == "m-a" and state["counts"]["switches"] == 0
    # The seeded Thompson draw repeats.
    first, _ = apply_all(Log().models(model("m-a", "f-a"), model("m-b", "f-b")).batch("m-a", 200).events)
    second, _ = apply_all(Log().models(model("m-a", "f-a"), model("m-b", "f-b")).batch("m-a", 200).events)
    assert first["counts"]["explorations"] == second["counts"]["explorations"] > 0


def test_cusum_constants_steps_reset_and_sustained():
    a, b = constants("0.05", "0.15")
    assert a == numeric.q(Decimal(3).ln()) and b == numeric.q((Decimal(17) / 19).ln())
    assert update("0", 1, a, b) == a and update("0", 0, a, b) == 0
    log = Log().models(model("m-a", "f-a"), model("m-b", "f-b"), clean=2000)
    for _ in range(40):
        log.outcome("m-a", 0)
    state, derived = apply_all(log.events)
    alarms = [payload for kind, payload in derived if kind == "alarm"]
    model_alarms = [item for item in alarms if item["stream"] == "model:m-a"]
    assert len(model_alarms) >= 2 and model_alarms[0]["sustained"] is False and model_alarms[1]["sustained"] is True
    assert state["counts"]["sustained"] >= 1 and len([k for k, _p in derived if k == "hold"]) == 2  # one hold per stream


def test_a_first_alarm_under_a_model_change_hold_is_not_sustained_and_opens_its_own_hold():
    # Sustained is a second alarm while the stream's alarm hold is open (second-alarm-while-held-v1): a model change's hold
    # on the same stream does not make the first alarm after the change sustained.
    log = Log().models(model("m-a", "f-a"), model("m-b", "f-b"), clean=2000)
    log.batch("m-a", 25).batch("m-b", 25)
    log.add("model_change", {"adapter_id": "m-a", "from_version": "2026-11-21", "to_version": "2026-11-22", "source": "registry"})
    for _ in range(40):
        log.outcome("m-a", 0)
    state, derived = apply_all(log.events)
    holds = [payload for kind, payload in derived if kind == "hold"]
    change_hold = next(item["hold_id"] for item in holds if item["cause"] == "model_change")
    alarms = [payload for kind, payload in derived if kind == "alarm" and payload["stream"] == "model:m-a"]
    assert len(alarms) >= 2 and alarms[0]["sustained"] is False and alarms[0]["hold_id"] != change_hold
    alarm_hold = next(item for item in holds if item["cause"] == "alarm" and item["hold_id"] == alarms[0]["hold_id"])
    assert alarm_hold["models"] == ["m-a"] and alarms[1]["sustained"] is True and alarms[1]["hold_id"] == alarm_hold["hold_id"]
    assert state["counts"]["sustained"] == sum(1 for kind, item in derived if kind == "alarm" and item["sustained"])
    assert {state["holds"][change_hold]["cause"], state["holds"][alarm_hold["hold_id"]]["cause"]} == {"model_change", "alarm"}


def test_the_controller_counts_a_refused_operator_input_and_leaves_the_prior():
    from app.services.ranking.recommission import refusal

    a = model("m-a", "f-a")
    log = Log().models(a, model("m-b", "f-b"), clean=40).batch("m-a", 3)
    before, _ = apply_all(log.events)
    assert refusal(before, "commission", {"adapter_id": "m-a", "version": a["model_version"]}) == "has_outcomes"
    assert refusal(before, "commission", {"adapter_id": "m-b", "version": "other"}) == "version_mismatch"
    assert refusal(before, "recommission_pass", {"adapter_id": "m-a", "version": "other"}) == "version_mismatch"
    assert refusal(before, "recommission_pass", {"adapter_id": "m-a", "version": a["model_version"]}) is None
    assert refusal(before, "commission", {"adapter_id": "m-z", "version": "x"}) == "unknown_model"
    log.commission(a, clean=1, failed=30)
    log.add("recommission_pass", {"adapter_id": "m-b", "version": "other", "clean": 40, "failed": 0, "generated": 40, "run_sha256": "0" * 64})
    after, _ = apply_all(log.events)
    assert after["counts"]["refused_inputs"] == 2 and after["models"]["m-a"]["prior"] == before["models"]["m-a"]["prior"]


def test_the_recommission_set_resolves_in_a_checkout_and_in_an_image_layout(tmp_path):
    from app.services.ranking.recommission import RecommissionSetError, recommission_queries, recommission_set_path

    relative = PACKAGE.ranking.golden_set_path
    assert recommission_set_path(relative) == REPO_ROOT / relative
    # The API image (apps/api/Dockerfile: WORKDIR /app, apps/api/app at /app/app, the set at /app/<relative>).
    module = tmp_path / "app" / "app" / "services" / "ranking" / "recommission.py"
    module.parent.mkdir(parents=True)
    module.write_text("", encoding="utf-8")
    with pytest.raises(RecommissionSetError) as missing:
        recommission_queries(PACKAGE, start=module)
    assert missing.value.problem == "missing"
    image_copy = tmp_path / "app" / relative
    image_copy.parent.mkdir(parents=True)
    image_copy.write_bytes((REPO_ROOT / relative).read_bytes())
    assert recommission_set_path(relative, start=module) == image_copy
    assert len(recommission_queries(PACKAGE, start=module)) == PACKAGE.ranking.golden_set_items
    golden = json.loads(image_copy.read_text(encoding="utf-8"))
    golden["items"] = golden["items"][:-1]
    image_copy.write_text(json.dumps(golden), encoding="utf-8")
    with pytest.raises(RecommissionSetError) as changed:
        recommission_queries(PACKAGE, start=module)
    assert changed.value.problem == "sha256_or_count_mismatch"
    image_copy.write_text("{", encoding="utf-8")
    with pytest.raises(RecommissionSetError) as unreadable:
        recommission_queries(PACKAGE, start=module)
    assert unreadable.value.problem == "unreadable"
    # The image copies exactly that file to that place.
    dockerfile = (API_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert f"COPY --chown=qcai:qcai {relative} ./{relative}" in dockerfile.splitlines()
    assert "WORKDIR /app" in dockerfile.splitlines() and "COPY --chown=qcai:qcai apps/api/app ./app" in dockerfile.splitlines()


def test_outcome_rule_order_cluster_and_tier():
    from app.services.ranking.contexts import tier_for
    from app.services.ranking.signals import NON_VERDICT_FINALS

    assert NON_VERDICT_FINALS["checker_unavailable"] == "detector_down" and NON_VERDICT_FINALS["v2_degraded_withheld"] == "v2_withheld"

    class Check:
        def __init__(self, check_id, reason_code):
            self.check_id, self.reason_code = check_id, reason_code

    class Verification:
        verdicts = ()
        checks = (Check("V1.6", "keyed_answer_present"),)

    class Entry:
        verification = Verification()

    assert tier_for(Entry(), PACKAGE) == (1, "v1_6")
    Verification.checks = ()
    assert tier_for(Entry(), PACKAGE) == (2, "default")


# ------------------------------------------------------------------------------------------------- the package


def test_the_ranking_schema_number_is_one_constant_and_no_schema_rule_compares_with_a_literal_number():
    # E16: renumbering the Phase 9 package edits one constant (ranking.vocabulary.RANKING_FIRST_MAJOR); the loader's names
    # and bound follow it, and the shipped package carries the same number as its schema and its major.
    first = load_config_package(V7_PACKAGE_PATH, governed=True)
    assert RANKING_SCHEMA_VERSION == RANKING_FIRST_MAJOR == first.schema_version
    assert PACKAGE.schema_version == LATEST_SCHEMA_VERSION == LEARNER_SCHEMA_VERSION
    assert first.package_version == f"{RANKING_FIRST_MAJOR}.0.0" and V7_PACKAGE_PATH.name == f"v{RANKING_FIRST_MAJOR}.json"
    assert DEFAULT_PACKAGE_PATH.name == f"v{LATEST_SCHEMA_VERSION}.json" and PACKAGE.ranking == first.ranking
    assert EHMF_SCHEMA_VERSION == 6
    loader = ast.parse((API_ROOT / "app" / "core" / "config_package.py").read_text(encoding="utf-8"))
    assigned = {target.id: node.value for node in loader.body if isinstance(node, ast.Assign) for target in node.targets
                if isinstance(target, ast.Name)}
    assert isinstance(assigned["RANKING_SCHEMA_VERSION"], ast.Name) and assigned["RANKING_SCHEMA_VERSION"].id == "RANKING_FIRST_MAJOR"
    assert isinstance(assigned["LATEST_SCHEMA_VERSION"], ast.Name) and assigned["LATEST_SCHEMA_VERSION"].id == "LEARNER_SCHEMA_VERSION"
    for path in (API_ROOT / "app" / "core" / "config_package.py", API_ROOT / "app" / "services" / "v3" / "package_check.py",
                 API_ROOT / "app" / "services" / "v3" / "contracts.py", REPO_ROOT / "scripts" / "config_package.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare) and any(isinstance(c, ast.Constant) and c.value == RANKING_FIRST_MAJOR
                                                     for c in [node.left, *node.comparators]):
                raise AssertionError(f"{path.name}:{node.lineno} compares with {RANKING_FIRST_MAJOR}")
    from app.services.content_assembler import MODULE_BLUEPRINTS

    assert tuple(module["slug"] for module in MODULE_BLUEPRINTS) == CLUSTERS
    assert len(EVENT_KINDS) == 21 and max(len(kind) for kind in EVENT_KINDS) <= 17


REFUSALS = [
    (lambda r: r.update(provisional=False), "provisional"),
    (lambda r: r.update(version="ranking-v2"), "ranking.version"),
    (lambda r: r["contexts"].update(clusters=["unscoped"]), "MODULE_BLUEPRINTS"),
    (lambda r: r["trust"].update(gamma="0.8"), "ranking.trust.gamma"),
    (lambda r: r["trust"].update(gamma=0.995), "decimal string"),
    (lambda r: r["trust"].update(quantile="0.6"), "ranking.trust.quantile"),
    (lambda r: r["quality"]["weights"].update(V="0.5"), "sum to 1"),
    (lambda r: r["quality"].update(eta="0"), "ranking.quality.eta"),
    (lambda r: r["ratings"].update(B="0.96"), "strictly descending"),
    (lambda r: r["selection"].update(eps_s="0.6"), "ranking.selection.eps_s"),
    (lambda r: r["promotion"].update(delta="1"), "ranking.promotion.delta"),
    (lambda r: r["promotion"].update(n_d=0), "n_d"),
    (lambda r: r["micro_batch"].update(responses=0), "responses"),
    (lambda r: r["micro_batch"].update(seconds=30), "seconds"),
    (lambda r: r["cusum"].update(p0="0.2"), "p0 < p1"),
    (lambda r: r["cusum"].update(h="0"), "ranking.cusum.h"),
    (lambda r: r["recommission"].update(deflation="1.2"), "deflation"),
    (lambda r: r["recommission"].update(cap="B"), "cap"),
    (lambda r: r["recommission"].update(min_generated=8), "min_generated is refused"),
    (lambda r: r["recommission"].update(gateway_mode="on"), "gateway_mode"),
    (lambda r: r["recommission"]["golden_set"].update(sha256="0" * 64), "ehmf.golden_set"),
    (lambda r: r["penalties"].update(latency_target_ms=500), "latency target"),
    (lambda r: r["fallback"].update(pre_verified_source="store"), "pre_verified_source"),
    (lambda r: r["live_routing"].update(state="live"), "refused"),
    (lambda r: r["replay"].update(stop_refresh_s=0), "stop_refresh_s"),
    (lambda r: r.update(clean_rule="other"), "clean_rule"),
    (lambda r: r["tier_permissions"].update(C=[3]), "tier_permissions"),
    (lambda r: r.update(hand_fixtures=[]), "hand_fixtures"),
]


@pytest.mark.parametrize("edit, match", REFUSALS)
def test_every_ranking_block_refusal(tmp_path, edit, match):
    def change(payload):
        edit(payload["ranking"])
    with pytest.raises(ConfigPackageError, match=match):
        load_config_package(package_copy(tmp_path, change), governed=False)


def test_the_flag_policy_and_owner_decisions_the_ranking_needs(tmp_path):
    cases = [
        (lambda p: p["flag_policy"]["ranking"].update(default_elsewhere="shadow"), "default_elsewhere"),
        (lambda p: p["flag_policy"].update(phase9_exit_passed=True), "phase9_exit_evidence"),
        (lambda p: p["owner_decisions"].pop("D-28"), "D-28"),
        (lambda p: p["owner_decisions"]["D-06"].update(operator_values=[]), "ranking.penalties"),
        (lambda p: p["v3"]["triggers"].update(queue_reasons=p["v3"]["triggers"]["queue_reasons"][:4]), "queue reasons"),
        (lambda p: next(m for m in p["gateway"]["registries"]["development"] if m["adapter_id"] == "fake-delta-v1")["fake"].pop("generate_rule"),
         "generate_rule"),
        (lambda p: next(m for m in p["gateway"]["registries"]["development"] if m["adapter_id"] == "fake-alpha-v1")["fake"].update(
            generate_rule="extractive-clone-v1"), "only a fake member with generate"),
    ]
    for edit, match in cases:
        with pytest.raises(ConfigPackageError, match=match):
            load_config_package(package_copy(tmp_path / match.replace(" ", "_"), edit), governed=False)


def test_package_v6_refuses_a_fake_generate_rule(tmp_path):
    import shutil

    from app.core.config_package import V6_PACKAGE_PATH, canonical_sha256

    target = tmp_path / "config_package"
    shutil.copytree(V6_PACKAGE_PATH.parent, target)
    path = target / "v6.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    next(m for m in payload["gateway"]["registries"]["development"] if m["adapter_id"] == "fake-delta-v1")["fake"]["generate_rule"] = "extractive-clone-v1"
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.with_name("v6.json.sha256").write_text(canonical_sha256(payload) + "\n", encoding="utf-8")
    with pytest.raises(ConfigPackageError, match=f"needs package v{RANKING_SCHEMA_VERSION}"):
        load_config_package(path, governed=False)
    v6 = load_config_package(V6_PACKAGE_PATH, governed=False)
    assert v6.ranking is None and v6.v3.queue_reasons == ("v1_3_flag", "v1_8_misconception", "v2_correction_exhausted", "v2_degraded_withheld")
    assert PACKAGE.v3.queue_reasons[-1] == "ranking_empty_eligible_set"


# ------------------------------------------------------------------------------------------------- the V3 helpers and the clone


def test_record_model_change_returns_its_seq_and_window_remaining_counts_the_draws():
    from datetime import UTC, datetime

    from app.services.v3 import triggers as trig
    from app.services.v3.scan import record_model_change, window_remaining
    from v3_fakes import fresh_v3_sessions

    with fresh_v3_sessions() as (factory, _engine):
        with factory() as db:
            seq = record_model_change(db, trig.ModelChange("generator:x", "1", "2"), source="ranking", from_ledger_seq=0, window=3,
                                      now=datetime.now(UTC))
            db.commit()
            assert isinstance(seq, int) and window_remaining(db, seq) == 3 and window_remaining(db, seq + 99) == 0


def test_lines_describing_a_transaction_s_writes_are_logged_only_when_it_commits(caplog):
    # record_cusum_alarm(db=...) and the derived events' lines (log_derived) wait for the caller's commit: a rolled-back or
    # closed transaction logs none of them, a committed one logs each once.
    import logging
    from datetime import UTC, datetime

    from app.core.config import Settings
    from app.services.ranking.scan import log_derived
    from app.services.v3.contracts import CusumAlarm
    from app.services.v3.events import record_cusum_alarm
    from v3_fakes import fresh_v3_sessions

    alarm = CusumAlarm(stream="model:x", p0=0.05, p1=0.15, h=4.0, statistic=4.2, observations=120, raised_at="2026-11-20T12:00:00Z",
                       source="phase9-cusum")
    payload = {"stream": "model:x", "statistic": "4.2", "observations": 120, "sustained": False}
    settings = Settings(environment="development")

    def lines() -> list[str]:
        return [record.json_fields["event"] for record in caplog.records if hasattr(record, "json_fields")
                and record.json_fields.get("event") in ("v3.x5_event", "ranking.alarm")]

    with fresh_v3_sessions() as (factory, _engine), caplog.at_level(logging.INFO):
        with factory() as db:
            record_cusum_alarm(alarm, settings=settings, package=PACKAGE, db=db, now=datetime.now(UTC))
            log_derived(db, "alarm", payload)
            db.rollback()
        with factory() as db:
            record_cusum_alarm(alarm, settings=settings, package=PACKAGE, db=db, now=datetime.now(UTC))
            log_derived(db, "alarm", payload)
        assert lines() == []
        with factory() as db:
            record_cusum_alarm(alarm, settings=settings, package=PACKAGE, db=db, now=datetime.now(UTC))
            log_derived(db, "alarm", payload)
            assert lines() == []
            db.commit()
            assert lines() == ["v3.x5_event", "ranking.alarm"]
            db.commit()
        assert lines() == ["v3.x5_event", "ranking.alarm"]


def test_the_clone_generator_is_refused_outside_its_rule_and_development():
    from dataclasses import replace

    from app.core.config import Settings
    from app.gateway.registry import registry_for
    from app.services.ranking.generators import CloneGenerator, CloneUnavailable

    development = Settings(environment="development")
    spec = next(member for member in registry_for(PACKAGE, development).members if member.adapter_id == "fake-delta-v1")
    generator = CloneGenerator(spec, PACKAGE, settings=development)
    assert generator.ref.generator_id == "fake-delta-v1" and generator.ref.model_id == "fake-delta-verifier@2026-11-21"
    for changed, settings in ((replace(spec, fake_generate_rule=None), development), (replace(spec, capabilities=("verify",)), development),
                              (replace(spec, provider="openai"), development),
                              (spec, Settings(environment="staging", allowed_origins=["https://staging.example.test"], guest_token_secret="s" * 32))):
        with pytest.raises(CloneUnavailable):
            CloneGenerator(changed, PACKAGE, settings=settings)


def test_the_replay_script_exit_codes(tmp_path):
    from test_phase9_acceptance import REPORT, scripts_module

    script = scripts_module("run_ranking_replay")
    assert script.main(["--check", str(tmp_path / "missing.json")]) == 2
    assert script.main([]) == 2
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    assert script.main(["--check", str(tmp_path / "bad.json")]) == 2
    assert REPORT.is_file()
