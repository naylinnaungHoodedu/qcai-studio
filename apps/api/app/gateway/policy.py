"""The payload policy (plan Phase 5 H "Only public-corpus spans leave the platform"; control row "No private span in
production provider payloads"; invariant 8; R-10; Q-15; Phase 5 spec 4.5). Rule public-quotable-spans-and-templates-only-v1.

PayloadPolicy.check(request, context) raises PayloadViolation, and the gateway then stops (plan L "Stop on a payload
violation"). The context is built per call by the V2 track from its own pipeline and is never sent, so one process
gateway serves pipelines over different stores and manifests without binding either.
  claim item      the span id resolves in the store's span registry; its record is public-plane and quotable under
                  D-19 (contained_answers.span_is_quotable: under D-31 nothing is quotable outside development, so
                  nothing could leave); the request's span text is the record's text (whitespace collapsed); the claim
                  text lies inside that span (NFKC-casefolded and whitespace-collapsed, as V1.2's verbatim binding makes
                  every locked claim), so a claim item carries public corpus text only; no string holds a learner
                  identifier, an email or a bearer credential.
  alignment item  the rendered text is the layout of the context's rendering; each claim segment is a locked claim of
                  the context, whose every span passes the claim-item span checks; every other segment is its
                  template's output; the objective is null or the lesson's summary; no string holds an identifier.
check_embedding(texts, purpose=..., context) is the same rule for the gateway's embedding egress (app.gateway.embeddings):
  query           the learner's query text, which plan H never lets leave: always refused (learner_text)
  documents       each text is the excerpt of an index entry of the context's store (whitespace collapsed) whose span
                  passes the claim-item span checks (public plane, quotable under D-19); no text holds an identifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.gateway.adapters import fold
from app.gateway.contracts import AlignmentRequest, VerdictRequest, identifier_in

POLICY_RULE = "public-quotable-spans-and-templates-only-v1"
EMBEDDING_PURPOSES = ("documents", "query")


class PayloadViolation(RuntimeError):
    """A request that the payload policy refuses; reason is an enumeration, never request text."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"payload policy refused the request: {reason}")
        self.reason = reason


@dataclass(frozen=True)
class PolicyContext:
    store: Any                      # the pipeline's CourseStore (span_registry, lessons)
    corpus_registry: Any            # the pipeline's CorpusRegistry
    rendering: Any = None           # the RenderedResponse an alignment item judges
    locked: Any = None              # the LockedClaimSet of that rendering
    lesson_slug: str | None = None


def _collapse(text: str) -> str:
    return " ".join(str(text).split())


def _span_problem(span_id: str, context: PolicyContext, text: str | None = None) -> str | None:
    from app.services.contained_answers import span_is_quotable

    record = context.store.span_registry.get(span_id)
    if record is None:
        return "unknown_span"
    if getattr(record, "plane", None) != "public":
        return "non_public_span"
    if not span_is_quotable(record, context.corpus_registry):
        return "span_not_quotable"
    if text is not None and _collapse(text) != _collapse(record.text):
        return "span_text_differs"
    return None


class PayloadPolicy:
    rule = POLICY_RULE

    def check(self, request: VerdictRequest | AlignmentRequest, context: PolicyContext) -> None:
        if isinstance(request, VerdictRequest):
            problem = _span_problem(request.span.span_id, context, request.span.text)
            if problem:
                raise PayloadViolation(problem)
        elif isinstance(request, AlignmentRequest):
            self._alignment(request, context)
        else:
            raise PayloadViolation("unknown_item")
        if identifier_in(request.model_dump(mode="json")):
            raise PayloadViolation("identifier_in_payload")
        if isinstance(request, VerdictRequest) and fold(request.claim_text) not in fold(request.span.text):
            raise PayloadViolation("claim_not_in_span")

    def _alignment(self, request: AlignmentRequest, context: PolicyContext) -> None:
        from app.services.tutor_pipeline.render import TEMPLATES, layout_text

        rendering, locked = context.rendering, context.locked
        if rendering is None or locked is None or request.rendered_text != layout_text(rendering.segments):
            raise PayloadViolation("rendering_differs")
        claims = {claim.claim_id: claim for claim in locked.claims}
        for segment in rendering.segments:
            if segment.kind == "claim":
                claim = claims.get(segment.claim_id or "")
                if claim is None or claim.text != segment.text:
                    raise PayloadViolation("claim_segment_not_locked")
                for span_id in claim.span_ids:
                    problem = _span_problem(span_id, context)
                    if problem:
                        raise PayloadViolation(problem)
            else:
                template = TEMPLATES.get(segment.template_id or "")
                if template is None or template[0] != segment.kind or template[1].format(*segment.params) != segment.text:
                    raise PayloadViolation("non_template_segment")
        summary = None
        if context.lesson_slug:
            lesson = getattr(context.store, "lessons", {}).get(context.lesson_slug)
            summary = getattr(lesson, "summary", None)
        if request.objective is not None and request.objective != summary:
            raise PayloadViolation("objective_not_lesson_summary")

    def check_embedding(self, texts, *, purpose: str, context: PolicyContext | None) -> None:
        """One embedding request (Phase 5 spec 4.19). A query embedding sends the learner's query text, and plan H lets
        only public-corpus spans leave the platform: it is refused. A document item must be the excerpt of an index
        entry of the context's store whose span passes the claim-item span checks."""
        if purpose == "query":
            raise PayloadViolation("learner_text")
        if purpose != "documents":
            raise PayloadViolation("unknown_item")
        if context is None:
            raise PayloadViolation("no_context")
        span_ids_by_text: dict[str, list[str]] = {}
        for entry in getattr(context.store, "chunks", ()):
            span_ids_by_text.setdefault(_collapse(entry.excerpt), []).append(entry.span_id)
        for text in texts:
            span_ids = span_ids_by_text.get(_collapse(text))
            if not span_ids:
                raise PayloadViolation("unknown_span")
            problems = [_span_problem(span_id, context) for span_id in span_ids]
            if all(problems):
                raise PayloadViolation(str(problems[0]))
        if identifier_in(list(texts)):
            raise PayloadViolation("identifier_in_payload")
