# Phase 8 provisional learner consent

PD-200 uses consent version `d27-unresolved-v1` while D-27 remains open. The three classes are adaptation, analytics, and research. Absent or stale state denies phase-controlled processing. Development may record adaptation and analytics grants for synthetic evaluation. Research grants are refused in every environment. Outside development the freeze retains the current processing policy and refuses new grants.

The consent row uses `user_id` and `consent_class` as its key and records `consent_version`, `granted`, `updated_at`, and `source`. Consent changes append an erasable history row. Guest consent does not become account consent when a record is claimed.

The retention register covers every table discovered by the erasure metadata. Sessions expire on their existing expiry timestamp. Guest legacy-upgrade records and ordinary guest-study data use the existing 365-day period. Consent ages from its last update. Subject bindings remain until explicit erasure. Revocation tombstones continue to protect previously revoked credentials. Security events and independently submitted support records follow their separate existing rules.
