"""Renderer template-renderer-v1 and the subset checker (plan tasks 3.6-3.7; Phase 3 spec 4.8, 4.9, 13.2)."""

from __future__ import annotations

import pytest

from app.core.config_package import canonical_sha256
from app.services import claim_gate
from app.services.claim_gate import PROBLEM_CODES, check_subset
from app.services.tutor_pipeline import render
from app.services.tutor_pipeline.contracts import ConfigStamp, LockedClaim, LockedClaimSet, PresentationPlan, ResolverRef, Segment, lock_hash
from app.services.tutor_pipeline.render import PLANS_LAYOUT, TEMPLATES, TemplateRenderer, layout_text, pedagogical_prompt_hash

H = "a" * 64
SPAN_A, SPAN_B, SPAN_C = ("span-" + digit * 64 for digit in "123")


def _locked() -> LockedClaimSet:
    claims = (
        # Locked order is evidence order; source order puts the second claim first.
        LockedClaim(claim_id="claim-" + "b" * 32, text="Routing adds SWAP gates on sparse hardware.", span_ids=(SPAN_B,), source_order=("item-b", 40)),
        LockedClaim(claim_id="claim-" + "a" * 32, text="Graph shrinking reduces the routing burden.", span_ids=(SPAN_A, SPAN_C), source_order=("item-a", 5)),
    )
    draft = LockedClaimSet.model_construct(
        claims=claims, span_ids=(SPAN_A, SPAN_B, SPAN_C), corpus_version="c", index_version="i", generator=None, evidential_prompt_hash=None,
        pedagogical_prompt_hash=H, resolver=ResolverRef(model_id="thread-resolver-v1", prompt_hash=H),
        config_package=ConfigStamp(version="2.0.0", sha256=H), claim_set_hash="0" * 64,
    )
    return LockedClaimSet.model_validate({**draft.model_dump(mode="json"), "claim_set_hash": lock_hash(draft)})


LOCKED = _locked()
RENDERER = TemplateRenderer()


def _render(plan_id: str):
    return RENDERER.render(LOCKED, PresentationPlan(plan_id=plan_id, source="request"), attempt=1)


def test_each_plan_has_its_exact_layout():
    concise = _render("concise")
    assert concise.text == (
        "These sentences are quoted from the approved course sources:\n"
        "Routing adds SWAP gates on sparse hardware. [1]\n"
        "Graph shrinking reduces the routing burden. [2] [3]"
    )
    assert concise.citations == (SPAN_B, SPAN_A, SPAN_C)
    stepwise = _render("stepwise")
    assert stepwise.text == (
        "The approved course sources make these points, in source order:\n"
        "Point 1: Graph shrinking reduces the routing burden. [1] [2]\n"
        "Point 2: Routing adds SWAP gates on sparse hardware. [3]"
    )
    assert stepwise.citations == (SPAN_A, SPAN_C, SPAN_B)  # numbered by first appearance after reordering
    socratic = _render("socratic")
    assert socratic.text == (
        "What do the approved course sources say about your question?\n"
        "Routing adds SWAP gates on sparse hardware. [1]\n"
        "Graph shrinking reduces the routing burden. [2] [3]\n"
        "Which of these points would you like to look at more closely?"
    )
    for rendered in (concise, stepwise, socratic):
        assert layout_text(rendered.segments) == rendered.text
        assert check_subset(rendered, LOCKED).passed
        assert [segment.claim_id for segment in rendered.segments if segment.kind == "claim"].count("claim-" + "a" * 32) == 1
        assert {segment.kind for segment in rendered.segments} <= {"connective", "question", "claim", "citation"}
    assert len({concise.text, stepwise.text, socratic.text}) == 3


def test_the_renderer_is_never_called_for_an_abstention():
    empty = LockedClaimSet.model_validate({**LOCKED.model_dump(mode="json"), "claims": [], "span_ids": [],
                                            "claim_set_hash": lock_hash(LOCKED.model_copy(update={"claims": (), "span_ids": ()}))})
    with pytest.raises(ValueError, match="abstention"):
        RENDERER.render(empty, PresentationPlan(plan_id="concise", source="default"), attempt=1)


def test_the_pedagogical_hash_covers_every_plan(monkeypatch):
    pinned = pedagogical_prompt_hash()
    changed = {**PLANS_LAYOUT, "socratic": {**PLANS_LAYOUT["socratic"], "close": None}}
    monkeypatch.setitem(render.PEDAGOGICAL_PROMPT_HASH_INPUT, "plans", changed)
    assert pedagogical_prompt_hash() != pinned
    monkeypatch.setitem(render.PEDAGOGICAL_PROMPT_HASH_INPUT, "plans", PLANS_LAYOUT)
    assert pedagogical_prompt_hash() == pinned == canonical_sha256(render.PEDAGOGICAL_PROMPT_HASH_INPUT)


def _with(rendered, segments, *, citations=None, text=None):
    segments = tuple(segments)
    return rendered.model_copy(update={"segments": segments, "citations": tuple(citations if citations is not None else rendered.citations),
                                       "text": text if text is not None else layout_text(segments)})


def test_every_problem_code_is_raised():
    base = _render("concise")
    segments = list(base.segments)
    claim0 = next(segment for segment in segments if segment.kind == "claim")
    cite_b = next(segment for segment in segments if segment.kind == "citation" and segment.span_id == SPAN_B)
    cases = {
        "empty": _with(base, [], text=""),
        "text_not_segments": _with(base, segments, text=base.text + " More."),
        "unmapped_factual_sentence": _with(base, [*segments, Segment(kind="claim", line=1, text="An invented fact.", claim_id="claim-" + "0" * 32)]),
        "duplicate_claim": _with(base, [*segments, claim0.model_copy(update={"line": 3})]),
        "citation_outside_locked_set": _with(base, [*segments, Segment(kind="citation", line=1, text="[4]", template_id="citation", params=(4,),
                                                                          span_id="span-" + "9" * 64)], citations=(*base.citations, "span-" + "9" * 64)),
        "citation_not_on_claim": _with(base, [segment if segment is not cite_b else segment.model_copy(update={"line": 0}) for segment in segments]),
        "citation_marker_mismatch": _with(base, [segment if segment is not cite_b else segment.model_copy(update={"text": "[7]", "params": (7,)})
                                                 for segment in segments]),
    }
    for code, rendered in cases.items():
        result = check_subset(rendered, LOCKED)
        assert not result.passed and code in result.problems, (code, result.problems)
    assert set(cases) == set(PROBLEM_CODES)
    # A fact in a connective slot, and a wrong template kind, are unmapped factual sentences.
    lead = segments[0]
    for edited in (lead.model_copy(update={"text": "Routing is always optimal."}), lead.model_copy(update={"kind": "question"}),
                   lead.model_copy(update={"template_id": "stepwise.point"})):
        assert "unmapped_factual_sentence" in check_subset(_with(base, [edited, *segments[1:]]), LOCKED).problems
    # A claim segment whose claim_id disagrees with the matching locked claim.
    wrong_id = _with(base, [segment if segment is not claim0 else segment.model_copy(update={"claim_id": "claim-" + "a" * 32}) for segment in segments])
    assert "unmapped_factual_sentence" in check_subset(wrong_id, LOCKED).problems
    # Lines must be contiguous from 0, in order.
    shifted = _with(base, [segment.model_copy(update={"line": segment.line + 1}) for segment in segments])
    assert "text_not_segments" in check_subset(shifted, LOCKED).problems
    # A missing claim is reported, not failed: the plan requires a subset only.
    partial = _with(base, [segment for segment in segments if segment.line != 2], citations=(SPAN_B,))
    result = check_subset(partial, LOCKED)
    assert result.passed and result.missing_claims == 1


def test_matching_is_exact_after_normalisation_only():
    base = _render("concise")
    segments = list(base.segments)
    claim0 = next(segment for segment in segments if segment.kind == "claim")
    spaced = _with(base, [segment if segment is not claim0 else segment.model_copy(update={"text": "Routing  adds SWAP gates on sparse hardware. "})
                          for segment in segments])
    assert check_subset(spaced, LOCKED).passed  # whitespace is normalised
    digit = _with(base, [segment if segment is not claim0 else segment.model_copy(update={"text": "Routing adds SWAP gates on sparse hardware 2."})
                         for segment in segments])
    assert "unmapped_factual_sentence" in check_subset(digit, LOCKED).problems


def test_the_overlap_gate_and_evidence_digest_are_gone():
    assert not hasattr(claim_gate, "ClaimGate") and not hasattr(claim_gate, "evidence_digest")
    assert claim_gate.SUBSET_CHECK_RULE == "segment-exact-normalised-v1"
    assert TEMPLATES["citation"] == ("citation", "[{0}]")
