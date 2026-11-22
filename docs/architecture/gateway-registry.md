# Model gateway adapter registry (plan Phase 5 F)

Hand-maintained from configuration package v4 (`apps/api/app/config_package/v4.json`, `gateway.registries` and `gateway.budgets`); `scripts/config_package.py --check` prints the same counts, and `test_plan_f_the_registry_matrix_payload_register_and_terms_record_match_the_package` compares every adapter, family, model id, version, capability, cap, cost per call and daily budget stated here, and the matrix, with the package. Every identifier is pinned (`pinned-version-v1`, D-07 option (a)'s rule, PD-24). No real provider is registered while D-12, D-07 and Q-09 are open.

| Registry | Members |
|---|---|
| development | `fake-alpha-v1`, `fake-beta-v1`, `fake-gamma-v1`, `fake-delta-v1` |
| staging | none |
| production | none |
| default | none |

**Development members** (provider `fake`, rule `verbatim-support-v1`, no network call):

| Adapter | Family | Model id | Version | Capabilities | Caps | Cost per call |
|---|---|---|---|---|---|---|
| `fake-alpha-v1` | `fake-alpha` | `fake-alpha-verifier` | 2026-11-21 | verify | 256 tokens, 500 ms, 1 retry | 1 unit |
| `fake-beta-v1` | `fake-beta` | `fake-beta-verifier` | 2026-11-21 | verify | 256 tokens, 500 ms, 1 retry | 1 unit |
| `fake-gamma-v1` | `fake-gamma` | `fake-gamma-verifier` | 2026-11-21 | verify | 256 tokens, 500 ms, 1 retry | 1 unit |
| `fake-delta-v1` | `fake-delta` | `fake-delta-verifier` | 2026-11-21 | generate, verify | 256 tokens, 500 ms, 1 retry | 1 unit |

`fake-delta` is the spare family: eligibility precedes the panel, so it is drawn only when one of the first three is ineligible. The package's generator (`extractive-d19-v1`) has the family `extractive-d19`, which no registry member has.

**Daily budgets** (PD-26; A-15 open, hold H9): development 100000 units; staging, production and default 0 (every adapter ineligible). Alert at 4/5. Each registry's budget is one row per UTC day in the application database, shared by every instance, and so is its stop. Every attempt an adapter sends reserves its cost, retries included.

**Embedding egress** (`gateway.embeddings`, PD-26; the Phase 2 semantic backend's, never a panel member): provider `openai-embeddings`, model none (no model is chosen while D-07, D-12 or Q-09 is open or the Q-15 review is pending; a named one must be pinned); caps 256 inputs per request, 8000 characters per input, 10000 ms, 2 retries; 1 unit per input and attempt. The gateway gives no embedder: a query embedding would send the learner's query text, which plan H never lets leave (Phase 5 spec 4.19).

## Degraded-mode matrix (`degraded-matrix-v1`; D-29 (a), PD-23)

| Mode (eligible members) | Tier 1 | Tier 2 | Tier 3 | Response |
|---|---|---|---|---|
| FULL (3) | 1oo3 | 2oo3 | equal weights ≥ 2/3 | as voted |
| REDUCED-2 (2) | 1oo2 | 1oo2 | 1oo2 | label `degraded`, banner `degraded-reduced-2-v1` |
| REDUCED-1 (1) | withheld, queued for V3 | withheld, queued (D-29 (a)) | equal weights on the remaining verifier | label `degraded`, banner `degraded-reduced-1-v1` |
| ZERO (0) | withheld, queued | withheld, queued | withheld, queued | no call; withhold and queue (no pre-verified source, DI-83); banner `degraded-zero-v1` |

Registering any model outside development follows plan 13.9 (a) and needs DI-69, DI-70, DI-71 and DI-72 closed.
