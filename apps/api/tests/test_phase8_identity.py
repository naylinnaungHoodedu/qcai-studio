"""Phase 8 subject binding, guest-claim proof, and persistent audit."""

import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.guest_tokens import GUEST_TOKEN_MAX_AGE_SECONDS, guest_csrf_for, issue_guest_token
from app.db_models import ArenaProfile, Base, GuestRevocation, LearnerClaimAudit, LearnerGuestRevocation, LearnerRecord
from app.services.guest_sessions import is_guest_revoked
from app.services.learner_record_identity import bind_subject, claim_guest, find_subject


@pytest.fixture()
def identity_engine(fresh_database_url):
    engine = create_engine(fresh_database_url)
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()


def test_phase8_subject_is_stable_and_provider_scoped(identity_engine):
    principal = uuid4().hex
    with Session(identity_engine, autoflush=False) as db:
        local = bind_subject(db, "local", principal)
        federated = bind_subject(db, "auth0", principal)
        db.commit()
    with Session(identity_engine, autoflush=False) as db:
        assert bind_subject(db, "local", principal) == local
        assert find_subject(db, "auth0", principal) == federated
        assert local != federated and principal not in local


def test_phase8_claim_requires_guest_csrf_and_is_one_shot(identity_engine):
    guest = f"guest-{uuid4()}"
    account = f"account-{uuid4()}"
    settings = Settings(_env_file=None, learner_identity="on")
    issued = int(time.time())
    token = issue_guest_token(settings.guest_token_secret, guest, issued)
    csrf = guest_csrf_for(settings.guest_token_secret, guest, issued)
    with Session(identity_engine, autoflush=False) as db:
        db.add(LearnerRecord(user_id=guest, record_version=2, mastery={"skill": 0.6}, completed_items=["lesson"]))
        db.commit()
        with pytest.raises(HTTPException, match="both verified credentials"):
            claim_guest(db, "local", account, token, None, settings)
        db.rollback()
        assert db.get(LearnerRecord, guest) is not None

        assert claim_guest(db, "local", account, token, csrf, settings)["learner_records"] == 1
        db.commit()
        subject = find_subject(db, "local", account)
        assert db.get(LearnerRecord, subject).mastery == {"skill": 0.6}
        assert db.get(LearnerRecord, guest) is None
        audit = db.scalars(select(LearnerClaimAudit)).one()
        assert audit.transferred["learner_records"] == 1
        assert audit.guest_digest != guest and audit.subject_digest != subject
        assert is_guest_revoked(db, guest, include_phase8=True)
        with pytest.raises(HTTPException, match="unavailable"):
            claim_guest(db, "local", f"account-{uuid4()}", token, csrf, settings)


@pytest.mark.parametrize("case", ["tampered", "wrong-key", "wrong-csrf", "expired", "raw-revoked", "digest-revoked", "public"])
def test_phase8_claim_refuses_unauthorized_or_unavailable_guest(identity_engine, case):
    from app.services.guest_sessions import guest_credential_digest

    settings = Settings(_env_file=None, learner_identity="on")
    guest, principal = f"guest-{uuid4()}", f"acct-{uuid4()}"
    issued = int(time.time()) - (GUEST_TOKEN_MAX_AGE_SECONDS + 10 if case == "expired" else 0)
    issuer = uuid4().hex if case == "wrong-key" else settings.guest_token_secret
    token = issue_guest_token(issuer, guest, issued)
    csrf = guest_csrf_for(issuer, f"guest-{uuid4()}" if case == "wrong-csrf" else guest, issued)
    if case == "tampered":
        token = token[:-1] + ("1" if token[-1] == "0" else "0")
    with Session(identity_engine, autoflush=False) as db:
        db.add(LearnerRecord(user_id=guest, completed_items=["fixture"]))
        if case == "raw-revoked":
            db.add(GuestRevocation(guest_id=guest, reason="fixture"))
        if case == "digest-revoked":
            db.add(LearnerGuestRevocation(credential_digest=guest_credential_digest(guest)))
        if case == "public":
            db.add(ArenaProfile(player_id=guest, display_name="Fixture"))
        db.commit()
        with pytest.raises(HTTPException) as refused:
            claim_guest(db, "local", principal, token, csrf, settings)
        assert refused.value.status_code == (409 if case in {"raw-revoked", "digest-revoked", "public"} else 403)
        db.rollback()
        assert db.get(LearnerRecord, guest).completed_items == ["fixture"]
        assert find_subject(db, "local", principal) is None
        assert db.scalar(select(func.count()).select_from(LearnerClaimAudit)) == 0
        assert db.scalar(select(func.count()).select_from(LearnerGuestRevocation)) == int(case == "digest-revoked")


@pytest.mark.parametrize("claims", [{}, {"sub": ""}])
def test_phase8_identity_refuses_a_bearer_token_without_sub(monkeypatch, claims):
    from app.core import auth

    class OfflineKeyClient:
        def __init__(self, _url):
            pass

        def get_signing_key_from_jwt(self, _token):
            return SimpleNamespace(key=object())

    monkeypatch.setattr(auth, "PyJWKClient", OfflineKeyClient)
    monkeypatch.setattr(auth.jwt, "decode", lambda *args, **kwargs: claims)
    settings = Settings(_env_file=None, learner_identity="on", auth0_domain="issuer.invalid", auth0_audience="test")
    with pytest.raises(HTTPException) as refused:
        auth._decode_auth0_token("offline-fixture", settings)
    assert refused.value.status_code == 401
    settings.learner_identity = "off"
    assert auth._decode_auth0_token("offline-fixture", settings).user_id == claims.get("sub", "unknown")
