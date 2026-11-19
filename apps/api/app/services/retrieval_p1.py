"""The Phase 1 score floor (plan Action 27, R-15, AC-1-11), approved as P1-D-04.

Moved verbatim from content_assembler.py in Phase 2; content_assembler re-exports these names. The floor is the
`p1-floor` retrieval gate (configuration package v1, `gates.p1-floor`), which stays the default outside
development until a D-05 remediation release switches to `bm25f-v1` (Phase 2 spec, conflict 26).

A passage is returned only when its floor score reaches SCORE_FLOOR. The floor score counts whole-word matches
of the question's non-stopword terms (3 per heading match, 2 per text match) plus the phrase bonus, and leaves
out the module boost, so one shared word (at most 5) never passes. Ranking still uses the full score.
Evidence: BEP-1/27_score_floor/PROPOSAL.md.
"""

from dataclasses import dataclass, field

SCORE_FLOOR_VERSION = "score-floor-p1-v1"
SCORE_FLOOR = 6
QUERY_STOPWORDS = frozenset(
    """
    about above after again all also always and any anyone anything are aren because been before being below
    between both but can can't could describe did didn does doesn doesn't doing don don't done down during each
    even ever everything explain few for from further get gets give got had has have hello her here hers hey him
    his how into isn isn't its itself just kind know let lets like made make makes many may mean means meant
    might more most much must myself need never nor not nothing now off often okay once one ones only onto other
    our ours ourselves out over own per please really said same say shall she should some someone something
    still such tell than thank thanks that the their theirs them themselves then there these they thing things
    think this those through too under until upon use used uses using very via want was way ways well were what
    when where which while who whom whose why will with without won work works would yes yet you your yours
    yourself
    """.split()
)


@dataclass
class IndexedChunk:
    chunk_id: str
    title: str
    source_kind: str
    source_title: str
    excerpt: str
    lesson_slug: str | None
    score_boost: float
    timestamp_label: str | None = None
    # Set only for spans of a source document; video chapters and authored notes are not quotable spans.
    source_filename: str | None = None
    title_words: frozenset[str] = field(init=False, repr=False)
    excerpt_words: frozenset[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.title_words = frozenset(_tokenize(self.title))
        self.excerpt_words = frozenset(_tokenize(self.excerpt))


def _tokenize(text: str) -> list[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return [token for token in cleaned.split() if len(token) > 2]


def _floor_score(floor_terms: set[str], chunk, phrase_bonus: int) -> int:
    # Duck-typed: an IndexedChunk (Phase 1) or a Phase 2 IndexEntry, both with title_words and excerpt_words.
    title_hits = sum(1 for term in floor_terms if term in chunk.title_words)
    excerpt_hits = sum(1 for term in floor_terms if term in chunk.excerpt_words)
    return title_hits * 3 + excerpt_hits * 2 + phrase_bonus
