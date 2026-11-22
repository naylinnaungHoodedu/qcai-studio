"""V1.1, every span id resolves (Phase 4 spec 4.2; plan Phase 4 D; R-13, R-14)."""

from __future__ import annotations

import pytest

from app.services.span_resolver import SpanResolver
from app.services.store import get_course_store
from app.services.tutor_pipeline.contracts import ClaimPlan, GeneratorRef, ProposedClaim
from app.services.v1_checks.v1_1_resolution import check_v1_1
from v1_fakes import MULTI_CLAIM, dev_pipeline, run

REF = GeneratorRef(generator_id="g", model_id="g", kind="extractive", prompt_hash="1" * 64)


def _bundle():
    result = run(dev_pipeline(), MULTI_CLAIM)
    assert result.bundle.spans
    return result.bundle


def _plan(*span_lists) -> ClaimPlan:
    return ClaimPlan(generator=REF, claims=tuple(ProposedClaim(text=f"Claim number {index} text here.", span_ids=tuple(spans))
                                                 for index, spans in enumerate(span_lists)))


def test_each_reason_code_and_the_first_failure_decides():
    bundle = _bundle()
    resolver = SpanResolver(get_course_store())
    real = bundle.spans[0].span_id
    assert check_v1_1(_plan([real]), bundle, resolver=resolver, attempt=1).reason_code == "resolved"
    cases = {
        "malformed_span_id": "span-not-a-span-id",
        "unresolvable": "span-" + "e" * 64,
    }
    for reason, bad in cases.items():
        result = check_v1_1(_plan([real], [bad]), bundle, resolver=resolver, attempt=2)
        assert (result.outcome, result.reason_code, result.attempt, result.claim_id) == ("hard_fail", reason, 2, None)
        assert result.ehmf_types == ("B",) and result.stage == "pre_render"
    # Upper-case hex is not a span id (ids are lowercase), so it is malformed.
    assert check_v1_1(_plan([real.upper()]), bundle, resolver=resolver, attempt=1).reason_code == "malformed_span_id"
    # The first failing id decides.
    assert check_v1_1(_plan(["span-" + "e" * 64], ["span-bad"]), bundle, resolver=resolver, attempt=1).reason_code == "unresolvable"


def test_a_content_hash_that_differs_from_the_bundle_hard_fails():
    bundle = _bundle()
    resolver = SpanResolver(get_course_store())
    span = bundle.spans[0]
    tampered = bundle.model_copy(update={"spans": (span.model_copy(update={"content_hash": "0" * 64}), *bundle.spans[1:])})
    result = check_v1_1(_plan([span.span_id]), tampered, resolver=resolver, attempt=1)
    assert (result.outcome, result.reason_code) == ("hard_fail", "content_hash_mismatch")


def test_a_plan_that_cites_nothing_passes_v1_1_and_v1_2_drops_it():
    bundle = _bundle()
    resolver = SpanResolver(get_course_store())
    assert check_v1_1(_plan([]), bundle, resolver=resolver, attempt=1).reason_code == "resolved"
    assert check_v1_1(ClaimPlan(generator=REF, claims=()), bundle, resolver=resolver, attempt=1).outcome == "pass"


@pytest.mark.parametrize("bad", ["span-" + "f" * 64, "span-xyz", "SPAN-" + "a" * 64])
def test_a_resolved_span_outside_the_bundle_is_v1_2_s_concern_but_a_fake_id_is_v1_1_s(bad):
    bundle = _bundle()
    resolver = SpanResolver(get_course_store())
    outside = next(record.span_id for record in get_course_store().span_registry.records if record.span_id not in {s.span_id for s in bundle.spans})
    assert check_v1_1(_plan([outside]), bundle, resolver=resolver, attempt=1).outcome == "pass"
    assert check_v1_1(_plan([bad]), bundle, resolver=resolver, attempt=1).outcome == "hard_fail"
