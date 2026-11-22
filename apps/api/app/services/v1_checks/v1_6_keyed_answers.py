"""V1.6, no keyed answer in an assessment context (rule keyed-answer-containment-v1, with keyed-answer-socratic-omit-v1;
plan Phase 4 D: "keyed-answer match -> HARD", EHMF E, "Socratic regen"; R-42; Phase 4 spec 4.7).

Assessment context (prompt-containment-or-jaccard-v1). Every lesson's keyed items are searched, whatever lesson the
request names (more conservative than its own lesson only). An item is in context when the resolved question names
its id (ids are hyphenated, "{lesson_slug}-quiz-{n}"; the id must stand between characters outside [a-z0-9-] or the
text's edges), or when max(Jaccard, prompt containment) of their alignment terms reaches v1.assessment_threshold.

The key whose presence leaks the answer (key_text): the answer itself when it has at least v1.short_key_min_tokens
tokens; a shorter key that names a choice (its text, a letter a-d or a digit 1-4) leaks as that choice's text when it
has enough tokens; otherwise the key cannot be matched without false alarms (short_key_unmatchable, a residual).

A rendering whose knorm text (with or without its citation markers, since a key may run across claims) holds a key of an\nitem in context hard-fails (keyed_answer_present). The runner then
re-renders with the socratic presentation plan and leaves out every locked claim that holds the key or lies inside it
(keyed_claim_ids); when that would leave no claim, the run abstains with keyed_answer_leak. A withheld keyed claim is
never delivered, so the delivered text never holds the key (AC-4-5).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Protocol

from app.services.tutor_pipeline.contracts import CheckResult, LockedClaimSet, RenderedResponse
from app.services.v1_checks.lexicon import alignment_terms, fold, jaccard, knorm
from app.services.v1_checks.results import make_result
from app.services.v1_checks.rules import CHOICE_DIGITS, CHOICE_LETTERS

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config_package import V1Params


@dataclass(frozen=True)
class KeyedItem:
    item_id: str
    lesson_slug: str
    prompt: str
    choices: tuple[str, ...]
    answer: str


class KeyedItemSource(Protocol):
    def items(self) -> tuple[KeyedItem, ...]: ...


def _names_item(question: str, item_id: str) -> bool:
    pattern = r"(?<![a-z0-9-])" + re.escape(fold(item_id)) + r"(?![a-z0-9-])"
    return re.search(pattern, fold(question)) is not None


def assessment_items(question_text: str, source: KeyedItemSource, *, v1: "V1Params", stopwords: Iterable[str]) -> tuple[KeyedItem, ...]:
    question_terms = alignment_terms(question_text, v1.lexicon, stopwords)
    found = []
    for item in source.items():
        if _names_item(question_text, item.item_id):
            found.append(item)
            continue
        prompt_terms = alignment_terms(item.prompt, v1.lexicon, stopwords)
        if not prompt_terms:
            continue
        containment = len(question_terms & prompt_terms) / len(prompt_terms)
        if max(jaccard(question_terms, prompt_terms), containment) >= v1.assessment_threshold:
            found.append(item)
    return tuple(found)


def _token_count(text: str) -> int:
    return len(knorm(text).split())


def key_text(item: KeyedItem, *, v1: "V1Params") -> str | None:
    if _token_count(item.answer) >= v1.short_key_min_tokens:
        return item.answer
    short = knorm(item.answer).strip()
    choice = next((candidate for candidate in item.choices if knorm(candidate).strip() == short), None)
    if choice is None:
        for labels in (CHOICE_LETTERS, CHOICE_DIGITS):
            if short in labels and labels.index(short) < len(item.choices):
                choice = item.choices[labels.index(short)]
    if choice is not None and _token_count(choice) >= v1.short_key_min_tokens:
        return choice
    return None


def keyed_claim_ids(locked: LockedClaimSet, items: Iterable[KeyedItem], *, v1: "V1Params") -> frozenset[str]:
    """The locked claims that hold a key, or that a key holds (a key may span several claims)."""
    keys = [knorm(text) for text in (key_text(item, v1=v1) for item in items) if text]
    keyed = set()
    for claim in locked.claims:
        claim_form = knorm(claim.text)
        if any(key in claim_form or claim_form in key for key in keys):
            keyed.add(claim.claim_id)
    return frozenset(keyed)


def check_v1_6(rendered: RenderedResponse, items: Iterable[KeyedItem], *, v1: "V1Params", attempt: int) -> CheckResult:
    items = tuple(items)
    if not items:
        return make_result("V1.6", "post_render", attempt, "not_assessment")
    keys = [key_text(item, v1=v1) for item in items]
    # The rendered text, and its words without the citation markers (a key may run across two claims).
    texts = (knorm(rendered.text), knorm(" ".join(segment.text for segment in rendered.segments if segment.kind != "citation")))
    if any(key is not None and knorm(key) in text for key in keys for text in texts):
        return make_result("V1.6", "post_render", attempt, "keyed_answer_present")
    if all(key is None for key in keys):
        return make_result("V1.6", "post_render", attempt, "short_key_unmatchable")
    return make_result("V1.6", "post_render", attempt, "key_absent")
