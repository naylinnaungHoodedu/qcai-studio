# ADR-006: Security model

## Context

RevB §6.3 and §8 require PKCE, CSRF, CSP, hardened headers, authentication abuse testing, dependency scanning, and a threat model.

## Decision

Use Auth0 authorization-code PKCE where configured, server-verified JWTs/local opaque hashed sessions, CSRF/origin checks for cookie mutations, nonce CSP, non-root containers, and CI SCA. Durable learner-record endpoints reject guest/demo identities.

## Consequences

Open demo access cannot be silently promoted to cross-device persistence. Threat model, dependency-scan outputs, session rotation/device management, and configured IdP proof still require G1/G2 evidence.
