"""Claim binding, rule resolver-bundle-sentence-v2 (plan tasks 3.3-3.4; Phase 3 spec 4.6; R-11, R-13).

Every proposed claim is validated against the spans it cites, and dropped whole on the first failing check:
  unbound          it cites no span
  outside_bundle   a cited span is not in the evidence bundle
  unresolvable     the Phase 2 SpanResolver does not resolve it, or its content hash differs from the bundle's
  not_quotable     a cited span is not a quotable (public-plane, bound, approved) document span (D-19, D-31)
  partial_sentence the claim is a piece of a cited span's own text that the span cuts out of a longer document
                   sentence: the span starts or ends inside that sentence (spec 18.10 H1)
  not_verbatim     the claim is not a whole sentence of EVERY cited span (whole_sentences), or the cited spans hold
                   the sentence in different characters
  duplicate        the same sentence was already bound on all of the spans it cites
A claim is never re-bound to a span it did not cite: Phase 1's overlap rebinding is gone (plan 3.4).

A whole sentence of a span (whole_sentences) is a sentences-v2 sentence of the span's section text that lies wholly
inside the span: it starts and ends at sentences-v2 boundaries of the document, never at a span edge. No entailment
checker exists before Phase 4, so this is what keeps a truncated sentence that drops a qualification or a negation
from binding. Until spec 18.10 H1 (rule resolver-bundle-sentence-v1) the sentences were cut from the span's own text,
whose first and last pieces can begin or end mid-sentence (spans are splitter chunks), so 42 of 263 locked claims in
the replay were fragments of a document sentence, one with its "fail to" dropped.

What is locked is the span's own sentence (whitespace() form), never the generator's text: NFKC is used only to
compare (spec conflict 32; D-19 "verbatim"), so a generator that folds "x²" to "x2" binds, but the locked, ledgered
and rendered claim still reads "x²". A sentence proposed again on other spans that also hold it verbatim (the
splitter overlaps chunks, so one sentence can sit in two adjacent spans) is merged into the first claim, whose span
set becomes the union; it is counted as "merged", never as a binding failure (contracts.bound_claim_ratio_terms).
Each draft carries its sentence's own place in the source, (item_id, the item offset of its first character), the
earliest over the spans it cites, so the stepwise plan's "in source order" holds for two sentences of one span
(spec 18.10 H2).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.core.config_package import TutorPipelineParams
from app.core.corpus_governance import CorpusRegistry
from app.services.contained_answers import span_is_quotable
from app.services.tutor_pipeline.contracts import (
    BINDING_FAILURES,
    MERGED,
    PARTIAL_SENTENCE,
    ClaimPlan,
    EvidenceBundle,
    ledger_canonical,
    sha256_hex,
)
from app.services.tutor_pipeline.text import normalise, sentence_bounds, sentences, whitespace

if TYPE_CHECKING:  # pragma: no cover
    from app.services.content_assembler import CourseStore
    from app.services.span_resolver import SpanResolver
    from app.services.spans import SpanRecord

BINDING_RULE = "resolver-bundle-sentence-v2"
# What bind() counts in BindResult.dropped: every binding failure, and "merged" (which is not a failure).
DROP_REASONS = (*BINDING_FAILURES, MERGED)


@dataclass(frozen=True)
class SpanSentence:
    """A whole sentence of a span: its whitespace() text, as the span holds it, and the item offset of its first
    character."""

    text: str
    position: int


@dataclass(frozen=True)
class LockedClaimDraft:
    claim_id: str
    text: str
    span_ids: tuple[str, ...]
    # (item_id, item offset of the sentence's first character): the earliest over the cited spans (spec 18.10 H2).
    source_order: tuple[str, int]


@dataclass(frozen=True)
class BindResult:
    bound: tuple[LockedClaimDraft, ...]
    dropped: Counter = field(default_factory=Counter)
    proposed: int = 0


def claim_id_for(text: str, span_ids) -> str:
    """Content-addressed: the same claim on the same spans has the same id in every plan and response."""
    return "claim-" + sha256_hex(ledger_canonical({"text": normalise(text), "span_ids": sorted(span_ids)}))[:32]


def _whole_bounds(record: "SpanRecord", store: "CourseStore") -> tuple[tuple[int, int], ...]:
    """The span-local (start, end) of each sentences-v2 sentence of the record's section that lies wholly inside the
    span. Empty when the store does not hold the record's section text exactly (fail closed: nothing of it binds)."""
    item = (getattr(store, "items", None) or {}).get(record.item_id)
    if item is None:
        return ()
    section = next((candidate for candidate in item.sections if candidate.ordinal == record.section_ordinal), None)
    if section is None:
        return ()
    local_start = record.start - section.body_start
    local_end = record.end - section.body_start
    if local_start < 0 or local_end > len(section.body) or section.body[local_start:local_end] != record.text:
        return ()
    return tuple(
        (begin - local_start, end - local_start)
        for begin, end in sentence_bounds(section.body)
        if local_start <= begin and end <= local_end
    )


def whole_sentences(record: "SpanRecord", store: "CourseStore", *, min_words: int, max_chars: int) -> tuple[SpanSentence, ...]:
    """The span's whole sentences (rule resolver-bundle-sentence-v2): sentences-v2 sentences of its section text
    lying wholly inside the span, with at least min_words words and at most max_chars characters, in text order."""
    found = []
    for begin, end in _whole_bounds(record, store):
        text = whitespace(record.text[begin:end])
        if len(text.split()) >= min_words and len(text) <= max_chars:
            found.append(SpanSentence(text=text, position=record.start + begin))
    return tuple(found)


def whole_sentence_text(record: "SpanRecord", store: "CourseStore") -> str | None:
    """The span's own characters from the start of its first whole sentence to the end of its last (the evidential
    envelope's text for the span), or None when the span holds no whole sentence. Cut under sentences-v2, it yields
    exactly the span's whole sentences, so a generator that quotes it never proposes a span-edge fragment."""
    bounds = _whole_bounds(record, store)
    if not bounds:
        return None
    return record.text[bounds[0][0] : bounds[-1][1]]


def bind(
    plan: ClaimPlan,
    bundle: EvidenceBundle,
    *,
    resolver: "SpanResolver",
    store: "CourseStore",
    registry: CorpusRegistry,
    params: TutorPipelineParams,
) -> BindResult:
    in_bundle = {span.span_id: span for span in bundle.spans}
    # Bound sentences in first-bound order: (normalised, verbatim) -> the union of the spans that cite it, and the
    # earliest (item_id, position) of the sentence among them.
    bound: dict[tuple[str, str], set[str]] = {}
    places: dict[tuple[str, str], tuple[str, int]] = {}
    dropped: Counter = Counter()
    sentence_cache: dict[str, dict[str, SpanSentence]] = {}
    piece_cache: dict[str, frozenset[str]] = {}

    def sentences_of(span_id: str) -> dict[str, SpanSentence]:
        """The span's whole sentences: normalised form -> the span's own (whitespace-collapsed) sentence."""
        if span_id not in sentence_cache:
            record = store.span_registry.get(span_id)
            found: dict[str, SpanSentence] = {}
            if record is not None:
                for sentence in whole_sentences(record, store, min_words=params.min_sentence_words, max_chars=params.max_sentence_chars):
                    found.setdefault(normalise(sentence.text), sentence)
            sentence_cache[span_id] = found
        return sentence_cache[span_id]

    def pieces_of(span_id: str) -> frozenset[str]:
        """The sentences-v2 pieces of the span's own text (normalised), span-edge fragments included."""
        if span_id not in piece_cache:
            record = store.span_registry.get(span_id)
            text = record.text if record is not None else ""
            piece_cache[span_id] = frozenset(
                normalise(piece) for piece in sentences(text, min_words=params.min_sentence_words, max_chars=params.max_sentence_chars)
            )
        return piece_cache[span_id]

    for claim in plan.claims:
        span_ids = tuple(sorted(set(claim.span_ids)))
        reason = None
        if not span_ids:
            reason = "unbound"
        elif any(span_id not in in_bundle for span_id in span_ids):
            reason = "outside_bundle"
        else:
            for span_id in span_ids:
                resolved = resolver.resolve_current(span_id)
                if resolved is None or resolved.content_hash != in_bundle[span_id].content_hash:
                    reason = "unresolvable"
                    break
            if reason is None:
                for span_id in span_ids:
                    record = store.span_registry.get(span_id)
                    if record is None or not span_is_quotable(record, registry):
                        reason = "not_quotable"
                        break
            if reason is None:
                key = normalise(claim.text)
                found = [sentences_of(span_id).get(key) for span_id in span_ids]
                if any(sentence is None for sentence in found):
                    # A piece of every cited span's text, but on at least one a span-edge fragment, not a sentence.
                    edge_cut = all(sentence is not None or key in pieces_of(span_id) for span_id, sentence in zip(span_ids, found))
                    reason = PARTIAL_SENTENCE if edge_cut else "not_verbatim"
                elif len({sentence.text for sentence in found}) != 1:
                    reason = "not_verbatim"
                else:
                    merge_key = (key, found[0].text)
                    place = min((in_bundle[span_id].item_id, sentence.position) for span_id, sentence in zip(span_ids, found))
                    spans = bound.get(merge_key)
                    if spans is None:
                        bound[merge_key] = set(span_ids)
                        places[merge_key] = place
                    elif set(span_ids) <= spans:
                        reason = "duplicate"
                    else:
                        spans.update(span_ids)
                        places[merge_key] = min(places[merge_key], place)
                        reason = MERGED
        if reason is not None:
            dropped[reason] += 1
    drafts = tuple(
        LockedClaimDraft(claim_id=claim_id_for(text, spans), text=text, span_ids=tuple(sorted(spans)), source_order=places[(key, text)])
        for (key, text), spans in bound.items()
    )
    return BindResult(bound=drafts, dropped=dropped, proposed=len(plan.claims))
