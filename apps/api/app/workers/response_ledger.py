"""Verify the tutor response ledger's hash chain for a scheduled job (plan task 3.8, 7.5; Phase 3 spec 7.15).

Logs one JSON line with the record count, sequence range, head hash and head row, and exits. The head in the
platform logs is the copy kept outside the database (with each append's own `tutor.ledger.appended` line): a later
run whose chain does not reach an earlier logged head shows the history was rewritten (--expect-head SEQ:HASH).
A broken chain or a failure exits with status 1. Scheduling it daily is a cloud write (DI-33).
Run as: python -m app.workers.response_ledger [--expect-head SEQ:HASH]
"""

import argparse
import sys
import time

from app.core.db import SessionLocal
from app.core.structured_logging import FIELDS
from app.services.ledger import parse_head, verify_response_ledger
from app.workers.common import LOGGER


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-head", default=None, help="a head logged earlier, SEQ:HASH, that the chain must still reach")
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        expected = parse_head(args.expect_head)
        with SessionLocal() as db:
            check = verify_response_ledger(db, expected_head=expected)
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
        "problems": list(check.problems),
        "duration_ms": round((time.monotonic() - started) * 1000),
    }
    if not check.ok:
        LOGGER.error("Response ledger chain is broken", extra={FIELDS: fields})
        return 1
    LOGGER.info("Response ledger chain verified", extra={FIELDS: fields})
    return 0


if __name__ == "__main__":
    sys.exit(main())
