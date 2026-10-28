# ADR-001: Grounding separation

## Context

RevB §6.1 requires learner progress to affect presentation but never to function as factual evidence or silently alter retrieval/abstention behavior.

## Decision

The Tutor orchestrator has two typed channels. `build_pedagogical_context` supplies style guidance after retrieval; the resolved factual query is the only input to retrieval. The claim gate binds each factual answer sentence to retrieved span IDs. A failure produces an abstention, not an uncited personalized answer.

## Consequences

RQ2 can compare factual-claim/cited-span sets across low/medium/high mastery replays. Personalization is intentionally constrained to explanation style, pacing, and scaffolding.
