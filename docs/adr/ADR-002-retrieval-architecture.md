# ADR-002: Retrieval architecture

## Context

RevB §§5.1 and 6.2 require retrieval, citations, and graceful semantic-to-lexical degradation.

## Decision

Retain lexical retrieval as the canonical baseline and wrap optional semantic/Pinecone retrieval behind `RetrievalEngine`. Every result has a stable `chunk_id`; the persistent Tutor records retrieval mode and corpus manifest version. The evaluation harness models the four required arms explicitly.

## Consequences

Provider failure cannot remove the evidence path. Semantic retrieval is an optimization, not the sole source of truth, and arm B remains measurable rather than a claim in documentation.
