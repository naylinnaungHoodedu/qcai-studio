# Payload register (Q-15; plan Phase 5 F and H)

What each model-gateway call would send. Only public-corpus spans and fixed templates leave the platform (plan H; invariant 8), and the payload policy (`app/gateway/policy.py`, rule `public-quotable-spans-and-templates-only-v1`) stops the gateway on anything else. No non-fake adapter is registered (D-12, Q-09 open), so today nothing leaves the process.

Status: owner review pending (DI-71). This register is hold H6's release evidence; no non-fake adapter may be registered before the review.

## Claim item (`VerdictRequest`, schema `v2-verdict-request-v1`)

| Field | Source | Plane | Bound |
|---|---|---|---|
| `request_schema` | constant `v2-verdict-request-v1` | none | fixed |
| `item` | constant `claim` | none | fixed |
| `claim_text` | a locked claim: a verbatim whole sentence of a quotable public span | public | 1-2000 characters; no identifier pattern |
| `span` | one bound span of that claim | public | `span_id` (`span-<sha256>`) and `text` (the span's resolved text, at most 20000 characters; the store's spans hold at most 700) |
| `instructions` | fixed text and its hash | none | `prompt_id`, `prompt_hash`, `verdicts`, `ehmf_types`, `tool_contract_version` |

## Alignment item (`AlignmentRequest`, schema `v2-alignment-request-v1`)

| Field | Source | Plane | Bound |
|---|---|---|---|
| `request_schema` | constant `v2-alignment-request-v1` | none | fixed |
| `item` | constant `alignment` | none | fixed |
| `rendered_text` | the rendering: locked claim texts and fixed renderer templates (integer parameters only) | public | at most 20000 characters |
| `objective` | the lesson's authored summary, or null | public curriculum text | at most 4000 characters |
| `band` | the package's readability band (`v1.v1_9.readability`) | none | `min_grade`, `max_grade` |
| `instructions` | fixed text and its hash | none | `prompt_id`, `prompt_hash`, `ratings`, `tool_contract_version` |

The span's fields are `span_id` and `text`; the instructions' fields are `prompt_id`, `prompt_hash`, `verdicts`, `ehmf_types`, `ratings` and `tool_contract_version`; the band's are `min_grade` and `max_grade`.

## Never sent

The resolved question and the learner's own text, learner identifiers (user, guest, account, thread, turn, message or response ids, emails), history or any prior turn, mastery or other learner state, the generator identity (its id, model or family), other votes of the panel, other claims of the response, private-plane or unapproved spans, and any rationale text a verifier returns (an adapter keeps only `verdict`, `ehmf_type` and `span_id`, or `rating` and `leakage`).

The HTTP envelope of a provider-neutral adapter adds only `model`, `model_version` and `max_tokens` of that adapter itself; the key travels in a header, never in the URL or the body.
