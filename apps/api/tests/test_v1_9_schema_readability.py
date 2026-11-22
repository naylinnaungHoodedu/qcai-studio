"""V1.9, schema and readability band (Phase 4 spec 4.10, conflict 18; PD-16)."""

from __future__ import annotations

import dataclasses

import pytest

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.services.tutor_pipeline.contracts import ClaimPlan, GeneratorRef, ProposedClaim, RenderedResponse, Segment
from app.services.tutor_pipeline.pipeline import render_checked
from app.services.tutor_pipeline.render import TemplateRenderer
from app.services.v1_checks.v1_9_schema_readability import (
    check_v1_9_envelope,
    check_v1_9_plan,
    check_v1_9_readability,
    readability_grade,
    syllables,
)
from v1_fakes import MULTI_CLAIM, dev_pipeline, run

PACKAGE = get_config_package(Settings())
V1 = PACKAGE.v1
REF = GeneratorRef(generator_id="g", model_id="g", kind="extractive", prompt_hash="1" * 64)


def test_a_plan_with_an_extra_field_or_another_generator_or_a_fault_is_invalid():
    plan = ClaimPlan(generator=REF, claims=(ProposedClaim(text="A claim.", span_ids=("span-" + "1" * 64,)),))
    assert check_v1_9_plan(plan, generator_ref=REF, attempt=1)[0].reason_code == "schema_valid"
    assert check_v1_9_plan(plan.model_dump(mode="json"), generator_ref=REF, attempt=1)[1] == plan
    extra = {**plan.model_dump(mode="json"), "extra": True}
    for raw in (extra, None, "a string", RuntimeError("generator fault"), {"claims": []}):
        result, parsed = check_v1_9_plan(raw, generator_ref=REF, attempt=2)
        assert (result.outcome, result.reason_code, parsed) == ("hard_fail", "claim_plan_invalid", None)
    other = plan.model_copy(update={"generator": REF.model_copy(update={"generator_id": "other"})})
    assert check_v1_9_plan(other, generator_ref=REF, attempt=1)[0].reason_code == "generator_mismatch"


def test_an_envelope_is_re_validated_even_when_built_with_model_construct():
    good = RenderedResponse(renderer_id="r", plan_id="concise", attempt=1, segments=(), citations=(), text="")
    assert check_v1_9_envelope(good, attempt=1)[0].reason_code == "schema_valid"
    bad = RenderedResponse.model_construct(renderer_id="r", plan_id="concise", attempt=0, segments=(), citations=(), text="")
    result, rendered = check_v1_9_envelope(bad, attempt=1)
    assert (result.outcome, result.reason_code, result.stage, rendered) == ("hard_fail", "response_envelope_invalid", "post_render", None)


def test_an_invalid_envelope_reaching_render_checked_is_response_envelope_invalid_not_a_fault():
    locked = run(dev_pipeline(), MULTI_CLAIM).locked

    class Invalid:
        renderer_id = "template-renderer-v1"

        def render(self, locked, plan, *, attempt, **options):
            return RenderedResponse.model_construct(renderer_id="r", plan_id=plan.plan_id, attempt=0, segments=(), citations=(), text="")

    seen = []

    def hook(attempt):
        from app.services.tutor_pipeline.pipeline import HookVerdict

        seen.append((attempt.fault, attempt.envelope_error, attempt.subset))
        return HookVerdict(accept=False, reason="response_envelope_invalid")

    from app.services.tutor_pipeline.contracts import PresentationPlan

    rendered, attempts, reason = render_checked(Invalid(), locked, PresentationPlan(plan_id="concise", source="request"), max_regenerations=2,
                                                post_render=hook)
    assert (rendered, attempts, reason) == (None, 3, "response_envelope_invalid")
    assert seen == [(None, "response_envelope_invalid", None)] * 3


@pytest.mark.parametrize(("word", "count"), [("the", 1), ("table", 2), ("free", 1), ("make", 1), ("rhythm", 1), ("quantum", 2), ("ee", 1), ("e", 1)])
def test_syllable_vectors(word, count):
    assert syllables(word) == count


def test_fk_grade_vectors_and_band_edges():
    def rendered(*texts):
        segments = tuple(Segment(kind="connective", line=index, text=text) for index, text in enumerate(texts))
        return RenderedResponse(renderer_id="r", plan_id="concise", attempt=1, segments=segments, citations=(), text="\n".join(texts))

    # 4 words, 1 sentence, 4 syllables: 0.39 * 4 + 11.8 * 1 - 15.59
    assert readability_grade(rendered("The cat sat down.")) == round(0.39 * 4 + 11.8 - 15.59, 3)
    citation = Segment(kind="citation", line=0, text="[1]", span_id="span-" + "1" * 64)
    with_citation = RenderedResponse(renderer_id="r", plan_id="concise", attempt=1, segments=(Segment(kind="connective", line=0, text="The cat sat down."), citation),
                                     citations=(), text="")
    assert readability_grade(with_citation) == readability_grade(rendered("The cat sat down."))
    grade = readability_grade(rendered("The cat sat down."))
    assert check_v1_9_readability(rendered("The cat sat down."), v1=V1, attempt=1).reason_code == "within_band"
    assert check_v1_9_readability(rendered("The cat sat down."), v1=dataclasses.replace(V1, readability_min=grade + 0.001), attempt=1).reason_code == "below_band"
    assert check_v1_9_readability(rendered("The cat sat down."), v1=dataclasses.replace(V1, readability_max=grade - 0.001), attempt=1).reason_code == "above_band"
    assert check_v1_9_readability(rendered("The cat sat down."), v1=dataclasses.replace(V1, readability_min=grade, readability_max=grade), attempt=1).outcome == "pass"
    assert check_v1_9_readability(rendered("The cat sat down."), v1=dataclasses.replace(V1, readability_max=grade - 1), attempt=1).outcome == "flag"


def test_every_template_rendering_of_the_dev_answers_is_inside_the_provisional_band():
    renderer = TemplateRenderer(PACKAGE)
    from app.services.tutor_pipeline.contracts import PresentationPlan

    for query in (MULTI_CLAIM, "Why does routing depth matter?", "What is a quantum kernel?"):
        locked = run(dev_pipeline(), query).locked
        if not locked.claims:
            continue
        for plan in ("concise", "stepwise", "socratic"):
            rendered = renderer.render(locked, PresentationPlan(plan_id=plan, source="request"), attempt=1)
            assert V1.readability_min <= readability_grade(rendered) <= V1.readability_max
