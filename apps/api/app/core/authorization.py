"""The route authorization matrix (plan task 1.2, R-02).

Every route the API serves has exactly one policy here. `tests/test_authorization.py` checks both ways:
each route's real dependencies match its declared access, every policy names a live route, and every
refused (access level, kind of caller) pair is refused. `python scripts/authorization_matrix.py` writes
`docs/security/authorization-matrix.md` from this table, and a test keeps that file current.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute

# Who may call. A demo identity exists only where demo auth is on, which settings allow in development.
PUBLIC = "public"
SERVICE = "service"
PRINCIPAL = "principal"
VERIFIED_PRINCIPAL = "verified_principal"
ASSET_READER = "asset_reader"
DURABLE_LEARNER = "durable_learner"
STAFF = "staff"
ADMIN = "admin"
REVIEWER = "reviewer"
ARENA_TICKET = "arena_ticket"

# The closed role set (Phase 6 spec 4.12): every role a route's dependencies name is one of these. A guest principal has
# role learner; no in-app grant of any role exists (reviewer provisioning is DI-91 with DI-38).
ROLES = ("learner", "instructor", "admin", "reviewer")

ACCESS_LEVELS = {
    PUBLIC: "Anyone; no credential is read.",
    SERVICE: "No principal; called by the frontend server and guarded by its own checks (see the note).",
    PRINCIPAL: "Any verified principal: a signed guest token, a local-account session, an Auth0 token, or a demo identity.",
    VERIFIED_PRINCIPAL: "A signed guest token, local-account session, or Auth0 token with a nonblank subject.",
    ASSET_READER: "A verified principal whose role is learner or admin.",
    DURABLE_LEARNER: "A signed-in account (local or Auth0, not guest or demo) whose role is learner or admin.",
    STAFF: "A verified principal whose role is instructor or admin.",
    ADMIN: "A verified principal whose role is admin.",
    REVIEWER: "A verified principal whose role is reviewer; outside development no caller is admitted while the reviewer pool (D-18) is unstaffed.",
    ARENA_TICKET: "A WebSocket from a trusted Origin offering a valid single-use Arena ticket (task 1.4).",
}

# Whose data a route touches.
NONE = "none"
CALLER = "caller"
OWNER = "owner"
NOT_OWNER = "not_owner"
PUBLIC_HANDLES = "public_handles"

# Roles that read any tutor ledger record, shadow records included: the plan's "reviewer" and nothing wider (plan 7.3
# "GET /ledger/responses/{response_id} (owner or reviewer)"). Each such read is a security event (plan 7.6 "reviewer
# access is logged"). No reviewer is provisioned yet (DI-38). Outside development LEDGER_ROUTE_ENABLED is false, so
# the route answers 404 to everyone, owners included (PD-12); and while the reviewer pool (D-18) is unstaffed a
# reviewer reads there as an owner (app.core.reviewer_access.reviewer_admitted, Phase 6).
LEDGER_READER_ROLES = ("reviewer",)

OWNERSHIP_SCOPES = {
    NONE: "No learner data.",
    CALLER: "Only the caller's own rows; no parameter names another learner.",
    OWNER: "Names an object; only its owner may act, and anyone else gets the same 404 as a missing id.",
    NOT_OWNER: "Names another learner's object; its owner may not act on it.",
    PUBLIC_HANDLES: "Other learners' public work, identified by public handle only (task 1.3).",
}


@dataclass(frozen=True)
class RoutePolicy:
    access: str
    ownership: str
    note: str = ""


def _p(access: str, ownership: str = NONE, note: str = "") -> RoutePolicy:
    return RoutePolicy(access, ownership, note)


V3_REVIEWER_NOTE = (
    "Reviewer role only: an authenticated caller of any other role gets 403 and authz.denied in every environment, and "
    "outside development every authenticated caller gets 403 and authz.denied while the reviewer pool (D-18) is "
    "unstaffed. Authentication comes first: a caller without a credential gets 401 and no security event where demo auth "
    "is off (the default outside development), a rejected bearer or guest token gets 401 with auth.credential_rejected, "
    "and a POST whose session or guest cookie fails the CSRF guard (an invalid cookie, no matching CSRF header or an "
    "untrusted Origin) gets 403 with request.forbidden before routing. An admitted reviewer gets 404 "
    "unless V3_QUEUE is shadow or on (development only by default). Claim text, public quotable span text, span ids and "
    "keyed digests only, never a learner identifier; a successful call is a v3.* security event."
)


ROUTE_POLICIES: dict[tuple[str, str], RoutePolicy] = {
    # Authentication and account
    ("GET", "/auth/me"): _p(PRINCIPAL, CALLER),
    ("POST", "/auth/register"): _p(PUBLIC, NONE, "Creates a learner account; rate-limited."),
    ("POST", "/auth/login"): _p(PUBLIC, NONE, "Rate-limited; failures are security events."),
    ("POST", "/auth/logout"): _p(PUBLIC, CALLER, "Ends the session named by the caller's own cookie."),
    ("DELETE", "/auth/account"): _p(PRINCIPAL, CALLER, "Local accounts only, with password confirmation."),
    ("POST", "/auth/guest-upgrade"): _p(SERVICE, NONE, "Legacy guest migration: closed by default, windowed, rate-limited (Action 20)."),
    # Course content
    ("GET", "/content/course"): _p(PUBLIC),
    ("HEAD", "/content/course"): _p(PUBLIC),
    ("GET", "/content/modules/{module_slug}"): _p(PUBLIC),
    ("HEAD", "/content/modules/{module_slug}"): _p(PUBLIC),
    ("GET", "/content/lessons/{lesson_slug}"): _p(PUBLIC),
    ("HEAD", "/content/lessons/{lesson_slug}"): _p(PUBLIC),
    ("GET", "/content/progress"): _p(PRINCIPAL, CALLER),
    ("GET", "/content/lessons/{lesson_slug}/notes"): _p(PRINCIPAL, CALLER),
    ("POST", "/content/lessons/{lesson_slug}/notes"): _p(PRINCIPAL, CALLER),
    ("POST", "/content/quiz-attempts"): _p(PRINCIPAL, CALLER, "The server scores the responses; no client score is read."),
    ("GET", "/source-assets/by-id/{asset_id}"): _p(ASSET_READER, NONE, "Approved corpus assets only (manifest governance)."),
    ("HEAD", "/source-assets/by-id/{asset_id}"): _p(ASSET_READER, NONE, "Approved corpus assets only (manifest governance)."),
    ("GET", "/source-assets/{filename}"): _p(ASSET_READER, NONE, "Approved corpus assets only (manifest governance)."),
    ("HEAD", "/source-assets/{filename}"): _p(ASSET_READER, NONE, "Approved corpus assets only (manifest governance)."),
    ("GET", "/search"): _p(PUBLIC, NONE, "Rate-limited."),
    ("GET", "/spans/{span_id}"): _p(PUBLIC, NONE, "Rate-limited span metadata; 404 unless SPAN_RESOLVER_ROUTE_ENABLED; no excerpt under D-31."),
    ("GET", "/evidence/spans/{span_id}"): _p(
        PUBLIC, NONE, "Alias of /spans/{span_id} (plan 7.3): the same SPAN_RESOLVER_ROUTE_ENABLED flag, rate limit and D-31 rules; public license_class only."
    ),
    # Questions and tutor
    ("POST", "/qa/ask"): _p(PRINCIPAL, CALLER, "Rate-limited."),
    ("GET", "/qa/history"): _p(PRINCIPAL, CALLER),
    ("POST", "/assistant/chat"): _p(PRINCIPAL, OWNER, "A thread_id in the body must be the caller's thread."),
    ("GET", "/assistant/threads"): _p(PRINCIPAL, CALLER),
    ("POST", "/assistant/threads"): _p(PRINCIPAL, CALLER),
    ("GET", "/assistant/threads/{thread_id}"): _p(PRINCIPAL, OWNER),
    ("POST", "/tutor/turns"): _p(
        PRINCIPAL,
        OWNER,
        "Two-pass tutor endpoint (plan 7.3). 404 outside development unless TWO_PASS_TUTOR is on, which settings refuse "
        "before the Phase 4 exit; returns the legacy contained answer and runs the two-pass pipeline in shadow. A "
        "thread_id in the body must be the caller's thread. Rate-limited.",
    ),
    ("GET", "/ledger/responses/{response_id}"): _p(
        PRINCIPAL,
        OWNER,
        "404 unless LEDGER_ROUTE_ENABLED. The turn's owner reads its legacy record (a pre-ledger turn reads as "
        "no-verdict); the reviewer role reads any record, shadow records included, and each such read is a security "
        "event; outside development while the reviewer pool (D-18) is unstaffed, a reviewer reads as an owner. Any other "
        "role, admin included, reads only its own turns. A learner never sees a shadow record (AC-3-6).",
    ),
    # V3 audit and adjudication (Phase 6)
    ("POST", "/v3/flags"): _p(
        PRINCIPAL,
        OWNER,
        "404 to every authenticated caller outside development, and unless V3_QUEUE is shadow or on (a caller without a "
        "credential gets 401 where demo auth is off). The caller's own tutor turn only: another learner's, "
        "a missing and a pre-ledger turn get the same 404. Sets F_i = 0 and queues the response (X3); changes no verdict and "
        "no ledger row. Rate-limited.",
    ),
    **{key: _p(REVIEWER, NONE, V3_REVIEWER_NOTE) for key in (
        ("GET", "/v3/queue"), ("POST", "/v3/scan"), ("GET", "/v3/items/{item_id}"), ("POST", "/v3/items/{item_id}/claim"),
        ("POST", "/v3/items/{item_id}/adjudicate"), ("POST", "/v3/items/{item_id}/apply"), ("GET", "/v3/metrics"))},
    # Analytics
    ("POST", "/analytics/events"): _p(PRINCIPAL, CALLER),
    ("POST", "/analytics/public-web-vitals"): _p(PUBLIC, NONE, "Anonymous browser metrics; rate-limited."),
    ("GET", "/analytics/public-web-vitals/summary"): _p(PUBLIC, NONE, "Aggregates only."),
    # Administration
    ("POST", "/admin/rebuild-content"): _p(STAFF),
    ("POST", "/admin/guest-revocations"): _p(ADMIN, NONE, "Recorded as a security event."),
    # Arena (off outside development, Decision D-03)
    ("GET", "/arena/leaderboard"): _p(PUBLIC, PUBLIC_HANDLES),
    ("GET", "/arena/me"): _p(PRINCIPAL, CALLER),
    ("GET", "/arena/status"): _p(PUBLIC, NONE, "Counts only."),
    ("POST", "/arena/ticket"): _p(PRINCIPAL, CALLER, "The ticket is bound to the caller."),
    ("WS", "/arena/ws"): _p(ARENA_TICKET, CALLER, "The player is the ticket's principal."),
    # Builder
    ("GET", "/builder/scenarios"): _p(PRINCIPAL, CALLER),
    ("GET", "/builder/profile"): _p(PRINCIPAL, CALLER),
    ("GET", "/builder/feed"): _p(PUBLIC, PUBLIC_HANDLES),
    ("POST", "/builder/submit"): _p(PRINCIPAL, CALLER),
    ("POST", "/builder/share"): _p(PRINCIPAL, CALLER),
    # Insights
    ("GET", "/insights/dashboard"): _p(PRINCIPAL, CALLER),
    ("GET", "/insights/profile"): _p(PRINCIPAL, CALLER),
    ("PUT", "/insights/profile"): _p(PRINCIPAL, CALLER),
    ("POST", "/insights/check-ins"): _p(PRINCIPAL, CALLER),
    ("GET", "/insights/path"): _p(PRINCIPAL, CALLER),
    ("GET", "/insights/skill-gap"): _p(PRINCIPAL, CALLER),
    ("POST", "/insights/realtime-feedback"): _p(PRINCIPAL, CALLER),
    # Learner record
    ("GET", "/learner-record"): _p(DURABLE_LEARNER, CALLER),
    ("POST", "/learner-record/operations"): _p(DURABLE_LEARNER, CALLER),
    ("POST", "/learner-record/replicas"): _p(DURABLE_LEARNER, CALLER, "Phase 8 replica issuance."),
    ("POST", "/auth/guest-claim"): _p(DURABLE_LEARNER, CALLER, "Phase 8. Also requires a verified guest session."),
    ("GET", "/auth/learner-consent"): _p(VERIFIED_PRINCIPAL, CALLER, "Phase 8 provisional consent."),
    ("PUT", "/auth/learner-consent"): _p(VERIFIED_PRINCIPAL, CALLER, "Phase 8 provisional consent."),
    ("GET", "/auth/learner-export"): _p(VERIFIED_PRINCIPAL, CALLER, "Phase 8 local learner data."),
    ("POST", "/auth/learner-erasure"): _p(VERIFIED_PRINCIPAL, CALLER, "Phase 8 local erasure and receipt."),
    # Projects
    ("GET", "/projects/catalog"): _p(PUBLIC),
    ("GET", "/projects/my-submissions"): _p(PRINCIPAL, CALLER),
    ("GET", "/projects/review-queue"): _p(PRINCIPAL, PUBLIC_HANDLES, "Other learners' submissions, never the caller's own."),
    ("POST", "/projects/submissions"): _p(PRINCIPAL, CALLER),
    ("POST", "/projects/reviews"): _p(PRINCIPAL, NOT_OWNER, "Missing and retracted submissions get the same 404."),
    ("DELETE", "/projects/submissions/{submission_id}"): _p(PRINCIPAL, OWNER),
    # Support and operations
    ("POST", "/support/requests"): _p(PUBLIC, NONE, "Rate-limited."),
    ("GET", "/health"): _p(PUBLIC),
    ("GET", "/ready"): _p(PUBLIC),
}


def served_routes(app: FastAPI, routers: Iterable[APIRouter]) -> list[APIRoute | APIWebSocketRoute]:
    """Every API route: the included routers' routes, then the app's own (FastAPI's docs routes excluded)."""
    routes = [route for router in routers for route in router.routes]
    routes += [route for route in app.router.routes if isinstance(route, (APIRoute, APIWebSocketRoute))]
    return [route for route in routes if isinstance(route, (APIRoute, APIWebSocketRoute))]


def route_keys(routes: Iterable[APIRoute | APIWebSocketRoute]) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    for route in routes:
        if isinstance(route, APIWebSocketRoute):
            keys.append(("WS", route.path))
        else:
            keys.extend((method, route.path) for method in sorted(route.methods))
    return keys


def render_matrix(live_routes: list[tuple[str, str]]) -> str:
    """The matrix document, in the order the API serves its routes."""
    lines = [
        "# Authorization matrix",
        "",
        "Generated from `apps/api/app/core/authorization.py` by `python scripts/authorization_matrix.py`;",
        "do not edit by hand. `apps/api/tests/test_authorization.py` checks that every route has a policy,",
        "that each policy matches the route's real dependencies, and that this file is current (plan task 1.2).",
        "",
        "## Access levels",
        "",
        "| Access | Who may call |",
        "|---|---|",
        *(f"| `{name}` | {description} |" for name, description in ACCESS_LEVELS.items()),
        "",
        "## Ownership scopes",
        "",
        "| Ownership | Meaning |",
        "|---|---|",
        *(f"| `{name}` | {description} |" for name, description in OWNERSHIP_SCOPES.items()),
        "",
        "## Routes",
        "",
        "| Method | Path | Access | Ownership | Note |",
        "|---|---|---|---|---|",
    ]
    for method, path in live_routes:
        policy = ROUTE_POLICIES[(method, path)]
        lines.append(f"| {method} | `{path}` | `{policy.access}` | `{policy.ownership}` | {policy.note} |")
    return "\n".join(lines) + "\n"
