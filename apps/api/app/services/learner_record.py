"""Convergent learner-record operations for the CS595 engineering increment.

The API accepts append-only, idempotent operations.  The materialized state is an
implementation of the merge rules specified in RevB §6.1: max-register mastery,
set-union completions, grow-only per-replica attempt counters, and logical-clock
last-writer-wins cursor/preferences.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import LearnerRecord, LearnerRecordOperation, LearnerReplica
from app.schemas import LearnerRecordOperationInput, LearnerRecordRead


_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,255}$")


def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _require_identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid {field}.")
    return value


def _payload_hash(operation: LearnerRecordOperationInput) -> str:
    payload = {
        "replica_id": operation.replica_id,
        "logical_counter": operation.logical_counter,
        "causal_vector": operation.causal_vector,
        "operation_type": operation.operation_type,
        "payload": operation.payload,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _clock_tuple(value: object) -> tuple[int, str]:
    envelope = _as_dict(value)
    counter = envelope.get("logical_counter", 0)
    replica_id = envelope.get("replica_id", "")
    return (counter if isinstance(counter, int) and counter >= 0 else 0, replica_id if isinstance(replica_id, str) else "")


def _wins(existing: object, counter: int, replica_id: str) -> bool:
    return (counter, replica_id) > _clock_tuple(existing)


def _record_for_user(db: Session, user_id: str) -> LearnerRecord:
    record = db.get(LearnerRecord, user_id)
    if record is None:
        record = LearnerRecord(user_id=user_id)
        db.add(record)
        db.flush()
    return record


def _replica_for_operation(db: Session, user_id: str, replica_id: str, logical_counter: int) -> LearnerReplica:
    replica = db.scalar(
        select(LearnerReplica).where(LearnerReplica.user_id == user_id, LearnerReplica.replica_id == replica_id)
    )
    if replica is None:
        replica = LearnerReplica(
            user_id=user_id,
            replica_id=replica_id,
            last_logical_counter=logical_counter,
        )
        db.add(replica)
        # SessionLocal intentionally disables autoflush; persist the replica now so
        # later operations in the same batch observe its unique identity.
        db.flush()
    else:
        replica.last_logical_counter = max(replica.last_logical_counter, logical_counter)
    return replica


def _apply_payload(record: LearnerRecord, operation: LearnerRecordOperationInput) -> None:
    payload = _as_dict(operation.payload)
    mastery = _as_dict(record.mastery)
    completed_items = set(item for item in _as_list(record.completed_items) if isinstance(item, str))
    counters = _as_dict(record.attempt_counters)
    cursor = _as_dict(record.cursor)
    preferences = _as_dict(record.preferences)

    if operation.operation_type == "mastery_set":
        skill_id = _require_identifier(payload.get("skill_id"), "skill_id")
        value = payload.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= float(value) <= 1:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Mastery value must be between 0 and 1.")
        mastery[skill_id] = max(float(mastery.get(skill_id, 0.0) or 0.0), round(float(value), 6))

    elif operation.operation_type == "complete_item":
        completed_items.add(_require_identifier(payload.get("item_id"), "item_id"))

    elif operation.operation_type == "increment_attempt":
        item_id = _require_identifier(payload.get("item_id"), "item_id")
        delta = payload.get("delta", 1)
        if not isinstance(delta, int) or isinstance(delta, bool) or not 1 <= delta <= 100:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Attempt increment must be a positive integer.")
        item_components = _as_dict(counters.get(item_id))
        current = item_components.get(operation.replica_id, 0)
        if not isinstance(current, int) or current < 0:
            current = 0
        item_components[operation.replica_id] = current + delta
        counters[item_id] = item_components

    elif operation.operation_type == "set_cursor":
        value = payload.get("value")
        if not isinstance(value, str) or not value.strip() or len(value) > 1024:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Cursor value is invalid.")
        if _wins(cursor, operation.logical_counter, operation.replica_id):
            cursor = {
                "value": value.strip(),
                "logical_counter": operation.logical_counter,
                "replica_id": operation.replica_id,
            }

    elif operation.operation_type == "set_preference":
        key = _require_identifier(payload.get("key"), "preference key")
        value = payload.get("value")
        if isinstance(value, (dict, list)) or value is None or len(json.dumps(value)) > 1024:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Preference value is invalid.")
        existing = preferences.get(key)
        if _wins(existing, operation.logical_counter, operation.replica_id):
            preferences[key] = {
                "value": value,
                "logical_counter": operation.logical_counter,
                "replica_id": operation.replica_id,
            }

    record.mastery = mastery
    record.completed_items = sorted(completed_items)
    record.attempt_counters = counters
    record.cursor = cursor
    record.preferences = preferences


def materialize_record(record: LearnerRecord) -> LearnerRecordRead:
    counters = _as_dict(record.attempt_counters)
    attempt_counts = {
        item_id: sum(value for value in _as_dict(components).values() if isinstance(value, int) and value >= 0)
        for item_id, components in counters.items()
        if isinstance(item_id, str)
    }
    raw_preferences = _as_dict(record.preferences)
    preferences = {
        key: _as_dict(value).get("value")
        for key, value in raw_preferences.items()
        if isinstance(key, str) and "value" in _as_dict(value)
    }
    raw_cursor = _as_dict(record.cursor)
    cursor_value = raw_cursor.get("value") if isinstance(raw_cursor.get("value"), str) else None
    return LearnerRecordRead(
        user_id=record.user_id,
        record_version=record.record_version,
        mastery={key: float(value) for key, value in _as_dict(record.mastery).items() if isinstance(value, (int, float))},
        completed_item_ids=sorted(item for item in _as_list(record.completed_items) if isinstance(item, str)),
        attempt_counts=attempt_counts,
        cursor=cursor_value,
        preferences=preferences,
        version_vector={
            key: value for key, value in _as_dict(record.version_vector).items() if isinstance(key, str) and isinstance(value, int)
        },
    )


def read_learner_record(db: Session, user_id: str) -> LearnerRecordRead:
    return materialize_record(_record_for_user(db, user_id))


def apply_learner_record_operations(
    db: Session,
    user_id: str,
    operations: list[LearnerRecordOperationInput],
) -> tuple[list[dict[str, str]], LearnerRecordRead]:
    record = _record_for_user(db, user_id)
    vector = _as_dict(record.version_vector)
    receipts: list[dict[str, str]] = []
    applied_count = 0

    for operation in operations:
        payload_hash = _payload_hash(operation)
        existing = db.scalar(
            select(LearnerRecordOperation).where(
                LearnerRecordOperation.user_id == user_id,
                LearnerRecordOperation.operation_id == operation.operation_id,
            )
        )
        if existing is not None:
            if existing.payload_hash != payload_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Operation ID was replayed with a different payload.",
                )
            receipts.append({"operation_id": operation.operation_id, "status": "duplicate"})
            continue

        _replica_for_operation(db, user_id, operation.replica_id, operation.logical_counter)
        _apply_payload(record, operation)
        for replica_id, counter in operation.causal_vector.items():
            vector[replica_id] = max(int(vector.get(replica_id, 0) or 0), counter)
        vector[operation.replica_id] = max(int(vector.get(operation.replica_id, 0) or 0), operation.logical_counter)
        db.add(
            LearnerRecordOperation(
                user_id=user_id,
                operation_id=operation.operation_id,
                replica_id=operation.replica_id,
                logical_counter=operation.logical_counter,
                causal_vector=operation.causal_vector,
                operation_type=operation.operation_type,
                payload=operation.payload,
                payload_hash=payload_hash,
            )
        )
        receipts.append({"operation_id": operation.operation_id, "status": "applied"})
        applied_count += 1

    if applied_count:
        record.version_vector = vector
        record.record_version += applied_count
        db.flush()
    return receipts, materialize_record(record)


def build_pedagogical_context(db: Session, user_id: str) -> str:
    """Return style guidance only; this string must never be sent to retrieval."""
    record = read_learner_record(db, user_id)
    scores = list(record.mastery.values())
    if not scores:
        return "Treat the learner as new to this topic: introduce prerequisites before advancing."
    average = sum(scores) / len(scores)
    if average < 0.4:
        return "Use a concise prerequisite recap and one concrete worked explanation."
    if average < 0.75:
        return "Use a direct explanation, then invite the learner to connect it to a prior lesson."
    return "Use concise Socratic prompting and emphasize validation assumptions rather than repeating basics."
