"""Subset checker, rule segment-exact-normalised-v1 (plan Phase 3 E: "claim_gate becomes the subset checker";
task 3.7; Phase 3 spec 4.9). Phase 4 V1.4 subsumes it.

The overlap ClaimGate and evidence_digest are gone (plan 3.4: "overlap rebinding removed", R-13): nothing binds a
sentence to whichever citation shares its words. Instead every factual segment of a rendered response must equal a
locked claim by exact normalised match, and every citation must be one of that claim's locked spans. Questions and
connectives are typed by the renderer, never detected heuristically; a non-factual segment whose text is not its
template's text counts as an unmapped factual sentence. The caller regenerates (at most twice), then abstains.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.tutor_pipeline.contracts import LockedClaimSet, RenderedResponse, verify_locked
from app.services.tutor_pipeline.render import TEMPLATES, layout_text
from app.services.tutor_pipeline.text import normalise

SUBSET_CHECK_RULE = "segment-exact-normalised-v1"
PROBLEM_CODES = (
    "empty",
    "text_not_segments",
    "unmapped_factual_sentence",
    "duplicate_claim",
    "citation_outside_locked_set",
    "citation_not_on_claim",
    "citation_marker_mismatch",
)


def _formatted(template: tuple[str, str] | None, params: tuple[int, ...]) -> str | None:
    if template is None:
        return None
    try:
        return template[1].format(*params)
    except (IndexError, KeyError, ValueError):
        return None


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

    by_text = {normalise(claim.text): claim for claim in locked.claims}
    locked_spans = set(locked.span_ids)
    citation_order = list(rendered.citations)
    rendered_claims: set[str] = set()
    line_claims: dict[int, list] = {}
    factual = mapped = 0
    for segment in segments:
        if segment.kind == "claim":
            factual += 1
            claim = by_text.get(normalise(segment.text))
            if claim is None or segment.claim_id != claim.claim_id:
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
    unique = tuple(dict.fromkeys(problems))
    missing = sum(1 for claim in locked.claims if claim.claim_id not in rendered_claims)
    return SubsetCheckResult(passed=not unique, problems=unique, factual_segments=factual, mapped=mapped, missing_claims=missing)
