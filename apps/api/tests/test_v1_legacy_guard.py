"""The legacy guard on contained answers: V1.1 and V1.2, and V1.7 when no disclosure is shown (plan Phase 4 L; AC-4-6;
Phase 4 spec 4.15, conflicts 4, 22, 34)."""

from __future__ import annotations

import dataclasses
import functools
import json
import logging
from pathlib import Path
import re

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.core.corpus_governance import get_corpus_registry
from app.services.contained_answers import ABSTENTION, contain_answer
from app.services.provenance import native_citation
from app.services.retrieval_engine import RetrievalEngine
from app.services.span_resolver import SpanResolver
from app.services.store import get_course_store
from app.services.text_utils import normalize_display_text
from app.services.v1_checks.legacy_guard import DISPLAY_ELLIPSIS, guard_contained
from app.services.v1_checks.lexicon import negation_cues, quantities, quantities_covered
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

    numbered = next((claim.text for claim in contained.claims if re.search(r"\d", claim.text)), None)
    # (label, expected (check_id, reason_code), forgery): each forgery fails at the named check and reason.
    forgeries = [
        ("fabricated span id", ("V1.1", "unresolvable"), _forged(contained, span_id="span-" + "e" * 64)),
        ("appended sentence", ("V1.2", "not_verbatim"), _forged(contained, text=quote + " And quantum computers are always faster.")),
        ("inserted negation", ("V1.2", "not_verbatim"), _forged(contained, text=quote.replace(" ", " not ", 1))),
        ("no cited span", ("V1.2", "unbound"),
         dataclasses.replace(contained, claims=[contained.claims[0].model_copy(update={"cited_span_ids": []})])),
        ("changed content hash", ("V1.1", "content_hash_mismatch"), dataclasses.replace(
            contained, citations=[contained.citations[0].model_copy(update={"content_hash": "0" * 64}), *contained.citations[1:]])),
    ]
    V1_METRICS.reset()
    for label, expected, forged in forgeries:
        with caplog.at_level(logging.WARNING, logger="qcai.tutor"):
            guarded = guard_contained(forged, store=store, package=PACKAGE, surface="tutor")
        assert guarded.withheld[0] == expected, (label, guarded.withheld)
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
        swapped_guard = guard_contained(dataclasses.replace(contained, claims=changed), store=store, package=PACKAGE, surface="qa")
        assert swapped_guard.contained.decision == "abstain" and swapped_guard.withheld[0] == ("V1.2", "not_verbatim")


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


def _collapsed(text: str) -> str:
    return " ".join(text.split())


@functools.lru_cache(maxsize=1)
def _edge_cuts() -> dict[str, tuple]:
    """Development quotations cut mid-token, each still a verbatim substring of its span: a number cut short ("128" to
    "12", a number the span does not hold) and a negation cue cut short ("not" to "no", a cue the span does not hold).
    Only the polarity rule can tell these from a faithful quotation (the claim-to-span rule, E-27)."""
    store = get_course_store()
    resolver = SpanResolver(store)
    lexicon = PACKAGE.v1.lexicon
    found: dict[str, tuple] = {}
    for item in DATA["in_domain"]:
        contained = _contained(item["query"])
        if contained.decision != "answer":
            continue
        for index, claim in enumerate(contained.claims):
            if len(claim.cited_span_ids) != 1:
                continue
            span = _collapsed(normalize_display_text(resolver.resolve_current(claim.cited_span_ids[0]).text or ""))
            quotation = _collapsed(claim.text.removesuffix(DISPLAY_ELLIPSIS))
            if quotation not in span:
                continue
            for match in re.finditer(r"(?<![\w.,])(\d{2,})(?![\w.,])", quotation):
                cut = quotation[: match.end(1) - 1]
                if ("quantity" not in found and (match.group(1)[:-1], "") in quantities(cut, lexicon)
                        and not quantities_covered(cut, span, lexicon)):
                    found["quantity"] = (contained, index, cut)
            for match in re.finditer(r"\bnot\b", quotation):
                cut = quotation[: match.start() + 2]
                if ("negation" not in found and quantities_covered(cut, span, lexicon)
                        and negation_cues(cut, lexicon)["no"] > negation_cues(span, lexicon)["no"]):
                    found["negation"] = (contained, index, cut)
        if len(found) == 2:
            break
    assert set(found) == {"quantity", "negation"}, "no development quotation to cut"
    return found


def _with_quotation(contained, index: int, text: str):
    claims = [*contained.claims]
    claims[index] = claims[index].model_copy(update={"text": text})
    return dataclasses.replace(contained, claims=claims)


def test_the_polarity_rule_withholds_a_verbatim_quotation_that_cuts_a_number_or_a_cue():
    # Each cut is verbatim in its span, so V1.1 and verbatim binding pass it: the withholding is the polarity rule's.
    store = get_course_store()
    for kind, reason in (("quantity", "quantity_mismatch"), ("negation", "negation_mismatch")):
        contained, index, cut = _edge_cuts()[kind]
        forged = _with_quotation(contained, index, cut)
        guarded = guard_contained(forged, store=store, package=PACKAGE, surface="qa")
        assert guarded.withheld == (("V1.2", reason),), (kind, guarded.withheld)
        assert guarded.contained.answer == ABSTENTION and guarded.contained.decision == "abstain"
        # The quotation it was cut from is faithful and passes.
        assert guard_contained(contained, store=store, package=PACKAGE, surface="qa").withheld == ()


def test_without_a_v1_block_the_polarity_rule_is_skipped_in_development():
    store = get_course_store()
    no_v1 = dataclasses.replace(PACKAGE, v1=None)
    # The polarity rule's own cases pass without the lexicon (they are verbatim): only the polarity rule is skipped.
    for kind in ("quantity", "negation"):
        contained, index, cut = _edge_cuts()[kind]
        forged = _with_quotation(contained, index, cut)
        assert guard_contained(forged, store=store, package=PACKAGE, surface="qa").withheld != ()
        guarded = guard_contained(forged, store=store, package=no_v1, surface="qa")
        assert guarded.withheld == () and guarded.contained is forged, kind
    # V1.1 and verbatim binding still run without the lexicon.
    contained = _answered()
    assert guard_contained(_forged(contained, span_id="span-" + "e" * 64), store=store, package=no_v1, surface="qa").withheld[0] == ("V1.1", "unresolvable")
    assert guard_contained(_forged(contained, text=contained.claims[0].text + " Always."), store=store, package=no_v1,
                           surface="qa").withheld[0] == ("V1.2", "not_verbatim")


def _conflicting():
    """A contained answer quoting one span of each of two document items, and a package whose v1 block makes the two
    items one version family, so V1.7 finds a version_of_same_asset conflict between the quotations."""
    from app.schemas import Citation
    from app.services.provenance import CITATION_SCHEMA

    store = get_course_store()
    family = ("analyzing-quantum-computing-and-ai-paper-2025", "quantum-computing-ai-research-synthesis-2026")
    citations = []
    for item_id in family:
        record = next(r for r in store.span_registry.records if r.item_id == item_id and len(r.text) > 200)
        citations.append(Citation(chunk_id=record.span_id, span_id=record.span_id, source_kind="document", source_title="t", section_title="s",
                                  excerpt=record.text, source_filename=record.source_filename, content_hash=record.content_hash,
                                  citation_schema=CITATION_SCHEMA, item_id=record.item_id))
    contained = contain_answer(citations, get_corpus_registry(SETTINGS), store.span_registry, settings=SETTINGS)
    assert contained.decision == "answer" and len(contained.citations) == 2
    package = dataclasses.replace(PACKAGE, v1=dataclasses.replace(PACKAGE.v1, version_families={item: "fixture" for item in family}))
    return contained, package


def test_conflicting_quotations_are_withheld_unless_a_disclosure_is_shown(caplog):
    # AC-4-6 on the learner path: V1.7 over the quotations, withheld when no disclosure is shown (the default), passed
    # unchanged when the caller shows the evidence panel's conflicts, skipped without a v1 block.
    store = get_course_store()
    contained, package = _conflicting()
    assert guard_contained(contained, store=store, package=PACKAGE, surface="qa").withheld == ()  # no family, no conflict
    V1_METRICS.reset()
    with caplog.at_level(logging.WARNING, logger="qcai.tutor"):
        guarded = guard_contained(contained, store=store, package=package, surface="tutor")
    assert guarded.withheld == (("V1.7", "conflict_withheld"),)
    assert (guarded.contained.answer, guarded.contained.decision, guarded.contained.citations) == (ABSTENTION, "abstain", [])
    (line,) = [r.json_fields for r in caplog.records if getattr(r, "json_fields", {}).get("event") == "tutor.v1.legacy_guard_withheld"]
    assert (line["check_id"], line["reason_code"], line["surface"]) == ("V1.7", "conflict_withheld", "tutor")
    assert V1_METRICS.detail_snapshot()["legacy_guard"]["by_check"] == {"V1.1": 0, "V1.2": 0, "V1.7": 1}
    shown = guard_contained(contained, store=store, package=package, surface="tutor", disclosure_shown=True)
    assert shown.withheld == () and shown.contained is contained
    no_v1 = dataclasses.replace(package, v1=None)
    assert guard_contained(contained, store=store, package=no_v1, surface="tutor").contained is contained


def test_a_stored_reply_is_linked_to_its_turn_by_time_and_carries_its_conflict_labels():
    # AC-4-6 where a stored reply is shown again (GET /assistant/threads/{id}): the reply carries the V1.7 labels of its
    # turn's citations. Its turn is the one stamped MESSAGE_TICK before it (chat() sets the times), or the one stamped
    # at the same instant (a database clock stamped turn and reply); an instant two turns share, an abstaining turn, a
    # withdrawn reply and a package without a v1 block give none.
    from datetime import datetime, timezone
    from uuid import uuid4

    from app.core.db import SessionLocal
    from app.db_models import TutorMessage, TutorThread, TutorTurn
    from app.services.tutor_orchestrator import MESSAGE_TICK, _message_read, _reply_conflicts

    contained, package = _conflicting()
    conflicting = [citation.model_dump() for citation in contained.citations]
    single = conflicting[:1]
    thread_id, user_id = f"thread-{uuid4()}", f"p4-link-{uuid4().hex[:12]}"
    base = datetime(2026, 11, 21, 10, 0, 0, 123456, tzinfo=timezone.utc)
    minute = 60_000_000 * MESSAGE_TICK
    old = datetime(2026, 11, 10, 9, 0, 0, tzinfo=timezone.utc)  # before containment: the reply is withdrawn (R-16)

    def turn(at, decision, citations):
        return TutorTurn(id=f"turn-{uuid4()}", thread_id=thread_id, user_id=user_id, resolved_query="q", retrieval_mode="lexical",
                         provider="none", model="extractive", decision=decision, decision_reason="evidence", citations=citations,
                         claims=[], corpus_version="c", policy_version="p", created_at=at)

    def reply(at):
        return TutorMessage(id=f"message-{uuid4()}", thread_id=thread_id, role="assistant", content="quoted", created_at=at)

    linked, same_instant = reply(base + MESSAGE_TICK), reply(base + minute)
    shared, abstained, unconflicted, withdrawn = reply(base + 2 * minute), reply(base + 3 * minute + MESSAGE_TICK), \
        reply(base + 4 * minute + MESSAGE_TICK), reply(old + MESSAGE_TICK)
    question = TutorMessage(id=f"message-{uuid4()}", thread_id=thread_id, role="user", content="q", created_at=base)
    with SessionLocal() as db:
        db.add(TutorThread(id=thread_id, user_id=user_id, title="t"))
        db.flush()
        db.add_all([turn(base, "answer", conflicting), turn(base + minute, "answer", conflicting),
                    turn(base + 2 * minute, "answer", conflicting), turn(base + 2 * minute, "answer", conflicting),
                    turn(base + 3 * minute, "abstain", conflicting), turn(base + 4 * minute, "answer", single),
                    turn(old, "answer", conflicting)])
        db.add_all([question, linked, same_instant, shared, abstained, unconflicted, withdrawn])
        db.commit()
        try:
            messages = list(db.query(TutorMessage).filter(TutorMessage.thread_id == thread_id).order_by(TutorMessage.created_at, TutorMessage.id))
            expected = [{"kind": "version_of_same_asset", "passages": [1, 2]}]
            found = _reply_conflicts(db, thread_id, messages, package)
            assert {message_id: [conflict.model_dump() for conflict in labels] for message_id, labels in found.items()} == {
                linked.id: expected, same_instant.id: expected}
            assert _reply_conflicts(db, thread_id, messages, PACKAGE) == {}  # the shipped package: no family, no conflict
            assert _reply_conflicts(db, thread_id, messages, dataclasses.replace(package, v1=None)) == {}
            by_id = {message.id: message for message in messages}
            read = _message_read(by_id[withdrawn.id], found.get(linked.id))
            assert read.withdrawn and read.conflicts is None and "conflicts" not in read.model_dump()
            assert _message_read(by_id[linked.id], found[linked.id]).model_dump()["conflicts"] == expected
        finally:
            db.query(TutorMessage).filter(TutorMessage.thread_id == thread_id).delete()
            db.query(TutorTurn).filter(TutorTurn.thread_id == thread_id).delete()
            db.query(TutorThread).filter(TutorThread.id == thread_id).delete()
            db.commit()


def test_stored_labels_keep_the_answer_s_positions():
    # evidence_panel.stored_conflicts: the panel's rule over stored citation dumps, in the stored order the answer's [n]
    # numbering follows; an entry that is not a citation keeps its position and conflicts with nothing; fewer than two
    # entries, or no v1 block, give none.
    from app.services.evidence_panel import panel_conflicts, stored_conflicts

    contained, package = _conflicting()
    stored = [citation.model_dump() for citation in contained.citations]
    live = [conflict.model_dump() for conflict in panel_conflicts(contained, package)]
    assert [conflict.model_dump() for conflict in stored_conflicts(stored, package)] == live == [
        {"kind": "version_of_same_asset", "passages": [1, 2]}]
    shifted = stored_conflicts([stored[0], "not a citation", stored[1]], package)
    assert [conflict.model_dump() for conflict in shifted] == [{"kind": "version_of_same_asset", "passages": [1, 3]}]
    assert stored_conflicts(stored[:1], package) is None and stored_conflicts([], package) is None
    assert stored_conflicts(stored, PACKAGE) is None and stored_conflicts(stored, dataclasses.replace(package, v1=None)) is None
