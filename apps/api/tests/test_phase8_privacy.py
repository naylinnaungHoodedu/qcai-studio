"""Phase 8 synthetic privacy lifecycle checks."""

import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.config_package import canonical_sha256
from app.db_models import Base, LearnerErasureAudit, LearnerRecord
from app.services.guest_sessions import is_guest_revoked
from app.services.learner_record_identity import bind_subject
from app.services.learner_record_privacy import erase_subject, iter_export, read_consent, set_consent


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
        subject = bind_subject(db, provider, owner)
        db.get(LearnerRecord, subject).completed_items = ["owned"]
        db.add(LearnerRecord(user_id=other, completed_items=["control"]))
        db.commit()
        rows = [json.loads(line) for line in iter_export(db, provider, owner)]
        assert [row["record"]["completed_items"] for row in rows if row["table"] == "learner_records"] == [["owned"]]
        assert all(owner not in str(row) and other not in str(row) for row in rows)
        receipt = erase_subject(db, provider, owner, settings)
        db.commit()
        assert receipt["zero_counts"] and set(receipt["zero_counts"].values()) == {0}
        assert db.get(LearnerErasureAudit, receipt["id"]).receipt_digest == canonical_sha256(receipt)
        assert db.get(LearnerRecord, other).completed_items == ["control"]
        if provider == "guest":
            assert is_guest_revoked(db, owner)
