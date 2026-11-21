"""V1.6, keyed answers in an assessment context (Phase 4 spec 4.7; PD-17; R-42; AC-4-5)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.services.quiz_keys import QuizKeySource
from app.services.store import get_course_store
from app.services.tutor_pipeline.contracts import RenderedResponse, Segment
from app.services.v1_checks.lexicon import knorm
from app.services.v1_checks.v1_6_keyed_answers import assessment_items, check_v1_6, key_text, keyed_claim_ids
from v1_fakes import MULTI_CLAIM, FixtureKeys, dev_pipeline, keyed_item, run

PACKAGE = get_config_package(Settings())
V1 = PACKAGE.v1
STOP = PACKAGE.retrieval.stopwords
DATA = json.loads((Path(__file__).parent / "data" / "score_floor_queries.json").read_text(encoding="utf-8"))


def _source():
    return QuizKeySource(get_course_store().quiz_keys)


def _rendered(text: str) -> RenderedResponse:
    return RenderedResponse(renderer_id="r", plan_id="concise", attempt=1, segments=(Segment(kind="connective", line=0, text=text),), citations=(), text=text)


def test_context_by_similarity_matches_the_in_quiz_prompts_and_no_off_topic_item():
    source = _source()
    items = source.items()
    assert len(items) == 12
    for item in items:
        assert item in assessment_items(item.prompt, source, v1=V1, stopwords=STOP)
    in_domain = sum(1 for item in DATA["in_domain"] if assessment_items(item["query"], source, v1=V1, stopwords=STOP))
    off_topic = sum(1 for query in DATA["off_topic"] + DATA["stopword_only"] if assessment_items(query, source, v1=V1, stopwords=STOP))
    assert (in_domain, off_topic) == (8, 0)


def test_context_by_a_hyphenated_item_id_inside_the_turn():
    source = _source()
    item = source.items()[0]
    assert item in assessment_items(f"Can you help me with {item.item_id}, please?", source, v1=V1, stopwords=STOP)
    assert item not in assessment_items(f"Can you help me with x{item.item_id}x?", source, v1=V1, stopwords=STOP)
    assert item not in assessment_items(f"about {item.item_id}0 only", source, v1=V1, stopwords=STOP)


def test_every_lesson_s_items_are_searched_whatever_the_lesson():
    items = _source().items()
    assert len({item.lesson_slug for item in items}) == 12


def test_long_keys_are_matched_by_containment_and_short_keys_only_as_choice_text():
    long_item = keyed_item("k-1", "Which kernel?", "Quantum kernels map data into a feature space")
    assert key_text(long_item, v1=V1) == long_item.answer
    present = check_v1_6(_rendered("As noted, quantum kernels map data into a feature space today."), [long_item], v1=V1, attempt=1)
    assert (present.outcome, present.reason_code) == ("hard_fail", "keyed_answer_present")
    absent = check_v1_6(_rendered("Kernels are a method."), [long_item], v1=V1, attempt=1)
    assert (absent.outcome, absent.reason_code) == ("pass", "key_absent")
    lettered = keyed_item("k-2", "Pick one", "b", choices=["routing adds swap gates", "compression shrinks the circuit depth", "none"])
    assert key_text(lettered, v1=V1) == "compression shrinks the circuit depth"
    assert check_v1_6(_rendered("Compression shrinks the circuit depth."), [lettered], v1=V1, attempt=1).reason_code == "keyed_answer_present"
    by_text = keyed_item("k-3", "Pick", "routing adds swap gates", choices=["routing adds swap gates"])
    assert key_text(by_text, v1=V1) == "routing adds swap gates"
    digit = keyed_item("k-4", "Pick", "2", choices=["a b", "error mitigation lowers bias"])
    assert key_text(digit, v1=V1) == "error mitigation lowers bias"
    short = keyed_item("k-5", "Yes or no?", "yes")
    assert key_text(short, v1=V1) is None
    assert check_v1_6(_rendered("yes, of course"), [short], v1=V1, attempt=1).reason_code == "short_key_unmatchable"
    assert check_v1_6(_rendered("anything"), [], v1=V1, attempt=1).reason_code == "not_assessment"
    # The threshold comes from the package (R-46).
    assert key_text(keyed_item("k-6", "p", "two token key"), v1=dataclasses.replace(V1, short_key_min_tokens=4)) is None


def test_keyed_claim_ids_name_the_claims_that_hold_the_key_or_lie_inside_it():
    locked = run(dev_pipeline(), MULTI_CLAIM).locked
    first, second = locked.claims[0], locked.claims[1]
    assert keyed_claim_ids(locked, [keyed_item("k", "p", first.text)], v1=V1) == {first.claim_id}
    spanning = keyed_item("k", "p", f"{first.text} {second.text}")
    assert keyed_claim_ids(locked, [spanning], v1=V1) == {first.claim_id, second.claim_id}
    assert keyed_claim_ids(locked, [keyed_item("k", "p", "nothing like any claim at all")], v1=V1) == frozenset()


def test_no_quiz_key_or_explanation_appears_in_any_public_span_of_the_dev_corpus():
    store = get_course_store()
    spans = [knorm(record.text) for record in store.span_registry.records if record.plane == "public"]
    for key in store.quiz_keys.all():
        for text in (key.answer, key.explanation):
            assert not any(knorm(text) in span for span in spans), key.id


def test_a_fixture_source_replaces_the_store_keys_in_the_pipeline():
    pipeline = dev_pipeline(keyed_items=FixtureKeys([keyed_item("fixture-key", MULTI_CLAIM, "unrelated key text that no claim holds")]))
    record = run(pipeline, MULTI_CLAIM).entry.verification
    assert [r.reason_code for r in record.checks if r.check_id == "V1.6"] == ["key_absent"]
