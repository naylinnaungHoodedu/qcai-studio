"""The evidence panel of a tutor or Q&A answer (plan task 3.8: "evidence panel shows decision, span links, degraded
and "lexically screened" labels" [E-46]; Phase 3 spec 4.13). It is shown on tutor answers and on Q&A answers, whose
citation cards E-46 names.

Labels only, and only for the contained answer the learner already receives: the decision, the spans quoted
(links to GET /evidence/spans/{span_id} only when that route is enabled), the "lexically screened" label (task
1.11: it "MAY accompany only that contained output", so only on an answer), the degraded modes in force, and the
verdict "no-verdict" (the contained answer is not V1-verified: V1 runs in the two-pass shadow). With conflicts, it
also labels which quoted passages disagree (V1.7 over the quotations, Phase 4 spec 4.8). It never says "grounded" and
never reads the two-pass shadow. EVIDENCE_PANEL_ENABLED gates it (development by default; production rollout is DI-34).

stored_conflicts applies the same rule to a stored answer, over the citations stored with it, and record_conflicts to
a legacy ledger record, over its claims, so every read that shows a stored answer's quotations again
(GET /assistant/threads/{thread_id}, GET /qa/history, GET /ledger/responses/{response_id}) carries the V1.7 labels the
package in force at read time gives them, whatever EVIDENCE_PANEL_ENABLED says (AC-4-6; Phase 4 spec 4.15 item 3).
Nothing stores the labels shown at delivery, so other V1.7 values in a later package relabel the stored answer (DI-68).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from app.core.config import Settings
from app.schemas import Citation, EvidenceConflict, EvidencePanel, EvidenceSpanLink


def build_evidence_panel(*, decision: str, citations: list[Citation], retrieval_mode: str, settings: Settings,
                         conflicts: list[EvidenceConflict] | None = None) -> EvidencePanel:
    answered = decision == "answer"
    degraded = ["extractive_only"]  # D-19: generation is off; only quotations are shown
    if retrieval_mode.startswith("lexical-fallback"):
        degraded.append("retrieval_fallback")
    if any(citation.provisional for citation in citations):
        degraded.append("citations_provisional")
    return EvidencePanel(
        decision="answer" if answered else "abstain",
        labels=["lexically_screened"] if answered else [],
        degraded=degraded,
        spans=[
            EvidenceSpanLink(
                span_id=citation.span_id or citation.chunk_id,
                label=f"{citation.source_title} — {citation.section_title}",
                resolvable=bool(settings.span_resolver_route_enabled),
            )
            for citation in citations
        ],
        conflicts=conflicts or None,
    )


def panel_conflicts(contained, package) -> list[EvidenceConflict] | None:
    """V1.7 over a contained answer's quoted passages, for the evidence panel (labels only), or None (Phase 4 spec 4.8).
    With the panel off, or under the package's conflict policy withhold, the legacy guard withholds such an answer
    instead (legacy_guard.may_disclose), so the panel never sees it."""
    if package.v1 is None or contained.decision != "answer" or len(contained.citations) < 2:
        return None
    from app.services.v1_checks.v1_7_conflicts import legacy_conflicts

    return legacy_conflicts(contained.citations, v1=package.v1, stopwords=package.retrieval.stopwords) or None


@dataclass(frozen=True)
class _StoredQuotation:
    """What V1.7 reads of a stored citation: its item and its quoted text."""

    item_id: str | None
    excerpt: str


def stored_conflicts(stored_citations: Iterable[object], package) -> list[EvidenceConflict] | None:
    """panel_conflicts' rule over the citations stored with an answer (Citation dumps, in the answer's quotation order),
    or None. An entry that is not a citation dict keeps its position and conflicts with nothing."""
    if package.v1 is None:
        return None
    quotations = [
        _StoredQuotation(item_id=raw.get("item_id") if isinstance(raw.get("item_id"), str) else None,
                         excerpt=raw.get("excerpt") if isinstance(raw.get("excerpt"), str) else "")
        if isinstance(raw, dict) else _StoredQuotation(item_id=None, excerpt="")
        for raw in stored_citations or ()
    ]
    if len(quotations) < 2:
        return None
    from app.services.v1_checks.v1_7_conflicts import legacy_conflicts

    return legacy_conflicts(quotations, v1=package.v1, stopwords=package.retrieval.stopwords) or None


def record_conflicts(entry: Mapping[str, object], package, *, item_of: Callable[[str], str | None]) -> list[EvidenceConflict] | None:
    """panel_conflicts' rule over a legacy ledger record's claims (its delivered quotations, in the record's order), or
    None. Each claim's item is its first span's: from the record's evidence spans, else item_of(span_id) (the span
    registry; a span id names one item). Passages are 1-based positions in the record's claims. A shadow record is never
    delivered: its V1.7 result is its own verification record's."""
    if entry.get("delivery") != "legacy" or entry.get("decision") != "answer":
        return None
    retrieval = entry.get("retrieval")
    evidence = retrieval.get("evidence") if isinstance(retrieval, dict) else None
    items = {span.get("span_id"): span.get("item_id") for span in evidence or () if isinstance(span, dict)}
    quotations = []
    for claim in entry.get("claims") or ():
        span_ids = claim.get("span_ids") if isinstance(claim, dict) else None
        first = span_ids[0] if isinstance(span_ids, list) and span_ids and isinstance(span_ids[0], str) else None
        item_id = (items.get(first) or item_of(first)) if first is not None else None
        quotations.append({"item_id": item_id, "excerpt": claim.get("text") if isinstance(claim, dict) else ""})
    return stored_conflicts(quotations, package)
