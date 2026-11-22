"""Phase 5 evidential cache (plan Phase 5 task 5.7; AC-5-8, AC-5-11; R-47; PD-27; Phase 5 spec 4.15): the key rules, the
per-process cache and the shared DatabaseEvidentialCache."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.gateway.contracts import AdapterVerdict
from app.services.tutor_pipeline.contracts import ClaimPlan, ProposedClaim
from app.services.v2_panel.cache import DatabaseEvidentialCache, ProcessEvidentialCache, claim_plan_key, get_cache, verdict_key
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


def test_the_shared_cache_is_one_cache_for_every_instance_under_keyed_digests():
    # Plan 5.7 "Shared cache", 7.5 "shared verdict cache": two DatabaseEvidentialCache objects are two instances over one
    # table. A key is stored only as a keyed digest, a value as its contract's JSON; a hit refreshes the entry, and a put
    # beyond the kind's bound evicts the least recently used one.
    class Clock:
        now = 100.0

        def __call__(self) -> float:
            self.now += 1.0
            return self.now

    clock = Clock()
    first = DatabaseEvidentialCache(max_plans=2, max_verdicts=2, clock=clock)
    second = DatabaseEvidentialCache(max_plans=2, max_verdicts=2, clock=clock)
    verdict = AdapterVerdict(verdict="NOT_ENOUGH_INFO", ehmf_type="B", span_id=SPAN)
    first.put("verdict", "a", verdict)
    first.put("verdict", "b", verdict)
    assert second.get("verdict", "a") == verdict  # another instance hits, and the hit refreshes "a"
    second.put("verdict", "c", verdict)          # the bound evicts "b", the least recently used
    assert first.get("verdict", "b") is None and first.get("verdict", "c") == verdict
    assert first.keys("verdict") == second.keys("verdict") and len(first.keys("verdict")) == 2
    assert {"a", "b", "c"}.isdisjoint(first.keys("verdict")) and DatabaseEvidentialCache.stored_key("a") in first.keys("verdict")
    assert all(len(key) == 32 and set(key) <= set("0123456789abcdef") for key in first.keys("verdict"))
    assert first.snapshot()["verdict"] == {"hits": 1, "misses": 1, "entries": 2} and second.snapshot()["verdict"]["hits"] == 1
    for kind, value in (("verdict", "rendered text"), ("claim_plan", verdict), ("verdict", {"verdict": "SUPPORTED"}), ("alignment", verdict)):
        with pytest.raises(TypeError):
            first.put(kind, "k", value)
    plan = ClaimPlan(generator=v2_pipeline().generator.ref, claims=(ProposedClaim(text="x", span_ids=(SPAN,)),))
    first.put("claim_plan", "p", plan)
    assert second.get("claim_plan", "p") == plan and second.values("claim_plan") == [plan]
    first.evict("claim_plan", "p")
    assert second.get("claim_plan", "p") is None


def test_the_process_cache_is_the_shared_cache_and_the_seam_empties_it():
    from app.services.v2_panel.cache import reset_process_cache

    cache = get_cache()
    assert isinstance(cache, DatabaseEvidentialCache) and cache._limits == {"claim_plan": 1024, "verdict": 8192}
    cache.put("verdict", "k", AdapterVerdict(verdict="SUPPORTED", ehmf_type=None, span_id=SPAN))
    reset_process_cache()
    assert get_cache() is not cache and get_cache().get("verdict", "k") is None


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


def test_a_shared_cache_whose_store_fails_misses_and_skips_and_never_raises(monkeypatch, caplog):
    # F-1 (plan P): the shared cache is evidential and optional. A database fault makes a get a miss and a put or an evict
    # a no-op (tutor.v2.cache_unavailable, the operation only), so the caller makes the call instead of failing.
    import logging

    from sqlalchemy.exc import OperationalError

    from app.services.v2_panel import cache as cache_module

    verdict = AdapterVerdict(verdict="SUPPORTED", ehmf_type=None, span_id="span-" + "a" * 64)
    shared = DatabaseEvidentialCache()
    shared.put("verdict", "k", verdict)

    def down():
        raise OperationalError("SELECT evidential_cache_entries", {}, Exception("database unavailable"))

    caplog.set_level(logging.WARNING, logger="qcai.tutor")
    monkeypatch.setattr(cache_module, "_engine", down)
    assert shared.get("verdict", "k") is None and shared.misses["verdict"] == 1
    assert shared.put("verdict", "other", verdict) is None and shared.evict("verdict", "k") is None
    with pytest.raises(TypeError):
        shared.put("verdict", "k", "not a verdict")  # a wrong type is still refused: a programming error, not a fault
    events = [record.json_fields for record in caplog.records if getattr(record, "json_fields", {}).get("event") == "tutor.v2.cache_unavailable"]
    assert [event["operation"] for event in events] == ["get", "put", "evict"]
    monkeypatch.undo()
    assert shared.get("verdict", "k") == verdict and shared.get("verdict", "other") is None  # nothing was evicted or written
