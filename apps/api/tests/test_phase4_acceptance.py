"""Phase 4 acceptance: V1 deterministic validation (plan Phase 4 K, G, H, I, L; Phase 4 spec section 13.1).

Configurations: "dev" is the development store (V1_PIPELINE=enforce on the two-pass shadow by default); the fixture
runner's all-public-approved store for the adversarial set and the answer-rate block. Checker configurations: (a)
production, the NullChecker (D-21 none), and (b) a fake always-SUPPORTED checker (what the deterministic checks catch
alone). Readings (spec R-a): no two-pass text reaches a learner; "delivered text" in AC-4-4 and AC-4-5 is the text of
V1's accepted rendering, recorded in the shadow ledger record.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib.util
import json
import logging
from pathlib import Path
import random
import re
import subprocess
import sys
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect as sa_inspect, select
from sqlalchemy.orm import sessionmaker

from app.api.routes import assistant as assistant_route
from app.api.routes import ledger as ledger_route
from app.api.routes import qa as qa_route
from app.core.config import Settings
from app.core.config_package import DEFAULT_PACKAGE_PATH, V2_PACKAGE_PATH, V3_PACKAGE_PATH, canonical_sha256, get_config_package, load_config_package
from app.core.db import Base, SessionLocal
from app.core.schema_upgrades import run_schema_upgrades
from app.db_models import ResponseLedgerRecord
from app.main import app
from app.services import ledger, qa_engine, tutor_orchestrator
from app.services.claim_gate import check_subset
from app.services.contained_answers import ABSTENTION, contain_answer
from app.services.content_assembler import CourseStore
from app.services.qa_engine import QAEngine
from app.services.retrieval_engine import RetrievalEngine
from app.services.span_resolver import SpanResolver
from app.services.store import get_course_store, get_retrieval_engine
from app.services.teaching_assistant import TeachingAssistantService
from app.services.tutor_orchestrator import TutorOrchestrator
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline.bind import claim_id_for
from app.services.tutor_pipeline.contracts import LEARNER_STATE_FIELDS, CheckResult, LedgerEntryV2, VerificationRecord
from app.services.tutor_pipeline.render import TemplateRenderer
from app.services.v1_checks import V1_METRICS
from app.services.v1_checks.aggregate import V1Abstained, V1HardFail, V1Passed, consult_v2
from app.services.v1_checks.lexicon import knorm
from app.services.v1_checks.results import make_result
from app.services.v1_checks.v1_1_resolution import check_v1_1
from app.services.v1_checks.v1_6_keyed_answers import assessment_items
from app.services.v1_checks.v1_7_conflicts import disagreement
from tutor_fakes import ScriptedGenerator
from v1_fakes import (
    MULTI_CLAIM,
    AlwaysContradictedChecker,
    AlwaysSupportedChecker,
    FixtureKeys,
    InjectedClock,
    LateChecker,
    RaisingChecker,
    SupportedVoter,
    UnmappedRenderer,
    WrongTypeChecker,
    dev_pipeline,
    keyed_item,
    run,
    temp_package,
)

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
SETTINGS = Settings()
PACKAGE = get_config_package(SETTINGS)
V1 = PACKAGE.v1
STOP = PACKAGE.retrieval.stopwords
DATA = json.loads((Path(__file__).parent / "data" / "score_floor_queries.json").read_text(encoding="utf-8"))
IN_DOMAIN = [item["query"] for item in DATA["in_domain"]]
OFF_TOPIC = list(DATA["off_topic"]) + list(DATA["stopword_only"])
REPORT_PATH = REPO_ROOT / "docs" / "evaluation" / "phase4" / "v1_fixture_report_v1.json"
FIXTURES_PATH = REPO_ROOT / "docs" / "evaluation" / "phase4" / "v1_adversarial_fixtures_v1.json"
REPO_MANIFEST = REPO_ROOT / "corpus" / "public" / "manifest.json"
SPEC = (REPO_ROOT / "docs" / "architecture" / "phase4-implementation-spec.md").read_text(encoding="utf-8")
client = TestClient(app)


def load_runner():
    spec = importlib.util.spec_from_file_location("phase4_acceptance_runner", REPO_ROOT / "scripts" / "run_v1_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = load_runner()


@pytest.fixture(scope="module")
def fixture_report():
    """One fresh run of the fixture runner, shared by tests 4, 5, 7, 8, 9 and 23."""
    return RUNNER.compute(commit_source=lambda: "0" * 40)


def demo(prefix: str) -> dict[str, str]:
    return {"x-demo-user": f"{prefix}-{uuid4().hex[:12]}", "x-demo-role": "learner", "x-forwarded-for": f"phase4-{uuid4().hex}"}


def fresh(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "x-forwarded-for": f"phase4-{uuid4().hex}"}


def _events(caplog, event: str) -> list[dict]:
    return [r.json_fields for r in caplog.records if getattr(r, "json_fields", {}).get("event") == event]


def _answered_queries(count: int) -> list[str]:
    found = []
    pipeline = dev_pipeline(Settings(v1_pipeline="off"))
    for query in IN_DOMAIN:
        result = run(pipeline, query)
        if result.decision == "answer" and result.envelope is not None:
            found.append(query)
        if len(found) == count:
            break
    return found


# ======================================================================================================== AC-4-1


def _bad_id(rng: random.Random, real: str) -> str:
    form = rng.choice(("hex", "malformed", "upper"))
    if form == "hex":
        return "span-" + "".join(rng.choice("0123456789abcdef") for _ in range(64))
    if form == "malformed":
        return "span-" + "".join(rng.choice("ghijklmnop") for _ in range(rng.randint(1, 70)))
    return real.upper()


def test_ac_4_1_property_an_unresolvable_span_id_hard_fails_and_no_vote_changes_the_outcome():
    rng = random.Random(20261120)
    queries = _answered_queries(12)
    resolver = SpanResolver(get_course_store())
    material = {}
    for query in queries:
        base = run(dev_pipeline(Settings(v1_pipeline="off")), query)
        material[query] = (base.bundle, [(sentence, span.span_id) for span in base.envelope.evidence for sentence in [span.text.split(". ")[0]]])
    for _ in range(200):
        query = rng.choice(queries)
        bundle, pool = material[query]
        claims = [list(rng.choice(pool)) for _ in range(rng.randint(1, 4))]
        for index in rng.sample(range(len(claims)), rng.randint(1, len(claims))):
            claims[index][1] = _bad_id(rng, claims[index][1])
        script = [[(text, [span_id]) for text, span_id in claims]]
        generator = ScriptedGenerator(script)
        plan = generator.propose(None)
        assert check_v1_1(plan, bundle, resolver=resolver, attempt=1).outcome == "hard_fail"
        voter = SupportedVoter()
        result = run(dev_pipeline(generator=ScriptedGenerator(script), checker=AlwaysSupportedChecker(), v2_hook=voter), query)
        record = result.entry.verification
        assert (result.decision, result.abstention_reason, record.hard_fail, record.generation_attempts) == ("abstain", "unresolvable_citation", True, 3)
        assert [r.outcome for r in record.checks if r.check_id == "V1.1"] == ["hard_fail"] * 3
        assert isinstance(result.v1.decision, V1HardFail) and voter.calls == 0
        assert consult_v2(voter, result.v1.decision) is result.v1.decision and voter.calls == 0


def test_ac_4_1_a_hard_fail_is_typed_final_and_only_a_v1_passed_reaches_the_v2_hook():
    names = {field.name for field in dataclasses.fields(V1HardFail)} | {field.name for field in dataclasses.fields(V1Abstained)}
    assert not names & {"locked", "rendered", "verdicts"}
    passed = run(dev_pipeline(checker=AlwaysSupportedChecker()), MULTI_CLAIM).v1.decision
    assert isinstance(passed, V1Passed)
    hard = make_result("V1.1", "pre_render", passed.generation_attempts, "unresolvable")
    with pytest.raises(ValueError, match="hard fail is final"):
        dataclasses.replace(passed, results=(*passed.results, hard))
    render_hard = make_result("V1.4", "post_render", passed.render_attempts, "unmapped_factual_sentence")
    with pytest.raises(ValueError):
        dataclasses.replace(passed, results=(*passed.results, render_hard))
    dropped = make_result("V1.2", "pre_render", passed.generation_attempts, "not_verbatim", claim_id=claim_id_for("a dropped proposal", []))
    assert dataclasses.replace(passed, results=(*passed.results, dropped)).final == passed.final
    locked_drop = make_result("V1.2", "pre_render", passed.generation_attempts, "not_verbatim", claim_id=passed.locked.claims[0].claim_id)
    with pytest.raises(ValueError):
        dataclasses.replace(passed, results=(*passed.results, locked_drop))
    voter = SupportedVoter()
    for decision in (V1HardFail(results=(hard,), failing=(hard,), generation_attempts=1, render_attempts=0, abstention_reason="unresolvable_citation"),
                     V1Abstained(results=(), generation_attempts=0, render_attempts=0, abstention_reason="no_match")):
        assert consult_v2(voter, decision) is decision
    assert voter.calls == 0 and consult_v2(voter, passed) is passed and voter.calls == 1
    # The ledger refuses a delivered verdict despite a hard fail or a flag of its own claim, or a withheld conflict naming it.
    payload = run(dev_pipeline(checker=AlwaysSupportedChecker()), MULTI_CLAIM).entry.model_dump(mode="json")
    verdict = payload["verification"]["verdicts"][0]
    for extra in (make_result("V1.8", "pre_render", 1, "misconception_match", claim_id=verdict["claim_id"]),
                  make_result("V1.3", "pre_render", 1, "contradicted", claim_id=verdict["claim_id"], checker_model_id="fixture-always-supported")):
        changed = json.loads(json.dumps(payload))
        changed["verification"]["verdicts"][0]["v1"].append(extra.model_dump(mode="json"))
        with pytest.raises(ValidationError, match="invariant 6"):
            LedgerEntryV2.model_validate(changed)
    changed = json.loads(json.dumps(payload))
    spans = sorted(changed["span_ids"][:2] if len(changed["span_ids"]) > 1 else [changed["span_ids"][0], "span-" + "f" * 64])
    changed["verification"]["disclosure"] = {"block_schema": "conflict-disclosure-v1", "policy": "withhold", "conflicts": [
        {"kind": "number_disagreement", "span_ids": spans, "item_ids": ["a", "b"], "claim_ids": [verdict["claim_id"]]}]}
    with pytest.raises(ValidationError, match="withheld conflict"):
        LedgerEntryV2.model_validate(changed)


def test_ac_4_1_a_regenerated_candidate_is_judged_afresh_and_the_hard_failed_one_never_reaches_v2():
    base = run(dev_pipeline(Settings(v1_pipeline="off")), MULTI_CLAIM)
    clean = [(claim.text, list(claim.span_ids)) for claim in base.plan.claims]
    bad = [(clean[0][0], ["span-" + "e" * 64])] + clean[1:]
    voter = SupportedVoter()
    result = run(dev_pipeline(generator=ScriptedGenerator([bad, clean]), checker=AlwaysSupportedChecker(), v2_hook=voter), MULTI_CLAIM)
    record = result.entry.verification
    assert result.decision == "answer" and record.generation_attempts == 2 and record.cycle_count == 1
    assert [(r.attempt, r.outcome) for r in record.checks if r.check_id == "V1.1"] == [(1, "hard_fail"), (2, "pass")]
    assert voter.calls == 1 and isinstance(voter.seen[0], V1Passed)
    assert {claim.claim_id for claim in voter.seen[0].locked.claims} == {claim.claim_id for claim in base.locked.claims}
    assert all(r.attempt == 2 for v in record.verdicts for r in v.v1 if r.stage == "pre_render" and r.check_id != "V1.5")


# ======================================================================================================== AC-4-2


def test_ac_4_2_the_adversarial_set_fails_or_abstains_under_production_and_only_the_residual_class_is_delivered_with_a_perfect_checker(fixture_report):
    assert fixture_report["result"] == "pass" and fixture_report["problems"] == []
    for configuration in fixture_report["configurations"]:
        for name, block in configuration["classes"].items():
            if name in RUNNER.RESIDUAL_CLASSES:
                assert configuration["name"] != "production" or block["delivered"] == 0
            else:
                assert block["delivered"] == 0 and block["catch_rate"] == 1.0, (configuration["name"], name)
        assert configuration["expected_missing"] == []
    production = next(c for c in fixture_report["configurations"] if c["name"] == "production")
    assert production["finals"]["deliver"] == 0 and production["checker_model_id"] == "none"
    deterministic = next(c for c in fixture_report["configurations"] if c["name"] == "deterministic_only")
    expected = {"stripped_negation": "V1.2", "inserted_negation": "V1.2", "number_swap": "V1.2", "unit_swap": "V1.2",
                "fabricated_sentence_generator": "V1.2", "fabricated_sentence_renderer": "V1.4", "unresolvable_span_id": "V1.1",
                "conflict_version": "V1.7", "conflict_number": "V1.7", "conflict_negation": "V1.7", "keyed_answer_leak": "V1.6",
                "out_of_scope": "V1.5", "checker_unavailable": "V1.3", "invalid_schema": "V1.9", "misconception": "V1.8"}
    for name, check in expected.items():
        assert deterministic["classes"][name]["caught_by"].get(check) == deterministic["classes"][name]["cases"], name
    # The residual class is an implementation-defined case of plan M's "checker error" (plan M names only "checker
    # error, paraphrased leakage"): with a perfect-support checker its three contradiction cases are delivered, so
    # AC-4-2 holds for them only while V1.3 withholds every claim (the NullChecker, D-21 none). DI-64 re-establishes
    # it when a checker is hosted.
    assert deterministic["classes"]["residual_paraphrased_contradiction"]["delivered"] == 3
    assert production["classes"]["residual_paraphrased_contradiction"]["caught_by"] == {"V1.3": 3}
    assert deterministic["citation_resolution_delivered"]["rate"] in (1.0, None)


def test_ac_4_2_the_committed_fixture_report_matches_a_fresh_run_and_its_hashes_match_the_package(fixture_report):
    committed = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    def comparable(report):
        stripped = RUNNER._strip_volatile(report)
        stripped.pop("inputs", None)  # inside a test process the imported-module map also holds what other tests imported
        return stripped

    assert comparable(committed) == comparable(fixture_report)
    assert RUNNER.input_problems(committed["inputs"]) == []
    fixtures = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    assert committed["fixtures"] == {"path": "docs/evaluation/phase4/v1_adversarial_fixtures_v1.json", "set_sha256": V1.fixtures_set_sha256,
                                     "cases": V1.fixtures_cases}
    rows = {row["id"]: row["case_sha256"] for row in committed["configurations"][0]["cases"]}
    assert rows == {case["id"]: canonical_sha256(case) for case in fixtures["cases"]}
    assert committed["evidence_class"] == "fixture measurements, not research results (plan Phase 4 H)" and committed["public_corpus_only"] is True
    with pytest.raises(SystemExit, match="lqs"):
        RUNNER.load_fixtures(REPO_ROOT / "lqs" / "fixtures.json")
    written = [path.name for path in RUNNER.TEMP_ROOT.rglob("*") if path.is_file()]
    assert written == ["manifest.json"]


def test_ac_4_2_deterministic_checks_alone_catch_negation_number_fabrication_unresolvable_and_conflict_cases():
    fixtures = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    env = RUNNER.gate_environment("bm25f-v1")
    overlay = RUNNER.overlay_v1(PACKAGE, fixtures["fixture_package"])
    expected = {"neg-strip-01": ("V1.2", "negation_mismatch"), "number-swap-01": ("V1.2", "quantity_mismatch"),
                "fabricated-generator-01": ("V1.2", "not_verbatim"), "unresolvable-01": ("V1.1", "unresolvable"),
                "fabricated-renderer-01": ("V1.4", "unmapped_factual_sentence"), "conflict-version-01": ("V1.7", "conflict_disclosed")}
    cases = {case["id"]: case for case in fixtures["cases"]}
    for case_id, (check, reason) in expected.items():
        row, result = RUNNER.run_pipeline_case(cases[case_id], env, overlay, "deterministic_only", fixtures)
        reasons = {(r.check_id, r.reason_code) for r in result.entry.verification.checks}
        assert (check, reason) in reasons and not row["delivered"], (case_id, reasons)


# ======================================================================================================== AC-4-3


def test_ac_4_3_out_of_scope_fixtures_abstain_under_v1_5_for_both_gates(fixture_report):
    assert {block["gate"]: (block["off_topic"], block["off_topic_v1_5_abstained"]) for block in fixture_report["answer_rate"]} == {
        "bm25f-v1": (124, 124), "p1-floor": (124, 124)}
    for query in OFF_TOPIC[:12]:
        record = run(dev_pipeline(checker=AlwaysSupportedChecker()), query).entry.verification
        assert [r.outcome for r in record.checks if r.check_id == "V1.5"] == ["abstain"] and record.final == "abstain"


def test_ac_4_3_the_in_domain_answer_rate_is_at_least_the_phase_2_baseline_for_the_same_gate(fixture_report, tmp_path):
    calibration = json.loads((REPO_ROOT / "docs" / "evaluation" / "phase2" / "calibration_record_v1.json").read_text(encoding="utf-8"))
    baseline = {gate: tuple(int(part) for part in calibration["answer_rate"][key].split("/"))
                for gate, key in (("bm25f-v1", "bm25"), ("p1-floor", "p1_floor_span_index"))}
    assert baseline == {"bm25f-v1": (166, 174), "p1-floor": (146, 174)}
    for block in fixture_report["answer_rate"]:
        answered, in_domain = baseline[block["gate"]]
        assert block["in_domain"] == in_domain and block["v1_5_answered"] * in_domain >= answered * block["in_domain"]
        assert block["phase2_baseline"] == f"{answered}/{in_domain}"
    assert dict(V1.answer_rate_floor) == baseline and all(isinstance(v, int) for pair in V1.answer_rate_floor.values() for v in pair)
    raised = load_config_package(temp_package(tmp_path, edit=lambda raw: raw["v1"]["stop"]["answer_rate_floor"].update(
        {"bm25f-v1": {"answered": 167, "in_domain": 174}})), governed=False)
    result, problems = RUNNER.evaluate(fixture_report, raised)
    assert result == "stop" and any("below its floor" in problem for problem in problems)


def test_ac_4_3_v1_adds_no_in_domain_abstention_over_the_phase_3_composition(fixture_report):
    for block in fixture_report["answer_rate"]:
        assert block["composition_identical_b"] == block["in_domain"] == 174, block["gate"]
        assert block["composition_answered_v1_b"] == block["composition_answered_v1_off"] == block["composition_answered_v1_a_not_abstain"]


# ======================================================================================================== AC-4-4


def test_ac_4_4_an_unmapped_sentence_is_re_rendered_at_most_twice_then_only_locked_claims_remain():
    renderer = UnmappedRenderer(TemplateRenderer(), [1, 2])
    result = run(dev_pipeline(checker=AlwaysSupportedChecker(), renderer=renderer), MULTI_CLAIM)
    record = result.entry.verification
    assert (result.decision, record.render_attempts, record.cycle_count) == ("answer", 3, 2)
    assert check_subset(result.rendered, result.locked).passed and renderer.sentence not in result.rendered.text
    locked = {claim.claim_id: claim.text for claim in result.locked.claims}
    assert all(segment.claim_id in locked and segment.text == locked[segment.claim_id] for segment in result.rendered.segments if segment.kind == "claim")
    assert [r.outcome for r in record.checks if r.check_id == "V1.4"] == ["hard_fail", "hard_fail", "pass"]
    once = run(dev_pipeline(checker=AlwaysSupportedChecker(), renderer=UnmappedRenderer(TemplateRenderer(), [1])), MULTI_CLAIM)
    assert once.entry.verification.render_attempts == 2 and once.decision == "answer"


def test_ac_4_4_a_renderer_that_never_stops_adding_a_sentence_abstains_after_two_regenerations():
    result = run(dev_pipeline(checker=AlwaysSupportedChecker(), renderer=UnmappedRenderer(TemplateRenderer(), None)), MULTI_CLAIM)
    record = result.entry.verification
    assert (result.decision, result.abstention_reason, record.hard_fail) == ("abstain", "subset_check_failed", True)
    assert isinstance(result.v1.decision, V1HardFail) and result.v1.rendered is None and result.rendered is None
    assert [r.reason_code for r in record.checks if r.check_id == "V1.4"] == ["unmapped_factual_sentence"] * 3


# ======================================================================================================== AC-4-5


def _keyed_run(checker, question: str, key_text: str, prompt: str):
    keys = FixtureKeys([keyed_item("fixture-key-1", prompt, key_text)])
    return run(dev_pipeline(checker=checker, keyed_items=keys), question)


def test_ac_4_5_an_assessment_draft_with_the_keyed_answer_is_re_rendered_socratically_without_it():
    base = run(dev_pipeline(Settings(v1_pipeline="off")), MULTI_CLAIM)
    assert len(base.locked.claims) >= 2
    key = base.locked.claims[0].text
    for checker, final in ((AlwaysSupportedChecker(), "deliver"), (None, "withhold")):
        result = _keyed_run(checker, MULTI_CLAIM, key, MULTI_CLAIM)
        record = result.entry.verification
        assert [(r.attempt, r.outcome) for r in record.checks if r.check_id == "V1.6"] == [(1, "hard_fail"), (2, "pass")]
        assert result.entry.presentation.plan_id == "socratic" and result.entry.presentation.source == "request"
        assert knorm(key) not in knorm(result.rendered.text) and record.final == final
        finals = {v.claim_id: v.final for v in record.verdicts}
        assert finals[base.locked.claims[0].claim_id] == "withhold"
        if final == "deliver":
            assert all(value == "deliver" for claim_id, value in finals.items() if claim_id != base.locked.claims[0].claim_id)
    # The turn names the item by its id inside a sentence; the prompt itself shares nothing with the question.
    named = _keyed_run(AlwaysSupportedChecker(), f"{MULTI_CLAIM} This is about fixture-key-1.", key, "Unrelated prompt about bread")
    assert [r.reason_code for r in named.entry.verification.checks if r.check_id == "V1.6"][0] == "keyed_answer_present"
    # Every lesson's items are searched, whatever lesson the request names.
    store = get_course_store()
    quiz = store.quiz_keys.all()[0]
    other_lesson = next(slug for slug in store.lessons if slug != quiz.lesson_slug)
    from app.services.quiz_keys import QuizKeySource

    assert any(item.item_id == quiz.id for item in assessment_items(quiz.prompt, QuizKeySource(store.quiz_keys), v1=V1, stopwords=STOP))
    # A turn on another lesson's page still finds the fixture item (lesson "fixture-lesson") and re-renders without its key.
    keys = FixtureKeys([keyed_item("fixture-key-1", MULTI_CLAIM, key)])
    assert other_lesson != "fixture-lesson"
    scoped = run(dev_pipeline(checker=AlwaysSupportedChecker(), keyed_items=keys), MULTI_CLAIM, lesson_slug=other_lesson)
    assert [(r.attempt, r.reason_code) for r in scoped.entry.verification.checks if r.check_id == "V1.6"][0] == (1, "keyed_answer_present")
    assert knorm(key) not in knorm(scoped.rendered.text)


def test_ac_4_5_a_draft_whose_every_claim_holds_the_key_abstains():
    base = run(dev_pipeline(Settings(v1_pipeline="off")), MULTI_CLAIM)
    key = " ".join(claim.text for claim in base.locked.claims)
    result = _keyed_run(AlwaysSupportedChecker(), MULTI_CLAIM, key, MULTI_CLAIM)
    assert (result.decision, result.abstention_reason, result.entry.verification.hard_fail) == ("abstain", "keyed_answer_leak", True)
    assert isinstance(result.v1.decision, V1HardFail)


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


def _quiz_objects(value):
    if isinstance(value, dict):
        if "prompt" in value and "question_type" in value:
            yield value
        for item in value.values():
            yield from _quiz_objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from _quiz_objects(item)


def test_ac_4_5_no_public_content_payload_carries_a_keyed_answer():
    store = get_course_store()
    keys = store.quiz_keys.all()
    headers = demo("p4-keys")
    bodies = [client.get("/content/course").json()]
    bodies += [client.get(f"/content/modules/{slug}").json() for slug in store.modules]
    bodies += [client.get(f"/content/lessons/{slug}").json() for slug in store.lessons]
    for key in keys:
        bodies.append(client.get("/search", params={"query": key.prompt}, headers=fresh(headers)).json())
        bodies.append(client.post("/qa/ask", json={"question": key.prompt}, headers=fresh(headers)).json())
        bodies.append(client.post("/assistant/chat", json={"message": key.prompt}, headers=fresh(headers)).json())
    choice_positions = 0
    for body in bodies:
        for question in _quiz_objects(body):
            assert set(question) <= {"id", "question_type", "prompt", "choices", "difficulty"}, question
        text = knorm(" ".join(_strings(body)))
        for key in keys:
            assert knorm(key.explanation) not in text or key.explanation == key.answer and key.question_type == "mcq", key.id
            if key.question_type != "mcq":
                assert knorm(key.answer) not in text, key.id
        # An mcq key appears only as one entry of its own question's choices.
        stripped = json.loads(json.dumps(body))
        for question in _quiz_objects(stripped):
            choice_positions += len(question.get("choices", []))
            question["choices"] = []
        remaining = knorm(" ".join(_strings(stripped)))
        for key in keys:
            if key.question_type == "mcq":
                assert knorm(key.answer) not in remaining, key.id
    assert choice_positions > 0
    openapi = client.get("/openapi.json").json()
    assert "answer" not in openapi["components"]["schemas"]["QuizQuestion"]["properties"]
    assert set(openapi["components"]["schemas"]["QuizFeedbackItem"]["properties"]) == {"question_id", "answered", "correct", "answer", "explanation"}


def test_ac_4_5_the_quiz_attempt_returns_feedback_only_after_saving_and_only_for_answered_questions():
    from test_authorization import _guest, _local_account

    store = get_course_store()
    slug = next(iter(store.lessons))
    keys = store.quiz_keys.for_lesson(slug)
    responses = {keys[0].id: keys[0].answer}
    shapes = []
    guest_browser, guest_headers, _ = _guest()
    durable_browser, durable_headers = _local_account()
    for caller, headers in ((client, demo("p4-quiz")), (guest_browser, guest_headers), (durable_browser, durable_headers)):
        body = caller.post("/content/quiz-attempts", json={"lesson_slug": slug, "score": 999, "responses": responses}, headers=headers).json()
        assert body["score"] == 1 and len(body["feedback"]) == len(keys)
        first, *rest = body["feedback"]
        assert first == {"question_id": keys[0].id, "answered": True, "correct": True, "answer": keys[0].answer, "explanation": keys[0].explanation}
        assert all(item["answered"] is False and item["answer"] is None and item["explanation"] is None and item["correct"] is None for item in rest)
        shapes.append(sorted(body))
    assert shapes[0] == shapes[1] == shapes[2] == ["attempt_id", "feedback", "score", "status"]


# ======================================================================================================== AC-4-6


def test_ac_4_6_conflicting_cited_spans_get_a_disclosure_block_or_are_withheld():
    fixtures = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    env = RUNNER.gate_environment("bm25f-v1")
    overlay = RUNNER.overlay_v1(PACKAGE, fixtures["fixture_package"])
    case = next(case for case in fixtures["cases"] if case["id"] == "conflict-version-01")
    _, result = RUNNER.run_pipeline_case(case, env, overlay, "deterministic_only", fixtures)
    record = result.entry.verification
    (pair,) = [pair for pair in record.disclosure.conflicts if pair.kind == "version_of_same_asset"]
    assert set(pair.item_ids) == set(fixtures["fixture_package"]["v1_7.version_families"][0]["item_ids"])
    assert set(pair.span_ids) == set(result.v1.locked.span_ids) and "conflict_disclosed" in record.labels and record.final == "deliver"
    _, withheld = RUNNER.run_pipeline_case(case, env, dataclasses.replace(overlay, on_conflict="withhold"), "deterministic_only", fixtures)
    involved = {claim_id for pair in withheld.entry.verification.disclosure.conflicts for claim_id in pair.claim_ids}
    assert involved and all(v.final == "withhold" for v in withheld.entry.verification.verdicts if v.claim_id in involved)
    assert withheld.entry.verification.final == "withhold" and withheld.entry.verification.final_reason == "conflict_withheld"
    sentence = "The routing stage inserts 12 extra swap gates into the compiled benchmark circuit."
    assert disagreement(sentence, sentence.replace("12", "13"), v1=V1, stopwords=STOP) == "number_disagreement"
    assert disagreement("The benchmark circuit holds 5 qubits after routing today", "The benchmark circuit holds 5 noisy qubits after routing today",
                        v1=V1, stopwords=STOP) is None
    # The shipped family names video items, which are never cited spans (inert in production, spec conflict 33).
    shipped = {item for item in V1.version_families}
    assert shipped == {"quantum-computing-and-artificial-intelligence-2025", "quantum-computing-and-artificial-intelligence-2026"}
    assert not any(record.item_id in shipped for record in get_course_store().span_registry.records if record.item_kind == "document")


def _family_citations():
    from app.schemas import Citation
    from app.services.provenance import CITATION_SCHEMA

    store = get_course_store()
    family = ("analyzing-quantum-computing-and-ai-paper-2025", "quantum-computing-ai-research-synthesis-2026")
    citations = []
    for item_id in family:
        record = next(r for r in store.span_registry.records if r.item_id == item_id and len(r.text) > 200)
        citations.append(Citation(chunk_id=record.span_id, span_id=record.span_id, source_kind="document", source_title="t", section_title="s",
                                  excerpt=record.text, source_filename=record.source_filename, content_hash=record.content_hash,
                                  citation_schema=CITATION_SCHEMA, item_id=record.item_id))
    return citations, family


def test_ac_4_6_the_evidence_panel_shows_the_disclosure_for_a_contained_answer(monkeypatch):
    citations, family = _family_citations()
    real = tutor_orchestrator.contain_answer
    monkeypatch.setattr(tutor_orchestrator, "contain_answer", lambda _citations, registry, spans, **kwargs: real(citations, registry, spans, **kwargs))
    overlay = dataclasses.replace(PACKAGE, v1=dataclasses.replace(V1, version_families={item: "fixture" for item in family}))
    monkeypatch.setattr(tutor_orchestrator, "get_config_package", lambda settings=None: overlay)
    orchestrator = TutorOrchestrator(TeachingAssistantService(get_retrieval_engine(), SETTINGS), SETTINGS)
    monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda: orchestrator)
    body = client.post("/assistant/chat", json={"message": "Why does routing depth matter?"}, headers=demo("p4-panel")).json()
    assert body["decision"] == "answer" and body["evidence"]["conflicts"] == [{"kind": "version_of_same_asset", "passages": [1, 2]}]
    off = Settings(evidence_panel_enabled=False)
    plain = TutorOrchestrator(TeachingAssistantService(get_retrieval_engine(), off), off)
    monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda: plain)
    body = client.post("/assistant/chat", json={"message": "Why does routing depth matter?"}, headers=demo("p4-panel")).json()
    assert "evidence" not in body


def test_ac_4_6_with_no_disclosure_shown_a_contained_answer_quoting_conflicting_spans_is_withheld(monkeypatch, caplog):
    # AC-4-6 on the learner path: with the evidence panel off (its default outside development) nothing discloses a
    # conflict, so the legacy guard withholds the answer (V1.7 / conflict_withheld) as today's abstention, on the tutor
    # and the Q&A surface; with the panel on the same answer is delivered with the panel's conflicts.
    citations, family = _family_citations()
    overlay = dataclasses.replace(PACKAGE, v1=dataclasses.replace(V1, version_families={item: "fixture" for item in family}))
    real = contain_answer
    for module in (tutor_orchestrator, qa_engine):
        monkeypatch.setattr(module, "contain_answer", lambda _citations, registry, spans, **kwargs: real(citations, registry, spans, **kwargs))
        monkeypatch.setattr(module, "get_config_package", lambda settings=None: overlay)
    for panel in (True, False):
        settings = Settings(evidence_panel_enabled=panel)
        orchestrator = TutorOrchestrator(TeachingAssistantService(get_retrieval_engine(), settings), settings)
        monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda orchestrator=orchestrator: orchestrator)
        monkeypatch.setattr(qa_route, "get_qa_engine", lambda settings=settings: QAEngine(get_retrieval_engine(), settings))
        V1_METRICS.reset()
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="qcai.tutor"):
            chat = client.post("/assistant/chat", json={"message": "Why does routing depth matter?"}, headers=demo("p4-conflict")).json()
            asked = client.post("/qa/ask", json={"question": "Why does routing depth matter?"}, headers=demo("p4-conflict")).json()
        lines = _events(caplog, "tutor.v1.legacy_guard_withheld")
        guard = V1_METRICS.detail_snapshot()["legacy_guard"]
        if panel:
            assert (chat["decision"], asked["decision"]) == ("answer", "answer")
            assert chat["evidence"]["conflicts"] == asked["evidence"]["conflicts"] == [{"kind": "version_of_same_asset", "passages": [1, 2]}]
            assert lines == [] and guard["by_check"]["V1.7"] == 0
        else:
            for body in (chat, asked):
                assert (body["decision"], body["answer"], body["citations"], body["claims"] if "claims" in body else []) == ("abstain", ABSTENTION, [], [])
                assert "evidence" not in body
            assert [(line["check_id"], line["reason_code"], line["surface"]) for line in lines] == [
                ("V1.7", "conflict_withheld", "tutor"), ("V1.7", "conflict_withheld", "qa")]
            assert guard["by_check"]["V1.7"] == 2 and guard["withheld"] == {"tutor": 1, "qa": 1}


def test_ac_4_6_under_the_withhold_policy_conflicting_quotations_are_withheld_even_with_the_panel_on(monkeypatch, caplog):
    # AC-4-6 "a disclosure block is shown or the response withheld": the package's conflict policy v1.v1_7.on_conflict
    # (an owner value under Q-22) governs the learner path as it governs the two-pass V1.7. Under withhold the legacy
    # guard withholds the answer on the tutor and the Q&A surface although the evidence panel is on.
    citations, family = _family_citations()
    overlay = dataclasses.replace(PACKAGE, v1=dataclasses.replace(V1, version_families={item: "fixture" for item in family},
                                                                  on_conflict="withhold"))
    real = contain_answer
    for module in (tutor_orchestrator, qa_engine):
        monkeypatch.setattr(module, "contain_answer", lambda _citations, registry, spans, **kwargs: real(citations, registry, spans, **kwargs))
        monkeypatch.setattr(module, "get_config_package", lambda settings=None: overlay)
    settings = Settings(evidence_panel_enabled=True)
    orchestrator = TutorOrchestrator(TeachingAssistantService(get_retrieval_engine(), settings), settings)
    monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda: orchestrator)
    monkeypatch.setattr(qa_route, "get_qa_engine", lambda: QAEngine(get_retrieval_engine(), settings))
    V1_METRICS.reset()
    with caplog.at_level(logging.WARNING, logger="qcai.tutor"):
        chat = client.post("/assistant/chat", json={"message": "Why does routing depth matter?"}, headers=demo("p4-withhold")).json()
        asked = client.post("/qa/ask", json={"question": "Why does routing depth matter?"}, headers=demo("p4-withhold")).json()
    for body in (chat, asked):
        assert (body["decision"], body["answer"], body["citations"]) == ("abstain", ABSTENTION, [])
        assert not (body.get("evidence") or {}).get("conflicts")
    assert [(line["check_id"], line["reason_code"], line["surface"]) for line in _events(caplog, "tutor.v1.legacy_guard_withheld")] == [
        ("V1.7", "conflict_withheld", "tutor"), ("V1.7", "conflict_withheld", "qa")]
    assert V1_METRICS.detail_snapshot()["legacy_guard"]["by_check"]["V1.7"] == 2


def test_ac_4_6_a_stored_answer_quoting_conflicting_spans_is_shown_again_with_its_disclosure(monkeypatch):
    # AC-4-6 on every surface that shows a stored answer again: with the panel on, the answer quoting conflicting
    # passages is delivered with the panel's conflicts and stored; GET /assistant/threads/{id}, GET /qa/history and the
    # owner's and the reviewer's GET /ledger/responses/{turn_id} then return its labels whatever EVIDENCE_PANEL_ENABLED
    # says at read time. They are the V1.7 labels of the package in force at read time, not stored ones: under the
    # shipped package (no fixture family) the same stored answer carries none, and no conflicts key (DI-68).
    citations, family = _family_citations()
    overlay = dataclasses.replace(PACKAGE, v1=dataclasses.replace(V1, version_families={item: "fixture" for item in family}))
    real = contain_answer
    for module in (tutor_orchestrator, qa_engine):
        monkeypatch.setattr(module, "contain_answer", lambda _citations, registry, spans, **kwargs: real(citations, registry, spans, **kwargs))
    expected = [{"kind": "version_of_same_asset", "passages": [1, 2]}]

    def use(package, settings):
        for module in (tutor_orchestrator, qa_engine, qa_route, ledger_route):
            monkeypatch.setattr(module, "get_config_package", lambda settings=None: package)
        orchestrator = TutorOrchestrator(TeachingAssistantService(get_retrieval_engine(), settings), settings)
        monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda: orchestrator)
        monkeypatch.setattr(qa_route, "get_qa_engine", lambda: QAEngine(get_retrieval_engine(), settings))

    headers = demo("p4-reread")
    reviewer = {**demo("p4-reread-reviewer"), "x-demo-role": "reviewer"}
    use(overlay, Settings(evidence_panel_enabled=True))
    chat = client.post("/assistant/chat", json={"message": "Why does routing depth matter?"}, headers=fresh(headers)).json()
    asked = client.post("/qa/ask", json={"question": "Why does routing depth matter?"}, headers=fresh(headers)).json()
    assert (chat["decision"], asked["decision"]) == ("answer", "answer")
    assert chat["evidence"]["conflicts"] == asked["evidence"]["conflicts"] == expected
    for package, panel, labels in ((overlay, True, expected), (overlay, False, expected), (PACKAGE, True, None)):
        use(package, Settings(evidence_panel_enabled=panel))
        thread = client.get(f"/assistant/threads/{chat['thread_id']}", headers=fresh(headers))
        assert thread.status_code == 200
        question, reply = thread.json()["messages"]
        assert (question["role"], reply["role"], reply["content"]) == ("user", "assistant", chat["answer"])
        assert "conflicts" not in question and reply.get("conflicts") == labels and ("conflicts" in reply) == (labels is not None)
        history = client.get("/qa/history", headers=fresh(headers))
        assert history.status_code == 200
        # Both stored answers: the /qa/ask row and the tutor turn's own Q&A row.
        items = [item for item in history.json() if item["answer"] == chat["answer"]]
        assert len(items) == 2 and asked["answer"] == chat["answer"]
        assert all(item.get("conflicts") == labels and ("conflicts" in item) == (labels is not None) for item in items)
        for reader in (headers, reviewer):
            read = client.get(f"/ledger/responses/{chat['turn_id']}", headers=fresh(reader))
            assert read.status_code == 200
            record = read.json()["record"]
            assert record["delivery"] == "legacy" and len(record["claims"]) == 2
            assert record.get("conflicts") == labels and ("conflicts" in record) == (labels is not None)


# ======================================================================================================== AC-4-7


@pytest.mark.parametrize("kind", ["raising", "wrong_type", "late"])
def test_ac_4_7_an_unavailable_or_late_checker_makes_the_decision_abstain(kind, caplog):
    clock = InjectedClock()
    checker = {"raising": RaisingChecker(), "wrong_type": WrongTypeChecker(), "late": LateChecker(clock, 51)}[kind]
    pipeline = dev_pipeline(checker=checker)
    pipeline.v1_params = dataclasses.replace(pipeline.v1_params, checker_timeout_ms=50)
    pipeline.v1_clock = clock
    V1_METRICS.reset()
    with caplog.at_level(logging.WARNING, logger="qcai.tutor"):
        result = run(pipeline, MULTI_CLAIM)
    record = result.entry.verification
    assert (result.decision, result.abstention_reason, record.final, record.hard_fail) == ("abstain", "checker_unavailable", "abstain", False)
    assert [(r.outcome, r.claim_id) for r in record.checks if r.check_id == "V1.3"] == [("abstain", None)]
    assert V1_METRICS.detail_snapshot()["v1_3"]["unavailable"] == 1
    (line,) = _events(caplog, "tutor.v1.checker_unavailable")
    assert line["cause"] == ("timeout" if kind == "late" else "error")


# =============================================================================================== plan G / L / D / I / H


@pytest.fixture
def isolated(fresh_database_url):
    engine = create_engine(fresh_database_url)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    yield engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)
    engine.dispose()


def test_plan_g_ledger_v2_is_additive_and_old_records_still_verify(isolated, tmp_path):
    from tutor_fakes import make_entry

    engine, factory = isolated
    ledger.append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
    # MODEL_GATEWAY off: this test's subject is the v2 record beside v1 (Phase 5 spec 13.3; test_v2_ledger_records.py has v3).
    run(dev_pipeline(Settings(v1_pipeline="off", model_gateway="off"), session_factory=factory), MULTI_CLAIM, record=True)
    shadow = run(dev_pipeline(Settings(v1_pipeline="shadow", model_gateway="off"), session_factory=factory), MULTI_CLAIM, record=True,
                 legacy_decision="answer")
    with factory() as db:
        schemas = [row.entry_schema for row in db.scalars(select(ResponseLedgerRecord).order_by(ResponseLedgerRecord.seq))]
        assert schemas == ["ledger-entry-v1", "ledger-entry-v1", "ledger-entry-v2"]
        assert ledger.verify_response_ledger(db).ok
        exported = tmp_path / "ledger.jsonl"
        assert ledger.export_ledger(db, exported) == 3
        intents = ledger.pending_v3_intents(db)
        provenance = ledger.ledger_provenance(db, PACKAGE)
    assert {item["claim_id"] for item in intents} == {v.claim_id for v in shadow.entry.verification.verdicts if v.v3 is not None}
    assert provenance["problem_count"] == 0
    script = REPO_ROOT / "scripts" / "verify_ledger.py"
    url = engine.url.render_as_string(hide_password=False)
    completed = subprocess.run([sys.executable, str(script), "--database-url", url, "--check-provenance"], capture_output=True, text=True, timeout=180)
    assert completed.returncode == 0, completed.stderr
    restored_url = str(tmp_path / "restored.db")
    restored = create_engine(f"sqlite:///{restored_url}")
    Base.metadata.create_all(restored)
    run_schema_upgrades(restored)
    with sessionmaker(bind=restored)() as db:
        assert ledger.restore_ledger(db, exported)[0] == 3
        assert ledger.verify_response_ledger(db).ok
    restored.dispose()
    lines = exported.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[-1])
    entry = json.loads(row["entry"])
    entry["verification"]["final"] = "deliver"
    row["entry"] = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    row["entry_sha256"] = contracts.sha256_hex(row["entry"].encode("utf-8"))
    row["record_hash"] = ledger.record_hash_for(seq=row["seq"], created_at=__import__("datetime").datetime.fromisoformat(row["created_at"]),
                                                prev_hash=row["prev_hash"], entry_sha256=row["entry_sha256"])
    tampered = tmp_path / "tampered.jsonl"
    tampered.write_text("\n".join([*lines[:-1], json.dumps(row)]) + "\n", encoding="utf-8")
    again = create_engine(f"sqlite:///{tmp_path / 'again.db'}")
    Base.metadata.create_all(again)
    run_schema_upgrades(again)
    with sessionmaker(bind=again)() as db, pytest.raises(ledger.LedgerRestoreRefused, match="entry fails ledger-entry-v2"):
        ledger.restore_ledger(db, tampered)
    again.dispose()


def _band_package(tmp_path) -> Path:
    return temp_package(tmp_path, edit=lambda raw: raw["v1"]["v1_9"]["readability"].update(min_grade=0.0, max_grade=1.0))


def test_plan_g_shadow_logs_disagreements_with_the_phase_3_decision_path(tmp_path, caplog):
    settings = Settings(v1_pipeline="shadow", config_package_path=str(_band_package(tmp_path)))
    V1_METRICS.reset()
    with caplog.at_level(logging.INFO, logger="qcai.tutor"):
        result = run(dev_pipeline(settings), MULTI_CLAIM, legacy_decision="answer")
    record = result.entry.verification
    assert result.decision == "answer" and result.entry.decision == "answer" and record.final == "abstain"
    assert record.final_reason == "readability_out_of_band" and record.comparison.agrees_phase3 is False
    lines = _events(caplog, "tutor.v1.disagreement")
    assert {line["with"] for line in lines} == {"phase3", "legacy"} and all(set(line) >= {"with", "v1_outcome", "reference"} for line in lines)
    serialised = json.dumps(lines)
    assert MULTI_CLAIM not in serialised and "shadow-" not in serialised and "turn-" not in serialised
    assert V1_METRICS.detail_snapshot()["disagreements"] == {"phase3": 1, "legacy": 1}


def _forge(kind: str):
    def forged(real):
        def wrapper(citations, registry, spans=None, **kwargs):
            contained = real(citations, registry, spans, **kwargs)
            if contained.decision != "answer":
                return contained
            claim = contained.claims[0]
            if kind == "number":
                changed = claim.model_copy(update={"text": claim.text + " 999 qubits"})
            else:
                changed = claim.model_copy(update={"cited_span_ids": ["span-" + "e" * 64]})
            return dataclasses.replace(contained, claims=[changed, *contained.claims[1:]])
        return wrapper
    return forged


@pytest.mark.parametrize("path", ["/assistant/chat", "/tutor/turns"])
def test_plan_g_a_route_turn_s_shadow_record_compares_v1_with_the_decision_the_learner_received(monkeypatch, path):
    # Spec R-b: the shadowed path includes the legacy contained decision the learner received. A real turn carries it
    # to its shadow record (orchestrator -> ShadowJob -> PipelineInput -> V1Context), where plan G's comparison and
    # D-20's replacement read it. Three turns: answered; withheld by the legacy guard (the learner gets the
    # abstention while the shadow's own retrieval answers, so V1 disagrees); and off-topic (both abstain).
    question = "Why does routing depth matter on sparse hardware?"
    headers = demo("p4-legacy-decision")
    turns = [(client.post(path, json={"message": question}, headers=fresh(headers)).json(), "answer", "withhold", "extractive_d19", True)]
    monkeypatch.setattr(tutor_orchestrator, "contain_answer", _forge("span")(contain_answer))
    turns.append((client.post(path, json={"message": question}, headers=fresh(headers)).json(), "abstain", "withhold", "abstention", False))
    monkeypatch.setattr(tutor_orchestrator, "contain_answer", contain_answer)
    turns.append((client.post(path, json={"message": OFF_TOPIC[0]}, headers=fresh(headers)).json(), "abstain", "abstain", "none", True))
    for body, decision, final, replacement, agrees in turns:
        assert body["decision"] == decision, body
        with SessionLocal() as db:
            rows = list(db.scalars(select(ResponseLedgerRecord).where(ResponseLedgerRecord.shadowed_response_id == body["turn_id"])))
        # The development default (MODEL_GATEWAY=shadow) records V2's shadow beside V1: a ledger-entry-v3 (Phase 5 spec 13.3).
        # Since Phase 7 the development default (EHMF=shadow) types it: a ledger-entry-v4, which extends v3 (Phase 7 spec 13.3).
        assert len(rows) == 1 and rows[0].entry_schema == "ledger-entry-v4"
        verification = json.loads(rows[0].entry)["verification"]
        comparison = verification["comparison"]
        assert (comparison["legacy_decision"], comparison["agrees_legacy"]) == (decision, agrees), (path, decision)
        assert (verification["final"], verification["replacement"]) == (final, replacement), (path, decision)
        if final == "withhold":
            assert verification["final_reason"] == "d20_interim_withhold"


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
def test_plan_l_v1_1_and_v1_2_are_enforced_on_every_delivery_path_in_every_mode(monkeypatch, mode, caplog):
    settings = Settings(v1_pipeline=mode)
    question = "Why does routing depth matter on sparse hardware?"
    orchestrator = TutorOrchestrator(TeachingAssistantService(get_retrieval_engine(), settings), settings)
    monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda: orchestrator)
    engine = QAEngine(get_retrieval_engine(), settings)
    monkeypatch.setattr(qa_route, "get_qa_engine", lambda: engine)
    headers = demo("p4-guard")
    unforged = {path: client.post(path, json=payload, headers=fresh(headers)).json()
                for path, payload in (("/assistant/chat", {"message": question}), ("/qa/ask", {"question": question}))}
    assert all(body["decision"] == "answer" for body in unforged.values())
    for kind in ("number", "span"):
        monkeypatch.setattr(tutor_orchestrator, "contain_answer", _forge(kind)(contain_answer))
        monkeypatch.setattr(qa_engine, "contain_answer", _forge(kind)(contain_answer))
        V1_METRICS.reset()
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="qcai.tutor"):
            bodies = {path: client.post(path, json=payload, headers=fresh(headers)).json()
                      for path, payload in (("/assistant/chat", {"message": question}), ("/tutor/turns", {"message": question}),
                                            ("/qa/ask", {"question": question}))}
        for path, body in bodies.items():
            assert (body["answer"], body["decision"], body["citations"], body.get("claims", [])) == (ABSTENTION, "abstain", [], []), path
            assert body["grounded"] is False
        surfaces = [line["surface"] for line in _events(caplog, "tutor.v1.legacy_guard_withheld")]
        assert sorted(surfaces) == ["qa", "tutor", "tutor"]
        assert V1_METRICS.detail_snapshot()["legacy_guard"]["withheld"] == {"tutor": 2, "qa": 1}
    monkeypatch.setattr(tutor_orchestrator, "contain_answer", contain_answer)
    monkeypatch.setattr(qa_engine, "contain_answer", contain_answer)
    again = client.post("/qa/ask", json={"question": question}, headers=fresh(headers)).json()
    assert again == unforged["/qa/ask"]


def test_plan_l_the_unforged_answer_is_byte_identical_across_modes():
    question = "Why does routing depth matter on sparse hardware?"
    bodies = []
    for mode in ("off", "shadow", "enforce"):
        engine = QAEngine(get_retrieval_engine(), Settings(v1_pipeline=mode))
        bodies.append(engine.ask(question).model_dump_json())
    assert bodies[0] == bodies[1] == bodies[2]


def test_plan_l_flag_back_to_shadow_restores_the_phase_3_decision_and_keeps_the_verdict(tmp_path):
    path = str(_band_package(tmp_path))
    enforced = run(dev_pipeline(Settings(v1_pipeline="enforce", config_package_path=path)), MULTI_CLAIM).entry
    shadowed = run(dev_pipeline(Settings(v1_pipeline="shadow", config_package_path=path)), MULTI_CLAIM).entry
    phase3 = run(dev_pipeline(Settings(v1_pipeline="off", config_package_path=path)), MULTI_CLAIM).entry
    assert enforced.decision == "abstain" and enforced.abstention_reason == "readability_out_of_band"
    assert shadowed.decision == phase3.decision == "answer" and shadowed.claim_set_hash == phase3.claim_set_hash
    assert shadowed.rendered_text_sha256 == phase3.rendered_text_sha256
    assert shadowed.verification.final == enforced.verification.final == "abstain"
    assert shadowed.verification.final_reason == enforced.verification.final_reason


def test_plan_l_the_stop_conditions_are_named_in_package_v3_and_the_fixture_runner_exits_3(fixture_report, tmp_path):
    stop = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))["v1"]["stop"]
    assert stop["provisional"] is True and stop["v1_p95_latency_ms"] == 250 and stop["composition"]["rule"] == "v1-adds-no-in-domain-abstention-v1"
    floor = load_config_package(temp_package(tmp_path, edit=lambda raw: raw["v1"]["stop"]["answer_rate_floor"].update(
        {"bm25f-v1": {"answered": 167, "in_domain": 174}})), governed=False)
    report = json.loads(json.dumps(fixture_report))
    assert RUNNER.evaluate(report, floor)[0] == "stop"
    report["result"] = "stop"
    assert RUNNER.exit_code(report) == RUNNER.EXIT_STOP
    budget = load_config_package(temp_package(tmp_path / "budget", edit=lambda raw: raw["v1"]["stop"].update(v1_p95_latency_ms=1)), governed=False)
    slow = json.loads(json.dumps(fixture_report))
    slow["latency"]["p95_ms"] = RUNNER.nearest_rank_p95([5.0] * 20)  # an injected slow clock: every run 5 ms
    assert RUNNER.evaluate(slow, budget) == ("stop", ["the V1 p95 latency 5.0 ms is above its budget 1 ms"])
    target = IN_DOMAIN[1]

    class Crippled:
        def __init__(self, inner):
            self.inner, self.ref = inner, inner.ref

        def propose(self, envelope):
            plan = self.inner.propose(envelope)
            return plan.model_copy(update={"claims": ()}) if envelope.question == target else plan

    block = RUNNER.answer_rate_block(RUNNER.gate_environment("bm25f-v1"), V1, [], track_hook=lambda pipeline: setattr(pipeline, "generator", Crippled(pipeline.generator)))
    crippled = {**json.loads(json.dumps(fixture_report)), "answer_rate": [block]}
    result, problems = RUNNER.evaluate(crippled, PACKAGE)
    assert result == "stop" and any("adds in-domain abstentions" in problem for problem in problems)


def test_plan_d_the_digest_and_overlap_gate_paths_are_gone_and_stay_gone():
    from app.services import claim_gate

    assert not hasattr(claim_gate, "ClaimGate") and not hasattr(claim_gate, "evidence_digest") and not hasattr(claim_gate, "_STOPWORDS")
    sources = [*sorted((API_ROOT / "app").rglob("*.py")), *sorted((REPO_ROOT / "scripts").glob("*.py"))]
    assert any("workers" in str(path) for path in sources)
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                assert node.name != "ClaimGate", path
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.name != "evidence_digest" and "_digest_answer" not in node.name, (path, node.name)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr != "_ask_vertex", path
            if isinstance(node, ast.keyword) and node.arg == "grounded":
                assert not (isinstance(node.value, ast.Constant) and node.value.value is True), path
    import inspect

    chat = inspect.getsource(TutorOrchestrator.chat)
    assert chat.index("guard_contained(") < chat.index("answer=contained.answer")
    ask = inspect.getsource(QAEngine.ask)
    assert ask.index("guard_contained(") < ask.index("answer=contained.answer")


def test_plan_d_hard_fail_is_typed_so_v2_cannot_be_consulted_and_v1_3_never_hard_fails():
    assert "hard_fail" not in contracts.REASON_OUTCOMES["V1.3"].values()
    for checker in (None, AlwaysSupportedChecker(), AlwaysContradictedChecker(), RaisingChecker(), WrongTypeChecker()):
        record = run(dev_pipeline(checker=checker), MULTI_CLAIM).entry.verification
        assert all(r.outcome != "hard_fail" for r in record.checks if r.check_id == "V1.3")


def test_plan_e_with_no_checker_v1_3_flags_every_claim_and_every_answer_is_withheld():
    pipeline = dev_pipeline()
    answered = 0
    for index, query in enumerate(IN_DOMAIN[:30]):
        legacy = "answer" if index % 2 else "abstain"
        result = run(pipeline, query, legacy_decision=legacy)
        record = result.entry.verification
        assert {r.reason_code for r in record.checks if r.check_id == "V1.3"} <= {"no_checker"}
        assert all(v.final != "deliver" for v in record.verdicts)
        if result.decision == "answer":
            answered += 1
            assert record.final == "withhold" and record.replacement == {"answer": "extractive_d19", "abstain": "abstention"}[legacy]
            assert all(v.v3 is not None and "v1_3_flag" in v.v3.reasons for v in record.verdicts)
        assert "under_review" not in json.dumps(result.entry.model_dump(mode="json"))
    assert answered >= 15


def test_plan_d_thresholds_load_only_from_the_configuration_package(tmp_path):
    rules = API_ROOT / "app" / "services" / "v1_checks" / "rules.py"
    for path in sorted((API_ROOT / "app" / "services" / "v1_checks").glob("*.py")):
        if path == rules:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                assert node.value in (0, 1, -1), (path.name, node.value, node.lineno)
    loose = load_config_package(temp_package(tmp_path / "a", edit=lambda raw: raw["v1"]["v1_6"].update(assessment_threshold=0.01)), governed=False).v1
    from app.services.quiz_keys import QuizKeySource

    source = QuizKeySource(get_course_store().quiz_keys)
    plain = "Why does routing depth matter on sparse hardware?"
    assert not assessment_items(plain, source, v1=V1, stopwords=STOP) and assessment_items(plain, source, v1=loose, stopwords=STOP)
    sentence = "The routing stage inserts 12 extra swap gates into the compiled benchmark circuit."
    other = "The routing stage often inserts 13 swap gates into circuits."
    strict = load_config_package(temp_package(tmp_path / "b", edit=lambda raw: raw["v1"]["v1_7"].update(alignment_threshold=0.95)), governed=False).v1
    lenient = load_config_package(temp_package(tmp_path / "c", edit=lambda raw: raw["v1"]["v1_7"].update(alignment_threshold=0.3)), governed=False).v1
    assert disagreement(sentence, other, v1=lenient, stopwords=STOP) == "number_disagreement" and disagreement(sentence, other, v1=strict, stopwords=STOP) is None
    banded = run(dev_pipeline(Settings(config_package_path=str(_band_package(tmp_path / "d"))), checker=AlwaysSupportedChecker()), MULTI_CLAIM)
    assert banded.abstention_reason == "readability_out_of_band"


def test_plan_i_ready_reports_package_v3_and_the_v1_fields_and_no_shadow_outcome(monkeypatch):
    from app import main as main_module
    from app.services.retrieval_metrics import snapshot as retrieval_slis

    body = client.get("/ready").json()
    assert body["config_package_version"] == PACKAGE.package_version and body["config_package_sha256"] == PACKAGE.sha256
    assert (body["v1_pipeline"], body["v1_pipeline_setting"]) == ("enforce", "enforce")
    v1 = body["v1"]
    assert v1 == {"version": V1.version, "rules_hash": V1.rules_hash, "checker": {"hosting": "none", "model_id": "none"},
                  "misconception_library": {"version": V1.library_version, "entries": 0, "sha256": V1.library_sha256}, "fixtures_set_sha256": V1.fixtures_set_sha256,
                  "regeneration": {"generation": 2, "render": 2}, "readability_band": [-4.0, 64.0], "x4_margin": {"bm25f-v1": 2.4, "p1-floor": 0.0},
                  "stop": {"answer_rate_floor": {"bm25f-v1": "166/174", "p1-floor": "146/174"}, "v1_p95_latency_ms": 250},
                  "quiz_feedback": {"rule": "keys-after-saved-attempt-answered-only-v1", "provisional": True},
                  "provisional": True, "available": True, "legacy_guard": "on"}
    assert set(body["slis"]) == set(retrieval_slis()) | {"manifest_drift", "tutor_ledger", "two_pass_shadow"}
    before = main_module._build_fields()
    client.post("/assistant/chat", json={"message": "Why does routing depth matter?"}, headers=demo("p4-ready"))
    after_body = client.get("/ready").json()
    assert main_module._build_fields() == before and after_body["v1"] == v1
    assert set(after_body["slis"]["two_pass_shadow"]) == set(body["slis"]["two_pass_shadow"])

    def no_database(*args, **kwargs):
        raise AssertionError("_build_fields reads no database")

    monkeypatch.setattr(main_module, "SessionLocal", no_database)
    assert main_module._build_fields() == before


def test_plan_i_v1_metrics_report_resolution_hard_fails_flag_rate_latency_and_disagreements():
    V1_METRICS.reset()
    run(dev_pipeline(checker=AlwaysSupportedChecker()), MULTI_CLAIM)
    run(dev_pipeline(), MULTI_CLAIM)
    run(dev_pipeline(generator=ScriptedGenerator([[("x y z w", ["span-" + "e" * 64])]])), MULTI_CLAIM)
    run(dev_pipeline(Settings(v1_pipeline="shadow")), OFF_TOPIC[0], legacy_decision="answer")
    snapshot = V1_METRICS.detail_snapshot()
    assert snapshot["runs"] == {"shadow": 1, "enforce": 3}
    assert snapshot["citation_resolution"]["rate"] == 1.0 and snapshot["citation_resolution"]["checked"] > 0
    assert snapshot["hard_fail_rate"]["V1.1"] == round(1 / 3, 6) and snapshot["checks"]["V1.1"]["hard_fail"] == 3
    assert snapshot["v1_3"]["flag_rate"] is not None and 0 < snapshot["v1_3"]["flag_rate"] < 1
    assert sum(snapshot["latency_ms"]["buckets"].values()) == 4 and snapshot["latency_ms"]["p95"] is not None
    assert snapshot["latency_ms"]["budget"] == 250 and snapshot["latency_ms"]["stop"] is False
    assert snapshot["disagreements"] == {"phase3": 0, "legacy": 1}
    assert snapshot["finals"]["abstain"] == 2 and snapshot["v3_intents"] >= 1


def test_plan_i_the_hard_fail_rate_per_check_has_one_definition_in_process_in_the_report_and_in_the_runbook():
    # Spec 10.3: per check, the runs in which it hard-failed at least once over the runs in which it ran. A run whose
    # three V1.1 attempts all hard-fail is one hard-failed run, not three.
    V1_METRICS.reset()
    records = [run(pipeline, MULTI_CLAIM).entry.verification for pipeline in (
        dev_pipeline(generator=ScriptedGenerator([[("x y z w", ["span-" + "e" * 64])]])),
        dev_pipeline(checker=AlwaysSupportedChecker()),
        dev_pipeline(renderer=UnmappedRenderer(TemplateRenderer(), None), checker=AlwaysSupportedChecker()),
    )]
    snapshot = V1_METRICS.detail_snapshot()
    per_check = RUNNER._per_check(records)
    assert {check: block["hard_fail_rate"] for check, block in per_check.items()} == snapshot["hard_fail_rate"]
    assert {check: block["hard_fail"] for check, block in per_check.items()} == {check: counts["hard_fail"] for check, counts in snapshot["checks"].items()}
    assert (per_check["V1.1"]["runs"], per_check["V1.1"]["hard_fail"], per_check["V1.1"]["hard_fail_runs"]) == (3, 3, 1)
    assert per_check["V1.1"]["hard_fail_rate"] == round(1 / 3, 6)
    assert (per_check["V1.4"]["runs"], per_check["V1.4"]["hard_fail"], per_check["V1.4"]["hard_fail_runs"]) == (2, 3, 1)
    assert per_check["V1.4"]["hard_fail_rate"] == 0.5
    assert all(block["hard_fail_rate"] is None or 0 <= block["hard_fail_rate"] <= 1 for block in per_check.values())
    # The committed report and the runbook state the same rate.
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    for configuration in report["configurations"]:
        for block in configuration["per_check"].values():
            assert block["hard_fail_rate"] == (round(block["hard_fail_runs"] / block["runs"], 6) if block["runs"] else None)
    runbook = (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8")
    row = next(line for line in runbook.splitlines() if line.startswith("| `tutor.v1.run` |"))
    assert "runs whose `outcomes.<check>.hard_fail` is above 0, over the runs whose `outcomes` has `<check>`" in row
    assert "(`outcomes.<check>.hard_fail` over runs)" not in runbook


def test_plan_i_the_runbook_says_a_delivered_no_approved_span_also_counts_the_legacy_guard_s_withholdings(caplog):
    # A guard withholding (V1.1, V1.2, or V1.7 conflict_withheld) delivers today's abstention, whose reason is
    # no_approved_span, so the delivered-abstention SLI folds it in with the approval and verification gaps; the runbook
    # says so and names the line that tells them apart.
    contained, registry = _citations_for("Why does routing depth matter on sparse hardware?")
    answered = contain_answer(contained, registry, get_course_store().span_registry, settings=SETTINGS)
    claim = answered.claims[0].model_copy(update={"cited_span_ids": ["span-" + "e" * 64]})
    forged = dataclasses.replace(answered, claims=[claim, *answered.claims[1:]])
    from app.services.v1_checks import legacy_guard

    guarded = legacy_guard.guard_contained(forged, store=get_course_store(), package=PACKAGE, surface="qa")
    assert (guarded.contained.decision, guarded.contained.reason) == ("abstain", "no_approved_span") and guarded.withheld
    runbook = (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8")
    paragraph = next(line for line in runbook.splitlines() if line.startswith("A legacy delivery's abstention reason"))
    assert "`no_approved_span` only when" not in paragraph
    assert "the Phase 4 legacy guard withheld a contained answer" in paragraph and "`tutor.v1.legacy_guard_withheld`" in paragraph
    row = next(line for line in runbook.splitlines() if line.startswith("| Delivered abstention by reason |"))
    assert "`no_approved_span` holds the legacy guard's withholdings too" in row
    guard_row = next(line for line in runbook.splitlines() if line.startswith("| `tutor.v1.legacy_guard_withheld` |"))
    assert "names it `no_approved_span`" in guard_row
    # The code texts that define the reason say the same (P2-12-D-03 covers comments and docstrings).
    contracts_source = (API_ROOT / "app" / "services" / "tutor_pipeline" / "contracts.py").read_text(encoding="utf-8")
    comment = contracts_source.split("# The legacy contained path's own abstention reason", 1)[1].split("LEGACY_ABSTENTION_REASON =", 1)[0]
    comment = " ".join(comment.replace("#", " ").split())
    assert "keeps it only for a gate" not in comment and "legacy guard withheld the contained answer" in comment
    docstring = " ".join((ledger.delivered_abstention_reason.__doc__ or "").split())
    assert "legacy guard withheld the contained answer" in docstring and "tutor.v1.legacy_guard_withheld" in docstring


def test_plan_i_the_v1_3_flag_rate_has_one_definition_in_process_in_the_report_and_in_the_runbook(caplog):
    # Plan I "V1.3 flag rate": V1.3's claim-level results with outcome flag over its claim-level results (flag plus
    # pass), in process (V1_METRICS v1_3), in the fixture report (v1_3_flag_rate) and from the run log's outcomes (the
    # runbook's log-based metric). The run log's withheld_claims counts withheld verdicts for any reason: a claim V1.8
    # withholds is one, though V1.3 flagged nothing.
    from v1_fakes import fixture_library

    locked = run(dev_pipeline(), MULTI_CLAIM).locked
    words = sorted({word.lower().strip(".,;:") for word in locked.claims[0].text.split() if len(word) > 5})[:2]
    pipelines = (dev_pipeline(), dev_pipeline(checker=AlwaysSupportedChecker()),
                 dev_pipeline(checker=AlwaysSupportedChecker(), misconceptions=fixture_library([("MC-1", words)])))
    V1_METRICS.reset()
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="qcai.tutor"):
        records = [run(pipeline, MULTI_CLAIM).entry.verification for pipeline in pipelines]
    lines = _events(caplog, "tutor.v1.run")
    assert len(lines) == 3
    flags = sum(line["outcomes"]["V1.3"].get("flag", 0) for line in lines)
    passes = sum(line["outcomes"]["V1.3"].get("pass", 0) for line in lines)
    claim_level = [result for record in records for result in record.checks if result.check_id == "V1.3" and result.claim_id is not None]
    assert flags == sum(1 for result in claim_level if result.outcome == "flag") > 0 and flags + passes == len(claim_level) > flags
    snapshot = V1_METRICS.detail_snapshot()["v1_3"]
    assert (snapshot["flagged"], snapshot["claims_checked"], snapshot["flag_rate"]) == (flags, flags + passes, round(flags / (flags + passes), 6))
    misconception = lines[2]
    assert misconception["outcomes"]["V1.3"].get("flag", 0) == 0 and misconception["withheld_claims"] >= 1 and "flagged_claims" not in misconception
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    for configuration in report["configurations"]:
        block = configuration["v1_3_flag_rate"]
        assert block["rate"] == (round(block["flagged"] / block["checked"], 6) if block["checked"] else None)
    runbook = (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8")
    row = next(line for line in runbook.splitlines() if line.startswith("| `tutor.v1.run` |"))
    assert "V1.3 flag rate: the sum of `outcomes.V1.3.flag` over the sum of `outcomes.V1.3.flag` and `outcomes.V1.3.pass`" in row
    assert "`withheld_claims`" in row and "flagged_claims" not in runbook


def test_plan_i_the_runbook_names_every_configuration_override_the_api_records():
    # "Alert on overrides" (plan Phase 1 I): every detail main._record_configuration_overrides can emit is named on a
    # config.override line of the runbook, the Phase 4 v1_pipeline_enforce included.
    source = (API_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    function = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "_record_configuration_overrides")
    names = [node.elts[0].value for node in ast.walk(function)
             if isinstance(node, ast.Tuple) and len(node.elts) == 2 and isinstance(node.elts[0], ast.Constant) and isinstance(node.elts[0].value, str)]
    assert "v1_pipeline_enforce" in names and len(names) == len(set(names)) >= 16
    runbook = (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8")
    override_lines = [line for line in runbook.splitlines() if "config.override" in line]
    assert [name for name in names if not any(f"`{name}`" in line for line in override_lines)] == []
    # Under V1 enforce the shadow line's reason label takes the V1 abstention reasons too, and the runbook says so.
    row = next(line for line in runbook.splitlines() if line.startswith("| Shadow abstention by reason |"))
    assert "contracts.V1_ABSTENTION_REASONS" in row and all(f"`{reason}`" in row for reason in contracts.V1_ABSTENTION_REASONS)


def test_plan_h_and_ac_3_1_v1_checks_import_no_learner_module_and_hold_no_learner_state(caplog):
    forbidden = ("app.services.learner_record", "app.services.learner_progress", "app.services.learning_intelligence", "app.services.microlearning",
                 "app.core.auth", "app.api.routes", "app.services.answer_history", "app.services.retrieval_legacy_p1")
    modules = sorted((API_ROOT / "app" / "services" / "v1_checks").glob("*.py"))
    assert len(modules) >= 16
    for path in modules:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for name in names:
                assert not name.startswith(forbidden), (path.name, name)
    for field in LEARNER_STATE_FIELDS:
        with pytest.raises(ValidationError):
            CheckResult.model_validate({"check_id": "V1.1", "stage": "pre_render", "attempt": 1, "outcome": "pass", "ehmf_types": ["B"],
                                        "reason_code": "resolved", field: "learner state"})
    record = run(dev_pipeline(), MULTI_CLAIM).entry.verification.model_dump(mode="json")
    for field in LEARNER_STATE_FIELDS:
        with pytest.raises(ValidationError):
            VerificationRecord.model_validate({**record, field: "learner state"})
    marker = f"MARKER-{uuid4().hex}"
    headers = demo("p4-privacy")
    question = f"Why does routing depth matter? {marker}"
    with caplog.at_level(logging.INFO, logger="qcai.tutor"):
        response = client.post("/assistant/chat", json={"message": question}, headers=headers)
    turn_id = response.json()["turn_id"]
    with SessionLocal() as db:
        rows = list(db.scalars(select(ResponseLedgerRecord).where(ResponseLedgerRecord.shadowed_response_id == turn_id)))
    assert rows and rows[0].entry_schema == "ledger-entry-v4"  # the development default records V2's shadow (Phase 5), typed since Phase 7
    texts = [rows[0].entry, *[json.dumps(r.json_fields) for r in caplog.records if str(getattr(r, "json_fields", {}).get("event", "")).startswith("tutor.v1.")]]
    for text in texts:
        assert headers["x-demo-user"] not in text and marker not in text and question not in text


def test_invariant_6_no_two_pass_text_reaches_a_learner_with_v1_enforcing(monkeypatch):
    assert contracts.TWO_PASS_DELIVERY_IMPLEMENTED is False
    question = "Why does routing depth matter on sparse hardware?"
    bodies = []
    for settings in (Settings(two_pass_tutor="off"), Settings(two_pass_tutor="shadow", v1_pipeline="enforce")):
        orchestrator = TutorOrchestrator(TeachingAssistantService(get_retrieval_engine(), settings), settings)
        monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda orchestrator=orchestrator: orchestrator)
        body = client.post("/assistant/chat", json={"message": question}, headers=demo("p4-inv6")).json()
        bodies.append({key: value for key, value in body.items() if key not in {"thread_id", "turn_id"}})
    assert bodies[0] == bodies[1]
    with SessionLocal() as db:
        assert not list(db.scalars(select(ResponseLedgerRecord).where(ResponseLedgerRecord.delivery == "delivered")))


def test_freeze_production_bodies_are_unchanged_by_v1(monkeypatch, tmp_path):
    from app.core.manifest_v2 import with_all_public_approved

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(with_all_public_approved(json.loads(REPO_MANIFEST.read_text(encoding="utf-8")))), encoding="utf-8")
    settings = Settings(environment="production", enforce_corpus_governance=True, corpus_manifest_path=str(manifest))
    assert settings.v1_pipeline == "shadow" and settings.evidence_panel_enabled is False
    store = CourseStore(settings)
    engine = RetrievalEngine(store, settings)
    guarded = [QAEngine(engine, settings).ask(query).model_dump_json() for query in IN_DOMAIN[:8]]
    monkeypatch.setattr(qa_engine, "guard_contained", lambda contained, **kwargs: type("G", (), {"contained": contained, "withheld": ()})())
    identity = [QAEngine(engine, settings).ask(query).model_dump_json() for query in IN_DOMAIN[:8]]
    assert guarded == identity and any('"decision":"answer"' in body for body in guarded)
    assert all(set(json.loads(body)) == {"answer", "citations", "retrieval_mode", "decision", "grounded"} for body in guarded)


def test_settings_v1_pipeline_defaults_and_refusals(monkeypatch, fresh_database_url):
    assert Settings().v1_pipeline == "enforce" and Settings(environment="production").v1_pipeline == "shadow"
    with pytest.raises(ValidationError, match="13.6"):
        Settings(environment="production", v1_pipeline="off")
    with pytest.raises(ValidationError, match="phase4_exit_passed"):
        Settings(environment="production", v1_pipeline="enforce")
    from app.core import config_package as package_module

    claimed = dataclasses.replace(PACKAGE, flag_policy=dataclasses.replace(PACKAGE.flag_policy, phase4_exit_passed=True, phase4_exit_evidence="test"))
    monkeypatch.setattr(package_module, "get_config_package", lambda settings=None: claimed)
    allowed = Settings(environment="production", v1_pipeline="enforce")
    assert allowed.v1_pipeline == "enforce"
    monkeypatch.setattr(package_module, "get_config_package", lambda settings=None: dataclasses.replace(claimed, is_default_path=False))
    with pytest.raises(ValidationError, match="shipped, hash-verified"):
        Settings(environment="production", v1_pipeline="enforce")
    monkeypatch.undo()
    from test_configuration_overrides import _override_details

    assert _override_details(monkeypatch, allowed) == {"v1_pipeline_enforce": True}
    env = {"DATABASE_URL": fresh_database_url, "PYTHONUNBUFFERED": "1"}
    off = _startup({**env, "ENVIRONMENT": "production", "V1_PIPELINE": "off"})
    assert off.returncode != 0 and "V1_PIPELINE=off" in off.stderr
    governed = _startup({**env, "ENVIRONMENT": "development", "ENFORCE_CORPUS_GOVERNANCE": "true", "CONFIG_PACKAGE_PATH": str(V2_PACKAGE_PATH),
                         "CORPUS_MANIFEST_PATH": str(REPO_MANIFEST)})
    assert governed.returncode != 0 and "no v1 block" in governed.stderr
    # Outside development a governance override does not reopen the development fallback (plan 13.6).
    ungoverned = _startup({**env, "ENVIRONMENT": "production", "ENFORCE_CORPUS_GOVERNANCE": "false", "CONFIG_PACKAGE_PATH": str(V2_PACKAGE_PATH),
                           "CORPUS_MANIFEST_PATH": str(REPO_MANIFEST)})
    assert ungoverned.returncode != 0 and "ConfigPackageError: v1 checks: the configuration package has no v1 block" in ungoverned.stderr
    probe = create_engine(fresh_database_url)
    try:
        assert set(sa_inspect(probe).get_table_names()) == set()
    finally:
        probe.dispose()


def test_start_up_a_v1_package_problem_turns_v1_off_only_in_development_with_governance_off(monkeypatch, caplog):
    # Spec 10.1: the one path besides V1_PIPELINE=off on which the two-pass V1 mode is off (plan 13.6: "No flag ... MAY
    # disable V1"), and only in development with governance off; the legacy guard keeps running.
    from app import main as main_module
    from app.core.config_package import ConfigPackageError
    from app.services import v1_checks
    from app.services.v1_checks import legacy_guard, package_check

    problem = "v1.rules_hash differs from the code's rule vocabulary (test)"
    monkeypatch.setattr(package_check, "check_v1_package", lambda package, *, structural: [problem])
    assert main_module.settings.environment == "development" and main_module.settings.enforce_corpus_governance is False
    try:
        with caplog.at_level(logging.WARNING, logger="qcai.tutor"):
            main_module._check_v1_package(PACKAGE)
        assert v1_checks.V1_UNAVAILABLE_REASON == problem
        lines = _events(caplog, "tutor.v1.unavailable")
        assert len(lines) == 1 and lines[0]["reason"] == problem
        assert [r.levelno for r in caplog.records if getattr(r, "json_fields", {}).get("event") == "tutor.v1.unavailable"] == [logging.WARNING]
        assert v1_checks.mode(Settings(v1_pipeline="enforce"), PACKAGE) == v1_checks.mode(Settings(v1_pipeline="shadow"), PACKAGE) == "off"
        body = client.get("/ready").json()
        assert (body["v1_pipeline"], body["v1_pipeline_setting"], body["v1"]["available"]) == ("off", "enforce", False)
        # The two-pass shadow runs the Phase 3 composition alone (a ledger-entry-v1 record, no V1 verdict) ...
        result = run(dev_pipeline(), MULTI_CLAIM, legacy_decision="answer")
        assert result.v1 is None and result.entry.entry_schema == "ledger-entry-v1"
        # ... while the legacy guard still withholds a forged quotation.
        store = get_course_store()
        answered = contain_answer(*_citations_for("Why does routing depth matter on sparse hardware?"), store.span_registry, settings=SETTINGS)
        assert answered.decision == "answer"
        claim = answered.claims[0].model_copy(update={"cited_span_ids": ["span-" + "e" * 64]})
        forged = dataclasses.replace(answered, claims=[claim, *answered.claims[1:]])
        guarded = legacy_guard.guard_contained(forged, store=store, package=PACKAGE, surface="qa")
        assert guarded.withheld[0] == ("V1.1", "unresolvable") and guarded.contained.decision == "abstain"
        # A governed build, and any build outside development whatever its governance setting, stops instead.
        for settings in (Settings(enforce_corpus_governance=True), Settings(environment="production", enforce_corpus_governance=False),
                         Settings(environment="staging", enforce_corpus_governance=False)):
            v1_checks.V1_UNAVAILABLE_REASON = None
            monkeypatch.setattr(main_module, "settings", settings)
            with pytest.raises(ConfigPackageError, match="v1 checks: v1.rules_hash differs"):
                main_module._check_v1_package(PACKAGE)
            assert v1_checks.V1_UNAVAILABLE_REASON is None
    finally:
        v1_checks.V1_UNAVAILABLE_REASON = None


def _citations_for(query: str):
    from app.core.corpus_governance import get_corpus_registry
    from app.services.provenance import native_citation

    store = get_course_store()
    retrieval = RetrievalEngine(store, SETTINGS).search(query, top_k=4, surface="qa")
    return [native_citation(hit, corpus_version=store.corpus_version, settings=SETTINGS) for hit in retrieval.results], get_corpus_registry(SETTINGS)


def _startup(extra: dict[str, str]) -> subprocess.CompletedProcess:
    import os

    env = {key: value for key, value in os.environ.items() if key not in {"V1_PIPELINE", "CONFIG_PACKAGE_PATH", "ENFORCE_CORPUS_GOVERNANCE"}}
    env.update(extra)
    return subprocess.run([sys.executable, "-c", "from app.main import _initialize_database; _initialize_database()"], cwd=API_ROOT, env=env,
                          capture_output=True, text=True, timeout=240)


def test_phase4_docs_quote_plan_m_and_state_the_current_rules():
    # P2-12-D-03: the authoritative text states the current code, and plan text is quoted exactly.
    plan_m = "Residual: checker error, paraphrased leakage."
    adr = (REPO_ROOT / "docs" / "adr" / "ADR-005-abstention-gate.md").read_text(encoding="utf-8")
    readme = (REPO_ROOT / "docs" / "evaluation" / "phase4" / "README.md").read_text(encoding="utf-8")
    for name, text in (("ADR-005", adr), ("README", readme), ("spec", SPEC)):
        assert plan_m in text, name
        assert "named by plan M (checker error, paraphrased leakage, paraphrased contradiction)" not in text, name
        assert "it (plan M)" not in text, name
    # The legacy guard's polarity rule runs claim to span: a quotation never adds a number or a cue, but may omit one.
    assert "keeps the span's numbers and negations" not in adr
    assert "holds no number or negation cue that its span lacks" in adr
    # Spec 12.1 counts the fixture's own synthetic queries: those not taken from the public fixture queries.
    public = set(IN_DOMAIN) | set(OFF_TOPIC)
    synthetic = {case["query"] for case in json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))["cases"]
                 if case.get("query") and case["query"] not in public}
    words = {3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}
    assert f"and {words[len(synthetic)]} short synthetic keyword queries" in SPEC
    # M2 counts the synthetic queries whose envelope holds spans of both fixture-family items: the conflict_version
    # cases' queries, all synthetic (the unit_swap query retrieves neither item).
    family_queries = {case["query"] for case in json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))["cases"] if case["class"] == "conflict_version"}
    assert family_queries <= synthetic and len(family_queries) < len(synthetic)
    assert f"{words[len(family_queries)]} synthetic keyword queries put spans of both in one envelope (the `conflict_version` cases, 12.1)" in SPEC
    assert f"{words[len(synthetic)]} synthetic keyword queries put spans of both" not in SPEC
    # The runbook names the rollback order and the README the provenance of the committed records.
    runbook = (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8")
    assert "**Rollback order: the API first, then the frontend**" in runbook and "Auto-score: N / N" in runbook
    # The Phase 3 runbook's package steps name the shipped package, which is v3 from the Phase 4 release.
    phase3_runbook = runbook.split("## Phase 3: two-channel tutor", 1)[1].split("\n## Phase 4", 1)[0]
    assert "for v2 (the default)" not in phase3_runbook and "configuration package v2 `tutor_pipeline.budgets`" not in phase3_runbook
    assert "the shipped package (v2 with the Phase 3 release; v3 from the Phase 4 release" in phase3_runbook
    assert "the shipped package's `tutor_pipeline.budgets` (PD-11; v2 with the Phase 3 release, v3 from the Phase 4 release" in phase3_runbook
    assert "# from a clean tree" not in readme and "**Provenance.**" in readme and "--allow-dirty" in readme


def test_phase4_docs_name_every_q_22_value_and_the_package_s_provisional_until():
    # The spec's DI-52 row names every value package v3 lists under owner_decisions.Q-22, and main.py's comment on
    # bm25f-v1's floor and margin states the package's abstention.provisional_until. Package v3 is the package this spec's
    # DI-52 row describes (the Phase 5 spec names v4's v2.voting; test_phase5_docs_quote_the_plan_and_state_the_current_rules).
    raw = json.loads(V3_PACKAGE_PATH.read_text(encoding="utf-8"))
    labels = {"v1.v1_5.x4_margin": "X4 margin", "abstention": "V1.5 floor and margin", "v1.v1_3.support_threshold": "V1.3 threshold",
              "v1.v1_7": "V1.7 alignment rule", "v1.v1_9.readability": "V1.9 band", "v1.stop": "stop values"}
    values = raw["owner_decisions"]["Q-22"]["provisional_values"]
    assert sorted(values) == sorted(labels)

    # Every block the package keeps provisional until Q-22 is one of them (the loader refuses a package otherwise).
    def until_q22(node, path):
        if not isinstance(node, dict):
            return []
        own = [path] if "Q-22" in str(node.get("provisional_until", "")) else []
        return own + [inner for key, value in node.items() for inner in until_q22(value, f"{path}.{key}" if path else key)]

    assert until_q22(raw, "") == ["abstention"] and set(until_q22(raw, "")) <= set(values)
    row = next(line for line in SPEC.splitlines() if line.startswith("| DI-52 |"))
    for value, label in labels.items():
        assert label in row, value
    until = raw["abstention"]["provisional_until"]
    assert until == "Q-22 (DI-52)" and f"`abstention.provisional_until` `{until}`" in row
    # Conflict 11 cites the provisional defaults the package's Q-22 record names, and no other.
    record = set(re.findall(r"PD-\d+", raw["owner_decisions"]["Q-22"]["record"]))
    conflict_11 = SPEC.split("11. **Precondition \"V1.3, X4 and V1.9 values", 1)[1].split("\n12. ", 1)[0]
    assert record == {"PD-15", "PD-16", "PD-18"} and set(re.findall(r"PD-\d+", conflict_11)) == record
    main_source = (API_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    comment = " ".join(line.strip().lstrip("# ") for line in main_source.split('"manifest_drift"', 1)[1].split('"threshold_version"', 1)[0].splitlines())
    assert "bm25f-v1's floor and margin" in comment and f"provisional until {until}" in comment
    assert "provisional until Phase 4" not in main_source


def test_phase4_docs_the_phase3_spec_states_what_phase4_changed():
    # Spec 7.14 (conflict 36): Phase 3 text that Phase 4 made false is edited in place. Its contracts listing holds the
    # code's ENTRY_SCHEMAS line, 5.2 names the shipped DEFAULT_PACKAGE_PATH, and no test description still asserts the
    # 2.0.0 package as the shipped one.
    phase3 = (REPO_ROOT / "docs" / "architecture" / "phase3-implementation-spec.md").read_text(encoding="utf-8")
    contracts_source = (API_ROOT / "app" / "services" / "tutor_pipeline" / "contracts.py").read_text(encoding="utf-8")
    entry_schemas = next(line for line in contracts_source.splitlines() if line.startswith("ENTRY_SCHEMAS"))
    assert entry_schemas in phase3 and '# SCHEMA_MODELS["LedgerEntryV2"] = LedgerEntryV2' in phase3
    assert "Phase 4 adds ledger-entry-v2." not in phase3
    shipped = re.search(r'^DEFAULT_PACKAGE_PATH = .*?"(v\d+\.json)"', (API_ROOT / "app" / "core" / "config_package.py").read_text(encoding="utf-8"),
                        flags=re.MULTILINE).group(1)
    assert shipped == DEFAULT_PACKAGE_PATH.name and f"`.../{shipped}` with Phase 9" in phase3
    assert "`DEFAULT_PACKAGE_PATH` becomes `.../v2.json`" not in phase3
    assert '`config_package_version == "2.0.0"`' not in phase3 and 'asserts `package_version == "2.0.0"`' not in phase3
    for test in ("test_plan_i_ready_reports_versions_ledger_head_and_two_pass_mode", "test_the_shipped_package_validates_and_matches_its_hash"):
        line = next(line for line in phase3.splitlines() if f"`{test}`" in line or f"::{test}`" in line)
        assert f"{PACKAGE.package_version} for Phase 9's v{PACKAGE.schema_version}" in line, test
    # 13.3 item 1 and 13.1 test 25 name the package their tests read; 5.2's parsing names every schema version the
    # loader accepts; the frontend row quotes the chat's render expression; 4.3 names the sufficiency's score.
    assert "`RAW` now reads v2" not in phase3 and f"`RAW` reads the shipped package (v{PACKAGE.schema_version} since Phase 9) and `V2_RAW` reads v2" in phase3
    assert "a copy of `v2.json`" not in phase3
    # The loader accepts schema versions 1 to LATEST_SCHEMA_VERSION (Phase 9 reads the bound from one constant, the ranking
    # schema, E16): load a copy of the shipped package at each bound and one past it.
    from app.core.config_package import LATEST_SCHEMA_VERSION, ConfigPackageError, parse_config_package

    source = (API_ROOT / "app" / "core" / "config_package.py").read_text(encoding="utf-8")
    assert "1 <= schema_version <= LATEST_SCHEMA_VERSION" in source and LATEST_SCHEMA_VERSION == PACKAGE.raw["schema_version"]
    for refused_version in (0, LATEST_SCHEMA_VERSION + 1, True):
        with pytest.raises(ConfigPackageError, match="schema_version"):
            parse_config_package({**PACKAGE.raw, "schema_version": refused_version}, path=PACKAGE.path, sha256="", hash_verified=False)
    assert "accepts `schema_version` 1 or 2. For 1" not in phase3 and f"accepts `schema_version` 1 or 2, 3 since Phase 4, 4 since Phase 5, 5 since Phase 6, and 6 since Phase 7, and {LATEST_SCHEMA_VERSION} since Phase 9" in phase3
    chat = (REPO_ROOT / "apps" / "frontend" / "src" / "components" / "teaching-assistant-chat.tsx").read_text(encoding="utf-8")
    render = next(line.strip() for line in chat.splitlines() if "<EvidencePanel evidence={message.evidence} />" in line)
    assert f"render `{render}`" in phase3
    sufficiency = next(line for line in phase3.splitlines() if "Decision `near_miss` when `top.near_floor`" in line)
    assert "`score = top.score`" not in sufficiency and "`score` is the top result's gate score" in sufficiency
    # 7.17's three-plan replay report shape gives config_package.version as the package in force, the version the
    # committed record (which `replay_tutor_plans.py --check` reads) holds.
    record = json.loads((REPO_ROOT / "docs" / "evaluation" / "phase3" / "three_plan_replay_v1.json").read_text(encoding="utf-8"))
    shape = phase3.split("**Report shape**", 1)[1].split("- **Exit codes:**", 1)[0]
    assert record["config_package"]["version"] == PACKAGE.package_version
    assert '"config_package": {"version": "2.0.0"' not in shape and '"config_package": {"version": "...", "sha256": "..."}' in shape
    assert f"{record['config_package']['version']} for Phase 9's v{PACKAGE.schema_version}, which the committed record holds" in shape
    assert "7.17's three-plan replay report shape" in _spec_head().split("### 7.14", 1)[1].split("### 7.15", 1)[0]


def test_phase4_docs_13_3_calls_unchanged_no_test_it_names_as_changed():
    # Spec 13.3 item 11 lists the existing tests that are unchanged since main; no test that another item of 13.3 names
    # as changed, and no group a change touched, may be listed there wholesale.
    section = SPEC.split("### 13.3 Existing tests that change", 1)[1].split("\n### 13.4", 1)[0]
    items = re.split(r"\n(?=\d+[a-z]?\. )", section)
    item_11 = next(item for item in items if item.startswith("11. "))
    unchanged = item_11.split("**Expected unchanged and verified**", 1)[1].split(". The package-copy tests changed", 1)[0]
    changed = {name for item in items if not item.startswith("11. ") for name in re.findall(r"test_[a-z0-9_]+", item)}
    named = set(re.findall(r"test_[a-z0-9_]+", unchanged))
    excepted = {"test_d9_ready_reports_the_configuration_package_corpus_gate_and_slis"}  # named as the exception
    assert changed and (named - excepted) & changed == set()
    for blanket in ("every Phase 3 doc-text test", "every package-copy test", "AC-3-6 tests;", "the Phase 2 `d9` tests;"):
        assert blanket not in unchanged, blanket
    assert "but `test_d9_ready_reports_the_configuration_package_corpus_gate_and_slis` (item 2b)" in unchanged


def test_phase4_docs_the_start_up_mode_and_settings_text_states_the_current_rules():
    # P2-12-D-03: docstrings and comments describe the current code. _check_tutor_pipeline_package runs the V1 package
    # check first, which stops every governed build and every build outside development whatever TWO_PASS_TUTOR says;
    # v1_checks.mode names enforce as refused only outside development (it is the development default); the settings
    # comments state EVIDENCE_PANEL_ENABLED's part in the legacy guard (V1.7) and name the guard by all its checks.
    import inspect

    from app import main as main_module
    from app.services import v1_checks

    def flat(text: str) -> str:
        return " ".join(text.split())

    start_up = flat(inspect.getdoc(main_module._check_tutor_pipeline_package))
    assert start_up.startswith("The package's V1 block, then its tutor-pipeline schema pins")
    assert "First _check_v1_package" in start_up and "every build outside development, whatever TWO_PASS_TUTOR says" in start_up
    mode_doc = flat(inspect.getdoc(v1_checks.mode))
    assert "enforce in development by default; outside development Settings refuse off, and refuse enforce before the Phase 4 exit" in mode_doc
    assert "Settings refuse off outside development and enforce before" not in mode_doc
    config = (API_ROOT / "app" / "core" / "config.py").read_text(encoding="utf-8")
    assert "V1.1/V1.2 legacy guard" not in config
    panel = flat(" ".join(line.strip().lstrip("# ") for line in
                          config.split("ledger_route_enabled: bool | None = None", 1)[1].split("evidence_panel_enabled: bool | None = None", 1)[0].splitlines()))
    assert "the legacy guard's disclosure_shown" in panel and "V1.7 finds in conflict" in panel
    assert "the thread, Q&A-history and ledger reads label it again" in panel
    assert "Under the policy withhold the guard withholds it whatever this setting says" in panel
    pipeline = flat(" ".join(line.strip().lstrip("# ") for line in
                             config.split("ledger_rate_limit: str", 1)[1].split("v1_pipeline: Literal", 1)[0].splitlines()))
    assert "V1.1 and V1.2 always, and V1.7 whenever no evidence panel shows the conflict" in pipeline
    assert "or the package's conflict policy (v1.v1_7.on_conflict) is withhold" in pipeline


def _flat(text: str) -> str:
    return " ".join(text.split())


def _comments(text: str) -> str:
    """The comment lines of a YAML or Python text, joined without their markers."""
    return _flat(" ".join(line.strip().lstrip("# ") for line in text.splitlines() if line.strip().startswith("#")))


def _spec_head() -> str:
    """Sections 0-17 of this phase's spec: the authoritative text."""
    return SPEC.split("\n## 18. Review history\n", 1)[0]


def _spec_line(start: str) -> str:
    return next(line for line in _spec_head().splitlines() if line.lstrip().startswith(start))


def _runbook(name: str, heading: str) -> str:
    text = (REPO_ROOT / "infra" / "cloudrun" / name).read_text(encoding="utf-8")
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


def test_phase4_docs_name_each_v1_rule_by_its_current_id():
    # The authoritative texts name every V1 rule by the id the code (rules.RULE_IDS) and package v3 hold, and no other
    # version of it: spec 5.1's listing of the v1_5 block names the package's rule.
    from app.services.v1_checks.rules import RULE_IDS

    raw = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
    assert raw["v1"]["rule_ids"] == RULE_IDS and raw["v1"]["v1_5"]["rule"] == RULE_IDS["V1.5"]
    adr = (REPO_ROOT / "docs" / "adr" / "ADR-005-abstention-gate.md").read_text(encoding="utf-8")
    strategy = (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
    texts = {"spec 0-17": _spec_head(), "ADR-005": adr.split("## Decision 2026-11-20", 1)[1],
             "test strategy": strategy.split("## Phase 4 acceptance map", 1)[1],
             "README": (REPO_ROOT / "docs" / "evaluation" / "phase4" / "README.md").read_text(encoding="utf-8"),
             "deployment.md": _runbook("deployment.md", "## Phase 4"), "observability.md": _runbook("observability.md", "## Phase 4")}
    for name, text in texts.items():
        for rule in RULE_IDS.values():
            family = re.sub(r"-v\d+$", "", rule)
            assert set(re.findall(rf"\b{re.escape(family)}-v\d+\b", text)) <= {rule}, (name, rule)
    block = _spec_head().split("### 5.1 File", 1)[1].split("`v1_5` (", 1)[1].split("), `v1_6`", 1)[0]
    assert f'`rule "{raw["v1"]["v1_5"]["rule"]}"`' in block and "gate score" in block


def test_phase4_docs_state_the_learner_path_v1_7_rule_wherever_they_name_it():
    # legacy_guard.may_disclose: on the learner path a V1.7 conflict is disclosed only under the package's policy
    # disclose with the evidence panel shown; with the panel off, or under withhold, the guard withholds the answer.
    # Every authoritative text that says when the guard withholds names both cases (spec R-a, conflict 3, section 2,
    # the AC-4-6 row, 4.8 item 4, 10.4; the v1_checks, Q&A and orchestrator docstrings; the env example; the
    # observability runbook), and the spec's lists of the reads that label a stored answer name the ledger read too.
    import inspect

    from app.services import v1_checks
    from app.services.v1_checks import legacy_guard

    withhold = dataclasses.replace(PACKAGE, v1=dataclasses.replace(V1, on_conflict="withhold"))
    assert PACKAGE.v1.on_conflict == "disclose" and legacy_guard.may_disclose(PACKAGE, disclosure_shown=True)
    assert not legacy_guard.may_disclose(PACKAGE, disclosure_shown=False) and not legacy_guard.may_disclose(withhold, disclosure_shown=True)
    head = _flat(_spec_head())
    for stale in ("V1.7 while no evidence panel is shown", "V1.7 when no panel is shown", "with no panel shown",
                  "or, with the panel off, the legacy guard withholds the answer", "the panel labels them; with the panel off"):
        assert stale not in head, stale
    statements = {
        "R-a": _spec_line('- In AC-4-6, "a disclosure block is shown"'),
        "conflict 3": _spec_line("- **Resolution:** `off` is development and test only"),
        "section 2": _spec_line("├─ contain_answer (D-19, unchanged)"),
        "AC-4-6 row": _spec_line("| AC-4-6 |"),
        "4.8 item 4": _spec_line("4. **Legacy path.**"),
        "10.4": _spec_line("| `tutor.v1.legacy_guard_withheld` |"),
    }
    for name, line in statements.items():
        # Withheld unless the policy is disclose and the panel shows the conflict: the line names the panel, and the
        # withhold value or the rule's "unless ... disclose".
        assert "panel" in line, name
        assert "`withhold`" in line or ("unless" in line and "disclose" in line), name
    for name in ("R-a", "AC-4-6 row"):
        assert "ledger read" in statements[name] and "current package" in statements[name], name
    assert "`GET /ledger/responses/{response_id}`" in statements["R-a"]
    docstrings = {"v1_checks": inspect.getdoc(v1_checks), "qa_engine": inspect.getdoc(qa_engine),
                  "tutor_orchestrator": inspect.getdoc(tutor_orchestrator)}
    for name, text in docstrings.items():
        flat = _flat(text)
        assert "conflict policy" in flat and "disclose" in flat, name
    assert "when no evidence panel discloses them" not in _flat(docstrings["v1_checks"])
    example = _comments((REPO_ROOT / "infra" / "cloudrun" / "api-production.env.example.yaml").read_text(encoding="utf-8"))
    assert "with it on, the package's conflict policy (v1.v1_7.on_conflict) decides: disclose labels the conflict, withhold withholds the answer" in example
    paragraph = next(line for line in (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8").splitlines()
                     if line.startswith("A legacy delivery's abstention reason"))
    assert "with no evidence panel shown" not in paragraph and "conflict policy `v1.v1_7.on_conflict` `withhold`" in paragraph


def test_phase4_docs_say_a_stored_answer_is_labelled_by_the_package_in_force_at_read_time():
    # Each read of a stored answer (the thread read, the Q&A history, the ledger read) applies the V1.7 rule of the
    # package in force at read time to the stored citations, and nothing stores the labels a delivery showed: the AC-4-6
    # stored-answer test reads an answer delivered with labels under one package and gets none under the shipped one.
    # So no text promises the same labels on every read, or that no read shows the quotations undisclosed; each names
    # the read-time package, and the residual is recorded (spec 4.15 item 3, 16.2, ADR-005; DI-68).
    import inspect

    from app.services import evidence_panel
    from app.services.v1_checks import legacy_guard

    adr = (REPO_ROOT / "docs" / "adr" / "ADR-005-abstention-gate.md").read_text(encoding="utf-8").split("## Decision 2026-11-20", 1)[1]
    sources = {name: (API_ROOT / "app" / path).read_text(encoding="utf-8") for name, path in (
        ("legacy_guard", "services/v1_checks/legacy_guard.py"), ("evidence_panel", "services/evidence_panel.py"),
        ("ledger route", "api/routes/ledger.py"), ("qa_engine", "services/qa_engine.py"),
        ("tutor_orchestrator", "services/tutor_orchestrator.py"))}
    texts = {**sources, "ADR-005": adr, "spec 0-17": _spec_head(),
             "deployment.md": _runbook("deployment.md", "## Phase 4"),
             "test strategy": (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8").split("## Phase 4 acceptance map", 1)[1]}
    for name, text in texts.items():
        flat = _flat(text)
        for phrase in ("the same labels", "same V1.7 labels", "never shows those quotations undisclosed", "re-shows conflicting quotations undisclosed",
                       "So no read", "without their labels"):
            assert phrase not in flat, (name, phrase)
    docstrings = {"legacy_guard": inspect.getdoc(legacy_guard), "evidence_panel": inspect.getdoc(evidence_panel),
                  "ledger route": inspect.getdoc(ledger_route), "qa_engine": inspect.getdoc(qa_engine),
                  "tutor_orchestrator": inspect.getdoc(tutor_orchestrator)}
    for name, text in {**docstrings, "ADR-005": adr}.items():
        assert "in force at read time" in _flat(text), name
    for name in ("legacy_guard", "evidence_panel", "ledger route", "tutor_orchestrator"):
        assert "DI-68" in docstrings[name], name
    residuals = next(line for line in adr.splitlines() if line.startswith("- **Residuals.**"))
    assert "DI-68" in residuals and "not the labels shown at delivery" in residuals
    item_3 = _flat(_spec_head().split("3. **Where a stored answer is shown again (AC-4-6).**", 1)[1].split("\n4. ", 1)[0])
    assert "Nothing stores the labels a delivery showed" in item_3 and "(DI-68)" in item_3
    assert "relabels" in _flat(_runbook("deployment.md", "## Phase 4")) and "(DI-68)" in _runbook("deployment.md", "## Phase 4")
    assert _spec_line("| DI-68 |")
    # The statements of what a read shows say whose rule labels it: R-a, the AC-4-6 row, 4.15 item 1, the section 9 read
    # rows, and the test strategy's AC-4-6 row.
    strategy = (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
    reads = {"R-a": _spec_line('- In AC-4-6, "a disclosure block is shown"'), "AC-4-6 row": _spec_line("| AC-4-6 |"),
             "4.15 item 1": _spec_line("**V1.7 (AC-4-6; only with a v1 block):**"),
             "section 9 reads": _spec_line("| `GET /assistant/threads/{thread_id}`, `GET /qa/history` |"),
             "section 9 ledger": _spec_line("| `GET /ledger/responses/{response_id}` |"),
             "test strategy": next(line for line in strategy.splitlines() if line.startswith("| AC-4-6 "))}
    for name, line in reads.items():
        assert "current package" in line or "in force at read time" in line, name


def test_phase4_docs_the_runbook_says_what_a_legacy_record_s_sufficiency_score_holds():
    # retrieve.sufficiency_of records the top result's gate score in a legacy record's retrieval.sufficiency.score (the
    # P1 floor score under p1-floor, production's gate), where the Phase 3 image recorded the top result's ranking score;
    # the entry schema is still ledger-entry-v1. Production writes such a record for every delivery, so the Phase 4
    # runbook's "What ships" and its digest rollback, and spec 8, say so and name the field that tells them apart.
    from app.services.tutor_pipeline.retrieve import sufficiency_of

    settings = Settings(retrieval_gate="p1-floor")
    engine = RetrievalEngine(CourseStore(settings), settings)
    differing = [query for query in list(IN_DOMAIN)[:20] if (response := engine.search(query, top_k=4)).results
                 and sufficiency_of(response, threshold_version="t").score != response.results[0].score]
    assert differing  # the two meanings differ on real p1-floor retrievals
    runbook = _runbook("deployment.md", "## Phase 4")
    ships = _flat(runbook.split("**What ships, and its defaults outside development.**", 1)[1].split("**Before the release.**", 1)[0])
    assert "**Legacy ledger records: what `retrieval.sufficiency.score` holds changes.**" in ships
    for phrase in ("the top result's gate score", "the P1 floor score", "the top result's ranking score", "`versions.config_package_version`",
                   "3.0.0 from the Phase 4 image, 2.0.0 from the Phase 3 image"):
        assert phrase in ships, phrase
    rollback = _flat(runbook.split("**Rollback.**", 1)[1].split("**Rollback order", 1)[0])
    assert "its legacy records go back to the ranking score in `retrieval.sufficiency.score`" in rollback
    assert "`versions.config_package_version`" in rollback
    section_8 = _flat(_spec_head().split("## 8. Database", 1)[1].split("\n## 9. ", 1)[0])
    assert "**What a legacy record's `retrieval.sufficiency.score` holds.**" in section_8
    for phrase in ("the top result's gate score", "the P1 floor score", "`versions.config_package_version`", "`ledger-entry-v1`"):
        assert phrase in section_8, phrase


def test_phase4_docs_the_code_texts_name_the_shipped_package():
    # P2-12-D-03 covers docstrings and comments: the texts that say where the budgets come from, or which package pins
    # the schemas or is checked against the pipeline code, name the shipped package (v4 since Phase 5), as the Phase 3
    # runbook's lines do; contracts.py names the v2 ledger schema that only package v3 pins (spec 7.14).
    import inspect

    from app.services import tutor_followups, tutor_pipeline
    from app.services.tutor_pipeline import package_check

    from app.core.config_package import V4_PACKAGE_PATH, V5_PACKAGE_PATH

    raw = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
    v2 = json.loads(V2_PACKAGE_PATH.read_text(encoding="utf-8"))
    v3 = json.loads(V3_PACKAGE_PATH.read_text(encoding="utf-8"))
    v4 = json.loads(V4_PACKAGE_PATH.read_text(encoding="utf-8"))
    assert raw["tutor_pipeline"]["budgets"] == v2["tutor_pipeline"]["budgets"] == v3["tutor_pipeline"]["budgets"] == v4["tutor_pipeline"]["budgets"]
    v2_schema = "schemas/ledger-entry.v2.schema.json"
    paths = {name: {entry["path"] for entry in package["tutor_pipeline"]["schemas"].values()}
             for name, package in (("v6", raw), ("v5", json.loads(V5_PACKAGE_PATH.read_text(encoding="utf-8"))), ("v4", v4), ("v3", v3), ("v2", v2))}
    assert v2_schema in paths["v3"] and v2_schema not in paths["v2"] and len(paths["v3"]) == len(paths["v2"]) + 1
    assert paths["v3"] < paths["v4"] and len(paths["v4"]) == len(paths["v3"]) + 5 and paths["v4"] == paths["v5"]
    assert paths["v6"] == paths["v5"] | {"schemas/ledger-entry.v4.schema.json"}  # Phase 7: v6 adds the LedgerEntryV4 pin
    texts = {"contracts": inspect.getdoc(contracts), "package_check": inspect.getdoc(package_check),
             "ledger": inspect.getdoc(ledger), "tutor_followups": inspect.getdoc(tutor_followups),
             "tutor_pipeline": inspect.getdoc(tutor_pipeline)}
    flat = {name: _flat(text) for name, text in texts.items()}
    assert "pinned by sha256 in configuration package v2." not in flat["contracts"]
    assert "ledger-entry.v2.schema.json" in flat["contracts"] and f"the shipped configuration package (v{PACKAGE.schema_version} since Phase 9" in flat["contracts"]
    assert not flat["package_check"].startswith("Consistency of configuration package v2 with")
    assert "schema 2 or later" in flat["package_check"] and f"v{PACKAGE.schema_version} since Phase 9, the shipped package" in flat["package_check"]
    assert "come from configuration package v2" not in flat["ledger"] and "come from the shipped configuration package" in flat["ledger"]
    assert "(configuration package v2 tutor_pipeline.budgets" not in flat["tutor_followups"]
    assert f"the shipped configuration package's tutor_pipeline.budgets, v{PACKAGE.schema_version} since Phase 9" in flat["tutor_followups"]
    assert "package_check (configuration package v2)" not in flat["tutor_pipeline"]
    example = _comments((REPO_ROOT / "infra" / "cloudrun" / "api-production.env.example.yaml").read_text(encoding="utf-8"))
    assert "configuration package v2 tutor_pipeline.budgets" not in example
    for budget in ("shadow_ms", "ledger_append_ms"):
        assert (f"the shipped configuration package's tutor_pipeline.budgets.{budget} (v2 with the Phase 3 release, v3 from the Phase 4 release;"
                in example), budget
    assert "`test_phase4_docs_the_code_texts_name_the_shipped_package`" in _spec_head().split("### 7.14", 1)[1].split("### 7.15", 1)[0]


def test_phase4_docs_the_ci_records_name_the_latest_branch_run():
    # PR #36 was squash-merged as 98f7cc4 (tree identical to aa9f1ef); main run 44971066403 passed every job and is the
    # cited run. Spec 17's CI bullet, its DI-58 row and the test strategy's exit gate name the merge and that run, none
    # still says a commit is unpushed or has no run, and the exit stays not passed.
    texts = {"spec 17": _spec_line("- **CI.**"), "DI-58": _spec_line("| DI-58 |"),
             "test strategy": next(line for line in (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
                                   .split("## Phase 4 acceptance map", 1)[1].splitlines() if line.startswith("**Exit gate.**"))}
    for name, text in texts.items():
        assert "44971066403" in text and "`98f7cc4`" in text, name
        for stale in ("not pushed", "have no run", "has no run", "each later commit needs its own"):
            assert stale not in text, (name, stale)
    for name in ("DI-58", "test strategy"):
        assert "The exit is not passed" in texts[name] and "D-06" in texts[name], name
    assert _spec_line("- `phase4_exit_passed` stays `false`").endswith("the exit is not passed (DI-58).")


def _test_function_names() -> set[str]:

    names = set()
    for path in (API_ROOT / "tests").glob("test_*.py"):
        names |= set(re.findall(r"^(?:async )?def (test_\w+)\(", path.read_text(encoding="utf-8"), flags=re.MULTILINE))
    return names


def _unresolved(text: str, functions: set[str]) -> list[str]:
    """The backticked test names, `prefix_*` groups and test files in text that do not exist."""
    missing = [name for name in re.findall(r"`(test_[a-z0-9_]+)`", text) if name not in functions]
    missing += [group for group in re.findall(r"`(test_[a-z0-9_]+?)_?\*`", text) if not any(name.startswith(group) for name in functions)]
    missing += [name for name in re.findall(r"`((?:test_[a-z0-9_]+|v1_fakes)\.py)`", text) if not (API_ROOT / "tests" / name).exists()]
    for path in re.findall(r"`((?:apps/frontend/)?tests/[\w.-]+\.test\.ts)`", text):
        if not (REPO_ROOT / "apps" / "frontend" / path.removeprefix("apps/frontend/")).exists():
            missing.append(path)
    return missing


def test_phase4_docs_the_test_strategy_maps_every_test_module_the_phase_added():
    # Every test module this phase added has a row saying what it proves, and every row names a file that exists.
    strategy = (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
    phase_4 = strategy.split("## Phase 4 acceptance map", 1)[1].split("\n## ", 1)[0]
    table = phase_4.split("### Phase 4 test files", 1)[1].split("**Exit gate.**", 1)[0]
    rows = {match.group(1): match.group(2) for line in table.splitlines() if (match := re.match(r"\| `([^`]+)` \| (.+) \|$", line))}
    tests = API_ROOT / "tests"
    expected = {path.name for pattern in ("test_phase4_*.py", "test_v1_*.py", "v1_fakes.py", "test_quiz_keys.py", "test_python_sources.py")
                for path in tests.glob(pattern)}
    expected |= {f"apps/frontend/tests/{path.name}" for path in (REPO_ROOT / "apps" / "frontend" / "tests").glob("*.test.ts")
                 if "Phase 4" in path.read_text(encoding="utf-8")}
    assert {"test_phase4_acceptance.py", "v1_fakes.py", "test_quiz_keys.py", "apps/frontend/tests/quiz-keys.integration.test.ts"} <= expected
    assert len([name for name in expected if name.startswith("test_v1_")]) == 12
    assert sorted(rows) == sorted(expected), sorted(set(rows) ^ expected)
    for name, text in rows.items():
        assert len(text) > 100, name  # it says what the file proves, not only its name
    assert _unresolved(phase_4, _test_function_names()) == []


def test_phase4_docs_the_spec_ends_in_one_review_history_table():
    # P2-12-D-03: sections 0-17 state the current code and carry no review-round narrative; section 18, the last, is one
    # history table whose every finding is one line naming the tests that fail if its defect comes back.
    head, history = SPEC.split("\n## 18. Review history\n", 1)
    assert re.findall(r"^## (\d+)\. ", head, flags=re.MULTILINE) == [str(number) for number in range(18)]
    assert "\n## " not in history and "\n### " not in history
    intro = history.split("\n| Round |", 1)[0]
    assert "may describe behaviour that a later round superseded" in intro and "sections 0-17 are authoritative" in intro
    assert history.count("\n| Round |") == 1
    rows = [line for line in history.splitlines() if line.startswith("| ") and not line.startswith(("| Round |", "|---"))]
    assert [row.split(" | ", 1)[0] for row in rows[:5]] == ["| Spec review 1 (pre-code)", "| Build", "| Review 1", "| Housekeeping H1-H3", "| Review 2"]
    for row in rows:
        round_name, commit, findings = row.split(" | ", 2)
        assert round_name == "| Spec review 1 (pre-code)" or re.search(r"`[0-9a-f]{7,40}`", commit), round_name
        for finding in findings.rstrip(" |").split("<br>"):
            assert re.search(r"`test_[a-z0-9_]+\*?`|\.test\.ts`", finding), (round_name, finding[:60])
    assert _unresolved(history, _test_function_names()) == []
    from test_phase3_docs import NARRATIVE

    assert NARRATIVE.findall(head) == []
    assert re.findall(r"\b[Rr]eview \d+\b|\bround \d+\b|[Ss]ection 18 records", head) == []


def _code_fields(source: str, name: str) -> list[str]:
    node = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == name)
    return [ast.unparse(item) for item in node.body if isinstance(item, (ast.AnnAssign, ast.Assign))]


def test_phase4_spec_section_3_lists_the_code_s_fields():
    section = SPEC.split("## 3. Data shapes", 1)[1].split("## 4. V1 specification", 1)[0]
    sources = {
        "contracts": (API_ROOT / "app" / "services" / "tutor_pipeline" / "contracts.py").read_text(encoding="utf-8"),
        "aggregate": (API_ROOT / "app" / "services" / "v1_checks" / "aggregate.py").read_text(encoding="utf-8"),
        "schemas": (API_ROOT / "app" / "schemas.py").read_text(encoding="utf-8"),
    }
    classes = {name: {node.name for node in ast.parse(source).body if isinstance(node, ast.ClassDef)} for name, source in sources.items()}
    checked = 0
    for block in re.findall(r"```python\n(.*?)```", section, flags=re.DOTALL):
        for node in ast.parse(block).body:
            if not isinstance(node, ast.ClassDef):
                continue
            owner = next(name for name in ("contracts", "aggregate", "schemas") if node.name in classes[name])
            listed = [ast.unparse(item) for item in node.body if isinstance(item, (ast.AnnAssign, ast.Assign))]
            code = _code_fields(sources[owner], node.name)
            header = block.splitlines()[node.lineno - 1]
            if "additions only" in header:
                assert listed and set(listed) <= set(code), node.name
            else:
                assert listed == code, node.name
            checked += 1
    assert checked >= 15
