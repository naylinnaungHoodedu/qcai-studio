"""Deterministic text features of the V1 checks (Phase 4 spec 4.1). Pure functions; every comparison folds the text
with NFKC and casefold, and nothing here strips a negation cue or a number (E-27: the legacy overlap gate's stopwords
stripped negation, so "is not" and "is" matched).

  tokens            WORD_PATTERN over the folded text ("don't" is one token)
  negation_cues     the tokens that are lexicon negation cues or end in a negation suffix, as a multiset
  quantities        (number, unit) pairs: a QUANTITY_PATTERN number ("," removed) with the following word as its unit
                    only when that word is "%" or a lexicon unit (a closed list: "5 noisy qubits" has no unit), plus
                    each lexicon number word with no unit
  quantities_covered  every claim quantity is matched by a distinct span quantity with the same number and unit; a
                    claim quantity with no unit may match a span quantity of the same number with any unit, because a
                    quotation may end at the number
  alignment_terms   the content terms two sentences are aligned on: not stopwords, cues or number words, not starting
                    with a digit, at least min_alignment_term_chars long
  knorm             " " + the folded text with punctuation replaced by spaces, whitespace collapsed + " ": a substring
                    test on knorm forms matches whole tokens only
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
import re
import unicodedata
from typing import TYPE_CHECKING

from app.services.v1_checks.rules import KEY_STRIP_PATTERN, QUANTITY_PATTERN, WORD_PATTERN

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config_package import V1Lexicon

_WORD = re.compile(WORD_PATTERN)
_QUANTITY = re.compile(QUANTITY_PATTERN)
_KEY_STRIP = re.compile(KEY_STRIP_PATTERN)


def fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def tokens(text: str) -> list[str]:
    return _WORD.findall(fold(text))


def is_cue(token: str, lexicon: "V1Lexicon") -> bool:
    return token in lexicon.negation_cues or token.endswith(lexicon.negation_suffixes)


def negation_cues(text: str, lexicon: "V1Lexicon") -> Counter:
    return Counter(token for token in tokens(text) if is_cue(token, lexicon))


def quantities(text: str, lexicon: "V1Lexicon") -> Counter:
    found: Counter = Counter()
    for match in _QUANTITY.finditer(fold(text)):
        unit = match.group("unit") or ""
        found[(match.group("number").replace(",", ""), unit if unit == "%" or unit in lexicon.units else "")] += 1
    for token in tokens(text):
        if token in lexicon.number_words:
            found[(token, "")] += 1
    return found


def numbers(text: str, lexicon: "V1Lexicon") -> Counter:
    values: Counter = Counter()
    for (number, _unit), count in quantities(text, lexicon).items():
        values[number] += count
    return values


def quantities_covered(claim: str, span: str, lexicon: "V1Lexicon") -> bool:
    available = quantities(span, lexicon)
    wanted = quantities(claim, lexicon)
    # Quantities with a unit need their exact pair; then each unit-less one takes any left of its number.
    for (number, unit), count in sorted(wanted.items(), key=lambda item: item[0][1] == ""):
        for _ in range(count):
            if unit:
                if available[(number, unit)] < 1:
                    return False
                available[(number, unit)] -= 1
                continue
            match = next((key for key in sorted(available) if key[0] == number and available[key] > 0), None)
            if match is None:
                return False
            available[match] -= 1
    return True


def alignment_terms(text: str, lexicon: "V1Lexicon", stopwords: Iterable[str]) -> frozenset[str]:
    stop = stopwords if isinstance(stopwords, (set, frozenset)) else frozenset(stopwords)
    return frozenset(
        token
        for token in tokens(text)
        if token not in stop
        and not is_cue(token, lexicon)
        and token not in lexicon.number_words
        and not token[0].isdigit()
        and len(token) >= lexicon.min_alignment_term_chars
    )


def jaccard(left: frozenset[str] | set[str], right: frozenset[str] | set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def knorm(text: str) -> str:
    return " " + " ".join(_KEY_STRIP.sub(" ", fold(text)).split()) + " "
