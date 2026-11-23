# Phase 8 identity linking

A verified principal binds to a random learner subject through a provider-scoped digest. The guest signing key can rotate independently. New bindings require identity to be enabled. An existing binding continues to address the same learner record after flag rollback. Legacy credentials and ordinary activity remain attached to the principal. Erasure serializes writers and verifies both keys and their dependent rows.

The guest claim requires a durable principal, a verified guest token, its matching CSRF proof, and a trusted origin. The claim rejects revoked, previously claimed, and known public guest identifiers. The transfer, one-shot revocation tombstone, and audit row share a transaction. The audit has keyed digests and table counts. The revocation tombstone uses a domain-separated digest whose recognition survives key rotation and feature rollback.

The merge takes per-skill mastery maxima, unions completions, takes componentwise attempt and clock maxima, and keeps the winning cursor or preference. Where a unique record such as a public handle collides, the pre-existing account row wins. Duplicate operation keys retain the account's receipt while the materialized record joins both sides.

The claim emits `subject.claimed` with the transferred-row count or `subject.claim_refused` for a denied claim. Review the structured security logs for outcomes and the linking audit table for the claim time, keyed digests, and table counts. The receipt audit keeps a receipt identifier, canonical receipt hash, table-set hash, and deleted total. Both audit tables use the existing 365-day security retention period when privacy cleanup is active. These audit rows outlive learner erasure within that period.
