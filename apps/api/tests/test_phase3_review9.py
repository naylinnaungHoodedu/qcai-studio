"""Phase 3, ninth review round (2026-11-19; Phase 3 spec 18.12). Each test fails if its defect comes back.

J1  a duplicate claim (its sentence already bound on every span it cites) counts as bound in the plan L ratio, as a
    merged claim does, so two claim plans that lock one claim set give one ratio whatever their order.
J2  the invariant 1 fixture compares the ClaimPlans and the whole shadow record (bundle, threshold, sufficiency,
    abstention reason, counts), so a learner-dependent plan or threshold fails it.
J3  a render attempt that raises logs tutor.two_pass.render_failed, and a run whose every attempt raised abstains
    with render_failed, never subset_check_failed.
J4  spec 18.11 I2 says what the pipeline records for a refused fault, and every exact fault test asserts what was
    placed.
J5  the coverage check counts a turn whose append may still be running as pending, not as a lost record.
J6  the attempt horizon is derived from the code's own terms (the append queue included) and the runbook reads it
    by CPU allocation.
J7  spec 4.11, section 9's connection note and 13.1 items 28 and 39 say what the code and the tests do.
J8  spec sections 14 and 15 mark the CI job, budget setting and Alembic step that later rounds changed.
The evidence package lives beside the repository, not in it (CI has none): its checks run where it is present.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
import inspect
import json
import logging
import math
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.core.db import Base
from app.core.schema_upgrades import run_schema_upgrades
from app.db_models import TutorThread, TutorTurn
from app.services import ledger
from app.services.ledger import LegacyDelivery, append_ledger_entry, ledger_coverage, record_legacy_delivery
from app.services.retrieval_engine import RetrievalEngine
from app.services.store import get_course_store
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline import pipeline as pipeline_module
from app.services.tutor_pipeline.contracts import LedgerEntry, PresentationPlan, ProposedClaim, bound_claim_ratio_terms
from app.services.tutor_pipeline.evidential import ExtractiveD19Generator
from app.services.tutor_pipeline.metrics import TwoPassMetrics
from app.services.tutor_pipeline.pipeline import PipelineInput, TwoPassPipeline, render_checked
from app.services.tutor_pipeline.render import TemplateRenderer
from app.services.tutor_pipeline.resolve import LearnerTurn, resolve_turns
from tutor_fakes import FaultyRenderer, ScriptedGenerator, SpyGenerator, make_entry

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
BEP_ROOT = REPO_ROOT.parent / "BEP-2-12"
SPEC = (REPO_ROOT / "docs" / "architecture" / "phase3-implementation-spec.md").read_text(encoding="utf-8")
RUNBOOK = (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8")
OBSERVABILITY = (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8")
README = (REPO_ROOT / "docs" / "evaluation" / "phase3" / "README.md").read_text(encoding="utf-8")
ADR_001 = (REPO_ROOT / "docs" / "adr" / "ADR-001-grounding-separation.md").read_text(encoding="utf-8")
ADR_005 = (REPO_ROOT / "docs" / "adr" / "ADR-005-abstention-gate.md").read_text(encoding="utf-8")
STRATEGY = (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
PACKAGE = get_config_package(Settings())
PARAMS = PACKAGE.tutor_pipeline
# The regression query (apps/api/tests/data/phase3_replay_regressions.json) whose answer locks a sentence that two
# overlapping spans both hold: one claim citing two spans (spec 18.4).
TWO_SPAN = "How should the trained model be evaluated on a physical QPU against classical baselines?"
MULTI_CLAIM = "Explain why quantum logistics needs both problem reduction before execution and routing control during compilation."
OUTSIDE_SPAN = "span-" + "9" * 64


def _section(title: str, end: str) -> str:
    return SPEC.split(title, 1)[1].split(end, 1)[0]


def _run(pipeline: TwoPassPipeline, query: str, plan_id: str = "concise"):
    resolved = resolve_turns([], LearnerTurn(f"message-{uuid4()}", query), package=pipeline.package)
    return pipeline.run(PipelineInput(resolved=resolved, lesson_slug=None, presentation=PresentationPlan(plan_id=plan_id, source="request"),
                                      response_id=f"shadow-{uuid4()}", delivery="shadow", shadowed_response_id=f"turn-{uuid4()}"), record=False)


def _events(caplog, name: str) -> list[dict]:
    return [dict(record.json_fields) for record in caplog.records if getattr(record, "json_fields", {}).get("event") == name]


def _bep(relative: str) -> str | None:
    path = BEP_ROOT / relative
    return path.read_text(encoding="utf-8") if path.exists() else None


def _load_replay():
    import importlib.util

    spec = importlib.util.spec_from_file_location("phase3_review9_replay", REPO_ROOT / "scripts" / "replay_tutor_plans.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ============================================================================================================ J1


def test_j1_two_claim_orders_that_lock_one_claim_set_give_one_ratio_and_no_stop():
    settings = Settings()
    engine = RetrievalEngine(get_course_store(), settings)
    baseline = _run(TwoPassPipeline(engine, settings), TWO_SPAN)
    multi = [claim for claim in baseline.locked.claims if len(claim.span_ids) >= 2]
    assert multi, "the regression query no longer locks a claim on two spans"
    claim = multi[0]
    first, second = claim.span_ids[:2]
    results = {}
    # The reviewer's probe: the same sentence on (A,) then (A, B) merges; on (A, B) then (A,) it is a duplicate.
    for reason, script in (("merged", [(claim.text, (first,)), (claim.text, (first, second))]),
                           ("duplicate", [(claim.text, (first, second)), (claim.text, (first,))])):
        result = _run(TwoPassPipeline(engine, settings, generator=ScriptedGenerator([script])), TWO_SPAN)
        assert result.decision == "answer" and dict(result.entry.counts.dropped) == {reason: 1}, (reason, result.entry.counts)
        results[reason] = result
    assert results["merged"].locked.claim_set_hash == results["duplicate"].locked.claim_set_hash  # one locked claim set
    assert {bound_claim_ratio_terms(result.entry.counts) for result in results.values()} == {(2, 2)}  # one ratio, 1.0
    metrics = TwoPassMetrics()
    for result in results.values():
        metrics.completed(decision=result.decision, reason=result.abstention_reason, counts=result.entry.counts, attempts=result.render_attempts)
    snapshot = metrics.snapshot(PARAMS.phase2_bound_claim_ratio)
    assert (snapshot["bound_claim_ratio"], snapshot["bound_claim_ratio_stop"]) == (1.0, False)
    assert contracts.DUPLICATE not in contracts.BINDING_FAILURES and contracts.DUPLICATE in contracts.DROP_REASONS
    # A real binding failure still lowers the ratio: the unbound fourth claim of 18.4's test generator.
    failing = _run(TwoPassPipeline(engine, settings, generator=ScriptedGenerator([[(claim.text, (first,)), ("No span says this.", ())]])), TWO_SPAN)
    assert bound_claim_ratio_terms(failing.entry.counts) == (2, 1)


class _Repeating:
    """Proposes every extractive claim twice on the same spans: each repeat is a duplicate."""

    def __init__(self, inner) -> None:
        self.inner, self.ref = inner, inner.ref

    def propose(self, envelope):
        plan = self.inner.propose(envelope)
        return plan.model_copy(update={"claims": tuple(claim for claim in plan.claims for _ in range(2))})


def test_j1_a_generator_that_repeats_its_claims_is_not_a_replay_stop():
    module = _load_replay()
    report = module.compute(subset=12, regressions=None, configurations=(("all_public_approved", "bm25f-v1"),),
                            generator_factory=lambda package: _Repeating(ExtractiveD19Generator(package)), commit_source=lambda: "test")
    two_pass = report["configurations"][0]["two_pass"]
    assert two_pass["proposed_claims"] > 0 and two_pass["proposed_claims"] % 2 == 0
    # Until 18.12 J1 every repeat was a binding failure: ratio 0.5, the plan L stop and exit 3.
    assert (two_pass["bound_claim_ratio"], report["result"], module.exit_code(report)) == (1.0, "pass", 0)


def test_j1_the_records_count_a_duplicate_as_bound():
    counts = _section("class PipelineCounts(Contract):", "class LedgerEntry(Contract):")
    assert "not_verbatim (binding failures)" in counts and "merged|duplicate (18.12 J1)|budget_exceeded (not failures)" in counts
    row = next(line for line in _section("### 4.6 Bind", "### 4.7").splitlines() if line.startswith("| the same sentence was already bound on every span"))
    assert "`duplicate`" in row and "18.12 J1" in row
    metrics = next(line for line in _section("### 11.3 Metrics", "### 11.4").splitlines() if line.startswith("- `bound_claim_ratio = "))
    assert "`duplicate` claims are in both terms" in metrics
    assert "and so does a duplicate" in README and "a merged or duplicate claim in both" in OBSERVABILITY
    assert "which read a merge, a duplicate or a budget overrun as a binding failure" in OBSERVABILITY
    source = (API_ROOT / "app" / "services" / "tutor_pipeline" / "contracts.py").read_text(encoding="utf-8")
    terms = source.split("def bound_claim_ratio_terms", 1)[1].split("\nclass ", 1)[0]
    assert "dropped.get(DUPLICATE, 0)" in terms and "dropped.get(MERGED, 0)" in terms


# ============================================================================================================ J2


_LEAK = {"learner": None}


class _LeakySpy(SpyGenerator):
    """A generator that reads state outside its envelope (a module global) and, for one learner, adds a claim that
    does not bind: the ClaimPlan and the counts differ, while the locked set, its hash and the decision do not."""

    def propose(self, envelope):
        plan = self.inner.propose(envelope)
        if _LEAK["learner"] == 0.5 and envelope.evidence:
            plan = plan.model_copy(update={"claims": (*plan.claims, ProposedClaim(text="No span holds this sentence verbatim.",
                                                                                  span_ids=(envelope.evidence[0].span_id,)))})
        self.envelopes.append(envelope.model_dump(mode="json"))
        self.plans.append(plan.model_dump(mode="json"))
        return plan


def _old_projection(item: dict) -> dict:
    """What the invariant 1 test compared until 18.12 J2."""
    record = item["record"]
    return {"request": item["retrieve"]["request"], "envelopes": item["envelopes"],
            "bundle": [(span["span_id"], span["score"]) for span in record["retrieval"]["evidence"]],
            "claim_set_hash": record["claim_set_hash"], "decision": record["decision"]}


def _leaky_assistant_class():
    from test_phase3_acceptance import _SpyAssistant

    class _LeakyAssistant(_SpyAssistant):
        spy = None

        @property
        def pipeline(self):
            if getattr(self, "_spy_pipeline", None) is None:
                type(self).spy = _LeakySpy(ExtractiveD19Generator(get_config_package(self.settings)))
                self._spy_pipeline = TwoPassPipeline(self.retrieval_engine, self.settings, generator=type(self).spy)
            return self._spy_pipeline

    return _LeakyAssistant


def test_j2_a_learner_dependent_claim_plan_fails_the_invariant_1_fixture_though_the_old_comparison_passed(monkeypatch):
    from test_phase3_acceptance import observe_three_learners

    monkeypatch.setitem(_LEAK, "learner", None)
    observed, _, _ = observe_three_learners(monkeypatch, assistant_class=_leaky_assistant_class(), prefix="j2-plan",
                                            on_learner=lambda mastery: _LEAK.__setitem__("learner", mastery))
    # The five fields the test compared until 18.12 J2 are equal: the extra claim never bound.
    assert all([_old_projection(item) for item in learner] == [_old_projection(item) for item in observed[0]] for learner in observed)
    # The whole fixture is not: the 0.5 learner's ClaimPlans and counts differ, as plan 7.8 invariant 1 forbids.
    assert observed[1] != observed[0] and observed[2] == observed[0]
    differing = [index for index, (item, other) in enumerate(zip(observed[1], observed[0])) if item != other]
    assert differing and all(observed[1][index]["plans"] != observed[0][index]["plans"] for index in differing)
    assert all(observed[1][index]["record"]["counts"]["dropped"].get("not_verbatim") == 1 for index in differing)


def test_j2_a_learner_dependent_threshold_fails_the_invariant_1_fixture(monkeypatch):
    from test_phase3_acceptance import _SpyAssistant, observe_three_learners

    learner = {"mastery": None}
    real_retrieve = pipeline_module.retrieve

    def retrieve(engine, request, **kwargs):
        bundle = real_retrieve(engine, request, **kwargs)
        if learner["mastery"] != 0.9:
            return bundle
        # A learner-dependent threshold version that leaves the same results above it (the gap the finding named).
        sufficiency = bundle.sufficiency.model_copy(update={"threshold_version": bundle.sufficiency.threshold_version + "-learner"})
        return bundle.model_copy(update={"sufficiency": sufficiency})

    monkeypatch.setattr(pipeline_module, "retrieve", retrieve)
    observed, _, _ = observe_three_learners(monkeypatch, assistant_class=_SpyAssistant, prefix="j2-threshold",
                                            on_learner=lambda mastery: learner.__setitem__("mastery", mastery))
    assert all([_old_projection(item) for item in each] == [_old_projection(item) for item in observed[0]] for each in observed)
    assert observed[1] == observed[0] and observed[2] != observed[0]
    assert all(item["record"]["retrieval"]["threshold_version"].endswith("-learner") for item in observed[2])


def test_j2_the_records_name_what_the_invariant_1_fixture_compares():
    acceptance = (API_ROOT / "tests" / "test_phase3_acceptance.py").read_text(encoding="utf-8")
    helper = acceptance.split("def observe_three_learners(", 1)[1].split("\ndef ", 1)[0]
    for needed in ('"retrieve":', '"top_k"', '"envelopes":', '"plans":', '"record": learner_independent(entry)'):
        assert needed in helper, needed
    test = acceptance.split("def test_ac_3_1_what_the_evidential_pass_receives_holds_zero_learner_state_under_three_learner_contexts", 1)[1].split("\ndef ", 1)[0]
    assert "observe_three_learners(monkeypatch)" in test and "all(learner == observed[0] for learner in observed)" in test
    item_3 = next(line for line in SPEC.splitlines() if line.startswith("3. `test_ac_3_1_what_the_evidential_pass_receives"))
    for needed in ("`ClaimPlan`s", "threshold version", "abstention reason", "`top_k`", "Corrected in 18.12 J2"):
        assert needed in item_3, needed
    revision = ADR_001.split("## Revision 2026-11-19", 1)[1]
    sentence = next(line for line in revision.splitlines() if "The invariant 1 test replays" in line)
    assert "ClaimPlans" in sentence and "threshold version" in sentence and "Corrected in Phase 3 spec 18.12 J2" in sentence
    ac_3_1 = next(line for line in STRATEGY.splitlines() if line.startswith("| AC-3-1"))
    assert "ClaimPlans" in ac_3_1 and "18.12 J2" in ac_3_1
    if (record := _bep("phase03/PHASE_RECORD.md")) is not None:
        row = next(line for line in record.splitlines() if line.startswith("| AC-3-1 "))
        assert "ClaimPlans" in row and "18.12 J2" in row and "identical requests, envelopes, bundles, hashes and decisions" not in row


# ============================================================================================================ J3


class _RaisingRenderer:
    """Raises on the attempts marked True; renders normally (through the template renderer) otherwise."""

    def __init__(self, raises, *, error: BaseException | None = None) -> None:
        self.inner = TemplateRenderer()
        self.renderer_id = self.inner.renderer_id
        self.raises = list(raises)
        self.error = error or KeyError("template bug (test)")

    def render(self, locked, plan, *, attempt: int):
        if self.raises[attempt - 1]:
            raise self.error
        return self.inner.render(locked, plan, attempt=attempt)


def test_j3_a_renderer_that_raises_on_every_attempt_abstains_as_render_failed_and_logs_each_attempt(caplog):
    settings = Settings()
    engine = RetrievalEngine(get_course_store(), settings)
    with caplog.at_level(logging.ERROR, logger="qcai.tutor"):
        result = _run(TwoPassPipeline(engine, settings, renderer=_RaisingRenderer([True, True, True])), MULTI_CLAIM)
    assert (result.decision, result.abstention_reason, result.render_attempts) == ("abstain", contracts.RENDER_FAILED, 3)
    assert result.entry.abstention_reason == "render_failed" and result.entry.presentation.subset_check == "failed"
    LedgerEntry.model_validate(result.entry.model_dump(mode="json"))  # a valid record
    lines = _events(caplog, "tutor.two_pass.render_failed")
    assert [(line["step"], line["render_attempt"], line["error"]) for line in lines] == [("render", 1, "KeyError"), ("render", 2, "KeyError"),
                                                                                         ("render", 3, "KeyError")]
    assert "render_failed" in contracts.ABSTENTION_REASONS and "subset_check_failed" in contracts.ABSTENTION_REASONS


def test_j3_one_fault_then_a_clean_rendering_answers_and_a_checked_refusal_keeps_subset_check_failed(caplog):
    settings = Settings()
    engine = RetrievalEngine(get_course_store(), settings)
    with caplog.at_level(logging.ERROR, logger="qcai.tutor"):
        recovered = _run(TwoPassPipeline(engine, settings, renderer=_RaisingRenderer([True, False, False])), MULTI_CLAIM)
    assert (recovered.decision, recovered.render_attempts) == ("answer", 2)
    assert len(_events(caplog, "tutor.two_pass.render_failed")) == 1
    caplog.clear()
    # One attempt raised, the other two rendered an invented claim that the subset check refused: the run abstains as a
    # subset-check failure, because at least one rendering was checked and refused.
    baseline = _run(TwoPassPipeline(engine, settings), MULTI_CLAIM)
    faulty = FaultyRenderer(_RaisingRenderer([True, False, False]), [False, True, True], random.Random(2), modes=("invented",),
                            outside_sentence="x", outside_span_id=OUTSIDE_SPAN, exact=True)
    with caplog.at_level(logging.ERROR, logger="qcai.tutor"):
        rendered, attempts, reason = render_checked(faulty, baseline.locked, PresentationPlan(plan_id="concise", source="request"),
                                                    max_regenerations=PARAMS.max_regenerations)
    assert (rendered, attempts, reason) == (None, 3, "subset_check_failed")
    assert faulty.placed == ["invented", "invented"] and len(_events(caplog, "tutor.two_pass.render_failed")) == 1


def test_j3_a_subset_check_that_raises_is_a_render_fault_and_a_tampered_set_still_propagates(monkeypatch, caplog):
    settings = Settings()
    engine = RetrievalEngine(get_course_store(), settings)
    baseline = _run(TwoPassPipeline(engine, settings), MULTI_CLAIM)
    monkeypatch.setattr(pipeline_module, "check_subset", lambda rendered, locked: (_ for _ in ()).throw(RuntimeError("checker bug (test)")))
    with caplog.at_level(logging.ERROR, logger="qcai.tutor"):
        rendered, attempts, reason = render_checked(TemplateRenderer(), baseline.locked, PresentationPlan(plan_id="concise", source="request"),
                                                    max_regenerations=PARAMS.max_regenerations)
    assert (rendered, attempts, reason) == (None, 3, "render_failed")
    assert {(line["step"], line["error"]) for line in _events(caplog, "tutor.two_pass.render_failed")} == {("subset_check", "RuntimeError")}
    monkeypatch.undo()
    with pytest.raises(contracts.LockedClaimSetTampered):
        render_checked(_RaisingRenderer([True, True, True], error=contracts.LockedClaimSetTampered("tampered (test)")), baseline.locked,
                       PresentationPlan(plan_id="concise", source="request"), max_regenerations=PARAMS.max_regenerations)


def test_j3_a_shadow_run_with_a_crashing_renderer_completes_with_its_reason_and_no_shadow_failure(caplog):
    from test_phase3_acceptance import _job, _thread_with_message

    from app.services.tutor_pipeline.shadow import run_shadow

    settings = Settings()
    thread_id, message_id = _thread_with_message(f"j3-{uuid4().hex[:8]}", MULTI_CLAIM)
    with caplog.at_level(logging.INFO, logger="qcai.tutor"):
        run_shadow(_job(thread_id, message_id), settings=settings, pipeline_factory=lambda: TwoPassPipeline(
            RetrievalEngine(get_course_store(), settings), settings, renderer=_RaisingRenderer([True, True, True])))
    (line,) = _events(caplog, "tutor.two_pass.shadow")
    assert (line["decision"], line["reason"]) == ("abstain", "render_failed")
    assert _events(caplog, "tutor.two_pass.shadow_failed") == [] and len(_events(caplog, "tutor.two_pass.render_failed")) == 3


def test_j3_the_records_name_the_render_fault():
    step_7 = next(line for line in _section("### 4.10 Pipeline", "### 4.11").splitlines() if line.startswith("7. **Render loop.**"))
    assert "`tutor.two_pass.render_failed`" in step_7 and "`render_failed`" in step_7 and "18.12 J3" in step_7
    revision = ADR_005.split("## Revision 2026-11-19 (Phase 3)", 1)[1]
    assert "`render_failed`" in revision and "18.12 J3" in revision
    assert any(line.startswith("| `tutor.two_pass.render_failed` |") for line in OBSERVABILITY.splitlines())
    alert = next(line for line in OBSERVABILITY.splitlines() if line.startswith("| Shadow render faults |"))
    assert 'jsonPayload.event="tutor.two_pass.render_failed"' in alert and "Alert on any match" in alert
    reasons = next(line for line in OBSERVABILITY.splitlines() if line.startswith("| Shadow abstention by reason |"))
    assert "`render_failed`" in reasons
    source = (API_ROOT / "app" / "services" / "tutor_pipeline" / "pipeline.py").read_text(encoding="utf-8")
    function = source.split("def render_checked(", 1)[1].split("\nclass ", 1)[0]
    assert "except Exception:  # noqa: BLE001 - a renderer fault is a failed attempt" not in function
    assert '"tutor.two_pass.render_failed"' in function and "contracts.RENDER_FAILED" in function


# ============================================================================================================ J4


def test_j4_spec_18_11_says_what_the_pipeline_records_for_a_refused_fault():
    i2 = _section("**I2. Four fault-injection tests", "**I3.")
    bullet = next(line for line in i2.splitlines() if line.startswith("- New tests: under each of the three plans"))
    assert "Corrected in 18.12 J4" in bullet and "`FaultyRenderer.placed`" in bullet and "`render_failed`" in bullet
    for line in SPEC.split("### 18.12 Ninth review round", 1)[0].splitlines():  # 18.12 J4 itself quotes the old sentence
        if "the pipeline records `not_placed`" in line:
            assert "Corrected in 18.12 J4" in line, line[:160]
    assert "not_placed" not in "".join(path.read_text(encoding="utf-8") for path in (API_ROOT / "app").rglob("*.py"))


def test_j4_every_exact_fault_test_asserts_what_was_placed():
    """A refused exact fault never reaches the subset check, so the abstention alone cannot show that a fault was
    placed: every test that builds an exact FaultyRenderer must also assert its `placed` list."""
    checked = 0
    for path in sorted((API_ROOT / "tests").glob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
                continue
            body = ast.get_source_segment(source, node) or ""
            exact = [call for call in ast.walk(node) if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "FaultyRenderer"
                     and any(keyword.arg == "exact" and getattr(keyword.value, "value", False) is True for keyword in call.keywords)]
            if exact:
                checked += 1
                assert ".placed" in body, (path.name, node.name)
    assert checked >= 4, checked  # acceptance AC-3-3, review4 E1, review8 I2, J3 here


# ============================================================================================================ J5


def _sessions(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False), engine


def _legacy(response_id: str) -> LegacyDelivery:
    return LegacyDelivery(
        response_id=response_id, decision="abstain", reason="no_approved_span", claims=(), quoted=(), retrieved=None,
        answer_sha256="c" * 64, retrieval_mode="lexical-extractive-lexically-screened", provider="none", model="extractive-lexically-screened",
        corpus_version="corpus-test", index_version="index-test", gate="p1-floor", threshold_version="score-floor-p1-v1", floor=6.0, margin=0.0,
        policy_version="cs595-v1",
    )


def _add_turn(db, thread: TutorThread, *, age: timedelta = timedelta(0), expected: bool | None = True) -> str:
    turn_id = f"turn-{uuid4()}"
    db.add(TutorTurn(id=turn_id, thread_id=thread.id, user_id=thread.user_id, resolved_query="q", retrieval_mode="lexical", provider="none",
                     model="m", decision="abstain", decision_reason="no_approved_span", citations=[], claims=[], corpus_version="c",
                     policy_version="p", created_at=datetime.now(UTC) - age, ledger_record_expected=expected))
    return turn_id


def _worker(database_url: str, *args: str) -> tuple[int, dict | None]:
    env = {**os.environ, "DATABASE_URL": database_url, "PYTHONUNBUFFERED": "1"}
    completed = subprocess.run([sys.executable, "-m", "app.workers.response_ledger", *args], cwd=API_ROOT, env=env, capture_output=True,
                               text=True, timeout=120)
    lines = [line for line in completed.stderr.splitlines() if '"job": "response_ledger"' in line]
    return completed.returncode, (json.loads(lines[-1][lines[-1].index("{"):]) if lines else None)


def test_j5_a_turn_whose_append_is_still_running_is_pending_not_unrecorded(fresh_database_url, monkeypatch):
    factory, engine = _sessions(fresh_database_url)
    released = threading.Event()
    real_append = ledger.append_ledger_entry

    def held_open(entry, **kwargs):
        assert released.wait(30)  # the append is in flight (as a slow pool checkout would hold it)
        return real_append(entry, **{**kwargs, "budget_ms": 5000})

    monkeypatch.setattr(ledger, "append_ledger_entry", held_open)
    try:
        since = datetime.now(UTC) - timedelta(minutes=1)
        with factory() as db:
            thread = TutorThread(id=f"thread-{uuid4()}", user_id=f"review9-{uuid4().hex[:8]}", title="t")
            db.add(thread)
            db.flush()
            turn_id = _add_turn(db, thread)
            db.commit()  # the turn commits first; its append runs after the commit
        # The request stops waiting (deferred); the append is still running when the coverage check reads the turn.
        assert record_legacy_delivery(_legacy(turn_id), settings=Settings(tutor_ledger_append_budget_ms=100), session_factory=factory) is None
        with factory() as db:
            during = ledger_coverage(db, since)
        assert (during["turns_since"], during["unrecorded"], during["pending"], during["horizon_s"]) == (1, 0, 1, 360)
        code, report = _worker(fresh_database_url, "--coverage-since", since.isoformat())
        assert code == 0 and (report["coverage"]["unrecorded"], report["coverage"]["pending"]) == (0, 1)
        released.set()
        assert ledger.LEGACY_APPENDS.drain(30)
        with factory() as db:
            after = ledger_coverage(db, since)
            # Recorded: neither pending nor unrecorded, whatever the horizon.
            assert (after["unrecorded"], after["pending"]) == (0, 0) and ledger.verify_response_ledger(db).count == 1
            assert (ledger_coverage(db, since, horizon_s=0)["unrecorded"], ledger_coverage(db, since, horizon_s=0)["pending"]) == (0, 0)
    finally:
        released.set()
        engine.dispose()


def test_j5_a_turn_older_than_the_horizon_without_its_record_is_still_a_lost_record(fresh_database_url, tmp_path):
    factory, engine = _sessions(fresh_database_url)
    try:
        since = datetime.now(UTC) - timedelta(hours=1)
        with factory() as db:
            thread = TutorThread(id=f"thread-{uuid4()}", user_id=f"review9-{uuid4().hex[:8]}", title="t")
            db.add(thread)
            db.flush()
            old = _add_turn(db, thread, age=timedelta(minutes=10))
            new = _add_turn(db, thread)
            db.commit()
        with factory() as db:
            coverage = ledger_coverage(db, since)
            assert (coverage["unrecorded"], coverage["pending"]) == (1, 1)  # the old turn is lost, the new one may be running
            settled = datetime.fromisoformat(coverage["settled_before"])
            assert abs((datetime.now(UTC) - settled).total_seconds() - 360) < 30
            # Later, past the horizon, the new turn is counted too; horizon 0 counts every turn at once.
            assert ledger_coverage(db, since, now=datetime.now(UTC) + timedelta(seconds=361))["unrecorded"] == 2
            assert (ledger_coverage(db, since, horizon_s=0)["unrecorded"], ledger_coverage(db, since, horizon_s=0)["pending"]) == (2, 0)
            with pytest.raises(ValueError):
                ledger_coverage(db, since, horizon_s=-1)
        code, report = _worker(fresh_database_url, "--coverage-since", since.isoformat(), "--coverage-horizon-s", "0")
        assert code == 0 and (report["coverage"]["unrecorded"], report["coverage"]["pending"], report["coverage"]["horizon_s"]) == (2, 0, 0)
        code, report = _worker(fresh_database_url, "--coverage-since", since.isoformat(), "--coverage-horizon-s", "-5")
        assert code == 2 and report["status"] == "usage"
        # The development script shares ledger_coverage and takes the same option.
        import importlib.util

        spec = importlib.util.spec_from_file_location("phase3_review9_verify", REPO_ROOT / "scripts" / "verify_ledger.py")
        verify = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verify)
        report_path = tmp_path / "coverage.json"
        assert verify.main(["--database-url", fresh_database_url, "--report", str(report_path), "--coverage-since", since.isoformat()]) == 0
        block = json.loads(report_path.read_text(encoding="utf-8"))["coverage"]
        assert (block["unrecorded"], block["pending"], block["horizon_s"]) == (1, 1, 360)
        assert verify.main(["--database-url", fresh_database_url, "--coverage-since", since.isoformat(), "--coverage-horizon-s", "-1"]) == 2
        assert {old, new}  # both turns exist; neither has a record
    finally:
        engine.dispose()


def test_j5_the_runbook_and_the_spec_name_the_pending_count():
    bullet = next(line for line in RUNBOOK.splitlines() if line.startswith("- `python -m app.workers.response_ledger --coverage-since <time>`"))
    for needed in ("`pending`", "`horizon_s`", "360 s", "`--coverage-horizon-s 0`", "18.12 J5"):
        assert needed in bullet, needed
    row = next(line for line in OBSERVABILITY.splitlines() if line.startswith("| Ledger coverage (100%) |"))
    assert "`pending`" in row and "18.12 J5" in row
    for title, end in (("### 7.15 NEW", "### 7.16"), ("### 7.16 NEW", "### 7.17")):
        section = _section(title, end)
        assert "`--coverage-horizon-s" in section and "18.12 J5" in section, title
    script = _section("### 7.16 NEW", "### 7.17")
    for key in ("`pending`", "`horizon_s`", "`settled_before`"):
        assert key in script, key


# ============================================================================================================ J6


def test_j6_the_attempt_horizon_is_derived_from_the_code_s_own_terms():
    per_append = ledger.POOL_CHECKOUT_TIMEOUT_S + ledger.CONNECT_TIMEOUT_S + (ledger.ATTEMPT_STATEMENTS + 1) * PARAMS.ledger_append_budget_ms / 1000
    rounds = math.ceil(PARAMS.ledger_append_max_in_flight / PARAMS.ledger_append_workers)
    assert (per_append, rounds) == (70.5, 4)
    assert ledger.attempt_horizon_s(PARAMS, PARAMS.ledger_append_budget_ms) == 60 * math.ceil((rounds * per_append + ledger.HORIZON_MARGIN_S) / 60) == 360
    assert ledger.coverage_horizon_s(Settings()) == 360
    assert ledger.coverage_horizon_s(Settings(tutor_ledger_append_budget_ms=5000)) > 360  # follows the budget in force
    # A smaller worker pool, or more appends in flight, lengthens it.
    assert ledger.attempt_horizon_s(SimpleNamespace(ledger_append_max_in_flight=16, ledger_append_workers=1), 1500) > 360
    # The pool's checkout timeout is the library default the code keeps; the connect bound is the one app.core.db
    # enforces (round 10, K2: the connector's own timeout never bounded a new connection).
    db_source = (API_ROOT / "app" / "core" / "db.py").read_text(encoding="utf-8")
    assert "pool_timeout" not in db_source
    assert inspect.signature(QueuePool.__init__).parameters["timeout"].default == ledger.POOL_CHECKOUT_TIMEOUT_S
    from app.core.db import CONNECT_TIMEOUT_S, cloud_sql_creator

    assert ledger.CONNECT_TIMEOUT_S == CONNECT_TIMEOUT_S == inspect.signature(cloud_sql_creator).parameters["timeout_s"].default == 30


def test_j6_an_append_attempt_runs_the_statements_the_horizon_counts(fresh_database_url):
    factory, engine = _sessions(fresh_database_url)
    statements: list[str] = []
    try:
        append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)  # the head row exists; the engine is warm
        event.listen(engine, "before_cursor_execute", lambda conn, cursor, statement, *args: statements.append(statement))
        append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
        set_locals = [statement for statement in statements if statement.startswith("SET LOCAL")]
        assert len(set_locals) == (3 if engine.dialect.name == "postgresql" else 0)
        # The commit is the sixth statement: it is not a cursor execute.
        assert len(statements) - len(set_locals) == ledger.ATTEMPT_STATEMENTS - 1, statements
    finally:
        engine.dispose()


def test_j6_queued_appends_end_within_the_rounds_the_horizon_counts():
    appender = ledger._LegacyAppender(2, 4)
    hold = 0.3
    started = time.monotonic()
    ends: list[float] = []
    lock = threading.Lock()

    def task():
        time.sleep(hold)
        with lock:
            ends.append(time.monotonic() - started)

    futures = [appender.submit(task, workers=2, max_in_flight=4) for _ in range(4)]
    assert all(future is not None for future in futures)
    assert appender.submit(task, workers=2, max_in_flight=4) is None  # past max_in_flight: refused at once, never queued
    assert appender.drain(10)
    rounds = math.ceil(4 / 2)  # attempt_horizon_s's rounds for 4 in flight on 2 workers
    assert ledger.attempt_horizon_s(SimpleNamespace(ledger_append_max_in_flight=4, ledger_append_workers=2), 1500) == 60 * math.ceil((rounds * 70.5 + 60) / 60)
    ends.sort()
    assert ends[-1] >= (rounds - 0.5) * hold  # the last two waited a round in the queue: the term the 60 s horizon left out
    assert ends[-1] <= rounds * hold + 2.0


def test_j6_the_runbook_reads_the_horizon_by_cpu_allocation():
    stop = next(line for line in RUNBOOK.splitlines() if line.startswith("- ledger coverage below 100%"))
    for needed in ("360 s", "always-on CPU allocation", "until the allocation is read and recorded (DI-48)", "request-based CPU allocation recorded",
                   "has stopped", "`pending` is not a stop"):
        assert needed in stop, needed
    deferred = next(line for line in RUNBOOK.splitlines() if line.startswith("Each `tutor.ledger.append_deferred`"))
    assert "within the horizon is not a stop" in deferred and "18.12 J6" in deferred
    cpu = next(line for line in RUNBOOK.splitlines() if line.startswith("- **Check CPU allocation after the response.**"))
    assert "Until the allocation is read and recorded, read the stops as for always-on CPU" in cpu
    row = next(line for line in OBSERVABILITY.splitlines() if line.startswith("| Ledger coverage (100%) |"))
    for needed in ("360 s", "`ledger.attempt_horizon_s`", "30 s checkout timeout", "30 s connect timeout", "six statements", "16 in flight on 4 workers",
                   "always-on CPU allocation", "Python runs the queued appends before the process exits", "Corrected in 18.12 J6"):
        assert needed in row, needed
    # The 60 s horizon survives only where a line marks it as superseded.
    for name, text in (("runbook", RUNBOOK), ("observability", OBSERVABILITY), ("spec", SPEC.split("### 18.12 Ninth review round", 1)[0])):
        for line in text.splitlines():
            if re.search(r"\b60 s\b", line) and "horizon" in line:
                assert re.search(r"18\.12 (J5, )?J6", line), (name, line[:160])
    for name in ("00_meta/DEFERRED_ITEMS_REGISTER.md",):
        if (register := _bep(name)) is not None:
            di_48 = next(line for line in register.splitlines() if line.startswith("| DI-48 |"))
            di_50 = next(line for line in register.splitlines() if line.startswith("| DI-50 |"))
            assert "ninth review round, spec 18.12 J6" in di_48 and "360 s" in di_50 and "`pending`" in di_50


# ============================================================================================================ J7


def test_j7_spec_4_11_section_9_and_tests_28_and_39_say_what_the_code_does():
    shadow = _section("### 4.11 Shadow runner", "### 4.12")
    listing = shadow.split("```python", 1)[1].split("```", 1)[0]
    assert "TWO_PASS_DELIVERY_IMPLEMENTED = False" not in listing and "def shadow_budget_ms" in listing
    assert "Corrected in 18.12 J7" in shadow.split("```", 2)[2].split("**`effective_mode`", 1)[0]
    step_3 = next(line for line in shadow.splitlines() if line.startswith("3. `pipeline.run("))
    assert "budget_ms=shadow_budget_ms(settings, pipeline.package)" in step_3 and "Corrected in 18.12 J7" in step_3
    source = (API_ROOT / "app" / "services" / "tutor_pipeline" / "shadow.py").read_text(encoding="utf-8")
    assert "budget_ms=shadow_budget_ms(settings, pipeline.package)" in source and "TWO_PASS_DELIVERY_IMPLEMENTED =" not in source
    assert "TWO_PASS_DELIVERY_IMPLEMENTED = False" in (API_ROOT / "app" / "services" / "tutor_pipeline" / "contracts.py").read_text(encoding="utf-8")
    note = next(line for line in SPEC.splitlines() if line.startswith("**Connection note.**"))
    assert "`shadow_budget_ms`" in note and "18.12 J7" in note
    item_28 = next(line for line in SPEC.splitlines() if line.startswith("28. `test_plan_l_a_shadow_or_ledger_failure"))
    assert "`TWO_PASS_METRICS.snapshot()`" in item_28 and "Corrected in 18.12 J7" in item_28
    item_39 = next(line for line in SPEC.splitlines() if line.startswith("39. `test_plan_l_a_held_ledger_lock"))
    assert "+ 500 ms + 1500 ms" in item_39 and "40P01" in item_39 and "Corrected in 18.12 J7" in item_39
    acceptance = (API_ROOT / "tests" / "test_phase3_acceptance.py").read_text(encoding="utf-8")
    assert "+ 500 + 1500" in acceptance.split("def test_plan_l_a_held_ledger_lock_never_delays_the_learner_beyond_the_append_budget", 1)[1]
    plan_l = acceptance.split("def test_plan_l_a_shadow_or_ledger_failure_never_changes_the_learner_response_and_is_counted", 1)[1].split("\ndef ", 1)[0]
    assert "TWO_PASS_METRICS.snapshot" in plan_l and '{"scheduled", "phase2_bound_claim_ratio_baseline"}' in plan_l


# ============================================================================================================ J8


def test_j8_spec_sections_14_and_15_mark_what_later_rounds_changed():
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert re.search(r"^  api-postgres-driver:", ci, flags=re.MULTILINE) and re.search(r"^  api-postgres:", ci, flags=re.MULTILINE)
    assert 'needs.api-postgres-driver.result' in ci
    section_14 = _section("## 14. CI changes", "## 15.")
    bullet = next(line for line in section_14.splitlines() if "runs the API suite on PostgreSQL 16" in line)
    assert bullet.startswith("- `api-postgres-driver` runs") and "Corrected in 18.12 J8" in bullet
    item_5 = _section("5. **`infra/cloudrun/deployment.md`:**", "6. **`infra/cloudrun/observability.md`:**")
    defaults = next(line for line in item_5.splitlines() if "**Defaults that ship:**" in line)
    assert "Superseded in 18.5 C3, marked in 18.12 J8" in defaults
    before = next(line for line in item_5.splitlines() if "**Before the release:**" in line)
    assert "Superseded in 18.8 F14, marked in 18.12 J8" in before and "`alembic current`" in before
    config = (API_ROOT / "app" / "core" / "config.py").read_text(encoding="utf-8")
    assert re.search(r"tutor_ledger_append_budget_ms: int \| None = Field\(\s*default=None", config)
    assert "`alembic upgrade head` on such a database replays revisions" in RUNBOOK


# ======================================================================================================= records


def test_j_the_spec_record_and_the_evidence_package_name_the_ninth_round():
    record = SPEC.split("### 18.12 Ninth review round", 1)[1]
    for group in ("J1", "J2", "J3", "J4", "J5", "J6", "J7", "J8"):
        assert f"**{group}." in record, group
    assert "test_phase3_review9.py" in record and "**Verification of the ninth review round**" in record
    section_16 = _section("## 16. Provisional defaults", "## 17.")
    assert "**Revised in 18.12" in section_16
    row = next(line for line in STRATEGY.splitlines() if line.startswith("| Ninth review round (spec 18.12, J1-J8)"))
    assert "`test_phase3_review9.py`" in row
    source = (API_ROOT / "tests" / "test_phase3_review9.py").read_text(encoding="utf-8")
    for name in re.findall(r"^def (test_\w+)\(", source, flags=re.MULTILINE):
        group = re.match(r"(test_j\d*)_", name).group(1)
        assert f"`{group}_*`" in row, name
    if (phase_record := _bep("phase03/PHASE_RECORD.md")) is not None:
        assert "## Ninth review round (2026-11-19)" in phase_record
        suite = next(line for line in phase_record.splitlines() if line.startswith("| Local suite |"))
        assert 'The latest run is in "Ninth review round"' in suite
    if (register := _bep("00_meta/PROVISIONAL_DEFAULTS_REGISTER.md")) is not None:
        pd_11 = next(line for line in register.splitlines() if line.startswith("| PD-11 |"))
        assert "attempt_horizon_s" in pd_11 and "HORIZON_MARGIN_S" in pd_11
