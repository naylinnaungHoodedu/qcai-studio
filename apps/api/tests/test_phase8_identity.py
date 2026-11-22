"""Phase 8 subject binding, guest-claim proof, and persistent audit."""

import time
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.guest_tokens import guest_csrf_for, issue_guest_token
from app.db_models import Base, LearnerClaimAudit, LearnerRecord
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


def test_plan_j_a_forged_or_revoked_guest_token_cannot_claim(identity_engine):
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
        with pytest.raises(HTTPException, match="unavailable for claim"):
            claim_guest(db, "local", f"account-{uuid4()}", token, csrf, settings)
