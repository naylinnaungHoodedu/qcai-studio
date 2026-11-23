"""The gold store (plan Phase 6 D task 3 "append-only gold store"; plan 7.4 "AuditEvent {prev_hash, hash, actor_role,
action, payload_digest} is append-only [Risk R-22]"; AC-6-4; Phase 6 spec 4.6).

v3_gold_labels holds one row per adjudication round: the canonical JSON of a GoldLabel (claim and span ids, claim-text
hashes, enumerations, keyed digests; never a learner identifier or learner text), its sha256 (the payload digest), the
previous row's record hash and its own:
    record_hash = sha256(canonical{chain "v3-gold", seq, created_at, prev_hash, entry_sha256})
the response ledger's rule over another chain, so an edited, removed, reordered or truncated row breaks the chain and
verify_gold_store names where. Database triggers refuse UPDATE, DELETE and TRUNCATE and an insert that does not extend
the chain (app.core.schema_upgrades); UNIQUE (item_id, review_round) refuses a second row for a round. On PostgreSQL an
append takes a transaction-scoped advisory lock first, so appends are linear; on SQLite writers are serialised. Every
append logs its seq and record hash after commit (v3.gold_appended, the off-database copy; the caller logs it). Rows are
written by adjudication only (queue.adjudicate): no import or restore path exists, and the export (export_gold, the
worker's export-gold) is the archive and the recalibration input Phase 7 consumes (DI-93).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import insert, select, text
from sqlalchemy.orm import Session

from app.services.tutor_pipeline.contracts import ledger_canonical, sha256_hex
from app.services.v3.contracts import GoldLabel
from app.services.v3.rules import GOLD_CHAIN, GOLD_GENESIS

V3_GOLD_LOCK_KEY = 7_401_207
_MAX_PROBLEMS = 50


@dataclass(frozen=True)
class GoldCheck:
    count: int
    head_seq: int | None
    head_hash: str | None
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def gold_hash_for(*, seq: int, created_at: datetime, prev_hash: str, entry_sha256: str) -> str:
    return sha256_hex(ledger_canonical({"chain": GOLD_CHAIN, "seq": int(seq), "created_at": _utc(created_at).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                                        "prev_hash": prev_hash, "entry_sha256": entry_sha256}))


def append_gold(db: Session, entry: GoldLabel, *, now: datetime) -> tuple[int, str]:
    """Append one gold row inside the caller's transaction; returns (seq, record_hash)."""
    from app.db_models import V3GoldLabelRecord

    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": V3_GOLD_LOCK_KEY})
    last = db.execute(select(V3GoldLabelRecord.seq, V3GoldLabelRecord.record_hash).order_by(V3GoldLabelRecord.seq.desc()).limit(1)).first()
    seq = int(last.seq) + 1 if last is not None else 1
    prev_hash = last.record_hash if last is not None else GOLD_GENESIS
    payload = ledger_canonical(entry.model_dump(mode="json"))
    digest = sha256_hex(payload)
    created_at = _utc(now)
    record_hash = gold_hash_for(seq=seq, created_at=created_at, prev_hash=prev_hash, entry_sha256=digest)
    db.execute(insert(V3GoldLabelRecord).values(
        seq=seq, item_id=entry.item_id, review_round=entry.review_round, actor_role="reviewer", action="adjudicate",
        reviewer_digest=entry.reviewer_digest, entry=payload.decode("utf-8"), entry_sha256=digest, prev_hash=prev_hash,
        record_hash=record_hash, created_at=created_at))
    return seq, record_hash


def verify_gold_store(db: Session, *, expected_head: tuple[int, str] | None = None) -> GoldCheck:
    from app.db_models import V3GoldLabelRecord

    problems: list[str] = []
    previous: tuple[int, str] | None = None
    count = 0
    reached = expected_head is None
    rows = db.execute(select(V3GoldLabelRecord).order_by(V3GoldLabelRecord.seq).execution_options(yield_per=500)).scalars()
    for row in rows:
        count += 1
        if previous is None:
            if row.seq != 1:
                problems.append(f"seq 1 to {row.seq - 1} missing")
            elif row.prev_hash != GOLD_GENESIS:
                problems.append("seq 1 does not start from the genesis hash")
        else:
            if row.seq != previous[0] + 1:
                problems.append(f"seq {previous[0] + 1} to {row.seq - 1} missing")
            if row.prev_hash != previous[1]:
                problems.append(f"seq {row.seq} does not chain onto seq {previous[0]}")
        raw = (row.entry or "").encode("utf-8")
        if sha256_hex(raw) != row.entry_sha256:
            problems.append(f"seq {row.seq} entry does not match its entry_sha256")
        if gold_hash_for(seq=row.seq, created_at=row.created_at, prev_hash=row.prev_hash, entry_sha256=row.entry_sha256) != row.record_hash:
            problems.append(f"seq {row.seq} does not match its record_hash")
        parsed: Any = None
        try:
            parsed = json.loads(row.entry)
            if ledger_canonical(parsed) != raw:
                problems.append(f"seq {row.seq} entry is not canonical JSON")
        except (TypeError, ValueError):
            problems.append(f"seq {row.seq} entry is not canonical JSON")
        if isinstance(parsed, dict):
            try:
                label = GoldLabel.model_validate(parsed)
                if (label.item_id, label.review_round, label.reviewer_digest) != (row.item_id, row.review_round, row.reviewer_digest):
                    problems.append(f"seq {row.seq} columns disagree with its entry")
            except ValidationError:
                problems.append(f"seq {row.seq} entry fails v3-gold-label-v1")
        if expected_head is not None and (row.seq, row.record_hash) == tuple(expected_head):
            reached = True
        previous = (row.seq, row.record_hash)
    if not reached:
        problems.append(f"the chain no longer reaches the logged head seq {expected_head[0]}")
    return GoldCheck(count=count, head_seq=previous[0] if previous else None, head_hash=previous[1] if previous else None,
                     problems=tuple(problems[:_MAX_PROBLEMS]))


def refused_export_roots(module: Path | None = None) -> tuple[Path, ...]:
    """The trees an export may not enter (plan L627-628: gold labels "MUST NOT enter the public repository, CI artifacts,
    logs or releases"): the application tree, and the repository checkout holding it (the first parent of this module
    with a .git entry; the image has none). `module` stands in for this file's path (a test seam)."""
    here = Path(module or __file__).resolve()
    roots = [here.parents[2]]
    checkout = next((parent for parent in here.parents if (parent / ".git").exists()), None)
    if checkout is not None:
        roots.append(checkout)
    return tuple(roots)


def export_gold(db: Session, path: Path, *, applied_only: bool = True) -> int:
    """One JSON line per row (seq, record_hash, entry, created_at): the applied items' final rows, or every row with
    applied_only False. The path must lie outside the application tree and the repository checkout
    (refused_export_roots); a refusal writes nothing. Returns the line count."""
    from app.db_models import V3GoldLabelRecord, V3QueueItem

    target = Path(path).resolve()
    if any(target.is_relative_to(root) for root in refused_export_roots()):
        raise ValueError("the export path must lie outside the application tree and the repository checkout")
    query = select(V3GoldLabelRecord).order_by(V3GoldLabelRecord.seq)
    if applied_only:
        finals = select(V3QueueItem.final_gold_seq).where(V3QueueItem.state == "applied", V3QueueItem.final_gold_seq.is_not(None))
        query = query.where(V3GoldLabelRecord.seq.in_(finals))
    count = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for row in db.execute(query).scalars():
            handle.write(json.dumps({"seq": row.seq, "record_hash": row.record_hash, "entry": json.loads(row.entry),
                                     "created_at": _utc(row.created_at).strftime("%Y-%m-%dT%H:%M:%S.%fZ")}, sort_keys=True) + "\n")
            count += 1
    return count
