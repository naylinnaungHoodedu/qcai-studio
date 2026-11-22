"""Phase 3: an Idempotency-Key claim whose request died is released after its lease, and a request past its lease never
makes a second turn (DI-40; spec 7.13).

E7  an abandoned claim is released after a short lease, not the 24-hour TTL; the lease is a provisional package value.
F13 a request past its lease cannot make a second turn for its key; the claim token guards a reused id, a late release
    and a concurrent fill; the lease is a liveness bound and the runbook records the request timeout.
Each test fails if its defect comes back; the spec's review history (18.4) names the round behind each group.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from app.api.routes import tutor as tutor_route
from app.core.config import Settings
from app.core.config_package import get_config_package
from app.core.db import Base, SessionLocal
from app.core.schema_upgrades import run_schema_upgrades
from app.db_models import TutorTurn, TutorTurnIdempotency
from app.main import app
from app.services import turn_idempotency
from app.services.tutor_pipeline.contracts import sha256_hex


PACKAGE = get_config_package(Settings())
PARAMS = PACKAGE.tutor_pipeline
IN_DOMAIN = "How does graph shrinking reduce routing overhead?"
client = TestClient(app)
API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
RUNBOOK = (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8")


def demo(prefix: str, role: str = "learner") -> dict[str, str]:
    return {"x-demo-user": f"{prefix}-{uuid4().hex[:12]}", "x-demo-role": role, "x-forwarded-for": f"idempotency-lease-{uuid4().hex}"}


def fresh(headers: dict[str, str]) -> dict[str, str]:
    # A distinct client address per request keeps the per-address limits apart.
    return {**headers, "x-forwarded-for": f"idempotency-lease-{uuid4().hex}"}


def fresh_sessions(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False), engine


# =============================================================================================================== E7


def _idempotent_turn(headers: dict[str, str], key: str):
    return client.post("/tutor/turns", headers={**fresh(headers), "Idempotency-Key": key}, json={"message": IN_DOMAIN})


def _claim(user_id: str, key: str, *, age: timedelta) -> None:
    digest = turn_idempotency.request_sha256(message=IN_DOMAIN, thread_id=None, lesson_slug=None, presentation_plan=None)
    with SessionLocal() as db:
        db.add(TutorTurnIdempotency(user_id=user_id, key_sha256=sha256_hex(key), request_sha256=digest, created_at=datetime.now(UTC) - age))
        db.commit()


def test_e7_an_abandoned_claim_is_released_after_its_lease_and_a_live_one_still_answers_409():
    assert PARAMS.idempotency_lease_seconds == 600 < PARAMS.idempotency_ttl_hours * 3600
    headers = demo("e7")
    user_id = headers["x-demo-user"]
    live_key, dead_key = f"live-{uuid4().hex}", f"dead-{uuid4().hex}"
    _claim(user_id, live_key, age=timedelta(seconds=30))
    _claim(user_id, dead_key, age=timedelta(seconds=PARAMS.idempotency_lease_seconds + 60))
    assert _idempotent_turn(headers, live_key).status_code == 409
    renewed = _idempotent_turn(headers, dead_key)
    assert renewed.status_code == 200 and "idempotent-replayed" not in renewed.headers
    with SessionLocal() as db:
        row = db.scalars(select(TutorTurnIdempotency).where(TutorTurnIdempotency.user_id == user_id,
                                                            TutorTurnIdempotency.key_sha256 == sha256_hex(dead_key))).one()
        assert row.turn_id == renewed.json()["turn_id"] and row.response_body is not None
    # The retry is then remembered as usual.
    again = _idempotent_turn(headers, dead_key)
    assert again.status_code == 200 and again.headers["idempotent-replayed"] == "true" and again.json() == renewed.json()


def test_e7_the_lease_is_a_provisional_package_value_shorter_than_the_ttl(tmp_path):
    raw = json.loads(PACKAGE.path.read_text(encoding="utf-8"))
    block = raw["tutor_pipeline"]["idempotency"]
    assert block["provisional"] is True and block["in_progress_lease_seconds"] == 600
    from app.core.config_package import ConfigPackageError, parse_config_package

    for value in (block["ttl_hours"] * 3600, 30, None):
        payload = json.loads(json.dumps(raw))
        if value is None:
            payload["tutor_pipeline"]["idempotency"].pop("in_progress_lease_seconds")
        else:
            payload["tutor_pipeline"]["idempotency"]["in_progress_lease_seconds"] = value
        with pytest.raises(ConfigPackageError):
            parse_config_package(payload, path=PACKAGE.path, sha256="", hash_verified=False)


# ============================================================================================================== F13


def _key_row(user_id: str, key: str) -> TutorTurnIdempotency:
    with SessionLocal() as db:
        return db.scalars(select(TutorTurnIdempotency).where(TutorTurnIdempotency.user_id == user_id,
                                                             TutorTurnIdempotency.key_sha256 == turn_idempotency.key_sha256(key))).one()


def test_f13_a_request_past_its_lease_cannot_make_a_second_turn_for_its_key(monkeypatch):
    headers = demo("f13")
    user_id, key = headers["x-demo-user"], f"lease-{uuid4().hex}"
    real = tutor_route.deliver_tutor_turn
    outcome: dict[str, object] = {}

    def outlives_its_lease(*args, **kwargs):
        if not outcome:
            outcome["started"] = True  # the retry below passes through here too, and runs normally
            # The claim ages past its lease while this request still runs, and a retry takes the key over.
            with SessionLocal() as db:
                db.execute(update(TutorTurnIdempotency)
                           .where(TutorTurnIdempotency.user_id == user_id, TutorTurnIdempotency.key_sha256 == turn_idempotency.key_sha256(key))
                           .values(created_at=datetime.now(UTC) - timedelta(seconds=PARAMS.idempotency_lease_seconds + 60)))
                db.commit()
            outcome["retry"] = client.post("/tutor/turns", headers={**fresh(headers), "Idempotency-Key": key}, json={"message": IN_DOMAIN})
        return real(*args, **kwargs)

    monkeypatch.setattr(tutor_route, "deliver_tutor_turn", outlives_its_lease)
    late = client.post("/tutor/turns", headers={**fresh(headers), "Idempotency-Key": key}, json={"message": IN_DOMAIN})
    retry = outcome["retry"]
    assert retry.status_code == 200 and "idempotent-replayed" not in retry.headers
    assert (late.status_code, late.json()["detail"], late.headers["cache-control"]) == (409, turn_idempotency.SUPERSEDED, "no-store")
    with SessionLocal() as db:
        turns = list(db.scalars(select(TutorTurn.id).where(TutorTurn.user_id == user_id)))
    assert turns == [retry.json()["turn_id"]]  # one key, one turn
    row = _key_row(user_id, key)
    assert row.turn_id == retry.json()["turn_id"] and json.loads(row.response_body) == retry.json()
    monkeypatch.undo()
    again = client.post("/tutor/turns", headers={**fresh(headers), "Idempotency-Key": key}, json={"message": IN_DOMAIN})
    assert again.status_code == 200 and again.headers["idempotent-replayed"] == "true" and again.json() == retry.json()


def test_f13_the_claim_token_guards_a_reused_id_a_late_release_and_a_concurrent_fill(fresh_database_url, monkeypatch):
    factory, engine = fresh_sessions(fresh_database_url)
    key, request = "k" * 64, "r" * 64
    now = datetime.now(UTC)
    old = now - timedelta(seconds=PARAMS.idempotency_lease_seconds + 60)
    lease = {"ttl_hours": PARAMS.idempotency_ttl_hours, "lease_seconds": PARAMS.idempotency_lease_seconds}
    try:
        with factory() as db:
            first = turn_idempotency.new_claim(user_id="u", key_digest=key, request_digest=request, now=old)
            db.add(first)
            db.commit()
            held_first = TutorTurnIdempotency(id=first.id, claim_token=first.claim_token)
        # A retry replaces the abandoned claim; its row takes the same id, as SQLite reused ids before AUTOINCREMENT.
        with factory() as db:
            assert turn_idempotency.find(db, "u", key, now=now, **lease) is None
            second = turn_idempotency.new_claim(user_id="u", key_digest=key, request_digest=request, now=now)
            second.id = held_first.id
            db.add(second)
            db.commit()
            held_second = TutorTurnIdempotency(id=second.id, claim_token=second.claim_token)
        assert held_first.id == held_second.id and held_first.claim_token != held_second.claim_token
        with factory() as db:
            with pytest.raises(turn_idempotency.ClaimLost):
                turn_idempotency.fill(db, held_first, turn_id="turn-late", response_body="{}")
            db.rollback()
            turn_idempotency.release(db, held_first)  # the late request's release leaves the retry's claim alone
            db.commit()
        with factory() as db:
            row = db.scalars(select(TutorTurnIdempotency)).one()
            assert (row.claim_token, row.turn_id, row.response_body) == (held_second.claim_token, None, None)
            turn_idempotency.fill(db, held_second, turn_id="turn-retry", response_body='{"ok":true}')
            db.commit()
        with factory() as db:
            with pytest.raises(turn_idempotency.ClaimLost):  # a filled claim is never filled twice
                turn_idempotency.fill(db, held_second, turn_id="turn-again", response_body="{}")
        # A claim that is filled while a retry decides it is abandoned is kept: the conditional delete misses it, and
        # the retry reads the filled record.
        with factory() as db:
            db.execute(update(TutorTurnIdempotency).values(turn_id=None, response_body=None, created_at=old))
            db.commit()
        real_lookup = turn_idempotency._lookup
        calls = []

        def lookup(db, user_id, key_digest):
            row = real_lookup(db, user_id, key_digest)
            if not calls:
                with factory() as other:
                    other.execute(update(TutorTurnIdempotency).values(turn_id="turn-filled", response_body='{"filled":true}'))
                    other.commit()
            calls.append(row)
            return row

        monkeypatch.setattr(turn_idempotency, "_lookup", lookup)
        with factory() as db:
            found = turn_idempotency.find(db, "u", key, now=now, **lease)
            assert found is not None and found.turn_id == "turn-filled"
        assert len(calls) == 2
    finally:
        engine.dispose()


def test_f13_the_lease_is_a_liveness_bound_and_the_runbook_records_the_request_timeout():
    source = (API_ROOT / "app" / "services" / "turn_idempotency.py").read_text(encoding="utf-8")
    assert "Safety does not depend on any timeout" in source and "were it still running, its commit would find the claim gone" not in source
    assert "Read the service's request timeout" in RUNBOOK and "timeoutSeconds" in RUNBOOK
