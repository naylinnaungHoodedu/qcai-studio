"""The two retrieval gates over index entries (plan Phase 2 tasks 2.5-2.6; spec 3.5-3.7a)."""

from __future__ import annotations

from dataclasses import replace
import math

from app.core.config import Settings
from app.core.config_package import get_config_package, stopwords_sha256
from app.services.lexical_index import IndexEntry, LexicalIndex, tokenize
from app.services.retrieval_p1 import QUERY_STOPWORDS, _tokenize

PACKAGE = get_config_package(Settings())
PARAMS = PACKAGE.retrieval


def entry(span_id: str, title: str, excerpt: str, lessons=("lesson-a",), modules=(1,), kind="document") -> IndexEntry:
    return IndexEntry(
        span_id=span_id, item_id="item", item_version="sha256:" + "0" * 16, item_kind=kind, section_ordinal=0, start=0,
        end=len(excerpt), content_hash="0" * 64, title=title, source_kind="lesson" if kind == "authored" else "document",
        source_title="Source", excerpt=excerpt, source_filename=None if kind == "authored" else "doc.docx",
        lesson_slugs=tuple(lessons), module_indexes=tuple(modules), title_words=frozenset(_tokenize(title)),
        excerpt_words=frozenset(_tokenize(excerpt)),
    )


ENTRIES = [
    entry("span-1", "Qubit routing", "Routing adds SWAP gates and increases circuit depth on routing hardware."),
    entry("span-2", "Portfolio optimization", "Quantum kernels help portfolio optimization under noise.", ("lesson-b",), (2,)),
    entry("span-3", "Noise", "Noise limits depth.", ("lesson-a", "lesson-b"), (1, 2)),
]


def index(gate: str = "bm25f-v1", floor: float | None = None, margin: float | None = None) -> LexicalIndex:
    abstention = PACKAGE.abstention
    if floor is not None:
        abstention = replace(abstention, floor=floor, margin=abstention.margin if margin is None else margin)
    return LexicalIndex(ENTRIES, PARAMS, abstention, gate=gate)


def test_bm25f_scores_match_a_hand_computation():
    lexical = index(floor=0.0)
    terms = lexical.query_terms("routing depth")
    assert terms == ("depth", "routing")
    k1, b, w = PARAMS.k1, PARAMS.b, PARAMS.title_weight
    lengths = []
    for item in ENTRIES:
        lengths.append(len(tokenize(item.excerpt, PARAMS)) + w * len(tokenize(item.title, PARAMS)))
    average = sum(lengths) / len(lengths)
    df = {"routing": 1, "depth": 2}
    idf = {t: math.log(1 + (3 - n + 0.5) / (n + 0.5)) for t, n in df.items()}
    tf_routing = 2 + w * 1  # body twice, title once
    tf_depth = 1
    norm = 1 - b + b * lengths[0] / average
    expected = idf["routing"] * tf_routing * (k1 + 1) / (tf_routing + k1 * norm) + idf["depth"] * tf_depth * (k1 + 1) / (tf_depth + k1 * norm)
    score, matched, eligible = lexical.score_entry(terms, ENTRIES[0])
    assert math.isclose(score, expected, rel_tol=1e-12) and matched == 2 and eligible


def test_the_stopword_list_and_tokenizer():
    words = sorted(PARAMS.stopwords)
    assert PACKAGE.raw["retrieval"]["stopwords"]["sha256"] == stopwords_sha256(words) == PARAMS.stopwords_sha256
    assert QUERY_STOPWORDS <= PARAMS.stopwords
    assert {"define", "definition", "term", "terms", "word", "words", "is", "of"} <= PARAMS.stopwords
    assert tokenize("The ﬁnancial STRASSE_and Straße of a QUBO-v2 x", PARAMS) == ["financial", "strasse", "strasse", "qubo", "v2"]


def test_coverage_v1_needs_two_matched_terms_or_a_title_match():
    lexical = index(floor=0.0)
    two = lexical.query_terms("routing portfolio")
    assert lexical.score_entry(two, ENTRIES[0])[2] is False  # one of two terms
    one = lexical.query_terms("swap")
    assert lexical.score_entry(one, ENTRIES[0])[2] is False  # a single term in the text only
    assert lexical.score_entry(lexical.query_terms("routing"), ENTRIES[0])[2] is True  # a single term in the title


def test_abstention_reasons_in_order_of_precedence():
    lexical = index(floor=0.0)
    assert lexical.evaluate("What is the?").reason == "no_query_terms"
    assert lexical.evaluate("zebra xylophone").reason == "no_match"
    assert lexical.evaluate("routing zebra").reason == "insufficient_coverage"
    high = index(floor=99.0)
    assert high.evaluate("routing depth").reason == "below_floor"
    decision = lexical.evaluate("routing depth")
    assert (decision.abstained, decision.reason, decision.gate) == (False, "evidence", "bm25f-v1")


def test_ties_break_by_span_id_and_the_lesson_filter_applies_after_scoring():
    twins = [entry("span-b", "Same", "Identical routing depth text."), entry("span-a", "Same", "Identical routing depth text.", ("lesson-b",), (2,))]
    lexical = LexicalIndex(twins, PARAMS, replace(PACKAGE.abstention, floor=0.0), gate="bm25f-v1")
    results = lexical.evaluate("routing depth").results
    assert [r.entry.span_id for r in results] == ["span-a", "span-b"] and results[0].score == results[1].score
    filtered = lexical.evaluate("routing depth", lesson_slug="lesson-a").results
    assert [r.entry.span_id for r in filtered] == ["span-b"] and filtered[0].score == results[1].score


def test_near_floor_marks_scores_within_the_margin():
    lexical = index(floor=0.0)
    score = lexical.evaluate("routing depth").results[0].score
    near = index(floor=score - 0.01, margin=1.0)
    clear = index(floor=score - 2.0, margin=1.0)
    assert near.evaluate("routing depth").results[0].near_floor is True
    assert clear.evaluate("routing depth").results[0].near_floor is False


def test_the_p1_floor_gate_uses_whole_words_substring_overlap_and_the_best_lesson_boost():
    p1 = index(gate="p1-floor")
    # "swap" is one shared word in the text (2) with the text phrase bonus (2): 4 < 6, so it never passes;
    # "routing" also matches the whole heading phrase (+4) and passes, exactly as Phase 1 scored it.
    assert p1.evaluate("swap").abstained and p1.evaluate("swap").reason == "below_floor"
    assert not p1.evaluate("routing").abstained
    decision = p1.evaluate("routing depth")
    assert [r.entry.span_id for r in decision.results] == ["span-1"]
    # Substring overlap scores: "rout" matches the heading and text as substrings, as Phase 1 scored.
    score, passes, boost_lesson, matched = p1.p1_score_entry("routing depth", ENTRIES[0], None)
    assert passes and matched and boost_lesson == "lesson-a"
    assert score == 3 * 1 + 2 * 2 + 0 + 1  # heading "routing", text "routing" and "depth", module 1
    # A span bound to two lessons takes the higher module's boost, or the requested lesson's.
    noise = ENTRIES[2]
    assert p1.p1_score_entry("noise limits depth", noise, None)[2] == "lesson-b"
    assert p1.p1_score_entry("noise limits depth", noise, "lesson-a")[2] == "lesson-a"
    assert p1.evaluate("noise limits depth").results[0].near_floor is False
    assert p1.evaluate("").reason == "no_query_terms" and p1.evaluate("zebra quokka").reason == "no_match"
