"""Retrieve, bind and lock (plan tasks 3.2-3.5; R-11, R-13; Phase 3 spec 4.3-4.7, 13.2)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import unicodedata

import pytest

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.core.corpus_governance import get_corpus_registry
from app.schemas import SearchResult
from app.services import retrieval_metrics
from app.services.contained_answers import contain_answer, span_is_quotable
from app.services.content_assembler import CourseStore
from app.services.provenance import native_citation
from app.services.retrieval_engine import RetrievalEngine
from app.services.span_resolver import SpanResolver
from app.services.store import get_course_store
from app.services.tutor_pipeline.bind import bind, claim_id_for
from app.services.tutor_pipeline.contracts import (
    ClaimPlan,
    EvidenceBundle,
    EvidenceSpan,
    GeneratorRef,
    ProposedClaim,
    ResolvedQuestion,
    ResolverRef,
    RetrievalRequest,
)
from app.services.tutor_pipeline.lock import lock
from app.services.tutor_pipeline.render import pedagogical_prompt_hash
from app.services.tutor_pipeline.retrieve import build_request, retrieve
from app.services.tutor_pipeline.text import normalise, sentences, whitespace

DATA = Path(__file__).parent / "data"
REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE = get_config_package(Settings())
PARAMS = PACKAGE.tutor_pipeline
REF = GeneratorRef(generator_id="scripted-test", model_id="scripted-test", kind="generative", prompt_hash="1" * 64)
RESOLVER = ResolverRef(model_id="thread-resolver-v1", prompt_hash=PARAMS.resolver_prompt_hash)


def _sentences(record) -> list[str]:
    return sentences(record.text, min_words=PARAMS.min_sentence_words, max_chars=PARAMS.max_sentence_chars)


def _span(record, *, score: float | None = 5.0, quotable: bool = True) -> EvidenceSpan:
    return EvidenceSpan(span_id=record.span_id, item_id=record.item_id, item_version=record.item_version, kind=record.item_kind,
                        char_start=record.start, char_end=record.end, content_hash=record.content_hash, score=score, near_floor=False,
                        license_class="public", quotable=quotable)


def _bundle(store, spans) -> EvidenceBundle:
    from app.services.tutor_pipeline.contracts import Sufficiency

    floor, margin, version = store.index.thresholds
    return EvidenceBundle(corpus_version=store.corpus_version, index_version=store.index_version, retrieval_mode="lexical", spans=tuple(spans),
                          sufficiency=Sufficiency(score=5.0, gate=store.gate, threshold_version=version, floor=floor, margin=margin,
                                                  decision="answer", reason="evidence"))


def test_the_retrieval_request_is_exactly_text_lesson_scope_and_corpus_version():
    resolved = ResolvedQuestion(text="Why does routing depth matter?", resolver=RESOLVER, source_turn_ids=("m1",))
    request = build_request(resolved, lesson_slug="ai4qc-routing-and-optimization", corpus_version="corpus-x")
    assert request.model_dump() == {"text": "Why does routing depth matter?", "lesson_slug": "ai4qc-routing-and-optimization", "corpus_version": "corpus-x"}


def test_a_corpus_version_mismatch_abstains_with_no_spans():
    store = get_course_store()
    engine = RetrievalEngine(store, Settings())
    bundle = retrieve(engine, RetrievalRequest(text="Why does routing depth matter?", corpus_version="corpus-stale"), top_k=4,
                      registry=get_corpus_registry(Settings()))
    assert (bundle.sufficiency.decision, bundle.sufficiency.reason, bundle.spans) == ("abstain", "corpus_version_mismatch", ())


def test_sufficiency_abstains_on_no_result_marks_near_miss_from_the_gates_flag_and_answers_otherwise():
    store = get_course_store()  # development: bm25f-v1, whose margin marks near_floor results
    assert store.gate == "bm25f-v1"
    engine = RetrievalEngine(store, Settings())
    registry = get_corpus_registry(Settings())
    off = retrieve(engine, RetrievalRequest(text="What is the capital of France?", corpus_version=store.corpus_version), top_k=4, registry=registry)
    assert off.sufficiency.decision == "abstain" and off.spans == () and off.sufficiency.reason != "evidence"
    fixture = json.loads((DATA / "score_floor_queries.json").read_text(encoding="utf-8"))
    calibration = json.loads((DATA / "phase2_calibration_queries.json").read_text(encoding="utf-8"))
    queries = [item["query"] for item in fixture["in_domain"]]
    queries += [item["query"] for group in calibration.values() if isinstance(group, list) for item in group if isinstance(item, dict) and "query" in item]
    seen = {"answer": 0, "near_miss": 0}
    for query in queries:
        response = engine.evidence(query, top_k=4)
        if not response.results:
            continue
        bundle = retrieve(engine, RetrievalRequest(text=query, corpus_version=store.corpus_version), top_k=4, registry=registry)
        expected = "near_miss" if response.results[0].near_floor else "answer"
        assert bundle.sufficiency.decision == expected, query
        assert bundle.sufficiency.score == response.results[0].score
        seen[expected] += 1
    assert seen["answer"] > 100 and seen["near_miss"] >= 1, seen


def test_every_bind_drop_reason_and_no_rebinding():
    store = get_course_store()
    resolver = SpanResolver(store)
    registry = resolver.registry
    documents = [record for record in store.span_registry.records if record.item_kind == "document" and len(_sentences(record)) >= 2]
    a, b = documents[0], next(record for record in documents if record.item_id != documents[0].item_id)
    authored = next(record for record in store.span_registry.records if record.item_kind == "authored" and _sentences(record))
    outside = next(record for record in documents if record.span_id not in {a.span_id, b.span_id} and _sentences(record))
    bundle = _bundle(store, [_span(a), _span(b), _span(authored, quotable=False)])
    a_sentence, b_sentence = _sentences(a)[0], _sentences(b)[0]
    clause = next((sentence for record in documents for sentence in _sentences(record) if ", " in sentence and record.span_id == a.span_id), None)
    if clause is None:  # take a document span of the bundle with a qualifying clause
        a = next(record for record in documents if any(", " in sentence for sentence in _sentences(record)))
        bundle = _bundle(store, [_span(a), _span(b), _span(authored, quotable=False)])
        a_sentence = _sentences(a)[0]
        clause = next(sentence for sentence in _sentences(a) if ", " in sentence)
    truncated = clause.split(", ")[0] + "."
    plan = ClaimPlan(generator=REF, claims=(
        ProposedClaim(text=a_sentence, span_ids=(a.span_id,)),  # binds
        ProposedClaim(text=a_sentence, span_ids=()),  # unbound
        ProposedClaim(text=_sentences(outside)[0], span_ids=(outside.span_id,)),  # outside the bundle
        ProposedClaim(text=_sentences(authored)[0], span_ids=(authored.span_id,)),  # authored, never quotable (D-19)
        ProposedClaim(text=a_sentence, span_ids=(b.span_id,)),  # A's sentence citing B: dropped, never rebound to A
        ProposedClaim(text=truncated, span_ids=(a.span_id,)),  # a qualifying clause removed
        ProposedClaim(text="Quantum annealers always outperform classical solvers.", span_ids=(a.span_id,)),  # invented
        ProposedClaim(text=a_sentence, span_ids=(a.span_id, b.span_id)),  # cross-span: not a sentence of B
        ProposedClaim(text=b_sentence, span_ids=(b.span_id,)),  # binds
        ProposedClaim(text="  " + a_sentence.replace(" ", "  ") + " ", span_ids=(a.span_id,)),  # the same claim again
    ))
    result = bind(plan, bundle, resolver=resolver, store=store, registry=registry, params=PARAMS)
    assert [draft.text for draft in result.bound] == [a_sentence, b_sentence]
    assert [draft.span_ids for draft in result.bound] == [(a.span_id,), (b.span_id,)]
    assert dict(result.dropped) == {"unbound": 1, "outside_bundle": 1, "not_quotable": 1, "not_verbatim": 4, "duplicate": 1}
    assert result.proposed == len(plan.claims)
    forged = bundle.model_copy(update={"spans": (bundle.spans[0].model_copy(update={"content_hash": "f" * 64}), *bundle.spans[1:])})
    forged_result = bind(ClaimPlan(generator=REF, claims=(ProposedClaim(text=a_sentence, span_ids=(a.span_id,)),)), forged,
                         resolver=resolver, store=store, registry=registry, params=PARAMS)
    assert dict(forged_result.dropped) == {"unresolvable": 1} and forged_result.bound == ()


def test_claim_text_stays_verbatim_and_claim_ids_are_content_addressed():
    store = get_course_store()
    resolver = SpanResolver(store)
    record, sentence = _nfkc_changing(store)
    plan = ClaimPlan(generator=REF, claims=(ProposedClaim(text=sentence, span_ids=(record.span_id,)),))
    result = bind(plan, _bundle(store, [_span(record)]), resolver=resolver, store=store, registry=resolver.registry, params=PARAMS)
    assert [draft.text for draft in result.bound] == [whitespace(sentence)]  # verbatim, not NFKC-folded
    assert result.bound[0].text != normalise(sentence)
    assert result.bound[0].claim_id == claim_id_for(sentence, [record.span_id]) == claim_id_for("  " + sentence, (record.span_id,))
    assert claim_id_for(sentence, [record.span_id]) != claim_id_for(sentence + " More.", [record.span_id])


def _nfkc_changing(store) -> tuple:
    changing = [
        (record, sentence)
        for record in store.span_registry.records
        if record.item_kind == "document"
        for sentence in _sentences(record)
        if unicodedata.normalize("NFKC", sentence) != sentence
    ]
    assert changing, "the dev corpus has a sentence NFKC would change (spec M22)"
    return changing[0]


def test_a_folded_claim_binds_to_the_spans_own_text_and_a_folded_rendering_is_unmapped():
    # Review 2026-11-19: NFKC is used only to compare. A generator that folds a character still binds, but what is
    # locked, ledgered and rendered is the span's own text; a renderer that folds it changes what a learner reads.
    from app.services.claim_gate import check_subset
    from app.services.tutor_pipeline.contracts import PresentationPlan
    from app.services.tutor_pipeline.render import TemplateRenderer, layout_text

    store = get_course_store()
    resolver = SpanResolver(store)
    record, sentence = _nfkc_changing(store)
    folded = unicodedata.normalize("NFKC", sentence)
    bundle = _bundle(store, [_span(record)])
    result = bind(ClaimPlan(generator=REF, claims=(ProposedClaim(text=folded, span_ids=(record.span_id,)),)), bundle, resolver=resolver,
                  store=store, registry=resolver.registry, params=PARAMS)
    assert [draft.text for draft in result.bound] == [whitespace(sentence)] and dict(result.dropped) == {}
    assert result.bound[0].text != folded and result.bound[0].text in whitespace(record.text)
    locked = lock(result.bound, bundle=bundle, generator=REF, evidential_prompt_hash=REF.prompt_hash, pedagogical_prompt_hash=pedagogical_prompt_hash(),
                  resolver=RESOLVER, package=PACKAGE)
    assert locked.claims[0].text == whitespace(sentence)
    rendered = TemplateRenderer().render(locked, PresentationPlan(plan_id="concise", source="request"), attempt=1)
    assert whitespace(sentence) in rendered.text and folded not in rendered.text and check_subset(rendered, locked).passed
    segments = [segment.model_copy(update={"text": unicodedata.normalize("NFKC", segment.text)}) if segment.kind == "claim" else segment
                for segment in rendered.segments]
    altered = rendered.model_copy(update={"segments": tuple(segments), "text": layout_text(segments)})
    assert altered.text != rendered.text
    checked = check_subset(altered, locked)
    assert not checked.passed and "unmapped_factual_sentence" in checked.problems


def _shared_sentence(store) -> tuple:
    """A document sentence that sits in two adjacent spans (the splitter overlaps chunks), with both spans."""
    holders: dict[str, list] = {}
    registry = get_corpus_registry(Settings())
    for record in store.span_registry.records:
        if record.item_kind != "document" or not span_is_quotable(record, registry):
            continue
        for sentence in _sentences(record):
            holders.setdefault(normalise(sentence), []).append((record, sentence))
    for entries in holders.values():
        spans = {record.span_id: (record, sentence) for record, sentence in entries}
        if len(spans) >= 2:
            (a, sentence), (b, _) = list(spans.values())[:2]
            return a, b, sentence
    raise AssertionError("the dev corpus has a sentence in two overlapping spans (review 2026-11-19)")


def test_a_sentence_proposed_on_two_overlapping_spans_is_one_locked_claim_on_both():
    # Review 2026-11-19: the extractive generator proposes such a sentence once per span. Both used to lock as two
    # claims with one text, and the subset check, keyed on text, then rejected the honest rendering.
    store = get_course_store()
    resolver = SpanResolver(store)
    a, b, sentence = _shared_sentence(store)
    both = tuple(sorted((a.span_id, b.span_id)))
    other = next((s for s in _sentences(a) if normalise(s) != normalise(sentence)), None)
    proposals = [
        ProposedClaim(text=sentence, span_ids=(a.span_id,)),
        ProposedClaim(text=sentence, span_ids=(b.span_id,)),  # merged: its span joins the first claim
        ProposedClaim(text=sentence, span_ids=(a.span_id,)),  # already bound on these spans: a duplicate
        ProposedClaim(text=sentence, span_ids=both),  # likewise
    ]
    if other is not None:
        proposals.append(ProposedClaim(text=other, span_ids=(a.span_id,)))
    result = bind(ClaimPlan(generator=REF, claims=tuple(proposals)), _bundle(store, [_span(a), _span(b)]), resolver=resolver, store=store,
                  registry=resolver.registry, params=PARAMS)
    assert result.bound[0].text == whitespace(sentence) and result.bound[0].span_ids == both
    assert result.bound[0].claim_id == claim_id_for(sentence, both)
    assert [draft.text for draft in result.bound[1:]] == ([whitespace(other)] if other is not None else [])
    assert dict(result.dropped) == {"merged": 1, "duplicate": 2}
    assert result.proposed == len(result.bound) + sum(result.dropped.values()) == len(proposals)


def test_the_lock_hash_is_stable_and_stamped():
    store = get_course_store()
    resolver = SpanResolver(store)
    record = next(r for r in store.span_registry.records if r.item_kind == "document" and _sentences(r))
    bundle = _bundle(store, [_span(record)])
    drafts = bind(ClaimPlan(generator=REF, claims=(ProposedClaim(text=_sentences(record)[0], span_ids=(record.span_id,)),)), bundle,
                  resolver=resolver, store=store, registry=resolver.registry, params=PARAMS).bound
    first = lock(drafts, bundle=bundle, generator=REF, evidential_prompt_hash=REF.prompt_hash, pedagogical_prompt_hash=pedagogical_prompt_hash(),
                 resolver=RESOLVER, package=PACKAGE)
    again = lock(drafts, bundle=bundle, generator=REF, evidential_prompt_hash=REF.prompt_hash, pedagogical_prompt_hash=pedagogical_prompt_hash(),
                 resolver=RESOLVER, package=PACKAGE)
    assert first == again and first.claim_set_hash == again.claim_set_hash
    assert (first.corpus_version, first.index_version, first.config_package.version) == (store.corpus_version, store.index_version, "2.0.0")
    assert first.claims[0].source_order == (record.item_id, record.start)
    other = lock(drafts, bundle=bundle, generator=REF, evidential_prompt_hash=REF.prompt_hash, pedagogical_prompt_hash=pedagogical_prompt_hash(),
                 resolver=ResolverRef(model_id="thread-resolver-v1", prompt_hash="9" * 64), package=PACKAGE)
    assert other.claim_set_hash != first.claim_set_hash
    assert pedagogical_prompt_hash() == PARAMS.pedagogical_prompt_hash


@pytest.mark.parametrize("config", ["dev", "governed_empty"])
def test_span_is_quotable_equals_the_contained_answer_decision_for_every_span(config):
    if config == "dev":
        settings, store = Settings(), get_course_store()
    else:
        settings = Settings(environment="production", enforce_corpus_governance=True,
                            corpus_manifest_path=str(REPO_ROOT / "corpus" / "public" / "manifest.json"))
        store = CourseStore(settings)
    registry = get_corpus_registry(settings)
    quotable = 0
    for record in store.span_registry.records:
        result = SearchResult(chunk_id=record.span_id, title=record.section_title, source_kind="lesson" if record.item_kind == "authored" else "document",
                              source_title=record.source_title, excerpt=record.text[:320], score=5.0, source_filename=record.source_filename,
                              span_id=record.span_id, item_id=record.item_id, item_version=record.item_version, start=record.start, end=record.end,
                              content_hash=record.content_hash)
        contained = contain_answer([native_citation(result, corpus_version=store.corpus_version, settings=settings)], registry, store.span_registry,
                                   settings=settings)
        assert span_is_quotable(record, registry) == (contained.decision == "answer"), record.span_id
        quotable += span_is_quotable(record, registry)
    assert quotable > 900 if config == "dev" else quotable == 0  # D-31: nothing is quotable in the governed build


def test_evidence_is_the_lexical_search_never_semantic_and_records_no_sli():
    store = get_course_store()
    lexical = RetrievalEngine(store, Settings())
    calls: list[str] = []
    switched = Settings(semantic_retrieval_enabled=True, openai_api_key="test-key", pinecone_api_key="test-key", pinecone_index="test-index")
    hybrid = RetrievalEngine(store, switched)
    hybrid._semantic_backend = SimpleNamespace(enabled=True, aligned=True, search=lambda *args, **kwargs: calls.append("semantic") or [])
    assert hybrid.semantic_enabled is True
    for query in ("Why does routing depth matter?", "QUBO logistics", "What is the capital of France?", "quantum kernels for finance"):
        before = retrieval_metrics.snapshot()["abstention"]["decisions"]
        evidence = hybrid.evidence(query, top_k=4)
        assert retrieval_metrics.snapshot()["abstention"]["decisions"] == before  # no Phase 2 SLI from the shadow
        assert calls == []  # never the embeddings provider (spec conflict 33)
        search = lexical.search(query, top_k=4)
        assert evidence.mode == "lexical" and search.mode == "lexical"
        assert [(r.span_id, r.score, r.near_floor) for r in evidence.results] == [(r.span_id, r.score, r.near_floor) for r in search.results]
        assert (evidence.abstained, evidence.reason, evidence.gate, evidence.floor, evidence.margin) == (
            search.abstained, search.reason, search.gate, search.floor, search.margin)
    hybrid.search("Why does routing depth matter?", top_k=4)
    assert calls == ["semantic"]  # control: the hybrid search itself does call it
