"""The V1.1/V1.2 legacy guard on contained answers (plan Phase 4 L; Phase 4 spec 4.15, conflicts 4, 22, 34)."""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.core.corpus_governance import get_corpus_registry
from app.services.contained_answers import ABSTENTION, contain_answer
from app.services.provenance import native_citation
from app.services.retrieval_engine import RetrievalEngine
from app.services.store import get_course_store
from app.services.v1_checks.legacy_guard import guard_contained
from app.services.v1_checks.metrics import V1_METRICS

SETTINGS = Settings()
PACKAGE = get_config_package(SETTINGS)
DATA = json.loads((Path(__file__).parent / "data" / "score_floor_queries.json").read_text(encoding="utf-8"))


def _contained(query: str):
    store = get_course_store()
    engine = RetrievalEngine(store, SETTINGS)
    retrieval = engine.search(query, top_k=4, surface="qa")
    citations = [native_citation(hit, corpus_version=store.corpus_version, settings=SETTINGS) for hit in retrieval.results]
    return contain_answer(citations, get_corpus_registry(SETTINGS), store.span_registry, settings=SETTINGS)


def _answered():
    contained = _contained("Why does routing depth matter on sparse hardware?")
    assert contained.decision == "answer" and contained.claims
    return contained


def _forged(contained, *, text=None, span_id=None):
    claim = contained.claims[0]
    forged_claim = claim.model_copy(update={"text": text if text is not None else claim.text,
                                            "cited_span_ids": [span_id] if span_id is not None else claim.cited_span_ids})
    return dataclasses.replace(contained, claims=[forged_claim, *contained.claims[1:]])


def test_every_dev_contained_answer_passes_unchanged():
    store = get_course_store()
    answered = 0
    for item in DATA["in_domain"]:
        contained = _contained(item["query"])
        guarded = guard_contained(contained, store=store, package=PACKAGE, surface="qa")
        assert guarded.withheld == () and guarded.contained is contained, item["query"]
        answered += int(contained.decision == "answer")
    assert answered >= 150


def test_each_guard_failure_withholds_the_whole_answer_as_today_s_abstention(caplog):
    store = get_course_store()
    contained = _answered()
    quote = contained.claims[0].text
    import re

    numbered = next((claim.text for claim in contained.claims if re.search(r"\d", claim.text)), None)
    forgeries = {
        ("V1.1", "unresolvable"): _forged(contained, span_id="span-" + "e" * 64),
        ("V1.2", "not_verbatim"): _forged(contained, text=quote + " And quantum computers are always faster."),
        ("V1.2", "negation_inserted"): _forged(contained, text=quote.replace(" ", " not ", 1)),
        ("V1.2", "unbound"): dataclasses.replace(contained, claims=[contained.claims[0].model_copy(update={"cited_span_ids": []})]),
        ("V1.1", "content_hash_mismatch"): dataclasses.replace(
            contained, citations=[contained.citations[0].model_copy(update={"content_hash": "0" * 64}), *contained.citations[1:]]),
    }
    V1_METRICS.reset()
    for (check_id, reason), forged in forgeries.items():
        with caplog.at_level(logging.WARNING, logger="qcai.tutor"):
            guarded = guard_contained(forged, store=store, package=PACKAGE, surface="tutor")
        assert guarded.withheld[0][0] == check_id, (check_id, reason, guarded.withheld)
        assert guarded.contained.answer == ABSTENTION and guarded.contained.decision == "abstain" and guarded.contained.reason == "no_approved_span"
        assert guarded.contained.citations == [] and guarded.contained.claims == [] and guarded.contained.grounded is False
    lines = [r.json_fields for r in caplog.records if getattr(r, "json_fields", {}).get("event") == "tutor.v1.legacy_guard_withheld"]
    assert len(lines) == len(forgeries) and {line["surface"] for line in lines} == {"tutor"}
    assert all(set(line) >= {"check_id", "reason_code", "surface"} and quote not in json.dumps(line) for line in lines)
    snapshot = V1_METRICS.detail_snapshot()["legacy_guard"]
    assert snapshot["withheld"]["tutor"] == len(forgeries) and snapshot["by_check"]["V1.1"] == 2
    if numbered is not None:
        swapped = re.sub(r"(\d+)", lambda m: str(int(m.group(1)) + 1), numbered, count=1)
        index = next(i for i, claim in enumerate(contained.claims) if claim.text == numbered)
        changed = [*contained.claims]
        changed[index] = changed[index].model_copy(update={"text": swapped})
        assert guard_contained(dataclasses.replace(contained, claims=changed), store=store, package=PACKAGE, surface="qa").contained.decision == "abstain"


def test_a_truncated_quotation_and_a_number_before_a_non_unit_word_pass():
    store = get_course_store()
    contained = _answered()
    claim = contained.claims[0]
    words = claim.text.split()
    truncated = _forged(contained, text=" ".join(words[: max(4, len(words) // 2)]) + "...")
    assert guard_contained(truncated, store=store, package=PACKAGE, surface="qa").withheld == ()


def test_an_abstention_passes_and_is_counted():
    V1_METRICS.reset()
    contained = _contained("What is the capital of France?")
    assert contained.decision == "abstain"
    assert guard_contained(contained, store=get_course_store(), package=PACKAGE, surface="qa").contained is contained
    assert V1_METRICS.detail_snapshot()["legacy_guard"]["checked"]["qa"] == 1


def test_without_a_v1_block_the_polarity_rule_is_skipped_in_development():
    store = get_course_store()
    contained = _answered()
    negated = _forged(contained, text=contained.claims[0].text)  # verbatim: passes either way
    no_v1 = dataclasses.replace(PACKAGE, v1=None)
    assert guard_contained(negated, store=store, package=no_v1, surface="qa").withheld == ()
    # V1.1 and verbatim binding still run without the lexicon.
    assert guard_contained(_forged(contained, span_id="span-" + "e" * 64), store=store, package=no_v1, surface="qa").withheld[0] == ("V1.1", "unresolvable")
