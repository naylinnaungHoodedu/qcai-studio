# Fictional User Accounts and User Commands

This artifact adds a reusable, privacy-safe audit fixture set for QA, demos, and professional audit evidence.

Source of truth:

- account and command fixture library: `apps/frontend/src/lib/audit-user-fixtures.ts`
- validation coverage: `apps/frontend/tests/audit-user-fixtures.integration.test.ts`

What is included:

- `17` fictional user accounts
- `45` realistic user commands
- role coverage for:
  - guest prospects
  - learners
  - instructors and creators
  - support and trust-and-safety staff
  - enterprise managers
  - parents and guardians
- edge-case coverage for:
  - accessibility-sensitive learners
  - low-bandwidth learners
  - failed renewals
  - locked accounts after suspicious login
  - duplicate-email recovery
  - guardian consent and minor access
  - privacy-rights requests
  - unsubscribed marketing preferences

Data-safety rules used in the fixture set:

- all names are fictional
- all emails use reserved or synthetic domains such as `ql.test`
- all phone numbers use synthetic `555` formatting
- no real addresses, passwords, secrets, or production identifiers are included

How to use it:

1. Seed the accounts in a non-production environment only.
2. Execute user commands as walkthroughs, test cases, or demo scripts.
3. Attach screenshots, logs, or tickets to the command ids for audit traceability.
4. Keep the fixture set synthetic and separate from real user data.
