# ADR-004: Citation traceability

## Context

RevB §6.1 requires every factual sentence to bind to retrieved span identifiers; §8.3 separately measures citation existence and claim support.

## Decision

Persist citation objects and claim-to-`chunk_id` bindings with each Tutor turn, plus corpus/policy version. Treat title/excerpt strings as presentation data, not identity.

## Consequences

The current chunk identifier is the compatibility provenance ID. Before the experiment freeze it must be upgraded to an immutable corpus item/document version/offset/hash span identity; the LQS must reference that immutable form.
