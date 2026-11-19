"""Verify the tutor response ledger's hash chain for a scheduled job (plan task 3.8, 7.5; Phase 3 spec 7.15).

Logs one JSON line with the record count, sequence range, head hash and head row, and exits. The head in the
platform logs is the copy kept outside the database (with each append's own `tutor.ledger.appended` line): a later
run whose chain does not reach an earlier logged head shows the history was rewritten (--expect-head SEQ:HASH).
A broken chain or a failure exits with status 1. Scheduling it daily is a cloud write (DI-33).

It runs in the API image and connects as the API does (the Cloud SQL Python connector when
CLOUD_SQL_CONNECTION_NAME is set), so the runbook's production checks need no workstation copy of scripts/
(spec 18.6 D12):
  --coverage-since ISO8601  also logs tutor turns since then that have no ledger record, and the qa- records since
                            then (counts only; plan I "ledger writes 100% of deliveries").
  --export PATH             also writes every record as one JSON object per line to PATH, which must lie outside
                            the application tree: the step before an Alembic downgrade. The file holds corpus text
                            and learner-linked ids; its handling rule is in infra/cloudrun/deployment.md.
  --restore PATH            first re-inserts an --export file into an empty ledger (after the downgrade was undone),
                            recomputing every hash, in one transaction, then verifies the chain as usual: with
                            --expect-head set to the export's last head, the restored chain must reach it
                            (spec 18.7 E12). A ledger that already holds records, or a line that does not extend
                            the chain, is refused and nothing is written.
Exit codes: 0 ok, 1 broken, failed or a refused restore, 2 a usage error.
Run as: python -m app.workers.response_ledger [--expect-head SEQ:HASH] [--coverage-since ISO8601] [--export PATH]
        [--restore PATH]
"""

import argparse
from datetime import UTC, datetime
from pathlib import Path
import sys
import time

from app.core.db import SessionLocal
from app.core.structured_logging import FIELDS
from app.services.ledger import LedgerRestoreRefused, export_ledger, ledger_coverage, parse_head, restore_ledger, verify_response_ledger
from app.workers.common import LOGGER

# The application tree: the repository in a checkout, /app in the image. An export never lands inside it.
APPLICATION_ROOT = Path(__file__).resolve().parents[2]


def _application_tree() -> Path:
    for candidate in (APPLICATION_ROOT, *APPLICATION_ROOT.parents):
        if (candidate / ".git").exists():
            return candidate
    return APPLICATION_ROOT


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _since(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--expect-head", default=None, help="a head logged earlier, SEQ:HASH, that the chain must still reach")
    parser.add_argument("--coverage-since", default=None, help="also count tutor turns since this time without a ledger record")
    parser.add_argument("--export", type=Path, default=None, help="also write every record as JSON lines to this path (outside the application tree)")
    parser.add_argument("--restore", type=Path, default=None, help="first re-insert an --export file into an empty ledger")
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        expected = parse_head(args.expect_head)
        since = _since(args.coverage_since) if args.coverage_since else None
    except ValueError as exc:
        LOGGER.error("Response ledger check refused its arguments", extra={FIELDS: {"job": "response_ledger", "status": "usage", "error": str(exc)}})
        return 2
    if args.export is not None and _inside(args.export, _application_tree()):
        LOGGER.error("Response ledger export refused", extra={FIELDS: {"job": "response_ledger", "status": "usage",
                                                                      "error": "--export must write outside the application tree"}})
        return 2
    if args.export is not None and args.restore is not None:
        LOGGER.error("Response ledger check refused its arguments", extra={FIELDS: {"job": "response_ledger", "status": "usage",
                                                                                   "error": "--export and --restore are separate steps"}})
        return 2
    extra: dict = {}
    try:
        if args.restore is not None:
            with SessionLocal() as db:
                rows, head = restore_ledger(db, args.restore)
            extra["restored"] = {"rows": rows, "head": f"{head[0]}:{head[1]}" if head else None}
    except LedgerRestoreRefused as exc:
        LOGGER.error("Response ledger restore refused", extra={FIELDS: {"job": "response_ledger", "status": "restore_refused", "error": str(exc)}})
        return 1
    except Exception:
        LOGGER.exception("Response ledger restore failed", extra={FIELDS: {"job": "response_ledger", "status": "failed"}})
        return 1
    try:
        with SessionLocal() as db:
            check = verify_response_ledger(db, expected_head=expected)
            if since is not None:
                extra["coverage"] = ledger_coverage(db, since)
            if args.export is not None:
                extra["exported"] = {"rows": export_ledger(db, args.export)}
    except Exception:
        LOGGER.exception("Response ledger check failed", extra={FIELDS: {"job": "response_ledger", "status": "failed"}})
        return 1
    fields = {
        "job": "response_ledger",
        "status": "ok" if check.ok else "broken",
        "records": check.count,
        "first_seq": check.first_seq,
        "last_seq": check.last_seq,
        "head_hash": check.head_hash,
        "head_row": list(check.head_row) if check.head_row else None,
        "appended_during_check": check.appended_during_check,
        "problems": list(check.problems),
        "duration_ms": round((time.monotonic() - started) * 1000),
        **extra,
    }
    if not check.ok:
        LOGGER.error("Response ledger chain is broken", extra={FIELDS: fields})
        return 1
    LOGGER.info("Response ledger chain verified", extra={FIELDS: fields})
    return 0


if __name__ == "__main__":
    sys.exit(main())
