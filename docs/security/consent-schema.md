# Phase 8 provisional learner consent

PD-200 uses consent version `d27-unresolved-v1` while D-27 remains open. The three classes are adaptation, analytics, and research. Absent or stale state denies phase-controlled processing. Development may record adaptation and analytics grants for synthetic evaluation. Research grants are refused in every environment. Outside development the freeze retains the current processing policy and refuses new grants.

The consent row uses `user_id` and `consent_class` as its key and records `consent_version`, `granted`, `updated_at`, and `source`. Consent changes append an erasable history row. Guest consent does not become account consent when a record is claimed.

The retention register covers every user-keyed table. Durable records stay until erasure unless a specific expiry applies. With `LEARNER_PRIVACY=on`, the job recognizes bound guests by provider. Guest consent ages from its update time, and guest legacy-upgrade records expire after 365 days while a digest protects the one-shot rule. Sessions use explicit expiry. Bindings remain until erasure. Identifier-free linking and erasure audit rows expire after 365 days with privacy enabled. Support contacts retain their separate 540-day rule under P2-12-D-05.

| Table | Retention class |
|---|---|
| `analytics_events` | `guest-created/durable-until-erasure` |
| `arena_match_records` | `guest-created/durable-until-erasure` |
| `arena_profiles` | `guest-created/durable-until-erasure` |
| `builder_runs` | `guest-created/durable-until-erasure` |
| `builder_shares` | `guest-created/durable-until-erasure` |
| `guest_legacy_upgrades` | `guest-upgrade-age` |
| `guest_revocations` | `credential-protection` |
| `learner_assessment_facts` | `guest-created/durable-until-erasure` |
| `learner_consent_changes` | `guest-created/durable-until-erasure` |
| `learner_consents` | `guest-updated/durable-until-erasure` |
| `learner_issued_replicas` | `guest-created/durable-until-erasure` |
| `learner_profiles` | `guest-created/durable-until-erasure` |
| `learner_record_operations` | `guest-created/durable-until-erasure` |
| `learner_records` | `guest-created/durable-until-erasure` |
| `learner_replicas` | `guest-created/durable-until-erasure` |
| `learner_subjects` | `until-erasure` |
| `learning_pulses` | `guest-created/durable-until-erasure` |
| `notes` | `guest-created/durable-until-erasure` |
| `peer_reviews` | `guest-created/durable-until-erasure` |
| `project_submissions` | `guest-created/durable-until-erasure` |
| `public_handles` | `guest-created/durable-until-erasure` |
| `qa_interactions` | `guest-created/durable-until-erasure` |
| `quiz_attempts` | `guest-created/durable-until-erasure` |
| `tutor_threads` | `guest-created/durable-until-erasure` |
| `tutor_turn_idempotency` | `guest-created/durable-until-erasure` |
| `tutor_turns` | `guest-created/durable-until-erasure` |
| `user_accounts` | `until-erasure` |
| `user_sessions` | `session-expiry` |
