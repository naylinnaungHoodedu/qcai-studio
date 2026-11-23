"""The V3 queue and the adjudication workflow (plan Phase 6 D tasks 2-3 "Workflow queued -> claimed -> adjudicated ->
applied; append-only gold store; 10% double review"; plan 16.1 "the X6 auditor MUST NOT audit their own change [Risk
R-35]"; AC-6-3, AC-6-4; Phase 6 spec 4.5; PD-36).

Items. One item per (ledger record, claim) or per record (claim_key ""), id item_id_for(ledger_seq, claim_key).
upsert_item inserts a new item (state queued, round 1, the double-review draw on its id, its severity, exposure, K and
priority) or merges a later trigger into it under a row lock: the unions of triggers, reasons, types and held, severity
and priority recomputed; it never writes state, review_round, closed_at or final_gold_seq, so a concurrent adjudication
is never undone, and a trigger on a closed item is recorded and the item is not reopened (v3.trigger_after_close).
Exposure is the record's (priority.exposure_for): an item created before the scan considered its record (an X3 flag)
counts the deliveries considered so far, and refresh_exposure, which the scan runs once it has drawn the record (every
earlier delivery considered), raises it to the full count. On PostgreSQL the flag takes the scan's advisory lock first
(feedback.record_flag), so it never counts while a scan's draws are uncommitted; on SQLite the writers serialise. The
final exposure and priority therefore never depend on which path created the item.

Workflow. "claimed" is derived: a queued item whose current round has a live lease (v3_claims, user-keyed). claim_item
takes a 30-minute lease (idempotent for its holder; an expired lease is replaced). adjudicate appends exactly one gold row
(gold.append_gold) and changes no ledger row; round 1 closes the item unless it was drawn for double review (1/10), when
round 2 needs another reviewer; a round 2 that agrees closes it, one that disagrees goes to a third reviewer, whose round
3 is final. apply_item exports the final label as recalibration input: it is allowed to a reviewer with no round on the
item, edits no ledger row and no verdict and releases nothing (DI-93). Independence and apply are judged on the
user-keyed round records in v3_claims, never on a keyed digest, which rotates with the guest secret (conflict 28). An
item whose claims cannot all be shown (a span that is not public and quotable, or a record that does not parse) is not
reviewable: it cannot be claimed or adjudicated and stays queued and held (plan J). Every mutation that retries does so
as a whole transaction on an IntegrityError, a serialization failure or a deadlock, or on SQLite (development) a
"database is locked" error from two writers that both began deferred transactions (at most 5 attempts; then V3Busy,
which the routes answer 503).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from fractions import Fraction
import hashlib
import logging
from typing import Any, NamedTuple

from sqlalchemy import delete, insert, select, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.client_identity import keyed_digest
from app.core.structured_logging import FIELDS
from app.services.tutor_pipeline.contracts import sha256_hex
from app.services.v3.contracts import AdjudicationRequest, ApplyRequest, GoldClaim, GoldLabel
from app.services.v3.draw import bernoulli, claim_set_key
from app.services.v3.priority import exposure_for, priority, severity
from app.services.v3.rules import DELIVERIES, DOUBLE_REVIEW_PURPOSE

LOGGER = logging.getLogger("qcai.v3")
CONFLICTS = ("claimed_by_another", "not_claimed", "lease_expired", "independent_review_required", "already_adjudicated", "not_adjudicated",
             "adjudicator_cannot_apply", "labels_do_not_match_subject", "not_recorded_yet", "not_reviewable")
RETRYABLE_SQLSTATES = frozenset({"40001", "40P01"})
BUSY_MESSAGES = ("database is locked", "database is busy", "database table is locked")
ATTEMPTS = 5


class V3NotFound(LookupError):
    """A missing item, or a flag's turn that is missing or someone else's."""


class V3Busy(RuntimeError):
    """A V3 write that could not complete within its attempts (a database that stayed locked or kept conflicting)."""


class V3Conflict(RuntimeError):
    def __init__(self, reason: str) -> None:
        if reason not in CONFLICTS:
            raise ValueError(f"unknown V3 conflict {reason!r}")
        super().__init__(reason)
        self.reason = reason


class Applied(NamedTuple):
    final_gold_seq: int
    duplicate: bool                     # the same client key again: nothing written


class Adjudicated(NamedTuple):
    gold_seq: int
    record_hash: str
    duplicate: bool
    review_round: int
    state: str


@dataclass(frozen=True)
class Lease:
    item_id: str
    review_round: int
    lease_expires_at: datetime


def _log(level: int, message: str, event: str, **fields: Any) -> None:
    LOGGER.log(level, message, extra={FIELDS: {"event": event, **fields}})


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def iso(value: datetime) -> str:
    return utc(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def split(value: str | None) -> frozenset[str]:
    return frozenset(part for part in (value or "").split(",") if part)


def join(values: Iterable[str]) -> str:
    return ",".join(sorted(set(values)))


def item_id_for(ledger_seq: int, claim_key: str) -> str:
    return "v3i-" + hashlib.sha256(f"{int(ledger_seq)}|{claim_key}".encode("utf-8")).hexdigest()[:24]


def response_digest(response_id: str) -> str:
    return keyed_digest(response_id, "v3-response")


def reviewer_digest(user_id: str) -> str:
    return keyed_digest(user_id, "v3-reviewer")


def _dialect(db: Session):
    return postgresql if db.get_bind().dialect.name == "postgresql" else sqlite


def _sqlstate(exc: BaseException) -> str | None:
    from app.services.ledger import sqlstate

    return sqlstate(exc)


def sqlite_busy(exc: BaseException) -> bool:
    """A SQLite "database is locked" or "busy" error: it carries no SQLSTATE, and a retry of the whole transaction waits
    for the other writer through the busy timeout."""
    import sqlite3

    if not isinstance(exc, OperationalError):
        return False
    original = getattr(exc, "orig", None)
    text = str(original).lower()
    return isinstance(original, sqlite3.OperationalError) and any(word in text for word in BUSY_MESSAGES)


def _retrying(db: Session, body):
    """Run body() as one transaction, retried on an IntegrityError, a serialization failure, a deadlock or a SQLite
    busy error; V3Busy once the attempts are spent."""
    last: Exception | None = None
    for _ in range(ATTEMPTS):
        try:
            result = body()
            db.commit()
            return result
        except IntegrityError as exc:
            db.rollback()
            last = exc
            continue
        except DBAPIError as exc:
            db.rollback()
            if _sqlstate(exc) in RETRYABLE_SQLSTATES or sqlite_busy(exc):
                last = exc
                continue
            raise
        except Exception:
            db.rollback()
            raise
    raise V3Busy("the V3 queue write could not complete within its attempts") from last


def _item(db: Session, item_id: str, *, lock: bool = False) -> Any:
    from app.db_models import V3QueueItem

    query = select(V3QueueItem.__table__).where(V3QueueItem.item_id == item_id)
    if lock:
        query = query.with_for_update()
    return db.execute(query).first()


def record_row(db: Session, ledger_seq: int) -> Any:
    from app.db_models import ResponseLedgerRecord

    return db.execute(select(ResponseLedgerRecord.__table__).where(ResponseLedgerRecord.seq == int(ledger_seq))).first()


def parse_entry(row: Any) -> Any:
    """The validated ledger entry of a response_ledger row, or None when its schema is unknown or it fails."""
    from pydantic import ValidationError

    from app.services.tutor_pipeline.contracts import ENTRY_SCHEMAS

    if row is None:
        return None
    model = ENTRY_SCHEMAS.get(row.entry_schema)
    if model is None:
        return None
    try:
        return model.model_validate_json(row.entry)
    except (ValidationError, ValueError):
        return None


# ------------------------------------------------------------------------------------------------------- items


def upsert_item(db: Session, *, record_row: Any, spec: Any, entry: Any, package: Any, now: datetime) -> tuple[str, bool]:
    """Insert or merge one item inside the caller's transaction; returns (item_id, created)."""
    from app.db_models import V3QueueItem

    v3 = package.v3
    item_id = item_id_for(record_row.seq, spec.claim_key)
    existing = _item(db, item_id, lock=True)
    if existing is None:
        sev = severity(spec.ehmf_types, v3.severity)
        exposure = exposure_for(db, record_row, claim_set_key(entry))
        value = priority(sev, exposure, spec.k)
        statement = _dialect(db).insert(V3QueueItem).values(
            item_id=item_id, ledger_seq=int(record_row.seq), claim_key=spec.claim_key, subject=spec.subject,
            record_kind="shadow" if record_row.delivery == "shadow" else "delivery", response_digest=response_digest(record_row.response_id),
            triggers=join(spec.triggers), reasons=join(spec.reasons), ehmf_types=join(spec.ehmf_types), held=bool(spec.held),
            severity=float(sev), exposure=int(exposure), k=float(spec.k), priority=float(value), state="queued", review_round=1,
            double_review=bernoulli(DOUBLE_REVIEW_PURPOSE, v3.draw_seed, item_id, v3.double_review_rate), enqueued_at=utc(now),
            package_version=package.package_version, package_sha256=package.sha256,
        ).on_conflict_do_nothing(index_elements=["item_id"]).returning(V3QueueItem.item_id)
        # RETURNING says whether the row was inserted, whatever rowcount a driver reports for this statement.
        if db.execute(statement).first() is not None:
            return item_id, True
        existing = _item(db, item_id, lock=True)
    triggers = split(existing.triggers) | set(spec.triggers)
    reasons = split(existing.reasons) | set(spec.reasons)
    types = split(existing.ehmf_types) | set(spec.ehmf_types)
    held = bool(existing.held) or bool(spec.held)
    changed = (triggers != split(existing.triggers) or reasons != split(existing.reasons) or types != split(existing.ehmf_types)
               or held != bool(existing.held))
    if changed:
        sev = severity(types, v3.severity)
        k = Fraction(existing.k).limit_denominator(10**6)
        db.execute(update(V3QueueItem).where(V3QueueItem.item_id == item_id).values(
            triggers=join(triggers), reasons=join(reasons), ehmf_types=join(types), held=held, severity=float(sev),
            priority=float(priority(sev, int(existing.exposure), k))))
        if existing.state != "queued":
            _log(logging.INFO, "A trigger reached a closed V3 item; it is recorded and not reopened", "v3.trigger_after_close",
                 item_id=item_id, triggers=sorted(triggers))
    return item_id, False


def refresh_exposure(db: Session, *, record_row: Any, entry: Any, package: Any) -> int:
    """Raise every item of the record whose stored exposure is below the record's (priority.exposure_for) to it, with its
    priority recomputed; inside the caller's transaction. The scan runs it once it has drawn the record, when every
    earlier delivery has been considered, so the count is final. Returns the items raised."""
    from app.db_models import V3QueueItem

    exposure = exposure_for(db, record_row, claim_set_key(entry))
    query = select(V3QueueItem.__table__).where(V3QueueItem.ledger_seq == int(record_row.seq), V3QueueItem.exposure < exposure)
    raised = 0
    for item in db.execute(query.with_for_update()).all():
        sev = severity(split(item.ehmf_types), package.v3.severity)
        k = Fraction(item.k).limit_denominator(10**6)
        db.execute(update(V3QueueItem).where(V3QueueItem.item_id == item.item_id).values(exposure=int(exposure),
                                                                                         priority=float(priority(sev, exposure, k))))
        raised += 1
    return raised


def live_lease(db: Session, item: Any, *, now: datetime) -> Any:
    from app.db_models import V3Claim

    row = db.execute(select(V3Claim.__table__).where(V3Claim.item_id == item.item_id, V3Claim.review_round == item.review_round,
                                                     V3Claim.adjudicated_at.is_(None))).first()
    if row is not None and utc(row.lease_expires_at) > utc(now):
        return row
    return None


def workflow_state(db: Session, item: Any, *, now: datetime) -> str:
    if item.state == "queued" and live_lease(db, item, now=now) is not None:
        return "claimed"
    return item.state


def list_queue(db: Session, *, state: str | None = None, limit: int = 50, now: datetime, item_ids: Iterable[str] | None = None) -> list[Any]:
    """Items in queue order (priority descending, then enqueued_at, then item_id). state None is queued with claimed."""
    from app.db_models import V3QueueItem

    stored = "queued" if state in (None, "queued", "claimed") else state
    query = select(V3QueueItem.__table__).where(V3QueueItem.state == stored)
    if item_ids is not None:
        query = query.where(V3QueueItem.item_id.in_(list(item_ids)))
    query = query.order_by(V3QueueItem.priority.desc(), V3QueueItem.enqueued_at.asc(), V3QueueItem.item_id.asc())
    rows = []
    for row in db.execute(query):
        if state in ("queued", "claimed") and workflow_state(db, row, now=now) != state:
            continue
        rows.append(row)
        if len(rows) >= int(limit):
            break
    return rows


def get_item(db: Session, item_id: str) -> Any:
    return _item(db, item_id)


def subject_claims(item: Any, entry: Any) -> tuple | None:
    """The recorded claims an item covers, sorted by claim id: its one claim, or every claim of its record; None when the
    record does not parse or does not hold the item's claim."""
    if entry is None:
        return None
    claims = sorted(entry.claims, key=lambda claim: claim.claim_id)
    if item.subject == "claim":
        claims = [claim for claim in claims if claim.claim_id == item.claim_key]
        if len(claims) != 1:
            return None
    return tuple(claims)


def span_shown(span_id: str, *, store: Any, corpus_registry: Any) -> tuple[bool, str | None]:
    from app.services.contained_answers import span_is_quotable

    record = store.span_registry.get(span_id)
    if record is not None and record.plane == "public" and span_is_quotable(record, corpus_registry):
        return True, record.text
    return False, None


def reviewable(item: Any, entry: Any, *, store: Any, corpus_registry: Any) -> bool:
    claims = subject_claims(item, entry)
    if claims is None:
        return False
    return all(span_shown(span_id, store=store, corpus_registry=corpus_registry)[0] for claim in claims for span_id in claim.span_ids)


def _defaults(store: Any, corpus_registry: Any) -> tuple[Any, Any]:
    if store is None:
        from app.services.store import get_course_store

        store = get_course_store()
    if corpus_registry is None:
        from app.core.config import get_settings
        from app.core.corpus_governance import get_corpus_registry

        corpus_registry = get_corpus_registry(get_settings())
    return store, corpus_registry


# ---------------------------------------------------------------------------------------------------- workflow


def claim_item(db: Session, item_id: str, *, user_id: str, now: datetime, package: Any, store: Any = None, corpus_registry: Any = None) -> Lease:
    from app.db_models import V3Claim

    store, corpus_registry = _defaults(store, corpus_registry)
    lease_s = int(package.v3.lease_s)

    def body() -> Lease:
        item = _item(db, item_id, lock=True)
        if item is None:
            raise V3NotFound(item_id)
        if item.state != "queued":
            raise V3Conflict("already_adjudicated")
        if not reviewable(item, parse_entry(record_row(db, item.ledger_seq)), store=store, corpus_registry=corpus_registry):
            raise V3Conflict("not_reviewable")
        reviewed = db.execute(select(V3Claim.id).where(V3Claim.item_id == item_id, V3Claim.user_id == user_id,
                                                       V3Claim.adjudicated_at.is_not(None))).first()
        if reviewed is not None:
            raise V3Conflict("independent_review_required")
        current = db.execute(select(V3Claim.__table__).where(V3Claim.item_id == item_id, V3Claim.review_round == item.review_round)).first()
        if current is not None:
            if utc(current.lease_expires_at) > utc(now):
                if current.user_id != user_id:
                    raise V3Conflict("claimed_by_another")
                return Lease(item_id=item_id, review_round=int(item.review_round), lease_expires_at=utc(current.lease_expires_at))
            db.execute(delete(V3Claim).where(V3Claim.id == current.id))
        expires = utc(now) + timedelta(seconds=lease_s)
        db.execute(insert(V3Claim).values(item_id=item_id, review_round=int(item.review_round), user_id=user_id, claimed_at=utc(now),
                                          lease_expires_at=expires, adjudicated_at=None))
        return Lease(item_id=item_id, review_round=int(item.review_round), lease_expires_at=expires)

    return _retrying(db, body)


def _labels_match(item: Any, entry: Any, claims: tuple, request: AdjudicationRequest) -> bool:
    labelled = [label.claim_id for label in request.claim_labels]
    if labelled != [claim.claim_id for claim in claims]:
        return False
    if item.subject == "claim":
        return request.abstention_label is None
    return (request.abstention_label is not None) == (entry.decision == "abstain")


def _round_labels(db: Session, item_id: str, review_round: int) -> tuple | None:
    import json

    from app.db_models import V3GoldLabelRecord

    row = db.execute(select(V3GoldLabelRecord.entry).where(V3GoldLabelRecord.item_id == item_id, V3GoldLabelRecord.review_round == review_round)).first()
    if row is None:
        return None
    entry = json.loads(row.entry)
    return entry.get("claim_labels"), entry.get("abstention_label")


def adjudicate(db: Session, item_id: str, request: AdjudicationRequest, *, user_id: str, now: datetime, package: Any, store: Any = None,
               corpus_registry: Any = None) -> Adjudicated:
    import json

    from app.db_models import V3Claim, V3GoldLabelRecord, V3QueueItem
    from app.services.v3.gold import append_gold

    store, corpus_registry = _defaults(store, corpus_registry)
    appended: dict[str, Any] = {}

    def body() -> Adjudicated:
        item = _item(db, item_id, lock=True)
        if item is None:
            raise V3NotFound(item_id)
        mine = {row.review_round for row in db.execute(select(V3Claim.review_round).where(V3Claim.item_id == item_id, V3Claim.user_id == user_id))}
        for row in db.execute(select(V3GoldLabelRecord.seq, V3GoldLabelRecord.record_hash, V3GoldLabelRecord.review_round,
                                     V3GoldLabelRecord.entry).where(V3GoldLabelRecord.item_id == item_id)):
            if row.review_round in mine and json.loads(row.entry).get("client_key") == request.client_key:
                return Adjudicated(int(row.seq), row.record_hash, True, int(row.review_round), item.state)
        if item.state != "queued":
            raise V3Conflict("already_adjudicated")
        lease = db.execute(select(V3Claim.__table__).where(V3Claim.item_id == item_id, V3Claim.review_round == item.review_round,
                                                           V3Claim.user_id == user_id, V3Claim.adjudicated_at.is_(None))).first()
        if lease is None:
            raise V3Conflict("not_claimed")
        if utc(lease.lease_expires_at) <= utc(now):
            raise V3Conflict("lease_expired")
        record = record_row(db, item.ledger_seq)
        entry = parse_entry(record)
        if not reviewable(item, entry, store=store, corpus_registry=corpus_registry):
            raise V3Conflict("not_reviewable")
        claims = subject_claims(item, entry)
        if not _labels_match(item, entry, claims, request):
            raise V3Conflict("labels_do_not_match_subject")
        delivered = record.delivery in DELIVERIES
        delivery_id = record.response_id if delivered else record.shadowed_response_id
        label = GoldLabel(
            item_id=item_id, review_round=int(item.review_round), subject=item.subject, triggers=tuple(sorted(split(item.triggers))),
            reasons=tuple(sorted(split(item.reasons))), ledger_seq=int(item.ledger_seq), response_digest=item.response_digest,
            delivery_digest=response_digest(delivery_id or record.response_id),
            delivered_answer=delivered and record.decision == "answer",
            claims=tuple(GoldClaim(claim_id=claim.claim_id, span_ids=tuple(claim.span_ids), text_sha256=sha256_hex(claim.text)) for claim in claims),
            claim_labels=request.claim_labels, abstention_label=request.abstention_label,
            residual_error=(delivered and record.decision == "answer" and any(label.verdict != "SUPPORTED" for label in request.claim_labels)),
            reviewer_digest=reviewer_digest(user_id), client_key=request.client_key, package_version=package.package_version,
            package_sha256=package.sha256, adjudicated_at=iso(now),
        )
        seq, record_hash = append_gold(db, label, now=now)
        db.execute(update(V3Claim).where(V3Claim.id == lease.id).values(adjudicated_at=utc(now)))
        round_ = int(item.review_round)
        labels = ([entry_label.model_dump(mode="json") for entry_label in request.claim_labels], request.abstention_label)
        agreement = None
        if round_ == 1:
            closes = not item.double_review
        elif round_ == 2:
            previous = _round_labels(db, item_id, 1)
            agreement = previous is not None and (previous[0], previous[1]) == labels
            closes = agreement
        else:
            closes = True
        if closes:
            values = {"state": "adjudicated", "closed_at": utc(now), "final_gold_seq": seq}
            state = "adjudicated"
        else:
            values = {"review_round": round_ + 1}
            state = "queued"
        db.execute(update(V3QueueItem).where(V3QueueItem.item_id == item_id).values(**values))
        appended.update(seq=seq, record_hash=record_hash, round=round_, subject=item.subject, state=state, agreement=agreement)
        return Adjudicated(seq, record_hash, False, round_, state)

    result = _retrying(db, body)
    if not result.duplicate:
        fields = {"item_id": item_id, "review_round": appended["round"], "subject": appended["subject"], "state": appended["state"]}
        if appended["round"] == 2:
            fields["agreement"] = bool(appended["agreement"])
        _log(logging.INFO, "V3 gold row appended", "v3.gold_appended", seq=appended["seq"], record_hash=appended["record_hash"])
        _log(logging.INFO, "V3 item adjudicated", "v3.adjudicated", **fields)
    return result


def apply_item(db: Session, item_id: str, request: ApplyRequest, *, user_id: str, now: datetime) -> Applied:
    from app.db_models import V3Claim, V3QueueItem

    def body() -> Applied:
        item = _item(db, item_id, lock=True)
        if item is None:
            raise V3NotFound(item_id)
        if item.state == "applied" and item.applied_client_key == request.client_key:
            return Applied(int(item.final_gold_seq), True)
        if item.state != "adjudicated":
            raise V3Conflict("not_adjudicated")
        adjudicator = db.execute(select(V3Claim.id).where(V3Claim.item_id == item_id, V3Claim.user_id == user_id,
                                                          V3Claim.adjudicated_at.is_not(None))).first()
        if adjudicator is not None:
            raise V3Conflict("adjudicator_cannot_apply")
        db.execute(update(V3QueueItem).where(V3QueueItem.item_id == item_id, V3QueueItem.state == "adjudicated").values(
            state="applied", applied_at=utc(now), applied_by_digest=reviewer_digest(user_id), applied_client_key=request.client_key))
        return Applied(int(item.final_gold_seq), False)

    result = _retrying(db, body)
    if not result.duplicate:
        _log(logging.INFO, "V3 item applied", "v3.applied", item_id=item_id, final_gold_seq=result.final_gold_seq)
    return result

