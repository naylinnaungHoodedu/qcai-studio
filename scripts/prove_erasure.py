"""Build a repeatable Phase 8 erasure proof on synthetic SQLite data."""

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
if __name__ == "__main__":
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text, create_engine, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.config_package import canonical_sha256
from app.core.guest_tokens import guest_csrf_for, issue_guest_token
from app.core.schema_upgrades import run_schema_upgrades
from app.db_models import Base, GuestLegacyUpgrade, LearnerErasureAudit, LearnerRecord
from app.services.erasure import USER_KEY_COLUMNS, user_keyed_tables
from app.services.learner_record_privacy import erase_subject
from app.services.learner_record_identity import bind_subject, claim_guest, find_subject


def _value(column):
    kind = column.type
    if isinstance(kind, DateTime):
        return datetime(2026, 1, 1, tzinfo=UTC)
    if isinstance(kind, Boolean):
        return False
    if isinstance(kind, Integer):
        return 1
    if isinstance(kind, Float):
        return 1.0
    if isinstance(kind, JSON):
        return {}
    if isinstance(kind, (String, Text)):
        value = f"synthetic-{uuid4().hex}"
        return value[:kind.length] if kind.length else value
    raise TypeError(f"Unsupported fixture column {column.table.name}.{column.name}")


def _seed(db, subject, *, existing=None, exclude=()):
    covered = {table.name for table in user_keyed_tables()}
    keys = dict(existing or {})
    for table in Base.metadata.sorted_tables:
        if table.name in keys or table.name in exclude:
            continue
        if table.name not in covered and not any(fk.column.table.name in keys for fk in table.foreign_keys):
            continue
        values = {}
        for column in table.columns:
            if column.primary_key and isinstance(column.type, Integer) and not column.foreign_keys:
                continue
            if column.name in USER_KEY_COLUMNS:
                values[column.name] = subject
            elif column.foreign_keys:
                fk = next(iter(column.foreign_keys))
                values[column.name] = keys[fk.column.table.name][fk.column.name]
            else:
                values[column.name] = _value(column)
        result = db.execute(table.insert().values(**values))
        keys[table.name] = dict(zip((column.name for column in table.primary_key.columns), result.inserted_primary_key))
    return keys


def _present(db, keys):
    return sorted(name for name, pk in keys.items() if db.execute(
        select(1).select_from(Base.metadata.tables[name]).where(
            *(Base.metadata.tables[name].c[key] == value for key, value in pk.items())
        )
    ).scalar_one_or_none() is not None)


def independently_remaining(db, identifiers):
    return sorted(
        table.name for table in user_keyed_tables()
        if db.scalar(select(func.count()).select_from(table).where(or_(*(
            table.c[name].in_(identifiers) for name in USER_KEY_COLUMNS if name in table.c
        ))))
    )


def seed_bound(db, provider, principal):
    subject = bind_subject(db, provider, principal)
    raw = _seed(db, principal, exclude={"learner_subjects", "guest_revocations"})
    binding_key = db.scalar(select(Base.metadata.tables["learner_subjects"].c.principal_digest).where(
        Base.metadata.tables["learner_subjects"].c.user_id == subject
    ))
    bound = _seed(db, subject, existing={
        "learner_records": {"user_id": subject}, "learner_subjects": {"principal_digest": binding_key},
    }, exclude={"guest_revocations"})
    return subject, raw, bound


def seed_claimed(db, settings, principal):
    # A valid claim cannot start with a public guest record or a revoked credential.
    guest = f"guest-{uuid4()}"
    db.add_all([GuestLegacyUpgrade(guest_id=guest), LearnerRecord(user_id=guest, mastery={"fixture": 0.4})])
    db.flush()
    now = int(time.time())
    claim_guest(db, "local", principal, issue_guest_token(settings.guest_token_secret, guest, now),
                guest_csrf_for(settings.guest_token_secret, guest, now), settings)
    return guest


def compute():
    settings = Settings(_env_file=None, environment="development", database_url="sqlite:///:memory:")
    scenarios = {}
    for scenario in ("local", "guest", "auth0", "demo", "bound-local", "claimed-local"):
        provider = scenario.split("-")[-1]
        engine = create_engine("sqlite:///:memory:")
        try:
            Base.metadata.create_all(engine)
            run_schema_upgrades(engine)
            with Session(engine, autoflush=False) as db:
                subject = f"{provider}-{uuid4().hex}"
                if scenario == "claimed-local":
                    guest = seed_claimed(db, settings, subject)
                    assert find_subject(db, "local", subject)
                else:
                    guest = None
                if scenario in {"bound-local", "claimed-local"}:
                    bound, raw_rows, bound_rows = seed_bound(db, provider, subject)
                    snapshots = (raw_rows, bound_rows)
                else:
                    bound = None
                    snapshots = (_seed(db, subject, exclude={"guest_revocations"} if provider != "guest" else ()),)
                controls = _seed(db, f"{provider}-{uuid4().hex}")
                db.commit()
                receipt = erase_subject(db, provider, subject, settings)
                db.commit()
                persisted = db.get(LearnerErasureAudit, receipt["id"])
                owned = tuple(identifier for identifier in (subject, bound, guest) if identifier is not None)
                remaining = set(independently_remaining(db, owned))
                remaining.update(table for rows in snapshots for table in _present(db, rows))
                scenarios[scenario] = {
                    "seeded_rows": sum(map(len, snapshots)), "remaining_tables": sorted(remaining),
                    "control_tables": len(controls), "control_tables_remaining": len(_present(db, controls)),
                    "zero_counts": receipt["zero_counts"],
                    "receipt_verified": persisted.receipt_digest == canonical_sha256(receipt),
                    "table_set_sha256": receipt["table_set_sha256"],
                }
        finally:
            engine.dispose()
    return {"format": "phase8-synthetic-erasure-proof-v1", "scenarios": scenarios}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", type=Path)
    mode.add_argument("--check", type=Path)
    args = parser.parse_args()
    if args.write and subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip():
        print("Refused: commit the build before generating the proof.", file=sys.stderr)
        return 4
    proof = compute()
    if any(
        scenario["remaining_tables"] or not scenario["receipt_verified"]
        or scenario["control_tables_remaining"] != scenario["control_tables"]
        for scenario in proof["scenarios"].values()
    ):
        print("Erasure proof failed.", file=sys.stderr)
        return 3
    if args.check:
        if proof != json.loads(args.check.read_text(encoding="utf-8")):
            print("Erasure proof drifted.", file=sys.stderr)
            return 1
        print("Erasure proof is current.")
    else:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print("Erasure proof written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
