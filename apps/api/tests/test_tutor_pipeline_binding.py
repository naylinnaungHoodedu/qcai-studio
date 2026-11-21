"""Phase 3: the two-pass pipeline's sentence rule, binding and envelope (plan tasks 3.3-3.5; R-11, R-13; Phase 3 spec
4.4-4.7).

C10 sentences-v2 keeps abbreviations, initials and numbers inside their sentence, and the package names the rule.
H1  binding locks only whole document sentences: a span-edge fragment of a longer sentence never binds
    (partial_sentence), the envelope carries only whole sentences, and every locked claim of the public replay is a
    sentences-v2 sentence of its document section lying wholly inside each span it cites.
H2  the stepwise plan's "in source order" holds for two sentences of one span (source_order is the sentence's place).
I1  an empty evidential envelope says why: no_quotable_evidence when no bundle span is quotable, no_whole_sentence when
    the quotable spans hold no whole document sentence; a record never says no_quotable_evidence beside quotable spans.
J1  a duplicate claim (its sentence already bound on every span it cites) counts as bound in the plan L ratio, as a
    merged claim does, so two claim plans that lock one claim set give one ratio whatever their order.
Each test fails if its defect comes back; the spec's review history (18.4) names the round behind each group.
"""

from __future__ import annotations

from collections import Counter
import dataclasses
from functools import lru_cache
import json
from pathlib import Path
import re
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.services.contained_answers import span_is_quotable
from app.services.retrieval_engine import RetrievalEngine
from app.services.span_resolver import SpanResolver
from app.services.store import get_course_store
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline import pipeline as pipeline_module
from app.services.tutor_pipeline.bind import bind, claim_id_for, whole_sentence_text, whole_sentences
from app.services.tutor_pipeline.contracts import (
    NO_QUOTABLE_EVIDENCE,
    NO_WHOLE_SENTENCE,
    ClaimPlan,
    EvidenceBundle,
    EvidenceSpan,
    GeneratorRef,
    PresentationPlan,
    ProposedClaim,
    ResolverRef,
    Sufficiency,
    bound_claim_ratio_terms,
)
from app.services.tutor_pipeline.evidential import ExtractiveD19Generator, build_envelope, no_envelope_reason
from app.services.tutor_pipeline.lock import lock
from app.services.tutor_pipeline.metrics import TwoPassMetrics
from app.services.tutor_pipeline.package_check import check_tutor_pipeline_package
from app.services.tutor_pipeline.pipeline import PipelineInput, TwoPassPipeline
from app.services.tutor_pipeline.render import TEMPLATES, TemplateRenderer
from app.services.tutor_pipeline.resolve import LearnerTurn, resolve_turns
from app.services.tutor_pipeline.retrieve import build_request
from app.services.tutor_pipeline.text import SENTENCE_RULE, content_terms, sentence_bounds, sentences, split_sentences, whitespace

from tutor_fakes import ScriptedGenerator


PACKAGE = get_config_package(Settings())
PARAMS = PACKAGE.tutor_pipeline
DATA = Path(__file__).parent / "data"
IN_DOMAIN = [item["query"] for item in json.loads((DATA / "score_floor_queries.json").read_text(encoding="utf-8"))["in_domain"]]
REF = GeneratorRef(generator_id="scripted-test", model_id="scripted-test", kind="generative", prompt_hash="1" * 64)
RESOLVER = ResolverRef(model_id="thread-resolver-v1", prompt_hash=PARAMS.resolver_prompt_hash)
WORDS = {"min_words": PARAMS.min_sentence_words, "max_chars": PARAMS.max_sentence_chars}
# A query whose two-pass answer locks several claims on several spans (spec 18.10 H1, 18.11 I2).
MULTI_CLAIM = "Explain why quantum logistics needs both problem reduction before execution and routing control during compilation."
API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
# The regression query (apps/api/tests/data/phase3_replay_regressions.json) whose answer locks a sentence that two
# overlapping spans both hold: one claim citing two spans (spec 18.4).
TWO_SPAN = "How should the trained model be evaluated on a physical QPU against classical baselines?"


def _section(store, record):
    return next(section for section in store.items[record.item_id].sections if section.ordinal == record.section_ordinal)


def _span(record, *, quotable: bool = True) -> EvidenceSpan:
    return EvidenceSpan(span_id=record.span_id, item_id=record.item_id, item_version=record.item_version, kind=record.item_kind,
                        char_start=record.start, char_end=record.end, content_hash=record.content_hash, score=5.0, near_floor=False,
                        license_class="public", quotable=quotable)


def _bundle(store, records, *, quotable: bool = True) -> EvidenceBundle:
    floor, margin, version = store.index.thresholds
    return EvidenceBundle(corpus_version=store.corpus_version, index_version=store.index_version, retrieval_mode="lexical",
                          spans=tuple(_span(record, quotable=quotable) for record in records),
                          sufficiency=Sufficiency(score=5.0, gate=store.gate, threshold_version=version, floor=floor, margin=margin,
                                                  decision="answer", reason="evidence"))


def _edge_fragments(store):
    """(record, piece, edge) for each quotable document span whose first or last piece of its own text, cut under
    sentences-v2, is not a sentence of its section: the span starts or ends inside a longer document sentence."""
    registry = SpanResolver(store).registry
    from app.services.contained_answers import span_is_quotable

    found = []
    for record in store.span_registry.records:
        if record.item_kind != "document" or not span_is_quotable(record, registry):
            continue
        section_sentences = set(split_sentences(_section(store, record).body))
        pieces = split_sentences(record.text)
        for piece, edge in ((pieces[0], "start"), (pieces[-1], "end")):
            if piece not in section_sentences and sentences(piece, **WORDS) == [piece]:
                found.append((record, piece, edge))
    return found


@lru_cache(maxsize=1)
def _replay():
    """The two-pass pipeline over the public in-domain fixture (development store, bm25f-v1), stepwise plan: the same
    run the committed replay record makes for that configuration, minus its other plans (the lock precedes them)."""
    settings = Settings()
    store = get_course_store()
    pipeline = TwoPassPipeline(RetrievalEngine(store, settings), settings)
    results = []
    for index, query in enumerate(IN_DOMAIN):
        resolved = resolve_turns([], LearnerTurn(f"h1-{index}", query), package=pipeline.package)
        results.append((query, pipeline.run(PipelineInput(resolved=resolved, lesson_slug=None, presentation=PresentationPlan(plan_id="stepwise", source="request"),
                                                          response_id=f"shadow-{uuid4()}", delivery="shadow", shadowed_response_id=f"turn-{uuid4()}"),
                                            record=False)))
    return store, results


def _whole(store, record):
    return whole_sentences(record, store, **WORDS)


def _run(pipeline: TwoPassPipeline, query: str, plan_id: str = "concise"):
    resolved = resolve_turns([], LearnerTurn(f"message-{uuid4()}", query), package=pipeline.package)
    return pipeline.run(PipelineInput(resolved=resolved, lesson_slug=None, presentation=PresentationPlan(plan_id=plan_id, source="request"),
                                      response_id=f"shadow-{uuid4()}", delivery="shadow", shadowed_response_id=f"turn-{uuid4()}"), record=False)


def _quotable_documents(store):
    registry = SpanResolver(store).registry
    return [record for record in store.span_registry.records if record.item_kind == "document" and span_is_quotable(record, registry)]


def _load_replay():
    import importlib.util

    spec = importlib.util.spec_from_file_location("phase3_review9_replay", REPO_ROOT / "scripts" / "replay_tutor_plans.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ============================================================================================================== C10


@pytest.mark.parametrize("text, expected", [
    ("Hybrid solvers help on hard instances, e.g. vehicle routing with time windows. They also scale.",
     ["Hybrid solvers help on hard instances, e.g. vehicle routing with time windows.", "They also scale."]),
    ("A kernel is a similarity measure, i.e. an inner product in feature space. It is learned.",
     ["A kernel is a similarity measure, i.e. an inner product in feature space.", "It is learned."]),
    ("Tesi et al. explicitly target jet images from CMS Open Data. The model is hybrid.",
     ["Tesi et al. explicitly target jet images from CMS Open Data.", "The model is hybrid."]),
    ("As shown in Fig. 3 the error falls with depth. The next figure differs.",
     ["As shown in Fig. 3 the error falls with depth.", "The next figure differs."]),
    ("The update follows Eq. (2) and converges quickly. We stop there.", ["The update follows Eq. (2) and converges quickly.", "We stop there."]),
    ("Sec. 4 describes the routing heuristic in detail. It is greedy.", ["Sec. 4 describes the routing heuristic in detail.", "It is greedy."]),
    ("Quantum vs. classical baselines were compared on one dataset. Both converged.",
     ["Quantum vs. classical baselines were compared on one dataset.", "Both converged."]),
    ("Dr. Preskill coined the term NISQ for these devices. It stuck.", ["Dr. Preskill coined the term NISQ for these devices.", "It stuck."]),
    ("This follows J. Preskill closely in spirit. Others disagree.", ["This follows J. Preskill closely in spirit.", "Others disagree."]),
    ("Schuld, M., & Petruccione, F. (2021). Machine learning with quantum computers.",
     ["Schuld, M., & Petruccione, F. (2021).", "Machine learning with quantum computers."]),
    ("The gate fidelity reached 99.5 percent on average. Errors remain.", ["The gate fidelity reached 99.5 percent on average.", "Errors remain."]),
    ("Install version 1.2.3 of the toolkit before running. Then rerun it.", ["Install version 1.2.3 of the toolkit before running.", "Then rerun it."]),
    ("Python 3.11 is required by this module. Earlier releases fail.", ["Python 3.11 is required by this module.", "Earlier releases fail."]),
    ("Routing uses approx. ten swaps per layer here. That is cheap.", ["Routing uses approx. ten swaps per layer here.", "That is cheap."]),
    # Real boundaries still split.
    ("The circuit is deep. The noise grows.", ["The circuit is deep.", "The noise grows."]),
    ("Is it fast? Yes, on small inputs.", ["Is it fast?", "Yes, on small inputs."]),
    ("It works! Then it stops.", ["It works!", "Then it stops."]),
    ("Routing ends at step 3. Then mapping starts.", ["Routing ends at step 3.", "Then mapping starts."]),
    ("Gates, measurements, etc. The rest follows.", ["Gates, measurements, etc.", "The rest follows."]),
])
def test_c10_sentences_v2_keeps_abbreviations_initials_and_numbers_inside_their_sentence(text, expected):
    assert split_sentences(text) == expected


ABBREVIATION_ENDINGS = ("e.g.", "i.e.", "et al.", "Fig.", "Figs.", "Eq.", "Eqs.", "Sec.", "vs.", "Dr.", "Prof.", "cf.", "approx.")


def test_c10_no_dev_corpus_sentence_ends_at_an_abbreviation_any_more():
    def cut_at_abbreviation(parts: list[str]) -> int:
        return sum(1 for part in parts if part.endswith(ABBREVIATION_ENDINGS))

    documents = [record for record in get_course_store().span_registry.records if record.item_kind == "document"]
    # sentences-v1 cut after every ". " (the rule this one replaced).
    old_rule = sum(cut_at_abbreviation([part for part in re.split(r"(?<=[.!?])\s+", " ".join(r.text.split())) if part]) for r in documents)
    assert old_rule > 0  # the corpus does hold such sentences, so this test can fail
    assert sum(cut_at_abbreviation(split_sentences(r.text)) for r in documents) == 0


def test_c10_the_package_names_the_codes_sentence_rule_and_a_mismatch_is_a_package_problem():
    assert SENTENCE_RULE == PARAMS.sentence_rule == "sentences-v2"
    assert check_tutor_pipeline_package(PACKAGE, structural=False) == []
    stale = dataclasses.replace(PACKAGE, tutor_pipeline=dataclasses.replace(PARAMS, sentence_rule="sentences-v1"))
    assert any("sentence_rule" in problem for problem in check_tutor_pipeline_package(stale, structural=False))
    assert sentences("Short. A sentence of enough words here.", min_words=4, max_chars=PARAMS.max_sentence_chars) == ["A sentence of enough words here."]


# =============================================================================================================== H1


def test_h1_sentence_bounds_cut_exactly_where_split_sentences_does():
    store = get_course_store()
    texts = [section.body for item in store.items.values() for section in item.sections]
    texts += ["", "   ", "One two three four.  Five six seven eight!", "\n  Lead text here. Next one is here?\tLast words",
              "See e.g. this case. Then Fig. 3 shows it. J. Preskill wrote it. Done.", "No boundary at all"]
    assert len(texts) > 100
    for text in texts:
        bounds = sentence_bounds(text)
        assert split_sentences(text) == [whitespace(text[begin:end]) for begin, end in bounds]
        assert all(text[begin:end] == text[begin:end].strip() and begin < end for begin, end in bounds)
        assert list(bounds) == sorted(bounds) and all(a[1] <= b[0] for a, b in zip(bounds, bounds[1:]))


def test_h1_a_span_edge_fragment_never_binds_and_a_whole_sentence_of_the_same_span_does():
    store = get_course_store()
    resolver = SpanResolver(store)
    fragments = _edge_fragments(store)
    # Not vacuous: spans are splitter chunks, so hundreds start or end inside a document sentence.
    assert sum(edge == "start" for _, _, edge in fragments) > 50 and sum(edge == "end" for _, _, edge in fragments) > 50
    start = next((record, piece) for record, piece, edge in fragments if edge == "start" and _whole(store, record))
    end = next((record, piece) for record, piece, edge in fragments if edge == "end" and record.span_id != start[0].span_id)
    whole = _whole(store, start[0])[0]
    plan = ClaimPlan(generator=REF, claims=(
        ProposedClaim(text=start[1], span_ids=(start[0].span_id,)),  # its opening words are in the previous span only
        ProposedClaim(text=end[1], span_ids=(end[0].span_id,)),  # its end is in the next span only
        ProposedClaim(text=whole.text, span_ids=(start[0].span_id,)),  # binds
        ProposedClaim(text=start[1].split(" ", 1)[1], span_ids=(start[0].span_id,)),  # a cut of a fragment: no piece at all
    ))
    result = bind(plan, _bundle(store, [start[0], end[0]]), resolver=resolver, store=store, registry=resolver.registry, params=PARAMS)
    assert [draft.text for draft in result.bound] == [whole.text]
    assert dict(result.dropped) == {"partial_sentence": 2, "not_verbatim": 1}
    assert result.bound[0].source_order == (start[0].item_id, whole.position)
    assert contracts.PARTIAL_SENTENCE in contracts.BINDING_FAILURES  # a binding failure: it lowers the bound-claim ratio


def test_h1_the_reported_negation_drop_no_longer_binds():
    # The finding's example: a span that starts at "preserve the underlying structural feasibility", cut from "...these
    # classical heuristics often fail to | preserve ...". Under resolver-bundle-sentence-v1 that piece locked, without
    # its "fail to".
    store = get_course_store()
    resolver = SpanResolver(store)
    record = next(r for r in store.span_registry.records if r.item_kind == "document" and r.text.startswith("preserve the underlying structural feasibility"))
    section = _section(store, record)
    assert section.body[: record.start - section.body_start].rstrip().endswith("fail to")
    piece = split_sentences(record.text)[0]
    result = bind(ClaimPlan(generator=REF, claims=(ProposedClaim(text=piece, span_ids=(record.span_id,)),)), _bundle(store, [record]),
                  resolver=resolver, store=store, registry=resolver.registry, params=PARAMS)
    assert result.bound == () and dict(result.dropped) == {"partial_sentence": 1}
    window = whole_sentence_text(record, store)
    assert window is None or not window.startswith("preserve")


def test_h1_the_envelope_carries_only_whole_sentences_and_every_locked_claim_is_one():
    store, results = _replay()
    answered = 0
    old_rule_fragments = 0
    for query, result in results:
        question = content_terms(query, PACKAGE.retrieval)
        for span in result.bundle.spans:
            record = store.span_registry.get(span.span_id)
            if not span.quotable:
                continue
            # What the extractive generator proposed from this span under the old envelope (the span's whole text).
            old = [s for s in sentences(record.text, **WORDS) if len(content_terms(s, PACKAGE.retrieval) & question) >= PARAMS.min_question_overlap_terms]
            section_sentences = set(split_sentences(_section(store, record).body))
            old_rule_fragments += sum(s not in section_sentences for s in old[: PARAMS.max_claims_per_span])
        if result.envelope is not None:
            for evidence in result.envelope.evidence:
                record = store.span_registry.get(evidence.span_id)
                assert evidence.text in record.text and evidence.text == whole_sentence_text(record, store)
                assert sentences(evidence.text, **WORDS) == [s.text for s in _whole(store, record)]
            quotable_with_sentences = [s.span_id for s in result.bundle.spans if s.quotable and whole_sentence_text(store.span_registry.get(s.span_id), store)]
            assert [evidence.span_id for evidence in result.envelope.evidence] == quotable_with_sentences
        if result.decision != "answer":
            continue
        answered += 1
        assert result.entry.counts.dropped == {} or set(result.entry.counts.dropped) <= {"merged", "duplicate"}
        for claim in result.locked.claims:
            for span_id in claim.span_ids:
                record = store.span_registry.get(span_id)
                section = _section(store, record)
                assert claim.text in set(split_sentences(section.body)), claim.text[:80]
                held = [s for s in _whole(store, record) if s.text == claim.text]
                assert held and all(record.start <= s.position < record.end for s in held)
            assert claim.source_order[1] == min(s.position for span_id in claim.span_ids
                                                for s in _whole(store, store.span_registry.get(span_id)) if s.text == claim.text)
    assert answered > 100
    # The fixture exercises the defect: the old envelope made the generator propose span-edge fragments.
    assert old_rule_fragments > 10


def test_h1_the_extractive_generator_proposes_only_what_binds():
    store, results = _replay()
    proposed = bound = 0
    for _, result in results:
        proposed += result.entry.counts.proposed_claims
        bound += result.entry.counts.bound_claims + result.entry.counts.dropped.get("merged", 0)
        assert "partial_sentence" not in result.entry.counts.dropped and "not_verbatim" not in result.entry.counts.dropped
    assert proposed > 200 and bound == proposed  # the bound-claim ratio stays 1.0, the Phase 2 baseline (plan L)


def test_h1_a_store_without_the_section_text_binds_nothing():
    store = get_course_store()
    resolver = SpanResolver(store)
    record = next(r for r in store.span_registry.records if r.item_kind == "document" and _whole(store, r))
    sentence = _whole(store, record)[0].text
    blind = SimpleNamespace(span_registry=store.span_registry, items={})
    assert whole_sentences(record, blind, **WORDS) == () and whole_sentence_text(record, blind) is None
    result = bind(ClaimPlan(generator=REF, claims=(ProposedClaim(text=sentence, span_ids=(record.span_id,)),)), _bundle(store, [record]),
                  resolver=resolver, store=blind, registry=resolver.registry, params=PARAMS)
    assert result.bound == ()


# =============================================================================================================== H2


def test_h2_stepwise_keeps_two_sentences_of_one_span_in_their_source_order():
    store = get_course_store()
    resolver = SpanResolver(store)
    # A span with two whole sentences whose claim ids sort the later one first: the old key (span start, claim id)
    # rendered them later-first under the "in source order" lead.
    record, earlier, later = next(
        (r, a, b) for r in store.span_registry.records if r.item_kind == "document"
        for a, b in zip(_whole(store, r), _whole(store, r)[1:])
        if claim_id_for(b.text, [r.span_id]) < claim_id_for(a.text, [r.span_id])
    )
    bundle = _bundle(store, [record])
    drafts = bind(ClaimPlan(generator=REF, claims=(ProposedClaim(text=later.text, span_ids=(record.span_id,)),
                                                   ProposedClaim(text=earlier.text, span_ids=(record.span_id,)))),
                  bundle, resolver=resolver, store=store, registry=resolver.registry, params=PARAMS).bound
    locked = lock(drafts, bundle=bundle, generator=REF, evidential_prompt_hash=REF.prompt_hash, pedagogical_prompt_hash=PARAMS.pedagogical_prompt_hash,
                  resolver=RESOLVER, package=PACKAGE)
    assert [claim.text for claim in locked.claims] == [later.text, earlier.text]  # the locked order is the proposal order
    assert [claim.source_order for claim in locked.claims] == [(record.item_id, later.position), (record.item_id, earlier.position)]
    assert earlier.position < later.position
    renderer = TemplateRenderer()
    stepwise = renderer.render(locked, PresentationPlan(plan_id="stepwise", source="request"), attempt=1)
    assert [s.text for s in stepwise.segments if s.kind == "claim"] == [earlier.text, later.text]
    assert TEMPLATES["stepwise.lead"][1].endswith("in source order:")
    concise = renderer.render(locked, PresentationPlan(plan_id="concise", source="request"), attempt=1)
    assert [s.text for s in concise.segments if s.kind == "claim"] == [later.text, earlier.text]


def test_h2_every_stepwise_rendering_of_the_replay_is_in_source_order():
    store, results = _replay()
    pairs = same_span = 0
    for _, result in results:
        if result.decision != "answer":
            continue
        by_id = {claim.claim_id: claim for claim in result.locked.claims}
        order = [by_id[s.claim_id] for s in result.rendered.segments if s.kind == "claim"]
        for a, b in zip(order, order[1:]):
            pairs += 1
            same_span += a.span_ids[0] == b.span_ids[0]
            assert tuple(a.source_order) <= tuple(b.source_order)
            if a.source_order[0] == b.source_order[0]:
                item = store.items[a.source_order[0]]
                for claim in (a, b):
                    position = claim.source_order[1]
                    assert whitespace(item.text[position : position + 4 * len(claim.text) + 50]).startswith(claim.text)
    assert pairs > 100 and same_span > 30  # the measured defect: 59 of 111 same-span pairs were out of order


# =============================================================================================================== I1


def test_i1_quotable_spans_with_no_whole_sentence_abstain_as_no_whole_sentence_never_no_quotable_evidence(monkeypatch):
    settings = Settings()
    store = get_course_store()
    quotable = _quotable_documents(store)
    fragments = [record for record in quotable if whole_sentence_text(record, store) is None][:4]
    whole = next(record for record in quotable if whole_sentence_text(record, store) is not None)
    assert len(fragments) >= 2, "the dev corpus no longer has quotable spans without a whole sentence"
    resolved = resolve_turns([], LearnerTurn(f"message-{uuid4()}", MULTI_CLAIM), package=PACKAGE)
    request = build_request(resolved, lesson_slug=None, corpus_version=store.corpus_version)
    bundle = _bundle(store, fragments)
    assert build_envelope(request, bundle, store=store, params=PARAMS) is None
    assert no_envelope_reason(bundle, store=store) == NO_WHOLE_SENTENCE == "no_whole_sentence"
    # Nothing quotable (D-31: not approved), or nothing left at all (the license gate): the other reason.
    assert no_envelope_reason(_bundle(store, fragments, quotable=False), store=store) == NO_QUOTABLE_EVIDENCE == "no_quotable_evidence"
    assert no_envelope_reason(bundle.model_copy(update={"spans": ()}), store=store) == NO_QUOTABLE_EVIDENCE
    # The control: one quotable span with a whole sentence makes an envelope.
    assert build_envelope(request, _bundle(store, [*fragments, whole]), store=store, params=PARAMS) is not None
    # Through the pipeline, the record's reason agrees with its own per-span flags and sufficiency.
    monkeypatch.setattr(pipeline_module, "retrieve", lambda engine, request, **kwargs: bundle)
    result = _run(TwoPassPipeline(RetrievalEngine(store, settings), settings), MULTI_CLAIM)
    assert (result.decision, result.abstention_reason, result.envelope) == ("abstain", "no_whole_sentence", None)
    entry = result.entry
    assert entry.abstention_reason == "no_whole_sentence" and entry.retrieval.sufficiency.decision == "answer"
    assert entry.retrieval.evidence and all(span.quotable for span in entry.retrieval.evidence)
    # A valid ledger entry of its own schema (a two-pass record is ledger-entry-v2 since Phase 4).
    assert contracts.ENTRY_SCHEMAS[entry.entry_schema].model_validate(entry.model_dump(mode="json")) == entry
    assert "no_whole_sentence" in contracts.ABSTENTION_REASONS and "no_quotable_evidence" in contracts.ABSTENTION_REASONS


def test_i1_over_the_in_domain_fixture_each_empty_envelope_reason_matches_its_own_record():
    settings = Settings()
    store = get_course_store()
    pipeline = TwoPassPipeline(RetrievalEngine(store, settings), settings)
    reasons: Counter = Counter()
    for query in IN_DOMAIN:
        result = _run(pipeline, query)
        if result.abstention_reason not in (NO_QUOTABLE_EVIDENCE, NO_WHOLE_SENTENCE):
            continue
        assert result.envelope is None
        reasons[result.abstention_reason] += 1
        quotable = [span for span in result.entry.retrieval.evidence if span.quotable]
        if result.abstention_reason == NO_QUOTABLE_EVIDENCE:
            assert not quotable, query
        else:
            assert quotable and all(whole_sentence_text(store.span_registry.get(span.span_id), store) is None for span in quotable), query
    # The measured residual of 18.10 H1 (11 items under bm25f-v1 in the committed replay) now has its own reason.
    assert reasons[NO_WHOLE_SENTENCE] >= 1, reasons


# =============================================================================================================== J1


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
