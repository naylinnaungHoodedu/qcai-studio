"""Consent decisions and platform-managed lifecycle evidence for Phase 8."""

import json
from datetime import UTC, datetime
from math import isfinite
from uuid import uuid4

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.config_package import canonical_sha256, get_config_package
from app.db_models import GuestRevocation, LearnerConsent, LearnerConsentChange, LearnerErasureAudit, LearnerGuestRevocation
from app.schemas import LearnerConsentRecord
from app.services.erasure import USER_KEY_COLUMNS, erase_user, user_keyed_tables
from app.services.guest_sessions import guest_credential_digest
from app.services.learner_record_identity import _insert_for, find_subject
from app.services.learner_record_sync import lock_learner_record


CONSENT_VERSION = "d27-unresolved-v1"
CONSENT_CLASSES = ("adaptation", "analytics", "research")
_PRIVATE_COLUMNS = frozenset(USER_KEY_COLUMNS) | {
    "password_hash", "session_token_hash", "principal_digest", "key_sha256",
    "claim_token", "payload_hash", "request_sha256",
}
_CREDENTIAL_TABLES = {"user_sessions", "guest_revocations", "guest_legacy_upgrades", "learner_subjects"}


def retention_classes() -> dict[str, str]:
    overrides = {
        "user_sessions": "session-expiry",
        "guest_revocations": "credential-protection",
        "guest_legacy_upgrades": "guest-legacy-window",
        "learner_subjects": "subject-binding-until-erasure",
        "learner_consents": "guest-study-from-update",
    }
    return {
        table.name: overrides.get(table.name, "guest-study-from-creation" if "created_at" in table.c else "erasure-only")
        for table in user_keyed_tables()
    }


def subject_identifiers(db: Session, provider: str, identifier: str) -> tuple[str, ...]:
    subject = find_subject(db, provider, identifier)
    return (identifier, subject) if subject and subject != identifier else (identifier,)


def read_consent(db: Session, provider: str, identifier: str) -> dict[str, bool]:
    identifiers = subject_identifiers(db, provider, identifier)
    states = {kind: False for kind in CONSENT_CLASSES}
    for row in db.scalars(select(LearnerConsent).where(
        LearnerConsent.user_id.in_(identifiers), LearnerConsent.consent_version == CONSENT_VERSION,
    ).order_by(LearnerConsent.updated_at, LearnerConsent.user_id)):
        if row.consent_class in states:
            states[row.consent_class] = row.granted
    states["research"] = False
    return states


def set_consent(
    db: Session, provider: str, identifier: str, kind: str, granted: bool, settings: Settings,
) -> dict[str, bool]:
    if kind not in CONSENT_CLASSES:
        raise HTTPException(422, "Unknown consent class.")
    if granted and (kind == "research" or settings.environment.lower() != "development"):
        raise HTTPException(409, "Consent class is unavailable under D-27.")
    subject = subject_identifiers(db, provider, identifier)[-1]
    record = LearnerConsentRecord(
        user_id=subject, consent_class=kind, consent_version=CONSENT_VERSION, granted=granted,
        updated_at=datetime.now(UTC), source="self-service",
    )
    values = record.model_dump(exclude={"user_id", "consent_class"})
    db.execute(_insert_for(db)(LearnerConsent).values(user_id=subject, consent_class=kind, **values)
               .on_conflict_do_update(index_elements=["user_id", "consent_class"], set_=values))
    db.add(LearnerConsentChange(
        id=f"consent-{uuid4().hex}", user_id=subject, consent_class=kind,
        consent_version=CONSENT_VERSION, granted=granted, source="self-service",
    ))
    return read_consent(db, provider, identifier)


def iter_export(db: Session, provider: str, identifier: str):
    identifiers = subject_identifiers(db, provider, identifier)
    for table in user_keyed_tables():
        if table.name in _CREDENTIAL_TABLES:
            yield json.dumps({"table": table.name, "visibility": "credential-metadata withheld"}) + "\n"
            continue
        ownership = [table.c[key].in_(identifiers) for key in USER_KEY_COLUMNS if key in table.c and key != "opponent_id"]
        columns = [column for column in table.c if column.name not in _PRIVATE_COLUMNS]
        if not columns or not ownership:
            continue
        rows = db.execute(select(*columns).where(or_(*ownership)).order_by(*table.primary_key.columns))
        for row in rows.mappings():
            yield json.dumps({"table": table.name, "record": _finite_json(jsonable_encoder(dict(row)))}, allow_nan=False) + "\n"


def _finite_json(value):
    if isinstance(value, float) and not isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _finite_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_finite_json(item) for item in value]
    return value


def erase_subject(db: Session, provider: str, identifier: str, settings: Settings) -> dict:
    identifiers = subject_identifiers(db, provider, identifier)
    for subject in sorted(identifiers):
        lock_learner_record(db, subject)
    if provider == "guest":
        db.execute(_insert_for(db)(LearnerGuestRevocation).values(credential_digest=guest_credential_digest(identifier))
                   .on_conflict_do_nothing(index_elements=["credential_digest"]))
        db.execute(delete(GuestRevocation).where(GuestRevocation.guest_id == identifier))

    deleted_total = sum(sum(erase_user(db, subject).values()) for subject in identifiers)
    zero_counts = {}
    for table in user_keyed_tables():
        columns = [table.c[key] for key in USER_KEY_COLUMNS if key in table.c]
        count = db.scalar(select(func.count()).select_from(table).where(or_(*(column.in_(identifiers) for column in columns))))
        if count:
            raise RuntimeError(f"Erasure verification failed for {table.name}.")
        zero_counts[table.name] = 0

    package = get_config_package(settings)
    gateway = package.gateway
    registry = () if gateway is None else gateway.registries.get(settings.environment.lower(), gateway.registries["default"])
    table_digest = canonical_sha256(sorted(zero_counts))
    receipt = {
        "id": f"erasure-{uuid4().hex}",
        "timestamp": datetime.now(UTC).isoformat(),
        "consent_version": CONSENT_VERSION,
        "zero_counts": zero_counts,
        "table_set_sha256": table_digest,
        "package_version": package.package_version,
        "package_sha256": package.sha256,
        "gateway_registry": [adapter.adapter_id for adapter in registry],
        "scope": {
            "response_ledger": "retained and unlinkable after tutor-turn erasure",
            "evidential_cache": "holds no learner data",
            "external_processing": "historical egress unverified; external processors are outside this erasure",
            "identity_provider": "account retained at issuer",
            "backups": "deleted rows may remain through the backup window",
            "support_requests": "independently submitted records follow their support retention rule",
        },
    }
    db.add(LearnerErasureAudit(
        id=receipt["id"], receipt_digest=canonical_sha256(receipt), table_set_digest=table_digest,
        deleted_total=deleted_total,
    ))
    db.flush()
    return receipt
