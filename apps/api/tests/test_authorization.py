"""Route authorization matrix, negatives and object ownership (plan task 1.2, R-02; CT-05 "0 negatives accepted")."""

from pathlib import Path
import time
from uuid import uuid4

import pytest
from fastapi.routing import APIWebSocketRoute
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core import authorization as authz
from app.core.config import DEVELOPMENT_GUEST_TOKEN_SECRET, Settings, get_settings
from app.core.db import SessionLocal
from app.core.guest_tokens import GUEST_TOKEN_COOKIE, guest_csrf_for, issue_guest_token
from app.db_models import ProjectSubmission, QuizAttempt, ResponseLedgerRecord, SecurityEvent, TutorMessage
from app.main import ROUTERS, app
from app.services.store import get_course_store

REPO_ROOT = Path(__file__).resolve().parents[3]
TRUSTED_ORIGIN = "http://localhost:3000"
PASSWORD = "S3cureQuantumPath"
LESSON_SLUG = "ai4qc-routing-and-optimization"
PROJECT_SLUG = "routing-rescue-playbook"
SERVED = authz.served_routes(app, ROUTERS)
ROUTE_KEYS = authz.route_keys(SERVED)

KINDS = ("anonymous", "guest", "local_learner", "demo_learner", "demo_instructor", "demo_admin", "demo_reviewer")
ALLOWED_KINDS = {
    authz.PUBLIC: set(KINDS),
    authz.SERVICE: set(KINDS),
    authz.PRINCIPAL: set(KINDS) - {"anonymous"},
    authz.ASSET_READER: {"guest", "local_learner", "demo_learner", "demo_admin"},
    authz.DURABLE_LEARNER: {"local_learner"},
    authz.STAFF: {"demo_instructor", "demo_admin"},
    authz.ADMIN: {"demo_admin"},
    # Phase 6: the V3 reviewer routes (in development, where the reviewer gate admits a synthetic demo reviewer).
    authz.REVIEWER: {"demo_reviewer"},
}


def _source() -> dict[str, str]:
    # A distinct client address keeps the per-address HTTP rate limits of separate tests apart.
    return {"x-forwarded-for": f"203.0.113.{uuid4().int % 250 + 1}"}


# --- The matrix itself ---


def test_every_route_has_exactly_one_policy_and_every_policy_a_route():
    assert len(ROUTE_KEYS) == len(set(ROUTE_KEYS))
    assert set(ROUTE_KEYS) - set(authz.ROUTE_POLICIES) == set(), "routes without a policy"
    assert set(authz.ROUTE_POLICIES) - set(ROUTE_KEYS) == set(), "policies for routes that no longer exist"
    assert set(ALLOWED_KINDS) | {authz.ARENA_TICKET} == set(authz.ACCESS_LEVELS)


def _dependency_calls(dependant) -> list:
    calls = []
    for sub in dependant.dependencies:
        calls.append(sub.call)
        calls.extend(_dependency_calls(sub))
    return calls


def _actual_access(route) -> str:
    if isinstance(route, APIWebSocketRoute):
        return authz.ARENA_TICKET
    calls = _dependency_calls(route.dependant)
    names = {getattr(call, "__name__", "") for call in calls}
    role_sets = {getattr(call, "allowed_roles") for call in calls if hasattr(call, "allowed_roles")}
    if role_sets == {frozenset({"admin"})}:
        return authz.ADMIN
    if role_sets == {frozenset({"instructor", "admin"})}:
        return authz.STAFF
    if role_sets == {frozenset({"reviewer"})}:
        return authz.REVIEWER
    assert not role_sets, f"{route.path}: unrecognised role set {role_sets}"
    if "require_durable_learner" in names:
        return authz.DURABLE_LEARNER
    if "_require_asset_access" in names:
        return authz.ASSET_READER
    if "get_current_user" in names:
        return authz.PRINCIPAL
    return "none"


def test_every_route_names_roles_of_the_closed_role_set():
    # Phase 6 spec 4.12: roles are a closed set; a dependency naming any other role would be a role nobody can hold.
    named = set()
    for route in SERVED:
        if isinstance(route, APIWebSocketRoute):
            continue
        for call in _dependency_calls(route.dependant):
            named |= set(getattr(call, "allowed_roles", ()))
    assert named and named <= set(authz.ROLES), sorted(named - set(authz.ROLES))
    assert "reviewer" in named and authz.LEDGER_READER_ROLES == ("reviewer",)


def test_each_policy_matches_the_route_dependencies():
    mismatches = []
    for route in SERVED:
        actual = _actual_access(route)
        for key in authz.route_keys([route]):
            if key not in authz.ROUTE_POLICIES:
                continue  # reported by the coverage test
            declared = authz.ROUTE_POLICIES[key].access
            expected = "none" if declared in {authz.PUBLIC, authz.SERVICE} else declared
            if actual != expected:
                mismatches.append(f"{key}: declared {declared}, dependencies say {actual}")
    assert mismatches == []


def test_the_committed_matrix_is_current():
    committed = (REPO_ROOT / "docs" / "security" / "authorization-matrix.md").read_text(encoding="utf-8")
    assert committed.replace("\r\n", "\n") == authz.render_matrix(ROUTE_KEYS)


def test_the_arena_id_lookup_is_gone():
    # It mapped an internal player id to a public handle and confirmed which ids had profiles (R-03).
    assert all("/arena/profiles" not in path for _, path in ROUTE_KEYS)
    assert TestClient(app).get("/arena/profiles/guest-0123456789abcdef").status_code == 404


# --- Negatives: every refused (route, kind of caller) pair is refused ---


@pytest.fixture(scope="module")
def local_learner() -> tuple[TestClient, dict[str, str]]:
    browser = TestClient(app)
    response = browser.post(
        "/auth/register", json={"email": f"authz-{uuid4().hex[:8]}@example.com", "password": PASSWORD}, headers=_source()
    )
    assert response.status_code == 201
    return browser, {"origin": TRUSTED_ORIGIN, "x-qcai-csrf": browser.cookies.get("qcai_auth_csrf")}


def _guest() -> tuple[TestClient, dict[str, str], str]:
    guest_id = f"guest-{uuid4().hex}"
    issued = int(time.time())
    browser = TestClient(app)
    browser.cookies.set(GUEST_TOKEN_COOKIE, issue_guest_token(DEVELOPMENT_GUEST_TOKEN_SECRET, guest_id, issued))
    return browser, {"origin": TRUSTED_ORIGIN, "x-qcai-csrf": guest_csrf_for(DEVELOPMENT_GUEST_TOKEN_SECRET, guest_id, issued)}, guest_id


def _demo(role: str) -> dict[str, str]:
    return {"x-demo-user": f"authz-{role}-{uuid4().hex[:8]}", "x-demo-role": role}


def _concrete(path: str) -> str:
    lesson = get_course_store().lessons[LESSON_SLUG]
    values = {
        "lesson_slug": LESSON_SLUG,
        "module_slug": lesson.module_slug,
        "thread_id": "thread-0000000000",
        "submission_id": "1",
        "asset_id": "none",
        "filename": "none.pdf",
        "response_id": "turn-00000000-0000-0000-0000-000000000000",
        "span_id": "span-" + "0" * 64,
        "item_id": "v3i-" + "0" * 24,
    }
    for name, value in values.items():
        path = path.replace("{" + name + "}", value)
    assert "{" not in path, path
    return path


# Routes without a policy are skipped here; test_every_route_has_exactly_one_policy_and_every_policy_a_route
# names them.
POLICED = [(key, authz.ROUTE_POLICIES[key]) for key in ROUTE_KEYS if key in authz.ROUTE_POLICIES]
DENIED = [
    (method, path, kind)
    for (method, path), policy in POLICED
    if policy.access in ALLOWED_KINDS
    for kind in KINDS
    if kind not in ALLOWED_KINDS[policy.access]
]


@pytest.mark.parametrize(("method", "path", "kind"), DENIED, ids=[f"{m} {p} as {k}" for m, p, k in DENIED])
def test_a_refused_caller_is_refused(method, path, kind, local_learner):
    body = {"json": {}} if method in {"POST", "PUT", "DELETE"} else {}
    if kind == "anonymous":
        app.dependency_overrides[get_settings] = lambda: Settings(
            environment="development", enable_demo_auth=False, allowed_origins=[TRUSTED_ORIGIN]
        )
        try:
            response = TestClient(app).request(method, _concrete(path), **body)
        finally:
            app.dependency_overrides.pop(get_settings, None)
        assert response.status_code == 401, response.text
        return
    if kind == "guest":
        browser, headers, _ = _guest()
    elif kind == "local_learner":
        browser, headers = local_learner
    else:
        browser, headers = TestClient(app), _demo(kind.removeprefix("demo_"))
    response = browser.request(method, _concrete(path), headers=headers, **body)
    assert response.status_code == 403, response.text


def test_there_are_negatives_for_every_restricted_access_level():
    levels = {authz.ROUTE_POLICIES[(method, path)].access for method, path, _ in DENIED}
    assert levels == {authz.PRINCIPAL, authz.ASSET_READER, authz.DURABLE_LEARNER, authz.STAFF, authz.ADMIN, authz.REVIEWER}


def test_a_role_denial_is_a_security_event(monkeypatch):
    # A fresh denial cap (60 a minute per event type, M6 of the Phase 6 spec): the negatives above record more denials
    # than one minute's cap, and a capped denial is dropped by design, so this test counts against its own cap.
    from app.services import security_log

    monkeypatch.setattr(security_log, "_caps", security_log._Caps())
    with SessionLocal() as db:
        start = db.scalar(select(func.max(SecurityEvent.seq))) or 0
    response = TestClient(app).post("/admin/guest-revocations", json={}, headers=_demo("learner"))

    assert response.status_code == 403
    with SessionLocal() as db:
        # Every matching event, in seq (append) order: one denial is exactly one event. Without ORDER BY, PostgreSQL
        # returns rows in physical order, so .first() would not name a defined row.
        events = db.scalars(
            select(SecurityEvent)
            .where(SecurityEvent.seq > start, SecurityEvent.event_type == "authz.denied")
            .order_by(SecurityEvent.seq)
        ).all()
    assert [event.details for event in events] == [{"route": "/admin/guest-revocations", "required": "role:admin", "provider": "demo"}]


# --- Object ownership: every owner-scoped route is tested here ---

OWNERSHIP_TESTED = {
    ("GET", "/assistant/threads/{thread_id}"),
    ("POST", "/assistant/chat"),
    ("POST", "/tutor/turns"),
    ("GET", "/ledger/responses/{response_id}"),
    ("DELETE", "/projects/submissions/{submission_id}"),
    ("POST", "/projects/reviews"),
    ("POST", "/v3/flags"),
}


def test_every_owner_scoped_route_has_an_ownership_test():
    scoped = {key for key, policy in authz.ROUTE_POLICIES.items() if policy.ownership in {authz.OWNER, authz.NOT_OWNER}}
    assert scoped == OWNERSHIP_TESTED


def _thread_for(headers: dict[str, str]) -> str:
    response = TestClient(app).post("/assistant/threads", json={"title": "Owner's private thread"}, headers=headers)
    assert response.status_code == 201
    return response.json()["id"]


def test_another_learners_thread_cannot_be_read_or_continued():
    owner, intruder = _demo("learner"), _demo("learner")
    thread_id = _thread_for(owner)
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(TutorMessage).where(TutorMessage.thread_id == thread_id))

    read = TestClient(app).get(f"/assistant/threads/{thread_id}", headers=intruder)
    missing = TestClient(app).get("/assistant/threads/thread-does-not-exist", headers=intruder)
    chat = TestClient(app).post(
        "/assistant/chat", json={"message": "What is routing depth?", "thread_id": thread_id}, headers=intruder
    )

    assert (read.status_code, read.json()) == (missing.status_code, missing.json()) == (404, {"detail": "Tutor thread not found."})
    assert (chat.status_code, chat.json()) == (404, {"detail": "Tutor thread not found."})
    with SessionLocal() as db:
        after = db.scalar(select(func.count()).select_from(TutorMessage).where(TutorMessage.thread_id == thread_id))
    assert after == before
    assert TestClient(app).get(f"/assistant/threads/{thread_id}", headers=owner).status_code == 200


def test_another_learners_thread_cannot_be_continued_through_tutor_turns():
    # Phase 3 (plan 7.3): POST /tutor/turns names a thread like /assistant/chat does; only its owner may continue it.
    owner, intruder = _demo("learner"), _demo("learner")
    thread_id = _thread_for(owner)
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(TutorMessage).where(TutorMessage.thread_id == thread_id))

    turn = TestClient(app).post("/tutor/turns", json={"message": "What is routing depth?", "thread_id": thread_id}, headers={**intruder, **_source()})

    assert (turn.status_code, turn.json()) == (404, {"detail": "Tutor thread not found."})
    with SessionLocal() as db:
        after = db.scalar(select(func.count()).select_from(TutorMessage).where(TutorMessage.thread_id == thread_id))
    assert after == before
    own = TestClient(app).post("/tutor/turns", json={"message": "What is routing depth?", "thread_id": thread_id}, headers={**owner, **_source()})
    assert own.status_code == 200 and own.json()["thread_id"] == thread_id


def test_another_learners_ledger_record_reads_as_missing():
    # Phase 3 (plan 7.3 "owner or reviewer"): an intruder gets exactly the missing-id 404; the owner reads the record,
    # and never a shadow record (AC-3-6).
    owner, intruder = _demo("learner"), _demo("learner")
    chat = TestClient(app).post("/assistant/chat", json={"message": "Why does routing depth matter?"}, headers={**owner, **_source()})
    assert chat.status_code == 200
    turn_id = chat.json()["turn_id"]

    own = TestClient(app).get(f"/ledger/responses/{turn_id}", headers=owner)
    theirs = TestClient(app).get(f"/ledger/responses/{turn_id}", headers=intruder)
    missing = TestClient(app).get(f"/ledger/responses/turn-{uuid4()}", headers=intruder)

    assert own.status_code == 200 and own.json()["recorded"] is True and own.json()["record"]["seq"] is None
    assert (theirs.status_code, theirs.json()) == (missing.status_code, missing.json()) == (404, {"detail": "Response not found."})
    with SessionLocal() as db:
        shadow_id = db.scalar(select(ResponseLedgerRecord.response_id).where(ResponseLedgerRecord.shadowed_response_id == turn_id))
    assert shadow_id is not None and shadow_id.startswith("shadow-")
    shadow = TestClient(app).get(f"/ledger/responses/{shadow_id}", headers=owner)
    assert (shadow.status_code, shadow.json()) == (404, {"detail": "Response not found."})


def test_another_learners_turn_cannot_be_flagged():
    # Phase 6 (AC-6-6's intake): a learner flags only their own tutor turn; another learner's turn and a missing one get
    # the same 404, and neither records a flag.
    from app.db_models import V3Flag

    owner, intruder = _demo("learner"), _demo("learner")
    chat = TestClient(app).post("/assistant/chat", json={"message": "Why does routing depth matter?"}, headers={**owner, **_source()})
    assert chat.status_code == 200
    turn_id = chat.json()["turn_id"]
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(V3Flag))
    theirs = TestClient(app).post("/v3/flags", json={"response_id": turn_id}, headers={**intruder, **_source()})
    missing = TestClient(app).post("/v3/flags", json={"response_id": f"turn-{uuid4()}"}, headers={**intruder, **_source()})
    assert (theirs.status_code, theirs.json()) == (missing.status_code, missing.json()) == (404, {"detail": "Not Found"})
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(V3Flag)) == before
    own = TestClient(app).post("/v3/flags", json={"response_id": turn_id}, headers={**owner, **_source()})
    assert own.status_code == 200 and own.json()["f_i"] == 0.0


def _submission_for(headers: dict[str, str], title: str) -> int:
    response = TestClient(app).post(
        "/projects/submissions",
        json={
            "project_slug": PROJECT_SLUG,
            "title": title,
            "solution_summary": "A routing plan that limits two-qubit depth by shrinking the graph before mapping it.",
            "implementation_notes": "Shrink, map, then verify depth against the hardware coupling map.",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_another_learners_submission_cannot_be_retracted():
    owner, intruder = _demo("learner"), _demo("learner")
    submission_id = _submission_for(owner, "Owner's submission")

    attempt = TestClient(app).delete(f"/projects/submissions/{submission_id}", headers=intruder)
    missing = TestClient(app).delete("/projects/submissions/999999999", headers=intruder)

    assert (attempt.status_code, attempt.json()) == (missing.status_code, missing.json()) == (404, {"detail": "Submission not found."})
    with SessionLocal() as db:
        assert db.get(ProjectSubmission, submission_id).is_deleted is False


def test_peer_review_refuses_the_owner_and_answers_missing_and_retracted_alike():
    owner, reviewer = _demo("learner"), _demo("learner")
    submission_id = _submission_for(owner, "Submission to review")
    retracted_id = _submission_for(owner, "Submission to retract")
    assert TestClient(app).delete(f"/projects/submissions/{retracted_id}", headers=owner).status_code == 200
    review = {"rubric_scores": {"clarity": 4}, "feedback": "Clear plan; show the depth numbers before and after."}

    own = TestClient(app).post("/projects/reviews", json={**review, "submission_id": submission_id}, headers=owner)
    retracted = TestClient(app).post("/projects/reviews", json={**review, "submission_id": retracted_id}, headers=reviewer)
    missing = TestClient(app).post("/projects/reviews", json={**review, "submission_id": 999999999}, headers=reviewer)
    accepted = TestClient(app).post("/projects/reviews", json={**review, "submission_id": submission_id}, headers=reviewer)

    assert own.status_code == 400
    assert (retracted.status_code, retracted.json()) == (missing.status_code, missing.json()) == (404, {"detail": "Submission not found."})
    assert accepted.status_code == 200


# --- Caller scope: no caller-scoped read returns another learner's data ---

CALLER_READS = [
    path
    for (method, path), policy in POLICED
    if method == "GET" and policy.ownership == authz.CALLER and policy.access in {authz.PRINCIPAL, authz.DURABLE_LEARNER}
]
# Reads where the owner's own response must show the marker, so the check above is not vacuous.
MARKER_EXPECTED = {
    "/content/lessons/{lesson_slug}/notes",
    "/content/progress",
    "/assistant/threads",
    "/insights/profile",
    "/projects/my-submissions",
    "/learner-record",
}


def _local_account() -> tuple[TestClient, dict[str, str]]:
    browser = TestClient(app)
    response = browser.post(
        "/auth/register", json={"email": f"authz-{uuid4().hex[:8]}@example.com", "password": PASSWORD}, headers=_source()
    )
    assert response.status_code == 201
    return browser, {"origin": TRUSTED_ORIGIN, "x-qcai-csrf": browser.cookies.get("qcai_auth_csrf")}


def _write_everything(browser: TestClient, headers: dict[str, str], marker: str) -> None:
    writes = [
        ("POST", f"/content/lessons/{LESSON_SLUG}/notes", {"body": f"Note {marker}"}),
        ("POST", "/assistant/threads", {"title": f"Thread {marker}"}),
        # target_role must be a known role, so the marker goes in the free-text focus area.
        ("PUT", "/insights/profile", {"target_role": "Quantum ML Engineer", "focus_area": f"Focus {marker}"}),
        ("POST", "/insights/check-ins", {"motivation_level": 3, "focus_level": 3, "energy_level": 3, "today_goal": f"Goal {marker}"}),
        ("POST", "/analytics/events", {"event_type": "lesson_viewed", "lesson_slug": LESSON_SLUG, "payload": {"marker": marker}}),
        ("POST", "/qa/ask", {"question": f"What does {marker} mean for routing depth?", "lesson_slug": LESSON_SLUG}),
        (
            "POST",
            "/learner-record/operations",
            {
                "operations": [
                    {
                        "operation_id": f"op-{uuid4().hex[:12]}",
                        "replica_id": f"replica-{uuid4().hex[:8]}",
                        "logical_counter": 1,
                        "operation_type": "set_cursor",
                        "payload": {"value": f"cursor {marker}"},
                    }
                ]
            },
        ),
    ]
    for method, path, body in writes:
        response = browser.request(method, path, json=body, headers={**headers, **_source()})
        assert response.status_code in {200, 201}, (path, response.status_code, response.text)
    response = browser.post(
        "/projects/submissions",
        json={
            "project_slug": PROJECT_SLUG,
            "title": f"Submission {marker}",
            "solution_summary": "A routing plan that limits two-qubit depth by shrinking the graph before mapping it.",
            "implementation_notes": "Shrink, map, then verify depth against the hardware coupling map.",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text


def test_no_caller_scoped_read_returns_another_learners_data():
    owner, owner_headers = _local_account()
    other, other_headers = _local_account()
    marker = f"marker{uuid4().hex[:10]}"
    _write_everything(owner, owner_headers, marker)

    shown_to_owner = set()
    for path in CALLER_READS:
        url = _concrete(path)
        theirs = other.get(url, headers=other_headers)
        assert theirs.status_code == 200, (path, theirs.status_code)
        assert marker not in theirs.text, path
        if marker in owner.get(url, headers=owner_headers).text:
            shown_to_owner.add(path)

    assert MARKER_EXPECTED <= shown_to_owner, MARKER_EXPECTED - shown_to_owner


# --- Server-side quiz scoring (E-110) ---


def _quiz_questions():
    # The answer keys are server-side only (Phase 4, R-42): the public lesson carries no key.
    return get_course_store().quiz_keys.for_lesson(LESSON_SLUG)


def test_a_client_sent_score_is_ignored():
    headers = _demo("learner")
    questions = _quiz_questions()

    response = TestClient(app).post(
        "/content/quiz-attempts",
        json={"lesson_slug": LESSON_SLUG, "score": 999, "responses": {question.id: "wrong answer" for question in questions}},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["score"] == 0
    with SessionLocal() as db:
        assert db.get(QuizAttempt, response.json()["attempt_id"]).score == 0


def test_the_server_scores_responses_against_the_answer_key():
    questions = _quiz_questions()
    assert questions, "the fixture lesson needs quiz questions"
    responses = {question.id: question.answer for question in questions}
    responses[questions[0].id] = "wrong answer"
    responses["not-a-question"] = "ignored"
    responses[questions[-1].id] = questions[-1].answer if len(questions) > 1 else "x" * 5000

    response = TestClient(app).post(
        "/content/quiz-attempts", json={"lesson_slug": LESSON_SLUG, "responses": responses}, headers=_demo("learner")
    )

    assert response.status_code == 200
    assert response.json()["score"] == len(questions) - 1
    with SessionLocal() as db:
        stored = db.get(QuizAttempt, response.json()["attempt_id"]).responses
    assert set(stored) == {question.id for question in questions}
    assert all(len(value) <= 2000 for value in stored.values())


def test_a_quiz_attempt_for_an_unknown_lesson_is_refused():
    headers = _demo("learner")
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(QuizAttempt))

    response = TestClient(app).post(
        "/content/quiz-attempts", json={"lesson_slug": "no-such-lesson", "responses": {}}, headers=headers
    )

    assert response.status_code == 404
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(QuizAttempt)) == before


def test_durable_mastery_follows_the_server_score():
    browser, headers = _local_account()
    questions = _quiz_questions()

    response = browser.post(
        "/content/quiz-attempts",
        json={"lesson_slug": LESSON_SLUG, "score": len(questions), "responses": {}},
        headers=headers,
    )
    record = browser.get("/learner-record", headers=headers)

    assert response.status_code == 200 and response.json()["score"] == 0
    assert record.status_code == 200
    assert record.json()["mastery"][f"lesson:{LESSON_SLUG}"] == 0.0
    assert f"lesson:{LESSON_SLUG}" not in record.json()["completed_item_ids"]
