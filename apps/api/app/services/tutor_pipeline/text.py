"""Text helpers of the two-channel tutor (Phase 3 spec 4.1; conflict 32).

whitespace() is the verbatim surface that is stored, locked, ledgered and rendered: the span's own characters with
whitespace runs collapsed, never NFKC-folded (D-19 "verbatim"). normalise() adds NFKC and is used only to compare
(binding and the subset check), so a superscript or a ligature never changes what a learner would read.

sentences() is rule sentences-v2 (it replaced sentences-v1, which split after every ". " and so cut quotations at
"e.g.", "et al.", "Fig. 3" or "Dr."; plan Phase 3 M residual "misleading wording within locked claims"). A boundary is
whitespace after ".", "!" or "?", except after a period that ends:
  - a common abbreviation or title (ALWAYS_ABBREVIATIONS: e.g., i.e., vs., cf., Dr., Prof., approx. ...);
  - "et al.";
  - a reference abbreviation (Fig., Eq., Sec., Ref., No., Vol., pp. ...) followed by a number or a bracket;
  - dotted initials (U.S., a.k.a.), or a single capital initial followed by a capitalised word or a bracket
    (J. Preskill; "Petruccione, F. (2021)");
or when the next word starts with a lowercase letter (an unknown abbreviation; a new sentence starts with a
capital, a digit or a symbol). Decimal numbers and version strings (3.14, v1.2.3, Python 3.11) hold no whitespace
after their periods, so they are never split. When in doubt the rule keeps text together: a merged quotation is
longer but still verbatim, while a split one can drop its qualification.
"""

from __future__ import annotations

import re
import unicodedata

from app.core.config_package import RetrievalParams
from app.services import lexical_index

SENTENCE_RULE = "sentences-v2"
_CANDIDATE = re.compile(r"(?<=[.!?])\s+")
# Lower-cased, without the final period. A period after one of these never ends a sentence.
ALWAYS_ABBREVIATIONS = frozenset(
    {"e.g", "i.e", "vs", "cf", "ca", "approx", "viz", "resp", "incl", "dr", "mr", "mrs", "ms", "prof", "a.k.a"}
)
# A period after one of these does not end a sentence when a number or a bracket follows ("Fig. 3", "Eq. (2)").
REFERENCE_ABBREVIATIONS = frozenset(
    {"fig", "figs", "eq", "eqs", "sec", "secs", "ref", "refs", "no", "nos", "vol", "ch", "chap", "pp", "p", "tab", "thm", "app"}
)
_DOTTED_INITIALS = re.compile(r"^(?:[A-Za-z]\.){2,}$")
_LEADING_PUNCTUATION = "([{\"'‘“"


def whitespace(text: str) -> str:
    return " ".join(text.split())


def normalise(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _is_boundary(before: str, after: str) -> bool:
    """Whether the whitespace between `before` (the text up to and including the punctuation) and `after` ends a
    sentence (rule sentences-v2)."""
    if not after:
        return True
    if not before.endswith("."):
        return True  # "!" and "?" always end a sentence
    first = after[0]
    if first.islower():
        return False
    token = before.rsplit(" ", 1)[-1].lstrip(_LEADING_PUNCTUATION)
    word = token[:-1].lower()
    if word in ALWAYS_ABBREVIATIONS or _DOTTED_INITIALS.match(token):
        return False
    if word == "al" and before[: -len(token)].rstrip().lower().endswith("et"):
        return False
    if word in REFERENCE_ABBREVIATIONS and (first.isdigit() or first in "([" or (first.isupper() and len(after) > 1 and after[1].isdigit())):
        return False
    if len(token) == 2 and token[0].isupper() and (first.isupper() or first == "("):
        return False  # a single initial: "J. Preskill", "Schuld, M., & Petruccione, F. (2021)"
    return True


def split_sentences(text: str) -> list[str]:
    """Whitespace-normalised text cut at sentences-v2 boundaries (no length filter)."""
    flat = whitespace(text)
    parts: list[str] = []
    start = 0
    for match in _CANDIDATE.finditer(flat):
        if _is_boundary(flat[start : match.start()], flat[match.end() :]):
            parts.append(flat[start : match.start()])
            start = match.end()
    parts.append(flat[start:])
    return [part for part in parts if part]


def sentences(text: str, *, min_words: int, max_chars: int) -> list[str]:
    """sentences-v2 sentences with at least min_words words and at most max_chars characters (both from the
    configuration package, tutor_pipeline.evidential)."""
    return [part for part in split_sentences(text) if len(part.split()) >= min_words and len(part) <= max_chars]


def content_terms(text: str, params: RetrievalParams) -> frozenset[str]:
    """The package tokenizer (nfkc-casefold-alnum-v1) with stopwords-v1 removed."""
    return frozenset(lexical_index.tokenize(text, params))
