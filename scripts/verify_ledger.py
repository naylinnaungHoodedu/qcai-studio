"""Verify the tutor response ledger (plan Phase 3 F: "ledger integrity script"; task 3.8; Phase 3 spec 7.16).

Run: python scripts/verify_ledger.py [--database-url URL] [--report PATH] [--expect-head SEQ:HASH]
                                     [--coverage-since ISO8601] [--export PATH.jsonl]

Read-only. It walks the whole hash chain (gaps, broken links, edited entries or columns, non-canonical entries,
schema failures, a missing or mismatched head) and, with --expect-head, checks that the chain still reaches a head
logged earlier off the database (a forged head over a truncated tail). --coverage-since reports tutor turns created
since then that have no ledger record (plan I "ledger writes 100% of deliveries"; report only), and counts the
/qa/ask records since then (a qa- record holds no link to its Q&A row, so Q&A coverage is the per-process
legacy_by_surface.qa.coverage_rate SLI, not a join). --export writes
every row as one JSON object per line to a path outside the repository: the step before an Alembic downgrade.
The database URL comes from --database-url, else DATABASE_URL, and is never printed.
Exit codes: 0 ok, 1 the chain is broken, 2 a usage or connection error.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

_AMBIENT_URL = os.environ.get("DATABASE_URL")
# Importing the app must not create or touch a database file; this script builds its own engine.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.config import normalize_sqlite_database_url  # noqa: E402
from app.db_models import ResponseLedgerRecord, TutorTurn  # noqa: E402
from app.services.ledger import parse_head, verify_response_ledger  # noqa: E402


def _inside_repository(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        return False
    return True


def _since(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def coverage(db, since: datetime) -> dict:
    recorded = select(ResponseLedgerRecord.response_id).where(ResponseLedgerRecord.response_id == TutorTurn.id).exists()
    turns = db.scalar(select(func.count()).select_from(TutorTurn).where(TutorTurn.created_at >= since)) or 0
    unrecorded = db.scalar(select(func.count()).select_from(TutorTurn).where(TutorTurn.created_at >= since, ~recorded)) or 0
    qa_records = db.scalar(
        select(func.count()).select_from(ResponseLedgerRecord).where(ResponseLedgerRecord.created_at >= since, ResponseLedgerRecord.response_id.like("qa-%"))
    ) or 0
    return {"since": since.isoformat(), "turns_since": int(turns), "unrecorded": int(unrecorded), "qa_records_since": int(qa_records)}


def export(db, path: Path) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in db.execute(select(ResponseLedgerRecord).order_by(ResponseLedgerRecord.seq)).scalars():
            handle.write(json.dumps({
                "seq": row.seq, "response_id": row.response_id, "delivery": row.delivery, "decision": row.decision,
                "shadowed_response_id": row.shadowed_response_id, "claim_set_hash": row.claim_set_hash,
                "entry_schema": row.entry_schema, "entry": row.entry, "entry_sha256": row.entry_sha256,
                "prev_hash": row.prev_hash, "record_hash": row.record_hash, "created_at": row.created_at.isoformat(),
            }, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--expect-head", default=None)
    parser.add_argument("--coverage-since", default=None)
    parser.add_argument("--export", type=Path, default=None)
    args = parser.parse_args(argv)
    url = args.database_url or _AMBIENT_URL
    if not url:
        print("verify_ledger: no database URL (pass --database-url or set DATABASE_URL)", file=sys.stderr)
        return 2
    if args.export is not None and _inside_repository(args.export):
        print("verify_ledger: --export must write outside the repository", file=sys.stderr)
        return 2
    try:
        expected = parse_head(args.expect_head)
        since = _since(args.coverage_since) if args.coverage_since else None
    except ValueError as exc:
        print(f"verify_ledger: {exc}", file=sys.stderr)
        return 2
    engine = create_engine(normalize_sqlite_database_url(url))
    try:
        with sessionmaker(bind=engine)() as db:
            check = verify_response_ledger(db, expected_head=expected)
            report = {
                "report": "qcai-response-ledger-check",
                "format_version": 1,
                "checked_at": datetime.now(UTC).isoformat(),
                "status": "ok" if check.ok else "broken",
                "records": check.count,
                "first_seq": check.first_seq,
                "last_seq": check.last_seq,
                "head_hash": check.head_hash,
                "head_row": list(check.head_row) if check.head_row else None,
                "expected_head": list(expected) if expected else None,
                "problems": list(check.problems),
            }
            if since is not None:
                report["coverage"] = coverage(db, since)
            if args.export is not None:
                report["exported"] = {"rows": export(db, args.export)}
    except SQLAlchemyError as exc:
        print(f"verify_ledger: database error ({type(exc).__name__})", file=sys.stderr)
        return 2
    finally:
        engine.dispose()
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.report is not None:
        args.report.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if check.ok else 1


if __name__ == "__main__":
    sys.exit(main())
