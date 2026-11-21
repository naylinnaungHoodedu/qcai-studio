"""Subset checker, rule segment-exact-whitespace-v3 (plan Phase 3 E: "claim_gate becomes the subset checker";
task 3.7; Phase 3 spec 4.9). It is V1.4 (Phase 4 spec 4.5): v1_checks.v1_4_subset maps its result, which
render_checked computes through the pipeline module's check_subset, and no second implementation exists.

The overlap ClaimGate and evidence_digest are gone (plan 3.4: "overlap rebinding removed", R-13): nothing binds a
sentence to whichever citation shares its words. Instead every factual segment of a rendered response must name a
locked claim (its claim_id) and carry that claim's text exactly, whitespace runs aside, and every citation must be
one of that claim's locked spans. The text comparison is never NFKC-folded: the locked text is the span's own
(spec conflict 32), so a rendering that turns "x²" into "x2" or "½" into "1⁄2" changes what a learner reads and is
an unmapped factual sentence. Claims are looked up by id, not by text, so two locked claims with the same sentence
can both be rendered. Questions and connectives are typed by the renderer, never detected heuristically; a
non-factual segment whose text is not its template's text counts as an unmapped factual sentence. The caller
regenerates (at most twice), then abstains.

A rendering also fails when it shows no locked claim at all (no_claim_rendered: an "answer" of connectives only),
or when a claim it shows carries none of its own locked spans on its line (claim_uncited: a factual sentence a
learner could not trace). A renderer may still leave some locked claims out (missing_claims is reported, not
failed); the ledger records which claims and spans the passing rendering showed (spec 18.6 D4), taken from the
segments it displayed (displayed_span_ids), never from the renderer's own list.

That list must say what was displayed (citation_list_mismatch, spec 18.7 E1): rendered.citations must be exactly
the displayed citation spans, each once, in the order they first appear. A rendering that declares a span it never
shows, lists one twice or out of order fails, so no record can name a citation the learner did not see and marker
numbers never skip ([2] with no [1]).

Rule ids: v1 ("segment-exact-normalised-v1") compared NFKC-folded text; it was replaced before any release by
whitespace-only matching; v2 added the two checks above and v3 the citation-list check, so each id names one
behaviour. Neither earlier id was ever written outside development.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.tutor_pipeline.contracts import LockedClaimSet, RenderedResponse, verify_locked
from app.services.tutor_pipeline.render import TEMPLATES, layout_text
from app.services.tutor_pipeline.text import whitespace

SUBSET_CHECK_RULE = "segment-exact-whitespace-v3"
PROBLEM_CODES = (
    "empty",
    "text_not_segments",
    "unmapped_factual_sentence",
    "duplicate_claim",
    "citation_outside_locked_set",
    "citation_not_on_claim",
    "citation_marker_mismatch",
    "no_claim_rendered",
    "claim_uncited",
    "citation_list_mismatch",
)


def _formatted(template: tuple[str, str] | None, params: tuple[int, ...]) -> str | None:
    if template is None:
        return None
    try:
        return template[1].format(*params)
    except (IndexError, KeyError, ValueError):
        return None


def displayed_span_ids(rendered: RenderedResponse) -> tuple[str | None, ...]:
    """The spans a rendering's citation segments display, each once, in the order they first appear."""
    return tuple(dict.fromkeys(segment.span_id for segment in rendered.segments if segment.kind == "citation"))


@dataclass(frozen=True)
class SubsetCheckResult:
    passed: bool
    problems: tuple[str, ...]
    factual_segments: int
    mapped: int
    missing_claims: int


def check_subset(rendered: RenderedResponse, locked: LockedClaimSet, *, templates=TEMPLATES) -> SubsetCheckResult:
    verify_locked(locked)
    problems: list[str] = []
    segments = list(rendered.segments)
    if not segments:
        return SubsetCheckResult(False, ("empty",), 0, 0, len(locked.claims))

    lines = [segment.line for segment in segments]
    expected_lines = list(range(max(lines) + 1)) if lines else []
    if (
        any("\n" in segment.text for segment in segments)
        or lines != sorted(lines)
        or sorted(set(lines)) != expected_lines
        or layout_text(segments) != rendered.text
    ):
        problems.append("text_not_segments")

    by_id = {claim.claim_id: claim for claim in locked.claims}  # ids are unique in a locked set (verify_locked)
    locked_spans = set(locked.span_ids)
    citation_order = list(rendered.citations)
    rendered_claims: set[str] = set()
    line_claims: dict[int, list] = {}
    line_citations: dict[int, set[str]] = {}
    factual = mapped = 0
    for segment in segments:
        if segment.kind == "claim":
            factual += 1
            claim = by_id.get(segment.claim_id or "")
            if claim is None or whitespace(segment.text) != whitespace(claim.text):
                problems.append("unmapped_factual_sentence")
                continue
            mapped += 1
            if claim.claim_id in rendered_claims:
                problems.append("duplicate_claim")
            rendered_claims.add(claim.claim_id)
            line_claims.setdefault(segment.line, []).append(claim)
        elif segment.kind in ("connective", "question"):
            template = templates.get(segment.template_id or "")
            expected = _formatted(template, segment.params)
            if template is None or template[0] != segment.kind or expected is None or segment.text != expected:
                # Untyped text in a non-factual slot is treated as factual, and it maps to no locked claim.
                factual += 1
                problems.append("unmapped_factual_sentence")
    for segment in segments:
        if segment.kind != "citation":
            continue
        span_id = segment.span_id
        if span_id is None or span_id not in locked_spans:
            problems.append("citation_outside_locked_set")
            continue
        line_citations.setdefault(segment.line, set()).add(span_id)
        claims_on_line = line_claims.get(segment.line, [])
        if not claims_on_line or not any(span_id in claim.span_ids for claim in claims_on_line):
            problems.append("citation_not_on_claim")
        template = templates.get(segment.template_id or "")
        number = citation_order.index(span_id) + 1 if span_id in citation_order else None
        if (
            template is None
            or template[0] != "citation"
            or number is None
            or segment.params != (number,)
            or segment.text != _formatted(template, (number,))
        ):
            problems.append("citation_marker_mismatch")
    if set(rendered.citations) - locked_spans:
        problems.append("citation_outside_locked_set")
    if tuple(rendered.citations) != displayed_span_ids(rendered):
        # A declared span that no segment shows, a duplicate, or another order (spec 18.7 E1).
        problems.append("citation_list_mismatch")
    if not rendered_claims:
        problems.append("no_claim_rendered")
    for line, claims_on_line in line_claims.items():
        cited = line_citations.get(line, set())
        if any(not cited & set(claim.span_ids) for claim in claims_on_line):
            problems.append("claim_uncited")
    unique = tuple(dict.fromkeys(problems))
    missing = sum(1 for claim in locked.claims if claim.claim_id not in rendered_claims)
    return SubsetCheckResult(passed=not unique, problems=unique, factual_segments=factual, mapped=mapped, missing_claims=missing)
