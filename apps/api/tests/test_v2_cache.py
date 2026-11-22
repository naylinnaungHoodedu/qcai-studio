"""Phase 5 evidential cache (plan Phase 5 task 5.7; AC-5-8, AC-5-11; R-47; PD-27; Phase 5 spec 4.15)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.gateway.contracts import AdapterVerdict
from app.services.tutor_pipeline.contracts import ClaimPlan, ProposedClaim
from app.services.v2_panel.cache import ProcessEvidentialCache, claim_plan_key, verdict_key
from v1_fakes import MULTI_CLAIM, run
from v2_fakes import adapters_of, fake_spec, fresh_gateway, make_registry, v2_pipeline

SPAN = "span-" + "a" * 64
TIER2 = "Why do the sources repeatedly emphasize hybrid loops instead of end-to-end quantum models?"


def _verdict_inputs(**overrides):
    package = SimpleNamespace(package_version="4.0.0", sha256="1" * 64)
    generator = SimpleNamespace(generator_id="extractive-d19-v1", model_id="extractive-d19-v1", prompt_hash="2" * 64)
    inputs = dict(claim_text="A claim.", span_id=SPAN, span_content_hash="3" * 64, spec=fake_spec("fake-alpha"), verifier_prompt_hash="4" * 64,
                  tool_contract_version="mcp-tools-v1", resolved_question_sha256="5" * 64, corpus_version="c1", package=package,
                  generator_ref=generator)
    inputs.update(overrides)
    return inputs


def test_every_verdict_key_field_changes_the_key():
    base = verdict_key(**_verdict_inputs())
    variants = {
        "claim_text": "Another claim.", "span_id": "span-" + "b" * 64, "span_content_hash": "6" * 64,
        "spec": fake_spec("fake-alpha", model_version="2026-12-01"), "verifier_prompt_hash": "7" * 64, "tool_contract_version": "mcp-tools-v2",
        "resolved_question_sha256": "8" * 64, "corpus_version": "c2",
        "package": SimpleNamespace(package_version="4.0.1", sha256="1" * 64),
        "generator_ref": SimpleNamespace(generator_id="other", model_id="extractive-d19-v1", prompt_hash="2" * 64),
    }
    keys = {name: verdict_key(**_verdict_inputs(**{name: value})) for name, value in variants.items()}
    keys["config_package_sha256"] = verdict_key(**_verdict_inputs(package=SimpleNamespace(package_version="4.0.0", sha256="9" * 64)))
    keys["verifier_adapter_id"] = verdict_key(**_verdict_inputs(spec=fake_spec("fake-alpha", adapter_id="fake-alpha-2")))
    keys["verifier_model_id"] = verdict_key(**_verdict_inputs(spec=fake_spec("fake-alpha", model_id="another-model")))
    assert base not in keys.values() and len(set(keys.values())) == len(keys)
    assert len(base) == 64 and set(base) <= set("0123456789abcdef")


def test_the_claim_plan_key_holds_the_envelope_so_another_lesson_scope_misses():
    pipeline = v2_pipeline()
    first = run(pipeline, MULTI_CLAIM)
    scoped = next(result for slug in pipeline.store.lessons
                  if (result := run(pipeline, MULTI_CLAIM, lesson_slug=slug)).envelope is not None and result.envelope != first.envelope)
    assert scoped.envelope.question == first.envelope.question  # the same resolved text, another lesson scope's evidence
    keys = {claim_plan_key(result.envelope, pipeline.package, pipeline.generator.ref) for result in (first, scoped)}
    assert len(keys) == 2


def test_hits_bounds_and_types():
    cache = ProcessEvidentialCache(max_plans=2, max_verdicts=2)
    verdict = AdapterVerdict(verdict="SUPPORTED", ehmf_type=None, span_id=SPAN)
    for key in ("a", "b", "c"):
        cache.put("verdict", key, verdict)
    assert cache.get("verdict", "a") is None and cache.get("verdict", "c") == verdict and cache.keys("verdict") == ["b", "c"]
    assert cache.snapshot()["verdict"] == {"hits": 1, "misses": 1, "entries": 2}
    for kind, value in (("verdict", "rendered text"), ("claim_plan", verdict), ("verdict", {"verdict": "SUPPORTED"}), ("alignment", verdict)):
        with pytest.raises(TypeError):
            cache.put(kind, "k", value)
    plan = ClaimPlan(generator=v2_pipeline().generator.ref, claims=(ProposedClaim(text="x", span_ids=(SPAN,)),))
    cache.put("claim_plan", "p", plan)
    assert cache.get("claim_plan", "p") == plan


def test_generation_1_reads_the_cache_and_a_cached_plan_that_hard_fails_v1_1_is_evicted():
    pipeline = v2_pipeline()
    calls = []
    original = pipeline.generator.propose
    pipeline.generator.propose = lambda envelope: calls.append(1) or original(envelope)
    first = run(pipeline, MULTI_CLAIM)
    key = claim_plan_key(first.envelope, pipeline.package, pipeline.generator.ref)
    assert pipeline.cache.get("claim_plan", key) is not None and len(calls) == 1
    run(pipeline, MULTI_CLAIM)
    assert len(calls) == 1  # generation 1 came from the cache
    forged = ClaimPlan(generator=pipeline.generator.ref, claims=(ProposedClaim(text="A claim.", span_ids=("span-" + "e" * 64,)),))
    pipeline.cache.put("claim_plan", key, forged)
    result = run(pipeline, MULTI_CLAIM)
    assert pipeline.cache.get("claim_plan", key) is None  # evicted, and the regeneration bypasses the cache
    assert result.entry.verification.generation_attempts == 2 and len(calls) == 2


def test_no_learner_data_is_a_key_or_a_value():
    registry = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    pipeline = v2_pipeline(Settings(model_gateway="on"), gateway=fresh_gateway(adapters=adapters_of(registry)), registry=registry)
    result = run(pipeline, TIER2)
    cache = pipeline.cache
    for kind, value_type in (("claim_plan", ClaimPlan), ("verdict", AdapterVerdict)):
        assert cache.keys(kind) and all(len(key) == 64 and set(key) <= set("0123456789abcdef") for key in cache.keys(kind))
        assert all(isinstance(value, value_type) for value in cache.values(kind))
    dumped = repr(cache.values("verdict")) + repr(cache.values("claim_plan"))
    assert TIER2 not in dumped and result.rendered.text not in dumped
    assert result.entry.response_id not in dumped and result.entry.shadowed_response_id not in dumped
