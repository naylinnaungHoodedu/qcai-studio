# ADR-006: Security model

## Context

RevB §6.3 and §8 require PKCE, CSRF, CSP, hardened headers, authentication abuse testing, dependency scanning, and a threat model.

## Decision

Use Auth0 authorization-code PKCE where configured, server-verified JWTs/local opaque hashed sessions, CSRF/origin checks for cookie mutations, nonce CSP, non-root containers, and CI SCA. Durable learner-record endpoints reject guest/demo identities.

## Consequences

Open demo access cannot be silently promoted to cross-device persistence. Threat model, dependency-scan outputs, session rotation/device management, and configured IdP proof still require G1/G2 evidence.

## Revision 2026-11-21 (Phase 5: provider egress, keys and redaction)

- **The gateway is the only reader of a model-provider credential** (plan 7.1 "The gateway MUST be the sole holder of provider credentials [Risk R-06]"). `apps/api/app/gateway/` reads a key through its `SecretStore` (`EnvironmentSecretStore`: the process environment, which is how Cloud Run mounts Secret Manager secrets; no SDK, no network call) once per call; no adapter attribute holds it, and the gateway never discovers application-default credentials (E-109). That includes `OPENAI_API_KEY`, the Phase 2 semantic backend's embedding key: no setting holds it, and `app/gateway/embeddings.py` holds the embedding egress, behind the D-23 opt-in, closed provider decisions and the Q-15 review (Phase 5 spec 4.19). The AST guard `test_gateway_egress_guard.py` refuses a provider SDK or HTTP client import anywhere else in the API image, with one allow-list entry, the vector index client (`pinecone`) of the retrieval engine, reached only with an embedder the gateway gives; and it refuses a provider host name in a string literal of the Python files under `apps/api/app`, `scripts`, `evaluation` (its tests included) and `tools` outside the gateway package (`apps/api/tests`, `apps/frontend`, `infra` and every non-Python file are not scanned).
- **Per-environment egress opt-in (D-23, PD-22).** A non-fake provider is ineligible unless the environment's `MODEL_EGRESS_PROVIDERS` names it; the list is empty in every environment, development included, and no non-fake provider is registered anywhere (D-12, D-07, Q-09 open).
- **Keys only in headers; error redaction** (task 5.12). `HttpJsonAdapter` refuses an endpoint with a query, userinfo or fragment; the key travels as `Authorization: Bearer` or `x-api-key`; every failure, an undecodable body and any other httpx error included, is raised after its `except` block, so no httpx object (whose request holds the headers) is reachable from the error, and its text names the adapter, the kind and the status only; the gateway turns any other adapter exception into an adapter error, so a misbehaving member is only unavailable. A key read is registered with the log redaction, owner `gateway`.
- **Three stop guards** (plan Phase 5 L "Stop on a payload violation, secret in logs or budget breach"): a payload-policy refusal, a gateway-owned secret reaching a log record (the redaction listener only sets a flag; the gateway stops at its next call), or a call crossing the daily budget (or reporting a cost above its reservation) stops the gateway, logs `gateway.stopped` and writes the security event `gateway.stopped`; every later call is refused and the V2 mode is off. The stop is written to the registry's shared stop in the application database (`gateway_stops`): every other instance and every new process adopts it before its next eligibility decision or call, and only an operator clears it (`python -m app.workers.gateway_stop --clear`, security event `gateway.stop_cleared`). The daily budget is shared the same way (`gateway_budget_days`), so the hard stop holds across instances.
- **Retired provider code.** The dead Vertex path and its settings are removed (Phase 5 spec 4.18); a retired variable that a deployment still sets in the process environment is named at start-up (`gateway.retired_setting`) and its value stays masked.
