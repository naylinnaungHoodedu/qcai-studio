"""Phase 8 synthetic privacy lifecycle checks."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.config_package import canonical_sha256, get_config_package
from app.db_models import Base, LearnerErasureAudit, LearnerRecord, LearnerSubject
from app.services.erasure import learner_table_conditions
from app.services.guest_sessions import is_guest_revoked
from app.services.learner_record_identity import bind_subject, find_subject
from app.services.learner_record_privacy import erase_subject, iter_export, read_consent, set_consent
from scripts.prove_erasure import _present, _seed, independently_remaining, seed_bound, seed_claimed


@pytest.fixture()
def privacy_engine(fresh_database_url):
    engine = create_engine(fresh_database_url)
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()


def test_phase8_consent_defaults_denied_and_research_remains_refused(privacy_engine):
    owner = f"demo-{uuid4().hex}"
    settings = Settings(_env_file=None)
    with Session(privacy_engine, autoflush=False) as db:
        assert not any(read_consent(db, "demo", owner).values())
        assert set_consent(db, "demo", owner, "analytics", True, settings)["analytics"]
        db.commit()
        with pytest.raises(HTTPException, match="D-27"):
            set_consent(db, "demo", owner, "research", True, settings)
        assert not set_consent(db, "demo", owner, "analytics", False, settings)["analytics"]


@pytest.mark.parametrize("provider", ["local", "guest", "auth0", "demo"])
def test_phase8_export_and_erasure_cover_bound_subject_and_legacy_rows(privacy_engine, provider):
    owner, other = (f"{provider}-{uuid4().hex}" for _ in range(2))
    settings = Settings(_env_file=None)
    with Session(privacy_engine, autoflush=False) as db:
        subject, raw, bound = seed_bound(db, provider, owner)
        db.get(LearnerRecord, subject).completed_items = ["owned"]
        db.get(LearnerRecord, owner).completed_items = ["legacy"]
        controls = _seed(db, other)
        db.commit()
        rows = [json.loads(line) for line in iter_export(db, provider, owner)]
        assert sorted(row["record"]["completed_items"] for row in rows if row["table"] == "learner_records") == [
            ["legacy"], ["owned"],
        ]
        assert all(owner not in str(row) and other not in str(row) for row in rows)
        receipt = erase_subject(db, provider, owner, settings)
        db.commit()
        assert receipt["zero_counts"] and set(receipt["zero_counts"].values()) == {0}
        assert db.get(LearnerErasureAudit, receipt["id"]).receipt_digest == canonical_sha256(receipt)
        assert not independently_remaining(db, (owner, subject))
        assert not _present(db, raw) and not _present(db, bound)
        assert len(_present(db, controls)) == len(controls)
        if provider == "guest":
            assert is_guest_revoked(db, owner)


def test_plan_j_export_covers_every_user_keyed_table_and_no_other_learner_s_rows(privacy_engine):
    from app.db_models import ArenaMatchRecord, PeerReview, TutorMessage, TutorThread

    owner, other = (f"demo-{uuid4().hex}" for _ in range(2))
    with Session(privacy_engine, autoflush=False) as db:
        own_rows = _seed(db, owner)
        other_rows = _seed(db, other)
        owned_thread = db.get(TutorThread, own_rows["tutor_threads"]["id"])
        owned_message = db.get(TutorMessage, own_rows["tutor_messages"]["id"])
        other_message = db.get(TutorMessage, other_rows["tutor_messages"]["id"])
        owned_message.content = "owned-fictional-message"
        other_message.content = "control-fictional-message"
        match = db.get(ArenaMatchRecord, other_rows["arena_match_records"]["id"])
        match.opponent_id = owner
        review = db.get(PeerReview, other_rows["peer_reviews"]["id"])
        review.submission_id = own_rows["project_submissions"]["id"]
        review.feedback = "independent-review-marker"
        # Synthetic seed uses the owner in both roles. A third-party handle must be omitted.
        db.get(ArenaMatchRecord, own_rows["arena_match_records"]["id"]).opponent_id = other
        db.commit()
        expected = set(learner_table_conditions((owner,), export=True))
        export = [json.loads(line) for line in iter_export(db, "demo", owner)]
        assert expected == {row["table"] for row in export}
        assert len([row for row in export if row["table"] in {"arena_match_records", "peer_reviews"}]) == 2
        messages = [row["record"] for row in export if row["table"] == "tutor_messages"]
        assert len(messages) == 1 and messages[0]["thread_id"] == owned_thread.id
        assert messages[0]["content"] == "owned-fictional-message"
        serialized = json.dumps(export)
        assert not any(value in serialized for value in (owner, other, "control-fictional-message", "independent-review-marker"))


def test_phase8_claimed_guest_and_account_erasure_leave_no_keyed_rows(privacy_engine):
    owner = f"acct-{uuid4().hex}"
    settings = Settings(_env_file=None)
    with Session(privacy_engine, autoflush=False) as db:
        guest = seed_claimed(db, settings, owner)
        subject, raw, bound = seed_bound(db, "local", owner)
        db.commit()
        receipt = erase_subject(db, "local", owner, settings)
        db.commit()
        assert not independently_remaining(db, (guest, owner, subject))
        assert not _present(db, raw) and not _present(db, bound)
        assert "tutor_messages" in receipt["zero_counts"]


def test_phase8_erasure_refuses_an_in_flight_subject_rebind(privacy_engine):
    owner = f"acct-{uuid4().hex}"
    settings = Settings(_env_file=None)
    entered, finished = Event(), Event()

    with Session(privacy_engine, autoflush=False) as erasing:
        subject = bind_subject(erasing, "local", owner)
        erasing.commit()
        with ThreadPoolExecutor(max_workers=1) as pool:
            # The request has already resolved the identity. Erasure wins the writer lock.
            go = Event()
            def waiting_writer():
                with Session(privacy_engine, autoflush=False) as db:
                    assert find_subject(db, "local", owner) == subject
                    entered.set()
                    assert go.wait(5)
                    try:
                        with pytest.raises(HTTPException, match="unavailable") as refused:
                            bind_subject(db, "local", owner)
                        assert refused.value.status_code == 409
                    finally:
                        finished.set()
            pending = pool.submit(waiting_writer)
            assert entered.wait(5)
            receipt = erase_subject(erasing, "local", owner, settings)
            go.set()
            assert not finished.wait(0.15)
            erasing.commit()
            pending.result(timeout=10)
        assert not independently_remaining(erasing, (owner, subject))
        assert erasing.scalars(select(LearnerSubject)).first() is None
        assert "learner_records" in receipt["zero_counts"]


@pytest.mark.parametrize("provider", ["local", "guest", "auth0", "demo"])
@pytest.mark.parametrize("without_gateway", [False, True])
def test_phase8_erasure_receipt_scope_matches_the_principal_type(privacy_engine, provider, without_gateway, monkeypatch):
    from dataclasses import replace
    from app.services import learner_record_privacy

    settings = Settings(_env_file=None)
    package = get_config_package(settings)
    if without_gateway:
        package = replace(package, gateway=None)
    monkeypatch.setattr(learner_record_privacy, "get_config_package", lambda _: package)
    owner = f"{provider}-{uuid4().hex}"
    with Session(privacy_engine, autoflush=False) as db:
        subject = bind_subject(db, provider, owner)
        receipt = erase_subject(db, provider, owner, settings)
        assert owner not in json.dumps(receipt) and subject not in json.dumps(receipt)
        expected = "account retained at issuer (DI-306)" if provider == "auth0" else "no external identity provider"
        assert receipt["scope"]["identity_provider"] == expected
        assert "365 days" in receipt["scope"]["audit_retention"]
        assert "unverified" in receipt["scope"]["external_processing"]
        gateways = [adapter.adapter_id for adapter in package.gateway.registries["development"]] if package.gateway else []
        assert receipt["gateway_registry"] == gateways
        assert receipt["zero_counts"]["tutor_messages"] == 0


@pytest.mark.parametrize("privacy", ["off", "on"])
def test_plan_j_retention_deletes_by_retention_class_after_the_configured_period(privacy_engine, privacy, monkeypatch):
    from app.core.config import get_settings
    from app.db_models import GuestLegacyUpgrade, LearnerConsent, Note, UserAccount
    from app.services.guest_sessions import upgrade_legacy_guest
    from app.services.retention import GUEST_STUDY_RETENTION_DAYS, run_retention_cleanup

    settings = get_settings()
    monkeypatch.setattr(settings, "learner_privacy", privacy)
    now = datetime.now(UTC)
    old = now - timedelta(days=GUEST_STUDY_RETENTION_DAYS + 5)
    monkeypatch.setattr(settings, "guest_legacy_upgrade_until", now + timedelta(days=1))
    stale_guest, fresh_guest = (f"guest-{uuid4()}" for _ in range(2))
    durable = f"acct-{uuid4().hex}"
    with Session(privacy_engine, autoflush=False) as db:
        bound = bind_subject(db, "guest", stale_guest)
        db.add_all([
            GuestLegacyUpgrade(guest_id=stale_guest, upgraded_at=old),
            GuestLegacyUpgrade(guest_id=fresh_guest, upgraded_at=now),
            LearnerConsent(user_id=bound, consent_class="analytics", consent_version="d27-unresolved-v1",
                           granted=True, updated_at=old, source="self-service"),
            LearnerConsent(user_id=bound, consent_class="adaptation", consent_version="d27-unresolved-v1",
                           granted=True, updated_at=now, source="self-service"),
            Note(user_id=bound, lesson_slug="fixture", body="stale", created_at=old),
            Note(user_id=bound, lesson_slug="fixture", body="fresh", created_at=now),
            Note(user_id=durable, lesson_slug="fixture", body="durable", created_at=old),
            UserAccount(user_id=durable, email=f"{uuid4().hex}@example.invalid", password_hash="fixture", created_at=old),
        ])
        db.commit()
        run_retention_cleanup(db, now=now)
        active = privacy == "on"
        assert (db.get(GuestLegacyUpgrade, stale_guest) is None) == active
        assert db.get(GuestLegacyUpgrade, fresh_guest) is not None
        assert (db.get(LearnerConsent, (bound, "analytics")) is None) == active
        assert db.get(LearnerConsent, (bound, "adaptation")) is not None
        assert set(db.scalars(select(Note.body))) == ({"fresh", "durable"} if active else {"stale", "fresh", "durable"})
        assert db.get(UserAccount, durable) is not None and find_subject(db, "guest", stale_guest) == bound
        assert upgrade_legacy_guest(db, settings, stale_guest, uuid4().hex) is None


def test_plan_f_linking_and_erasure_audits_expire_after_the_security_retention_period(privacy_engine):
    from app.db_models import LearnerClaimAudit
    from app.services.retention import SECURITY_EVENT_RETENTION_DAYS, run_retention_cleanup

    now = datetime.now(UTC)
    for model, fields in [
        (LearnerClaimAudit, {"guest_digest": "a", "subject_digest": "b", "transferred": {}}),
        (LearnerErasureAudit, {"receipt_digest": "a", "table_set_digest": "b", "deleted_total": 0}),
    ]:
        with Session(privacy_engine, autoflush=False) as db:
            stale, fresh = uuid4().hex, uuid4().hex
            db.add_all([
                model(id=stale, created_at=now - timedelta(days=SECURITY_EVENT_RETENTION_DAYS + 1), **fields),
                model(id=fresh, created_at=now - timedelta(days=SECURITY_EVENT_RETENTION_DAYS - 1), **fields),
            ])
            db.commit()
            run_retention_cleanup(db, now=now)
            assert db.get(model, stale) is None and db.get(model, fresh) is not None
