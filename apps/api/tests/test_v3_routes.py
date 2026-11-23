"""Phase 6 V3 routes (Phase 6 spec section 9, 13.2): each route's 200 shape on seeded items, 404 when V3 is off or an id
is malformed, the 409 and 422 reasons, one security event per call, the flag route's ownership, 409, rate limit and
404 outside development, and Cache-Control: no-store. The queue routes read a fresh database (get_db overridden);
security events go to the shared database and are read in seq order."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.core.config_package import get_config_package
from app.core.db import SessionLocal, get_db
from app.db_models import SecurityEvent
from app.main import app
from app.services import security_log
import v3_fakes

PACKAGE = get_config_package(Settings())
client = TestClient(app)


@contextmanager
def fresh_routes(n: int = 2, *, double_review: bool = False, settings: Settings | None = None):
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        entries = v3_fakes.reviewable_deliveries(n)
        ids = v3_fakes.seed_items(factory, entries, package=PACKAGE, now=datetime.now(UTC), double_review=double_review)

        def override():
            db = factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override
        if settings is not None:
            app.dependency_overrides[get_settings] = lambda: settings
        try:
            yield factory, ids, entries
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_settings, None)


def _events_since(start: int, name: str) -> list:
    with SessionLocal() as db:
        return db.scalars(select(SecurityEvent).where(SecurityEvent.seq > start, SecurityEvent.event_type == name).order_by(SecurityEvent.seq)).all()


def _head() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.max(SecurityEvent.seq))) or 0


def _labels(entry, key: str) -> dict:
    return {"client_key": key, "claim_labels": [{"claim_id": claim.claim_id, "verdict": "SUPPORTED", "ehmf_type": None}
                                                for claim in sorted(entry.claims, key=lambda claim: claim.claim_id)]}


def test_the_reviewer_routes_shape_and_their_security_events():
    reviewer, second = v3_fakes.reviewer("a"), v3_fakes.reviewer("b")
    with fresh_routes(2) as (factory, ids, entries):
        start = _head()
        queue = client.get("/v3/queue", headers=reviewer)
        assert queue.status_code == 200 and queue.headers["cache-control"] == "no-store"
        body = queue.json()
        assert body["order"] == ["priority desc", "enqueued_at", "item_id"] and sorted(item["item_id"] for item in body["items"]) == sorted(ids)
        item = client.get(f"/v3/items/{ids[0]}", headers=reviewer).json()
        assert item["state"] == "queued" and item["reviewable"] is True and item["final_gold_seq"] is None
        claimed = client.post(f"/v3/items/{ids[0]}/claim", headers=reviewer)
        assert claimed.status_code == 200 and claimed.json()["state"] == "claimed" and claimed.json()["review_round"] == 1
        assert client.post(f"/v3/items/{ids[0]}/claim", headers=second).json() == {"detail": "claimed_by_another"}
        adjudicated = client.post(f"/v3/items/{ids[0]}/adjudicate", headers=reviewer, json=_labels(entries[0], "route-key-01"))
        result = adjudicated.json()
        assert adjudicated.status_code == 200 and result["state"] == "adjudicated" and result["duplicate"] is False and len(result["record_hash"]) == 64
        again = client.post(f"/v3/items/{ids[0]}/adjudicate", headers=reviewer, json=_labels(entries[0], "route-key-01")).json()
        assert again["duplicate"] is True and again["gold_seq"] == result["gold_seq"]
        assert client.post(f"/v3/items/{ids[0]}/apply", headers=reviewer, json={"client_key": "apply-key-01"}).json() == {
            "detail": "adjudicator_cannot_apply"}
        applied = client.post(f"/v3/items/{ids[0]}/apply", headers=second, json={"client_key": "apply-key-01"})
        assert applied.json() == {"item_id": ids[0], "state": "applied", "final_gold_seq": result["gold_seq"], "duplicate": False}
        repeat = client.post(f"/v3/items/{ids[0]}/apply", headers=second, json={"client_key": "apply-key-01"})
        assert repeat.json() == {"item_id": ids[0], "state": "applied", "final_gold_seq": result["gold_seq"], "duplicate": True}
        assert [event.details["duplicate"] for event in _events_since(start, "v3.item_applied")] == [False, True]
        metrics = client.get("/v3/metrics", headers=reviewer).json()
        assert metrics["gold"]["rows"] == 1 and metrics["escalation_share"]["counted"] == ["X1", "X2", "X3", "X4"]
        for name in ("v3.queue_read", "v3.item_read", "v3.item_claimed", "v3.item_adjudicated", "v3.item_applied", "v3.metrics_read"):
            events = _events_since(start, name)
            assert events and all(event.details["route"].startswith("/v3/") and event.actor_role == "reviewer" for event in events), name
        assert _events_since(start, "v3.queue_read")[0].details["count"] == 2


def test_a_locked_database_is_retried_and_a_lock_that_outlasts_the_retries_answers_503(monkeypatch):
    # SQLite (development) refuses a writer with "database is locked" when two deferred transactions both write: a claim
    # retries the whole transaction, and a lock that outlasts the attempts answers 503, never 500.
    import sqlite3

    from sqlalchemy.exc import OperationalError

    from app.services.v3 import queue as queue_module

    reviewer = v3_fakes.reviewer("a")
    locked = OperationalError("INSERT INTO v3_claims", {}, sqlite3.OperationalError("database is locked"))
    with fresh_routes(2) as (_factory, ids, _entries):
        real, calls = queue_module._item, []

        def flaky(db, item_id, lock=False):
            calls.append(item_id)
            if len(calls) == 1:
                raise locked
            return real(db, item_id, lock=lock)

        monkeypatch.setattr(queue_module, "_item", flaky)
        claimed = client.post(f"/v3/items/{ids[0]}/claim", headers=reviewer)
        assert claimed.status_code == 200 and claimed.json()["state"] == "claimed" and len(calls) == 2
        monkeypatch.setattr(queue_module, "_item", lambda db, item_id, lock=False: (_ for _ in ()).throw(locked))
        start = _head()
        busy = client.post(f"/v3/items/{ids[1]}/claim", headers=reviewer)
        assert (busy.status_code, busy.json(), busy.headers["retry-after"], busy.headers["cache-control"]) == (503, {"detail": "busy"}, "1", "no-store")
        assert _events_since(start, "v3.item_claimed") == []


def test_an_unreviewable_item_cannot_be_claimed_or_adjudicated(monkeypatch):
    from app.api.routes import v3 as routes
    from app.core.corpus_governance import get_corpus_registry
    from app.services.content_assembler import CourseStore

    governed = Settings(environment="production", enforce_corpus_governance=True, allowed_origins=["https://qantumlearn.academy"])
    store, registry = CourseStore(governed), get_corpus_registry(governed)   # D-31: no asset approved, nothing quotable
    with fresh_routes(1) as (factory, ids, entries):
        monkeypatch.setattr(routes, "_sources", lambda settings: (store, registry))
        reviewer = v3_fakes.reviewer("a")
        view = client.get(f"/v3/items/{ids[0]}", headers=reviewer).json()
        assert view["reviewable"] is False and all(claim["text"] is None for claim in view["claims"])
        claim = client.post(f"/v3/items/{ids[0]}/claim", headers=reviewer)
        assert (claim.status_code, claim.json()) == (409, {"detail": "not_reviewable"})
        adjudicate = client.post(f"/v3/items/{ids[0]}/adjudicate", headers=reviewer, json=_labels(entries[0], "route-key-02"))
        assert (adjudicate.status_code, adjudicate.json()) == (409, {"detail": "not_claimed"})
        from app.services.v3 import queue

        with factory() as db:
            # Even with a lease taken before the store changed, adjudication refuses a hidden claim.
            from sqlalchemy import insert

            from app.db_models import V3Claim

            db.execute(insert(V3Claim).values(item_id=ids[0], review_round=1, user_id="synthetic-a", claimed_at=datetime.now(UTC),
                                              lease_expires_at=datetime(2999, 1, 1, tzinfo=UTC), adjudicated_at=None))
            db.commit()
            assert queue.get_item(db, ids[0]).state == "queued"
        refused = client.post(f"/v3/items/{ids[0]}/adjudicate", headers=reviewer, json=_labels(entries[0], "route-key-03"))
        assert (refused.status_code, refused.json()) == (409, {"detail": "not_reviewable"})


def test_conflicts_and_malformed_ids_and_labels():
    reviewer = v3_fakes.reviewer("a")
    with fresh_routes(1) as (factory, ids, entries):
        assert client.get("/v3/items/not-an-item", headers=reviewer).status_code == 404
        assert client.get(f"/v3/items/v3i-{'0' * 24}", headers=reviewer).status_code == 404
        assert client.post(f"/v3/items/v3i-{'0' * 24}/claim", headers=reviewer).status_code == 404
        assert client.post(f"/v3/items/{ids[0]}/adjudicate", headers=reviewer, json=_labels(entries[0], "route-key-04")).json() == {"detail": "not_claimed"}
        client.post(f"/v3/items/{ids[0]}/claim", headers=reviewer)
        mismatch = client.post(f"/v3/items/{ids[0]}/adjudicate", headers=reviewer, json={"client_key": "route-key-05", "claim_labels": []})
        assert (mismatch.status_code, mismatch.json()) == (422, {"detail": "labels_do_not_match_subject"})
        assert client.post(f"/v3/items/{ids[0]}/adjudicate", headers=reviewer, json={"client_key": "short"}).status_code == 422
        assert client.post(f"/v3/items/{ids[0]}/apply", headers=reviewer, json={"client_key": "apply-key-02"}).json() == {"detail": "not_adjudicated"}
        assert client.get("/v3/queue?state=elsewhere", headers=reviewer).status_code == 422
        assert client.get("/v3/queue?limit=101", headers=reviewer).status_code == 422


def test_every_v3_route_answers_404_while_v3_is_off():
    off = Settings(environment="development", v3_queue="off")
    reviewer = v3_fakes.reviewer("a")
    with fresh_routes(1, settings=off) as (factory, ids, entries):
        for method, path, body in (("GET", "/v3/queue", None), ("POST", "/v3/scan", None), ("GET", f"/v3/items/{ids[0]}", None),
                                   ("POST", f"/v3/items/{ids[0]}/claim", None), ("POST", f"/v3/items/{ids[0]}/adjudicate", _labels(entries[0], "route-key-06")),
                                   ("POST", f"/v3/items/{ids[0]}/apply", {"client_key": "apply-key-03"}), ("GET", "/v3/metrics", None)):
            response = client.request(method, path, headers=reviewer, json=body)
            assert (response.status_code, response.headers.get("cache-control")) == (404, "no-store"), path
        learner = {"x-demo-user": f"flag-{uuid4().hex[:8]}", "x-demo-role": "learner"}
        assert client.post("/v3/flags", headers=learner, json={"response_id": f"turn-{uuid4()}"}).status_code == 404


@pytest.mark.parametrize("setting", ["off", "shadow"])
def test_outside_development_a_caller_without_a_credential_gets_401_and_no_security_event(setting, monkeypatch):
    # Demo auth is off outside development (its default), so authentication refuses an anonymous caller before any role
    # or pool check: every V3 route, the flag route included, answers 401 "Authentication required." and records no
    # security event of any kind (the runbook's unauthenticated check reads 401, not 403).
    from app import main as main_module
    from app.core import authorization as authz

    staging = v3_fakes.staging_settings(v3_queue=setting, enable_demo_auth=False)
    monkeypatch.setattr(main_module, "settings", staging)          # the CSRF and origin guard reads the process settings
    app.dependency_overrides[get_settings] = lambda: staging
    try:
        routes = [(method, path) for (method, path) in authz.ROUTE_POLICIES if path.startswith("/v3/")]
        assert len(routes) == 8
        anonymous = TestClient(app)
        for method, path in routes:
            body = {"response_id": f"turn-{uuid4()}"} if path == "/v3/flags" else ({} if method == "POST" else None)
            start = _head()
            response = anonymous.request(method, path.replace("{item_id}", "v3i-" + "0" * 24), json=body)
            assert (response.status_code, response.json()) == (401, {"detail": "Authentication required."}), path
            assert _head() == start, path
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_the_scan_route_scans_and_is_a_security_event():
    start = _head()
    response = client.post("/v3/scan", headers=v3_fakes.reviewer("a"))
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert set(response.json()) == {"from_seq", "to_seq", "records", "deliveries", "drawn_x6", "drawn_x5", "items_created", "items_updated",
                                    "model_changes", "unparsed", "done"}
    (event,) = _events_since(start, "v3.scan_run")
    assert event.details["records"] == response.json()["records"]


def test_the_flag_route_flags_the_callers_own_turn_once_and_says_when_its_record_is_not_written_yet(monkeypatch):
    learner = {"x-demo-user": f"flag-{uuid4().hex[:8]}", "x-demo-role": "learner", "x-forwarded-for": f"203.0.113.{uuid4().int % 250 + 1}"}
    chat = client.post("/assistant/chat", json={"message": "Why does routing depth matter?"}, headers=learner)
    turn_id = chat.json()["turn_id"]
    first = client.post("/v3/flags", headers=learner, json={"response_id": turn_id})
    again = client.post("/v3/flags", headers=learner, json={"response_id": turn_id})
    assert first.json() == {"status": "recorded", "f_i": 0.0, "duplicate": False} and again.json()["duplicate"] is True
    assert first.headers["cache-control"] == "no-store"
    assert client.post("/v3/flags", headers=learner, json={"response_id": "shadow-" + turn_id[5:]}).status_code == 422
    # A turn that expects a record that is not written yet is 409; one an earlier image made is 404 (not auditable).
    from app.db_models import TutorTurn

    with SessionLocal() as db:
        source = db.get(TutorTurn, turn_id)
        for expected in (True, None):
            pending = TutorTurn(id=f"turn-{uuid4()}", thread_id=source.thread_id, user_id=source.user_id, resolved_query="q",
                                retrieval_mode="lexical", provider="p", model="m", decision="answer", decision_reason="r", citations=[], claims=[],
                                corpus_version="c", policy_version="p", ledger_record_expected=expected)
            db.add(pending)
            db.commit()
            response = client.post("/v3/flags", headers=learner, json={"response_id": pending.id})
            assert response.status_code == (409 if expected else 404), expected
            if expected:
                assert response.json() == {"detail": "not_recorded_yet"}


def test_the_flag_route_is_rate_limited(monkeypatch):
    monkeypatch.setattr(get_settings(), "v3_flag_rate_limit", "2/minute")
    learner = {"x-demo-user": f"flag-{uuid4().hex[:8]}", "x-demo-role": "learner", "x-forwarded-for": f"198.51.100.{uuid4().int % 250 + 1}"}
    codes = [client.post("/v3/flags", headers=learner, json={"response_id": f"turn-{uuid4()}"}).status_code for _ in range(3)]
    assert codes == [404, 404, 429]


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_the_flag_route_is_404_outside_development_whatever_v3_queue_says(environment):
    from app.api.routes.v3 import flag_intake_open

    for queue_setting in ("off", "shadow"):
        settings = Settings(environment=environment, v3_queue=queue_setting, guest_token_secret="g" * 32, allowed_origins=["https://example.test"])
        assert flag_intake_open(settings) is False
    assert flag_intake_open(Settings(environment="development", v3_queue="shadow")) is True
    assert flag_intake_open(Settings(environment="development", v3_queue="off")) is False
