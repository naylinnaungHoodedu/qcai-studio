"""Phase 5 payload policy (plan Phase 5 H "Only public-corpus spans leave the platform"; plan L "Stop on a payload
violation"; invariant 8; R-10; Q-15; Phase 5 spec 4.5)."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.gateway.contracts import (
    AlignmentInstructions,
    AlignmentRequest,
    ReadabilityBand,
    VerdictInstructions,
    VerdictRequest,
    VerdictSpan,
)
from app.gateway.policy import PayloadPolicy, PayloadViolation, PolicyContext
from app.services.store import get_course_store
from app.services.v2_panel.rules import alignment_prompt_hash, verifier_prompt_hash
from v1_fakes import MULTI_CLAIM, dev_pipeline, run

POLICY = PayloadPolicy()


@pytest.fixture(scope="module")
def answered():
    pipeline = dev_pipeline(Settings(model_gateway="off"))
    result = run(pipeline, MULTI_CLAIM)
    assert result.rendered is not None
    return pipeline, result


def claim_item(claim: str, span_id: str, text: str) -> VerdictRequest:
    return VerdictRequest(claim_text=claim, span=VerdictSpan(span_id=span_id, text=text),
                          instructions=VerdictInstructions(prompt_hash=verifier_prompt_hash(), tool_contract_version="mcp-tools-v1"))


def alignment_item(text: str, objective=None) -> AlignmentRequest:
    return AlignmentRequest(rendered_text=text, objective=objective, band=ReadabilityBand(min_grade=-4.0, max_grade=64.0),
                            instructions=AlignmentInstructions(prompt_hash=alignment_prompt_hash(), tool_contract_version="mcp-tools-v1"))


def reason_of(request, context) -> str | None:
    try:
        POLICY.check(request, context)
    except PayloadViolation as exc:
        return exc.reason
    return None


def test_a_claim_item_passes_only_with_a_public_quotable_span_and_its_own_text(answered):
    pipeline, result = answered
    claim = result.locked.claims[0]
    record = pipeline.store.span_registry.get(claim.span_ids[0])
    context = PolicyContext(store=pipeline.store, corpus_registry=pipeline.registry)
    assert reason_of(claim_item(claim.text, record.span_id, record.text), context) is None
    assert reason_of(claim_item(claim.text, record.span_id, "  ".join(record.text.split(" "))), context) is None  # whitespace collapsed
    assert reason_of(claim_item(claim.text, "span-" + "f" * 64, record.text), context) == "unknown_span"
    assert reason_of(claim_item(claim.text, record.span_id, record.text + " An added sentence."), context) == "span_text_differs"
    # The claim text is public corpus text: it lies inside its span (V1.2 binds whole verbatim sentences), folded.
    assert reason_of(claim_item(claim.text.upper(), record.span_id, record.text), context) is None
    assert reason_of(claim_item("Every learner question is answered here.", record.span_id, record.text), context) == "claim_not_in_span"
    from app.core.corpus_governance import get_corpus_registry
    from app.services.content_assembler import CourseStore

    governed_settings = Settings(environment="production", enforce_corpus_governance=True, allowed_origins=["https://qantumlearn.academy"])
    governed_store = CourseStore(governed_settings)
    governed_context = PolicyContext(store=governed_store, corpus_registry=get_corpus_registry(governed_settings))
    # D-31: nothing is approved, so the governed store holds no document span of the development one, and none of the
    # spans it holds may leave.
    assert reason_of(claim_item(claim.text, record.span_id, record.text), governed_context) == "unknown_span"
    governed_records = list(governed_store.span_registry._by_id.values())
    assert governed_records
    for governed_record in governed_records:
        assert reason_of(claim_item(claim.text, governed_record.span_id, governed_record.text), governed_context) == "span_not_quotable"


def test_an_identifier_anywhere_in_a_payload_is_a_violation(answered):
    pipeline, result = answered
    claim = result.locked.claims[0]
    record = pipeline.store.span_registry.get(claim.span_ids[0])
    with pytest.raises(ValueError):
        claim_item(f"{claim.text} turn-12345678-1234-1234-1234-123456789abc", record.span_id, record.text)
    request = claim_item(claim.text, record.span_id, record.text)
    tampered = request.model_copy(update={"claim_text": "Contact learner@example.edu now."})
    assert reason_of(tampered, PolicyContext(store=pipeline.store, corpus_registry=pipeline.registry)) == "identifier_in_payload"


def test_an_alignment_item_carries_only_locked_claims_templates_and_the_lesson_summary(answered):
    pipeline, result = answered
    rendered, locked = result.rendered, result.locked
    context = PolicyContext(store=pipeline.store, corpus_registry=pipeline.registry, rendering=rendered, locked=locked)
    assert reason_of(alignment_item(rendered.text), context) is None
    assert reason_of(alignment_item(rendered.text + " extra"), context) == "rendering_differs"
    segments = list(rendered.segments)
    first = next(index for index, segment in enumerate(segments) if segment.kind == "connective")
    segments[first] = segments[first].model_copy(update={"text": "A connective the renderer never wrote."})
    from app.services.tutor_pipeline.render import layout_text

    forged = rendered.model_copy(update={"segments": tuple(segments), "text": layout_text(segments)})
    forged_context = PolicyContext(store=pipeline.store, corpus_registry=pipeline.registry, rendering=forged, locked=locked)
    assert reason_of(alignment_item(forged.text), forged_context) == "non_template_segment"
    slug, lesson = next(iter(get_course_store().lessons.items()))
    lesson_context = PolicyContext(store=pipeline.store, corpus_registry=pipeline.registry, rendering=rendered, locked=locked, lesson_slug=slug)
    assert reason_of(alignment_item(rendered.text, objective=lesson.summary), lesson_context) is None
    assert reason_of(alignment_item(rendered.text, objective="Another objective."), lesson_context) == "objective_not_lesson_summary"


def test_the_policy_context_is_per_call_so_one_gateway_serves_pipelines_over_different_stores(answered):
    from app.gateway.adapters import FakeAdapter
    from v2_fakes import fake_spec, fresh_gateway

    pipeline, result = answered
    claim = result.locked.claims[0]
    record = pipeline.store.span_registry.get(claim.span_ids[0])
    spec = fake_spec("fake-alpha")
    gateway = fresh_gateway(adapters={spec.adapter_id: FakeAdapter(spec)})
    other = dev_pipeline(Settings(model_gateway="off"))
    for store_pipeline in (pipeline, other):
        context = PolicyContext(store=store_pipeline.store, corpus_registry=store_pipeline.registry)
        assert gateway.verify(spec, claim_item(claim.text, record.span_id, record.text), context=context).verdict == "SUPPORTED"
    assert gateway.state == "open"
