"""Verify the security event log's hash chain for a scheduled job (plan task 1.7).

Logs one JSON line with the event count, sequence range and head hash, and exits. The head hash in the
platform logs is the copy kept outside the database: a later run whose chain does not lead back to an
earlier logged head shows the history was rewritten. A broken chain or a failure exits with status 1.
Run as: python -m app.workers.security_log
"""

import sys
import time

from app.core.db import SessionLocal
from app.core.structured_logging import FIELDS
from app.services.security_log import verify_security_log
from app.workers.common import LOGGER


def main() -> int:
    started = time.monotonic()
    try:
        with SessionLocal() as db:
            check = verify_security_log(db)
    except Exception:
        LOGGER.exception("Security log check failed", extra={FIELDS: {"job": "security_log", "status": "failed"}})
        return 1
    fields = {
        "job": "security_log",
        "status": "ok" if check.ok else "broken",
        "events": check.count,
        "first_seq": check.first_seq,
        "last_seq": check.last_seq,
        "head_hash": check.head_hash,
        "problems": list(check.problems),
        "duration_ms": round((time.monotonic() - started) * 1000),
    }
    if not check.ok:
        LOGGER.error("Security log chain is broken", extra={FIELDS: fields})
        return 1
    LOGGER.info("Security log chain verified", extra={FIELDS: fields})
    return 0


if __name__ == "__main__":
    sys.exit(main())
