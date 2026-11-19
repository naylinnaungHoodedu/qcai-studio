"""Fakes for the Phase 3 two-channel tutor tests (Phase 3 spec 13.1).

ScriptedGenerator emits scripted claim plans (unbound, outside-bundle, invented, non-verbatim, truncated or
cross-span claims, or a malformed plan); SpyGenerator records every envelope the evidential pass sends; FaultyRenderer
injects one fault per scheduled attempt; FailingLedger stands in for a ledger append that fails.
"""

from __future__ import annotations

from collections.abc import Sequence
import random
import re
from typing import Any

from app.services.tutor_pipeline.contracts import ClaimPlan, GeneratorRef, ProposedClaim, RenderedResponse, Segment
from app.services.tutor_pipeline.render import layout_text

FAULT_MODES = (
    "invented",
    "digit",
    "outside",
    "connective_fact",
    "extra_citation",
    "wrong_citation",
    "duplicate",
    "text_mismatch",
    "non_contiguous",
    # Review round 3 (spec 18.6 D4): a rendering that drops every claim (connectives only), or every citation.
    "drop_all_claims",
    "drop_citations",
)
INVENTED = "Quantum annealers always outperform every classical solver on routing problems."


class ScriptedGenerator:
    """Each call returns the next scripted plan: a list of (text, span_ids) pairs, or a raw object (a malformed plan)."""

    def __init__(self, claims_by_call: Sequence[Any], *, ref: GeneratorRef | None = None) -> None:
        self.ref = ref or GeneratorRef(generator_id="scripted-test", model_id="scripted-test", kind="generative", prompt_hash="1" * 64)
        self.claims_by_call = list(claims_by_call)
        self.calls = 0

    def propose(self, envelope):
        script = self.claims_by_call[min(self.calls, len(self.claims_by_call) - 1)]
        self.calls += 1
        if callable(script):
            script = script(envelope)
        if isinstance(script, (dict, str, bytes)) or script is None:
            return script
        return ClaimPlan(generator=self.ref, claims=tuple(ProposedClaim(text=text, span_ids=tuple(span_ids)) for text, span_ids in script))


class SpyGenerator:
    def __init__(self, inner) -> None:
        self.inner = inner
        self.ref = inner.ref
        self.envelopes: list[dict] = []

    def propose(self, envelope):
        self.envelopes.append(envelope.model_dump(mode="json"))
        return self.inner.propose(envelope)


class FailingLedger:
    """A stand-in for append_ledger_entry that always fails."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        raise RuntimeError("ledger unavailable (test)")


def _relayout(rendered: RenderedResponse, segments: list[Segment], citations: Sequence[str] | None = None) -> RenderedResponse:
    return rendered.model_copy(
        update={"segments": tuple(segments), "citations": tuple(citations if citations is not None else rendered.citations), "text": layout_text(segments)}
    )


def inject(rendered: RenderedResponse, mode: str, *, outside_sentence: str, outside_span_id: str) -> RenderedResponse:
    """One fault in a rendered response; every mode must be caught by check_subset."""
    segments = list(rendered.segments)
    claims = [segment for segment in segments if segment.kind == "claim"]
    last_line = max(segment.line for segment in segments)
    if mode == "wrong_citation":
        by_line: dict[int, set[str]] = {}
        for segment in claims:
            by_line.setdefault(segment.line, set())
        for segment in segments:
            if segment.kind == "citation" and segment.line in by_line:
                by_line[segment.line].add(segment.span_id)
        for index, segment in enumerate(segments):
            if segment.kind != "citation":
                continue
            foreign = sorted(span for line, spans in by_line.items() if line != segment.line for span in spans if span not in by_line.get(segment.line, set()))
            if foreign:
                segments[index] = segment.model_copy(update={"span_id": foreign[0]})
                return _relayout(rendered, segments)
        mode = "invented"  # a single-span locked set has no wrong citation to place
    if mode == "invented":
        segments.append(Segment(kind="claim", line=claims[0].line, text=INVENTED, claim_id="claim-" + "0" * 32))
        segments.sort(key=lambda segment: segment.line)
        return _relayout(rendered, segments)
    if mode == "digit":
        target = claims[0]
        text = target.text
        match = re.search(r"\d", text)
        changed = text[: match.start()] + str((int(match.group()) + 1) % 10) + text[match.end():] if match else "2 " + text
        segments[segments.index(target)] = target.model_copy(update={"text": changed})
        return _relayout(rendered, segments)
    if mode == "outside":
        target = claims[0]
        segments[segments.index(target)] = target.model_copy(update={"text": outside_sentence})
        return _relayout(rendered, segments)
    if mode == "connective_fact":
        lead = next(segment for segment in segments if segment.kind in ("connective", "question"))
        segments[segments.index(lead)] = lead.model_copy(update={"text": INVENTED})
        return _relayout(rendered, segments)
    if mode == "extra_citation":
        number = len(rendered.citations) + 1
        segments.append(Segment(kind="citation", line=claims[0].line, text=f"[{number}]", template_id="citation", params=(number,), span_id=outside_span_id))
        segments.sort(key=lambda segment: segment.line)
        return _relayout(rendered, segments, (*rendered.citations, outside_span_id))
    if mode == "duplicate":
        segments.append(claims[0].model_copy(update={"line": last_line + 1}))
        return _relayout(rendered, segments)
    if mode == "text_mismatch":
        return rendered.model_copy(update={"text": rendered.text + " " + INVENTED})
    if mode == "non_contiguous":
        segments = [segment.model_copy(update={"line": segment.line + 1}) for segment in segments]
        return _relayout(rendered, segments)
    if mode in ("drop_all_claims", "drop_citations"):
        # Well-formed otherwise: lines renumbered to stay contiguous, markers and the citation list consistent.
        dropped = ("claim", "citation") if mode == "drop_all_claims" else ("citation",)
        kept = [segment for segment in segments if segment.kind not in dropped]
        renumber = {line: index for index, line in enumerate(sorted({segment.line for segment in kept}))}
        kept = [segment.model_copy(update={"line": renumber[segment.line]}) for segment in kept]
        return _relayout(rendered, kept, ())
    raise ValueError(mode)


class FaultyRenderer:
    """Wraps a renderer; schedule[n] True injects a fault (a mode drawn from rng) into attempt n + 1."""

    def __init__(self, inner, schedule: Sequence[bool], rng: random.Random, *, outside_sentence: str, outside_span_id: str, modes=FAULT_MODES) -> None:
        self.inner = inner
        self.renderer_id = inner.renderer_id
        self.schedule = list(schedule)
        self.rng = rng
        self.modes = tuple(modes)
        self.outside_sentence = outside_sentence
        self.outside_span_id = outside_span_id
        self.injected: list[str | None] = []

    def render(self, locked, plan, *, attempt: int):
        rendered = self.inner.render(locked, plan, attempt=attempt)
        faulty = self.schedule[attempt - 1] if attempt - 1 < len(self.schedule) else False
        if not faulty:
            self.injected.append(None)
            return rendered
        mode = self.rng.choice(self.modes)
        self.injected.append(mode)
        return inject(rendered, mode, outside_sentence=self.outside_sentence, outside_span_id=self.outside_span_id)


def make_entry(response_id: str | None = None, *, delivery: str = "legacy", shadowed_response_id: str | None = None,
               decision: str = "answer", text: str = "Routing adds SWAP gates on sparse hardware.", span_id: str = "span-" + "1" * 64):
    """A valid ledger entry for chain tests (no learner data)."""
    from uuid import uuid4

    from app.services.tutor_pipeline.bind import claim_id_for
    from app.services.tutor_pipeline.contracts import (
        BudgetStamp, ClaimLedgerEntry, LedgerEntry, PipelineCounts, Provenance, RetrievalRecord, VersionStamps, sha256_hex,
    )

    prefix = "shadow" if delivery == "shadow" else "turn"
    response_id = response_id or f"{prefix}-{uuid4()}"
    if delivery == "shadow" and shadowed_response_id is None:
        shadowed_response_id = f"turn-{uuid4()}"
    provenance = Provenance(generator_model_id="extractive-lexically-screened", evidential_prompt_hash="a" * 64, pedagogical_prompt_hash=None,
                            corpus_version="corpus-test", threshold_set_version="score-floor-p1-v1")
    claims = () if decision == "abstain" else (
        ClaimLedgerEntry(claim_id=claim_id_for(text, [span_id]), response_id=response_id, text=text, span_ids=(span_id,), provenance=provenance),
    )
    return LedgerEntry(
        response_id=response_id,
        delivery=delivery,
        shadowed_response_id=shadowed_response_id,
        pipeline="two-pass-v1" if delivery == "shadow" else "legacy-contained-v1",
        decision=decision,
        abstention_reason="no_match" if decision == "abstain" else None,
        resolved_question=None,
        retrieval=RetrievalRecord(corpus_version="corpus-test", index_version="index-test", gate="p1-floor", threshold_version="score-floor-p1-v1",
                                  floor=6.0, margin=0.0, mode="lexical", evidence_scope="delivered_citations", sufficiency=None, evidence=()),
        claim_set_hash=None,
        claims=claims,
        span_ids=tuple(sorted({s for claim in claims for s in claim.span_ids})),
        presentation=None,
        rendered_text_sha256=sha256_hex(text),
        provenance=provenance,
        versions=VersionStamps(pipeline_version="legacy-contained-v1", code_sha="test", schema_revision_expected="20261119_phase3_response_ledger",
                               config_package_version="2.0.0", config_package_sha256="b" * 64, manifest_sha256=None, span_scheme="span-v2",
                               policy_version="cs595-v1", resolver_id=None, generator_id="contained-answers-v1", renderer_id=None,
                               budgets=BudgetStamp(shadow_ms=None, ledger_append_ms=1500)),
        counts=PipelineCounts(proposed_claims=len(claims), bound_claims=len(claims), dropped={}, render_attempts=0),
    )
