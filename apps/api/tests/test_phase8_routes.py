"""Phase 8 HTTP contracts across feature flags and the privacy lifecycle."""

from datetime import UTC, datetime, timedelta
import json
import secrets
import time
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, func, select

from app.core.config import get_settings
from app.core.config_package import canonical_sha256
from app.core.db import SessionLocal
from app.core.guest_tokens import GUEST_TOKEN_COOKIE, guest_csrf_for, issue_guest_token
from app.db_models import (
    AnalyticsEvent, GuestLegacyUpgrade, GuestRevocation, LearnerAssessmentFact, LearnerErasureAudit, LearnerRecord,
    LearnerRecordOperation, Note, QuizAttempt, SecurityEvent, SupportRequest,
)
from app.main import app
from app.services.erasure import user_keyed_tables
from app.services.guest_sessions import upgrade_legacy_guest
from app.services.learner_record_identity import bind_subject
from app.services.store import get_course_store
from scripts.prove_erasure import independently_remaining


ORIGIN = "http://localhost:3000"
LESSON = "nisq-reality-overview"
PASSWORD = "fixture-only-" + uuid4().hex


def account():
    browser = TestClient(app, client=(f"2001:db8::{secrets.randbits(16):x}:{secrets.randbits(16):x}", 50000))
    address = f"{uuid4().hex}@example.invalid"
    result = browser.post("/auth/register", json={"email": address, "password": PASSWORD}, headers={"origin": ORIGIN})
    assert result.status_code == 201
    return browser, {"origin": ORIGIN, "x-qcai-csrf": browser.cookies.get("qcai_auth_csrf")}, result.json()["user"]["user_id"], address


def batch(replica, clock, item, version=None):
    operation = {"operation_id": f"fixture-{uuid4().hex}", "replica_id": replica, "logical_counter": clock,
                 "operation_type": "complete_item", "payload": {"item_id": item}}
    return {"operations": [operation], **({"expected_record_version": version} if version is not None else {})}


def quiz(browser, headers):
    responses = {question.id: question.answer for question in get_course_store().quiz_keys.for_lesson(LESSON)}
    assert responses
    return browser.post("/content/quiz-attempts", json={"lesson_slug": LESSON, "responses": responses, "score": 999},
                        headers=headers)


def test_freeze_phase8_flags_off_learner_record_and_quiz_routes_are_unchanged(monkeypatch):
    settings = get_settings()
    for field in ("learner_identity", "learner_privacy", "learner_sync"):
        monkeypatch.setattr(settings, field, "off")
    browser, headers, principal, _ = account()
    assert browser.post("/learner-record/replicas", headers=headers).status_code == 404
    assert browser.post("/auth/guest-claim", headers=headers).status_code == 404
    assert browser.get("/auth/learner-consent").status_code == 404
    assert browser.put("/auth/learner-consent", headers=headers, json={}).status_code == 404
    assert browser.get("/auth/learner-export").status_code == 404
    assert browser.post("/auth/learner-erasure", headers=headers, json={}).status_code == 404
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())
    engine = SessionLocal.kw["bind"]
    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert browser.get("/learner-record").json()["record_version"] == 0
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert any("insert into learner_records" in statement for statement in statements)
    assert browser.post("/learner-record/operations", headers=headers,
                        json=batch(f"browser-{uuid4().hex}", 1, "fixture")).status_code == 200
    for _ in range(13):
        result = quiz(browser, headers)
        assert result.status_code == 200
    attempt_id = result.json()["attempt_id"]
    with SessionLocal() as db:
        assert db.scalar(select(LearnerRecordOperation.operation_id).where(
            LearnerRecordOperation.user_id == principal, LearnerRecordOperation.operation_id == f"quiz-{attempt_id}-mastery",
        ))
        assert db.get(LearnerAssessmentFact, attempt_id) is None


def test_phase8_first_binding_preserves_the_read_version_and_existing_replica(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "learner_identity", "off")
    browser, headers, _, _ = account()
    issued = browser.post("/learner-record/replicas", headers=headers)
    assert issued.status_code == 201
    replica = issued.json()["replica_id"]
    assert browser.post("/learner-record/operations", headers=headers, json=batch(replica, 1, "before", 0)).status_code == 200
    monkeypatch.setattr(settings, "learner_identity", "on")
    version = browser.get("/learner-record").json()["record_version"]
    response = browser.post("/learner-record/operations", headers=headers, json=batch(replica, 2, "after", version))
    assert response.status_code == 200, response.text
    assert response.json()["record"]["record_version"] == version + 1
    assert response.json()["record"]["completed_item_ids"] == ["after", "before"]


def test_phase8_existing_subject_survives_identity_and_sync_rollback(monkeypatch):
    settings = get_settings()
    browser, headers, principal, _ = account()
    for phase, identity in enumerate(("on", "off", "on")):
        monkeypatch.setattr(settings, "learner_identity", identity)
        assert quiz(browser, headers).status_code == 200
        issued = browser.post("/learner-record/replicas", headers=headers)
        assert issued.status_code == 201
        version = browser.get("/learner-record").json()["record_version"]
        response = browser.post("/learner-record/operations", headers=headers,
                                json=batch(issued.json()["replica_id"], 1, f"local-{phase}", version))
        assert response.status_code == 200, response.text
    record = browser.get("/learner-record").json()
    assert record["completed_item_ids"] == sorted([f"lesson:{LESSON}", "local-0", "local-1", "local-2"])
    assert record["attempt_counts"][f"lesson:{LESSON}"] == 3
    with SessionLocal() as db:
        assert db.get(LearnerRecord, principal) is None


def test_phase8_claim_http_requires_origin_and_preserves_record_with_sync_off(monkeypatch):
    settings = get_settings()
    for field in ("learner_sync", "learner_identity"):
        monkeypatch.setattr(settings, field, "off" if field == "learner_sync" else "on")
    browser, headers, principal, _ = account()
    guest = f"guest-{uuid4()}"
    issued = int(time.time())
    previous = uuid4().hex
    monkeypatch.setattr(settings, "guest_token_previous_secret", previous)
    browser.cookies.set(GUEST_TOKEN_COOKIE, issue_guest_token(previous, guest, issued))
    proof = guest_csrf_for(previous, guest, issued)
    with SessionLocal() as db:
        db.add_all([LearnerRecord(user_id=guest, completed_items=["guest-fixture"]),
                    LearnerRecord(user_id=principal, completed_items=["account-fixture"]),
                    GuestLegacyUpgrade(guest_id=guest)])
        db.commit()
    assert browser.post("/auth/guest-claim", headers=headers).status_code == 403
    assert browser.post("/auth/guest-claim", headers={
        "x-guest-claim-csrf": proof, "x-qcai-csrf": headers["x-qcai-csrf"],
    }).status_code == 403
    result = browser.post("/auth/guest-claim", headers={**headers, "x-guest-claim-csrf": proof})
    assert result.status_code == 200, result.text
    assert browser.get("/learner-record").json()["completed_item_ids"] == ["account-fixture", "guest-fixture"]
    with SessionLocal() as db:
        assert db.get(GuestLegacyUpgrade, guest) is None


def test_phase8_an_erased_guest_token_is_refused_on_requests_and_legacy_upgrade_after_rotation(monkeypatch):
    settings = get_settings()
    guest = f"guest-{uuid4()}"
    now = int(time.time())
    old_secret = settings.guest_token_secret
    browser = TestClient(app)
    browser.cookies.set(GUEST_TOKEN_COOKIE, issue_guest_token(old_secret, guest, now))
    erased = browser.post("/auth/learner-erasure",
                          headers={"origin": ORIGIN, "x-qcai-csrf": guest_csrf_for(old_secret, guest, now)}, json={})
    assert erased.status_code == 200, erased.text
    monkeypatch.setattr(settings, "guest_token_previous_secret", old_secret)
    monkeypatch.setattr(settings, "guest_token_secret", uuid4().hex)
    browser.cookies.set(GUEST_TOKEN_COOKIE, issue_guest_token(old_secret, guest, now))
    assert browser.get("/auth/me").status_code == 401
    monkeypatch.setattr(settings, "guest_token_previous_secret", None)
    browser.cookies.set(GUEST_TOKEN_COOKIE, issue_guest_token(settings.guest_token_secret, guest, now))
    assert browser.get("/auth/me").status_code == 401
    monkeypatch.setattr(settings, "guest_legacy_upgrade_until", datetime.now(UTC) + timedelta(days=1))
    with SessionLocal() as db:
        assert db.get(GuestRevocation, guest) is None
        assert upgrade_legacy_guest(db, settings, guest, uuid4().hex) is None


def test_phase8_privacy_http_consent_export_erasure_and_assessment(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "learner_identity", "on")
    browser, headers, principal, address = account()
    assert not any(browser.get("/auth/learner-consent").json()["consent"].values())
    assert browser.put("/auth/learner-consent", headers=headers,
                       json={"consent_class": "research", "granted": True}).status_code == 409
    payload = {"event_type": "fixture", "payload": {"marker": "owned-analytics-marker"}}
    assert browser.post("/analytics/events", headers=headers, json=payload).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AnalyticsEvent).where(AnalyticsEvent.user_id == principal)) == 0
    assert browser.put("/auth/learner-consent", headers=headers,
                       json={"consent_class": "analytics", "granted": True}).status_code == 200
    assert browser.post("/analytics/events", headers=headers, json=payload).status_code == 200
    with monkeypatch.context() as flags:
        flags.setattr(settings, "learner_privacy", "off")
        other, other_headers, other_id, _ = account()
        assert other.post("/analytics/events", headers=other_headers,
                          json={**payload, "payload": {"marker": "other-analytics-marker"}}).status_code == 200
    result = quiz(browser, headers)
    assert result.status_code == 200 and result.json()["score"] != 999
    attempt_id = result.json()["attempt_id"]
    with SessionLocal() as db:
        fact = db.get(LearnerAssessmentFact, attempt_id)
        assert fact is not None and fact.mastery == 1.0
        assert db.get(QuizAttempt, attempt_id).score == result.json()["score"]
        assert db.scalar(select(func.count()).select_from(AnalyticsEvent).where(AnalyticsEvent.user_id == other_id)) == 1
        subject = fact.user_id
        support = SupportRequest(email=address, name="Fixture", request_type="fixture", message="Fixture support message")
        db.add(support)
        db.flush()
        support_id = support.id
        before = db.scalar(select(func.max(SecurityEvent.seq))) or 0
        db.commit()
    exported = browser.get("/auth/learner-export")
    assert exported.status_code == 200 and exported.headers["cache-control"] == "no-store"
    rows = [json.loads(line) for line in exported.text.splitlines()]
    events = [row["record"]["payload"]["marker"] for row in rows if row["table"] == "analytics_events"]
    assert events == ["owned-analytics-marker"]
    assert browser.post("/auth/learner-erasure", headers=headers, json={}).status_code == 401
    assert browser.post("/auth/learner-erasure", headers=headers, json={"password": "incorrect"}).status_code == 401
    with SessionLocal() as db:
        events = list(db.scalars(select(SecurityEvent).where(
            SecurityEvent.seq > before, SecurityEvent.event_type == "learner.erasure",
        ).order_by(SecurityEvent.seq)))
        assert len(events) == 2 and all(row.outcome == "failure" and row.details["status"] == 401 for row in events)
        assert db.get(QuizAttempt, attempt_id) is not None
    erased = browser.post("/auth/learner-erasure", headers=headers, json={"password": PASSWORD})
    assert erased.status_code == 200, erased.text
    assert "qcai_session_token" not in browser.cookies
    receipt = erased.json()
    assert "support_requests" in receipt["scope"] and "support_requests" not in receipt["zero_counts"]
    with SessionLocal() as db:
        assert db.get(SupportRequest, support_id) is not None
        assert db.get(LearnerErasureAudit, receipt["id"]).receipt_digest == canonical_sha256(receipt)
        assert not independently_remaining(db, (principal, subject))


@pytest.mark.parametrize(("method", "path"), [("POST", "/auth/learner-erasure"), ("DELETE", "/auth/account")])
def test_ac_8_5_every_erasure_route_writes_a_verified_receipt(monkeypatch, method, path):
    monkeypatch.setattr(get_settings(), "learner_privacy", "on")
    browser, headers, principal, _ = account()
    with SessionLocal() as db:
        subject = bind_subject(db, "local", principal)
        db.add(Note(user_id=subject, lesson_slug=LESSON, body="Synthetic bound note"))
        db.commit()
        before = db.scalar(select(func.count()).select_from(LearnerErasureAudit))
        assert "user_accounts" in independently_remaining(db, (principal,))
        assert "notes" in independently_remaining(db, (subject,))
    response = browser.request(method, path, headers=headers, json={"password": PASSWORD})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert "qcai_session_token" not in browser.cookies
    body = response.json()
    if method == "DELETE":
        assert body["status"] == "deleted"
        receipt = body["receipt"]
    else:
        receipt = body
    zero_counts = receipt["zero_counts"]
    assert {table.name for table in user_keyed_tables()} <= set(zero_counts)
    assert all(count == 0 for count in zero_counts.values())
    with SessionLocal() as db:
        assert not independently_remaining(db, (principal, subject))
        assert db.scalar(select(func.count()).select_from(LearnerErasureAudit)) == before + 1
        audit = db.get(LearnerErasureAudit, receipt["id"])
        assert audit.receipt_digest == canonical_sha256(receipt)
        assert audit.table_set_digest == canonical_sha256(sorted(zero_counts)) and audit.deleted_total > 0


@pytest.mark.parametrize(("method", "path"), [("POST", "/auth/learner-erasure"), ("DELETE", "/auth/account")])
def test_ac_8_5_erasure_rolls_back_when_a_surviving_row_fails_verification(monkeypatch, method, path):
    from app.services import learner_record_privacy

    monkeypatch.setattr(get_settings(), "learner_privacy", "on")
    browser, headers, principal, _ = account()
    with SessionLocal() as db:
        subject = bind_subject(db, "local", principal)
        db.commit()
        before = db.scalar(select(func.count()).select_from(LearnerErasureAudit))
    erase = learner_record_privacy.erase_user

    def leave_bound_rows(db, identifier):
        return {} if identifier == subject else erase(db, identifier)

    monkeypatch.setattr(learner_record_privacy, "erase_user", leave_bound_rows)
    with pytest.raises(RuntimeError, match="Erasure verification failed"):
        browser.request(method, path, headers=headers, json={"password": PASSWORD})
    with SessionLocal() as db:
        assert "user_accounts" in independently_remaining(db, (principal,))
        assert "learner_records" in independently_remaining(db, (subject,))
        assert db.scalar(select(func.count()).select_from(LearnerErasureAudit)) == before


def test_freeze_phase8_privacy_off_account_deletion_keeps_the_original_response(monkeypatch):
    monkeypatch.setattr(get_settings(), "learner_privacy", "off")
    browser, headers, principal, _ = account()
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(LearnerErasureAudit))
    response = browser.request("DELETE", "/auth/account", headers=headers, json={"password": PASSWORD})
    assert response.status_code == 200, response.text
    assert response.content == b'{"status":"deleted"}'
    with SessionLocal() as db:
        assert not independently_remaining(db, (principal,))
        assert db.scalar(select(func.count()).select_from(LearnerErasureAudit)) == before


@pytest.mark.parametrize("identity", ["on", "off"])
def test_phase8_a_principal_erased_and_signing_in_again_gets_a_fresh_empty_record(monkeypatch, identity):
    from app.core import auth
    from app.services.learner_record_identity import find_subject

    settings = get_settings()
    monkeypatch.setattr(settings, "learner_identity", identity)
    principal = f"fixture-{uuid4().hex}"
    monkeypatch.setattr(auth, "_decode_auth0_token", lambda *_: auth.AuthUser(principal, None, "learner", "auth0"))
    headers = {"authorization": "Bearer fixture", "origin": ORIGIN}
    first = TestClient(app)
    assert quiz(first, headers).status_code == 200
    with SessionLocal() as db:
        previous = find_subject(db, "auth0", principal)
    assert first.post("/auth/learner-erasure", headers={"authorization": "Bearer fixture"}, json={}).status_code == 403
    assert first.post("/auth/learner-erasure", headers=headers, json={}).status_code == 200
    with SessionLocal() as db:
        assert not independently_remaining(db, tuple(filter(None, (principal, previous))))

    returning = TestClient(app)
    empty = returning.get("/learner-record", headers=headers).json()
    assert empty["record_version"] == 0 and empty["mastery"] == {}
    assert quiz(returning, headers).status_code == 200
    issued = returning.post("/learner-record/replicas", headers=headers)
    assert issued.status_code == 201
    version = returning.get("/learner-record", headers=headers).json()["record_version"]
    assert returning.post("/learner-record/operations", headers=headers,
                          json=batch(issued.json()["replica_id"], 1, "returning", version)).status_code == 200
    consent = returning.put("/auth/learner-consent", headers=headers, json={"consent_class": "analytics", "granted": True})
    assert consent.status_code == 200 and consent.json()["consent"]["analytics"]
    assert returning.post("/analytics/events", headers=headers, json={"event_type": "fixture"}).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AnalyticsEvent).where(AnalyticsEvent.user_id == principal)) == 1
        if previous is not None:
            assert find_subject(db, "auth0", principal) != previous
            assert not independently_remaining(db, (previous,))


@pytest.mark.parametrize("headers", [{}, {"x-demo-user": "demo-learner"}], ids=["fallback", "explicit"])
def test_phase8_shared_demo_cannot_export_or_erase(headers):
    browser = TestClient(app)
    assert browser.get("/auth/learner-export", headers=headers).status_code == 403
    assert browser.post("/auth/learner-erasure", headers={**headers, "origin": ORIGIN}, json={}).status_code == 403


def test_phase8_a_demo_header_cannot_export_or_erase_another_principal():
    signed_in, _, principal, _ = account()
    guest = f"guest-{uuid4()}"
    signed_guest = TestClient(app)
    signed_guest.cookies.set(GUEST_TOKEN_COOKIE, issue_guest_token(get_settings().guest_token_secret, guest, int(time.time())))
    with SessionLocal() as db:
        subject = bind_subject(db, "local", principal)
        db.add(Note(user_id=guest, lesson_slug=LESSON, body="Synthetic guest notes"))
        db.commit()
        targets = (principal, guest, subject)
        before = {identifier: independently_remaining(db, (identifier,)) for identifier in targets}
        assert all(before.values())
    visitor = TestClient(app)
    for identifier in (*targets, f"demo-{uuid4().hex}"):
        headers = {"x-demo-user": identifier, "origin": ORIGIN}
        assert visitor.get("/auth/learner-export", headers=headers).status_code == 403
        assert visitor.post("/auth/learner-erasure", headers=headers, json={}).status_code == 403
    with SessionLocal() as db:
        assert {identifier: independently_remaining(db, (identifier,)) for identifier in targets} == before
    assert signed_in.get("/auth/learner-export").status_code == 200
    assert signed_guest.get("/auth/learner-export").status_code == 200


def test_phase8_erasure_confirmation_is_limited_and_audits_duration(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_login_rate_limit", "2/minute")
    browser, headers, principal, _ = account()
    assert quiz(browser, headers).status_code == 200
    for _ in range(2):
        assert browser.post("/auth/learner-erasure", headers=headers, json={"password": "wrong"}).status_code == 401
    refused = browser.post("/auth/learner-erasure", headers=headers, json={"password": PASSWORD})
    assert refused.status_code == 429
    with SessionLocal() as db:
        assert "quiz_attempts" in independently_remaining(db, (principal,))

    monkeypatch.setattr(settings, "auth_login_rate_limit", "3/minute")
    with SessionLocal() as db:
        before = db.scalar(select(func.max(SecurityEvent.seq))) or 0
    erased = browser.post("/auth/learner-erasure", headers=headers, json={"password": PASSWORD})
    assert erased.status_code == 200
    with SessionLocal() as db:
        audit = db.scalars(select(SecurityEvent).where(
            SecurityEvent.seq > before, SecurityEvent.event_type == "learner.erasure", SecurityEvent.outcome == "success",
        ).order_by(SecurityEvent.seq)).one()
        assert isinstance(audit.details["duration_ms"], int) and audit.details["duration_ms"] >= 0


def test_phase8_assessment_quota_counts_the_authenticated_principal_of_a_bound_account(monkeypatch):
    from app.services.learner_record_identity import find_subject
    from app.services.learner_record_sync import ASSESSMENT_LIMIT

    monkeypatch.setattr(get_settings(), "learner_identity", "on")
    first, first_headers, first_principal, _ = account()
    second, second_headers, second_principal, _ = account()
    with SessionLocal() as db:
        first_subject = bind_subject(db, "local", first_principal)
        second_subject = bind_subject(db, "local", second_principal)
        assert first_subject != first_principal and second_subject != second_principal
        db.add_all(
            QuizAttempt(user_id=owner, lesson_slug=LESSON, score=0, responses={})
            for owner in (first_principal, second_subject) for _ in range(ASSESSMENT_LIMIT)
        )
        db.commit()
    refused = quiz(first, first_headers)
    assert refused.status_code == 429 and refused.headers["retry-after"] == "900"
    accepted = quiz(second, second_headers)
    assert accepted.status_code == 200, accepted.text
    with SessionLocal() as db:
        assert find_subject(db, "local", second_principal) == second_subject
        assert db.get(LearnerAssessmentFact, accepted.json()["attempt_id"]).user_id == second_subject


def test_plan_i_f3_a_server_scored_attempt_logs_the_record_update_within_the_interaction(caplog, monkeypatch):
    from app.core.structured_logging import FIELDS
    from app.services.learner_record_metrics import snapshot

    def update_events():
        return [getattr(log, FIELDS) for log in caplog.records
                if getattr(log, FIELDS, {}).get("event") == "learner.record.updated"]

    caplog.set_level("INFO")
    settings = get_settings()
    browser, headers, _, _ = account()
    committed = snapshot().get("learner.record.committed", 0)
    assert quiz(browser, headers).status_code == 200
    updates = update_events()
    assert len(updates) == 1
    update = updates[0]
    assert set(update) == {"event", "interaction_started_at", "record_committed_at", "record_version"}
    assert datetime.fromisoformat(update["interaction_started_at"]) <= datetime.fromisoformat(update["record_committed_at"])
    assert update["record_version"] == browser.get("/learner-record", headers=headers).json()["record_version"]
    assert snapshot()["learner.record.committed"] == committed + 1

    caplog.clear()
    monkeypatch.setattr(settings, "learner_sync", "off")
    assert quiz(browser, headers).status_code == 200
    monkeypatch.setattr(settings, "learner_sync", "on")
    assert quiz(TestClient(app), {"x-demo-user": f"fixture-{uuid4().hex}"}).status_code == 200
    guest = f"guest-{uuid4()}"
    issued = int(time.time())
    guest_client = TestClient(app)
    guest_client.cookies.set(GUEST_TOKEN_COOKIE, issue_guest_token(settings.guest_token_secret, guest, issued))
    assert quiz(guest_client, {"origin": ORIGIN, "x-qcai-csrf": guest_csrf_for(settings.guest_token_secret, guest, issued)}).status_code == 200
    assert not update_events()
    assert snapshot()["learner.record.committed"] == committed + 1
