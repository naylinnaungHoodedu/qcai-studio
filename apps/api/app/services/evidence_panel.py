"""The evidence panel of a tutor or Q&A answer (plan task 3.8: "evidence panel shows decision, span links, degraded
and "lexically screened" labels" [E-46]; Phase 3 spec 4.13). It is shown on tutor answers and on Q&A answers, whose
citation cards E-46 names.

Labels only, and only for the contained answer the learner already receives: the decision, the spans quoted
(links to GET /evidence/spans/{span_id} only when that route is enabled), the "lexically screened" label (task
1.11: it "MAY accompany only that contained output", so only on an answer), the degraded modes in force, and the
verdict "no-verdict" (no V1-V3 verification exists before Phase 4). It never says "grounded" and never reads the
two-pass shadow. EVIDENCE_PANEL_ENABLED gates it (development by default; production rollout is DI-34).
"""

from __future__ import annotations

from app.core.config import Settings
from app.schemas import Citation, EvidencePanel, EvidenceSpanLink


def build_evidence_panel(*, decision: str, citations: list[Citation], retrieval_mode: str, settings: Settings) -> EvidencePanel:
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
    )
