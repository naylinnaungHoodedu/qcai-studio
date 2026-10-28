"""Conservative claim-to-span gate for the persistent grounded Tutor."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas import Citation, GroundedClaim


_SENTENCES = re.compile(r"(?<=[.!?])\s+")
_WORDS = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}")
_STOPWORDS = {
    "about", "after", "also", "and", "are", "because", "been", "being", "but", "can", "could", "does",
    "from", "have", "into", "its", "not", "only", "or", "our", "that", "the", "their", "these", "this",
    "those", "was", "were", "what", "when", "which", "with", "would", "your",
}


@dataclass(frozen=True)
class ClaimGateResult:
    answer: str
    decision: str
    reason: str
    claims: list[GroundedClaim]
    grounded: bool


def _terms(text: str) -> set[str]:
    return {word.lower() for word in _WORDS.findall(text) if word.lower() not in _STOPWORDS}


def evidence_digest(citations: list[Citation]) -> str:
    statements: list[str] = []
    for index, citation in enumerate(citations[:3], start=1):
        excerpt = " ".join(citation.excerpt.split())
        if excerpt:
            statements.append(f"Evidence [{index}]: {excerpt}")
    return " ".join(statements)


class ClaimGate:
    """Fail closed when a factual sentence cannot be tied to a retrieved span.

    This is deliberately lexical and conservative.  It is an enforcement gate, not a
    substitute for the frozen human claim-rating protocol used by the evaluation harness.
    """

    def evaluate(self, answer: str, citations: list[Citation]) -> ClaimGateResult:
        usable = [citation for citation in citations if citation.chunk_id and citation.excerpt.strip()]
        if not usable:
            return ClaimGateResult(
                answer=(
                    "I cannot provide a grounded answer because the approved corpus did not return sufficient evidence. "
                    "Please narrow the question to a course topic or source."
                ),
                decision="abstain",
                reason="no_retrieved_evidence",
                claims=[],
                grounded=False,
            )

        claims: list[GroundedClaim] = []
        for sentence in (item.strip() for item in _SENTENCES.split(answer) if item.strip()):
            sentence_terms = _terms(sentence)
            if not sentence_terms:
                continue
            cited_span_ids = [
                citation.span_id or citation.chunk_id
                for citation in usable
                if self._supports(sentence_terms, _terms(citation.excerpt))
            ]
            claims.append(
                GroundedClaim(text=sentence, cited_span_ids=cited_span_ids, supported=bool(cited_span_ids))
            )

        if claims and all(claim.supported for claim in claims):
            return ClaimGateResult(
                answer=answer,
                decision="answer",
                reason="all_factual_claims_bound_to_retrieved_spans",
                claims=claims,
                grounded=True,
            )

        return ClaimGateResult(
            answer=(
                "I am abstaining from a generated answer because its factual claims could not be bound to the "
                "retrieved evidence at the required claim level. "
                "You can inspect the retrieved source excerpts below or ask a narrower question."
            ),
            decision="abstain",
            reason="claim_span_binding_failed",
            claims=claims,
            grounded=False,
        )

    @staticmethod
    def _supports(sentence_terms: set[str], span_terms: set[str]) -> bool:
        if not sentence_terms or not span_terms:
            return False
        overlap = len(sentence_terms & span_terms)
        # Short evidence summaries must substantially agree; longer generated claims
        # need at least three substantive words and half their terms in one span.
        required = max(1, min(3, (len(sentence_terms) + 1) // 2))
        return overlap >= required
