"""V1.2, binding and polarity (rule binding-polarity-v1 with quantity-negation-polarity-v1; Phase 4 spec 4.3; E-27, R-16)."""

from __future__ import annotations

from collections import Counter
import re

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.services.span_resolver import SpanResolver
from app.services.store import get_course_store
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline.bind import BindResult, LockedClaimDraft, bind, claim_id_for, whole_sentences
from app.services.tutor_pipeline.contracts import BINDING_FAILURES, ClaimPlan, EvidenceBundle, GeneratorRef, PipelineCounts, PipelineCountsV2, ProposedClaim, Sufficiency
from app.services.tutor_pipeline.retrieve import evidence_span_for
from app.services.v1_checks.lexicon import quantities, quantities_covered
from app.services.v1_checks.v1_2_binding import check_v1_2, polarity_problem

PACKAGE = get_config_package(Settings())
V1 = PACKAGE.v1
PARAMS = PACKAGE.tutor_pipeline
STOP = PACKAGE.retrieval.stopwords
REF = GeneratorRef(generator_id="g", model_id="g", kind="extractive", prompt_hash="1" * 64)


def _store():
    return get_course_store()


def _bundle(records) -> EvidenceBundle:
    store = _store()
    resolver = SpanResolver(store)
    spans = tuple(evidence_span_for(record, resolver.registry, score=5.0, near_floor=False, surface="two_pass") for record in records)
    sufficiency = Sufficiency(score=5.0, gate="bm25f-v1", threshold_version="t", floor=2.35, margin=2.4, decision="answer", reason="evidence")
    return EvidenceBundle(corpus_version=store.corpus_version, index_version=store.index_version, retrieval_mode="lexical", spans=spans, sufficiency=sufficiency)


def _sentences(record):
    return [s.text for s in whole_sentences(record, _store(), min_words=PARAMS.min_sentence_words, max_chars=PARAMS.max_sentence_chars)]


def _record_with(predicate):
    from app.services.contained_answers import span_is_quotable

    store = _store()
    registry = SpanResolver(store).registry
    for record in store.span_registry.records:
        if record.item_kind != "document" or not span_is_quotable(record, registry):
            continue
        for sentence in _sentences(record):
            if predicate(sentence):
                return record, sentence
    raise AssertionError("the dev corpus holds no such sentence")


def _check(plan, bundle, **kwargs):
    store = _store()
    resolver = SpanResolver(store)
    return check_v1_2(plan, bundle, resolver=resolver, store=store, registry=resolver.registry, params=PARAMS, v1=V1, stopwords=STOP, attempt=1, **kwargs)


@pytest.mark.parametrize(
    ("claim", "candidates", "expected"),
    [
        ("Routing adds SWAP gates on sparse hardware.", ["Routing does not add SWAP gates on sparse hardware."], "negation_mismatch"),
        ("Routing does not add SWAP gates on sparse hardware.", ["Routing adds SWAP gates on sparse hardware."], "negation_mismatch"),
        ("The routed circuit uses 5 qubits on the chip.", ["The routed circuit uses 6 qubits on the chip."], "quantity_mismatch"),
        ("The compiled circuit takes 5 ms to run.", ["The compiled circuit takes 5 ns to run."], "quantity_mismatch"),
        ("The compiled circuit is reduced to 5", ["The compiled circuit is reduced to 5 qubits overall."], None),
        ("The device holds 5 noisy qubits today.", ["The device holds 5 noisy qubits today."], None),
        ("Quantum kernels map data into feature spaces.", ["Completely unrelated sentence about bread baking."], None),
    ],
)
def test_the_polarity_table(claim, candidates, expected):
    assert polarity_problem(claim, candidates, v1=V1, stopwords=STOP) == expected


def test_a_non_unit_word_is_never_a_unit_and_a_unit_less_claim_number_matches_any_unit():
    assert quantities("5 noisy qubits", V1.lexicon) == Counter({("5", ""): 1})
    assert quantities("5 qubits and 1,000 shots at 3.5 ms, 40%", V1.lexicon) == Counter({("5", "qubits"): 1, ("1000", ""): 1, ("3.5", "ms"): 1, ("40", "%"): 1})
    assert quantities_covered("reduced to 5", "reduced to 5 qubits", V1.lexicon)
    assert not quantities_covered("reduced to 5 qubits", "reduced to 5 bits", V1.lexicon)
    assert quantities_covered("two layers", "two layers of gates", V1.lexicon)
    assert not quantities_covered("two layers", "three layers", V1.lexicon)


def test_among_equally_aligned_sentences_one_with_matching_polarity_passes():
    claim = "Routing adds SWAP gates on sparse hardware."
    candidates = ["Routing does not add SWAP gates on sparse hardware.", "Routing adds SWAP gates on sparse hardware."]
    assert polarity_problem(claim, candidates, v1=V1, stopwords=STOP) is None


def test_bind_outcomes_equal_the_per_claim_reasons_and_leave_the_binding_unchanged():
    record, sentence = _record_with(lambda s: len(s.split()) >= 6)
    bundle = _bundle([record])
    store = _store()
    resolver = SpanResolver(store)
    plan = ClaimPlan(generator=REF, claims=(
        ProposedClaim(text=sentence, span_ids=(record.span_id,)),
        ProposedClaim(text=sentence, span_ids=(record.span_id,)),
        ProposedClaim(text=sentence, span_ids=("span-" + "e" * 64,)),
        ProposedClaim(text="Bread baking requires flour, water and patience.", span_ids=(record.span_id,)),
        ProposedClaim(text=sentence, span_ids=()),
    ))
    outcomes: list[str] = []
    with_outcomes = bind(plan, bundle, resolver=resolver, store=store, registry=resolver.registry, params=PARAMS, outcomes=outcomes)
    without = bind(plan, bundle, resolver=resolver, store=store, registry=resolver.registry, params=PARAMS)
    assert outcomes == ["bound", "duplicate", "outside_bundle", "not_verbatim", "unbound"]
    assert with_outcomes == without and with_outcomes.dropped == Counter({"duplicate": 1, "outside_bundle": 1, "not_verbatim": 1, "unbound": 1})
    checked = _check(plan, bundle)
    reasons = [result.reason_code for result in checked.results]
    assert reasons == ["bound", "duplicate", "outside_bundle", "not_verbatim", "unbound"]
    locked_id = checked.drafts[0].claim_id
    # A bound or duplicate proposal names the locked claim; a dropped one its own content-addressed id.
    assert [result.claim_id for result in checked.results[:2]] == [locked_id, locked_id]
    assert checked.results[2].claim_id == claim_id_for(sentence, ["span-" + "e" * 64]) != locked_id
    assert [result.outcome for result in checked.results] == ["pass", "pass", "hard_fail", "hard_fail", "hard_fail"]


def test_a_verbatim_claim_always_passes_polarity_and_a_changed_one_is_dropped_with_its_reason():
    record, sentence = _record_with(lambda s: bool(re.search(r"(?<![\w.])\d+", s)) and len(s.split()) >= 6)
    bundle = _bundle([record])
    swapped = re.sub(r"(?<![\w.])(\d+)", lambda m: str(int(m.group(1)) + 1), sentence, count=1)
    checked = _check(ClaimPlan(generator=REF, claims=(ProposedClaim(text=sentence, span_ids=(record.span_id,)),
                                                       ProposedClaim(text=swapped, span_ids=(record.span_id,)))), bundle)
    assert [result.reason_code for result in checked.results] == ["bound", "quantity_mismatch"]
    assert len(checked.drafts) == 1 and not checked.polarity_dropped


def test_a_forced_polarity_drop_is_removed_and_counted_in_pipeline_counts_v2():
    record, sentence = _record_with(lambda s: bool(re.search(r"(?<![\w.])\d+", s)) and len(s.split()) >= 6)
    bundle = _bundle([record])
    swapped = re.sub(r"(?<![\w.])(\d+)", lambda m: str(int(m.group(1)) + 1), sentence, count=1)
    draft = LockedClaimDraft(claim_id=claim_id_for(swapped, [record.span_id]), text=swapped, span_ids=(record.span_id,), source_order=(record.item_id, 0))

    def forced_bind(plan, bundle, *, outcomes, **kwargs):
        outcomes.extend(["bound"])
        return BindResult(bound=(draft,), dropped=Counter(), proposed=1)

    checked = _check(ClaimPlan(generator=REF, claims=(ProposedClaim(text=swapped, span_ids=(record.span_id,)),)), bundle, bind_fn=forced_bind)
    assert checked.drafts == () and checked.polarity_dropped == Counter({"quantity_mismatch": 1})
    assert [result.reason_code for result in checked.results] == ["quantity_mismatch", "no_bound_claims"]
    assert checked.results[-1].outcome == "abstain" and checked.results[-1].claim_id is None
    counts = PipelineCountsV2(proposed_claims=1, bound_claims=0, dropped=dict(checked.dropped), render_attempts=0)
    assert counts.dropped == {"quantity_mismatch": 1}
    with pytest.raises(ValidationError):
        PipelineCounts(proposed_claims=1, bound_claims=0, dropped=dict(checked.dropped), render_attempts=0)
    assert contracts.bound_claim_ratio_terms(counts) == (1, 0)


def test_no_bound_claim_is_a_response_level_abstain():
    record, sentence = _record_with(lambda s: len(s.split()) >= 6)
    checked = _check(ClaimPlan(generator=REF, claims=(ProposedClaim(text="Bread baking requires flour, water and patience.", span_ids=(record.span_id,)),)),
                     _bundle([record]))
    assert checked.drafts == () and checked.results[-1].reason_code == "no_bound_claims"


def test_reason_outcomes_are_total_over_every_binding_failure():
    for code in BINDING_FAILURES:
        assert contracts.REASON_OUTCOMES["V1.2"][code] == "hard_fail"
    for code in ("bound", "merged", "duplicate"):
        assert contracts.REASON_OUTCOMES["V1.2"][code] == "pass"
    assert contracts.REASON_OUTCOMES["V1.2"]["no_bound_claims"] == "abstain"
