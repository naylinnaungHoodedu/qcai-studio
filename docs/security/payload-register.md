# Payload register (Q-15; plan Phase 5 F and H)

What each model-gateway call would send. In the claim and alignment items only public-corpus spans and fixed templates leave the platform (plan H; invariant 8); the embedding item would carry learner text, so the gateway gives no embedder before this register's review. The payload policy (`app/gateway/policy.py`, rule `public-quotable-spans-and-templates-only-v1`) stops the gateway on anything it refuses. For a claim item it refuses a span that is unknown, not public-plane or not quotable, a span text other than the span's, a claim text that does not lie inside that span (NFKC-casefolded, whitespace collapsed) and any identifier pattern. For an alignment item it refuses a rendering other than the context's, a claim segment that is not a locked claim on such spans, a segment that is not its template's output, an objective other than the lesson's summary and any identifier pattern. No non-fake adapter is registered and no embedder is given (D-12, Q-09 open), so today nothing leaves the process.

Status: owner review pending (DI-71). This register is hold H6's release evidence; no non-fake adapter may be registered before the review.

## Claim item (`VerdictRequest`, schema `v2-verdict-request-v1`)

| Field | Source | Plane | Bound |
|---|---|---|---|
| `request_schema` | constant `v2-verdict-request-v1` | none | fixed |
| `item` | constant `claim` | none | fixed |
| `claim_text` | a locked claim: V1.2 binds whole verbatim sentences of the claim's quotable public spans, and the policy checks that the text lies inside the span sent | public | 1-2000 characters; no identifier pattern |
| `span` | one bound span of that claim | public | `span_id` (`span-<sha256>`) and `text` (the span's resolved text, at most 20000 characters; the store's spans hold at most 700) |
| `instructions` | the fixed instructions' id and hash (the text itself travels in the HTTP envelope, below) | none | `prompt_id`, `prompt_hash`, `verdicts`, `ehmf_types`, `tool_contract_version` |

## Alignment item (`AlignmentRequest`, schema `v2-alignment-request-v1`)

| Field | Source | Plane | Bound |
|---|---|---|---|
| `request_schema` | constant `v2-alignment-request-v1` | none | fixed |
| `item` | constant `alignment` | none | fixed |
| `rendered_text` | the rendering: locked claim texts and fixed renderer templates (integer parameters only) | public | at most 20000 characters |
| `objective` | the lesson's authored summary, or null | public curriculum text | at most 4000 characters |
| `band` | the package's readability band (`v1.v1_9.readability`) | none | `min_grade`, `max_grade` |
| `instructions` | the fixed instructions' id and hash (the text itself travels in the HTTP envelope, below) | none | `prompt_id`, `prompt_hash`, `ratings`, `tool_contract_version` |

The span's fields are `span_id` and `text`; the instructions' fields are `prompt_id`, `prompt_hash`, `verdicts`, `ehmf_types`, `ratings` and `tool_contract_version`; the band's are `min_grade` and `max_grade`.

## Embedding item (`OpenAIEmbeddingAdapter`, the semantic backend's egress; Phase 5 spec 4.19)

The gateway gives the semantic backend no embedder while D-07, D-12 or Q-09 is open or this register's review is pending (DI-71), so with package v4 nothing below leaves the process.

| Field | Source | Plane | Bound |
|---|---|---|---|
| `model` | `OPENAI_EMBEDDING_MODEL` (pinned with `OPENAI_EMBEDDING_MODEL_VERSION`) | none | fixed per environment |
| `input` (index sync) | the span index's excerpts (`CourseStore.chunks`), in batches of 256 | public | the index's spans |
| `input` (a search) | the learner's search or question text, one string | learner text | the request's query |
| `encoding_format` | constant `float` | none | fixed |

A search embedding is the one gateway payload that would carry learner text, which plan H ("Only public-corpus spans leave the platform") and the list below exclude from the V2 items; that is why its owner review precedes any embedder. The key travels in the `Authorization` header only.

## Never sent

In a claim or alignment item: the resolved question and the learner's own text, learner identifiers (user, guest, account, thread, turn, message or response ids, emails), history or any prior turn, mastery or other learner state, the generator identity (its id, model or family), other votes of the panel, other claims of the response in a claim item (the alignment item's `rendered_text` is the whole rendering, so it carries every claim the rendering shows), private-plane or unapproved spans, and any rationale text a verifier returns (an adapter keeps only `verdict`, `ehmf_type` and `span_id`, or `rating` and `leakage`).

The HTTP envelope of a provider-neutral adapter (`HttpJsonAdapter`) is `{model, model_version, max_tokens, instructions, input}`: the adapter's own `model`, `model_version` and `max_tokens`, `instructions`, the fixed instruction text of the request's `prompt_id` (`VERIFIER_INSTRUCTIONS` or `ALIGNMENT_INSTRUCTIONS`, Phase 5 spec 4.7; public, fixed, naming no model, learner or vote; the adapter refuses a request whose `prompt_hash` is not that text's), and `input`, the request contract above. The key travels in a header, never in the URL or the body. A reply carries `output` and `usage.cost_units`; a cost above the call's reservation stops the gateway (`budget_breach`).
