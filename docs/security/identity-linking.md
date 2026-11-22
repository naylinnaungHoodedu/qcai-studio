# Phase 8 identity linking

A verified principal binds to a random learner subject through a provider-scoped digest. The binding is independent of the guest signing-key rotation and is absent from the baseline credential path when learner identity is off. Learner-record writes and server-scored mastery use the bound subject. Legacy account credentials and ordinary activity routes continue to use the authenticated principal. Erasure traverses both keys.

The guest claim requires a durable principal, a verified guest token, its matching CSRF proof, and a trusted origin. The claim rejects revoked, previously claimed, and known public guest identifiers. The transfer, one-shot revocation tombstone, and audit row share a transaction. The audit has keyed digests and table counts. The revocation tombstone uses a domain-separated digest whose recognition survives key rotation and feature rollback.

The merge takes per-skill mastery maxima, unions completions, takes componentwise attempt and clock maxima, and keeps the winning cursor or preference. Where a unique record such as a public handle collides, the pre-existing account row wins. Duplicate operation keys retain the account's receipt while the materialized record joins both sides.
