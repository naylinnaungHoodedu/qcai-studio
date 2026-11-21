"""Phase 3: the render loop and the subset check (plan tasks 3.6-3.7; Phase 3 spec 4.8-4.10).

D4  the subset check fails a rendering that shows no claim, or a claim without its citation; the ledger records what
    the passing rendering showed.
E1  the ledger's rendered_span_ids is what the citation segments displayed; the subset check refuses a citation list
    that is not exactly the displayed spans (rule segment-exact-whitespace-v3).
I2  the fault tests run on a several-claim answer, and each fault is placed as itself and refused by its own rule
    (tutor_fakes.FAULT_SIGNATURES, FaultyRenderer(exact=True)).
J3  a render attempt that raises logs tutor.two_pass.render_failed, and a run whose every attempt raised abstains with
    render_failed, never subset_check_failed.
J4  every test that builds an exact fault renderer asserts what it placed.
L8  the budget is checked between render attempts, never after a passing attempt or the last one.
Each test fails if its defect comes back; the spec's review history (18.4) names the round behind each group.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
import random
from uuid import uuid4

from pydantic import ValidationError
import pytest

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.services import claim_gate
from app.services.claim_gate import check_subset
from app.services.contained_answers import span_is_quotable
from app.services.retrieval_engine import RetrievalEngine
from app.services.span_resolver import SpanResolver
from app.services.store import get_course_store
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline import pipeline as pipeline_module
from app.services.tutor_pipeline.bind import whole_sentences
from app.services.tutor_pipeline.contracts import PresentationPlan
from app.services.tutor_pipeline.pipeline import PipelineInput, TwoPassPipeline, render_checked, rendered_span_ids
from app.services.tutor_pipeline.render import TemplateRenderer
from app.services.tutor_pipeline.resolve import LearnerTurn, resolve_turns

from tutor_fakes import FAULT_MODES, FAULT_SIGNATURES, FaultNotPlaced, FaultyRenderer, ScriptedGenerator, _relayout, inject, place_fault


IN_DOMAIN = "How does graph shrinking reduce routing overhead?"
# A query whose two-pass answer has several claims on several spans (spec 18.10 H1: the graph-shrinking query now
# answers with one whole sentence, because its other spans start or end inside the sentences it matched).
MULTI_CLAIM = "Explain why quantum logistics needs both problem reduction before execution and routing control during compilation."
API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
SPEC = (REPO_ROOT / "docs" / "architecture" / "phase3-implementation-spec.md").read_text(encoding="utf-8")
PACKAGE = get_config_package(Settings())
PARAMS = PACKAGE.tutor_pipeline
OUTSIDE_SPAN = "span-" + "9" * 64


def _run(pipeline: TwoPassPipeline, query: str, plan_id: str = "concise", *, budget_ms: int | None = None):
    resolved = resolve_turns([], LearnerTurn(f"message-{uuid4()}", query), package=pipeline.package)
    return pipeline.run(PipelineInput(resolved=resolved, lesson_slug=None, presentation=PresentationPlan(plan_id=plan_id, source="request"),
                                      response_id=f"shadow-{uuid4()}", delivery="shadow", shadowed_response_id=f"turn-{uuid4()}"),
                        budget_ms=budget_ms, record=False)


def _quotable_documents(store):
    registry = SpanResolver(store).registry
    return [record for record in store.span_registry.records if record.item_kind == "document" and span_is_quotable(record, registry)]


def _events(caplog, name: str) -> list[dict]:
    return [dict(record.json_fields) for record in caplog.records if getattr(record, "json_fields", {}).get("event") == name]


def _section(title: str, end: str) -> str:
    return SPEC.split(title, 1)[1].split(end, 1)[0]


def _pipeline_run(pipeline: TwoPassPipeline, query: str, *, record: bool = False):
    resolved = resolve_turns([], LearnerTurn(f"message-{uuid4()}", query), package=pipeline.package)
    return pipeline.run(PipelineInput(resolved=resolved, lesson_slug=None, presentation=PresentationPlan(plan_id="concise", source="request"),
                                      response_id=f"shadow-{uuid4()}", delivery="shadow", shadowed_response_id=f"turn-{uuid4()}"), record=record)


# =============================================================================================================== D4


@pytest.mark.parametrize("mode", ["drop_all_claims", "drop_citations"])
def test_d4_a_rendering_without_claims_or_citations_never_answers(mode):
    settings = Settings()
    engine = RetrievalEngine(get_course_store(), settings)
    import random

    always = FaultyRenderer(TemplateRenderer(), [True, True, True], random.Random(3), modes=(mode,), outside_sentence="x", outside_span_id="span-" + "9" * 64)
    result = _run(TwoPassPipeline(engine, settings, renderer=always), IN_DOMAIN)
    assert (result.decision, result.abstention_reason, result.render_attempts) == ("abstain", "subset_check_failed", 3)
    assert result.entry.presentation.rendered_claim_ids == () and result.entry.presentation.rendered_span_ids == ()


class _DropLastClaim:
    """Leaves the last locked claim (and its citation markers) out: a partial rendering, which passes."""

    renderer_id = "template-renderer-v1"

    def render(self, locked, plan, *, attempt):
        from tutor_fakes import _relayout

        rendered = TemplateRenderer().render(locked, plan, attempt=attempt)
        last_line = max(segment.line for segment in rendered.segments if segment.kind == "claim")
        kept = [segment for segment in rendered.segments if segment.line != last_line]
        cited = tuple(dict.fromkeys(segment.span_id for segment in kept if segment.kind == "citation"))
        return _relayout(rendered, kept, cited)


def test_d4_the_ledger_records_which_claims_and_spans_the_answer_showed():
    settings = Settings()
    engine = RetrievalEngine(get_course_store(), settings)
    full = _run(TwoPassPipeline(engine, settings), MULTI_CLAIM)
    assert full.decision == "answer" and len(full.locked.claims) >= 2
    presentation = full.entry.presentation
    assert presentation.rendered_claim_ids == tuple(claim.claim_id for claim in full.locked.claims)
    assert presentation.rendered_span_ids == full.rendered.citations
    # A rendering that leaves a claim out still answers (spec 4.9: a subset), and the record says what it showed.
    partial = _run(TwoPassPipeline(engine, settings, renderer=_DropLastClaim()), MULTI_CLAIM)
    assert partial.decision == "answer" and partial.locked.claim_set_hash == full.locked.claim_set_hash
    shown = partial.entry.presentation.rendered_claim_ids
    assert len(shown) == len(partial.locked.claims) - 1 and set(shown) < {claim.claim_id for claim in partial.entry.claims}
    assert partial.entry.presentation.rendered_span_ids == partial.rendered.citations
    assert set(partial.entry.presentation.rendered_span_ids) <= set(partial.entry.span_ids)
    # The contract refuses an answer whose rendering showed nothing, or ids outside the record.
    payload = full.entry.model_dump(mode="json")
    # Each edit is refused by the rule it breaks, in the record's own schema (ledger-entry-v2 since Phase 4), so the
    # refusal is never the schema literal's.
    model = contracts.ENTRY_SCHEMAS[payload["entry_schema"]]
    model.model_validate(payload)
    rules = ("an answer's passing rendering shows at least one claim and one citation",
             "an answer's passing rendering shows at least one claim and one citation",
             "presentation.rendered_claim_ids names a claim that is not a recorded claim")
    for edit, rule in zip(({"rendered_claim_ids": []}, {"rendered_span_ids": []}, {"rendered_claim_ids": ["claim-" + "0" * 32]}), rules):
        changed = {**payload, "presentation": {**payload["presentation"], **edit}}
        with pytest.raises(ValidationError, match=rule):
            model.model_validate(changed)


# =============================================================================================================== E1


class _StaleCitations:
    """The reviewer's renderer: leaves the last claim line (and its markers) out, but keeps the citation list."""

    renderer_id = "template-renderer-v1"

    def render(self, locked, plan, *, attempt):
        rendered = TemplateRenderer().render(locked, plan, attempt=attempt)
        last_line = max(segment.line for segment in rendered.segments if segment.kind == "claim")
        kept = [segment for segment in rendered.segments if segment.line != last_line]
        return _relayout(rendered, kept, rendered.citations)


def test_e1_a_rendering_that_lists_a_span_it_never_shows_never_answers(monkeypatch):
    settings = Settings()
    engine = RetrievalEngine(get_course_store(), settings)
    full = _run(TwoPassPipeline(engine, settings), MULTI_CLAIM)
    assert full.decision == "answer" and len(full.locked.claims) >= 2
    # On the reviewer's query the last claim's span is cited by no other claim, so the stale list names an unshown span.
    probe = _StaleCitations().render(full.locked, PresentationPlan(plan_id="concise", source="request"), attempt=1)
    assert set(probe.citations) - set(claim_gate.displayed_span_ids(probe)), "the query no longer has a span shown only by its last claim"
    assert check_subset_problems(probe, full.locked) == ("citation_list_mismatch",)
    # Spec 18.11 I2: the pipeline half runs on the same several-claim query (on the graph-shrinking query, one claim
    # since 18.10 H1, the stale renderer dropped the only claim and also failed no_claim_rendered), and every attempt is
    # refused by the stale list alone.
    seen = _spy_subset_problems(monkeypatch)
    stale = _run(TwoPassPipeline(engine, settings, renderer=_StaleCitations()), MULTI_CLAIM)
    assert (stale.decision, stale.abstention_reason, stale.render_attempts) == ("abstain", "subset_check_failed", 3)
    assert seen == [("citation_list_mismatch",)] * 3, seen
    assert stale.entry.presentation.rendered_span_ids == () and stale.entry.presentation.subset_check == "failed"


def check_subset_problems(rendered, locked) -> tuple[str, ...]:
    return claim_gate.check_subset(rendered, locked).problems


def _spy_subset_problems(monkeypatch) -> list[tuple[str, ...]]:
    """The problem codes of every subset check the pipeline runs (spec 18.11 I2)."""
    seen: list[tuple[str, ...]] = []
    check = claim_gate.check_subset

    def spy(rendered, locked):
        result = check(rendered, locked)
        seen.append(result.problems)
        return result

    monkeypatch.setattr(pipeline_module, "check_subset", spy)
    return seen


def test_e1_the_record_names_the_displayed_spans_even_if_a_check_let_a_stale_list_through(monkeypatch):
    settings = Settings()
    engine = RetrievalEngine(get_course_store(), settings)
    # Defence in depth: even a subset check that passed the stale list could not make the record name the unshown span.
    monkeypatch.setattr(pipeline_module, "check_subset", lambda rendered, locked: claim_gate.SubsetCheckResult(True, (), 0, 0, 0))
    result = _run(TwoPassPipeline(engine, settings, renderer=_StaleCitations()), MULTI_CLAIM)
    assert result.decision == "answer"
    displayed = tuple(dict.fromkeys(segment.span_id for segment in result.rendered.segments if segment.kind == "citation"))
    assert result.entry.presentation.rendered_span_ids == displayed == rendered_span_ids(result.rendered)
    assert set(result.rendered.citations) - set(displayed)  # the renderer's own list named more


def test_e1_the_rule_id_names_the_new_behaviour_and_the_fault_modes_include_it(monkeypatch):
    assert claim_gate.SUBSET_CHECK_RULE == "segment-exact-whitespace-v3" == PARAMS.subset_check
    assert "citation_list_mismatch" in claim_gate.PROBLEM_CODES
    assert "undisplayed_citation" in FAULT_MODES
    settings = Settings()
    engine = RetrievalEngine(get_course_store(), settings)
    # Spec 18.11 I2: on the several-claim query the fault leaves a claim line out (on the one-claim graph-shrinking
    # query it fell back to listing a shown span twice), and exact refuses any fallback.
    seen = _spy_subset_problems(monkeypatch)
    always = FaultyRenderer(TemplateRenderer(), [True, True, True], random.Random(5), modes=("undisplayed_citation",), outside_sentence="x",
                            outside_span_id="span-" + "9" * 64, exact=True)
    result = _run(TwoPassPipeline(engine, settings, renderer=always), MULTI_CLAIM)
    assert (result.decision, result.abstention_reason) == ("abstain", "subset_check_failed")
    assert always.placed == ["undisplayed_citation"] * 3 and seen == [("citation_list_mismatch",)] * 3, (always.placed, seen)
    for path in ("docs/adr/ADR-001-grounding-separation.md", "docs/adr/ADR-005-abstention-gate.md", "docs/evaluation/phase3/README.md"):
        assert "segment-exact-whitespace-v3" in (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert "citation_list_mismatch" in SPEC


# =============================================================================================================== I2


def _outside_sentence(store, locked) -> str:
    texts = {claim.text for claim in locked.claims}
    for record in _quotable_documents(store):
        if record.span_id in locked.span_ids:
            continue
        for sentence in whole_sentences(record, store, min_words=PARAMS.min_sentence_words, max_chars=PARAMS.max_sentence_chars):
            if sentence.text not in texts:
                return sentence.text
    raise AssertionError("no outside sentence")


@pytest.mark.parametrize("plan_id", ("concise", "stepwise", "socratic"))
def test_i2_every_fault_mode_is_placed_as_itself_and_raises_its_own_problem_under_every_plan(plan_id):
    assert set(FAULT_SIGNATURES) == set(FAULT_MODES) and set(FAULT_SIGNATURES.values()) <= set(claim_gate.PROBLEM_CODES)
    settings = Settings()
    store = get_course_store()
    result = _run(TwoPassPipeline(RetrievalEngine(store, settings), settings), MULTI_CLAIM, plan_id)
    assert result.decision == "answer" and len(result.locked.claims) >= 2 and len(result.locked.span_ids) >= 2
    claim_lines = {segment.line for segment in result.rendered.segments if segment.kind == "claim"}
    assert len(claim_lines) >= 2
    outside = _outside_sentence(store, result.locked)
    for mode in FAULT_MODES:
        faulty = inject(result.rendered, mode, outside_sentence=outside, outside_span_id=OUTSIDE_SPAN, exact=True)
        problems = check_subset(faulty, result.locked).problems
        assert FAULT_SIGNATURES[mode] in problems, (plan_id, mode, problems)
        if mode == "wrong_citation":  # a citation moved onto another claim, not the invented claim of the fallback
            assert "unmapped_factual_sentence" not in problems, problems
            assert faulty != inject(result.rendered, "invented", outside_sentence=outside, outside_span_id=OUTSIDE_SPAN)
        if mode == "undisplayed_citation":  # a claim line is gone, its span still listed: that rule alone
            assert problems == ("citation_list_mismatch",)
            assert len({segment.line for segment in faulty.segments if segment.kind == "claim"}) == len(claim_lines) - 1


def test_i2_an_exact_injection_refuses_a_fault_a_one_claim_answer_cannot_hold():
    settings = Settings()
    engine = RetrievalEngine(get_course_store(), settings)
    full = _run(TwoPassPipeline(engine, settings), MULTI_CLAIM)
    first = full.locked.claims[0]
    one = _run(TwoPassPipeline(engine, settings, generator=ScriptedGenerator([[(first.text, first.span_ids)]])), MULTI_CLAIM)
    assert one.decision == "answer" and len(one.locked.claims) == 1
    for mode, fallback in (("wrong_citation", "invented"), ("undisplayed_citation", "listed_twice")):
        _, placed = place_fault(one.rendered, mode, outside_sentence="x", outside_span_id=OUTSIDE_SPAN)
        assert placed == fallback  # what the seventh round's tests silently ran on the one-claim query
        with pytest.raises(FaultNotPlaced):
            inject(one.rendered, mode, outside_sentence="x", outside_span_id=OUTSIDE_SPAN, exact=True)
        renderer = FaultyRenderer(TemplateRenderer(), [True, True, True], random.Random(1), modes=(mode,), outside_sentence="x",
                                  outside_span_id=OUTSIDE_SPAN, exact=True)
        refused = _run(TwoPassPipeline(engine, settings, generator=ScriptedGenerator([[(first.text, first.span_ids)]]), renderer=renderer), MULTI_CLAIM)
        # Every attempt raised FaultNotPlaced: since spec 18.12 J3 the pipeline records render_failed, never
        # subset_check_failed, so a refused (unplaced) fault can no longer pass as a refused rendering.
        assert refused.abstention_reason == contracts.RENDER_FAILED and renderer.placed == [f"not_placed:{mode}"] * 3


# =============================================================================================================== J3


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
    contracts.ENTRY_SCHEMAS[result.entry.entry_schema].model_validate(result.entry.model_dump(mode="json"))  # a valid record of its own schema
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


# =============================================================================================================== J4


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
    assert checked >= 4, checked  # acceptance AC-3-3, and E1, I2 and J3 in this module


# =============================================================================================================== L8


class _Raising:
    renderer_id = "template-renderer-v1"

    def render(self, locked, presentation, *, attempt):
        raise RuntimeError("render fault (test)")


def test_l8_the_budget_is_checked_between_render_attempts_never_after_a_passing_or_the_last_one():
    settings = Settings()
    result = _pipeline_run(TwoPassPipeline(RetrievalEngine(get_course_store(), settings), settings), MULTI_CLAIM)
    assert result.decision == "answer"
    presentation = PresentationPlan(plan_id="concise", source="request")
    checks: list[int] = []

    def over() -> bool:
        checks.append(1)
        return True

    rendered, attempts, reason = render_checked(TemplateRenderer(PACKAGE), result.locked, presentation, max_regenerations=2, over=over)
    assert rendered is not None and (attempts, reason, checks) == (1, None, [])  # a passing attempt is never checked
    rendered, attempts, reason = render_checked(_Raising(), result.locked, presentation, max_regenerations=2, over=over)
    assert (rendered, attempts, reason, len(checks)) == (None, 1, "budget_exceeded", 1)  # checked after a failed attempt
    checks.clear()
    rendered, attempts, reason = render_checked(_Raising(), result.locked, presentation, max_regenerations=0, over=over)
    assert (rendered, attempts, reason, checks) == (None, 1, "render_failed", [])  # the last attempt is never checked
    section = _section("### 4.10 Pipeline", "### 4.11")
    assert "after each of steps 2, 4, 5 and each render attempt" not in section
    assert "between render attempts (step 7): never after a passing attempt or the last one" in section
