"""Claim-level taxonomy validation for RevB §8.3."""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Mapping


CLAIM_CATEGORIES = {"supported", "attribution_error", "unsupported_but_true", "fabricated"}


def validate_claims(claims: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    validated: list[dict[str, object]] = []
    for claim in claims:
        text = claim.get("text")
        category = claim.get("category")
        if not isinstance(text, str) or not text.strip() or category not in CLAIM_CATEGORIES:
            raise ValueError("Every factual claim requires non-empty text and exactly one valid category.")
        span_ids = claim.get("cited_span_ids", [])
        if not isinstance(span_ids, list) or not all(isinstance(value, str) and value for value in span_ids):
            raise ValueError("Claim cited_span_ids must be a string array.")
        validated.append({"text": text.strip(), "category": category, "cited_span_ids": span_ids})
    return validated


def category_counts(claims: Iterable[Mapping[str, object]]) -> dict[str, int]:
    validated = validate_claims(claims)
    counts = Counter(str(claim["category"]) for claim in validated)
    return {category: counts.get(category, 0) for category in sorted(CLAIM_CATEGORIES)}
