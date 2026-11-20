"""The pedagogical pass: renderer template-renderer-v1 (plan task 3.6; Phase 3 spec 4.8).

The renderer is the only component that takes a PresentationPlan; in Phase 3 the plan comes from the request's
presentation hint or the package default, never from learner state (the learner model is Phase 8). It MAY reorder
the locked claims and add questions; it MUST NOT add claims or citations. It emits typed segments (connective,
question, claim, citation), so the subset check never has to guess which sentences are factual (task 3.7).
Connectives and questions are fixed templates with integer parameters only.
"""

from __future__ import annotations

from typing import Protocol

from app.core.config_package import canonical_sha256
from app.services.tutor_pipeline.contracts import LockedClaimSet, PresentationPlan, RenderedResponse, Segment, verify_locked

RENDERER_ID = "template-renderer-v1"
TEMPLATES: dict[str, tuple[str, str]] = {
    "concise.lead": ("connective", "These sentences are quoted from the approved course sources:"),
    "stepwise.lead": ("connective", "The approved course sources make these points, in source order:"),
    "stepwise.point": ("connective", "Point {0}:"),
    "socratic.open": ("question", "What do the approved course sources say about your question?"),
    "socratic.close": ("question", "Which of these points would you like to look at more closely?"),
    "citation": ("citation", "[{0}]"),
}
PLANS_LAYOUT: dict[str, dict[str, str | None]] = {
    "concise": {"lead": "concise.lead", "order": "locked", "point": None, "close": None},
    "stepwise": {"lead": "stepwise.lead", "order": "source_order", "point": "stepwise.point", "close": None},
    "socratic": {"lead": "socratic.open", "order": "locked", "point": None, "close": "socratic.close"},
}
PEDAGOGICAL_PROMPT_HASH_INPUT = {"id": RENDERER_ID, "templates": TEMPLATES, "plans": PLANS_LAYOUT, "join": "lines \\n, segments ' '"}


def pedagogical_prompt_hash() -> str:
    """The hash of the whole renderer registry, every plan included, so it is known at lock time (spec conflict 1)."""
    return canonical_sha256(PEDAGOGICAL_PROMPT_HASH_INPUT)


def layout_text(segments) -> str:
    lines: dict[int, list[str]] = {}
    for segment in segments:
        lines.setdefault(segment.line, []).append(segment.text)
    return "\n".join(" ".join(lines[line]) for line in sorted(lines))


class Renderer(Protocol):
    renderer_id: str

    def render(self, locked: LockedClaimSet, plan: PresentationPlan, *, attempt: int) -> RenderedResponse: ...


def _template(template_id: str, *params: int) -> tuple[str, str]:
    kind, text = TEMPLATES[template_id]
    return kind, text.format(*params)


class TemplateRenderer:
    renderer_id = RENDERER_ID

    def __init__(self, package=None) -> None:
        self.package = package

    def render(self, locked: LockedClaimSet, plan: PresentationPlan, *, attempt: int) -> RenderedResponse:
        verify_locked(locked)
        if not locked.claims:
            raise ValueError("the renderer is never called for an abstention")
        layout = PLANS_LAYOUT[plan.plan_id]
        claims = list(locked.claims)
        if layout["order"] == "source_order":
            claims.sort(key=lambda claim: (tuple(claim.source_order), claim.claim_id))
        segments: list[Segment] = []
        citations: list[str] = []
        lead = str(layout["lead"])
        kind, text = _template(lead)
        segments.append(Segment(kind=kind, line=0, text=text, template_id=lead))
        line = 1
        for position, claim in enumerate(claims, start=1):
            if layout["point"]:
                point = str(layout["point"])
                kind, text = _template(point, position)
                segments.append(Segment(kind=kind, line=line, text=text, template_id=point, params=(position,)))
            segments.append(Segment(kind="claim", line=line, text=claim.text, claim_id=claim.claim_id))
            for span_id in claim.span_ids:
                if span_id not in citations:
                    citations.append(span_id)
                number = citations.index(span_id) + 1
                kind, text = _template("citation", number)
                segments.append(Segment(kind=kind, line=line, text=text, template_id="citation", params=(number,), span_id=span_id))
            line += 1
        if layout["close"]:
            close = str(layout["close"])
            kind, text = _template(close)
            segments.append(Segment(kind=kind, line=line, text=text, template_id=close))
        return RenderedResponse(
            renderer_id=self.renderer_id,
            plan_id=plan.plan_id,
            attempt=attempt,
            segments=tuple(segments),
            citations=tuple(citations),
            text=layout_text(segments),
        )
