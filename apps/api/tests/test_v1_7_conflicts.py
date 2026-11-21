"""V1.7, conflicting cited spans (rule conflict-version-polarity-v1; Phase 4 spec 4.8, conflict 33; R-19; AC-4-6)."""

from __future__ import annotations

import dataclasses
import hashlib

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.schemas import Citation
from app.services.tutor_pipeline.bind import LockedClaimDraft, claim_id_for
from app.services.tutor_pipeline.contracts import EvidenceBundle, EvidenceSpan, ResolverRef, Sufficiency
from app.services.tutor_pipeline.lock import lock
from app.services.v1_checks.v1_7_conflicts import check_v1_7, disagreement, legacy_conflicts

PACKAGE = get_config_package(Settings())
V1 = PACKAGE.v1
STOP = PACKAGE.retrieval.stopwords
RESOLVER = ResolverRef(model_id="thread-resolver-v1", prompt_hash="a" * 64)


def _span_id(name: str) -> str:
    return "span-" + hashlib.sha256(name.encode()).hexdigest()


def _setup(claims: list[tuple[str, str, str]], extra_sentences: dict[str, tuple[str, ...]] | None = None, v1=V1):
    """claims: (text, span name, item id). Returns (locked, bundle, sentences_of)."""
    spans = {}
    drafts = []
    sentences: dict[str, tuple[str, ...]] = {}
    for text, span_name, item_id in claims:
        span_id = _span_id(span_name)
        spans[span_id] = EvidenceSpan(span_id=span_id, item_id=item_id, item_version="v", kind="document", char_start=0, char_end=10,
                                      content_hash="c" * 64, score=1.0, near_floor=False, license_class="public", quotable=True)
        sentences.setdefault(span_id, ())
        sentences[span_id] = (*sentences[span_id], text)
        drafts.append(LockedClaimDraft(claim_id=claim_id_for(text, [span_id]), text=text, span_ids=(span_id,), source_order=(item_id, len(drafts))))
    for span_name, extra in (extra_sentences or {}).items():
        sentences[_span_id(span_name)] = (*sentences.get(_span_id(span_name), ()), *extra)
    sufficiency = Sufficiency(score=1.0, gate="bm25f-v1", threshold_version="t", floor=2.35, margin=2.4, decision="answer", reason="evidence")
    bundle = EvidenceBundle(corpus_version="c", index_version="i", retrieval_mode="lexical", spans=tuple(spans.values()), sufficiency=sufficiency)
    locked = lock(drafts, bundle=bundle, generator=None, evidential_prompt_hash=None, pedagogical_prompt_hash="b" * 64, resolver=RESOLVER, package=PACKAGE)
    return locked, bundle, (lambda span_id: sentences.get(span_id, ()))


def _check(locked, bundle, sentences_of, v1=V1):
    return check_v1_7(locked, bundle, sentences_of=sentences_of, v1=v1, stopwords=STOP, attempt=1)


ROUTED = "The routing stage inserts 12 extra swap gates into the compiled benchmark circuit."


def test_spans_of_two_items_in_one_version_family_disclose_a_version_pair():
    family = dataclasses.replace(V1, version_families={"paper-2025": "fixture", "paper-2026": "fixture"})
    locked, bundle, sentences_of = _setup([("Hybrid models need careful hardware aware design choices.", "a", "paper-2025"),
                                          ("Quantum kernels embed data into large feature spaces.", "b", "paper-2026")])
    result, block = _check(locked, bundle, sentences_of, family)
    assert (result.outcome, result.reason_code) == ("flag", "conflict_disclosed") and block.policy == "disclose"
    (pair,) = block.conflicts
    assert pair.kind == "version_of_same_asset" and pair.item_ids == ("paper-2025", "paper-2026")
    assert set(pair.span_ids) == set(locked.span_ids) and set(pair.claim_ids) == {claim.claim_id for claim in locked.claims}
    # Without the family the same spans are no conflict.
    assert _check(locked, bundle, sentences_of)[1] is None


def test_aligned_sentences_of_other_items_that_differ_in_numbers_or_negation_disagree():
    number_twin = ROUTED.replace("12", "13")
    locked, bundle, sentences_of = _setup([(ROUTED, "a", "item-a"), (number_twin, "b", "item-b")])
    result, block = _check(locked, bundle, sentences_of)
    assert result.reason_code == "conflict_disclosed" and {pair.kind for pair in block.conflicts} == {"number_disagreement"}
    negated = "The routing stage never inserts extra swap gates into the compiled benchmark circuit."
    plain = "The routing stage inserts extra swap gates into the compiled benchmark circuit."
    locked, bundle, sentences_of = _setup([(plain, "a", "item-a"), (negated, "b", "item-b")])
    assert {pair.kind for pair in _check(locked, bundle, sentences_of)[1].conflicts} == {"negation_disagreement"}


def test_number_disagreement_compares_values_only_and_needs_both_sides_numbered():
    assert disagreement("Five qubits run the routed benchmark circuit today", "5 qubits run the routed benchmark circuit today", v1=V1, stopwords=STOP) == "number_disagreement"
    assert disagreement("The routed benchmark circuit uses 5 qubits overall", "The routed benchmark circuit uses 5 noisy qubits overall", v1=V1, stopwords=STOP) is None
    assert disagreement("The routed benchmark circuit uses 5 qubits overall", "The routed benchmark circuit uses qubits overall", v1=V1, stopwords=STOP) is None
    assert disagreement("The routed benchmark circuit uses 5 ms overall", "The routed benchmark circuit uses 5 ns overall", v1=V1, stopwords=STOP) is None


def test_short_or_unaligned_sentences_and_the_same_item_never_conflict():
    # Fewer than min_alignment_terms terms (bibliography-like lines).
    assert disagreement("Smith 2024 pp", "Smith 2025 pp", v1=V1, stopwords=STOP) is None
    assert disagreement(ROUTED, "Bread baking needs flour and water, 12 cups.", v1=V1, stopwords=STOP) is None
    locked, bundle, sentences_of = _setup([(ROUTED, "a", "item-a"), (ROUTED.replace("12", "13"), "b", "item-a")])
    assert _check(locked, bundle, sentences_of)[1] is None
    # The thresholds come from the package (R-46).
    loose = dataclasses.replace(V1, alignment_threshold=0.01, min_alignment_terms=1)
    assert disagreement("Smith 2024 pp", "Smith 2025 pp", v1=loose, stopwords=STOP) == "number_disagreement"


def test_the_withhold_policy_names_the_involved_claims():
    withhold = dataclasses.replace(V1, on_conflict="withhold")
    locked, bundle, sentences_of = _setup([(ROUTED, "a", "item-a"), (ROUTED.replace("12", "13"), "b", "item-b"),
                                          ("Quantum kernels embed data into large feature spaces.", "c", "item-c")])
    result, block = _check(locked, bundle, sentences_of, withhold)
    assert (result.reason_code, block.policy) == ("conflict_withheld", "withhold")
    involved = {claim_id for pair in block.conflicts for claim_id in pair.claim_ids}
    assert involved == {locked.claims[0].claim_id, locked.claims[1].claim_id}


def test_the_legacy_panel_labels_quotations_of_different_items_by_position():
    def citation(item_id: str, excerpt: str) -> Citation:
        return Citation(chunk_id=_span_id(excerpt), source_kind="document", source_title="t", section_title="s", excerpt=excerpt, item_id=item_id)

    citations = [citation("item-a", ROUTED), citation("item-a", "Another sentence of the same document about kernels."),
                 citation("item-b", ROUTED.replace("12", "13"))]
    conflicts = legacy_conflicts(citations, v1=V1, stopwords=STOP)
    assert [(c.kind, c.passages) for c in conflicts] == [("number_disagreement", [1, 3])]
    family = dataclasses.replace(V1, version_families={"item-a": "f", "item-b": "f"})
    kinds = {(c.kind, tuple(c.passages)) for c in legacy_conflicts(citations, v1=family, stopwords=STOP)}
    assert ("version_of_same_asset", (1, 3)) in kinds and ("version_of_same_asset", (2, 3)) in kinds
    assert legacy_conflicts(citations[:2], v1=family, stopwords=STOP) == []
