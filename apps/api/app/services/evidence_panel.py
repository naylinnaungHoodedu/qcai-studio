"""The evidence panel of a tutor or Q&A answer (plan task 3.8: "evidence panel shows decision, span links, degraded
and "lexically screened" labels" [E-46]; Phase 3 spec 4.13). It is shown on tutor answers and on Q&A answers, whose
citation cards E-46 names.

Labels only, and only for the contained answer the learner already receives: the decision, the spans quoted
(links to GET /evidence/spans/{span_id} only when that route is enabled), the "lexically screened" label (task
1.11: it "MAY accompany only that contained output", so only on an answer), the degraded modes in force, and the
verdict "no-verdict" (the contained answer is not V1-verified: V1 runs in the two-pass shadow). With conflicts, it
also labels which quoted passages disagree (V1.7 over the quotations, Phase 4 spec 4.8). It never says "grounded" and
never reads the two-pass shadow. EVIDENCE_PANEL_ENABLED gates it (development by default; production rollout is DI-34).
"""

from __future__ import annotations

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
    """V1.7 over a contained answer's quoted passages, for the evidence panel (labels only), or None (Phase 4 spec 4.8)."""
    if package.v1 is None or contained.decision != "answer" or len(contained.citations) < 2:
        return None
    from app.services.v1_checks.v1_7_conflicts import legacy_conflicts

    return legacy_conflicts(contained.citations, v1=package.v1, stopwords=package.retrieval.stopwords) or None
