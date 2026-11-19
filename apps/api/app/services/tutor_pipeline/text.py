"""Text helpers of the two-channel tutor (Phase 3 spec 4.1; conflict 32).

whitespace() is the verbatim surface that is stored, locked, ledgered and rendered: the span's own characters with
whitespace runs collapsed, never NFKC-folded (D-19 "verbatim"). normalise() adds NFKC and is used only to compare
(binding and the subset check), so a superscript or a ligature never changes what a learner would read.
"""

from __future__ import annotations

import re
import unicodedata

from app.core.config_package import RetrievalParams
from app.services import lexical_index

SENTENCE_RULE = "sentences-v1"
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def whitespace(text: str) -> str:
    return " ".join(text.split())


def normalise(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def sentences_v1(text: str, *, min_words: int, max_chars: int = 1000) -> list[str]:
    """Whitespace-normalised sentences split after . ! or ?, with at least min_words words and at most max_chars."""
    return [part for part in SENTENCE_SPLIT.split(whitespace(text)) if len(part.split()) >= min_words and len(part) <= max_chars]


def content_terms(text: str, params: RetrievalParams) -> frozenset[str]:
    """The package tokenizer (nfkc-casefold-alnum-v1) with stopwords-v1 removed."""
    return frozenset(lexical_index.tokenize(text, params))
