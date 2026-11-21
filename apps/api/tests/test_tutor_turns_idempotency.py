"""Phase 3: POST /tutor/turns honours an Idempotency-Key, scoped to its caller (DI-40; spec 7.13).

C9  a retried POST with the same key returns the first turn and creates no second; a key is scoped to its caller and a
    changed body is refused; a malformed key is refused before anything is written; concurrent requests with one key
    create one turn; a key expires after the package TTL and erasure deletes its record.
The in-progress lease is in test_tutor_turns_idempotency_lease.py. Each test fails if its defect comes back; the spec's
review history (18.4) names the round behind each group.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import threading
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from app.api.routes import tutor as tutor_route
from app.core.config import Settings
from app.core.config_package import get_config_package
from app.core.db import SessionLocal
from app.core.db import engine as session_engine
from app.db_models import ResponseLedgerRecord, TutorTurn, TutorTurnIdempotency
from app.main import app
from app.services import turn_idempotency
from app.services.erasure import erase_user, user_keyed_tables
from app.services.tutor_pipeline.contracts import sha256_hex


PACKAGE = get_config_package(Settings())
PARAMS = PACKAGE.tutor_pipeline
IN_DOMAIN = "Why does routing depth matter?"
client = TestClient(app)
PRODUCTION = {"environment": "production", "allowed_origins": ["https://qantumlearn.academy"],
              "guest_token_secret": "a-production-like-secret-of-sufficient-length"}


def demo(prefix: str, role: str = "learner") -> dict[str, str]:
    return {"x-demo-user": f"{prefix}-{uuid4().hex[:12]}", "x-demo-role": role, "x-forwarded-for": f"hardening-{uuid4().hex}"}


def fresh(headers: dict[str, str]) -> dict[str, str]:
    # A distinct client address per request keeps the per-address limits apart.
    return {**headers, "x-forwarded-for": f"hardening-{uuid4().hex}"}


def records(**where) -> list[ResponseLedgerRecord]:
    with SessionLocal() as db:
        query = select(ResponseLedgerRecord).order_by(ResponseLedgerRecord.seq)
        for column, value in where.items():
            query = query.where(getattr(ResponseLedgerRecord, column) == value)
        return list(db.scalars(query))


# =============================================================================================================== C9


TURN = {"message": IN_DOMAIN}


def _turn(headers: dict[str, str], body: dict, key: str | None = None, browser: TestClient = client):
    extra = {"Idempotency-Key": key} if key is not None else {}
    return browser.post("/tutor/turns", headers={**fresh(headers), **extra}, json=body)


def _turns_of(user_id: str) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(TutorTurn).where(TutorTurn.user_id == user_id)) or 0


def _key_rows(user_id: str) -> list[TutorTurnIdempotency]:
    with SessionLocal() as db:
        return list(db.scalars(select(TutorTurnIdempotency).where(TutorTurnIdempotency.user_id == user_id)))


def test_c9_a_retried_post_with_the_same_key_returns_the_first_turn_and_creates_no_second():
    headers = demo("idem")
    user_id = headers["x-demo-user"]
    key = f"retry-{uuid4().hex}"
    first = _turn(headers, TURN, key)
    again = _turn(headers, TURN, key)
    assert first.status_code == again.status_code == 200
    assert again.json() == first.json() and again.headers["idempotent-replayed"] == "true" and "idempotent-replayed" not in first.headers
    assert again.headers["x-assistant-model"] == first.headers["x-assistant-model"]
    assert _turns_of(user_id) == 1 and len(records(response_id=first.json()["turn_id"])) == 1
    (row,) = _key_rows(user_id)
    assert row.key_sha256 == sha256_hex(key) and key not in json.dumps([row.key_sha256, row.request_sha256, row.response_body])
    # Without a key every POST is a new turn, as before.
    assert _turn(headers, TURN).json()["turn_id"] != first.json()["turn_id"] and _turns_of(user_id) == 2


def test_c9_a_key_is_scoped_to_its_caller_and_a_changed_body_is_refused():
    learner, other = demo("idem-scope"), demo("idem-scope-other")
    key = f"shared-{uuid4().hex}"
    mine = _turn(learner, TURN, key)
    theirs = _turn(other, TURN, key)
    assert mine.status_code == theirs.status_code == 200 and mine.json()["turn_id"] != theirs.json()["turn_id"]
    assert "idempotent-replayed" not in theirs.headers and _turns_of(other["x-demo-user"]) == 1
    changed = _turn(learner, {"message": "What is QUBO optimization in logistics?"}, key)
    assert (changed.status_code, changed.json()) == (422, {"detail": "This Idempotency-Key was already used with a different request."})
    assert _turn(learner, {**TURN, "presentation_plan": "socratic"}, key).status_code == 422
    assert _turns_of(learner["x-demo-user"]) == 1


@pytest.mark.parametrize("key", ["short", "x" * 129, "has space inside", "slash/inside-key", "semi;colon-key", ""])
def test_c9_a_malformed_or_oversized_key_is_refused_before_anything_is_written(key):
    headers = demo("idem-bad")
    response = _turn(headers, TURN, key)
    assert response.status_code == 422 and _turns_of(headers["x-demo-user"]) == 0 and _key_rows(headers["x-demo-user"]) == []


def test_c9_a_disabled_route_answers_404_whatever_the_key(monkeypatch):
    production = Settings(**PRODUCTION)
    monkeypatch.setattr(tutor_route, "get_settings", lambda: production)
    for key in ("x" * 300, f"valid-{uuid4().hex}"):
        response = _turn(demo("idem-off"), TURN, key)
        assert (response.status_code, response.json()) == (404, {"detail": "Not Found"})


def test_c9_a_retry_while_the_first_still_runs_gets_409_and_a_failed_turn_releases_its_key():
    headers = demo("idem-409")
    user_id = headers["x-demo-user"]
    key = f"running-{uuid4().hex}"
    digest = turn_idempotency.request_sha256(message=IN_DOMAIN, thread_id=None, lesson_slug=None, presentation_plan=None)
    with SessionLocal() as db:
        db.add(TutorTurnIdempotency(user_id=user_id, key_sha256=sha256_hex(key), request_sha256=digest, created_at=datetime.now(UTC)))
        db.commit()
    running = _turn(headers, TURN, key)
    assert running.status_code == 409 and _turns_of(user_id) == 0
    # A turn that fails (a thread the caller does not own) releases its claim, so the key can be used again.
    owner = demo("idem-409-owner")
    thread_id = client.post("/assistant/threads", headers=fresh(owner), json={"title": "not yours"}).json()["id"]
    failed_key = f"failing-{uuid4().hex}"
    assert _turn(headers, {**TURN, "thread_id": thread_id}, failed_key).status_code == 404
    assert [row.key_sha256 for row in _key_rows(user_id)] == [sha256_hex(key)]


def test_c9_concurrent_requests_with_one_key_create_one_turn():
    headers = demo("idem-race")
    user_id = headers["x-demo-user"]
    key = f"race-{uuid4().hex}"
    results: list = []
    if session_engine.dialect.name == "postgresql":
        barrier = threading.Barrier(3)

        def worker():
            browser = TestClient(app)  # one client per thread
            barrier.wait()
            results.append(_turn(headers, TURN, key, browser))

        workers = [threading.Thread(target=worker) for _ in range(3)]
        for thread in workers:
            thread.start()
        for thread in workers:
            thread.join(60)
    else:  # in-memory SQLite shares one connection across threads (StaticPool, spec M17): one after the other
        results.extend(_turn(headers, TURN, key) for _ in range(3))
    statuses = sorted(response.status_code for response in results)
    assert len(results) == 3 and set(statuses) <= {200, 409} and 200 in statuses
    assert _turns_of(user_id) == 1
    turn_ids = {response.json()["turn_id"] for response in results if response.status_code == 200}
    assert len(turn_ids) == 1


def test_c9_a_key_expires_after_the_package_ttl_and_erasure_deletes_its_record():
    headers = demo("idem-expiry")
    user_id = headers["x-demo-user"]
    key = f"expired-{uuid4().hex}"
    expired_at = datetime.now(UTC) - timedelta(hours=PARAMS.idempotency_ttl_hours, minutes=5)
    digest = turn_idempotency.request_sha256(message=IN_DOMAIN, thread_id=None, lesson_slug=None, presentation_plan=None)
    with SessionLocal() as db:
        db.add(TutorTurnIdempotency(user_id=user_id, key_sha256=sha256_hex(key), request_sha256=digest, turn_id=f"turn-{uuid4()}",
                                    response_body="{}", created_at=expired_at))
        db.commit()
    renewed = _turn(headers, TURN, key)
    assert renewed.status_code == 200 and "idempotent-replayed" not in renewed.headers and _turns_of(user_id) == 1
    assert [row.turn_id for row in _key_rows(user_id)] == [renewed.json()["turn_id"]]
    # User-keyed: erasure deletes it, and guest retention covers it (test_erasure_retention walks every such table).
    assert "tutor_turn_idempotency" in {table.name for table in user_keyed_tables()}
    with SessionLocal() as db:
        erase_user(db, user_id)
        db.commit()
    assert _key_rows(user_id) == []
