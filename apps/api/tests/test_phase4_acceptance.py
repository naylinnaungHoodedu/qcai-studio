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
from app.api.routes import qa as qa_route
from app.core.config import Settings
from app.core.config_package import DEFAULT_PACKAGE_PATH, V2_PACKAGE_PATH, canonical_sha256, get_config_package, load_config_package
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


def test_ac_4_2_the_adversarial_set_fails_or_abstains_in_both_checker_configurations(fixture_report):
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
    # Plan M: what only V1.3 could catch is the residual; under production V1.3 withholds it.
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
    run(dev_pipeline(Settings(v1_pipeline="off"), session_factory=factory), MULTI_CLAIM, record=True)
    shadow = run(dev_pipeline(Settings(v1_pipeline="shadow"), session_factory=factory), MULTI_CLAIM, record=True, legacy_decision="answer")
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
    assert body["config_package_version"] == "3.0.0" and body["config_package_sha256"] == PACKAGE.sha256
    assert (body["v1_pipeline"], body["v1_pipeline_setting"]) == ("enforce", "enforce")
    v1 = body["v1"]
    assert v1 == {"version": V1.version, "rules_hash": V1.rules_hash, "checker": {"hosting": "none", "model_id": "none"},
                  "misconception_library": {"version": "v0", "entries": 0, "sha256": V1.library_sha256}, "fixtures_set_sha256": V1.fixtures_set_sha256,
                  "regeneration": {"generation": 2, "render": 2}, "readability_band": [-4.0, 64.0], "x4_margin": {"bm25f-v1": 2.4, "p1-floor": 0.0},
                  "stop": {"answer_rate_floor": {"bm25f-v1": "166/174", "p1-floor": "146/174"}, "v1_p95_latency_ms": 250},
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
    assert rows and rows[0].entry_schema == "ledger-entry-v2"
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
    from test_phase3_hardening import _override_details

    assert _override_details(monkeypatch, allowed) == {"v1_pipeline_enforce": True}
    env = {"DATABASE_URL": fresh_database_url, "PYTHONUNBUFFERED": "1"}
    off = _startup({**env, "ENVIRONMENT": "production", "V1_PIPELINE": "off"})
    assert off.returncode != 0 and "V1_PIPELINE=off" in off.stderr
    governed = _startup({**env, "ENVIRONMENT": "development", "ENFORCE_CORPUS_GOVERNANCE": "true", "CONFIG_PACKAGE_PATH": str(V2_PACKAGE_PATH),
                         "CORPUS_MANIFEST_PATH": str(REPO_MANIFEST)})
    assert governed.returncode != 0 and "no v1 block" in governed.stderr
    probe = create_engine(fresh_database_url)
    try:
        assert set(sa_inspect(probe).get_table_names()) == set()
    finally:
        probe.dispose()


def _startup(extra: dict[str, str]) -> subprocess.CompletedProcess:
    import os

    env = {key: value for key, value in os.environ.items() if key not in {"V1_PIPELINE", "CONFIG_PACKAGE_PATH", "ENFORCE_CORPUS_GOVERNANCE"}}
    env.update(extra)
    return subprocess.run([sys.executable, "-c", "from app.main import _initialize_database; _initialize_database()"], cwd=API_ROOT, env=env,
                          capture_output=True, text=True, timeout=240)


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
