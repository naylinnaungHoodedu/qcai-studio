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
ASSET_READER = "asset_reader"
DURABLE_LEARNER = "durable_learner"
STAFF = "staff"
ADMIN = "admin"
ARENA_TICKET = "arena_ticket"

ACCESS_LEVELS = {
    PUBLIC: "Anyone; no credential is read.",
    SERVICE: "No principal; called by the frontend server and guarded by its own checks (see the note).",
    PRINCIPAL: "Any verified principal: a signed guest token, a local-account session, an Auth0 token, or a demo identity.",
    ASSET_READER: "A verified principal whose role is learner or admin.",
    DURABLE_LEARNER: "A signed-in account (local or Auth0, not guest or demo) whose role is learner or admin.",
    STAFF: "A verified principal whose role is instructor or admin.",
    ADMIN: "A verified principal whose role is admin.",
    ARENA_TICKET: "A WebSocket from a trusted Origin offering a valid single-use Arena ticket (task 1.4).",
}

# Whose data a route touches.
NONE = "none"
CALLER = "caller"
OWNER = "owner"
NOT_OWNER = "not_owner"
PUBLIC_HANDLES = "public_handles"

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
    # Questions and tutor
    ("POST", "/qa/ask"): _p(PRINCIPAL, CALLER, "Rate-limited."),
    ("GET", "/qa/history"): _p(PRINCIPAL, CALLER),
    ("POST", "/assistant/chat"): _p(PRINCIPAL, OWNER, "A thread_id in the body must be the caller's thread."),
    ("GET", "/assistant/threads"): _p(PRINCIPAL, CALLER),
    ("POST", "/assistant/threads"): _p(PRINCIPAL, CALLER),
    ("GET", "/assistant/threads/{thread_id}"): _p(PRINCIPAL, OWNER),
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
