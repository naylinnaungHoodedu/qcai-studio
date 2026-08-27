# ADR-005: Abstention gate

## Context

RevB treats weak-evidence abstention as a correct first-class outcome, not a generic error message.

## Decision

`ClaimGate` fails closed. It accepts only answer sentences with adequate overlap to at least one retrieved span; otherwise it emits a transparent `abstain` decision with reason and stores the failed claim bindings.

## Consequences

Coverage may decline, especially with provider-generated prose. This is deliberate: evidence digest/follow-up clarification is preferable to presenting an unsupported answer as grounded. Human evaluation remains the definitive faithfulness measurement.
