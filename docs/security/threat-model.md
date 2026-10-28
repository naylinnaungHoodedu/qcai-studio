# CS595 security threat model - initial version

| Asset / boundary | Threat | Control | Verification |
| --- | --- | --- | --- |
| OIDC authorization | State/PKCE theft or callback mix-up | Server-side state/verifier cookies, S256 challenge, issuer/audience/JWKS validation | Auth route and callback regression tests. |
| Local sessions | Token theft/fixation/CSRF | Opaque hashed token, secure/HttpOnly/SameSite cookie, origin + CSRF double-submit validation, logout revocation | Auth abuse/session tests. |
| Learner Record | Stale replica overwrites completion or replay double-counts | Operation ID hash, replica/logical counter, set/max/G-counter merge semantics | Randomized interleaving and replay tests. |
| Tutor | Learner-state information treated as cited fact | Pedagogical/evidence channel separation, provenance, claim gate | RQ2 invariance and leakage-negative tests. |
| Corpus | Licensed text served/released publicly | Reviewed public manifest, production fail-close, release preflight, private storage policy | Corpus validator + release preflight. |
| AI/provider | Prompt injection, model/provider failure, fabricated claim | Sanitization, bounded history, retrieval only, lexical fallback, claim gate/abstention | Integration and four-arm evaluation. |
| Supply chain | Vulnerable dependency/container | Locked dependencies, CI `pip-audit`, image/SBOM evidence before G2 release | CI and release checklist. |

This is a living G1 artifact. The final version must record risks, owners, remediation status, and no-open-critical finding evidence.
