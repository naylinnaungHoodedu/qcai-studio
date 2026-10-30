# Authorization matrix

Generated from `apps/api/app/core/authorization.py` by `python scripts/authorization_matrix.py`;
do not edit by hand. `apps/api/tests/test_authorization.py` checks that every route has a policy,
that each policy matches the route's real dependencies, and that this file is current (plan task 1.2).

## Access levels

| Access | Who may call |
|---|---|
| `public` | Anyone; no credential is read. |
| `service` | No principal; called by the frontend server and guarded by its own checks (see the note). |
| `principal` | Any verified principal: a signed guest token, a local-account session, an Auth0 token, or a demo identity. |
| `asset_reader` | A verified principal whose role is learner or admin. |
| `durable_learner` | A signed-in account (local or Auth0, not guest or demo) whose role is learner or admin. |
| `staff` | A verified principal whose role is instructor or admin. |
| `admin` | A verified principal whose role is admin. |
| `arena_ticket` | A WebSocket from a trusted Origin offering a valid single-use Arena ticket (task 1.4). |

## Ownership scopes

| Ownership | Meaning |
|---|---|
| `none` | No learner data. |
| `caller` | Only the caller's own rows; no parameter names another learner. |
| `owner` | Names an object; only its owner may act, and anyone else gets the same 404 as a missing id. |
| `not_owner` | Names another learner's object; its owner may not act on it. |
| `public_handles` | Other learners' public work, identified by public handle only (task 1.3). |

## Routes

| Method | Path | Access | Ownership | Note |
|---|---|---|---|---|
| GET | `/auth/me` | `principal` | `caller` |  |
| POST | `/auth/register` | `public` | `none` | Creates a learner account; rate-limited. |
| POST | `/auth/login` | `public` | `none` | Rate-limited; failures are security events. |
| POST | `/auth/logout` | `public` | `caller` | Ends the session named by the caller's own cookie. |
| DELETE | `/auth/account` | `principal` | `caller` | Local accounts only, with password confirmation. |
| POST | `/auth/guest-upgrade` | `service` | `none` | Legacy guest migration: closed by default, windowed, rate-limited (Action 20). |
| GET | `/content/course` | `public` | `none` |  |
| HEAD | `/content/course` | `public` | `none` |  |
| GET | `/content/modules/{module_slug}` | `public` | `none` |  |
| HEAD | `/content/modules/{module_slug}` | `public` | `none` |  |
| GET | `/content/lessons/{lesson_slug}` | `public` | `none` |  |
| HEAD | `/content/lessons/{lesson_slug}` | `public` | `none` |  |
| GET | `/content/progress` | `principal` | `caller` |  |
| GET | `/content/lessons/{lesson_slug}/notes` | `principal` | `caller` |  |
| POST | `/content/lessons/{lesson_slug}/notes` | `principal` | `caller` |  |
| POST | `/content/quiz-attempts` | `principal` | `caller` | The server scores the responses; no client score is read. |
| GET | `/source-assets/by-id/{asset_id}` | `asset_reader` | `none` | Approved corpus assets only (manifest governance). |
| HEAD | `/source-assets/by-id/{asset_id}` | `asset_reader` | `none` | Approved corpus assets only (manifest governance). |
| GET | `/source-assets/{filename}` | `asset_reader` | `none` | Approved corpus assets only (manifest governance). |
| HEAD | `/source-assets/{filename}` | `asset_reader` | `none` | Approved corpus assets only (manifest governance). |
| GET | `/search` | `public` | `none` | Rate-limited. |
| POST | `/qa/ask` | `principal` | `caller` | Rate-limited. |
| GET | `/qa/history` | `principal` | `caller` |  |
| POST | `/assistant/chat` | `principal` | `owner` | A thread_id in the body must be the caller's thread. |
| GET | `/assistant/threads` | `principal` | `caller` |  |
| POST | `/assistant/threads` | `principal` | `caller` |  |
| GET | `/assistant/threads/{thread_id}` | `principal` | `owner` |  |
| POST | `/analytics/events` | `principal` | `caller` |  |
| POST | `/analytics/public-web-vitals` | `public` | `none` | Anonymous browser metrics; rate-limited. |
| GET | `/analytics/public-web-vitals/summary` | `public` | `none` | Aggregates only. |
| POST | `/admin/rebuild-content` | `staff` | `none` |  |
| POST | `/admin/guest-revocations` | `admin` | `none` | Recorded as a security event. |
| GET | `/arena/leaderboard` | `public` | `public_handles` |  |
| GET | `/arena/me` | `principal` | `caller` |  |
| GET | `/arena/status` | `public` | `none` | Counts only. |
| POST | `/arena/ticket` | `principal` | `caller` | The ticket is bound to the caller. |
| WS | `/arena/ws` | `arena_ticket` | `caller` | The player is the ticket's principal. |
| GET | `/builder/scenarios` | `principal` | `caller` |  |
| GET | `/builder/profile` | `principal` | `caller` |  |
| GET | `/builder/feed` | `public` | `public_handles` |  |
| POST | `/builder/submit` | `principal` | `caller` |  |
| POST | `/builder/share` | `principal` | `caller` |  |
| GET | `/insights/dashboard` | `principal` | `caller` |  |
| GET | `/insights/profile` | `principal` | `caller` |  |
| PUT | `/insights/profile` | `principal` | `caller` |  |
| POST | `/insights/check-ins` | `principal` | `caller` |  |
| GET | `/insights/path` | `principal` | `caller` |  |
| GET | `/insights/skill-gap` | `principal` | `caller` |  |
| POST | `/insights/realtime-feedback` | `principal` | `caller` |  |
| GET | `/learner-record` | `durable_learner` | `caller` |  |
| POST | `/learner-record/operations` | `durable_learner` | `caller` |  |
| GET | `/projects/catalog` | `public` | `none` |  |
| GET | `/projects/my-submissions` | `principal` | `caller` |  |
| GET | `/projects/review-queue` | `principal` | `public_handles` | Other learners' submissions, never the caller's own. |
| POST | `/projects/submissions` | `principal` | `caller` |  |
| POST | `/projects/reviews` | `principal` | `not_owner` | Missing and retracted submissions get the same 404. |
| DELETE | `/projects/submissions/{submission_id}` | `principal` | `owner` |  |
| POST | `/support/requests` | `public` | `none` | Rate-limited. |
| GET | `/health` | `public` | `none` |  |
| GET | `/ready` | `public` | `none` |  |
