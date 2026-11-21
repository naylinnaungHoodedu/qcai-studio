"""V1.7, conflicting cited spans are disclosed or withheld (rule conflict-version-polarity-v1; plan Phase 4 D:
"contradiction without disclosure block", EHMF D, "disclose/fail"; R-19; Phase 4 spec 4.8 and conflict 33).

Over the cited spans of one response (the locked set's spans; the bundle names each span's item):
  version_of_same_asset   two cited spans of different items in one v1.version_families family (one pair per item
                          pair, naming every cited span of both items and the claims that cite them)
  number_disagreement     a locked claim and a whole sentence of a cited span of another item align (each has at
                          least v1.min_alignment_terms alignment terms, Jaccard >= v1.alignment_threshold), both hold
                          numbers, and their number values differ (units are V1.2's concern)
  negation_disagreement   they align, and the parities of their negation-cue counts differ
No pair: pass / no_conflict. Otherwise a DisclosureBlock with policy v1.on_conflict: disclose (labels which spans
disagree; no new claim) gives flag / conflict_disclosed and the label conflict_disclosed; withhold gives
flag / conflict_withheld and every claim in a pair is withheld. Precedence between the sources ("newer peer-reviewed
over older") is Phase 7's.

The shipped family is the 2025/2026 lecture video (Q-10, E-21): video spans are never cited and the 2026 item is
unbound, so in production disclosure can come only from a number or negation disagreement. legacy_conflicts applies
the same rule to the quotations of a contained answer: the evidence panel labels what it finds, and while the panel
is off (its default outside development) the legacy guard withholds the answer instead (AC-4-6).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from itertools import combinations
from typing import TYPE_CHECKING

from app.schemas import EvidenceConflict
from app.services.tutor_pipeline.contracts import CheckResult, ConflictPair, DisclosureBlock, EvidenceBundle, LockedClaimSet
from app.services.tutor_pipeline.text import split_sentences
from app.services.v1_checks.lexicon import alignment_terms, jaccard, negation_cues, numbers
from app.services.v1_checks.results import make_result
from app.services.v1_checks.rules import MAX_CONFLICT_SPANS, MAX_DISCLOSED_CONFLICTS, PAIR, PARITY

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config_package import V1Params
    from app.schemas import Citation


def disagreement(left: str, right: str, *, v1: "V1Params", stopwords: Iterable[str]) -> str | None:
    """number_disagreement, negation_disagreement or None for two aligned sentences (rule conflict-version-polarity-v1)."""
    lexicon = v1.lexicon
    left_terms, right_terms = alignment_terms(left, lexicon, stopwords), alignment_terms(right, lexicon, stopwords)
    if len(left_terms) < v1.min_alignment_terms or len(right_terms) < v1.min_alignment_terms:
        return None
    if jaccard(left_terms, right_terms) < v1.alignment_threshold:
        return None
    left_numbers, right_numbers = numbers(left, lexicon), numbers(right, lexicon)
    if left_numbers and right_numbers and left_numbers != right_numbers:
        return "number_disagreement"
    if sum(negation_cues(left, lexicon).values()) % PARITY != sum(negation_cues(right, lexicon).values()) % PARITY:
        return "negation_disagreement"
    return None


def _pair(kind: str, span_ids: Iterable[str], items: Iterable[str], claim_ids: Iterable[str]) -> ConflictPair:
    return ConflictPair(kind=kind, span_ids=tuple(sorted(set(span_ids)))[:MAX_CONFLICT_SPANS], item_ids=tuple(sorted(set(items))),
                        claim_ids=tuple(sorted(set(claim_ids))))


def check_v1_7(
    locked: LockedClaimSet,
    bundle: EvidenceBundle,
    *,
    sentences_of: Callable[[str], tuple[str, ...]],
    v1: "V1Params",
    stopwords: Iterable[str],
    attempt: int,
) -> tuple[CheckResult, DisclosureBlock | None]:
    item_of = {span.span_id: span.item_id for span in bundle.spans}
    cited = [span_id for span_id in locked.span_ids if span_id in item_of]
    pairs: dict[tuple, ConflictPair] = {}
    by_item: dict[str, list[str]] = {}
    for span_id in cited:
        by_item.setdefault(item_of[span_id], []).append(span_id)
    for left, right in combinations(sorted(by_item), PAIR):
        family = v1.version_families.get(left)
        if family is None or v1.version_families.get(right) != family:
            continue
        spans = [*by_item[left], *by_item[right]]
        claims = [claim.claim_id for claim in locked.claims if set(claim.span_ids) & set(spans)]
        pair = _pair("version_of_same_asset", spans, (left, right), claims)
        pairs[(pair.kind, pair.span_ids)] = pair
    for claim in locked.claims:
        own_items = {item_of[span_id] for span_id in claim.span_ids if span_id in item_of}
        for other in cited:
            if item_of[other] in own_items:
                continue
            for sentence in sentences_of(other):
                kind = disagreement(claim.text, sentence, v1=v1, stopwords=stopwords)
                if kind is None:
                    continue
                own = [span_id for span_id in claim.span_ids if span_id in item_of]
                for span_id in own:
                    pair = _pair(kind, (span_id, other), (item_of[span_id], item_of[other]), (claim.claim_id,))
                    key = (pair.kind, pair.span_ids)
                    if key in pairs:
                        pair = _pair(kind, pair.span_ids, pair.item_ids, (*pairs[key].claim_ids, claim.claim_id))
                    pairs[key] = pair
    if not pairs:
        return make_result("V1.7", "pre_render", attempt, "no_conflict"), None
    ordered = tuple(pairs[key] for key in sorted(pairs))[:MAX_DISCLOSED_CONFLICTS]
    block = DisclosureBlock(policy=v1.on_conflict, conflicts=ordered)
    reason = "conflict_disclosed" if v1.on_conflict == "disclose" else "conflict_withheld"
    return make_result("V1.7", "pre_render", attempt, reason), block


def legacy_conflicts(citations: Sequence["Citation"], *, v1: "V1Params", stopwords: Iterable[str]) -> list[EvidenceConflict]:
    """The same rule over a contained answer's quotations (from different items), for the evidence panel and the
    legacy guard: version families, and the sentences-v2 pieces of each quotation. Passages are 1-based panel positions."""
    found: list[EvidenceConflict] = []
    seen: set[tuple] = set()
    for (index_a, left), (index_b, right) in combinations(list(enumerate(citations, start=1)), PAIR):
        if not left.item_id or not right.item_id or left.item_id == right.item_id:
            continue
        kinds = []
        family = v1.version_families.get(left.item_id)
        if family is not None and v1.version_families.get(right.item_id) == family:
            kinds.append("version_of_same_asset")
        for piece_a in split_sentences(left.excerpt):
            for piece_b in split_sentences(right.excerpt):
                kind = disagreement(piece_a, piece_b, v1=v1, stopwords=stopwords)
                if kind is not None:
                    kinds.append(kind)
        for kind in dict.fromkeys(kinds):
            if (kind, index_a, index_b) not in seen:
                seen.add((kind, index_a, index_b))
                found.append(EvidenceConflict(kind=kind, passages=[index_a, index_b]))
    return found
