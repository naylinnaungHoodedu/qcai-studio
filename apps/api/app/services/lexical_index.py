"""The Phase 2 evidence index and its two gates (plan Phase 2 tasks 2.5-2.7; Phase 2 spec 3.5-3.7a).

One IndexEntry per span bound to at least one lesson. Two gates read the same entries:
- "bm25f-v1": stopword-filtered BM25F-simple (k1, b, title weight from the configuration package) with the
  coverage-v1 sufficiency rule and the provisional abstention floor and margin; ties break by span_id.
- "p1-floor": the approved Phase 1 floor (P1-D-04, score-floor-p1-v1) applied to the span index, which in the
  governed D-31 configuration returns exactly today's results. It stays the default outside development until a
  D-05 remediation release switches (spec conflict 26).
Video chapter summaries are never entries (task 2.7). Nothing here takes a learner, history or page input
(invariant 1; AC-2-9): a query, an optional lesson filter and a result count are the only inputs.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
import math
import re
import unicodedata
from typing import Literal

from app.core.config_package import AbstentionParams, RetrievalParams
from app.services.retrieval_p1 import QUERY_STOPWORDS, SCORE_FLOOR, SCORE_FLOOR_VERSION, _floor_score, _tokenize

ALGORITHM = "bm25f-simple-v1"
TOKEN_PATTERN = re.compile(r"[^\W_]+")
Gate = Literal["p1-floor", "bm25f-v1"]
Reason = Literal["evidence", "no_query_terms", "no_match", "insufficient_coverage", "below_floor"]


@dataclass(frozen=True)
class IndexEntry:
    span_id: str
    item_id: str
    item_version: str
    item_kind: Literal["document", "authored"]
    section_ordinal: int
    start: int
    end: int
    content_hash: str
    title: str
    source_kind: Literal["document", "lesson"]
    source_title: str
    excerpt: str
    source_filename: str | None
    lesson_slugs: tuple[str, ...]
    module_indexes: tuple[int, ...]
    title_words: frozenset[str]
    excerpt_words: frozenset[str]
    timestamp_label: None = None

    @property
    def chunk_id(self) -> str:
        return self.span_id

    @property
    def lesson_slug(self) -> str:
        return self.lesson_slugs[0]


def tokenize(text: str, params: RetrievalParams) -> list[str]:
    """nfkc-casefold-alnum-v1: NFKC, casefold, alphanumeric runs, minimum length, stopwords-v1 removed; no stemming."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return [token for token in TOKEN_PATTERN.findall(normalized) if len(token) >= params.min_token_length and token not in params.stopwords]


@dataclass(frozen=True)
class ScoredEntry:
    entry: IndexEntry
    score: float
    matched_terms: int
    near_floor: bool
    # p1-floor: the lesson whose module boost the score used; bm25f-v1: None (the first bound lesson is shown).
    lesson_slug: str | None = None


@dataclass(frozen=True)
class RetrievalDecision:
    abstained: bool
    reason: Reason
    results: tuple[ScoredEntry, ...]
    query_terms: tuple[str, ...]
    gate: Gate
    floor: float
    margin: float
    threshold_version: str


class LexicalIndex:
    def __init__(self, entries: Sequence[IndexEntry], params: RetrievalParams, abstention: AbstentionParams, *, gate: Gate) -> None:
        if gate not in ("p1-floor", "bm25f-v1"):
            raise ValueError(f"Unknown retrieval gate {gate!r}")
        self.entries = tuple(entries)
        self.params = params
        self.abstention = abstention
        self.gate: Gate = gate
        self._body_tf: list[Counter[str]] = []
        self._title_tf: list[Counter[str]] = []
        self._tf: list[dict[str, float]] = []
        self._length: list[float] = []
        document_frequency: Counter[str] = Counter()
        for entry in self.entries:
            body = Counter(tokenize(entry.excerpt, params))
            title = Counter(tokenize(entry.title, params))
            weighted: dict[str, float] = {term: float(count) for term, count in body.items()}
            for term, count in title.items():
                weighted[term] = weighted.get(term, 0.0) + params.title_weight * count
            self._body_tf.append(body)
            self._title_tf.append(title)
            self._tf.append(weighted)
            self._length.append(sum(body.values()) + params.title_weight * sum(title.values()))
            document_frequency.update(weighted.keys())
        self._df = document_frequency
        self._n = len(self.entries)
        self._average_length = (sum(self._length) / self._n) if self._n else 0.0
        self._position = {entry.span_id: index for index, entry in enumerate(self.entries)}

    @property
    def threshold_version(self) -> str:
        return self.thresholds[2]

    @property
    def thresholds(self) -> tuple[float, float, str]:
        """(floor, margin, threshold_version) of the active gate: P1-D-04's floor 6 for p1-floor, the package's
        provisional calibrated floor and margin for bm25f-v1."""
        if self.gate == "p1-floor":
            return float(SCORE_FLOOR), 0.0, SCORE_FLOOR_VERSION
        return self.abstention.floor, self.abstention.margin, self.abstention.version

    # --- bm25f-v1 ---

    def query_terms(self, query: str) -> tuple[str, ...]:
        return tuple(sorted(set(tokenize(query, self.params))))

    def idf(self, term: str) -> float:
        df = self._df.get(term, 0)
        return math.log(1 + (self._n - df + 0.5) / (df + 0.5))

    def score_entry(self, terms: tuple[str, ...], entry: IndexEntry) -> tuple[float, int, bool]:
        """(BM25F score, matched query terms, coverage-v1 eligible)."""
        index = self._position[entry.span_id]
        tf = self._tf[index]
        k1, b = self.params.k1, self.params.b
        norm = (1 - b + b * self._length[index] / self._average_length) if self._average_length else 1.0
        score = 0.0
        matched = 0
        for term in terms:
            frequency = tf.get(term, 0.0)
            if frequency > 0:
                matched += 1
                score += self.idf(term) * frequency * (k1 + 1) / (frequency + k1 * norm)
        if len(terms) >= 2:
            eligible = matched >= 2
        elif len(terms) == 1:
            eligible = self._title_tf[index].get(terms[0], 0) > 0
        else:
            eligible = False
        return score, matched, eligible

    def _bm25_scored(self, terms: tuple[str, ...], entry: IndexEntry) -> ScoredEntry | None:
        score, matched, eligible = self.score_entry(terms, entry)
        if not eligible:
            return None
        rounded = round(score, 9)
        return ScoredEntry(entry, rounded, matched, rounded < self.abstention.floor + self.abstention.margin)

    def eligible_unfloored(self, query: str) -> list[ScoredEntry]:
        """bm25f-v1 coverage-eligible entries before the floor, best first (calibration input)."""
        terms = self.query_terms(query)
        if not terms:
            return []
        scored = [item for entry in self.entries if (item := self._bm25_scored(terms, entry)) is not None]
        scored.sort(key=lambda item: (-item.score, item.entry.span_id))
        return scored

    # --- p1-floor ---

    def p1_score_entry(self, query: str, entry: IndexEntry, lesson_slug: str | None) -> tuple[float, bool, str, bool]:
        """(score, passes the P1 floor, boost lesson, matched at all) for one entry, as Phase 1 scored it."""
        query_terms = {token for token in _tokenize(query) if token}
        floor_terms = query_terms - QUERY_STOPWORDS
        raw = query.strip().lower()
        title_text = entry.title.lower()
        excerpt_text = entry.excerpt.lower()
        title_overlap = sum(1 for term in query_terms if term in title_text)
        excerpt_overlap = sum(1 for term in query_terms if term in excerpt_text)
        phrase_bonus = 0
        if len(raw) >= 3:
            phrase_bonus = 4 if raw in title_text else 2 if raw in excerpt_text else 0
        matched = not (title_overlap == 0 and excerpt_overlap == 0 and phrase_bonus == 0)
        passes = matched and _floor_score(floor_terms, entry, phrase_bonus) >= SCORE_FLOOR
        if lesson_slug and lesson_slug in entry.lesson_slugs:
            boost_lesson = lesson_slug
            module_index = entry.module_indexes[entry.lesson_slugs.index(lesson_slug)]
        else:
            # The best-ranked of Phase 1's duplicates: the highest module, first in blueprint order on a tie.
            position = max(range(len(entry.lesson_slugs)), key=lambda i: (entry.module_indexes[i], -i))
            boost_lesson = entry.lesson_slugs[position]
            module_index = entry.module_indexes[position]
        boost = module_index + (0.1 if entry.item_kind == "authored" else 0.0)
        score = round(title_overlap * 3 + excerpt_overlap * 2 + phrase_bonus + boost, 3)
        return score, passes, boost_lesson, matched

    # --- either gate ---

    def gate_entry(self, query: str, entry: IndexEntry, lesson_slug: str | None) -> ScoredEntry | None:
        """The active gate applied to one entry; hybrid retrieval re-gates every semantic result with it."""
        if lesson_slug and lesson_slug not in entry.lesson_slugs:
            return None
        if self.gate == "p1-floor":
            if not query.strip():
                return None
            score, passes, boost_lesson, _ = self.p1_score_entry(query, entry, lesson_slug)
            return ScoredEntry(entry, score, 0, False, boost_lesson) if passes else None
        scored = self._bm25_scored(self.query_terms(query), entry)
        if scored is None or scored.score < self.abstention.floor:
            return None
        return scored

    def evaluate(self, query: str, lesson_slug: str | None = None, top_k: int = 8) -> RetrievalDecision:
        if self.gate == "p1-floor":
            return self._evaluate_p1(query, lesson_slug, top_k)
        return self._evaluate_bm25(query, lesson_slug, top_k)

    def _decision(self, reason: Reason, results: list[ScoredEntry], terms: tuple[str, ...]) -> RetrievalDecision:
        floor, margin, version = self.thresholds
        return RetrievalDecision(
            abstained=not results,
            reason=reason if not results else "evidence",
            results=tuple(results),
            query_terms=terms,
            gate=self.gate,
            floor=floor,
            margin=margin,
            threshold_version=version,
        )

    def _evaluate_bm25(self, query: str, lesson_slug: str | None, top_k: int) -> RetrievalDecision:
        terms = self.query_terms(query)
        if not terms:
            return self._decision("no_query_terms", [], terms)
        any_match = any_eligible = False
        results: list[ScoredEntry] = []
        for entry in self.entries:
            if lesson_slug and lesson_slug not in entry.lesson_slugs:
                continue
            score, matched, eligible = self.score_entry(terms, entry)
            any_match = any_match or matched >= 1
            if not eligible:
                continue
            any_eligible = True
            rounded = round(score, 9)
            if rounded < self.abstention.floor:
                continue
            results.append(ScoredEntry(entry, rounded, matched, rounded < self.abstention.floor + self.abstention.margin))
        results.sort(key=lambda item: (-item.score, item.entry.span_id))
        reason: Reason = "evidence" if results else "below_floor" if any_eligible else "insufficient_coverage" if any_match else "no_match"
        return self._decision(reason, results[:top_k], terms)

    def _evaluate_p1(self, query: str, lesson_slug: str | None, top_k: int) -> RetrievalDecision:
        terms = tuple(sorted({token for token in _tokenize(query) if token}))
        if not query.strip().lower():
            return self._decision("no_query_terms", [], terms)
        any_match = False
        results: list[ScoredEntry] = []
        for entry in self.entries:
            if lesson_slug and lesson_slug not in entry.lesson_slugs:
                continue
            score, passes, boost_lesson, matched = self.p1_score_entry(query, entry, lesson_slug)
            any_match = any_match or matched
            if passes:
                results.append(ScoredEntry(entry, score, 0, False, boost_lesson))
        results.sort(key=lambda item: item.score, reverse=True)  # stable on index order, as Phase 1 sorted
        reason: Reason = "evidence" if results else "below_floor" if any_match else "no_match"
        return self._decision(reason, results[:top_k], terms)
