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

What is recorded (spec R-a): every learner delivery is the legacy contained answer, recorded with
delivery "legacy" and response_id = the TutorTurn id; every shadow run of the two-pass pipeline is recorded with
delivery "shadow" and a shadow- id naming the turn it shadowed. "delivered" is Phase 4's.

No user id and no learner text: the ledger stores corpus text (claims) and hashes only, never the resolved
question or the rendered text. The link to a learner is tutor_turns, which erasure deletes; the rows then remain
but cannot be tied to anyone. Every append logs its seq and record_hash (an off-DB copy of the chain, conflict 6);
`python -m app.workers.response_ledger` verifies the chain and logs the head.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout, wait
import contextvars
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
import random
import threading
import time
from typing import Any

from pydantic import ValidationError
from sqlalchemy import insert, select, text, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.config_package import ConfigPackage, canonical_sha256, get_config_package
from app.core.db import SessionLocal
from app.core.structured_logging import FIELDS
from app.db_models import ResponseLedgerHead, ResponseLedgerRecord
from app.services.contained_answers import ABSTENTION, EXTRACTIVE_MODE, MAX_QUOTED_SPANS, QUOTATION_LEAD
from app.services.tutor_pipeline.bind import claim_id_for
from app.services.tutor_pipeline.contracts import (
    ENTRY_SCHEMAS,
    LEGACY_UNRESOLVED,
    ClaimLedgerEntry,
    EvidenceSpan,
    LedgerEntry,
    PipelineCounts,
    Provenance,
    RetrievalRecord,
    VersionStamps,
    ledger_canonical,
    sha256_hex,
)
from app.services.tutor_pipeline.metrics import LEDGER_METRICS

LOGGER = logging.getLogger("qcai.tutor")
CHAIN = "tutor-responses"
GENESIS_HASH = "0" * 64
# The Alembic revision this code expects (tested against the single head); stamped on every record (plan 13.5).
SCHEMA_REVISION = "20261119_phase3_response_ledger"
APPEND_ATTEMPTS = 3
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


def append_ledger_entry(
    entry: LedgerEntry,
    *,
    session_factory: Callable[[], Session] = SessionLocal,
    now: datetime | None = None,
    budget_ms: int,
) -> AppendedRecord:
    """Append one record in its own transaction, at most APPEND_ATTEMPTS times within budget_ms.

    Statements run in a fixed order (Core, so the unit of work never reorders them): head insert-if-missing, head
    SELECT ... FOR UPDATE, record INSERT, head UPDATE. Only an IntegrityError is retried; any other database error
    (a lock timeout, a statement timeout, a busy database, a trigger refusal) is raised at once, so the caller fails
    open quickly. On PostgreSQL every attempt first sets lock_timeout and statement_timeout to the remaining budget.
    Neither bounds the wait for a pooled connection: record_legacy_delivery bounds the learner's wait as a whole.
    """
    payload = entry_bytes(entry)
    entry_text = payload.decode("utf-8")
    entry_digest = sha256_hex(payload)
    created_at = _utc(now or datetime.now(UTC))
    deadline = time.monotonic() + max(1, int(budget_ms)) / 1000
    last_error: Exception | None = None
    for attempt in range(APPEND_ATTEMPTS):
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if attempt:
            if remaining_ms <= 0:
                break
            time.sleep(random.uniform(0, min(0.005 * attempt, remaining_ms / 1000)))
        with session_factory() as db:
            try:
                dialect = db.get_bind().dialect.name
                if dialect == "postgresql":
                    # Integers only (no bind parameters in SET): both end the attempt once the budget is spent.
                    timeout_ms = max(1, int((deadline - time.monotonic()) * 1000))
                    db.execute(text(f"SET LOCAL lock_timeout = '{timeout_ms}ms'"))
                    db.execute(text(f"SET LOCAL statement_timeout = '{timeout_ms}ms'"))
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
                         seq=appended.seq, record_hash=appended.record_hash, duplicate=True)
                    return appended
                module = postgresql if dialect == "postgresql" else sqlite
                db.execute(
                    module.insert(ResponseLedgerHead)
                    .values(chain=CHAIN, seq=0, record_hash=GENESIS_HASH, updated_at=created_at)
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
            except (LedgerConflict, DBAPIError):
                db.rollback()
                raise
        _log(logging.INFO, "Tutor ledger record appended", "tutor.ledger.appended", delivery=entry.delivery, seq=seq,
             record_hash=record_hash, duplicate=False)
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
    """Walk the chain in seq order. No retention applies, so the first row must be seq 1 (spec 4.12)."""
    problems: list[str] = []
    count = 0
    first_seq: int | None = None
    previous: tuple[int, str] | None = None
    reached_expected = expected_head is None
    rows = db.execute(select(ResponseLedgerRecord).order_by(ResponseLedgerRecord.seq).execution_options(yield_per=500)).scalars()
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
    head = chain_head(db)
    last = previous
    if last is not None:
        if head is None:
            problems.append("the chain head is missing")
        elif head != last:
            problems.append(f"the chain head (seq {head[0]}) does not match the last record (seq {last[0]})")
    elif head is not None and head[0] != 0:
        problems.append(f"the chain head (seq {head[0]}) does not match the last record (seq 0)")
    if not reached_expected and expected_head is not None:
        problems.append(f"the chain no longer reaches the logged head seq {expected_head[0]}")
    return LedgerCheck(
        count=count,
        first_seq=first_seq,
        last_seq=last[0] if last else None,
        head_hash=last[1] if last else None,
        head_row=head,
        problems=tuple(problems[:_MAX_REPORTED_PROBLEMS]),
    )


# ------------------------------------------------------------------------------------------- legacy deliveries


@dataclass(frozen=True)
class LegacyDelivery:
    """What the legacy contained path delivered for one tutor turn (spec 7.12). Built by the orchestrator; holds
    corpus text and identifiers only, never the learner's question."""

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
    return LedgerEntry(
        response_id=delivery.response_id,
        delivery="legacy",
        shadowed_response_id=None,
        pipeline="legacy-contained-v1",
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
            sufficiency=None,
            evidence=tuple(delivery.retrieved if retrieved else delivery.quoted),
        ),
        claim_set_hash=None,
        claims=claims,
        span_ids=tuple(sorted({span_id for claim in claims for span_id in claim.span_ids})),
        presentation=None,
        rendered_text_sha256=delivery.answer_sha256,
        provenance=provenance,
        versions=VersionStamps(
            pipeline_version="legacy-contained-v1",
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
        ),
        counts=PipelineCounts(
            proposed_claims=len(claims) + int(delivery.dropped_unresolved),
            bound_claims=len(claims),
            dropped={LEGACY_UNRESOLVED: int(delivery.dropped_unresolved)} if delivery.dropped_unresolved else {},
            render_attempts=0,
        ),
    )


def record_ledger_failure(delivery: str, stage: str, exc: BaseException) -> None:
    """Count and log a lost ledger record (plan L: a ledger write failure is a stop condition)."""
    if isinstance(exc, LedgerConflict):
        LEDGER_METRICS.conflict()
        _log(logging.ERROR, "Tutor ledger conflict", "tutor.ledger.conflict", delivery=delivery)
    LEDGER_METRICS.failed(delivery)
    _log(logging.ERROR, "Tutor ledger record could not be appended", "tutor.ledger.append_failed", delivery=delivery, stage=stage,
         error=type(exc).__name__)


class _LegacyAppender:
    """Runs legacy appends on a small pool of worker threads, so the learner's wait is bounded as a whole.

    append_ledger_entry bounds lock waits and statements on PostgreSQL, but not the checkout of a pooled connection
    (the pool's own timeout, 30 s by default) or a new Cloud SQL connection. The request therefore waits for the
    append at most its budget plus LEGACY_WAIT_GRACE_MS; an append still running then finishes in the background and
    is counted when it ends (appended, or failed). At most LEGACY_APPEND_MAX_IN_FLIGHT appends run or wait at once;
    past that an append is refused at once and counted as failed, so a stuck database never piles up threads.
    """

    def __init__(self, workers: int, max_in_flight: int) -> None:
        self._workers = workers
        self._slots = threading.BoundedSemaphore(max_in_flight)
        self._lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._pending: set[Future] = set()

    def submit(self, task: Callable[[], Any]) -> Future | None:
        if not self._slots.acquire(blocking=False):
            return None
        try:
            with self._lock:
                if self._executor is None:
                    self._executor = ThreadPoolExecutor(max_workers=self._workers, thread_name_prefix="tutor-ledger")
                # The request's context (its logging fields) goes with the task.
                future = self._executor.submit(contextvars.copy_context().run, task)
                self._pending.add(future)
        except BaseException:
            self._slots.release()
            raise
        future.add_done_callback(self._finished)
        return future

    def _finished(self, future: Future) -> None:
        with self._lock:
            self._pending.discard(future)
        self._slots.release()

    def pending(self) -> int:
        with self._lock:
            return len(self._pending)

    def drain(self, timeout: float) -> bool:
        """Wait for every running or queued append (tests, and shutdown hooks); True when none is left."""
        with self._lock:
            pending = list(self._pending)
        done, not_done = wait(pending, timeout=timeout)
        return not not_done


LEGACY_WAIT_GRACE_MS = 250
LEGACY_APPEND_WORKERS = 4
LEGACY_APPEND_MAX_IN_FLIGHT = 16
LEGACY_APPENDS = _LegacyAppender(LEGACY_APPEND_WORKERS, LEGACY_APPEND_MAX_IN_FLIGHT)


def record_legacy_delivery(
    delivery: LegacyDelivery,
    *,
    settings: Settings | None = None,
    session_factory: Callable[[], Session] = SessionLocal,
) -> AppendedRecord | None:
    """Record a legacy delivery; never raises and never changes the learner's response (fail open, counted).

    The learner waits at most TUTOR_LEDGER_APPEND_BUDGET_MS + LEGACY_WAIT_GRACE_MS for the record, whatever the
    database does (spec conflict 29). None means the record was not confirmed in that time: it failed and was counted,
    or it is still being appended in the background and is counted when that ends.
    """
    try:
        settings = settings or get_settings()
        package = get_config_package(settings)
        entry = build_legacy_entry(delivery, settings=settings, package=package, manifest_sha256=delivery.manifest_sha256)
        budget_ms = settings.tutor_ledger_append_budget_ms
    except Exception as exc:  # noqa: BLE001 - a ledger fault must not change the learner's response
        record_ledger_failure("legacy", "append", exc)
        return None

    def append() -> AppendedRecord | None:
        try:
            appended = append_ledger_entry(entry, session_factory=session_factory, budget_ms=budget_ms)
        except Exception as exc:  # noqa: BLE001 - counted here, in the worker, whether or not the request still waits
            record_ledger_failure("legacy", "append", exc)
            return None
        LEDGER_METRICS.appended("legacy", duplicate=appended.duplicate)
        return appended

    try:
        future = LEGACY_APPENDS.submit(append)
    except Exception as exc:  # noqa: BLE001 - e.g. no thread could be started
        record_ledger_failure("legacy", "append", exc)
        return None
    if future is None:
        record_ledger_failure("legacy", "append", LedgerAppendError("too many ledger appends are already in flight"))
        return None
    try:
        return future.result(timeout=(budget_ms + LEGACY_WAIT_GRACE_MS) / 1000)
    except FutureTimeout:
        _log(logging.WARNING, "Tutor ledger append is still running; the response was not held for it", "tutor.ledger.append_deferred",
             delivery="legacy", budget_ms=budget_ms)
        return None
    except Exception as exc:  # noqa: BLE001 - append() never raises; this is a defence only
        record_ledger_failure("legacy", "append", exc)
        return None
