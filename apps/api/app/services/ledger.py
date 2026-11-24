"""The response ledger: an append-only, hash-chained record of every tutor response (plan task 3.8, 7.5; R-22;
Phase 3 spec 4.12).

Each row holds the canonical JSON of a LedgerEntry (every plan 7.4 provenance and version field, unused ones as
explicit nulls), its sha256, the previous row's record hash and its own:
    record_hash = sha256(canonical{chain, seq, created_at, prev_hash, entry_sha256})
so an edited, removed, reordered or truncated row breaks the chain, and verify_response_ledger names where.
Appends key on response_id: a retry with the same entry is a duplicate, a different entry a LedgerConflict.
The chain-head row is locked with SELECT ... FOR UPDATE by every append (SQLite serialises writers), so the chain
stays linear under concurrency; database triggers refuse UPDATE, DELETE and TRUNCATE of records, refuse an insert
that does not extend the chain, and let the head move forward only (app.core.schema_upgrades).

What is recorded (spec R-a): every learner delivery is a legacy contained answer, recorded with delivery "legacy":
a tutor turn with response_id = the TutorTurn id, and a /qa/ask answer with a random qa- id that is stored nowhere
else (plan task 3.8 and F-1 cover every delivered response). A qa- id names no learner, so the asker cannot be
shown the record and only a reviewer reads it. It is not unlinkable while the asker's Q&A history is kept: the
qa_interactions row holds the same answer (rendered_text_sha256 is its sha256), the same cited spans and a time a
few milliseconds earlier, so anyone who can read both tables can match the two (spec 18.6 D10). Erasure, or guest
retention, deletes that row, and the record can then no longer be tied to anyone. Every shadow run of the two-pass
pipeline is recorded with delivery "shadow" and a shadow- id naming the turn it shadowed. "delivered" waits for the
delivered two-pass path (DI-59). A shadow record is a ledger-entry-v1 (V1 off), a ledger-entry-v2 (the V1
verification), a ledger-entry-v3 (the V2 panel's verdicts beside it; Phase 5) or a ledger-entry-v4 (the EHMF typing,
precedence, disclosure and X2 list beside those, in development; Phase 7). Records from the Phase 7 release stamp
configuration package v6; a record's config_version (config_version_of) is its package version from v6 on and
"pre-phase-7" before it (plan Phase 7 G), mapped at read time and never written back.

A legacy record's abstention_reason says why the delivery abstained (plan I "abstention by reason"; spec 18.8 F1):
the retrieval gate's own reason when the gate returned nothing (no_query_terms, no_match, insufficient_coverage,
below_floor), and otherwise no_approved_span: the gate matched passages none of which could be quoted (not approved
under D-31, or not verified), or the Phase 4 legacy guard withheld the contained answer (V1.1, V1.2, or V1.7
conflict_withheld), which its tutor.v1.legacy_guard_withheld line names. Its retrieval.sufficiency is the gate's
decision (retrieve.sufficiency_of). The learner's response and the turn's decision_reason are unchanged.

Each delivery's attempt logs one tutor.ledger.attempted line with its decision, its abstention reason and an
attempt id, and ends in exactly one terminal line with the same attempt id once its append ends:
tutor.ledger.appended (delivery legacy) or tutor.ledger.append_failed (spec 18.8 F11). attempt_horizon_s bounds how
long that takes while the process keeps its CPU, and ledger_coverage counts a turn as lost only once it is older
than that horizon (spec 18.12 J5, J6).

Budgets, attempts and the appender's size come from the shipped configuration package (tutor_pipeline.budgets; PD-11;
v2 with the Phase 3 release, v3 from the Phase 4 release, v4 from the Phase 5 release, v5 from the Phase 6 release, with the
same values).
TUTOR_LEDGER_APPEND_BUDGET_MS and TWO_PASS_SHADOW_BUDGET_MS override the two budgets only; every record stamps
the budgets in force and which of them differ from the package (versions.budgets), so a record names its budgets
whether or not they were overridden (R-46), and an override outside development logs a config.override event.
No retention applies: plan 12.8 is an open decision, the package says "retain" (owner_decisions.PLAN-12.8, DI-45),
no job deletes a row and the triggers refuse DELETE.

No user id and no learner text: the ledger stores corpus text (claims) and hashes only, never the resolved
question or the rendered text. The link to a learner is tutor_turns (and, for a qa- record, the matching
qa_interactions row), which erasure deletes; the rows then remain but cannot be tied to anyone. Every append logs
its seq and record_hash (an off-DB copy of the chain, conflict 6); `python -m app.workers.response_ledger`
verifies the chain and logs the head.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout, wait
import contextvars
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import logging
import math
from pathlib import Path
import random
import threading
import time
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.config_package import ConfigPackage, TutorPipelineParams, canonical_sha256, get_config_package
from app.core.db import CONNECT_TIMEOUT_S, DEAD_PEER_BOUND_S, SessionLocal
from app.core.structured_logging import FIELDS
from app.db_models import ResponseLedgerHead, ResponseLedgerRecord, TutorTurn
from app.services.contained_answers import ABSTENTION, EXTRACTIVE_MODE, MAX_QUOTED_SPANS, QUOTATION_LEAD
from app.services.tutor_pipeline.bind import claim_id_for
from app.services.tutor_pipeline.contracts import (
    ENTRY_SCHEMAS,
    GATE_ABSTENTION_REASONS,
    LEGACY_ABSTENTION_REASON,
    LEGACY_NOT_PUBLIC,
    LEGACY_UNRESOLVED,
    BudgetStamp,
    ClaimLedgerEntry,
    EvidenceSpan,
    LedgerEntry,
    PipelineCounts,
    Provenance,
    RetrievalRecord,
    Sufficiency,
    VersionStamps,
    ledger_canonical,
    sha256_hex,
)
from app.services.tutor_pipeline.metrics import LEDGER_METRICS
from app.services.tutor_pipeline.retrieve import evidence_span_for, sufficiency_of

LOGGER = logging.getLogger("qcai.tutor")
CHAIN = "tutor-responses"
GENESIS_HASH = "0" * 64
# The record-hash rule record_hash_for implements; configuration package v2 names it (tutor_pipeline.ledger.
# record_hash_rule) and package_check requires the two to agree (spec 18.8 F4).
RECORD_HASH_RULE = "sha256(canonical{chain,seq,created_at,prev_hash,entry_sha256})-v1"
# PostgreSQL's deadlock and serialization failures: the attempt's transaction was rolled back whole, so it is
# retried within the remaining budget like an IntegrityError (spec 18.8 F8).
RETRYABLE_SQLSTATES = frozenset({"40P01", "40001"})
# The Alembic revision this code expects (tested against the single head); stamped on every record (plan 13.5).
SCHEMA_REVISION = "20261123_phase9_ranking"
# The legacy contained path's ids and rule hash, stamped on every legacy record (the only records production writes).
# Configuration package v2 pins all four (tutor_pipeline.legacy) and package_check requires them to agree, so the
# provenance audit (ledger_provenance) has a pinned reference value (DI-49).
LEGACY_PIPELINE_VERSION = "legacy-contained-v1"
LEGACY_GENERATOR_ID = "contained-answers-v1"
LEGACY_CONTAINMENT_RULE_HASH = canonical_sha256(
    {
        "id": LEGACY_GENERATOR_ID,
        "mode": EXTRACTIVE_MODE,
        "max_quoted_spans": MAX_QUOTED_SPANS,
        "quotation_lead": QUOTATION_LEAD,
        "abstention": ABSTENTION,
    }
)
_MAX_REPORTED_PROBLEMS = 50


class LedgerConflict(RuntimeError):
    """The response_id is already recorded with a different entry."""


class LedgerAppendError(RuntimeError):
    """The append did not succeed within its attempts or its budget."""


class LedgerRestoreRefused(RuntimeError):
    """restore_ledger refused its input or the database it was given; nothing was written."""


class LedgerUnavailable(RuntimeError):
    """The configuration package has no tutor_pipeline block (package v1), so it pins no ledger parameters."""


def ledger_params(package: ConfigPackage) -> TutorPipelineParams:
    if package.tutor_pipeline is None:
        raise LedgerUnavailable("configuration package v1 pins no ledger schema or budgets; the ledger needs package v2")
    return package.tutor_pipeline


def ledger_budget_ms(settings: Settings, package: ConfigPackage) -> int:
    """TUTOR_LEDGER_APPEND_BUDGET_MS when set, else the package's tutor_pipeline.budgets.ledger_append_ms (PD-11)."""
    if settings.tutor_ledger_append_budget_ms is not None:
        return int(settings.tutor_ledger_append_budget_ms)
    return ledger_params(package).ledger_append_budget_ms


# The terms of the attempt horizon (attempt_horizon_s). app.core.db sets no pool_timeout, so SQLAlchemy's QueuePool
# waits up to its default 30 s for a free connection. A new Cloud SQL connection is bounded by app.core.db's
# CONNECT_TIMEOUT_S (30 s), which its creator enforces. One checkout can take both: a pooled connection that fails
# its pre-ping is replaced by a new one.
POOL_CHECKOUT_TIMEOUT_S = 30
# The statements of one append attempt after its PostgreSQL SET LOCALs, the commit included: the response_id read,
# the head insert-if-missing, the head lock, the record insert, the head update and the commit (append_ledger_entry).
# The server ends each one when the budget left at the start of the attempt runs out (statement, lock and
# idle-in-transaction timeouts).
ATTEMPT_STATEMENTS = 6
# Log ingestion, and the time between a turn's created_at and its attempted line (the turn's own commit).
HORIZON_MARGIN_S = 60
# The reads on an open connection whose peer is gone that one append can meet (dead_peer_horizon_s): a pooled
# connection's pre-ping and one statement.
DEAD_PEER_READS = 2


def attempt_horizon_s(params: TutorPipelineParams, budget_ms: int) -> int:
    """The longest a legacy attempt takes from its tutor.ledger.attempted line to its terminal line, and a tutor turn
    from its created_at to its ledger record, while the process keeps its CPU (always-on CPU allocation). It is the
    runbook's horizon for both checks (infra/cloudrun/deployment.md, Phase 3).

    One append takes at most a connection wait (POOL_CHECKOUT_TIMEOUT_S + CONNECT_TIMEOUT_S) and ATTEMPT_STATEMENTS
    statements of at most the budget each, after earlier attempts that all ended within the budget (a retry starts
    only while budget remains): (ATTEMPT_STATEMENTS + 1) budgets in all. Appends run on ledger_append_workers threads
    with at most ledger_append_max_in_flight running or queued, so an append ends within ceil(max_in_flight /
    workers) such appends. Add HORIZON_MARGIN_S and round up to whole minutes: 360 s with the package's values.

    Each term is enforced by the code or by a library default it keeps, on the Cloud SQL connector path that
    production uses: the pool's checkout timeout, app.core.db's connect bound, and the server's statement, lock and
    idle-in-transaction timeouts. One wait is not in the horizon: a reply on a connection that is already open, which
    the server's timeouts bound only while the server answers (and the pre-ping and the first SET LOCAL run before
    any statement_timeout applies). When the database host or the network to it is gone, the TCP keepalive
    app.core.db sets on each Cloud SQL connection ends the read within DEAD_PEER_BOUND_S of the connection's last
    traffic (dead_peer_horizon_s). When the server keeps the connection up and never replies, nothing in the code
    ends the read: it lasts until the server replies or the process exits, and it holds one of the appender's
    workers meanwhile. An attempt that ends after the horizon on an always-on instance therefore means such a stall,
    and the runbook treats it as a stop; one still without a terminal line after dead_peer_horizon_s is held by a
    server that never replies, and the runbook replaces the instance.

    With request-based CPU allocation nothing bounds it: an append still queued or running when the response has
    gone runs on only when the instance next has CPU (its next request, or its shutdown, when Python runs the queued
    appends before the process exits). The runbook therefore reads a missing terminal line there as a case to
    investigate, and decides by a coverage check run once that instance has stopped.
    """
    return _horizon_s(params, budget_ms, stall_s=0)


def dead_peer_horizon_s(params: TutorPipelineParams, budget_ms: int) -> int:
    """attempt_horizon_s plus DEAD_PEER_READS dead-peer reads in each append: the longest a legacy attempt takes,
    while the process keeps its CPU, when the database host or the network to it is gone. Such a read ends within
    app.core.db.DEAD_PEER_BOUND_S of its connection's last traffic (TCP keepalive on each Cloud SQL connection). An
    append meets at most two: the pre-ping of a pooled connection, after which the pool replaces the connection
    (the connect term), and one statement, after which the append fails (a network error is never retried, and a
    retry starts only while budget remains): 840 s with the package's values. An attempt still without a terminal
    line after it is held by a server that keeps its connection up and never replies, which nothing in the code
    ends (infra/cloudrun/deployment.md, Phase 3: replace the instance)."""
    return _horizon_s(params, budget_ms, stall_s=DEAD_PEER_READS * DEAD_PEER_BOUND_S)


def _horizon_s(params: TutorPipelineParams, budget_ms: int, *, stall_s: int) -> int:
    per_append_s = POOL_CHECKOUT_TIMEOUT_S + CONNECT_TIMEOUT_S + (ATTEMPT_STATEMENTS + 1) * max(1, int(budget_ms)) / 1000 + stall_s
    rounds = math.ceil(params.ledger_append_max_in_flight / max(1, params.ledger_append_workers))
    return 60 * math.ceil((rounds * per_append_s + HORIZON_MARGIN_S) / 60)


def coverage_horizon_s(settings: Settings | None = None) -> int:
    """attempt_horizon_s for the package and the ledger budget in force: ledger_coverage's default horizon."""
    settings = settings or get_settings()
    package = get_config_package(settings)
    return attempt_horizon_s(ledger_params(package), ledger_budget_ms(settings, package))


def budget_stamp(settings: Settings, package: ConfigPackage, *, shadow_ms: int | None) -> BudgetStamp:
    """The budgets in force for one record, and which of them differ from the package's (R-46; spec 18.6 D5)."""
    params = ledger_params(package)
    append_ms = ledger_budget_ms(settings, package)
    overridden = tuple(
        name
        for name, value, packaged in (("shadow_ms", shadow_ms, params.shadow_budget_ms), ("ledger_append_ms", append_ms, params.ledger_append_budget_ms))
        if value is not None and int(value) != int(packaged)
    )
    return BudgetStamp(shadow_ms=shadow_ms, ledger_append_ms=append_ms, overridden=overridden)


@dataclass(frozen=True)
class AppendedRecord:
    seq: int
    record_hash: str
    duplicate: bool


@dataclass(frozen=True)
class LedgerCheck:
    count: int
    first_seq: int | None
    last_seq: int | None
    head_hash: str | None
    head_row: tuple[int, str] | None
    problems: tuple[str, ...]
    # Records past the head the check started from: appends that committed while it ran (not walked).
    appended_during_check: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems


def _utc(value: datetime) -> datetime:
    # SQLite returns these timestamps without a zone (stored as UTC); PostgreSQL returns them with one.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def entry_bytes(entry: LedgerEntry) -> bytes:
    return ledger_canonical(entry.model_dump(mode="json"))


def record_hash_for(*, seq: int, created_at: datetime, prev_hash: str, entry_sha256: str) -> str:
    return sha256_hex(
        ledger_canonical(
            {
                "chain": CHAIN,
                "seq": seq,
                "created_at": _utc(created_at).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "prev_hash": prev_hash,
                "entry_sha256": entry_sha256,
            }
        )
    )


def _log(level: int, message: str, event: str, **fields: Any) -> None:
    LOGGER.log(level, message, extra={FIELDS: {"event": event, **fields}})


def sqlstate(exc: BaseException) -> str | None:
    """The SQLSTATE of a database error from psycopg (.sqlstate) or pg8000 (args[0]["C"]), else None."""
    original = getattr(exc, "orig", exc)
    code = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    if code:
        return str(code)
    for argument in getattr(original, "args", ()) or ():
        if isinstance(argument, dict) and argument.get("C"):
            return str(argument["C"])
    return None


def _surface_field(surface: str | None) -> dict[str, str]:
    """A /qa/ask line says where it came from (surface "qa"); tutor lines keep their original fields."""
    return {"surface": "qa"} if surface == "qa" else {}


def _entry_surface(entry: LedgerEntry) -> str | None:
    return "qa" if entry.response_id.startswith("qa-") else None


def append_ledger_entry(
    entry: LedgerEntry,
    *,
    session_factory: Callable[[], Session] = SessionLocal,
    now: datetime | None = None,
    budget_ms: int,
    attempts: int | None = None,
    log_fields: dict[str, Any] | None = None,
) -> AppendedRecord:
    """Append one record in its own transaction, at most `attempts` times within budget_ms; attempts defaults to the
    configuration package's tutor_pipeline.budgets.ledger_append_attempts (PD-11).

    Statements run in a fixed order (Core, so the unit of work never reorders them): head insert-if-missing, head
    SELECT ... FOR UPDATE, record INSERT, head UPDATE. Start-up's trigger guard locks the two tables in the same
    order, head first, and skips its DDL when the guards are current (app.core.schema_upgrades; spec 18.8 F8). An
    IntegrityError, a deadlock (40P01) or a serialization failure (40001) is retried within the budget: each rolled
    the whole attempt back. Any other database error (a lock timeout, a statement timeout, a busy database, a trigger
    refusal) is raised at once, so the caller fails open quickly. log_fields (the legacy attempt id) are added to
    the appended line. On PostgreSQL every attempt first sets lock_timeout, statement_timeout and
    idle_in_transaction_session_timeout to the remaining budget. The last bounds the time the attempt holds the head
    row's lock between statements: if the process stalls after SELECT ... FOR UPDATE (a CPU-throttled instance once
    the response has gone, spec 18.6 D13), the server ends the session and releases the lock, so the other instances'
    appends are not held up. None of the three bounds the wait for a pooled connection: record_legacy_delivery
    bounds the learner's wait as a whole.
    """
    extra_fields = dict(log_fields or {})
    payload = entry_bytes(entry)
    entry_text = payload.decode("utf-8")
    entry_digest = sha256_hex(payload)
    created_at = _utc(now or datetime.now(UTC))
    deadline = time.monotonic() + max(1, int(budget_ms)) / 1000
    last_error: Exception | None = None
    if attempts is None:
        attempts = ledger_params(get_config_package(get_settings())).ledger_append_attempts
    for attempt in range(max(1, int(attempts))):
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if attempt:
            if remaining_ms <= 0:
                break
            time.sleep(random.uniform(0, min(0.005 * attempt, remaining_ms / 1000)))
        with session_factory() as db:
            try:
                dialect = db.get_bind().dialect.name
                if dialect == "postgresql":
                    # Integers only (no bind parameters in SET): each ends the attempt once the budget is spent.
                    timeout_ms = max(1, int((deadline - time.monotonic()) * 1000))
                    db.execute(text(f"SET LOCAL lock_timeout = '{timeout_ms}ms'"))
                    db.execute(text(f"SET LOCAL statement_timeout = '{timeout_ms}ms'"))
                    db.execute(text(f"SET LOCAL idle_in_transaction_session_timeout = '{timeout_ms}ms'"))
                existing = db.execute(
                    select(ResponseLedgerRecord.seq, ResponseLedgerRecord.record_hash, ResponseLedgerRecord.entry_sha256).where(
                        ResponseLedgerRecord.response_id == entry.response_id
                    )
                ).first()
                if existing is not None:
                    if existing.entry_sha256 != entry_digest:
                        raise LedgerConflict("this response_id is already recorded with a different entry")
                    appended = AppendedRecord(seq=existing.seq, record_hash=existing.record_hash, duplicate=True)
                    db.rollback()
                    _log(logging.INFO, "Tutor ledger record already present", "tutor.ledger.appended", delivery=entry.delivery,
                         seq=appended.seq, record_hash=appended.record_hash, duplicate=True, **_surface_field(_entry_surface(entry)),
                         **extra_fields)
                    return appended
                module = postgresql if dialect == "postgresql" else sqlite
                db.execute(
                    module.insert(ResponseLedgerHead)
                    .values(chain=CHAIN, seq=0, record_hash=GENESIS_HASH, updated_at=created_at, started_at=created_at)
                    .on_conflict_do_nothing(index_elements=["chain"])
                )
                head = db.execute(
                    select(ResponseLedgerHead.seq, ResponseLedgerHead.record_hash).where(ResponseLedgerHead.chain == CHAIN).with_for_update()
                ).one()
                seq = int(head.seq) + 1
                record_hash = record_hash_for(seq=seq, created_at=created_at, prev_hash=head.record_hash, entry_sha256=entry_digest)
                db.execute(
                    insert(ResponseLedgerRecord).values(
                        seq=seq,
                        response_id=entry.response_id,
                        delivery=entry.delivery,
                        decision=entry.decision,
                        shadowed_response_id=entry.shadowed_response_id,
                        claim_set_hash=entry.claim_set_hash,
                        entry_schema=entry.entry_schema,
                        entry=entry_text,
                        entry_sha256=entry_digest,
                        prev_hash=head.record_hash,
                        record_hash=record_hash,
                        created_at=created_at,
                    )
                )
                db.execute(
                    update(ResponseLedgerHead)
                    .where(ResponseLedgerHead.chain == CHAIN)
                    .values(seq=seq, record_hash=record_hash, updated_at=created_at)
                )
                db.commit()
            except IntegrityError as exc:
                # Another writer took this sequence number, or recorded this response_id: read again.
                db.rollback()
                last_error = exc
                continue
            except DBAPIError as exc:
                db.rollback()
                if sqlstate(exc) in RETRYABLE_SQLSTATES:
                    # A deadlock victim or a serialization failure: nothing of this attempt was kept, so try again.
                    last_error = exc
                    continue
                raise
            except LedgerConflict:
                db.rollback()
                raise
        _log(logging.INFO, "Tutor ledger record appended", "tutor.ledger.appended", delivery=entry.delivery, seq=seq,
             record_hash=record_hash, duplicate=False, **_surface_field(_entry_surface(entry)), **extra_fields)
        return AppendedRecord(seq=seq, record_hash=record_hash, duplicate=False)
    raise LedgerAppendError("the ledger record could not be appended within its attempts and budget") from last_error


def parse_head(value: str | None) -> tuple[int, str] | None:
    """A head logged earlier, as SEQ:HASH (the worker's and the verify script's --expect-head)."""
    if not value:
        return None
    seq, _, digest = value.partition(":")
    if not seq.isdigit() or len(digest) != 64 or set(digest.lower()) - set("0123456789abcdef"):
        raise ValueError("--expect-head takes SEQ:HASH (a sequence number and a 64-character record hash)")
    return int(seq), digest.lower()


def chain_head(db: Session) -> tuple[int, str] | None:
    head = db.execute(select(ResponseLedgerHead.seq, ResponseLedgerHead.record_hash).where(ResponseLedgerHead.chain == CHAIN)).first()
    return (int(head.seq), head.record_hash) if head else None


def _insert_head_if_missing(db: Session, *, at: datetime) -> None:
    module = postgresql if db.get_bind().dialect.name == "postgresql" else sqlite
    db.execute(
        module.insert(ResponseLedgerHead)
        .values(chain=CHAIN, seq=0, record_hash=GENESIS_HASH, updated_at=at, started_at=at)
        .on_conflict_do_nothing(index_elements=["chain"])
    )


def ledger_started_at(db: Session) -> datetime | None:
    """When the chain began (informational): the earlier of the head's started_at, which the first append writes,
    and the first record's created_at (a restored chain keeps its own times). None before either exists.

    It does not say which turns should have a record, and start-up does not write it: a revision
    deployed with no traffic starts while the earlier image still serves every learner, so a start time is not when
    the ledger began recording deliveries. Each turn says so itself instead: TutorTurn.ledger_record_expected is true
    when a Phase 3 image created it with TUTOR_LEDGER_ENABLED on, false under the kill switch, and null when an image
    that keeps no ledger created it (before Phase 3, or during a rollback window; spec 18.8 F12)."""
    started = db.scalar(select(ResponseLedgerHead.started_at).where(ResponseLedgerHead.chain == CHAIN))
    first = db.scalar(select(func.min(ResponseLedgerRecord.created_at)))
    times = [_utc(value) for value in (started, first) if value is not None]
    return min(times) if times else None


def _columns_agree(row: ResponseLedgerRecord, parsed: dict[str, Any]) -> bool:
    return (
        parsed.get("response_id") == row.response_id
        and parsed.get("delivery") == row.delivery
        and parsed.get("decision") == row.decision
        and parsed.get("shadowed_response_id") == row.shadowed_response_id
        and parsed.get("claim_set_hash") == row.claim_set_hash
        and parsed.get("entry_schema") == row.entry_schema
    )


def verify_response_ledger(db: Session, *, expected_head: tuple[int, str] | None = None) -> LedgerCheck:
    """Walk the chain in seq order. No retention applies, so the first row must be seq 1 (spec 4.12).

    The check holds one consistent view of the chain on any isolation level (spec 18.6 D8). It reads the head first
    and walks the records up to it only. An append inserts its record and moves the head in one transaction, so
    every record up to the head it read is committed, and a record past it is an append that committed while the
    check ran: it is counted (appended_during_check), not reported. A record past the head is a problem only when a
    head read after it still does not cover it (a record inserted without moving the head). Under READ COMMITTED,
    PostgreSQL's default, each statement takes its own snapshot; walking every record and then reading the head
    reported a sound chain as broken whenever an append committed in between.
    """
    problems: list[str] = []
    count = 0
    first_seq: int | None = None
    previous: tuple[int, str] | None = None
    reached_expected = expected_head is None
    head = chain_head(db)
    limit = head[0] if head is not None else 0
    rows = db.execute(
        select(ResponseLedgerRecord).where(ResponseLedgerRecord.seq <= limit).order_by(ResponseLedgerRecord.seq).execution_options(yield_per=500)
    ).scalars()
    for row in rows:
        count += 1
        if previous is None:
            first_seq = row.seq
            if row.seq != 1:
                problems.append(f"seq 1 to {row.seq - 1} missing")
            elif row.prev_hash != GENESIS_HASH:
                problems.append("seq 1 does not start from the genesis hash")
        else:
            if row.seq != previous[0] + 1:
                problems.append(f"seq {previous[0] + 1} to {row.seq - 1} missing")
            if row.prev_hash != previous[1]:
                problems.append(f"seq {row.seq} does not chain onto seq {previous[0]}")
        raw = (row.entry or "").encode("utf-8")
        if sha256_hex(raw) != row.entry_sha256:
            problems.append(f"seq {row.seq} entry does not match its entry_sha256")
        if record_hash_for(seq=row.seq, created_at=row.created_at, prev_hash=row.prev_hash, entry_sha256=row.entry_sha256) != row.record_hash:
            problems.append(f"seq {row.seq} does not match its record_hash")
        parsed: Any = None
        try:
            parsed = json.loads(row.entry)
            if ledger_canonical(parsed) != raw:
                problems.append(f"seq {row.seq} entry is not canonical JSON")
        except (TypeError, ValueError):
            problems.append(f"seq {row.seq} entry is not canonical JSON")
        model = ENTRY_SCHEMAS.get(row.entry_schema)
        if model is None:
            problems.append(f"seq {row.seq} has an unknown entry_schema")
        elif isinstance(parsed, dict):
            try:
                model.model_validate(parsed)
            except ValidationError:
                problems.append(f"seq {row.seq} entry fails {row.entry_schema}")
        if not isinstance(parsed, dict) or not _columns_agree(row, parsed):
            problems.append(f"seq {row.seq} columns disagree with its entry")
        if expected_head is not None and (row.seq, row.record_hash) == tuple(expected_head):
            reached_expected = True
        previous = (row.seq, row.record_hash)
    last = previous
    if last is not None:
        if head != last:
            problems.append(f"the chain head (seq {limit}) does not match the last record (seq {last[0]})")
    elif head is not None and head[0] != 0:
        problems.append(f"the chain head (seq {head[0]}) does not match the last record (seq 0)")
    # Records past the head read first: appends that committed during the walk, unless no later head covers them.
    beyond = db.execute(
        select(func.count(), func.max(ResponseLedgerRecord.seq)).select_from(ResponseLedgerRecord).where(ResponseLedgerRecord.seq > limit)
    ).one()
    appended_during = 0
    if beyond[0]:
        later = chain_head(db)
        if later is None:
            problems.append("the chain head is missing")
        elif later[0] < int(beyond[1]):
            problems.append(f"seq {int(beyond[1])} lies past the chain head (seq {later[0]})")
        else:
            appended_during = int(beyond[0])
    if not reached_expected and expected_head is not None:
        problems.append(f"the chain no longer reaches the logged head seq {expected_head[0]}")
    return LedgerCheck(
        count=count,
        first_seq=first_seq,
        last_seq=last[0] if last else None,
        head_hash=last[1] if last else None,
        head_row=head,
        problems=tuple(problems[:_MAX_REPORTED_PROBLEMS]),
        appended_during_check=appended_during,
    )


# ------------------------------------------------------------------------------- operator tools (worker, script)


def ledger_coverage(db: Session, since: datetime, *, now: datetime | None = None, horizon_s: int | None = None) -> dict[str, Any]:
    """Tutor turns created since `since` with no ledger record (plan I "ledger writes 100% of deliveries"; report
    only), split by what each turn expected (TutorTurn.ledger_record_expected; spec 18.8 F12):
      unrecorded                  it expected a record, has none, and was created before settled_before: a lost
                                  record, a plan L stop;
      pending                     it expected a record and has none yet, but was created at or after settled_before,
                                  so its append may still be running (the turn commits first and its append runs
                                  after the commit): not counted as lost; a later run counts it (spec 18.12 J5);
      not_expected_earlier_image  an image that keeps no ledger created it (before Phase 3, or a rollback window);
      ledger_disabled             it was created while TUTOR_LEDGER_ENABLED was off (the kill switch);
    and the /qa/ask records since then. settled_before is `now` (the check's start) less horizon_s, which defaults to
    coverage_horizon_s() (attempt_horizon_s: on an always-on instance every append has ended by then, unless an open
    database connection stopped answering); horizon_s=0
    counts every turn, for a check run once traffic has stopped. A qa- record holds no id of its Q&A row, so Q&A
    coverage is the per-process legacy_by_surface.qa.coverage_rate SLI and the tutor.ledger.* outcome lines, not a
    join."""
    since = _utc(since)
    now = _utc(now or datetime.now(UTC))
    if horizon_s is None:
        horizon_s = coverage_horizon_s()
    if int(horizon_s) < 0:
        raise ValueError("the coverage horizon is a number of seconds, 0 or more")
    settled_before = now - timedelta(seconds=int(horizon_s))
    recorded = select(ResponseLedgerRecord.response_id).where(ResponseLedgerRecord.response_id == TutorTurn.id).exists()

    def count(*conditions) -> int:
        return int(db.scalar(select(func.count()).select_from(TutorTurn).where(TutorTurn.created_at >= since, *conditions)) or 0)

    qa_records = db.scalar(
        select(func.count()).select_from(ResponseLedgerRecord).where(ResponseLedgerRecord.created_at >= since, ResponseLedgerRecord.response_id.like("qa-%"))
    ) or 0
    expected_missing = (TutorTurn.ledger_record_expected.is_(True), ~recorded)
    return {
        "since": since.isoformat(),
        "settled_before": settled_before.isoformat(),
        "horizon_s": int(horizon_s),
        "turns_since": count(),
        "unrecorded": count(*expected_missing, TutorTurn.created_at < settled_before),
        "pending": count(*expected_missing, TutorTurn.created_at >= settled_before),
        "not_expected_earlier_image": count(TutorTurn.ledger_record_expected.is_(None), ~recorded),
        "ledger_disabled": count(TutorTurn.ledger_record_expected.is_(False), ~recorded),
        "qa_records_since": int(qa_records),
    }


def clone_prompt_hashes(package: ConfigPackage, *, environment: str | None) -> dict[str, str]:
    """Package v7 (Phase 9 spec 4.12): each development-registry fake generate member with the extractive-clone-v1 rule,
    with the evidential prompt hash its shadow records carry; empty for a package without a ranking block, and empty
    outside development (a clone generator is refused there, so no clone record can be legitimate: the strictest check)."""
    if (environment or "").lower() != "development":
        return {}
    if getattr(package, "ranking", None) is None or package.gateway is None or package.tutor_pipeline is None:
        return {}
    from app.services.ranking.generators import clone_prompt_hash
    from app.services.ranking.vocabulary import CLONE_RULE

    return {spec.adapter_id: clone_prompt_hash(spec.adapter_id, package) for spec in package.gateway.registries.get("development", ())
            if spec.provider == "fake" and "generate" in spec.capabilities and getattr(spec, "fake_generate_rule", None) == CLONE_RULE}


def _provenance_problems(seq: int, entry: dict[str, Any], params: TutorPipelineParams, v1: Any, phase5: Any,
                         clones: dict[str, str] | None = None) -> list[str]:
    """What in one record's provenance differs from the package's pins (ledger_provenance). A two-pass ledger-entry-v2
    or ledger-entry-v3 record must also name the package's V1.3 checker and V1 rules hash (Phase 4 spec 7.9); a v3
    record also its tool contract, panel weights and routing table versions and its V2 verifier prompt hash (Phase 5
    spec 7.3). v1 is the package's v1 block (None for a package without one) and phase5 its (v2, tools) blocks (None for
    a package without them), each passed by every caller so that no call skips a check. clones (clone_prompt_hashes):
    a shadow record of a development clone generator (Phase 9 shadow generation) is checked against its clone prompt
    hash instead of the package's evidential hash and allowed generators; every other generator id is checked as before.
    Without clones (None) no generator is a clone, the strictest check."""
    provenance = entry.get("provenance") if isinstance(entry.get("provenance"), dict) else {}
    versions = entry.get("versions") if isinstance(entry.get("versions"), dict) else {}
    pipeline = entry.get("pipeline")
    problems = []
    if pipeline == params.legacy_pipeline_version:
        expected = {
            "provenance.evidential_prompt_hash": (provenance.get("evidential_prompt_hash"), params.legacy_containment_rule_hash),
            "provenance.generator_model_id": (provenance.get("generator_model_id"), params.legacy_generator_model_id),
            "provenance.pedagogical_prompt_hash": (provenance.get("pedagogical_prompt_hash"), None),
            "versions.pipeline_version": (versions.get("pipeline_version"), params.legacy_pipeline_version),
            "versions.generator_id": (versions.get("generator_id"), params.legacy_generator_id),
        }
    elif pipeline == params.version:
        resolved = entry.get("resolved_question") if isinstance(entry.get("resolved_question"), dict) else {}
        resolver = resolved.get("resolver") if isinstance(resolved.get("resolver"), dict) else {}
        expected = {
            "provenance.evidential_prompt_hash": (provenance.get("evidential_prompt_hash"), params.evidential_prompt_hash),
            "provenance.pedagogical_prompt_hash": (provenance.get("pedagogical_prompt_hash"), params.pedagogical_prompt_hash),
            "versions.pipeline_version": (versions.get("pipeline_version"), params.version),
            "resolved_question.resolver.prompt_hash": (resolver.get("prompt_hash"), params.resolver_prompt_hash),
        }
        clone_hash = (clones or {}).get(versions.get("generator_id")) if entry.get("delivery") == "shadow" else None
        if clone_hash is not None:
            expected["provenance.evidential_prompt_hash"] = (provenance.get("evidential_prompt_hash"), clone_hash)
        elif versions.get("generator_id") not in params.generators_allowed:
            problems.append(f"seq {seq} versions.generator_id is not a generator the package allows")
        if entry.get("entry_schema") in ("ledger-entry-v2", "ledger-entry-v3", "ledger-entry-v4"):
            verification = entry.get("verification") if isinstance(entry.get("verification"), dict) else {}
            policy = verification.get("policy") if isinstance(verification.get("policy"), dict) else {}
            if v1 is None:
                problems.append(f"seq {seq} is a V1-verified record but the package has no v1 block")
            else:
                expected["provenance.v1_3_checker_model_id"] = (provenance.get("v1_3_checker_model_id"), v1.checker_model_id)
                expected["verification.policy.rules_hash"] = (policy.get("rules_hash"), v1.rules_hash)
        if entry.get("entry_schema") in ("ledger-entry-v3", "ledger-entry-v4"):
            verification = entry.get("verification") if isinstance(entry.get("verification"), dict) else {}
            block = verification.get("v2") if isinstance(verification.get("v2"), dict) else {}
            if phase5 is None:
                problems.append(f"seq {seq} is a V2-verified record but the package has no v2 or tools block")
            else:
                v2, tools = phase5
                expected["provenance.tool_contract_version"] = (provenance.get("tool_contract_version"), tools.version)
                expected["provenance.panel_weights_version"] = (provenance.get("panel_weights_version"), v2.panel_weights_version)
                expected["provenance.routing_table_version"] = (provenance.get("routing_table_version"), v2.routing_table_version)
                expected["verification.v2.verifier_prompt_hash"] = (block.get("verifier_prompt_hash"), v2.verifier_prompt_hash)
    else:
        return [f"seq {seq} names a pipeline the package does not pin"]
    for name, (recorded, pinned) in expected.items():
        if recorded != pinned:
            problems.append(f"seq {seq} {name} is not the package pin")
    claims = entry.get("claims") if isinstance(entry.get("claims"), list) else []
    if any(not isinstance(claim, dict) or claim.get("provenance") != provenance for claim in claims):
        problems.append(f"seq {seq} has a claim whose provenance differs from its record's")
    return problems


def ledger_provenance(db: Session, package: ConfigPackage, *, environment: str | None = None) -> dict[str, Any]:
    """F-2's audit until a provider prompt exists (plan 15.1 "Zero learner-state fields in evidential-pass prompts";
    DI-49): no evidential prompt is logged or ledgered, so instead every record must name the pinned, learner-free
    evidential input of its pipeline. A record stamped with the package in force (versions.config_package_sha256) is
    compared with that package's pins:
      legacy (tutor_pipeline.legacy)  provenance.evidential_prompt_hash is the containment rule hash, and the
                                      generator model id, pipeline version and generator id are the legacy ids (no
                                      pedagogical prompt);
      two-pass (tutor_pipeline)       the evidential, pedagogical and resolver prompt hashes are the package's, the
                                      pipeline version is its version, and the generator is one it allows;
    and every claim carries its record's provenance. Only with environment "development" is a shadow record of a
    development clone generator checked against its clone prompt hash (clone_prompt_hashes); otherwise, the default,
    no generator is a clone. A record stamped with another package is counted
    (other_package) and not compared: its pins are that package's. Counts and seq numbers only, never record text.
    Read-only; run by the worker's and the script's --check-provenance."""
    params = ledger_params(package)
    clones = clone_prompt_hashes(package, environment=environment)
    problems: list[str] = []
    records = checked = other_package = 0
    config_versions: dict[str, int] = {}
    rows = db.execute(select(ResponseLedgerRecord.seq, ResponseLedgerRecord.entry).order_by(ResponseLedgerRecord.seq).execution_options(yield_per=500))
    for seq, raw in rows:
        records += 1
        try:
            entry = json.loads(raw)
        except (TypeError, ValueError):
            entry = None
        if not isinstance(entry, dict):
            problems.append(f"seq {seq} entry is not a JSON object")
            continue
        versions = entry.get("versions") if isinstance(entry.get("versions"), dict) else {}
        version = config_version_of(versions)
        config_versions[version] = config_versions.get(version, 0) + 1
        if versions.get("config_package_sha256") != package.sha256:
            other_package += 1
            continue
        checked += 1
        problems.extend(_provenance_problems(seq, entry, params, package.v1, phase5_blocks(package), clones))
    return {
        "package_version": package.package_version,
        "package_sha256": package.sha256,
        "records": records,
        "checked": checked,
        "other_package": other_package,
        "config_versions": dict(sorted(config_versions.items())),
        "problem_count": len(problems),
        "problems": problems[:_MAX_REPORTED_PROBLEMS],
    }


def phase5_blocks(package: ConfigPackage) -> Any:
    """(v2, tools) of a package v4, else None: what _provenance_problems compares a ledger-entry-v3 record with."""
    return (package.v2, package.tools) if package.v2 is not None and package.tools is not None else None


def pending_v3_intents(db: Session, *, after_seq: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
    """The V3 queue intents on ledger-entry-v2, ledger-entry-v3 and ledger-entry-v4 records (Phase 4 spec 7.9, conflict 28; Phase 5 spec
    7.3): one item per claim verdict with a v3 intent, in seq order, after `after_seq`; a v3 record's items also carry
    its escalation (X2 or null). Read-only; filtered on entry_schema in SQL and parsed in Python, so it behaves alike on
    SQLite, psycopg and pg8000. Ids, claim ids and enumerations only, never text. A read-only helper; the Phase 6 scan reads
    the records itself (app.services.v3.scan)."""
    rows = db.execute(
        select(ResponseLedgerRecord.seq, ResponseLedgerRecord.response_id, ResponseLedgerRecord.entry_schema, ResponseLedgerRecord.entry)
        .where(ResponseLedgerRecord.entry_schema.in_(("ledger-entry-v2", "ledger-entry-v3", "ledger-entry-v4")), ResponseLedgerRecord.seq > int(after_seq))
        .order_by(ResponseLedgerRecord.seq)
        .limit(int(limit))
    )
    intents: list[dict[str, Any]] = []
    for seq, response_id, entry_schema, raw in rows:
        try:
            entry = json.loads(raw)
        except (TypeError, ValueError):
            continue
        verification = entry.get("verification") if isinstance(entry, dict) else None
        for verdict in (verification or {}).get("verdicts") or []:
            intent = verdict.get("v3") if isinstance(verdict, dict) else None
            if isinstance(intent, dict):
                item = {"seq": int(seq), "response_id": response_id, "claim_id": verdict.get("claim_id"),
                        "reasons": list(intent.get("reasons") or []), "trigger": intent.get("trigger")}
                if entry_schema in ("ledger-entry-v3", "ledger-entry-v4"):
                    item["escalation"] = intent.get("escalation")
                intents.append(item)
    return intents


def config_version_of(versions: Any) -> str:
    """A record's config_version (plan Phase 7 G; Phase 7 spec R-e, 4.9): its config_package_version when that
    version's major is at least EHMF_FIRST_MAJOR (6, the first package with an ehmf block), else "pre-phase-7". A
    malformed version reads as major 0. Applied at read time; no row is rewritten."""
    from app.services.ehmf.vocabulary import EHMF_FIRST_MAJOR, PRE_PHASE_7

    version = str(versions.get("config_package_version", "0")) if isinstance(versions, dict) else "0"
    try:
        major = int(version.split(".")[0] or 0)
    except ValueError:
        major = 0
    return version if major >= EHMF_FIRST_MAJOR else PRE_PHASE_7


def _config_version_of_entry(entry_text: str) -> str:
    try:
        entry = json.loads(entry_text)
    except (TypeError, ValueError):
        return config_version_of(None)
    return config_version_of(entry.get("versions") if isinstance(entry, dict) else None)


def export_ledger(db: Session, path: Path) -> int:
    """Every record as one JSON object per line (the step before an Alembic downgrade); returns the row count. Each line
    also names the record's config_version (config_version_of, read-time; restore ignores it).

    The file holds corpus text, turn ids and, on shadow rows, the resolver's source message ids: pseudonymous data
    linked to learners while their turns exist. Its handling rule is in infra/cloudrun/deployment.md (Phase 3)."""
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in db.execute(select(ResponseLedgerRecord).order_by(ResponseLedgerRecord.seq).execution_options(yield_per=500)).scalars():
            handle.write(json.dumps({
                "seq": row.seq, "response_id": row.response_id, "delivery": row.delivery, "decision": row.decision,
                "shadowed_response_id": row.shadowed_response_id, "claim_set_hash": row.claim_set_hash,
                "entry_schema": row.entry_schema, "entry": row.entry, "entry_sha256": row.entry_sha256,
                "prev_hash": row.prev_hash, "record_hash": row.record_hash, "created_at": _utc(row.created_at).isoformat(),
                "config_version": _config_version_of_entry(row.entry),
            }, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def _restore_problem(line_number: int, row: dict[str, Any], previous: tuple[int, str]) -> str | None:
    """Why an exported line cannot extend the chain being restored, or None (spec 18.7 E12)."""
    try:
        seq, created_at = int(row["seq"]), datetime.fromisoformat(str(row["created_at"]))
        entry_text, prev_hash, entry_digest = str(row["entry"]), str(row["prev_hash"]), str(row["entry_sha256"])
    except (KeyError, TypeError, ValueError):
        return f"line {line_number} is not an exported ledger record"
    if (seq, prev_hash) != (previous[0] + 1, previous[1]):
        return f"line {line_number} (seq {seq}) does not extend the chain at seq {previous[0]}"
    raw = entry_text.encode("utf-8")
    if sha256_hex(raw) != entry_digest:
        return f"seq {seq} entry does not match its entry_sha256"
    if record_hash_for(seq=seq, created_at=created_at, prev_hash=prev_hash, entry_sha256=entry_digest) != row.get("record_hash"):
        return f"seq {seq} does not match its record_hash"
    model = ENTRY_SCHEMAS.get(str(row.get("entry_schema")))
    try:
        parsed = json.loads(entry_text)
        if model is None or not isinstance(parsed, dict) or ledger_canonical(parsed) != raw:
            return f"seq {seq} entry is not a canonical {row.get('entry_schema')} entry"
        model.model_validate(parsed)
    except (TypeError, ValueError, ValidationError):
        return f"seq {seq} entry fails {row.get('entry_schema')}"
    columns = ("response_id", "delivery", "decision", "shadowed_response_id", "claim_set_hash")
    if any(parsed.get(name) != row.get(name) for name in columns):
        return f"seq {seq} columns disagree with its entry"
    return None


def restore_ledger(db: Session, path: Path) -> tuple[int, tuple[int, str] | None]:
    """Re-insert an export_ledger file into an empty ledger (spec 18.7 E12): the step that undoes an Alembic
    downgrade's drop, so the R-22 record survives a rollback. Returns (rows restored, the restored head).

    Each line must extend the chain from the genesis hash with its exported seq, created_at, prev_hash and hashes,
    which are recomputed, and its entry must validate; the head then moves forward one record at a time, as the
    append-only triggers require. One transaction: a refused line, or a ledger that already holds a record, leaves
    the database as it was. The result is the exported chain byte for byte, so a head logged before the downgrade
    still verifies with --expect-head."""
    if db.scalar(select(func.count()).select_from(ResponseLedgerRecord)):
        raise LedgerRestoreRefused("the ledger already holds records; a restore needs an empty ledger")
    if chain_head(db) not in (None, (0, GENESIS_HASH)):
        raise LedgerRestoreRefused("the chain head is not at the genesis; a restore needs an empty ledger")
    previous: tuple[int, str] = (0, GENESIS_HASH)
    count = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    row = None
                problem = _restore_problem(line_number, row, previous) if isinstance(row, dict) else f"line {line_number} is not JSON"
                if problem:
                    raise LedgerRestoreRefused(problem)
                created_at = _utc(datetime.fromisoformat(row["created_at"]))
                if count == 0:
                    _insert_head_if_missing(db, at=created_at)
                db.execute(insert(ResponseLedgerRecord).values(
                    seq=row["seq"], response_id=row["response_id"], delivery=row["delivery"], decision=row["decision"],
                    shadowed_response_id=row.get("shadowed_response_id"), claim_set_hash=row.get("claim_set_hash"),
                    entry_schema=row["entry_schema"], entry=row["entry"], entry_sha256=row["entry_sha256"],
                    prev_hash=row["prev_hash"], record_hash=row["record_hash"], created_at=created_at,
                ))
                db.execute(update(ResponseLedgerHead).where(ResponseLedgerHead.chain == CHAIN)
                           .values(seq=row["seq"], record_hash=row["record_hash"], updated_at=created_at))
                previous = (int(row["seq"]), row["record_hash"])
                count += 1
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return count, (previous if count else None)


# ------------------------------------------------------------------------------------------- legacy deliveries


@dataclass(frozen=True)
class LegacyDelivery:
    """What a legacy contained answer delivered (spec 7.12): one tutor turn (surface "tutor") or one /qa/ask answer
    (surface "qa"). Built by legacy_delivery_for; holds corpus text and identifiers only, never the learner's
    question."""

    response_id: str
    decision: str
    reason: str
    claims: tuple[tuple[str, tuple[str, ...]], ...]
    quoted: tuple[EvidenceSpan, ...]
    retrieved: tuple[EvidenceSpan, ...] | None
    answer_sha256: str
    retrieval_mode: str
    provider: str
    model: str
    corpus_version: str
    index_version: str
    gate: str
    threshold_version: str
    floor: float
    margin: float
    policy_version: str
    dropped_unresolved: int = 0
    manifest_sha256: str | None = None
    # Delivered quotations whose span's derived license class is not public: kept out of the record and counted.
    dropped_not_public: int = 0
    surface: str = "tutor"
    # The retrieval gate's decision behind the delivery (None when no retrieval side channel was available).
    sufficiency: Sufficiency | None = None


@dataclass(frozen=True)
class LegacyPreparationFailed:
    """A delivery whose ledger record could not be built (spec 18.7 E5). The error is counted and logged only by
    record_legacy_delivery, after the delivery committed: a request that rolls back delivered nothing, so it is
    neither an attempt nor a lost record."""

    error: BaseException
    surface: str = "tutor"
    # What was delivered, for the delivered-decision SLI (plan I "abstention by reason"), when the caller knows it.
    decision: str | None = None
    reason: str | None = None


def delivered_abstention_reason(contained: Any, retrieval: Any) -> str | None:
    """Why a legacy delivery abstained (plan I "abstention by reason"; spec 18.8 F1), or None for an answer: the
    retrieval gate's own reason when it returned nothing, else no_approved_span: the gate matched passages but none
    could be quoted (not approved under D-31, or failed verification), or the Phase 4 legacy guard withheld the
    contained answer (V1.1, V1.2, or V1.7 conflict_withheld), which its tutor.v1.legacy_guard_withheld line names."""
    if contained.decision == "answer":
        return None
    results = getattr(retrieval, "results", None)
    reason = getattr(retrieval, "reason", None)
    if isinstance(results, list) and not results and reason in GATE_ABSTENTION_REASONS:
        return str(reason)
    return LEGACY_ABSTENTION_REASON


def preparation_failed(error: BaseException, *, contained: Any, retrieval: Any, surface: str) -> LegacyPreparationFailed:
    """A LegacyPreparationFailed that still says what was delivered (its decision and abstention reason)."""
    try:
        decision, reason = str(contained.decision), delivered_abstention_reason(contained, retrieval)
    except Exception:  # noqa: BLE001 - the failure is what is counted; the decision is extra
        decision, reason = None, None
    return LegacyPreparationFailed(error=error, surface="qa" if surface == "qa" else "tutor", decision=decision, reason=reason)


def legacy_delivery_for(
    *,
    response_id: str,
    contained: Any,
    retrieval: Any,
    store: Any,
    registry: Any,
    retrieval_mode: str,
    provider: str,
    model: str,
    policy_version: str,
    surface: str,
) -> LegacyDelivery:
    """The LegacyDelivery of a contained answer (contained_answers.ContainedAnswer) and the retrieval behind it.

    Every EvidenceSpan is built from the span record by retrieve.evidence_span_for, so its license_class is derived
    from the record's plane and the manifest, never labelled: a span that is not public is left out (fail closed),
    and a delivered claim that cites one is left out of the record and counted (LEGACY_NOT_PUBLIC)."""
    floor, margin, threshold_version = store.index.thresholds
    metric_surface = "qa" if surface == "qa" else "legacy"
    quoted: list[EvidenceSpan] = []
    for citation in contained.citations:
        record = store.span_registry.get(citation.span_id) if citation.span_id else None
        span = None
        if record is not None:
            span = evidence_span_for(record, registry, score=None, near_floor=bool(citation.near_floor), surface=metric_surface)
        if span is not None:
            quoted.append(span)
    public_ids = {span.span_id for span in quoted}
    claims: list[tuple[str, tuple[str, ...]]] = []
    not_public = 0
    for claim in contained.claims:
        cited = tuple(claim.cited_span_ids)
        if cited and not set(cited) <= public_ids:
            not_public += 1
            continue
        claims.append((claim.text, cited))
    retrieved: tuple[EvidenceSpan, ...] | None = None
    sufficiency: Sufficiency | None = None
    if retrieval is not None:
        sufficiency = sufficiency_of(retrieval, threshold_version=threshold_version)
        spans = []
        for result in retrieval.results:
            record = store.span_registry.get(result.span_id or result.chunk_id)
            if record is None:
                continue
            span = evidence_span_for(record, registry, score=result.score, near_floor=bool(result.near_floor), surface=metric_surface)
            if span is not None:
                spans.append(span)
        retrieved = tuple(spans)
    return LegacyDelivery(
        response_id=response_id,
        decision=contained.decision,
        reason=delivered_abstention_reason(contained, retrieval) or contained.reason,
        claims=tuple(claims),
        quoted=tuple(quoted),
        retrieved=retrieved,
        answer_sha256=sha256_hex(contained.answer),
        retrieval_mode=retrieval_mode,
        provider=provider,
        model=model,
        corpus_version=registry.corpus_version,
        index_version=store.index_version,
        gate=store.gate,
        threshold_version=threshold_version,
        floor=floor,
        margin=margin,
        policy_version=policy_version,
        dropped_unresolved=contained.dropped_unresolved,
        manifest_sha256=registry.manifest_sha256,
        dropped_not_public=not_public,
        surface="qa" if surface == "qa" else "tutor",
        sufficiency=sufficiency,
    )


def build_legacy_entry(delivery: LegacyDelivery, *, settings: Settings, package: ConfigPackage, manifest_sha256: str | None) -> LedgerEntry:
    provenance = Provenance(
        generator_model_id=EXTRACTIVE_MODE,
        evidential_prompt_hash=LEGACY_CONTAINMENT_RULE_HASH,
        pedagogical_prompt_hash=None,
        corpus_version=delivery.corpus_version,
        threshold_set_version=delivery.threshold_version,
    )
    claims = tuple(
        ClaimLedgerEntry(
            claim_id=claim_id_for(claim_text, span_ids),
            response_id=delivery.response_id,
            text=claim_text,
            span_ids=tuple(sorted(set(span_ids))),
            provenance=provenance,
        )
        for claim_text, span_ids in delivery.claims
        if span_ids
    )
    retrieved = delivery.retrieved is not None
    abstained = delivery.decision != "answer"
    dropped: dict[str, int] = {}
    if delivery.dropped_unresolved:
        dropped[LEGACY_UNRESOLVED] = int(delivery.dropped_unresolved)
    if delivery.dropped_not_public:
        dropped[LEGACY_NOT_PUBLIC] = int(delivery.dropped_not_public)
    return LedgerEntry(
        response_id=delivery.response_id,
        delivery="legacy",
        shadowed_response_id=None,
        pipeline=LEGACY_PIPELINE_VERSION,
        decision="abstain" if abstained else "answer",
        abstention_reason=delivery.reason if abstained else None,
        resolved_question=None,
        retrieval=RetrievalRecord(
            corpus_version=delivery.corpus_version,
            index_version=delivery.index_version,
            gate=delivery.gate,
            threshold_version=delivery.threshold_version,
            floor=delivery.floor,
            margin=delivery.margin,
            mode=delivery.retrieval_mode,
            evidence_scope="retrieved" if retrieved else "delivered_citations",
            sufficiency=delivery.sufficiency if retrieved else None,
            evidence=tuple(delivery.retrieved if retrieved else delivery.quoted),
        ),
        claim_set_hash=None,
        claims=claims,
        span_ids=tuple(sorted({span_id for claim in claims for span_id in claim.span_ids})),
        presentation=None,
        rendered_text_sha256=delivery.answer_sha256,
        provenance=provenance,
        versions=VersionStamps(
            pipeline_version=LEGACY_PIPELINE_VERSION,
            code_sha=settings.git_sha,
            schema_revision_expected=SCHEMA_REVISION,
            config_package_version=package.package_version,
            config_package_sha256=package.sha256,
            manifest_sha256=manifest_sha256,
            span_scheme=package.span_scheme,
            policy_version=delivery.policy_version,
            resolver_id=None,
            generator_id=LEGACY_GENERATOR_ID,
            renderer_id=None,
            budgets=budget_stamp(settings, package, shadow_ms=None),
        ),
        counts=PipelineCounts(
            proposed_claims=len(claims) + sum(dropped.values()),
            bound_claims=len(claims),
            dropped=dropped,
            render_attempts=0,
        ),
    )


def record_ledger_failure(delivery: str, stage: str, exc: BaseException, *, surface: str | None = None, attempt: str | None = None) -> None:
    """Count and log a lost ledger record (plan L: a ledger write failure is a stop condition). A legacy failure line
    carries the attempt id of its tutor.ledger.attempted line: it is that attempt's terminal line (spec 18.8 F11)."""
    if isinstance(exc, LedgerConflict):
        LEDGER_METRICS.conflict(delivery)
        _log(logging.ERROR, "Tutor ledger conflict", "tutor.ledger.conflict", delivery=delivery)
    LEDGER_METRICS.failed(delivery, surface=surface)
    # Tutor deliveries keep their original log fields; a /qa/ask record says where it came from.
    extra = {"surface": surface} if surface == "qa" else {}
    if attempt is not None:
        extra["attempt"] = attempt
    _log(logging.ERROR, "Tutor ledger record could not be appended", "tutor.ledger.append_failed", delivery=delivery, stage=stage,
         error=type(exc).__name__, **extra)


class _LegacyAppender:
    """Runs legacy appends on a small pool of worker threads, so the learner's wait is bounded as a whole.

    append_ledger_entry bounds lock waits and statements on PostgreSQL, but not the wait for a connection: the pool's
    checkout timeout (30 s by default) and a new Cloud SQL connection's bound (app.core.db.CONNECT_TIMEOUT_S, 30 s)
    are far longer than a learner should wait. The request therefore waits for the
    append at most its budget plus the package's ledger_wait_grace_ms; an append still running then finishes in the
    background and is counted when it ends (appended, or failed). At most ledger_append_max_in_flight appends run or
    wait at once; past that an append is refused at once and counted as failed, so a stuck database never piles up
    threads. The pool is sized by its constructor, or from the package on first use.
    """

    def __init__(self, workers: int | None = None, max_in_flight: int | None = None) -> None:
        self._lock = threading.Lock()
        self._workers = workers
        self._slots = threading.BoundedSemaphore(max_in_flight) if max_in_flight is not None else None
        self._executor: ThreadPoolExecutor | None = None
        self._pending: set[Future] = set()

    def _configure(self, workers: int, max_in_flight: int) -> threading.BoundedSemaphore:
        with self._lock:
            if self._slots is None:
                self._slots = threading.BoundedSemaphore(max_in_flight)
            if self._workers is None:
                self._workers = workers
            return self._slots

    def submit(self, task: Callable[[], Any], *, workers: int, max_in_flight: int) -> Future | None:
        slots = self._configure(workers, max_in_flight)
        if not slots.acquire(blocking=False):
            return None
        try:
            with self._lock:
                if self._executor is None:
                    self._executor = ThreadPoolExecutor(max_workers=self._workers, thread_name_prefix="tutor-ledger")
                # The request's context (its logging fields) goes with the task.
                future = self._executor.submit(contextvars.copy_context().run, task)
                self._pending.add(future)
        except BaseException:
            slots.release()
            raise
        future.add_done_callback(self._finished)
        return future

    def _finished(self, future: Future) -> None:
        with self._lock:
            self._pending.discard(future)
            slots = self._slots
        if slots is not None:
            slots.release()

    def pending(self) -> int:
        with self._lock:
            return len(self._pending)

    def drain(self, timeout: float) -> bool:
        """Wait for every running or queued append (tests, and shutdown hooks); True when none is left."""
        with self._lock:
            pending = list(self._pending)
        done, not_done = wait(pending, timeout=timeout)
        return not not_done


LEGACY_APPENDS = _LegacyAppender()


def record_legacy_delivery(
    delivery: LegacyDelivery | LegacyPreparationFailed,
    *,
    settings: Settings | None = None,
    session_factory: Callable[[], Session] = SessionLocal,
) -> AppendedRecord | None:
    """Record a legacy delivery; never raises and never changes the learner's response (fail open, counted).

    Call it only once the delivery's own transaction has committed: this is where the delivery counts as attempted
    (LEDGER_METRICS, and a tutor.ledger.attempted line, the cross-instance denominator of ledger coverage), so a
    request that rolls back is never an attempt and never lowers legacy_coverage_rate (spec 18.7 E5). A
    LegacyPreparationFailed is an attempt that failed at the prepare stage.

    The attempt also counts what was delivered, by decision and abstention reason (LEDGER_METRICS.delivered, and the
    decision and abstention_reason fields of the attempted line; plan I "abstention by reason", spec 18.8 F1),
    whatever the append then does. The attempted line carries an attempt id, and exactly one terminal line with the
    same id ends the attempt when its append ends: tutor.ledger.appended or tutor.ledger.append_failed (spec 18.8
    F11). An append_deferred line is not terminal: the request stopped waiting, and the terminal line follows.

    The learner waits at most the append budget plus the package's ledger_wait_grace_ms for the record, whatever the
    database does (spec conflict 29). None means the record was not confirmed in that time: it failed and was counted,
    or it is still being appended in the background and is counted when that ends.
    """
    surface = delivery.surface
    attempt = uuid4().hex
    decision = delivery.decision
    if isinstance(delivery, LegacyPreparationFailed):
        reason = delivery.reason
    else:
        reason = delivery.reason if delivery.decision != "answer" else None
    LEDGER_METRICS.attempt("legacy", surface=surface)
    if decision is not None:
        LEDGER_METRICS.delivered(decision, reason, surface=surface)
    _log(logging.INFO, "Tutor ledger record attempted", "tutor.ledger.attempted", delivery="legacy", **_surface_field(surface),
         decision=decision, abstention_reason=reason, attempt=attempt)
    if isinstance(delivery, LegacyPreparationFailed):
        record_ledger_failure("legacy", "prepare", delivery.error, surface=surface, attempt=attempt)
        return None
    try:
        settings = settings or get_settings()
        package = get_config_package(settings)
        params = ledger_params(package)
        entry = build_legacy_entry(delivery, settings=settings, package=package, manifest_sha256=delivery.manifest_sha256)
        budget_ms = ledger_budget_ms(settings, package)
    except Exception as exc:  # noqa: BLE001 - a ledger fault must not change the learner's response
        record_ledger_failure("legacy", "append", exc, surface=surface, attempt=attempt)
        return None

    def append() -> AppendedRecord | None:
        try:
            appended = append_ledger_entry(entry, session_factory=session_factory, budget_ms=budget_ms, attempts=params.ledger_append_attempts,
                                           log_fields={"attempt": attempt})
        except Exception as exc:  # noqa: BLE001 - counted here, in the worker, whether or not the request still waits
            record_ledger_failure("legacy", "append", exc, surface=surface, attempt=attempt)
            return None
        LEDGER_METRICS.appended("legacy", duplicate=appended.duplicate, surface=surface)
        return appended

    try:
        future = LEGACY_APPENDS.submit(append, workers=params.ledger_append_workers, max_in_flight=params.ledger_append_max_in_flight)
    except Exception as exc:  # noqa: BLE001 - e.g. no thread could be started
        record_ledger_failure("legacy", "append", exc, surface=surface, attempt=attempt)
        return None
    if future is None:
        record_ledger_failure("legacy", "append", LedgerAppendError("too many ledger appends are already in flight"), surface=surface,
                              attempt=attempt)
        return None
    try:
        return future.result(timeout=(budget_ms + params.ledger_wait_grace_ms) / 1000)
    except FutureTimeout:
        _log(logging.WARNING, "Tutor ledger append is still running; the response was not held for it", "tutor.ledger.append_deferred",
             delivery="legacy", budget_ms=budget_ms, attempt=attempt, **({"surface": surface} if surface == "qa" else {}))
        return None
    except Exception as exc:  # noqa: BLE001 - append() never raises; this is a defence only
        record_ledger_failure("legacy", "append", exc, surface=surface, attempt=attempt)
        return None
